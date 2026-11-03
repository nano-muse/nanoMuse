package io.github.nanomuse.cloud

import com.openminis.app.data.model.LLMModel
import org.json.JSONObject

/** Capacity disclosed by the endpoint serving this exact model. */
object ModelCapacity {
    fun apply(model: LLMModel, item: JSONObject): LLMModel = model.copy(
        contextWindow = positive(item.opt("context_length")) ?: model.contextWindow,
        maxOutputTokens = positive(item.opt("max_output_tokens")) ?: model.maxOutputTokens,
    )

    private fun positive(value: Any?): Int? = when (value) {
        is Int -> value.takeIf { it > 0 }
        is Long -> value.takeIf { it in 1..Int.MAX_VALUE.toLong() }?.toInt()
        else -> null
    }
}
