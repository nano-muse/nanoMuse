package io.github.nanomuse.sync

import io.github.nanomuse.hub.Device
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

@OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
class RemoteDeviceTaskTest {
    private val device = Device("desk", "Desk", "computer", "Linux", "", true, listOf("task"), 0)

    @Test fun `explicit task goes directly to the selected transport with streaming and language`() = runTest {
        var calls = 0
        val task = RemoteDeviceTask(device, "hello", "pt-BR", "call-one")
        val result = task.run(call = { id, to, action, args, event ->
            calls++
            assertEquals("call-one", id)
            assertEquals("desk", to)
            assertEquals("task", action)
            assertEquals("pt-BR", args.getString("language"))
            assertTrue(args.getBoolean("stream"))
            assertEquals("hello", args.getString("text"))
            event(JSONObject().put("stage", "text").put("text", "O"))
            event(JSONObject().put("stage", "text").put("text", "Olá"))
            JSONObject().put("text", "Olá")
        }, onEvent = {}, stop = {})
        assertEquals("Olá", result.getString("text"))
        assertEquals(1, calls)
    }

    @Test fun `cancel sends stop for its own call and cancels the suspended transport`() = runTest {
        val started = CompletableDeferred<Unit>()
        val stops = mutableListOf<String>()
        val task = RemoteDeviceTask(device, "hello", "en", "own-call")
        val job = launch {
            task.run(call = { _, _, _, _, _ -> started.complete(Unit); awaitCancellation() }, onEvent = {}, stop = { stops += it })
        }
        runCurrent()
        assertTrue("transport was not started", started.isCompleted)
        job.cancelAndJoin()
        assertEquals(listOf("own-call"), stops)
    }

    @Test fun `offline destination is refused before the transport is called`() = runTest {
        var called = false
        try {
            RemoteDeviceTask(device.copy(online = false), "hello", "en", "call").run(
                call = { _, _, _, _, _ -> called = true; JSONObject() }, onEvent = {}, stop = {},
            )
            fail("offline task was accepted")
        } catch (e: io.github.nanomuse.hub.HubException) {
            assertEquals("device_offline", e.code)
        }
        assertFalse(called)
    }

    @Test fun `events are delivered in order before the final result including old non-streaming targets`() = runTest {
        val events = mutableListOf<String>()
        val task = RemoteDeviceTask(device, "hello", "en", "call")
        task.run(call = { _, _, _, _, event ->
            event(JSONObject().put("stage", "tool"))
            event(JSONObject().put("stage", "tool_result"))
            JSONObject().put("text", "final only")
        }, onEvent = { events += it.getString("stage") }, stop = {})
        assertEquals(listOf("tool", "tool_result"), events)
    }

    @Test fun `a failed progress consumer stops the remote call instead of abandoning running work`() = runTest {
        val stops = mutableListOf<String>()
        try {
            RemoteDeviceTask(device, "hello", "en", "own-call").run(
                call = { _, _, _, _, event -> event(JSONObject().put("stage", "tool")); awaitCancellation() },
                onEvent = { throw IllegalStateException("cannot draw progress") }, stop = { stops += it },
            )
            fail("consumer error was lost")
        } catch (_: IllegalStateException) { }
        assertEquals(listOf("own-call"), stops)
    }

    @Test fun `a direct task timeout stops once and keeps the original error if cleanup fails`() = runTest {
        val stops = mutableListOf<String>()
        try {
            RemoteDeviceTask(device, "long task", "en", "timed-out-call").run(
                call = { _, _, _, _, _ -> throw io.github.nanomuse.hub.HubException("timeout", "original timeout") },
                onEvent = {},
                stop = { stops += it; throw io.github.nanomuse.hub.HubException("disconnected", "cleanup failed") },
            )
            fail("timeout must be reported")
        } catch (error: io.github.nanomuse.hub.HubException) {
            assertEquals("timeout", error.code)
            assertEquals("original timeout", error.message)
        }
        assertEquals(listOf("timed-out-call"), stops)
    }
}
