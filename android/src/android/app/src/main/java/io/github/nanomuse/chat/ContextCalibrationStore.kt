package io.github.nanomuse.chat

import android.content.Context
import android.content.SharedPreferences
import java.security.MessageDigest
import org.json.JSONObject

/** Durable numeric estimates isolated by provider route/configuration and model identity. */
class ContextCalibrationStore(private val preferences: SharedPreferences) {
    constructor(context: Context) : this(
        context.applicationContext.getSharedPreferences("nm_context_calibration", Context.MODE_PRIVATE),
    )

    fun load(providerKey: String, modelId: String): ContextEstimate.Calibration {
        val snapshot = runCatching {
            val saved = preferences.getString(key(providerKey, modelId), null) ?: return@runCatching null
            val json = JSONObject(saved)
            ContextEstimate.Snapshot(
                version = json.getInt("version"),
                scale = json.getDouble("scale"),
                samples = json.getInt("samples"),
            ).takeIf { it.isValid() }
        }.getOrNull()
        return ContextEstimate.Calibration(snapshot ?: ContextEstimate.Snapshot())
    }

    fun save(providerKey: String, modelId: String, calibration: ContextEstimate.Calibration) {
        val snapshot = calibration.snapshot()
        val value = JSONObject()
            .put("version", snapshot.version)
            .put("scale", snapshot.scale)
            .put("samples", snapshot.samples)
            .toString()
        preferences.edit().putString(key(providerKey, modelId), value).apply()
    }

    private fun key(providerKey: String, modelId: String): String {
        // Length prefixes avoid ambiguous pairs; hashing keeps route identities out of prefs.
        val identity = "${providerKey.length}:$providerKey${modelId.length}:$modelId"
        val digest = MessageDigest.getInstance("SHA-256").digest(identity.toByteArray(Charsets.UTF_8))
        return "v${ContextEstimate.CALIBRATION_VERSION}:" +
            digest.joinToString("") { "%02x".format(it.toInt() and 0xff) }
    }
}
