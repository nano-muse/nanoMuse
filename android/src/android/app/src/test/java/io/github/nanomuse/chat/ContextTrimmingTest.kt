package io.github.nanomuse.chat

import com.openminis.app.data.model.AgentContentPart
import com.openminis.app.data.model.LLMMessage
import java.io.IOException
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.test.runTest
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class ContextTrimmingTest {
    private fun user(text: String) = LLMMessage(LLMMessage.Role.USER, text)

    private fun round(
        id: String,
        output: String = "done",
        input: JSONObject = JSONObject().put("path", "$id.txt"),
        reasoning: String = "reasoning for $id",
    ) = listOf(
        LLMMessage(LLMMessage.Role.ASSISTANT, "", contentParts = listOf(
            AgentContentPart.ToolUse(id, "file_read", input),
        ), reasoningContent = reasoning),
        LLMMessage(LLMMessage.Role.USER, "", contentParts = listOf(
            AgentContentPart.ToolResult(id, "file_read", output),
        )),
    )

    private fun measure(messages: List<LLMMessage>) = ContextEstimate.request(messages)

    private fun pairs(messages: List<LLMMessage>): Pair<List<String>, List<String>> {
        val parts = messages.flatMap { it.contentParts }
        return parts.filterIsInstance<AgentContentPart.ToolUse>().map { it.id } to
            parts.filterIsInstance<AgentContentPart.ToolResult>().map { it.id }
    }

    @Test
    fun `a request that fits incurs no writes and keeps its objects`() = runTest {
        val history = listOf(user("current question")) + round("read", "large".repeat(1_000))
        val result = ContextTrimming.trim(history, measure(history), ::measure, {
            error("a fitting request must not write to disk")
        })
        assertSame(history, result.messages)
        assertTrue(result.edits.isEmpty())
        assertTrue(result.reachedTarget)
    }

    @Test
    fun `old reasoning is sufficient without any offload and recent thinking stays intact`() = runTest {
        val old = round("old", reasoning = "thinking".repeat(2_000))
        val recent = round("one") + round("two") + round("three")
        val history = listOf(user("finish the current task")) + old + recent
        val result = ContextTrimming.trim(history, measure(history) - 1_000, ::measure, {
            error("clearing old reasoning already frees enough")
        })
        assertEquals(listOf("reasoning"), result.steps)
        assertEquals("", result.messages[1].reasoningContent)
        assertEquals("thinking".repeat(2_000), history[1].reasoningContent)
        recent.forEachIndexed { index, message -> assertSame(message, result.messages[index + 3]) }
        assertTrue(result.reachedTarget)
    }

    @Test
    fun `large earlier result is recoverable and the last three tool iterations stay verbatim`() = runTest {
        val original = "搜索结果中的价格与型号".repeat(1_000)
        val recent = round("one", original) + round("two", original) + round("three", original)
        val history = listOf(user("找出手机的价格")) + round("old", original) + recent
        val writes = mutableListOf<ContextTrimming.Spill>()
        val result = ContextTrimming.trim(history, 0, ::measure, {
            writes += it
            "/var/minis/offloads/${it.key}.txt"
        })
        assertEquals(1, writes.size)
        assertEquals(original, writes.single().content)
        assertEquals(ContextTrimming.Kind.RESULT, writes.single().kind)
        val replacement = result.messages[2].contentParts.single() as AgentContentPart.ToolResult
        assertTrue(replacement.content.contains(writes.single().key))
        assertEquals(original, (history[2].contentParts.single() as AgentContentPart.ToolResult).content)
        assertSame(history[0], result.messages[0])
        recent.forEachIndexed { index, message -> assertSame(message, result.messages[index + 3]) }
        assertEquals(pairs(history), pairs(result.messages))
        assertFalse(result.reachedTarget)
    }

    @Test
    fun `offloading a write argument preserves original JSON and call result pairing`() = runTest {
        val original = "actual source code\n".repeat(1_000)
        val input = JSONObject().put("path", "draft.txt").put("content", original)
        val history = listOf(user("edit the file")) + round("write", input = input) + round("latest")
        val writes = mutableListOf<ContextTrimming.Spill>()
        val result = ContextTrimming.trim(history, 0, ::measure, {
            writes += it
            "/var/minis/offloads/arguments.json"
        }, ContextTrimming.Options(stripReasoning = false, keepRecentIterations = 1))
        val call = result.messages[1].contentParts.single() as AgentContentPart.ToolUse
        assertEquals(original, input.getString("content"))
        assertEquals("draft.txt", call.input.getString("path"))
        assertTrue(call.input.getString("content").contains("not the original argument"))
        assertEquals(original, JSONObject(writes.single().content).getString("content"))
        assertEquals(pairs(history), pairs(result.messages))
    }

    @Test
    fun `failed writes leave payloads intact even when whole step collapse is allowed`() = runTest {
        val history = listOf(user("keep the evidence")) +
            round("old", "original evidence".repeat(1_000)) + round("latest")
        for (throws in listOf(false, true)) {
            val result = ContextTrimming.trim(history, 0, ::measure, {
                if (throws) throw IOException("disk unavailable") else null
            }, ContextTrimming.Options(stripReasoning = false, keepRecentIterations = 1, allowCollapse = true))
            assertSame(history, result.messages)
            assertTrue(result.edits.isEmpty())
        }
    }

    @Test
    fun `cancelling an offload stops maintenance immediately`() = runTest {
        val history = round("old", "evidence".repeat(1_000)) + round("latest")
        var cancelled = false
        try {
            ContextTrimming.trim(history, 0, ::measure, {
                throw CancellationException("cancelled by caller")
            }, ContextTrimming.Options(keepRecentIterations = 1))
        } catch (_: CancellationException) {
            cancelled = true
        }
        assertTrue(cancelled)
    }

    @Test
    fun `a reference that increases measured size is rejected`() = runTest {
        val history = round("old", "small".repeat(100)) + round("latest")
        val result = ContextTrimming.trim(history, 0, ::measure, {
            "/var/minis/" + "very-long-path".repeat(1_000)
        }, ContextTrimming.Options(stripReasoning = false, keepRecentIterations = 1))
        assertSame(history, result.messages)
        assertEquals(result.beforeTokens, result.afterTokens)
    }

    @Test
    fun `unanswered duplicate and signed tool calls cannot be changed`() = runTest {
        val large = "important payload".repeat(1_000)
        val dangling = round("pending", large).take(1)
        val duplicates = round("duplicate", large) + round("duplicate", large)
        val signed = round("signed", large).toMutableList()
        val call = signed[0].contentParts.single() as AgentContentPart.ToolUse
        signed[0] = signed[0].copy(contentParts = listOf(call.copy(thoughtSignature = "opaque")))
        val history = dangling + duplicates + signed + round("latest")
        val result = ContextTrimming.trim(history, 0, ::measure, {
            error("incomplete, ambiguous or signed calls must not be changed")
        }, ContextTrimming.Options(keepRecentIterations = 1, allowCollapse = true))
        assertSame(history, result.messages)
    }

    @Test
    fun `parallel results with user text or attachments preserve every non-tool part`() = runTest {
        val large = "output".repeat(1_000)
        val first = round("a", large)
        val second = round("b", large)
        val image = LLMMessage.ImagePart(byteArrayOf(1, 2), "image/png")
        val carrier = first[1].copy(
            content = "用户补充说明",
            contentParts = first[1].contentParts + AgentContentPart.Text("用户补充说明"),
            imageParts = listOf(image),
        )
        val history = listOf(
            user("current question"),
            first[0].copy(contentParts = first[0].contentParts + second[0].contentParts),
            carrier, second[1],
        ) + round("latest")
        val result = ContextTrimming.trim(history, 0, ::measure, {
            assertNotEquals(ContextTrimming.Kind.STEP, it.kind)
            "/var/minis/offloads/${it.key}.txt"
        }, ContextTrimming.Options(keepRecentIterations = 1, allowCollapse = true))
        assertEquals(pairs(history), pairs(result.messages))
        assertEquals("用户补充说明", result.messages[2].content)
        assertTrue(result.messages[2].contentParts.contains(AgentContentPart.Text("用户补充说明")))
        assertSame(image, result.messages[2].imageParts.single())
    }

    @Test
    fun `whole step archive keeps original calls and removes both sides of each pair`() = runTest {
        val old = round("old", "old result".repeat(500), reasoning = "original reasoning")
        val history = listOf(user("original user request")) + old + round("latest")
        var archive: String? = null
        val result = ContextTrimming.trim(history, 0, ::measure, {
            if (it.kind == ContextTrimming.Kind.STEP) {
                archive = it.content
                "/var/minis/offloads/step.json"
            } else null
        }, ContextTrimming.Options(keepRecentIterations = 1, allowCollapse = true))
        assertTrue(result.steps.contains("steps"))
        assertSame(history[0], result.messages[0])
        assertEquals(listOf("latest") to listOf("latest"), pairs(result.messages))
        assertEquals(1, result.edits.count { it.replacement == null })
        val archived = JSONObject(archive!!).getJSONArray("messages")
        assertEquals("original reasoning", archived.getJSONObject(0).getString("reasoning"))
        assertEquals("old result".repeat(500), archived.getJSONObject(1)
            .getJSONArray("parts").getJSONObject(0).getString("content"))
        assertEquals("original reasoning", old[0].reasoningContent)
    }

    @Test
    fun `same source produces stable spill keys but reused ids with different payloads do not`() = runTest {
        suspend fun key(output: String): String {
            var key = ""
            ContextTrimming.trim(round("same", output) + round("latest"), 0, ::measure, {
                key = it.key
                "/var/minis/offloads/$key.txt"
            }, ContextTrimming.Options(stripReasoning = false, keepRecentIterations = 1))
            return key
        }
        val first = key("first".repeat(1_000))
        assertEquals(first, key("first".repeat(1_000)))
        assertNotEquals(first, key("second".repeat(1_000)))
    }

    @Test
    fun `one giant latest completed result can recover without losing its call or reasoning`() = runTest {
        val original = "FIRST EVIDENCE\n" + "large output\n".repeat(4_000) + "\nFINAL EVIDENCE"
        val history = listOf(user("answer the original question")) +
            round("latest", original, reasoning = "reasoning still required by the provider")
        val writes = mutableListOf<ContextTrimming.Spill>()
        val result = ContextTrimming.trim(history, 4_000, ::measure, {
            writes += it
            "/var/minis/offloads/latest.txt"
        }, ContextTrimming.Options(allowCollapse = true, allowOversizedLatestResult = true))
        assertTrue(result.reachedTarget)
        assertEquals(listOf("latest-result"), result.steps)
        assertSame(history[0], result.messages[0])
        assertSame(history[1], result.messages[1])
        assertEquals(pairs(history), pairs(result.messages))
        val output = (result.messages[2].contentParts.single() as AgentContentPart.ToolResult).content
        assertTrue(output.contains("FIRST EVIDENCE"))
        assertTrue(output.contains("FINAL EVIDENCE"))
        assertTrue(output.contains("/var/minis/offloads/latest.txt"))
        assertEquals(original, writes.single().content)
        assertEquals(original, (history[2].contentParts.single() as AgentContentPart.ToolResult).content)
    }

    @Test
    fun `latest result remains verbatim when spill fails or hard recovery is disabled`() = runTest {
        val history = listOf(user("retain all evidence")) + round("latest", "original".repeat(6_000))
        val failed = ContextTrimming.trim(history, 4_000, ::measure, { null },
            ContextTrimming.Options(allowOversizedLatestResult = true))
        assertSame(history, failed.messages)
        val disabled = ContextTrimming.trim(history, 4_000, ::measure, {
            error("recent results stay protected outside hard recovery")
        })
        assertSame(history, disabled.messages)
    }

    @Test
    fun `hard recovery does not replace a small recent result or drop its image`() = runTest {
        val recent = round("latest", "short result")
        val image = byteArrayOf(1, 2, 3)
        val result = recent[1].contentParts.single() as AgentContentPart.ToolResult
        val history = listOf(user("large user text".repeat(4_000)), recent[0],
            recent[1].copy(contentParts = listOf(result.copy(imageData = image, imageMimeType = "image/png"))))
        val trimmed = ContextTrimming.trim(history, 1_000, ::measure, {
            error("a user attachment or short result is not an oversized tool body")
        }, ContextTrimming.Options(allowCollapse = true, allowOversizedLatestResult = true))
        assertSame(history, trimmed.messages)
        assertSame(image, (trimmed.messages.last().contentParts.single() as AgentContentPart.ToolResult).imageData)
    }
}
