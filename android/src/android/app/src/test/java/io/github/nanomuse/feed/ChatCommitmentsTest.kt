package io.github.nanomuse.feed

import com.openminis.app.data.model.LLMModel
import com.openminis.app.provider.openai.OpenAIProvider
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import io.github.nanomuse.feed.FeedPreparation.Fact
import io.github.nanomuse.feed.FeedPreparation.Kind
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.time.LocalDate
import java.time.ZoneOffset

class ChatCommitmentsTest {
    private val today = LocalDate.of(2026, 11, 23)
    private fun line(text: String, id: String = "new", person: Boolean = true, days: Long = 0) =
        ChatCommitments.Line("local-chat", id, person, false, text,
            today.plusDays(days).atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli())
    private val english = line("I promised to email the museum tomorrow to arrange a visit.")
    private val chinese = line("我答应明天联系博物馆预约参观。")
    private val preference = Fact(Kind.MEMORY, "USER.md", "USER.md",
        "For museum visits we need a step-free entrance.")
    private fun facts(vararg lines: ChatCommitments.Line) =
        ChatCommitments.facts(lines.toList(), today, "Chat", ZoneOffset.UTC)

    @Test fun personalCommitmentFeedsOnlyItsOwnEvidenceAndIndependentPreference() {
        val input = facts(line("Some unrelated private sentence", id = "other"), english)
        val pairs = FeedPreparation.candidates(input + preference)
        val data = JSONObject(FeedPreparation.input(pairs.single(), "", "en"))
        assertEquals("draft", data.getString("form"))
        assertEquals(2, data.getJSONArray("records").length())
        assertTrue(data.toString().contains("2026-11-24"))
        assertFalse(data.toString().contains("private sentence"))
        assertFalse(data.toString().contains("local-chat"))
        val draft = FeedPreparation.draft(JSONObject().put("draft",
            "Hello, does the museum have a step-free entrance for our visit?").toString(), pairs)!!
        assertTrue(draft.chatBased)
        assertNull(FeedPreparation.draft(JSONObject().put("draft",
            "Hello, could I arrange a museum visit?").toString(), pairs))
        assertTrue(draft.source.contains("Chat · ${english.text}"))
        assertEquals(listOf(FeedPreparation.hash("local-chat")), draft.sourceSessions)
        assertTrue(FeedPreparation.revalidate(pairs, input).isEmpty())
        assertTrue(FeedPreparation.revalidate(pairs, listOf(preference)).isEmpty())
        val same = facts(english.copy(id = "other"))
        assertTrue(FeedPreparation.candidates(input + same).isEmpty())
        assertTrue(FeedPreparation.candidates(input + preference.copy(text = "Hiking permits require paper copies.")).isEmpty())
        val zh = FeedPreparation.candidates(facts(chinese) + preference.copy(text = "去博物馆参观时我需要无台阶入口。"))
        assertEquals("draft", JSONObject(FeedPreparation.input(zh.single(), "", "zh")).getString("form"))
    }

    @Test fun writerReceivesNoConversationOrToolsAndRechecksBeforeShowingReply() = runBlocking {
        MockWebServer().use { http ->
            http.start()
            val model = OpenAIProvider(apiKey = "unused", model = LLMModel.gpt4oMini,
                basePath = http.url("/").toString().trimEnd('/'))
            val local = facts(chinese, line("unrelated conversation", "other"))
            val choice = preference.copy(text = "去博物馆参观时我需要无台阶入口。")
            val pair = FeedPreparation.unseen(local + choice, emptySet()) { false }
            val draft = JSONObject().put("draft", "您好，我想预约参观博物馆。请问有无台阶入口吗？")
            val json = JSONObject.quote(draft.toString())
            val delta = """{"choices":[{"delta":{"role":"assistant","content":$json}}]}"""
            val stop = """{"choices":[{"delta":{},"finish_reason":"stop"}]}"""
            http.enqueue(MockResponse().setHeader("Content-Type", "text/event-stream")
                .setBody("data: $delta\n\ndata: $stop\n\ndata: [DONE]\n\n"))
            val result = FeedPreparation.request(model, pair, "", "zh")
            val wire = JSONObject(http.takeRequest().body.readUtf8())
            assertFalse(wire.has("tools"))
            val records = wire.getJSONArray("messages").getJSONObject(1).getString("content")
            assertTrue(records.contains(chinese.text))
            assertFalse(records.contains("unrelated conversation"))
            val saved = FeedPreparation.draft(result, FeedPreparation.revalidate(pair, local + choice))!!
            assertTrue(saved.chatBased)
            val now = facts(chinese, line("博物馆预约已取消。", "later")) + choice
            assertNull(FeedPreparation.draft(result, FeedPreparation.revalidate(pair, now)))
            val after = FeedPreparation.unseen(now, emptySet()) { false }
            assertEquals("[quiet]", FeedPreparation.request(model, after, "", "zh"))
            assertEquals(1, http.requestCount)
        }
    }

