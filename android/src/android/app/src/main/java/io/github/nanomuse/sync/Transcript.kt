package io.github.nanomuse.sync

import org.json.JSONArray
import org.json.JSONObject

/** A local message row, as much of it as sync needs. */
data class LocalMessage(
    val id: String,
    val sessionId: String,
    val role: String,
    val partsJson: String,
    val createdAt: Long,
)

/** What one row contributes to the synced transcript. */
data class TranscriptItem(
    val messageId: String,
    val role: String,
    val text: String,
    val attachments: List<Attachment>,
    val createdAt: Long,
)

/**
 * Which rows of a local chat are the conversation, as the other devices should see it.
 *
 * OpenMinis stores one assistant row per model call (text and tool calls), tool results as
 * user rows, and the person's own message as a user row with text or pictures. The contract
 * syncs the person's messages and the final assistant text of each turn — not the steps in
 * between, not the tool output. A turn counts as finished when another message of the person
 * follows it, or when its last row is an assistant row that asks for no tool; the half-done
 * turn of a chat that is still running (or was stopped) is left for the next push.
 */
object Transcript {
    private val systemReminder = Regex("<system-reminder>.*?</system-reminder>", RegexOption.DOT_MATCHES_ALL)
    private const val CONTINUE_REMINDER = "The user stopped the previous response"

    private class Row(val m: LocalMessage) {
        val parts: List<JSONObject> = runCatching {
            val arr = JSONArray(m.partsJson)
            (0 until arr.length()).mapNotNull { arr.optJSONObject(it) }
        }.getOrDefault(emptyList())
        val text: String = parts.filter { it.optString("type") == "text" }
            .joinToString("\n") { systemReminder.replace(it.optString("value"), "").trim() }
            .trim()
        val attachments: List<Attachment> = parts.filter { it.optString("type") == "mediaRef" }.mapNotNull { p ->
            val v = p.optJSONObject("value") ?: return@mapNotNull null
            val name = v.optString("originalFileName").ifBlank { v.optString("relativePath").substringAfterLast('/') }
            if (name.isBlank()) null else Attachment(name, v.optString("mimeType").ifBlank { "application/octet-stream" }, 0)
        }
        val hasToolUse = parts.any { it.optString("type") == "toolUse" }
        val hasToolResult = parts.any { it.optString("type") == "toolResult" }
        val isUser = m.role.equals("user", true)
        val isAssistant = m.role.equals("assistant", true)
        /** The person wrote this (not a tool result, not the runtime's "continue" nudge). */
        val isPersons = isUser && !hasToolResult && (text.isNotEmpty() || attachments.isNotEmpty()) && !text.startsWith(CONTINUE_REMINDER)
    }

    fun items(messages: List<LocalMessage>): List<TranscriptItem> {
        val rows = messages.map(::Row)
        // segments: each starts at a message of the person; rows before the first one form their own
        val segments = mutableListOf<MutableList<Row>>()
        for (r in rows) {
            // A proactive assistant message starts its own turn, preserving the previous answer.
            val checkIn = r.isAssistant && io.github.nanomuse.feed.ChatCheckIns.isMessage(r.m.id)
            if (checkIn || r.isPersons || segments.isEmpty()) segments += mutableListOf(r) else segments.last() += r
        }
        val out = mutableListOf<TranscriptItem>()
        segments.forEachIndexed { i, seg ->
            val head = seg.first()
            if (head.isPersons) out += TranscriptItem(head.m.id, "user", head.text, head.attachments, head.m.createdAt)
            val last = seg.last()
            val finished = i < segments.lastIndex || (last.isAssistant && !last.hasToolUse)
            if (!finished) return@forEachIndexed
            val reply = seg.lastOrNull { it.isAssistant && it.text.isNotEmpty() } ?: return@forEachIndexed
            out += TranscriptItem(reply.m.id, "assistant", reply.text, emptyList(), reply.m.createdAt)
        }
        return out
    }

    /** The parts a pulled message is stored with: one text part (and a line per attachment name). */
    fun partsJson(text: String, attachmentLines: List<String>): String {
        val body = buildString {
            append(text)
            for (line in attachmentLines) {
                if (isNotEmpty()) append("\n\n")
                append(line)
            }
        }
        return JSONArray().put(JSONObject().put("type", "text").put("value", body)).toString()
    }
}
