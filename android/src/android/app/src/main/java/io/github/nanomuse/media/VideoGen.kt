package io.github.nanomuse.media

import android.graphics.Bitmap
import com.openminis.app.data.model.ProviderInstance
import com.openminis.app.data.model.normalizeModalities
import com.openminis.app.logging.AppLogger
import io.github.nanomuse.avatar.ImageGen
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.util.concurrent.TimeUnit

/**
 * Short clips through Alibaba Cloud Model Studio's asynchronous video API — Wan 2.2 Flash by
 * default, or one of the Wan video models (`model` is whatever the user picked or typed, so a
 * newer build works too). The user's provider key and host are reused: `POST {host}/api/v1/
 * services/aigc/video-generation/video-synthesis` with `X-DashScope-Async: enable` returns a
 * task, `GET {host}/api/v1/tasks/{id}` is polled until it succeeds, and the MP4 is downloaded.
 * A first frame is uploaded to Model Studio's free 48-hour temporary storage first
 * (`/api/v1/uploads`), because the video API takes URLs, not inline data.
 *
 * The families take different bodies: MiniMax wants `media[first_frame]`, `resolution`,
 * `ratio` and `duration`; Wan up to 2.6 wants `img_url`, `resolution`/`size` and — on wan2.6 and
 * 2.5 — a `duration`; Wan 2.7 speaks Model Studio's newer protocol, `media[first_frame]` with
 * `resolution` for a picture and `resolution` with `ratio` for words, `duration` 2–15 on both.
 * Wan also splits text-to-video and image-to-video into sibling models
 * (`wan2.6-t2v` / `wan2.6-i2v`); whichever the user picked, the sibling is used for the other job.
 *
 * Costs are the user's: billing is per output second, so callers keep [imageToVideo]'s
 * `seconds` at the minimum that reads well (4 for an avatar loop).
 */
object VideoGen {
    private const val TAG = "VideoGen"
    private const val POLL_MS = 10_000L
    private const val MAX_WAIT_MS = 12 * 60_000L

    data class Endpoint(val instance: ProviderInstance, val apiKey: String, val model: String) {
        val studioUrl: String? get() = if (model == RelayMediaPolicy.VIDEO && RelayMediaPolicy.isPublicCloud(host)) "$host/app/?video=wizshot" else null
        val instanceId: String get() = instance.id
        val label: String get() = instance.label
        /**
         * `https://….maas.aliyuncs.com`, `https://dashscope.aliyuncs.com` or nanoMuse Cloud's
         * `https://cloud.nanomuse.cn`, without the API path (the relay serves the same
         * `/api/v1/…` video paths as Model Studio, next to its OpenAI-shaped `/v1`).
         */
        val host: String get() = ImageGen.baseUrlOf(instance)
            .substringBefore("/compatible-mode").substringBefore("/api/v1").trimEnd('/').removeSuffix("/v1")
    }

    class VideoGenException(message: String) : IOException(message)

    sealed class Progress {
        object Uploading : Progress()
        object Submitted : Progress()
        data class Running(val elapsedSec: Int) : Progress()
        object Downloading : Progress()
    }

    fun speaksDashScope(baseUrl: String): Boolean = baseUrl.contains("aliyuncs.com") || baseUrl.contains("dashscope")

    /**
     * The video models Model Studio serves through this API, as of this build. Its `/models`
     * list does not mention them (that list is the chat side), so these are the candidates
     * [probe] checks against the user's key; the first is the recommended one.
     */
    val KNOWN_DASHSCOPE_MODELS = listOf(
        "wan2.2-i2v-flash",
        "wan2.7-i2v", "wan2.7-t2v",
        "MiniMax/MiniMax-H3",
        "wan2.6-i2v", "wan2.6-t2v",
        "wan2.5-i2v-preview", "wan2.5-t2v-preview",
        "wan2.2-i2v-plus", "wan2.2-t2v-plus",
    )

    /** Names that mean "video" in a provider's model list. */
    fun looksLikeVideoModel(id: String): Boolean {
        val s = id.lowercase()
        return s == RelayMediaPolicy.VIDEO || listOf("t2v", "i2v", "video", "minimax-h", "hailuo", "kling", "veo", "seedance", "sora").any { s.contains(it) }
    }

    /**
     * Whether a model entry makes video: the entry says so (`video` among its output
     * modalities — a hand-added entry can be marked that way in its details, whatever its
     * name) or the name does ([looksLikeVideoModel]). Model Studio's `/models` list carries
     * no modalities and no video models at all, so for what a provider lists the name is the
     * only clue.
     */
    fun isVideoEntry(id: String, outputModalities: List<String>?): Boolean =
        "video" in outputModalities.normalizeModalities().orEmpty() || looksLikeVideoModel(id)

