package io.github.nanomuse.models

import org.json.JSONObject
import java.util.Locale

/** Explicit OFF for verified hybrid models that otherwise default to thinking. */
object QwenThinking {
    // https://help.aliyun.com/zh/model-studio/deep-thinking documents the switch.
    // https://help.aliyun.com/zh/model-studio/qwen3-8-max lists the snapshot and its alias.
    // Keep exact IDs: other Qwen variants only support thinking and cannot accept false.
    private val hybridMaxModels = setOf(
        "qwen3.8-max",
        "qwen3.8-max-0902",
        "qwen3.8-max-2026-09-02",
    )

    fun applyOff(modelId: String, body: JSONObject) {
        if (modelId.lowercase(Locale.ROOT) !in hybridMaxModels) return
        body.put("enable_thinking", false)
        val extra = body.optJSONObject("extra_body") ?: JSONObject()
        extra.put("enable_thinking", false)
        body.put("extra_body", extra)
    }
}
