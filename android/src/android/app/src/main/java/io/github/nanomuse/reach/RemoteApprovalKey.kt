package io.github.nanomuse.reach

import org.json.JSONObject
import java.security.MessageDigest

/**
 * The complete structured identity of another device's `approval` event. A legacy event without
 * `grant_target` deliberately returns null: it may be allowed once, but cannot select or create
 * a conversation or standing grant.
 */
object RemoteApprovalKey {
    fun target(event: JSONObject): String? {
        val value = event.optJSONObject("grant_target") ?: return null
        if (value.opt("version") as? Int != 1) return null
        val tool = (value.opt("tool") as? String)?.trim() ?: return null
        val resource = value.opt("resource") as? String ?: return null
        val action = value.opt("action") as? String ?: return null
        if (tool.isEmpty() || tool.length > 200 || resource.length > 4096 ||
            !Regex("^sha256:[0-9a-f]{64}$").matches(action)
        ) return null
        return "task:v1:" + listOf(tool, resource, action).joinToString("|") { component(it) }
    }

    /** The same action on another device is a different capability. */
    fun scoped(deviceId: String, wireRisk: String, target: String): String =
        "remote:" + listOf(deviceId, wireRisk.lowercase(), target).joinToString("|") {
            component(it)
        }

    /** The wire shape emitted by this Android target for a newer asking device. */
    fun wire(tool: String, resource: String?, canonicalAction: String): JSONObject {
        val action = MessageDigest.getInstance("SHA-256")
            .digest("$tool\u0000$canonicalAction".toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }
        return JSONObject()
            .put("version", 1)
            .put("tool", tool)
            .put("resource", resource.orEmpty())
            .put("action", "sha256:$action")
    }

    /** Compatibility for clients that understand only the 1.0.6 string key. */
    fun legacyKey(tool: String, resource: String?, canonicalAction: String): String =
        listOf(tool, resource.orEmpty(), canonicalAction).joinToString(":")

    private fun component(value: String): String = "${value.toByteArray(Charsets.UTF_8).size}:$value"
}
