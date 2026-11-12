package io.github.nanomuse.hub

import android.content.Context
import io.github.nanomuse.cloud.NanoMuseCloud
import io.github.nanomuse.sync.RemoteDeviceRoute
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

/** Only send() dispatches a turn. Reopening a chat can query but never dispatch it again. */
internal class DeviceConversations(
    private val devices: () -> List<Device>,
    private val load: () -> String,
    private val persist: (String) -> Unit,
    private val invoke: (String, String, JSONObject) -> JSONObject,
) {

    fun list(): List<JSONObject> = synchronized(lock) { read() }

    fun draft(id: String): String = find(id).optString("draft")

    fun saveDraft(id: String, text: String) {
        update { rows ->
            rows.onEach { chat -> if (chat.getString("id") == id) chat.put("draft", text) }
        }
    }

    /** Clear only the submitted draft; edits made while the target works are newer data. */
    fun clearDraftIfUnchanged(id: String, submitted: String) {
        update { rows ->
            rows.onEach { chat ->
                if (chat.getString("id") == id && chat.optString("draft") == submitted) chat.put("draft", "")
            }
        }
    }

    fun create(device: Device): JSONObject {
        if (devices().none { it.id == device.id }) throw HubException("not_found", "The device is no longer on this account")
        val chat = JSONObject().put("id", UUID.randomUUID().toString()).put("device", device.id)
            .put("name", device.name).put("kind", device.kind).put("turns", JSONArray())
        update { it + chat }
        return chat
    }

    fun send(id: String, text: String): JSONObject {
        val chat = find(id)
        val route = RemoteDeviceRoute.resolve(text, devices())
        if (route == RemoteDeviceRoute.Ambiguous) throw HubException("usage", "More than one device has that name")
        val mention = route as? RemoteDeviceRoute.Selected
        val device = mention?.device?.id ?: chat.getString("device")
        val remoteConversation = if (mention == null) id else UUID.randomUUID().toString()
        requireDevice(device)
        val prompt = (mention?.text ?: text).trim()
        require(prompt.isNotBlank())
        val turn = UUID.randomUUID().toString()
        var first = false
        update { rows ->
            rows.onEach { chat ->
                if (chat.getString("id") == id) {
                    if (pending(chat) != null) throw HubException("busy", "Resolve the previous turn before sending another")
                    if (mention == null && turns(chat).any { !it.has("destination") && it.optString("error") == "context_lost" }) {
                        throw HubException("context_lost", "Start a new conversation on this device")
                    }
                    val turns = chat.getJSONArray("turns")
                    first = mention != null || turns(chat).all { it.has("destination") || it.optBoolean("rejectedBeforeAcceptance") }
                    val entry = JSONObject().put("id", turn).put("text", text.trim()).put("state", "unknown")
                    mention?.let {
                        entry.put("destination", JSONObject().put("id", device).put("name", it.device.name).put("conversation", remoteConversation))
                    }
                    turns.put(entry)
                }
            }
        }
        try {
            val result = call(device, "task", args(remoteConversation, turn).put("text", prompt).put("new_conversation", first).put("stream", true))
            reconcile(id, turn, result)
        } catch (error: HubException) {
            if (error.code in definiteFailures) reconcile(id, turn, JSONObject().put("state", "failed").put("error", error.code), rejectedBeforeAcceptance = true)
        }
        return find(id)
    }

    fun refresh(id: String): Pair<JSONObject, List<JSONObject>> {
        val chat = find(id)
        val entry = pending(chat) ?: return chat to emptyList()
        val turn = entry.getString("id")
        val device = target(chat, entry)
        requireDevice(device)
        val result = call(device, "task.status", args(conversation(chat, entry), turn))
        reconcile(id, turn, result)
        return find(id) to objects(result.optJSONArray("events"))
    }

    fun stop(id: String): Boolean {
        val chat = find(id)
        val turn = pending(chat) ?: return false
        return call(target(chat, turn), "stop", args(conversation(chat, turn), turn.getString("id"))).optBoolean("stopped")
    }

    fun approve(id: String, approvalId: String, allow: Boolean) {
        val chat = find(id)
        val turn = pending(chat) ?: return
        call(target(chat, turn), "approve", JSONObject().put("approval_id", approvalId).put("allow", allow))
    }

    private fun call(device: String, action: String, args: JSONObject): JSONObject = invoke(device, action, args)

    private fun find(id: String): JSONObject = list().first { it.getString("id") == id }

    private fun requireDevice(id: String) {
        val target = devices().find { it.id == id }
        if (target?.online != true) throw HubException("device_offline", "The destination is offline")
        if ("task.status" !in target.actions) throw HubException("unknown_action", "The destination does not support persistent conversations")
    }

    private fun read(): List<JSONObject> = objects(JSONArray(load()))

    private fun update(change: (List<JSONObject>) -> List<JSONObject>) = synchronized(lock) {
        val next = change(read())
        persist(JSONArray(next).toString())
    }

    private fun reconcile(id: String, turn: String, result: JSONObject, rejectedBeforeAcceptance: Boolean = false) {
        val state = result.optString("state")
        if (state !in states) return
        update { rows ->
            rows.onEach { chat ->
                if (chat.getString("id") == id) turns(chat).find { it.getString("id") == turn && unsettled(it) }?.let {
                    it.put("state", state)
                    if (rejectedBeforeAcceptance) it.put("rejectedBeforeAcceptance", true)
                    if (result.has("text")) it.put("answer", result.optString("text"))
                    if (result.has("error")) it.put("error", result.optString("error"))
                }
            }
        }
    }

    companion object {
        fun open(context: Context, account: String): DeviceConversations {
            val app = context.applicationContext
            val prefs = app.getSharedPreferences("nanomuse_device_conversations", Context.MODE_PRIVATE)
            fun checkAccount() {
                check(account.isNotBlank() && NanoMuseCloud.account(app)?.accountId == account) { "The account changed" }
            }
            return DeviceConversations(
                devices = { Hub.others(app) },
                load = { checkAccount(); prefs.getString(account, "[]").orEmpty() },
                persist = { snapshot ->
                    checkAccount()
                    check(prefs.edit().putString(account, snapshot).commit()) { "Could not save the conversation" }
                },
                invoke = { device, action, args ->
                    checkAccount()
                    Hub.call(device, action, args, timeoutMs = if (action == "task") 15 * 60_000L else 10_000L)
                },
            )
        }
        private val lock = Any()
        private val definiteFailures = setOf("not_allowed", "denied", "usage", "no_model", "not_ready", "context_lost", "busy")
        private val states = setOf("unknown", "accepted", "completed", "failed", "cancelled", "interrupted")
        private fun args(id: String, turn: String) = JSONObject().put("conversation", id).put("turn_id", turn)
        private fun objects(array: JSONArray?): List<JSONObject> =
            if (array == null) emptyList() else List(array.length()) { array.getJSONObject(it) }
        fun turns(chat: JSONObject): List<JSONObject> = objects(chat.getJSONArray("turns"))
        fun pending(chat: JSONObject): JSONObject? = turns(chat).lastOrNull(::unsettled)
        fun target(chat: JSONObject, turn: JSONObject?): String =
            turn?.optJSONObject("destination")?.getString("id") ?: chat.getString("device")
        private fun conversation(chat: JSONObject, turn: JSONObject): String =
            turn.optJSONObject("destination")?.getString("conversation") ?: chat.getString("id")
        private fun unsettled(turn: JSONObject): Boolean = turn.optString("state") in setOf("unknown", "accepted")
    }
}
