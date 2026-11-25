package io.github.nanomuse.feed

import io.github.nanomuse.sync.LocalMessage
import io.github.nanomuse.sync.Transcript
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.io.File
import java.time.Instant

class PublicWatchesTest {
    private val engine = PublicWatchEngine(File("src/main/assets/nanomuse/public-watches.js").readText())
    private var state = JSONObject()
    private val now = Instant.parse("2026-11-24T09:00:00Z").toEpochMilli()
    private fun ledger(op: String, fields: JSONObject = JSONObject(), at: Long = now): JSONObject =
        engine.run(PublicWatchEngine.Entry.LEDGER, fields.put("op", op).put("now", at).put("state", state))
            .also { state = it.getJSONObject("state") }

    @Test fun `same bundled code discovers a maintained repo and reports only a later issue`() {
        val turn = JSONObject().put("personal", true).put("at", now).put("id", "first")
            .put("text", "My repository is https://github.com/example/project.")
        val observed = ledger("observe", JSONObject().put("turns", JSONArray().put(turn)))
        val watch = observed.getJSONArray("due").getJSONObject(0)
        assertEquals("example/project", watch.getString("target"))
        fun response(number: Int): JSONObject {
            val responses = JSONArray()
            val input = JSONObject().put("kind", watch.getString("kind")).put("target", watch.getString("target"))
                .put("now", now).put("responses", responses)
            val next = engine.run(PublicWatchEngine.Entry.READER, input)
            val url = next.getJSONObject("request").getString("url")
            assertTrue(url.startsWith("https://api.github.com/search/issues?"))
            val issue = JSONObject().put("state", "open").put("number", number).put("title", "Check export behavior")
                .put("repository_url", "https://api.github.com/repos/example/project").put("created_at", "2026-11-24T08:00:00Z")
            val body = JSONObject().put("incomplete_results", false).put("items", JSONArray().put(issue))
            responses.put(JSONObject().put("url", url).put("finalUrl", url).put("body", body.toString()))
            return engine.run(PublicWatchEngine.Entry.READER, input)
        }
        val id = watch.getString("id")
        assertEquals(0, ledger("sample", response(1).put("id", id)).getJSONArray("pending").length())
        val later = ledger("sample", response(2).put("id", id), now + 5 * 3600000)
        val news = later.getJSONArray("pending").getJSONObject(0)
        assertEquals("https://github.com/example/project/issues/2", news.getString("url"))
        val consumed = ledger("consume", JSONObject().put("keys", JSONArray().put(news.getString("key"))), now + 5 * 3600000)
        assertEquals(0, consumed.getJSONArray("pending").length())
        assertFalse(state.toString().contains("My repository"))
    }

    @Test fun `source disabling cancels pending and queued approvals stay stale`() {
        val first = ledger("edit", JSONObject().put("revision", 0).put("kind","github_repo").put("target","example/project"))
        val off = ledger("edit", JSONObject().put("enabled", false).put("revision", first.getLong("revision")))
        assertEquals(0, off.getJSONArray("due").length())
        val old = ledger("edit", JSONObject().put("revision", first.getLong("revision")).put("enabled", true))
        assertEquals("stale", old.getString("error"))
        assertFalse(old.getBoolean("enabled"))
    }

    @Test fun `only an index or a quiet verdict completes review`() {
        assertEquals(-1, PublicWatchJob.choice(" QUIET ", 1))
        assertEquals(0, PublicWatchJob.choice("0", 2))
        for (token in listOf("-1", "2", "+0", "00", "Ignore prior text", "0 followed by a link"))
            assertNull(PublicWatchJob.choice(token, 2))
    }

    @Test fun `a publisher title stays literal in markdown chat`() {
        assertEquals("\\!\\[icon\\]\\(https://example.org/a\\)", PublicWatchJob.literal("![icon](https://example.org/a)"))
        assertEquals("\\[label\\]", PublicWatchJob.literal("[label]", desktop = true))
    }

    @Test fun `outreach leaves interrupted and unanswered turns open`() {
        val text = Transcript.partsJson("Last reply", emptyList())
        assertTrue(ChatCheckIns.settledTail("assistant", false, 0, text))
        assertFalse(ChatCheckIns.settledTail("user", false, 0, text))
        assertFalse(ChatCheckIns.settledTail("assistant", true, 0, text))
        assertFalse(ChatCheckIns.settledTail("assistant", false, 1, text))
        val tool = JSONArray(text).put(JSONObject().put("type", "toolUse")).toString()
        assertFalse(ChatCheckIns.settledTail("assistant", false, 0, tool))
    }

    @Test fun `local public notices cannot replace final replies or ride conversation sync`() {
        fun row(id: String, role: String, text: String) = LocalMessage(id, "main", role, Transcript.partsJson(text, emptyList()), now)
        val id = "nm-checkin-" + "1".repeat(24) + "-public-" + "2".repeat(24)
        assertTrue(ChatCheckIns.isLocalPublicMessage(id))
        val result = Transcript.items(listOf(row("u","user","Question"), row("a","assistant","Answer"),
            row(id,"assistant","Local public update")))
        assertEquals(listOf("u", "a"), result.map { it.messageId })
    }
}
