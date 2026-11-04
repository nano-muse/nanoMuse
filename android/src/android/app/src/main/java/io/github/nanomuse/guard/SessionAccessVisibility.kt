package io.github.nanomuse.guard

/** Leaving a retained tab counts as leaving its conversation, even without an Activity stop. */
class SessionAccessVisibility(private val leave: (String) -> Unit) {
    private var visibleSession: String? = null

    fun update(sessionId: String?, visible: Boolean) {
        val next = sessionId?.takeIf { visible }
        if (next == visibleSession) return
        visibleSession?.let(leave)
        visibleSession = next
    }
}
