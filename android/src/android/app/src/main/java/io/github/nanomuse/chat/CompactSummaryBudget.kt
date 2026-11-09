package io.github.nanomuse.chat

import com.openminis.app.data.model.LLMError

/** Reserve the summary's output before deciding whether its transcript needs splitting. */
object CompactSummaryBudget {
    fun outputTokens(inputTokens: Int, contextWindow: Int, maxOutputTokens: Int): Int {
        // Match the normal budget's fallback when the model has no usable output limit.
        val requested = maxOutputTokens.takeIf { it > 0 } ?: 4_096
        // A small window still needs room for the prompt and transcript. For ordinary
        // windows, retain the same summary target even when the input approaches capacity.
        val output = minOf(8_192, requested, contextWindow / 2)
        if (output <= 0 || inputTokens > contextWindow - output) {
            throw LLMError.ProviderError("Compaction input exceeds context window")
        }
        return output
    }
}
