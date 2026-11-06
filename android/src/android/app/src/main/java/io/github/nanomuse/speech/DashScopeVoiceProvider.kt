package io.github.nanomuse.speech

import com.openminis.app.provider.voice.VoiceInputRequest
import com.openminis.app.provider.voice.VoiceInputResponse
import com.openminis.app.provider.voice.VoiceOutputRequest
import com.openminis.app.provider.voice.VoiceOutputFormat
import com.openminis.app.provider.voice.VoiceProvider
import com.openminis.app.provider.voice.VoiceProviderException
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeout
import okhttp3.Call
import okhttp3.Callback
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import okio.ByteString.Companion.toByteString
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/** Native transports for the existing record-then-transcribe and read-aloud flows. */
open class DashScopeVoiceProvider(
    providerId: String,
    baseURL: String,
    apiKey: String?,
    private val client: OkHttpClient = VoiceProvider.httpClient,
    private val timeoutMillis: Long = 120_000,
) : VoiceProvider(providerId, baseURL, apiKey) {
    override fun defaultVoiceInputModel() = "paraformer-realtime-v2"
    override fun defaultVoiceOutputModel() = "cosyvoice-v2"
    override fun defaultVoiceOutputVoice() = "longxiaochun_v2"

    override fun preferredOutputFormat(model: String?) =
        if (model == "qwen3-tts-flash") VoiceOutputFormat.WAV else VoiceOutputFormat.MP3

    // Keep the selected region/workspace and any proxy prefix. Strip only known API suffixes.
    private fun endpoint(path: String): String {
        val url = baseURL.trimEnd('/').toHttpUrl()
        val prefix = url.encodedPath.trimEnd('/').let { original ->
            listOf("/compatible-mode/v1", "/compatible-mode", "/api/v1", "/v1")
                .firstOrNull { original.endsWith(it) }?.let { original.removeSuffix(it) }
                ?: original
        }
        return url.newBuilder().encodedPath(prefix + path).query(null).fragment(null).build().toString()
    }

    override suspend fun transcribe(request: VoiceInputRequest): VoiceInputResponse {
        val model = request.model ?: defaultVoiceInputModel()
        if (model != "paraformer-realtime-v2") {
            // Offline audio chat can retain its existing adapter. Realtime sessions cannot.
            if (!model.contains("realtime", ignoreCase = true) &&
                request.resolvedModel?.let(::usesChatBasedASR) == true
            ) return super.transcribe(request)
            throw VoiceProviderException.Unsupported(model)
        }
        if (request.audioData.isEmpty()) throw VoiceProviderException.NoAudioData()
        val parameters = JSONObject().put("format", "wav").put("sample_rate", 16000)
        iso6391(request.language)?.takeIf { it in setOf("zh", "en", "ja", "yue", "ko", "de", "fr", "ru") }
            ?.let { parameters.put("language_hints", JSONArray().put(it)) }
        val sentences = sortedMapOf<Long, String>()
        runTask("asr", "recognition", model, parameters, onStarted = { socket, id ->
            // The recorder supplies mono 16 kHz WAV. Bound frames so queue failure is observable.
            for (start in request.audioData.indices step 16_384) {
                send(socket, request.audioData.toByteString(start, minOf(16_384, request.audioData.size - start)))
            }
            send(socket, command("finish-task", id, JSONObject().put("input", JSONObject())))
        }, onResult = { payload ->
            payload.optJSONObject("output")?.optJSONObject("sentence")?.let { sentence ->
                if (sentence.optBoolean("sentence_end") && !sentence.optBoolean("heartbeat")) {
                    sentences[sentence.getLong("begin_time")] = sentence.getString("text")
                }
            }
        })
        return VoiceInputResponse(sentences.values.joinToString(""))
    }

    override suspend fun synthesize(request: VoiceOutputRequest): ByteArray {
        val model = request.model ?: defaultVoiceOutputModel()
        if (model == "qwen3-tts-flash") return qwenSpeech(request, model)
        if (model != "cosyvoice-v2") throw VoiceProviderException.Unsupported(model)
        if (request.responseFormat == VoiceOutputFormat.AAC) throw VoiceProviderException.Unsupported("aac")
        val voice = request.voice?.takeUnless {
            it.isBlank() || it == model || it == "longxiaochun"
        } ?: defaultVoiceOutputVoice()
        val parameters = JSONObject().put("text_type", "PlainText").put("voice", voice)
            .put("format", request.responseFormat.wireValue).put("sample_rate", 22050)
        request.speed?.let { parameters.put("rate", it.coerceIn(0.5f, 2.0f).toDouble()) }
        val output = ByteArrayOutputStream()
        runTask("tts", "SpeechSynthesizer", model, parameters, onStarted = { socket, id ->
            send(socket, command("continue-task", id, JSONObject().put("input", JSONObject().put("text", request.input))))
            send(socket, command("finish-task", id, JSONObject().put("input", JSONObject())))
        }, onAudio = { bytes ->
            if (output.size() + bytes.size > MAX_AUDIO_BYTES) throw VoiceProviderException.Parse("audio size")
            output.write(bytes.toByteArray())
        })
        return output.toByteArray().takeIf { it.isNotEmpty() } ?: throw VoiceProviderException.NoAudioData()
    }

    private suspend fun qwenSpeech(request: VoiceOutputRequest, model: String): ByteArray = withTimeout(timeoutMillis) {
        // This HTTP API provides a WAV file and has no format-conversion request parameter.
        if (request.responseFormat != VoiceOutputFormat.WAV) {
            throw VoiceProviderException.Unsupported(request.responseFormat.wireValue)
        }
        val voice = request.voice?.takeUnless { it.isBlank() || it == model } ?: "Cherry"
        val body = JSONObject().put("model", model).put("input", JSONObject()
            .put("text", request.input).put("voice", voice).put("language_type", "Auto"))
        val builder = Request.Builder().url(endpoint("/api/v1/services/aigc/multimodal-generation/generation"))
            .post(body.toString().toRequestBody("application/json".toMediaType()))
        applyVoiceAuth(builder)
        val result = JSONObject(String(fetch(builder.build()), Charsets.UTF_8))
        if (result.optString("code").isNotEmpty()) throw VoiceProviderException.Parse(result.optString("code"))
        val audioUrl = result.optJSONObject("output")?.optJSONObject("audio")?.optString("url")
            ?.takeIf { it.isNotBlank() } ?: throw VoiceProviderException.NoAudioData()
        // The signed download URL is a separate request. Never send the provider credential to it.
        val download = Request.Builder().url(audioUrl).get().build()
        fetch(download).takeIf { it.isNotEmpty() } ?: throw VoiceProviderException.NoAudioData()
    }

    private suspend fun fetch(request: Request): ByteArray = suspendCancellableCoroutine { continuation ->
        val call = client.newCall(request)
        continuation.invokeOnCancellation { call.cancel() }
        call.enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                if (continuation.isActive) continuation.resumeWithException(e)
            }
            override fun onResponse(call: Call, response: Response) {
                val result = runCatching {
                    response.use {
                        if (it.code == 401 || it.code == 403) throw VoiceProviderException.Auth()
                        if (!it.isSuccessful) throw VoiceProviderException.Http(it.code, null)
                        val body = it.body ?: throw VoiceProviderException.NoAudioData()
                        val out = ByteArrayOutputStream()
                        body.byteStream().use { stream ->
                            val buffer = ByteArray(8192)
                            while (true) {
                                val count = stream.read(buffer)
                                if (count < 0) break
                                if (out.size() + count > MAX_AUDIO_BYTES) throw VoiceProviderException.Parse("audio size")
                                out.write(buffer, 0, count)
                            }
                        }
                        out.toByteArray()
                    }
                }
                if (continuation.isActive) continuation.resumeWith(result)
            }
        })
    }

    private suspend fun runTask(
        task: String,
        function: String,
        model: String,
        parameters: JSONObject,
        onStarted: (WebSocket, String) -> Unit,
        onResult: (JSONObject) -> Unit = {},
        onAudio: (ByteString) -> Unit = {},
    ) = withTimeout(timeoutMillis) {
        suspendCancellableCoroutine<Unit> { continuation ->
            val id = UUID.randomUUID().toString()
            val ended = AtomicBoolean(false)
            var started = false
            fun fail(socket: WebSocket, error: Throwable) {
                if (ended.compareAndSet(false, true)) {
                    socket.cancel()
                    continuation.resumeWithException(error)
                }
            }
            val builder = Request.Builder().url(endpoint("/api-ws/v1/inference"))
            applyVoiceAuth(builder)
            val socket = client.newWebSocket(builder.build(), object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) {
                    if (ended.get()) { webSocket.cancel(); return }
                    runCatching {
                        send(webSocket, command("run-task", id, JSONObject().put("task_group", "audio")
                            .put("task", task).put("function", function).put("model", model)
                            .put("parameters", parameters).put("input", JSONObject())))
                    }.onFailure { fail(webSocket, it) }
                }
                override fun onMessage(webSocket: WebSocket, text: String) {
                    if (ended.get()) return
                    runCatching {
                        val message = JSONObject(text)
                        val header = message.getJSONObject("header")
                        if (header.optString("task_id") != id) return
                        when (header.getString("event")) {
                            "task-started" -> if (!started) { started = true; onStarted(webSocket, id) }
                            "result-generated" -> if (started) onResult(message.getJSONObject("payload"))
                            "task-failed" -> throw VoiceProviderException.Parse(header.optString("error_code", "task-failed"))
                            "task-finished" -> {
                                if (!started) throw VoiceProviderException.Parse("task-finished")
                                if (ended.compareAndSet(false, true)) {
                                    webSocket.close(1000, null)
                                    continuation.resume(Unit)
                                }
                            }
                        }
                    }.onFailure { fail(webSocket, it) }
                }
                override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                    if (!ended.get() && started) runCatching { onAudio(bytes) }.onFailure { fail(webSocket, it) }
                }
                override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                    fail(webSocket, VoiceProviderException.Parse("WebSocket $code"))
                }
                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                    fail(webSocket, if (response?.code in listOf(401, 403)) VoiceProviderException.Auth() else t)
                }
            })
            continuation.invokeOnCancellation { ended.set(true); socket.cancel() }
        }
    }

    private fun command(action: String, id: String, payload: JSONObject) = JSONObject()
        .put("header", JSONObject().put("action", action).put("task_id", id).put("streaming", "duplex"))
        .put("payload", payload).toString()

    private fun send(socket: WebSocket, message: String) {
        if (!socket.send(message)) throw IOException("WebSocket send")
    }
    private fun send(socket: WebSocket, message: ByteString) {
        if (!socket.send(message)) throw IOException("WebSocket send")
    }

    private companion object {
        const val MAX_AUDIO_BYTES = 32 * 1024 * 1024
    }
}
