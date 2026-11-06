package io.github.nanomuse.speech

import com.openminis.app.data.model.LLMModel
import com.openminis.app.data.model.ProviderInstance
import com.openminis.app.data.model.ProviderCredential
import com.openminis.app.data.model.ProviderType
import com.openminis.app.data.model.VoiceProviderTemplate
import com.openminis.app.provider.voice.VoiceInputRequest
import com.openminis.app.provider.voice.VoiceOutputRequest
import com.openminis.app.provider.voice.VoiceProvider
import com.openminis.app.provider.voice.VoiceProviderException
import com.openminis.app.provider.voice.VoiceProviderFactory
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import okhttp3.Response
import okhttp3.Call
import okhttp3.EventListener
import okhttp3.OkHttpClient
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.SocketPolicy
import okio.ByteString
import okio.ByteString.Companion.toByteString
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import java.io.IOException

class DashScopeVoiceProviderTest {
    private val server = MockWebServer()
    private val commands = LinkedBlockingQueue<JSONObject>()
    private val binaries = LinkedBlockingQueue<ByteString>()
    private val opened = LinkedBlockingQueue<WebSocket>()
    private var taskId = ""

    @After fun close() { server.shutdown() }

    private fun provider(timeout: Long = 3000) = DashScopeVoiceProvider(
        "test", server.url("/compatible-mode/v1").toString(), "test-key", timeoutMillis = timeout,
    )

