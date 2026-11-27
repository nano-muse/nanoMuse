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
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class FeedPreparationTest {
    @get:Rule val folder = TemporaryFolder()
    private val source = "source-chat"
    private val goal = Fact(Kind.GOAL, "goal/orchard", "Orchard launch", "Orchard launch; request the totals",
        setOf(FeedPreparation.hash(source)), priority = 3, goalId = "orchard")
    private val diary = Fact(Kind.DIARY, "2026-11-23.md", "2026-11-23.md", "Orchard supplier still owes the totals")
    private val facts = listOf(goal, diary)
    private val pair = FeedPreparation.candidates(facts).single()

    private fun reply() = JSONObject().put("title", "Orchard follow-up")
        .put("draft", "Could you send the outstanding Orchard totals so I can finish the launch checklist?")
        .put("pair", pair.id)

    @Test fun offeredFactsBecomeUsableDraftWithVerifiedReceiptsAndOriginalGoal() {
        val offered = FeedPreparation.unseen(facts, emptySet()) { false }
        val prompt = JSONObject(FeedPreparation.input(offered.single(), "Short drafts", "en"))
        assertEquals("draft", prompt.getString("form"))
        assertEquals(2, prompt.getJSONArray("records").length())
        assertFalse(prompt.toString().contains(source))
        val draft = FeedPreparation.draft(reply().toString(), offered)!!
        assertEquals(pair.id, draft.preparation)
        assertEquals("orchard", draft.goalId)
        assertTrue(draft.source.contains("Orchard launch · Orchard launch; request the totals"))
        assertEquals(listOf(FeedPreparation.hash(source)), draft.sourceSessions)

        val file = folder.newFolder("2026-11-23").resolve("01.md")
        val post = FeedPost("2026-11-23", 1, draft.title, draft.type, "", draft.body, draft.source,
            0L, false, file, draft.preparation, draft.goalId, draft.sourceSessions)
        file.writeText(post.serialize())
        val saved = FeedPost.parse(file)!!
        assertEquals(post, saved)
        assertTrue(saved.visibleWith(setOf("another chat")))
        assertFalse(saved.visibleWith(setOf(source)))
        file.writeText("---\nsource: original; second\n---\n\nA historical card.")
        assertEquals(listOf("original", "second"), FeedPost.parse(file)!!.source)
        assertTrue(FeedPost.parse(file)!!.visibleWith(setOf(source)))
    }

    @Test fun providerReceivesOnlyEvidenceWithNoToolsAndNoRequestForAnEmptyDay() = runBlocking {
        MockWebServer().use { server ->
            server.start()
            val provider = OpenAIProvider(apiKey = "unused", model = LLMModel.gpt4oMini, basePath = server.url("/").toString().trimEnd('/'))
            assertEquals("[quiet]", FeedPreparation.request(provider, emptyList(), "", "en"))
            assertEquals(0, server.requestCount)
            val delta = JSONObject.quote(reply().toString())
            val event = """{"choices":[{"delta":{"role":"assistant","content":$delta}}]}"""
            val stop = """{"choices":[{"delta":{},"finish_reason":"stop"}]}"""
            server.enqueue(MockResponse().setHeader("Content-Type", "text/event-stream")
                .setBody("data: $event\n\ndata: $stop\n\ndata: [DONE]\n\n"))
            val result = FeedPreparation.request(provider, listOf(pair), "Short drafts", "en")
            assertNotNull(FeedPreparation.draft(result, listOf(pair)))
            val wire = JSONObject(server.takeRequest().body.readUtf8())
            assertFalse(wire.has("tools"))
            val messages = wire.getJSONArray("messages")
            assertEquals(2, messages.length())
            val payload = messages.getJSONObject(1).getString("content")
            assertEquals("draft", JSONObject(payload).getString("form"))
            assertFalse(payload.contains("2026-11-23"))
            assertFalse(payload.contains(source))
            assertEquals(1, server.requestCount)
        }
    }

    @Test fun noSpendOnUnrelatedStaticReplicatedOrGenericNotes() {
        assertTrue(FeedPreparation.candidates(listOf(goal, diary.copy(text = "Glacier measurements arrived"))).isEmpty())
        assertTrue(FeedPreparation.candidates(listOf(goal, goal.copy(location = "goal/2", text = "Orchard budget"))).isEmpty())
        assertTrue(FeedPreparation.candidates(listOf(goal.copy(timely = false), diary.copy(kind = Kind.MEMORY, timely = false))).isEmpty())
        assertTrue(FeedPreparation.candidates(listOf(diary, diary.copy(location = "USER.md"))).isEmpty())
        assertTrue(FeedPreparation.candidates(listOf(goal.copy(text = "Check the project tomorrow"),
            diary.copy(text = "Check the meeting tomorrow"))).isEmpty())
        assertEquals(1, FeedPreparation.candidates(listOf(goal.copy(text = "星桥发布评审"), diary.copy(text = "星桥发布前还要确认报价"))).size)
    }

    @Test fun upcomingCommitmentAndRealPreferenceCanPrepareWithoutFormalGoal() {
        val visit = diary.copy(text = "Tomorrow I visit the Orchard supplier to discuss costing.")
        val preference = Fact(Kind.MEMORY, "USER.md", "USER.md", "For Orchard supplier visits I prefer a printed comparison.")
        val offered = FeedPreparation.unseen(listOf(visit, preference), emptySet()) { false }
        val result = offered.single()
        val ready = reply().put("pair", result.id).put("title", "Orchard visit checklist")
            .also { it.remove("draft") }.put("checklist", JSONArray(listOf("Print the Orchard costing comparison", "Leave space beside each supplier cost")))
        val prepared = FeedPreparation.draft(ready.toString(), offered)!!
        assertEquals("", prepared.goalId)
        assertEquals(2, prepared.source.size)
        fun checkQuiet(vararg notes: Fact) =
            assertTrue(FeedPreparation.candidates(listOf(preference, *notes)).isEmpty())
        checkQuiet(visit.copy(text = "The Orchard supplier served a nice lunch."))
        checkQuiet(visit.copy(text = "Tomorrow I visit the Glacier observatory."))
        checkQuiet(visit, visit.copy(location = "2026-11-24.md", text = "The Orchard supplier visit was cancelled."))
        val olderCancellation = visit.copy(location = "2026-11-22.md", text = "The Orchard supplier visit was cancelled.")
        assertEquals(1, FeedPreparation.candidates(listOf(preference, visit, olderCancellation)).size)
        val chineseVisit = diary.copy(text = "明天去星桥工厂参观展厅")
        val checklist = preference.copy(text = "去星桥工厂要带纸质清单")
        assertEquals(1, FeedPreparation.candidates(listOf(chineseVisit, checklist)).size)
        assertTrue(FeedPreparation.candidates(listOf(chineseVisit, checklist,
            diary.copy(location = "2026-11-24.md", text = "星桥工厂参观已取消"))).isEmpty())
    }

    @Test fun suppressFabricatedSourceUnsupportedClaimAndUngroundedQuote() {
        fun rejects(reply: String) = assertNull(FeedPreparation.draft(reply, listOf(pair)))
        assertNotNull(FeedPreparation.draft(reply().also { it.remove("pair"); it.remove("title") }.toString(), listOf(pair)))
        assertNull(FeedPreparation.draft(reply().also { it.remove("pair") }.toString(), emptyList()))
        assertTrue(FeedPreparation.candidates(listOf(goal.copy(text = "Decide the layout for the Mercury sculpture exhibit."),
            diary.copy(text = "On my way home I heard a song by Freddie Mercury."))).isEmpty())
        rejects("[quiet]")
        rejects(reply().put("pair", "not-on-this-device").toString())
        rejects(reply().put("quotes", JSONArray(listOf("Orchard fabricated", pair.right.text))).toString())
        rejects(reply().put("quotes", JSONArray(listOf(pair.left.text))).toString())
        rejects(reply().put("title", "Something else").put("draft", "Prepare the itinerary for Brazil.").toString())
        rejects(reply().put("draft", "The Orchard meeting is confirmed at 14:30.").toString())
        rejects(reply().put("type", "executed").toString())
    }

    @Test fun completedDeletedAndRecentlyReviewedMaterialStaysQuietAcrossDays() {
        assertTrue(FeedPreparation.unseen(facts.reversed(), setOf(pair.id)) { false }.isEmpty())
        assertTrue(FeedPreparation.unseen(facts, emptySet()) { it.id == pair.id }.isEmpty())
        val alternate = diary.copy(location = "USER.md", kind = Kind.MEMORY, text = "Use a table for Orchard supplier totals")
        val reviewed = FeedPreparation.relatedAtPublication(pair, facts + alternate)
        assertTrue(FeedPreparation.unseen(facts + alternate, setOf(pair.id)) { it.id in reviewed }.isEmpty())
        val fresh = diary.copy(location = "2026-11-24.md", text = "New Orchard supplier totals need confirmation today")
        assertTrue(FeedPreparation.unseen(facts + fresh, setOf(pair.id)) { it.id in reviewed }.isNotEmpty())
        val updated = listOf(goal.copy(text = goal.text + " and get a written quotation"), diary)
        assertEquals(1, FeedPreparation.unseen(updated, setOf(pair.id)) { false }.size)
        assertTrue(FeedPreparation.revalidate(listOf(pair), listOf(diary)).isEmpty())
        assertTrue(FeedPreparation.revalidate(listOf(pair), updated).isEmpty())
        assertEquals(listOf(pair), FeedPreparation.revalidate(listOf(pair), facts.reversed()))
    }
}
