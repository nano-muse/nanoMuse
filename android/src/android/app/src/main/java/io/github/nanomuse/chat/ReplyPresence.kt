package io.github.nanomuse.chat

/** One visible conversation, independent of navigation routes and retained tab composition. */
class ReplyPresence(private val present: (String) -> Unit, private val absent: (String) -> Unit) {
    private var current: String? = null

    fun update(sessionId: String?, visible: Boolean) {
        val next = sessionId?.takeIf { visible && it.isNotBlank() }
        if (next == current) return
        val previous = current
        current = next
        // Register the new chat first so switching never briefly stops its foreground service.
        next?.let(present)
        previous?.let(absent)
    }
}
