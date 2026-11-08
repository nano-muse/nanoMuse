package io.github.nanomuse.hub

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class DeviceConversationsTest {
    @Test fun recoveringAnUncertainTurnOnlyQueriesTheOriginalTarget() {
        var disk = "[]"
        val actions = mutableListOf<String>()
        val desk = Device("desk", "Desk", "computer", "", "", true, listOf("task", "task.status"), 0)
        var sent: JSONObject? = null
        var savedAtDispatch: String? = null
        fun reopen() = DeviceConversations(
            devices = { listOf(desk) },
            load = { disk },
            persist = { disk = it },
            invoke = { target, action, args ->
                assertEquals(desk.id, target)
                actions.add(action)
                if (action == "task") {
                    sent = args
                    savedAtDispatch = JSONArray(disk).getJSONObject(0).getJSONArray("turns").getJSONObject(0).getString("id")
                    throw HubException("disconnected", "connection lost")
                }
                assertEquals(sent?.getString("turn_id"), args.getString("turn_id"))
                assertEquals(sent?.getString("conversation"), args.getString("conversation"))
                JSONObject().put("state", "completed").put("text", "recovered answer")
            },
        )
        val chat = reopen().create(desk).getString("id")
        val uncertain = reopen().send(chat, "run once")
        assertEquals(sent?.getString("turn_id"), savedAtDispatch)
        assertEquals("unknown", DeviceConversations.pending(uncertain)?.getString("state"))
        val recovered = DeviceConversations.turns(reopen().refresh(chat).first)
        assertEquals(1, recovered.size)
        assertEquals("recovered answer", recovered.single().getString("answer"))
        reopen().refresh(chat)
        assertEquals(listOf("task", "task.status"), actions)
    }
}
