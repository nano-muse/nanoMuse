package io.github.nanomuse.guard

import android.content.Context
import android.os.SystemClock
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow

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
    private fun changed() { _revision.value++ }
}
