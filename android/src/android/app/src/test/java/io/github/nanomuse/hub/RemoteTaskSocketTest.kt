package io.github.nanomuse.hub

import io.github.nanomuse.sync.RemoteDeviceTask
import io.github.nanomuse.sync.RemoteTaskReply
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicReference
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.runInterruptible
import kotlinx.coroutines.withContext
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

/** Real local WebSocket frames, without a provider, account credentials or a remote machine. */
class RemoteTaskSocketTest {
    private val device = Device("desk", "Desk", "computer", "Linux", "", true, listOf("task"), 0)

    private fun connected(server: MockWebServer): HubClient {
        val ready = CountDownLatch(1)
        val client = HubClient(server.url("/v1/hub").toString().replaceFirst("http", "ws"), "test-key",
            hello = { JSONObject().put("type", "hello") }, onCall = {}, onDevices = {},
            onState = { connected, _ -> if (connected) ready.countDown() })
        client.start()
        assertTrue("local socket did not connect", ready.await(5, TimeUnit.SECONDS))
        return client
    }

    @Test fun `local and relay task timeouts stop only the original call`() {
        for (relayTimeout in listOf(false, true)) {
            val server = MockWebServer()
            val calls = CopyOnWriteArrayList<JSONObject>()
            server.enqueue(MockResponse().withWebSocketUpgrade(object : WebSocketListener() {
                override fun onClosing(socket: WebSocket, code: Int, reason: String) { socket.close(1000, null) }
                override fun onMessage(socket: WebSocket, text: String) {
                    val frame = JSONObject(text)
                    if (frame.optString("type") == "hello") { socket.send("""{"type":"welcome","devices":[]}"""); return }
                    calls += frame
                    val id = frame.getString("id")
                    if (frame.optString("action") == "task" && relayTimeout) {
                        socket.send(JSONObject().put("type", "error").put("id", id)
                            .put("code", "timeout").put("message", "task deadline reached").toString())
                    }
                    if (frame.optString("action") == "stop") {
                        socket.send(JSONObject().put("type", "result").put("id", id).put("ok", true)
                            .put("body", JSONObject().put("stopped", true)).toString())
                    }
                }
            }))
            server.start()
            val client = connected(server)
            try {
                try {
                    client.call(device.id, "task", JSONObject().put("text", "long task"), if (relayTimeout) 5_000 else 100)
                    fail("task timeout must reach its caller")
                } catch (error: HubException) { assertEquals("timeout", error.code) }
                assertEquals(listOf("task", "stop"), calls.map { it.getString("action") })
                assertEquals(calls[0].getString("id"), calls[1].getJSONObject("args").getString("call"))
                assertEquals(device.id, calls[1].getString("to"))
                assertFalse(calls[1].getJSONObject("args").has("conversation"))
            } finally { client.stop(); server.close() }
        }
    }

    @Test fun `interrupted task callers stop the original call and retain interruption`() {
        val server = MockWebServer()
        val started = CountDownLatch(1)
        val calls = CopyOnWriteArrayList<JSONObject>()
        val failure = AtomicReference<Throwable?>()
        val interrupted = AtomicReference(false)
        server.enqueue(MockResponse().withWebSocketUpgrade(object : WebSocketListener() {
            override fun onClosing(socket: WebSocket, code: Int, reason: String) { socket.close(1000, null) }
            override fun onMessage(socket: WebSocket, text: String) {
                val frame = JSONObject(text)
                if (frame.optString("type") == "hello") { socket.send("""{"type":"welcome","devices":[]}"""); return }
                calls += frame
                when (frame.optString("action")) {
                    "task" -> started.countDown()
                    "stop" -> socket.send(JSONObject().put("type", "result").put("id", frame.getString("id"))
                        .put("ok", true).put("body", JSONObject().put("stopped", true)).toString())
                }
            }
        }))
        server.start()
        val client = connected(server)
        val caller = Thread {
            try { client.call(device.id, "task", JSONObject(), 30_000) }
            catch (error: Throwable) { failure.set(error); interrupted.set(Thread.currentThread().isInterrupted) }
        }
        try {
            caller.start()
            assertTrue(started.await(5, TimeUnit.SECONDS))
            caller.interrupt()
            caller.join(5_000)
            assertFalse("cleanup should finish after the stop response", caller.isAlive)
            assertTrue(failure.get() is InterruptedException)
            assertTrue("the caller's interruption must survive cleanup", interrupted.get())
            assertEquals(listOf("task", "stop"), calls.map { it.getString("action") })
            assertEquals(calls[0].getString("id"), calls[1].getJSONObject("args").getString("call"))
        } finally {
            client.stop()
            caller.interrupt()
            caller.join(5_000)
            server.close()
        }
    }