    /**
     * Whether [model] exists for this key, without making a video: an empty task is submitted
     * and Model Studio answers 404 "Model not exist" for an unknown name, or accepts the task
     * (which then fails at once on the missing prompt — nothing is billed). Null when the
     * host could not be asked.
     */
    fun probe(host: String, apiKey: String, model: String): Boolean? {
        val body = JSONObject().put("model", model).put("input", JSONObject()).put("parameters", JSONObject())
        val req = Request.Builder()
            .url("$host/api/v1/services/aigc/video-generation/video-synthesis")
            .header("Authorization", "Bearer $apiKey")
            .header("Content-Type", "application/json")
            .header("X-DashScope-Async", "enable")
            .post(body.toString().toRequestBody("application/json".toMediaType()))
            .build()
        return try {
            http.newCall(req).execute().use { resp ->
                val text = resp.body?.string().orEmpty()
                when {
                    resp.isSuccessful -> true
                    resp.code == 404 || text.contains("Model not exist", ignoreCase = true) -> false
                    resp.code == 401 || resp.code == 403 -> null
                    // Accepted the model name but not the empty body: the model is there.
                    resp.code == 400 -> true
                    else -> null
                }
            }
        } catch (e: IOException) {
            AppLogger.warning(TAG, "probe $model: ${e.message}")
            null
        }
    }

    private fun isWan(model: String) = model.startsWith("wan", ignoreCase = true)

    /** Wan 2.7 (`wan2.7-i2v`, `wan2.7-t2v`, their dated snapshots): the newer protocol. */
    internal fun isWan27(model: String) = model.startsWith("wan2.7", ignoreCase = true)

    /**
     * The Wan sibling for the job: `…-i2v…` when starting from a picture, `…-t2v…` from words.
     * Wan 2.2 has no text-to-video Flash: its Plus is the sibling there. Wan 2.7's dated snapshots
     * differ between the two (`wan2.7-t2v-2026-06-12`, `wan2.7-i2v-2026-04-25`), so the sibling
     * there is the undated id, which Model Studio keeps current.
     */
    internal fun modelFor(model: String, fromImage: Boolean): String = when {
        !isWan(model) -> model
        isWan27(model) -> (if (fromImage) "i2v" else "t2v").let { kind -> if (model.contains(kind, ignoreCase = true)) model else "wan2.7-$kind" }
        fromImage -> model.replace("t2v", "i2v")
        model.startsWith("wan2.2") -> "wan2.2-t2v-plus"
        else -> model.replace("i2v", "t2v")
    }

    /** Wan 2.2 is priced by resolution (480P is half of 720P) and the avatar's clips are small; the newer Wans start at 720P. */
    internal fun wanResolution(model: String): String = if (model.startsWith("wan2.2")) "480P" else "720P"

    /** Wan 2.2 has a fixed length; 2.5 takes 5 or 10; 2.6 anything from 2 to 15. MiniMax 4–15. */
    private fun durationFor(model: String, seconds: Int): Int? = when {
        model.startsWith("wan2.2") -> null
        model.startsWith("wan2.5") -> if (seconds <= 7) 5 else 10
        isWan(model) -> seconds.coerceIn(2, 15)
        else -> seconds.coerceIn(4, 15)
    }

