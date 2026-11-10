package io.github.nanomuse.hub

import org.json.JSONArray
import org.json.JSONObject

/** Live progress is recoverable while the process is running; terminal results live on disk. */
internal class LiveTurn(val callId: String, private val now: () -> Long = { System.nanoTime() / 1_000_000 }) {
    private data class Approval(val event: JSONObject, val expiresAt: Long)
    private val recent = ArrayDeque<JSONObject>()
    private val approvals = linkedMapOf<String, Approval>()

    @Synchronized fun record(event: JSONObject) {
        val serialized = event.toString()
        if (serialized.length > 4000) return
        val snapshot = JSONObject(serialized)
        when (snapshot.optString("stage")) {
            "approval" -> {
                val seconds = snapshot.optLong("timeout")
                val id = snapshot.optString("approval_id")
                if (seconds in 1..3600 && id.isNotBlank()) approvals[id] = Approval(snapshot, now() + seconds * 1000)
            }
            "approval_result" -> approvals.remove(snapshot.optString("approval_id"))
            "thinking", "tool", "tool_result", "text" -> {
                if (snapshot.optString("stage") == "text" && recent.lastOrNull()?.optBoolean("partial") == true) recent.removeLast()
                recent.addLast(snapshot)
                if (recent.size > 8) recent.removeFirst()
            }
        }
    }

    @Synchronized fun events(): JSONArray {
        val time = now()
        val pending = approvals.values.filter { it.expiresAt > time }.takeLast(4).map {
            JSONObject(it.event.toString()).put("timeout", (it.expiresAt - time + 999) / 1000)
        }
        return JSONArray(recent.map { JSONObject(it.toString()) } + pending)
    }
}
