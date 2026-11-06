package io.github.nanomuse.chat

import com.openminis.app.data.model.AgentContentPart
import com.openminis.app.data.model.AgentToolDefinition
import com.openminis.app.data.model.LLMMessage
import com.openminis.app.data.model.LLMUsage
import kotlin.math.ceil

/**
 * A conservative request-size estimate, not a tokenizer or a provider's bill.
 *
 * ASCII costs about one token per four characters. Non-ASCII BMP code points cost two,
 * and supplementary code points four, so Chinese and emoji do not inherit an English-only
 * character divisor. [Calibration] adapts this heuristic to measured provider input usage.
 * Images use the caller's counter, independently of their byte size.
 */
object ContextEstimate {
    private const val MESSAGE_OVERHEAD = 3
    private const val REPLY_OVERHEAD = 3

    /** Cached tokens still occupy context, even if the provider reports fresh input separately. */
    fun inputTokens(usage: LLMUsage): Int = maxOf(
        usage.latestContextTokens.coerceAtLeast(0),
        add(usage.inputTokens, usage.cacheReadInputTokens ?: 0, usage.cacheCreationInputTokens ?: 0),
    )

    fun text(text: String): Int {
        var quarters = 0L
        var index = 0
        while (index < text.length) {
            val codePoint = Character.codePointAt(text, index)
            quarters += when {
                codePoint < 0x80 -> 1L
                codePoint <= 0xffff -> 8L
                else -> 16L
            }
            if (quarters >= Int.MAX_VALUE.toLong() * 4) return Int.MAX_VALUE
            index += Character.charCount(codePoint)
        }
        return ((quarters + 3) / 4).toInt()
    }

    fun part(part: AgentContentPart, imageTokens: (ByteArray) -> Int): Int = when (part) {
        is AgentContentPart.Text -> text(part.text)
        is AgentContentPart.ToolUse -> add(
            MESSAGE_OVERHEAD,
            text(part.id),
            text(part.name),
            text(part.input.toString()),
            text(part.thoughtSignature.orEmpty()),
        )
        is AgentContentPart.ToolResult -> add(
            MESSAGE_OVERHEAD,
            text(part.id),
            text(part.name),
            text(part.content),
            image(part.imageData, imageTokens),
        )
        is AgentContentPart.ImageData -> image(part.data, imageTokens)
    }

    fun request(
        messages: List<LLMMessage>,
        systemPrompt: String? = null,
        tools: List<AgentToolDefinition> = emptyList(),
        imageTokens: (ByteArray) -> Int = { 1000 },
    ): Int {
        var total = REPLY_OVERHEAD
        if (!systemPrompt.isNullOrEmpty()) total = add(total, MESSAGE_OVERHEAD, text(systemPrompt))
        for (message in messages) {
            total = add(total, MESSAGE_OVERHEAD, text(message.reasoningContent.orEmpty()))
            // Providers serialize structured parts instead of the aggregate content string.
            // Counting both would charge the assistant's visible text twice.
            if (message.contentParts.isEmpty()) {
                total = add(total, text(message.content))
            } else {
                for (contentPart in message.contentParts) total = add(total, part(contentPart, imageTokens))
            }
            for (imagePart in message.imageParts) total = add(total, image(imagePart.data, imageTokens))
            // Native audio is not tokenized as its base64 transport text. Keep the previous
            // audio boundary: its model-dependent cost is known only from provider usage.
        }
        for (tool in tools) total = add(total, text(tool.toOpenAIJson().toString()))
        return total
    }

    private fun image(bytes: ByteArray?, imageTokens: (ByteArray) -> Int): Int =
        if (bytes == null || bytes.isEmpty()) 0 else imageTokens(bytes).coerceAtLeast(0)

    private fun add(vararg counts: Int): Int {
        var total = 0L
        for (count in counts) {
            total += count.coerceAtLeast(0)
            if (total >= Int.MAX_VALUE) return Int.MAX_VALUE
        }
        return total.toInt()
    }

    const val CALIBRATION_VERSION = 1
    private const val MIN_CALIBRATION_SCALE = 0.25
    private const val MAX_CALIBRATION_SCALE = 4.0
    private const val MIN_CALIBRATION_INPUT = 128
    private const val CALIBRATION_WEIGHT = 0.25

    /** Only numeric calibration state is persisted, never a conversation or provider credential. */
    data class Snapshot(
        val version: Int = CALIBRATION_VERSION,
        val scale: Double = 1.0,
        val samples: Int = 0,
    ) {
        fun isValid(): Boolean = version == CALIBRATION_VERSION && scale.isFinite() &&
            scale in MIN_CALIBRATION_SCALE..MAX_CALIBRATION_SCALE && samples >= 0
    }

    /**
     * A provider/model-specific, smoothed ratio. Both upward and downward corrections are
     * needed: a single large ratio must not leave every future request permanently "full".
     * Call once with the completed response's input usage and the exact request estimate.
     * Ignore tiny inputs, saturated counts and implausible ratios rather than persisting them.
     */
    class Calibration(snapshot: Snapshot = Snapshot()) {
        private var state = snapshot.takeIf { it.isValid() } ?: Snapshot()

        @Synchronized
        fun observe(actualTokens: Int, localEstimate: Int): Boolean {
            if (actualTokens <= 0 || actualTokens == Int.MAX_VALUE ||
                localEstimate < MIN_CALIBRATION_INPUT || localEstimate == Int.MAX_VALUE
            ) return false
            val observed = actualTokens.toDouble() / localEstimate
            if (observed !in MIN_CALIBRATION_SCALE..MAX_CALIBRATION_SCALE) return false
            state = Snapshot(
                scale = state.scale + CALIBRATION_WEIGHT * (observed - state.scale),
                samples = (state.samples.toLong() + 1).coerceAtMost(Int.MAX_VALUE.toLong()).toInt(),
            )
            return true
        }

        @Synchronized
        fun estimate(localEstimate: Int): Int {
            val scaled = localEstimate.coerceAtLeast(0).toDouble() * state.scale
            return if (scaled >= Int.MAX_VALUE) Int.MAX_VALUE else ceil(scaled).toInt()
        }

        @Synchronized
        fun snapshot(): Snapshot = state

        @Synchronized
        fun reset() {
            state = Snapshot()
        }
    }

    /**
     * An input usage anchor for an unchanged request prefix. The caller must discard it after
     * compaction, offload, prompt/schema changes, image rewriting or a provider/model switch.
     * It is deliberately not persisted. Appended assistant/tool messages are charged as a
     * delta, so a conservative heuristic cannot override the server's known prefix size.
     */
    data class UsageAnchor(val actualInputTokens: Int, val localInputEstimate: Int) {
        fun estimateAppendOnly(currentLocalEstimate: Int, calibration: Calibration): Int? {
            if (actualInputTokens <= 0 || actualInputTokens == Int.MAX_VALUE ||
                localInputEstimate <= 0 || localInputEstimate == Int.MAX_VALUE ||
                currentLocalEstimate < localInputEstimate
            ) return null
            return add(actualInputTokens, calibration.estimate(currentLocalEstimate - localInputEstimate))
        }
    }
}