    private val http: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(120, TimeUnit.SECONDS)
            .writeTimeout(120, TimeUnit.SECONDS)
            .build()
    }

    /** A clip that starts from [image]. Returns the MP4 bytes. */
    suspend fun imageToVideo(
        ep: Endpoint,
        image: Bitmap,
        prompt: String,
        seconds: Int = 4,
        onProgress: (Progress) -> Unit = {},
    ): ByteArray = withContext(Dispatchers.IO) {
        ep.studioUrl?.let { throw VideoGenException(it) }
        onProgress(Progress.Uploading)
        val model = modelFor(ep.model, fromImage = true)
        val png = pngBytes(fitFrame(image))
        val ossUrl = uploadTemp(ep.copy(model = model), png, "first-frame.png", "image/png")
        val task = createTask(ep, imageToVideoBody(model, ossUrl, prompt, seconds), ossInput = true)
        onProgress(Progress.Submitted)
        val url = poll(ep, task, onProgress)
        onProgress(Progress.Downloading)
        download(url)
    }

    /** A clip from words alone. [ratio] is one of 16:9, 9:16, 1:1, 4:3, 3:4, 21:9. */
    suspend fun textToVideo(
        ep: Endpoint,
        prompt: String,
        seconds: Int = 4,
        ratio: String = "1:1",
        onProgress: (Progress) -> Unit = {},
    ): ByteArray = withContext(Dispatchers.IO) {
        ep.studioUrl?.let { throw VideoGenException(it) }
        val model = modelFor(ep.model, fromImage = false)
        val task = createTask(ep, textToVideoBody(model, prompt, seconds, ratio), ossInput = false)
        onProgress(Progress.Submitted)
        val url = poll(ep, task, onProgress)
        onProgress(Progress.Downloading)
        download(url)
    }

    /** The body of an image-to-video task, as the families want it; [model] is already the sibling for the job. */
    internal fun imageToVideoBody(model: String, ossUrl: String, prompt: String, seconds: Int): JSONObject {
        val input = JSONObject().put("prompt", prompt)
        val parameters = JSONObject().put("watermark", false)
        when {
            isWan27(model) -> {
                input.put("media", JSONArray().put(JSONObject().put("type", "first_frame").put("url", ossUrl)))
                parameters.put("resolution", "720P")
            }
            isWan(model) -> {
                input.put("img_url", ossUrl)
                parameters.put("resolution", wanResolution(model))
            }
            else -> {
                input.put("media", JSONArray().put(JSONObject().put("type", "first_frame").put("url", ossUrl)))
                parameters.put("resolution", "768P")
            }
        }
        durationFor(model, seconds)?.let { parameters.put("duration", it) }
        return JSONObject().put("model", model).put("input", input).put("parameters", parameters)
    }

    /** The body of a text-to-video task. Wan 2.7 has 16:9, 9:16, 1:1, 4:3 and 3:4, so 21:9 becomes 16:9 there. */
    internal fun textToVideoBody(model: String, prompt: String, seconds: Int, ratio: String): JSONObject {
        val parameters = JSONObject().put("watermark", false)
        when {
            isWan27(model) -> parameters.put("resolution", "720P").put("ratio", if (ratio == "21:9") "16:9" else ratio)
            isWan(model) -> parameters.put("size", wanSize(ratio))
            else -> parameters.put("resolution", "768P").put("ratio", ratio)
        }
        durationFor(model, seconds)?.let { parameters.put("duration", it) }
        return JSONObject().put("model", model).put("input", JSONObject().put("prompt", prompt)).put("parameters", parameters)
    }

    /** Wan text-to-video takes a pixel size instead of a ratio; 720p-class frames for each ratio. */
    private fun wanSize(ratio: String): String = when (ratio) {
        "16:9" -> "1280*720"
        "9:16" -> "720*1280"
        "4:3" -> "960*720"
        "3:4" -> "720*960"
        "21:9" -> "1680*720"
        else -> "960*960"
    }

    // ── the protocol ──────────────────────────────────────────────────────

    /** Model Studio's temporary storage: a signed OSS policy, then a multipart POST. Returns the `oss://` URL. */
    internal fun uploadTemp(ep: Endpoint, bytes: ByteArray, name: String, mime: String): String {
        val policyReq = Request.Builder()
            .url("${ep.host}/api/v1/uploads?action=getPolicy&model=${ep.model}")
            .header("Authorization", "Bearer ${ep.apiKey}")
            .get()
            .build()
        val policy = http.newCall(policyReq).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) throw VideoGenException("Upload policy failed (HTTP ${resp.code})" + apiMessage(text))
            JSONObject(text).optJSONObject("data") ?: throw VideoGenException("Upload policy: no data")
        }
        val key = policy.getString("upload_dir") + "/" + name
        val form = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("OSSAccessKeyId", policy.getString("oss_access_key_id"))
            .addFormDataPart("Signature", policy.getString("signature"))
            .addFormDataPart("policy", policy.getString("policy"))
            .addFormDataPart("x-oss-object-acl", policy.optString("x_oss_object_acl", "private"))
            .addFormDataPart("x-oss-forbid-overwrite", policy.optString("x_oss_forbid_overwrite", "true"))
            .addFormDataPart("key", key)
            .addFormDataPart("file", name, bytes.toRequestBody(mime.toMediaType()))
            .build()
        http.newCall(Request.Builder().url(policy.getString("upload_host")).post(form).build()).execute().use { resp ->
            if (!resp.isSuccessful) throw VideoGenException("Upload failed (HTTP ${resp.code})")
        }
        return "oss://$key"
    }

    private fun createTask(ep: Endpoint, body: JSONObject, ossInput: Boolean): String {
        val req = Request.Builder()
            .url("${ep.host}/api/v1/services/aigc/video-generation/video-synthesis")
            .header("Authorization", "Bearer ${ep.apiKey}")
            .header("Content-Type", "application/json")
            .header("X-DashScope-Async", "enable")
            .apply { if (ossInput) header("X-DashScope-OssResourceResolve", "enable") }
            .post(body.toString().toRequestBody("application/json".toMediaType()))
            .build()
        return http.newCall(req).execute().use { resp ->
            val text = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) {
                AppLogger.warning(TAG, "create HTTP ${resp.code}: ${text.take(300)}")
                throw VideoGenException("HTTP ${resp.code}" + apiMessage(text))
            }
            val json = runCatching { JSONObject(text) }.getOrElse { throw VideoGenException("Unreadable response") }
            json.optJSONObject("output")?.optString("task_id")?.takeIf { it.isNotBlank() }
                ?: throw VideoGenException(json.optString("message").ifBlank { "No task id" })
        }
    }

    private suspend fun poll(ep: Endpoint, taskId: String, onProgress: (Progress) -> Unit): String {
        val started = System.currentTimeMillis()
        while (true) {
            delay(POLL_MS)
            val req = Request.Builder()
                .url("${ep.host}/api/v1/tasks/$taskId")
                .header("Authorization", "Bearer ${ep.apiKey}")
                .get()
                .build()
            val json = http.newCall(req).execute().use { resp ->
                val text = resp.body?.string().orEmpty()
                if (!resp.isSuccessful) throw VideoGenException("Task query failed (HTTP ${resp.code})" + apiMessage(text))
                runCatching { JSONObject(text) }.getOrElse { throw VideoGenException("Unreadable task") }
            }
            val out = json.optJSONObject("output") ?: JSONObject()
            when (out.optString("task_status")) {
                "SUCCEEDED" -> return out.optString("video_url").takeIf { it.isNotBlank() } ?: throw VideoGenException("No video URL")
                "FAILED", "CANCELED", "UNKNOWN" -> throw VideoGenException(failureMessage(out))
            }
            val elapsed = ((System.currentTimeMillis() - started) / 1000).toInt()
            onProgress(Progress.Running(elapsed))
            if (System.currentTimeMillis() - started > MAX_WAIT_MS) throw VideoGenException("Timed out after ${elapsed / 60} min")
        }
    }

    private fun download(url: String): ByteArray =
        http.newCall(Request.Builder().url(url).get().build()).execute().use { resp ->
            if (!resp.isSuccessful) throw VideoGenException("Video download failed (${resp.code})")
            resp.body?.bytes()?.takeIf { it.isNotEmpty() } ?: throw VideoGenException("Empty video")
        }

    /** The user-facing reason from a failed task; the activation message gets a plainer wording. */
    internal fun failureMessage(output: JSONObject): String {
        val code = output.optString("code")
        val message = output.optString("message")
        return when {
            message.contains("not activated", ignoreCase = true) ->
                "The video model is not activated on this account — open the model's card in the Model Studio console and activate it"
            message.isNotBlank() -> if (code.isNotBlank()) "$code: $message" else message
            code.isNotBlank() -> code
            else -> "Video task ${output.optString("task_status").ifBlank { "failed" }}"
        }
    }

    /** DashScope puts the message at the top; the nanoMuse relay answers OpenAI-shaped (`error.message`, e.g. the clip allowance). */
    private fun apiMessage(text: String): String =
        runCatching {
            val json = JSONObject(text)
            json.optString("message").ifBlank { json.optJSONObject("error")?.optString("message").orEmpty() }
        }.getOrNull()?.takeIf { it.isNotBlank() }?.let { ": $it" } ?: ""

    /** The API wants 256–5760 px on each side and an aspect within [0.4, 2.5]; a face is square, so only size matters. */
    private fun fitFrame(image: Bitmap): Bitmap {
        val max = 1024
        val min = 256
        val longest = maxOf(image.width, image.height)
        val shortest = minOf(image.width, image.height)
        return when {
            longest > max -> {
                val s = max.toFloat() / longest
                Bitmap.createScaledBitmap(image, (image.width * s).toInt().coerceAtLeast(min), (image.height * s).toInt().coerceAtLeast(min), true)
            }
            shortest < min -> {
                val s = min.toFloat() / shortest
                Bitmap.createScaledBitmap(image, (image.width * s).toInt(), (image.height * s).toInt(), true)
            }
            else -> image
        }
    }

    private fun pngBytes(bitmap: Bitmap): ByteArray =
        ByteArrayOutputStream().also { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }.toByteArray()
}
