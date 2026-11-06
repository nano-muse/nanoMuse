package io.github.nanomuse.chat

import com.openminis.app.data.model.AgentContentPart
import com.openminis.app.data.model.LLMMessage
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

class ContextTurnsTest {
    private val reminder = "<system-reminder>Continue the previous response.</system-reminder>"
    private fun user(text: String) = LLMMessage(LLMMessage.Role.USER, text)

    @Test
    fun `plain and persisted structured reminders do not start new user turns`() {
        assertFalse(ContextTurns.isUserRequest(user(reminder)))
        assertFalse(ContextTurns.isUserRequest(user(reminder).copy(
            contentParts = listOf(AgentContentPart.Text(reminder)), dbMessageId = "persisted-reminder",
        )))
        assertFalse(ContextTurns.isUserRequest(user(" \n$reminder\n$reminder\t")))
        assertFalse(ContextTurns.isUserRequest(user("").copy(contentParts = listOf(
            AgentContentPart.Text("<system-reminder>"),
            AgentContentPart.Text("Continue the previous response.</system-reminder>"),
        ))))
    }

    @Test
    fun `real text around reminders and incomplete markup still define a user request`() {
        for (text in listOf(
            "真实问题", "真实问题\n$reminder", "$reminder\n真实问题",
            "$reminder\n真实问题\n$reminder", "<system-reminder>unclosed",
            "", " ",
        )) assertTrue(text, ContextTurns.isUserRequest(user(text)))
        assertTrue(ContextTurns.isUserRequest(user(reminder).copy(contentParts = listOf(
            AgentContentPart.Text(reminder), AgentContentPart.Text("还有新的要求"),
        ))))
        assertTrue(ContextTurns.isUserRequest(user("新的正文").copy(
            contentParts = listOf(AgentContentPart.Text(reminder)),
        )))
    }

    @Test
    fun `attachments remain user requests even when their caption is a reminder`() {
        assertTrue(ContextTurns.isUserRequest(user(reminder).copy(
            imageParts = listOf(LLMMessage.ImagePart(byteArrayOf(1), "image/png")),
        )))
        assertTrue(ContextTurns.isUserRequest(user(reminder).copy(
            audioParts = listOf(LLMMessage.AudioPart("wav", "")),
        )))
        assertTrue(ContextTurns.isUserRequest(user(reminder).copy(contentParts = listOf(
            AgentContentPart.Text(reminder), AgentContentPart.ImageData(byteArrayOf(1), "image/png"),
        ))))
    }

    @Test
    fun `assistant and tool carriers are never user request boundaries`() {
        assertFalse(ContextTurns.isUserRequest(LLMMessage(LLMMessage.Role.ASSISTANT, "reply")))
        assertFalse(ContextTurns.isUserRequest(user("mixed text").copy(contentParts = listOf(
            AgentContentPart.Text("mixed text"), AgentContentPart.ToolResult("call", "read", "result"),
        ))))
    }

    @Test
    fun `Continue after a checkpoint keeps the real oversized current turn and the reminder`() {
        val earlier = listOf(user("old finished request"), LLMMessage(LLMMessage.Role.ASSISTANT, "done"))
        val active = listOf(user("保留这个请求的全部约束"),
            LLMMessage(LLMMessage.Role.ASSISTANT, "long partial response".repeat(1_000)))
        val postAnchor = listOf(user(reminder).copy(dbMessageId = "persisted-reminder"))
        val hasNewUser = postAnchor.any(ContextTurns::isUserRequest)
        assertFalse(hasNewUser)
        val replay = CompactHistory.retainRecentTurns(earlier + active, 100,
            keepNewestTurn = !hasNewUser)
        assertEquals(active, replay)
        val outbound = CheckpointReplay.retainCovered(replay, 100) + postAnchor
        assertSame(active[0], outbound[0])
        assertSame(postAnchor[0], outbound.last())
        assertEquals(active[0], (earlier + active + postAnchor).last(ContextTurns::isUserRequest))

        // Without a marker, the same reminder also must not become the replay boundary.
        assertEquals(active + postAnchor,
            CompactHistory.retainRecentTurns(earlier + active + postAnchor, 100))
    }

    @Test
    fun `a real new question after a reminder still creates a fresh optional replay boundary`() {
        val covered = listOf(user("previous request"),
            LLMMessage(LLMMessage.Role.ASSISTANT, "covered output".repeat(1_000)))
        val next = user("现在换个问题")
        val postAnchor = listOf(user(reminder), next)
        assertTrue(postAnchor.any(ContextTurns::isUserRequest))
        assertTrue(CompactHistory.retainRecentTurns(covered, 100,
            keepNewestTurn = !postAnchor.any(ContextTurns::isUserRequest)).isEmpty())
        assertEquals(listOf(next), CompactHistory.retainRecentTurns(covered + postAnchor, 100))
    }
}
