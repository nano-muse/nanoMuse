package io.github.nanomuse.chat

import com.openminis.app.data.model.AgentContentPart
import com.openminis.app.data.model.LLMMessage
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class CompactHistoryPairingTest {
    private fun user(text: String) = LLMMessage(LLMMessage.Role.USER, text)
    private fun call(id: String) = LLMMessage(LLMMessage.Role.ASSISTANT, "", contentParts = listOf(
        AgentContentPart.ToolUse(id, "file_read", JSONObject().put("path", "$id.txt")),
    ))
    private fun result(id: String) = LLMMessage(LLMMessage.Role.USER, "", contentParts = listOf(
        AgentContentPart.ToolResult(id, "file_read", "exact result"),
    ))

    @Test
    fun `mandatory replay widens repeatedly when users arrive between tool calls and results`() {
        val older = listOf(user("completed old turn"),
            LLMMessage(LLMMessage.Role.ASSISTANT, "old".repeat(1_000)))
        val needed = listOf(
            user("first active instruction"), call("a"),
            user("additional constraint"), result("a"), call("b"),
            user("latest correction"), result("b"),
        )
        val history = older + needed
        val retained = CompactHistory.retainRecentTurns(history, maxTokens = 1)
        assertEquals(needed, retained)
        needed.forEachIndexed { index, message -> assertSame(message, retained[index]) }
        val replay = CheckpointReplay.retainCovered(retained, maxTokens = 1)
        assertEquals(needed, replay)
        assertEquals(older + needed, history)
    }

    @Test
    fun `optional replay is omitted when the widened paired boundary exceeds its budget`() {
        val history = listOf(user("earlier instruction"), call("pending"),
            user("new instruction"), result("pending"))
        val unsafeSuffixBudget = ContextEstimate.request(history.drop(2))
        assertTrue(CompactHistory.retainRecentTurns(
            history, maxTokens = unsafeSuffixBudget, keepNewestTurn = false,
        ).isEmpty())
        assertSame(history, CompactHistory.retainRecentTurns(
            history, maxTokens = ContextEstimate.request(history), keepNewestTurn = false,
        ))
    }
}
