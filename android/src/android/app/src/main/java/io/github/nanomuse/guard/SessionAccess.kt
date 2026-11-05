package io.github.nanomuse.guard

import android.content.Context
import android.os.SystemClock
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update

/** Local-only metadata, deliberately separate from ChatSessionEntity and export/sync. */
object SessionAccess {
    private lateinit var state: SessionLocks
    private lateinit var prefs: android.content.SharedPreferences
    private val _protected = MutableStateFlow<Set<String>>(emptySet())
    val protected = _protected.asStateFlow()
    private val _revision = MutableStateFlow(0L)
    val revision = _revision.asStateFlow()
    val timeout get() = prefs.getInt("timeout", 300)
    @Synchronized fun initialize(context: Context) {
        if (::state.isInitialized) return
        prefs = context.applicationContext.getSharedPreferences("nanomuse_session_access", Context.MODE_PRIVATE)
        val ids = prefs.getStringSet("protected", emptySet()).orEmpty().toSet()
        state = SessionLocks(ids, { next ->
            check(prefs.edit().putStringSet("protected", next).commit())
            _protected.value = next
        }, SystemClock::elapsedRealtime)
        _protected.value = ids
    }
    fun isProtected(id: String) = id in _protected.value
    fun isLocked(id: String) = ::state.isInitialized && state.isLocked(id, timeout)
    fun requireUnlocked(id: String) {
        if (isLocked(id)) throw SecurityException("Device authentication required for protected conversation")
    }
    fun inheritProtection(sourceId: String, copyId: String) {
        if (isProtected(sourceId)) protect(copyId, true)
    }
    suspend fun protectPersisted(authenticated: Boolean, persist: suspend () -> String): String? {
        if (!authenticated || AppAccess.locked.value) return null
        return persist().also { protect(it, true) }
    }
    fun authorizeAction(id: String, authenticate: ((Boolean) -> Unit) -> Unit, action: () -> Unit) {
        val required = isLocked(id)
        authorize(required, authenticate) {
            if (required) this.authenticate(id, true)
            if (!isLocked(id)) action()
        }
    }
    /** Interactive backups ask once for the export, without unlocking every protected chat. */
    fun authorizeExport(includesChats: Boolean, authenticate: ((Boolean) -> Unit) -> Unit, action: () -> Unit) {
        authorize(includesChats && protected.value.any { isLocked(it) }, authenticate, action)
    }
    private fun authorize(required: Boolean, authenticate: ((Boolean) -> Unit) -> Unit, action: () -> Unit) {
        if (AppAccess.locked.value) return
        if (!required) { action(); return }
        authenticate { success ->
            if (success && !AppAccess.locked.value) action()
        }
    }
    fun protect(id: String, authenticated: Boolean) { state.protect(id, authenticated); changed() }
    fun unprotect(id: String, authenticated: Boolean) { state.unprotect(id, authenticated); changed() }
    fun authenticate(id: String, success: Boolean) { state.authenticate(id, success); changed() }
    fun leave(id: String) { state.leave(id, timeout); changed() }
    fun deleted(id: String) { if (::state.isInitialized) { state.deleted(id); changed() } }
    fun configureTimeout(seconds: Int, authenticated: Boolean) {
        if (!authenticated) return
        require(seconds in AppAccess.TIMEOUTS)
        check(prefs.edit().putInt("timeout", seconds).commit())
        changed()
    }
    private fun changed() { _revision.update { it + 1 } }
}