    @Test fun supersededDeadlineRetiresOldCardAndShowsCurrentDate() {
        val old = FeedPreparation.candidates(facts(english) + preference)
        val moved = line("The museum visit moved to Friday.", "update")
        val updated = facts(english, moved) + preference
        val fresh = FeedPreparation.candidates(updated).single()
        assertTrue(FeedPreparation.revalidate(old, updated).isEmpty())
        assertNotEquals(old.single().id, fresh.id)
        assertTrue(FeedPreparation.input(fresh, "", "en").contains("2026-11-27"))
        val answer = JSONObject().put("draft", "Hello, can the museum accommodate a step-free visit?")
        assertTrue(FeedPreparation.draft(answer.toString(), listOf(fresh))!!.source.any { it.contains(moved.text) })
        assertNull(FeedPreparation.draft(answer.put("draft", "Hello, can we visit the museum on 2026-11-24?").toString(), listOf(fresh)))
        assertTrue(facts(chinese, line("改到周五。", "update")).single().dueOn.endsWith("11-27"))
        assertTrue(facts(english, line("Museum visit postponed indefinitely.", "later")).isEmpty())
    }

    @Test fun onlyCurrentConsentedRequestsSurviveLaterCompletionOrPreparedAnswers() {
        assertTrue(facts(english.copy(person = false)).isEmpty())
        assertTrue(facts(line("Someone said they will email the museum tomorrow.")).isEmpty())
        assertTrue(facts(line("If I need to email the museum tomorrow, what should I say?")).isEmpty())
        assertTrue(facts(line(english.text, days = -3)).isEmpty())
        assertTrue(facts(chinese, line("我已经联系博物馆，预约好了。", "done")).isEmpty())
        assertTrue(facts(english, line("I already emailed the museum.", "done")).isEmpty())
        assertTrue(facts(english, line("I already emailed the observatory.", "other")).isNotEmpty())
        val answer = line("Subject: Museum visit\nDear museum team, is step-free access available?", "reply", false).copy(assistant = true)
        assertTrue(facts(english, answer).isEmpty())
        assertTrue(facts(english, line("Can you draft it for me?", "ask"), answer).isEmpty())
        assertFalse(ChatCommitments.relevant("I like museums."))
        assertTrue(ChatCommitments.relevant(english.text))
        assertTrue(facts(english, answer.copy(text = "I can help with that museum visit.")).isNotEmpty())
    }

    @Test fun explicitNextWeekAndAmbiguousOrUnfinishedUpdates() {
        val tuesday = LocalDate.of(2026, 11, 24)
        assertEquals(tuesday.plusDays(10), ChatCommitments.latestDay("下周五提交论文", tuesday))
        assertNull(ChatCommitments.latestDay("周三或周五提交论文", tuesday))
        assertTrue(facts(line("我答应周三或周五联系博物馆。")).isEmpty())
        assertTrue(facts(english, line("I have not yet sent the museum request.", "pending")).isNotEmpty())
        assertTrue(facts(chinese, line("博物馆的说明我还没提交，也还没发。", "pending")).isNotEmpty())
        assertTrue(facts(line("我不想联系博物馆。")).isEmpty())
    }

    @Test fun skipAttachmentsPastedDocumentsAndToolResults() {
        val part = JSONObject().put("type", "text").put("value", english.text)
        assertEquals(english.text, ChatCommitments.plain(JSONArray().put(part).toString(), true))
        assertEquals("", ChatCommitments.plain(JSONArray().put(part).put(JSONObject().put("type", "mediaRef")).toString(), true))
        assertEquals("", ChatCommitments.plain(JSONArray().put(part.put("type", "toolResult")).toString(), true))
        assertEquals("", ChatCommitments.plain(JSONArray().put(part.put("type", "text").put("value", "Pasted content\n${english.text}")).toString(), true))
    }
}
