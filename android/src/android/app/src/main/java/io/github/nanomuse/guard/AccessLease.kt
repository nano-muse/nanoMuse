package io.github.nanomuse.guard

/** Monotonic, process-local authentication lease, shared by app and session access. */
class AccessLease(private val clock: () -> Long) {
    companion object {
        const val BACKGROUND_GRACE_SECONDS = 15
    }

    private var unlockedAt: Long? = null
    private var backgroundedAt: Long? = null
    fun authenticate(success: Boolean) { if (success) unlockedAt = clock() }
    fun lock() { unlockedAt = null }
    fun isUnlocked(timeoutSeconds: Int): Boolean {
        val at = unlockedAt ?: return false
        return timeoutSeconds <= 0 || clock() - at < timeoutSeconds * 1000L
    }
    fun background() { if (backgroundedAt == null) backgroundedAt = clock() }
    fun foreground(timeoutSeconds: Int) {
        val leftAt = backgroundedAt ?: return
        backgroundedAt = null
        val seconds = if (timeoutSeconds == -1) BACKGROUND_GRACE_SECONDS else timeoutSeconds
        if (seconds != 0 && clock() - leftAt >= seconds * 1000L) lock()
    }
}
