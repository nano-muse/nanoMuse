package io.github.nanomuse.chat

import com.openminis.app.data.model.AgentContentPart
import com.openminis.app.data.model.LLMMessage
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class CheckpointReplayTest {
    private fun user(text: String) = LLMMessage(LLMMessage.Role.USER, text)
    private fun assistant(text: String) = LLMMessage(LLMMessage.Role.ASSISTANT, text)
    private fun round(id: String, text: String = "result", signature: String? = null) = listOf(
        LLMMessage(LLMMessage.Role.ASSISTANT, "", contentParts = listOf(
            AgentContentPart.ToolUse(id, "file_read", JSONObject().put("path", "$id.txt"), signature),
        )),
        LLMMessage(LLMMessage.Role.USER, "", contentParts = listOf(
            AgentContentPart.ToolResult(id, "file_read", text),
        )),
    )

    private fun callIds(messages: List<LLMMessage>): List<String> = messages.flatMap { it.contentParts }
        .filterIsInstance<AgentContentPart.ToolUse>().map { it.id }
    private fun resultIds(messages: List<LLMMessage>): List<String> = messages.flatMap { it.contentParts }
        .filterIsInstance<AgentContentPart.ToolResult>().map { it.id }

    @Test
    fun `a covered single turn with a hundred tools replays the request and last three pairs`() {
        val request = user("请保留完整用户指令。".repeat(100)).copy(
            imageParts = listOf(LLMMessage.ImagePart(byteArrayOf(1, 2), "image/png")),
            audioParts = listOf(LLMMessage.AudioPart("wav", "")),
        )
        val rounds = (1..100).flatMap { round("read-$it", "工具结果。".repeat(1_000)) }
        val covered = listOf(request, assistant("此前的分析。".repeat(10_000))) + rounds
        val before = ContextEstimate.request(covered)
        val retained = CheckpointReplay.retainCovered(covered, maxTokens = 40_000)
        assertSame(request, retained.first())
        assertEquals(listOf("read-98", "read-99", "read-100"), callIds(retained))
        assertEquals(callIds(retained), resultIds(retained))
        assertEquals(rounds.takeLast(6), retained.takeLast(6))
        assertTrue(ContextEstimate.request(retained) < 40_000)
        val outgoing = listOf(CompactHistory.prependSummary(retained.first(),
            "之前九十七次读取和分析已完成，当前继续核对最新三个结果。")) + retained.drop(1)
        assertTrue(ContextEstimate.request(outgoing) < before)
        assertEquals(before, ContextEstimate.request(covered))
        assertEquals(100, callIds(covered).size)
    }

    @Test
    fun `replay falls back to one complete latest iteration without truncating its result`() {
        val request = user("正在处理的请求")
        val rounds = (1..5).flatMap { round("read-$it", "精确结果。".repeat(1_000)) }
        val covered = listOf(request) + rounds
        val latest = listOf(request) + rounds.takeLast(2)
        val retained = CheckpointReplay.retainCovered(covered, maxTokens = ContextEstimate.request(latest))
        assertEquals(latest, retained)
        assertSame(rounds.last(), retained.last())
        assertEquals(listOf("read-5"), callIds(retained))
        assertEquals(callIds(retained), resultIds(retained))
    }

    @Test
    fun `fitting replay and oversized indispensable user text stay unchanged`() {
        val small = listOf(user("request")) + round("latest")
        assertSame(small, CheckpointReplay.retainCovered(small, ContextEstimate.request(small)))
        val oversized = listOf(user("完整指令不能截断。".repeat(10_000)))
        assertSame(oversized, CheckpointReplay.retainCovered(oversized, maxTokens = 1))
    }

    @Test
    fun `dangling calls results and intervening user instructions remain intact`() {
        val pending = round("pending").first()
        val orphan = round("orphan").last()
        val interrupted = round("interrupted")
        val correction = user("补充约束，仍需保留。")
        val covered = listOf(user("request"), pending, orphan, interrupted.first(), correction,
            interrupted.last()) + round("old", "old".repeat(1_000)) + round("latest")
        val retained = CheckpointReplay.retainCovered(covered, maxTokens = 1, keepRecentIterations = 1)
        for (protected in listOf(pending, orphan, interrupted.first(), correction, interrupted.last())) {
            assertTrue(retained.any { it === protected })
        }
        assertTrue("old" !in callIds(retained))
        assertTrue("old" !in resultIds(retained))
        assertTrue("latest" in callIds(retained))
    }

    @Test
    fun `mixed result user messages and duplicate ids cannot be detached from their calls`() {
        val mixed = round("mixed").toMutableList()
        mixed[1] = mixed[1].copy(contentParts = mixed[1].contentParts + AgentContentPart.Text("保留补充说明"))
        val duplicate = round("duplicate") + round("duplicate")
        val protected = listOf(user("request")) + mixed + duplicate
        val covered = protected + round("old", "old".repeat(1_000)) + round("latest")
        val retained = CheckpointReplay.retainCovered(covered, maxTokens = 1, keepRecentIterations = 1)
        for (message in protected) assertTrue(retained.any { it === message })
        assertEquals(callIds(retained), resultIds(retained))
    }

    @Test
    fun `signed continuation chain stays verbatim while earlier safe steps can be summarized`() {
        val request = user("request")
        val signedTail = round("signed", signature = "opaque-signature") +
            listOf(assistant("signed continuation")) + round("after") + round("latest")
        val covered = listOf(request) + round("old", "old".repeat(1_000)) + signedTail
        val retained = CheckpointReplay.retainCovered(covered, maxTokens = 1, keepRecentIterations = 1)
        assertEquals(listOf(request) + signedTail, retained)
        signedTail.forEachIndexed { index, message -> assertSame(message, retained[index + 1]) }
    }

    @Test
    fun `parallel calls are retained or removed as one balanced iteration`() {
        val a = round("a", "large".repeat(1_000))
        val b = round("b", "large".repeat(1_000))
        val parallel = listOf(a.first().copy(contentParts = a.first().contentParts + b.first().contentParts),
            a.last(), b.last())
        val old = listOf(user("request")) + parallel + round("latest")
        val retained = CheckpointReplay.retainCovered(old, maxTokens = 1, keepRecentIterations = 1)
        assertEquals(listOf("latest"), callIds(retained))
        assertEquals(callIds(retained), resultIds(retained))
        val latestParallel = listOf(user("request")) + round("old", "large".repeat(1_000)) + parallel
        val keptParallel = CheckpointReplay.retainCovered(latestParallel, maxTokens = 1, keepRecentIterations = 1)
        assertEquals(listOf("a", "b"), callIds(keptParallel))
        assertEquals(callIds(keptParallel), resultIds(keptParallel))
    }
}