    @Test fun `non-task timeouts never send a task stop`() {
        val server = MockWebServer()
        val calls = CopyOnWriteArrayList<JSONObject>()
        server.enqueue(MockResponse().withWebSocketUpgrade(object : WebSocketListener() {
            override fun onClosing(socket: WebSocket, code: Int, reason: String) { socket.close(1000, null) }
            override fun onMessage(socket: WebSocket, text: String) {
                val frame = JSONObject(text)
                if (frame.optString("type") == "hello") socket.send("""{"type":"welcome","devices":[]}""")
                else calls += frame
            }
        }))
        server.start()
        val client = connected(server)
        try {
            try { client.call(device.id, "info", JSONObject(), 100); fail("expected timeout") }
            catch (error: HubException) { assertEquals("timeout", error.code) }
            assertEquals(listOf("info"), calls.map { it.getString("action") })
        } finally { client.stop(); server.close() }
    }

    @Test fun `streamed frames reach the reply in order before its one final answer`() = runBlocking {
        val server = MockWebServer()
        val calls = CopyOnWriteArrayList<JSONObject>()
        server.enqueue(MockResponse().withWebSocketUpgrade(object : WebSocketListener() {
            override fun onClosing(socket: WebSocket, code: Int, reason: String) { socket.close(1000, null) }
            override fun onMessage(socket: WebSocket, text: String) {
                val frame = JSONObject(text)
                if (frame.optString("type") == "hello") { socket.send("""{"type":"welcome","devices":[]}"""); return }
                if (frame.optString("action") != "task") return
                calls += frame
                val id = frame.getString("id")
                for (value in listOf("O", "Olá")) socket.send(JSONObject().put("type", "event").put("id", id)
                    .put("body", JSONObject().put("stage", "text").put("text", value).put("partial", true)).toString())
                socket.send(JSONObject().put("type", "result").put("id", id).put("ok", true)
                    .put("body", JSONObject().put("text", "Olá")).toString())
            }
        }))
        server.start()
        val client = connected(server)
        try {
            val reply = RemoteTaskReply(device.id)
            val result = RemoteDeviceTask(device, "hello", "pt-BR", "specific-call").run(
                call = { id, to, action, args, event -> runInterruptible(Dispatchers.IO) { client.callWithId(id, to, action, args, 5_000, event) } },
                onEvent = { reply.event(it) }, stop = {},
            )
            assertEquals("specific-call", calls.single().getString("id"))
            assertEquals("desk", calls.single().getString("to"))
            assertTrue(calls.single().getJSONObject("args").getBoolean("stream"))
            reply.finish(RemoteTaskReply.answer(result)!!)
            assertEquals(listOf("Olá"), reply.blocks.map { it.content })
        } finally { client.stop(); server.close() }
    }

    @Test fun `cancellation sends stop naming the original call`() = runBlocking {
        val server = MockWebServer()
        val started = CountDownLatch(1)
        val stoppedCall = AtomicReference("")
        server.enqueue(MockResponse().withWebSocketUpgrade(object : WebSocketListener() {
            override fun onClosing(socket: WebSocket, code: Int, reason: String) { socket.close(1000, null) }
            override fun onMessage(socket: WebSocket, text: String) {
                val frame = JSONObject(text)
                if (frame.optString("type") == "hello") { socket.send("""{"type":"welcome","devices":[]}"""); return }
                when (frame.optString("action")) {
                    "task" -> started.countDown()
                    "stop" -> {
                        stoppedCall.set(frame.getJSONObject("args").getString("call"))
                        socket.send(JSONObject().put("type", "result").put("id", frame.getString("id")).put("ok", true)
                            .put("body", JSONObject().put("stopped", true)).toString())
                    }
                }
            }
        }))
        server.start()
        val client = connected(server)
        try {
            val job = launch {
                RemoteDeviceTask(device, "hello", "en", "own-call").run(
                    call = { id, to, action, args, event -> runInterruptible(Dispatchers.IO) { client.callWithId(id, to, action, args, 5_000, event) } },
                    onEvent = {},
                    stop = { id -> runInterruptible(Dispatchers.IO) { client.call(device.id, "stop", JSONObject().put("call", id), 5_000) }; Unit },
                )
            }
            assertTrue(withContext(Dispatchers.IO) { started.await(5, TimeUnit.SECONDS) })
            job.cancelAndJoin()
            assertEquals("own-call", stoppedCall.get())
        } finally { client.stop(); server.close() }
    }
}
