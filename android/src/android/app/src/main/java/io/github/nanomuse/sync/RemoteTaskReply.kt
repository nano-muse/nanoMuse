package io.github.nanomuse.sync

import com.openminis.app.ui.chat.AssistantBlock
import com.openminis.app.ui.chat.ToolBlockStatus
import org.json.JSONObject

class RemoteTaskReply(private val deviceId: String) {
    var blocks: List<AssistantBlock> = emptyList()
        private set
    private var finished = false
    private var serial = 0
    val text: String get() = blocks.filter { it.isText }.joinToString("\n\n") { it.content }

    fun event(body: JSONObject) {
        if (finished) return
        when (body.optString("stage")) {
            "text" -> body.optString("text").takeIf { it.isNotBlank() }?.let(::setText)
            "tool" -> {
                val id = "$deviceId:${body.optString("id").ifBlank { "step-${serial++}" }}"
                if (blocks.any { it.id == id }) return
                blocks = blocks + AssistantBlock(
                    id = id, kind = "tool_use", toolName = body.optString("name"),
                    toolTitle = body.optString("summary").ifBlank { body.optString("name") },
                    toolStatus = ToolBlockStatus.RUNNING, startTimeMs = System.currentTimeMillis(),
                )
            }
            "tool_result" -> {
                val id = "$deviceId:${body.optString("id")}"
                blocks = blocks.map { block ->
                    if (block.id != id) block else block.copy(
                        content = body.optString("summary"),
                        toolStatus = if (body.optBoolean("ok", true)) ToolBlockStatus.SUCCESS else ToolBlockStatus.FAILED,
                        durationMs = (System.currentTimeMillis() - block.startTimeMs).coerceAtLeast(0),
                    )
                }
            }
        }
    }

    private fun setText(text: String) {
        val last = blocks.lastOrNull()
        blocks = if (last?.isText == true) blocks.dropLast(1) + last.copy(content = text)
        else blocks + AssistantBlock(id = "$deviceId:text-${serial++}", kind = "text", content = text)
    }

    fun finish(text: String, failed: Boolean = false, stopped: Boolean = false): Boolean {
        if (finished) return false
        finished = true
        blocks = blocks.map { block ->
            if (block.toolStatus != ToolBlockStatus.RUNNING) block else block.copy(
                toolStatus = if (failed) ToolBlockStatus.FAILED else ToolBlockStatus.CANCELLED,
                durationMs = (System.currentTimeMillis() - block.startTimeMs).coerceAtLeast(0),
            )
        }
        if (failed || stopped) blocks = blocks + AssistantBlock(id = "$deviceId:end-${serial++}", kind = "text", content = text)
        else setText(text)
        return true
    }
    companion object {
        fun answer(body: JSONObject): String? = body.optString("text").ifBlank { body.optString("answer") }.trim().takeIf { it.isNotEmpty() }
    }
}
