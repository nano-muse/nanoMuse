package io.github.nanomuse.chat

import com.openminis.app.data.model.AgentContentPart
import com.openminis.app.data.model.AgentToolDefinition
import com.openminis.app.data.model.LLMMessage
import java.security.MessageDigest

/** Reuse measured input only while its complete outgoing prefix is still unchanged. */
class ContextUsageMeter {
    class Request internal constructor(
        internal val configuration: String,
        internal val messages: List<String>,
    )

    private data class Observation(val request: Request, val usage: ContextEstimate.UsageAnchor)
    private var observation: Observation? = null

    /** A known server input count must not be overruled by a calibration-only overflow probe. */
    @Volatile
    var lastEstimateUsedAnchor: Boolean = false
        private set

    /**
     * Capture before sending, not after collecting a response. JSONObject and image bytes can
     * be mutable even inside immutable message lists, so identity/equality is insufficient.
     * Only hashes are retained. [requestVariant] covers serializer switches such as thinking.
     */
    fun snapshot(
        routeKey: String,
        modelId: String,
        messages: List<LLMMessage>,
        systemPrompt: String? = null,
        tools: List<AgentToolDefinition> = emptyList(),
        requestVariant: String = "",
    ): Request {
        val configuration = Fingerprint().apply {
            field(routeKey)
            field(modelId)
            field(requestVariant)
            field(systemPrompt)
            field(tools.size.toString())
            tools.forEach { field(it.toOpenAIJson().toString()) }
        }.finish()
        return Request(configuration, messages.map(::messageFingerprint))
    }

    @Synchronized
    fun estimate(request: Request, localEstimate: Int, calibration: ContextEstimate.Calibration): Int {
        lastEstimateUsedAnchor = false
        val previous = observation
        if (previous != null) {
            val samePrefix = request.configuration == previous.request.configuration &&
                request.messages.size >= previous.request.messages.size &&
                previous.request.messages.indices.all { request.messages[it] == previous.request.messages[it] }
            if (samePrefix) {
                previous.usage.estimateAppendOnly(localEstimate, calibration)?.let {
                    lastEstimateUsedAnchor = true
                    return it
                }
            }
            // Do not revive an old anchor if a later request happens to restore the old text.
            observation = null
        }
        return calibration.estimate(localEstimate)
    }

    /** The caller observes only a completed successful stream's input usage, once. */
    @Synchronized
    fun observe(request: Request, actualInputTokens: Int, localInputEstimate: Int): Boolean {
        lastEstimateUsedAnchor = false
        if (actualInputTokens <= 0 || actualInputTokens == Int.MAX_VALUE ||
            localInputEstimate <= 0 || localInputEstimate == Int.MAX_VALUE
        ) {
            observation = null
            return false
        }
        observation = Observation(request, ContextEstimate.UsageAnchor(actualInputTokens, localInputEstimate))
        return true
    }

    @Synchronized
    fun clear() {
        observation = null
        lastEstimateUsedAnchor = false
    }

    private fun messageFingerprint(message: LLMMessage): String = Fingerprint().apply {
        field(message.role.value)
        field(message.content)
        field(message.reasoningContent)
        field(message.contentParts.size.toString())
        for (part in message.contentParts) {
            when (part) {
                is AgentContentPart.Text -> {
                    field("text")
                    field(part.text)
                }
                is AgentContentPart.ToolUse -> {
                    field("tool_use")
                    field(part.id)
                    field(part.name)
                    field(part.input.toString())
                    field(part.thoughtSignature)
                }
                is AgentContentPart.ToolResult -> {
                    field("tool_result")
                    field(part.id)
                    field(part.name)
                    field(part.content)
                    field(part.isError.toString())
                    bytes(part.imageData)
                    field(part.imageMimeType)
                    field(part.imageLinuxPath)
                }
                is AgentContentPart.ImageData -> {
                    field("image")
                    bytes(part.data)
                    field(part.mimeType)
                    field(part.linuxPath)
                    field(part.noVisionPlaceholder)
                }
            }
        }
        field(message.imageParts.size.toString())
        for (part in message.imageParts) {
            bytes(part.data)
            field(part.mimeType)
            field(part.linuxPath)
            field(part.noVisionPlaceholder)
        }
        field(message.audioParts.size.toString())
        for (part in message.audioParts) {
            field(part.format)
            field(part.base64Data)
        }
    }.finish()

    /** Length-delimited fields distinguish null, empty and differently partitioned payloads. */
    private class Fingerprint {
        private val digest = MessageDigest.getInstance("SHA-256")

        fun field(value: String?) = bytes(value?.toByteArray(Charsets.UTF_8))

        fun bytes(value: ByteArray?) {
            val length = value?.size ?: -1
            for (shift in 24 downTo 0 step 8) digest.update((length ushr shift).toByte())
            if (value != null) digest.update(value)
        }

        fun finish(): String = buildString(64) {
            val hex = "0123456789abcdef"
            for (byte in digest.digest()) {
                val value = byte.toInt() and 0xff
                append(hex[value ushr 4])
                append(hex[value and 0xf])
            }
        }
    }
}
