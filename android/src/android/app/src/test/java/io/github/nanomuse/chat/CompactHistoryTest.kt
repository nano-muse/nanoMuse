package io.github.nanomuse.chat

import com.openminis.app.data.model.AgentContentPart
import com.openminis.app.data.model.LLMMessage
import com.openminis.app.data.model.LLMModel
import com.openminis.app.provider.openai.OpenAIProvider
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class CompactHistoryTest {
    private fun user(text: String) = LLMMessage(LLMMessage.Role.USER, text)
    private fun assistant(text: String) = LLMMessage(LLMMessage.Role.ASSISTANT, text)

    private fun toolRound(id: String, output: String): List<LLMMessage> = listOf(
        LLMMessage(LLMMessage.Role.ASSISTANT, "", contentParts = listOf(
            AgentContentPart.ToolUse(id, "file_read", JSONObject().put("path", "report.txt")),
        )),
        LLMMessage(LLMMessage.Role.USER, "", contentParts = listOf(
            AgentContentPart.ToolResult(id, "file_read", output),
        )),
    )

    @Test
    fun `old long main chat gives way to summary while active search remains intact`() {
        val older = listOf(
            user("之前讨论的报告"), assistant("旧报告内容。".repeat(2_000)),
            user("再解释一下"), assistant("另一份报告内容。".repeat(2_000)),
        )
        val active = listOf(user("查一下这款手机的价格")) +
            toolRound("search", "找到了价格来源") +
            toolRound("fetch", "页面显示价格，需要对照型号") +
            toolRound("read", "确认型号和价格")
        val history = older + active
        val before = ContextEstimate.request(history)
        assertTrue(before > 32_000)

        val recent = CompactHistory.retainRecentTurns(history, maxTokens = 8_000)
        assertEquals(active, recent)
        assertTrue(ContextEstimate.request(recent) < 8_000)
        assertEquals(before, ContextEstimate.request(history))
        assertEquals(older + active, history)
    }

    @Test
    fun `retention boundary never cuts between a tool call and its result`() {
        val oldest = listOf(user("旧任务")) + toolRound("old", "很长的旧结果".repeat(1_000))
        val recent = listOf(user("最近的任务")) + toolRound("recent", "成功")
        val active = listOf(user("当前问题")) + toolRound("active", "当前结果")
        val retained = CompactHistory.retainRecentTurns(oldest + recent + active, maxTokens = 500)
        assertEquals(recent + active, retained)
        val parts = retained.flatMap { it.contentParts }
        assertEquals(
            setOf("recent", "active"),
            parts.filterIsInstance<AgentContentPart.ToolUse>().map { it.id }.toSet(),
        )
        assertEquals(
            setOf("recent", "active"),
            parts.filterIsInstance<AgentContentPart.ToolResult>().map { it.id }.toSet(),
        )
    }

    @Test
    fun `oversized active turn stays whole rather than losing the current question`() {
        val active = listOf(user("保留当前请求")) + toolRound("current", "最新内容".repeat(4_000))
        val retained = CompactHistory.retainRecentTurns(
            listOf(user("已完成的旧问题"), assistant("已完成")) + active,
            maxTokens = 1_000,
        )
        assertEquals(active, retained)
        assertTrue(ContextEstimate.request(retained) > 1_000)
    }

    @Test
    fun `small history and a history without a safe boundary stay unchanged`() {
        val small = listOf(user("问题一"), assistant("答复一"), user("问题二"))
        assertSame(small, CompactHistory.retainRecentTurns(small, maxTokens = 8_000))
        val resultsOnly = toolRound("active", "不要丢失结果")
        assertSame(resultsOnly, CompactHistory.retainRecentTurns(resultsOnly, maxTokens = 0))
        assertTrue(CompactHistory.retainRecentTurns(emptyList(), maxTokens = 8_000).isEmpty())
    }

    @Test
    fun `caller can budget recent turns using calibrated counts`() {
        val older = listOf(user("earlier"), assistant("a".repeat(400)))
        val active = listOf(user("current"))
        val history = older + active
        assertEquals(history, CompactHistory.retainRecentTurns(history, maxTokens = 200))
        assertEquals(active, CompactHistory.retainRecentTurns(history, maxTokens = 200) {
            ContextEstimate.request(it) * 2
        })
    }

    @Test
    fun `replay grows with model budget but charges fixed instructions and summary first`() {
        val older = listOf(user("earlier"), assistant("a".repeat(40_000)))
        val active = listOf(user("current")) + toolRound("current", "result")
        val history = older + active
        val small = ContextBudget.forModel(24_000, 4_096, fixedTokens = 4_000)
        val large = ContextBudget.forModel(128_000, 8_192, fixedTokens = 4_000)
        assertEquals(active, CompactHistory.retainForBudget(history, small, summaryTokens = 2_000))
        assertEquals(history, CompactHistory.retainForBudget(history, large, summaryTokens = 2_000))
        assertEquals(active, CompactHistory.retainForBudget(history, large, summaryTokens = large.targetTokens))
        assertEquals(older + active, history)
    }

    @Test
    fun `optional history does not force an old turn into a separately protected active request`() {
        val older = listOf(user("earlier")) + toolRound("old", "a".repeat(4000))
        val newestOld = listOf(user("last completed task")) + toolRound("completed", "done")
        assertTrue(CompactHistory.retainRecentTurns(
            older + newestOld, maxTokens = 0, keepNewestTurn = false,
        ).isEmpty())
        assertTrue(CompactHistory.retainRecentTurns(
            older, maxTokens = 100, keepNewestTurn = false,
        ).isEmpty())
        assertEquals(newestOld, CompactHistory.retainRecentTurns(
            older + newestOld, maxTokens = 100, keepNewestTurn = false,
        ))
        assertEquals(newestOld, CompactHistory.retainRecentTurns(older + newestOld, maxTokens = 0))
    }

    @Test
    fun `zero replay budget retains a manual anchor call needed by an uncovered result`() {
        val request = user("Read the report")
        val round = toolRound("across-anchor", "Result not covered by the checkpoint")
        val preAnchor = listOf(request, round.first())
        val postAnchor = listOf(round.last(), user("Use that result to answer the new question"))
        val retained = CompactHistory.retainRecentTurns(
            preAnchor, maxTokens = 0, keepNewestTurn = false,
            requiredToolIds = CompactHistory.externalToolResultIds(postAnchor),
        )
        assertEquals(preAnchor, retained)
        val outgoing = CheckpointReplay.retainCovered(retained, maxTokens = 0) + postAnchor
        assertSame(request, outgoing.first())
        assertSame(round.last(), outgoing[2])
        assertEquals(listOf("across-anchor"), outgoing.flatMap { it.contentParts }
            .filterIsInstance<AgentContentPart.ToolUse>().map { it.id })
        assertEquals(listOf("across-anchor"), outgoing.flatMap { it.contentParts }
            .filterIsInstance<AgentContentPart.ToolResult>().map { it.id })
    }

    @Test
    fun `multiple uncovered results preserve their earliest whole user turn without old duplicate ids`() {
        val reused = toolRound("reused", "Earlier completed result")
        val discardable = listOf(user("Completed earlier task")) + reused
        val first = toolRound("first-crossing", "First uncovered result")
        val second = toolRound("second-crossing", "Second uncovered result")
        val required = listOf(user("First request"), first.first(),
            user("Additional constraint"), second.first())
        val localRound = toolRound("reused", "A new call after the anchor supplies this result")
        val postAnchor = listOf(first.last(), second.last(), user("New request")) + localRound
        val dependencies = CompactHistory.externalToolResultIds(postAnchor)
        assertEquals(setOf("first-crossing", "second-crossing"), dependencies)
        val retained = CompactHistory.retainRecentTurns(
            discardable + required, maxTokens = 0, keepNewestTurn = false,
            requiredToolIds = dependencies,
        )
        assertEquals(required, retained)
        val outgoing = CheckpointReplay.retainCovered(retained, maxTokens = 0) + postAnchor
        val calls = outgoing.flatMap { it.contentParts }.filterIsInstance<AgentContentPart.ToolUse>()
        val results = outgoing.flatMap { it.contentParts }.filterIsInstance<AgentContentPart.ToolResult>()
        assertEquals(listOf("first-crossing", "second-crossing", "reused"), calls.map { it.id })
        assertEquals(calls.map { it.id }, results.map { it.id })
        assertEquals(listOf("First request", "Additional constraint", "New request"),
            outgoing.filter(ContextTurns::isUserRequest).map { it.content })
    }

    @Test
    fun `summary reaches the provider once when current request has structured text`() {
        val summary = "<context-summary>之前已确认预算。</context-summary>"
        val original = user("现在查价格").copy(
            dbMessageId = "current-user",
            contentParts = listOf(AgentContentPart.Text("现在查价格")),
        )
        val injected = CompactHistory.prependSummary(original, summary)
        val provider = OpenAIProvider(apiKey = "", model = LLMModel.gpt4oMini)
        val body = provider.buildRequestBody(
            messages = listOf(injected), systemPrompt = null, maxTokens = 128,
            stream = false, temperature = null, imageParts = emptyList(),
        )
        val wireText = body.getJSONArray("messages").getJSONObject(0).getString("content")
        assertTrue(wireText.contains(summary))
        assertTrue(wireText.contains("现在查价格"))
        assertEquals(1, Regex(Regex.escape(summary)).findAll(wireText).count())
        assertEquals("current-user", injected.dbMessageId)
        assertEquals(listOf(AgentContentPart.Text("现在查价格")), original.contentParts)
        assertTrue(ContextEstimate.request(listOf(injected)) > ContextEstimate.request(listOf(original)))
    }

    @Test
    fun `plain summary injection preserves attachments and leaves structured payload optional`() {
        val original = user("看这张图").copy(
            imageParts = listOf(LLMMessage.ImagePart(byteArrayOf(1, 2), "image/png")),
            audioParts = listOf(LLMMessage.AudioPart("wav", "")),
        )
        val injected = CompactHistory.prependSummary(original, "之前的摘要")
        assertEquals("之前的摘要\n\n看这张图", injected.content)
        assertTrue(injected.contentParts.isEmpty())
        assertSame(original.imageParts, injected.imageParts)
        assertSame(original.audioParts, injected.audioParts)
        assertSame(original, CompactHistory.prependSummary(original, ""))
    }

    @Test
    fun `summary and image survive a structured followup without counting aggregate text twice`() {
        val image = AgentContentPart.ImageData(byteArrayOf(1, 2), "image/png")
        val original = user("看这张图").copy(contentParts = listOf(
            AgentContentPart.Text("看这张图"), image,
        ))
        val summary = "<context-summary>之前确认了型号。</context-summary>"
        val injected = CompactHistory.prependSummary(original, summary)
        assertSame(image, injected.contentParts.last())
        val before = ContextEstimate.request(listOf(original), imageTokens = { 777 })
        val after = ContextEstimate.request(listOf(injected), imageTokens = { 777 })
        assertEquals(before + ContextEstimate.text(summary + "\n\n"), after)

        val model = LLMModel(
            id = "text-model", displayName = "Text model", provider = "test",
            inputModalities = listOf("text"),
        )
        val provider = OpenAIProvider(apiKey = "", model = model)
        val body = provider.buildRequestBody(
            messages = listOf(injected), systemPrompt = null, maxTokens = 128,
            stream = false, temperature = null, imageParts = emptyList(),
        )
        val parts = body.getJSONArray("messages").getJSONObject(0).getJSONArray("content")
        assertEquals(summary + "\n\n", parts.getJSONObject(0).getString("text"))
        assertEquals("看这张图", parts.getJSONObject(1).getString("text"))
        assertEquals(3, parts.length())
    }
}