    private fun websocket(onCommand: (WebSocket, JSONObject) -> Unit = { _, _ -> }) {
        server.enqueue(MockResponse().withWebSocketUpgrade(object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) { opened.add(webSocket) }
            override fun onMessage(webSocket: WebSocket, text: String) {
                val command = JSONObject(text)
                commands.add(command)
                if (command.getJSONObject("header").getString("action") == "run-task") {
                    taskId = command.getJSONObject("header").getString("task_id")
                    event(webSocket, "task-started")
                }
                onCommand(webSocket, command)
            }
            override fun onMessage(webSocket: WebSocket, bytes: ByteString) { binaries.add(bytes) }
            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) { webSocket.close(code, null) }
        }))
    }

    private fun event(socket: WebSocket, name: String, payload: JSONObject = JSONObject(), id: String = taskId) {
        socket.send(JSONObject().put("header", JSONObject().put("task_id", id).put("event", name))
            .put("payload", payload).toString())
    }

    private fun action(command: JSONObject) = command.getJSONObject("header").getString("action")

    @Test fun `Paraformer uses native websocket and waits for final sentences`() = runBlocking {
        val wav = VoiceProvider.wrapPcm16InWav(ByteArray(100), 16000)
        websocket { socket, command ->
            if (action(command) == "finish-task") {
                fun sentence(text: String, start: Int, final: Boolean) = JSONObject().put("output",
                    JSONObject().put("sentence", JSONObject().put("text", text)
                        .put("begin_time", start).put("sentence_end", final)))
                event(socket, "result-generated", sentence("partial", 0, false))
                event(socket, "result-generated", sentence("Hello ", 0, true))
                event(socket, "result-generated", sentence("Hello ", 0, true))
                event(socket, "result-generated", sentence("world", 200, true))
                event(socket, "task-finished")
            }
        }
        assertEquals("Hello world", provider().transcribe(VoiceInputRequest(wav, language = "en-US")).text)
        val request = server.takeRequest(1, TimeUnit.SECONDS)!!
        assertEquals("/api-ws/v1/inference", request.path)
        assertEquals("Bearer test-key", request.getHeader("Authorization"))
        val run = commands.poll(1, TimeUnit.SECONDS)!!
        assertEquals("run-task", action(run))
        val payload = run.getJSONObject("payload")
        assertEquals("paraformer-realtime-v2", payload.getString("model"))
        assertEquals("recognition", payload.getString("function"))
        assertEquals("wav", payload.getJSONObject("parameters").getString("format"))
        assertEquals(16000, payload.getJSONObject("parameters").getInt("sample_rate"))
        assertEquals("en", payload.getJSONObject("parameters").getJSONArray("language_hints").getString(0))
        assertArrayEquals(wav, binaries.poll(1, TimeUnit.SECONDS)!!.toByteArray())
        assertEquals("finish-task", action(commands.poll(1, TimeUnit.SECONDS)!!))
    }

    @Test fun `CosyVoice sends text after start and collects binary audio until finish`() = runBlocking {
        websocket { socket, command ->
            if (action(command) == "finish-task") {
                socket.send(byteArrayOf(1, 2).toByteString())
                socket.send(byteArrayOf(3, 4).toByteString())
                event(socket, "task-finished")
            }
        }
        assertArrayEquals(byteArrayOf(1, 2, 3, 4), provider().synthesize(
            VoiceOutputRequest("Hello", model = "cosyvoice-v2", voice = "cosyvoice-v2", speed = 1.5f)))
        val run = commands.poll(1, TimeUnit.SECONDS)!!.getJSONObject("payload")
        assertEquals("SpeechSynthesizer", run.getString("function"))
        assertEquals("longxiaochun_v2", run.getJSONObject("parameters").getString("voice"))
        assertEquals(1.5, run.getJSONObject("parameters").getDouble("rate"), 0.0)
        assertEquals("mp3", run.getJSONObject("parameters").getString("format"))
        val text = commands.poll(1, TimeUnit.SECONDS)!!
        assertEquals("continue-task", action(text))
        assertEquals("Hello", text.getJSONObject("payload").getJSONObject("input").getString("text"))
        assertEquals("finish-task", action(commands.poll(1, TimeUnit.SECONDS)!!))
    }

    @Test fun `Qwen TTS uses native HTTP and downloads without provider authorization`() = runBlocking {
        val url = server.url("/audio.wav").toString()
        server.enqueue(MockResponse().setBody(JSONObject().put("output", JSONObject()
            .put("audio", JSONObject().put("url", url))).toString()))
        server.enqueue(MockResponse().setBody(okio.Buffer().write(byteArrayOf(7, 8, 9))))
        assertArrayEquals(byteArrayOf(7, 8, 9), provider().synthesize(
            VoiceOutputRequest("Hello", "qwen3-tts-flash", "qwen3-tts-flash")))
        val generate = server.takeRequest(1, TimeUnit.SECONDS)!!
        assertEquals("/api/v1/services/aigc/multimodal-generation/generation", generate.path)
        assertEquals("Bearer test-key", generate.getHeader("Authorization"))
        val body = JSONObject(generate.body.readUtf8())
        assertEquals("qwen3-tts-flash", body.getString("model"))
        assertEquals("Hello", body.getJSONObject("input").getString("text"))
        assertEquals("Cherry", body.getJSONObject("input").getString("voice"))
        assertEquals("Auto", body.getJSONObject("input").getString("language_type"))
        val download = server.takeRequest(1, TimeUnit.SECONDS)!!
        assertEquals("/audio.wav", download.path)
        assertNull(download.getHeader("Authorization"))
    }

    @Test fun `unsupported realtime models never reach generic OpenAI audio endpoints`() = runBlocking {
        for (model in listOf("qwen3-asr-flash-realtime", "qwen3.8-omni-flash-realtime", "qwen-audio-3.1-realtime-flash")) {
            val result = runCatching { provider().transcribe(VoiceInputRequest(byteArrayOf(1), model,
                resolvedModel = LLMModel(id = model, displayName = model, provider = "alibaba"))) }
            assertTrue(result.exceptionOrNull() is VoiceProviderException.Unsupported)
        }
        assertTrue(runCatching { provider().synthesize(VoiceOutputRequest("Hello", "qwen3-tts-flash-realtime")) }
            .exceptionOrNull() is VoiceProviderException.Unsupported)
        assertEquals(0, server.requestCount)
    }

    @Test fun `task failure is terminal and unknown task results are ignored`() = runBlocking {
        websocket { socket, command ->
            if (action(command) == "finish-task") {
                event(socket, "task-finished", id = "another-task")
                socket.send(JSONObject().put("header", JSONObject().put("task_id", taskId)
                    .put("event", "task-failed").put("error_code", "InvalidParameter")).toString())
            }
        }
        val failure = runCatching { provider().transcribe(VoiceInputRequest(byteArrayOf(1))) }.exceptionOrNull()
        assertTrue(failure is VoiceProviderException.Parse)
        assertTrue(failure!!.message!!.contains("InvalidParameter"))
    }

    @Test fun `closing before task finish fails instead of returning incomplete audio`() = runBlocking {
        websocket { socket, command -> if (action(command) == "finish-task") socket.close(1000, null) }
        assertTrue(runCatching { provider().synthesize(VoiceOutputRequest("Hello")) }
            .exceptionOrNull() is VoiceProviderException.Parse)
    }

    @Test fun `empty synthesis result fails`() = runBlocking {
        websocket { socket, command -> if (action(command) == "finish-task") event(socket, "task-finished") }
        assertTrue(runCatching { provider().synthesize(VoiceOutputRequest("Hello")) }
            .exceptionOrNull() is VoiceProviderException.NoAudioData)
    }

    @Test fun `websocket timeout cancels the task`() = runBlocking {
        websocket()
        assertTrue(runCatching { provider(150).transcribe(VoiceInputRequest(byteArrayOf(1))) }
            .exceptionOrNull() is CancellationException)
    }

    @Test fun `caller cancellation remains cancellation`() = runBlocking {
        websocket()
        val task = async(start = CoroutineStart.UNDISPATCHED) { provider().synthesize(VoiceOutputRequest("Hello")) }
        assertNotNull(opened.poll(1, TimeUnit.SECONDS))
        task.cancel()
        assertTrue(runCatching { task.await() }.exceptionOrNull() is CancellationException)
    }

    @Test fun `HTTP authentication failure is surfaced without downloading`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(401))
        assertTrue(runCatching { provider().synthesize(VoiceOutputRequest("Hello", "qwen3-tts-flash")) }
            .exceptionOrNull() is VoiceProviderException.Auth)
        assertEquals(1, server.requestCount)
    }

    @Test fun `Qwen missing audio URL is not treated as audio`() = runBlocking {
        server.enqueue(MockResponse().setBody("{\"output\":{\"audio\":{}}}"))
        assertTrue(runCatching { provider().synthesize(VoiceOutputRequest("Hello", "qwen3-tts-flash")) }
            .exceptionOrNull() is VoiceProviderException.NoAudioData)
    }

    @Test fun `cancelling HTTP synthesis cancels the underlying call`() = runBlocking {
        val failed = LinkedBlockingQueue<Boolean>()
        val client = OkHttpClient.Builder().eventListener(object : EventListener() {
            override fun callFailed(call: Call, ioe: IOException) { failed.add(call.isCanceled()) }
        }).build()
        server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.NO_RESPONSE))
        val provider = DashScopeVoiceProvider("test", server.url("/api/v1").toString(), null, client)
        val task = async(start = CoroutineStart.UNDISPATCHED) {
            provider.synthesize(VoiceOutputRequest("Hello", "qwen3-tts-flash"))
        }
        assertNotNull(server.takeRequest(1, TimeUnit.SECONDS))
        task.cancel()
        assertTrue(runCatching { task.await() }.exceptionOrNull() is CancellationException)
        assertEquals(true, failed.poll(1, TimeUnit.SECONDS))
    }

    @Test fun `native URLs preserve an explicitly configured proxy prefix`() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(401))
        val provider = DashScopeVoiceProvider("test", server.url("/gateway/compatible-mode").toString(), null)
        runCatching { provider.synthesize(VoiceOutputRequest("Hello", "qwen3-tts-flash")) }
        assertEquals("/gateway/api/v1/services/aigc/multimodal-generation/generation",
            server.takeRequest(1, TimeUnit.SECONDS)!!.path)
    }

    @Test fun `factory and voice seeds recognize regional and workspace URLs`() {
        for (base in listOf("https://dashscope.aliyuncs.com/compatible-mode/v1",
            "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
            "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1")) {
            val instance = ProviderInstance(id = "test", label = "Test", providerType = ProviderType.openAI,
                credentialType = ProviderCredential.apiKey, customBaseURL = base)
            assertTrue(VoiceProviderFactory.make(instance, null) is DashScopeVoiceProvider)
            assertEquals(setOf("paraformer-realtime-v2", "cosyvoice-v2", "qwen3-tts-flash"),
                VoiceProviderTemplate.mockEntries(instance).map { it.baseModel.id }.toSet())
        }
    }
}
