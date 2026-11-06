package io.github.nanomuse.chat

import com.openminis.app.data.model.AgentContentPart
import com.openminis.app.data.model.LLMMessage

/** User-request boundaries shared by checkpoints, replay budgets and active-task selection. */
object ContextTurns {
    /** A persisted Continue reminder is still continuation of the preceding real user turn. */
    fun isUserRequest(message: LLMMessage): Boolean {
        if (message.role != LLMMessage.Role.USER ||
            message.contentParts.any { it is AgentContentPart.ToolResult }
        ) return false
        // Never classify a real attachment or non-text payload as a synthetic reminder.
        if (message.imageParts.isNotEmpty() || message.audioParts.isNotEmpty() ||
            message.contentParts.any { it !is AgentContentPart.Text }
        ) return true
        val structuredText = message.contentParts.filterIsInstance<AgentContentPart.Text>()
            .joinToString("") { it.text }
        val texts = listOf(message.content, structuredText).filter { it.isNotBlank() }
        // Preserve the previous treatment of empty user messages. Only a positive match for
        // whole reminder blocks removes a boundary; neither the message nor its text is removed.
        return texts.isEmpty() || texts.any { !onlyReminders(it) }
    }

    private const val OPEN = "<system-reminder>"
    private const val CLOSE = "</system-reminder>"

    private fun onlyReminders(text: String): Boolean {
        var cursor = 0
        var found = false
        while (cursor < text.length) {
            while (cursor < text.length && text[cursor].isWhitespace()) cursor++
            if (cursor == text.length) return found
            if (!text.startsWith(OPEN, cursor)) return false
            val close = text.indexOf(CLOSE, cursor + OPEN.length)
            if (close < 0) return false
            // Scan one block at a time. A greedy regex could swallow actual user text
            // between two reminder blocks and incorrectly discard the user's boundary.
            cursor = close + CLOSE.length
            found = true
        }
        return found
    }
}
