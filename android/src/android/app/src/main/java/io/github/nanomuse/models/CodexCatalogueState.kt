package io.github.nanomuse.models

import android.content.SharedPreferences
import java.security.MessageDigest
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.flowOn

class CodexCatalogueState(private val prefs: SharedPreferences) {
    private fun ownerKey(id: String) = "codex_menu_owner_$id"
    private fun fallbackKey(id: String) = "codex_menu_fallback_$id"

    private fun fingerprint(accountId: String) = MessageDigest.getInstance("SHA-256")
        .digest(accountId.toByteArray()).joinToString("") { "%02x".format(it) }

    fun hasLiveFor(id: String, accountId: String?): Boolean =
        !accountId.isNullOrBlank() && prefs.getString(ownerKey(id), null) == fingerprint(accountId)

    fun recordLive(id: String, accountId: String?) {
        prefs.edit().putString(ownerKey(id), accountId?.takeIf { it.isNotBlank() }?.let(::fingerprint))
            .remove(fallbackKey(id)).apply()
    }

    fun recordFallback(id: String, keepSaved: Boolean) {
        val edit = prefs.edit().putBoolean(fallbackKey(id), true)
        if (!keepSaved) edit.remove(ownerKey(id))
        edit.apply()
    }

    fun remove(id: String) {
        prefs.edit().remove(ownerKey(id)).remove(fallbackKey(id)).apply()
    }

    fun fallback(id: String): Flow<Boolean> = callbackFlow {
        val key = fallbackKey(id)
        val listener = SharedPreferences.OnSharedPreferenceChangeListener { _, changed ->
            if (changed == key || changed == null) trySend(prefs.getBoolean(key, false))
        }
        prefs.registerOnSharedPreferenceChangeListener(listener)
        trySend(prefs.getBoolean(key, false))
        awaitClose { prefs.unregisterOnSharedPreferenceChangeListener(listener) }
    }.flowOn(Dispatchers.IO)
}
