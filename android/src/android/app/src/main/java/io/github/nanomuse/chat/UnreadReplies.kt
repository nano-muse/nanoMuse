package io.github.nanomuse.chat

/** Separate from persisted pause badges: an unread completion belongs to this process. */
class UnreadReplies(private val changed: (Set<String>) -> Unit = {}) {
    private val running = mutableSetOf<String>()
    var ids: Set<String> = emptySet()
        private set
    @Synchronized fun started(id: String) { running += id }
    @Synchronized fun finished(id: String, success: Boolean, visible: Boolean) {
        if (!running.remove(id)) return
        if (success && !visible) { ids = ids + id; changed(ids) }
    }
    @Synchronized fun opened(id: String) { ids = ids - id; changed(ids) }
    @Synchronized fun removed(id: String) { running -= id; opened(id) }
}
