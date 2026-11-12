package io.github.nanomuse.hub

import org.json.JSONArray
import org.json.JSONObject

internal data class TurnOwner(val account: String, val caller: String, val conversation: String)

/** Commit the snapshot before publishing acceptance or a terminal result. */
internal class PersistentTurns(initial: String, private val write: (String) -> Unit) {
    private var journal = JSONObject(initial)
    private val live = mutableSetOf<Pair<String, String>>()
    private val uuid = Regex("[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")

    data class Reservation(val accepted: Boolean, val session: String, val result: JSONObject)

    private fun key(owner: TurnOwner, turn: String): String {
        if (owner.account.isBlank() || owner.caller.isBlank() ||
            !uuid.matches(owner.conversation) || !uuid.matches(turn)
        ) throw HubActions.Refused("usage", "A conversation UUID and turn UUID are required")
        return JSONArray(listOf(owner.account, owner.caller, owner.conversation)).toString()
    }

    @Synchronized fun status(owner: TurnOwner, turn: String): JSONObject? {
        val key = key(owner, turn)
        val result = journal.optJSONObject(key)?.optJSONObject("turns")?.optJSONObject(turn) ?: return null
        if (result.optString("state") == "accepted" && (key to turn) !in live) return state("interrupted")
        return JSONObject(result.toString())
    }

    @Synchronized fun accept(owner: TurnOwner, turn: String, create: () -> String): Reservation {
        val key = key(owner, turn)
        val prior = journal.optJSONObject(key)
        status(owner, turn)?.let { return Reservation(false, checkNotNull(prior).getString("session"), it) }
        if (live.any { it.first == key }) throw HubActions.Refused("busy", "This conversation is already running a turn")
        val session = prior?.getString("session") ?: create()
        val result = state("accepted")
        val next = JSONObject(journal.toString())
        val row = next.optJSONObject(key) ?: JSONObject().put("session", session).put("turns", JSONObject())
        row.getJSONObject("turns").put(turn, result)
        commit(next.put(key, row))
        live.add(key to turn)
        return Reservation(true, session, state("accepted"))
    }

    @Synchronized fun finish(owner: TurnOwner, turn: String, result: JSONObject) {
        val key = key(owner, turn)
        if ((key to turn) !in live) return
        try {
            val next = JSONObject(journal.toString())
            next.getJSONObject(key).getJSONObject("turns").put(turn, JSONObject(result.toString()))
            commit(next)
        } finally {
            live.remove(key to turn)
        }
    }

    private fun commit(next: JSONObject) {
        write(next.toString())
        journal = next
    }

    companion object {
        fun state(value: String): JSONObject = JSONObject().put("state", value)
    }
}
