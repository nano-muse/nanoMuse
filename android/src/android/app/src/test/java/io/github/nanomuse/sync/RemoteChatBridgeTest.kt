package io.github.nanomuse.sync

import com.openminis.app.ui.chat.AssistantBlock
import io.github.nanomuse.hub.Device
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

@OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
class RemoteChatBridgeTest {
    private val device = Device("desk", "Desk", "computer", "Linux", "", true, listOf("task"), 0)
    private class Host : RemoteChatBridge.Host {
        var running = false
        override val busy: Boolean get() = running
        var draft = "@Desk hello"
        var userCount = 0
        var saved = 0
        var updates = 0
        var ended = 0
        val errors = mutableListOf<RemoteChatBridge.Issue>()
        override fun setBusy(value: Boolean) { running = value }
        override fun error(issue: RemoteChatBridge.Issue, device: String) { errors += issue }
        override fun clearDraft() { draft = "" }
        override fun restoreDraft(text: String) { draft = text }
        override suspend fun session() = "session"
        override suspend fun user(sessionId: String, text: String) { userCount++ }
        override fun show(id: String, task: RemoteChatBridge.Task) { updates++ }
        override suspend fun finish(sessionId: String, id: String, task: RemoteChatBridge.Task) { saved++ }
        override fun afterTurn() { ended++ }
    }
    private class Task(private val wait: Boolean = false) : RemoteChatBridge.Task {
        override val text = "remote answer"
        override val blocks = emptyList<AssistantBlock>()
        override val failed = false
        var stops = 0
        var lateUpdate: (() -> Unit)? = null
        override suspend fun run(sessionId: String, update: () -> Unit) {
            lateUpdate = update
            update()
            if (wait) awaitCancellation()
        }
        override fun stop() { stops++ }
    }

    @Test fun `direct routing records one user and one answer and never creates a local task`() = runTest {
        val host = Host()
        var created = 0
        val task = Task()
        val bridge = RemoteChatBridge(this, host) { d, text, _ ->
            created++; assertEquals("desk", d.id); assertEquals("hello", text); task
        }
        assertFalse(bridge.send("ordinary message", listOf(device), false, false))
        assertEquals(0, created)
        assertTrue(bridge.send("@Desk hello", listOf(device), false, false))
        runCurrent()
        assertEquals(1, created)
        assertEquals(1, host.userCount)
        assertEquals(1, host.saved)
        assertEquals(1, host.ended)
        assertFalse(host.busy)
        val updates = host.updates
        task.lateUpdate!!()
        assertEquals("a completed reply must not be resurrected", updates, host.updates)
    }

    @Test fun `offline attachments and busy refusals keep the draft and never call the transport`() = runTest {
        for (kind in listOf("offline", "attachments", "busy")) {
            // The actual composer clears its field immediately before invoking sendMessage.
            val host = Host().apply { running = kind == "busy"; draft = "" }
            val bridge = RemoteChatBridge(this, host) { _, _, _ -> error("must not start") }
            assertTrue(bridge.send("@Desk hello", listOf(device.copy(online = kind != "offline")), kind == "attachments", false))
            assertEquals("@Desk hello", host.draft)
            assertEquals(0, host.saved)
            assertEquals(1, host.errors.size)
        }
    }

    @Test fun `cancelling a running task persists once and releases the conversation`() = runTest {
        val host = Host()
        val task = Task(wait = true)
        val bridge = RemoteChatBridge(this, host) { _, _, _ -> task }
        bridge.send("@Desk hello", listOf(device), false, false)
        assertTrue(bridge.cancel())
        runCurrent()
        assertEquals(1, host.saved)
        assertFalse(host.busy)
        assertFalse(bridge.cancel())
    }
}
