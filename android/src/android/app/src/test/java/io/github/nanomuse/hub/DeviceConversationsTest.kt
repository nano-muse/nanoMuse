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

    @Test fun aRejectedFirstTurnCanBeSentAfterCorrectingTheSetup() {
        for (rejection in listOf("no_model", "not_ready", "denied", "not_allowed", "busy", "usage")) {
            var disk = "[]"
            val calls = mutableListOf<JSONObject>()
            val desk = Device("desk", "Desk", "computer", "", "", true, listOf("task.status"), 0)
            fun reopen() = DeviceConversations(
                devices = { listOf(desk) }, load = { disk }, persist = { disk = it },
                invoke = { _, _, args ->
                    calls.add(args)
                    if (calls.size == 1) throw HubException(rejection, "correct the setup first")
                    assertTrue(args.getBoolean("new_conversation"))
                    JSONObject().put("state", "completed").put("text", "ready")
                },
            )
            val chat = reopen().create(desk).getString("id")
            assertEquals(rejection, DeviceConversations.turns(reopen().send(chat, "first"))[0].getString("error"))
            val retried = DeviceConversations.turns(reopen().send(chat, "try again"))[1]
            assertEquals("completed", retried.getString("state"))
            assertEquals("ready", retried.getString("answer"))
            assertNotEquals(calls[0].getString("turn_id"), calls[1].getString("turn_id"))
            assertEquals(calls[0].getString("conversation"), calls[1].getString("conversation"))
        }
    }

    @Test fun aFailedAcceptedTurnCannotRecreateItsMissingContext() {
        for (state in listOf("failed", "cancelled", "interrupted")) {
            var disk = "[]"
            val calls = mutableListOf<JSONObject>()
            val desk = Device("desk", "Desk", "computer", "", "", true, listOf("task.status"), 0)
            val service = DeviceConversations(
                devices = { listOf(desk) }, load = { disk }, persist = { disk = it },
                invoke = { _, _, args ->
                    calls.add(args)
                    if (calls.size == 1) JSONObject().put("state", state).put("error", "no_model")
                    else {
                        assertFalse(args.getBoolean("new_conversation"))
                        throw HubException("context_lost", "the saved context disappeared")
                    }
                },
            )
            val chat = service.create(desk).getString("id")
            service.send(chat, "first")
            assertEquals("context_lost", DeviceConversations.turns(service.send(chat, "follow up"))[1].getString("error"))
            try {
                service.send(chat, "another follow-up")
                fail("a lost context cannot be recreated")
            } catch (error: HubException) {
                assertEquals("context_lost", error.code)
            }
            assertEquals(2, calls.size)
        }
    }

    @Test fun anOfflineDestinationKeepsItsDraftWithoutDispatching() {
        var disk = "[]"
        var desk = Device("desk", "Desk", "computer", "", "", false, listOf("task", "task.status"), 0)
        val actions = mutableListOf<String>()
        fun reopen() = DeviceConversations(
            devices = { listOf(desk) }, load = { disk }, persist = { disk = it },
            invoke = { _, action, _ -> actions += action; JSONObject().put("state", "completed") },
        )
        val id = reopen().create(desk).getString("id")
        reopen().saveDraft(id, "keep this while the desktop is offline")

        val error = runCatching { reopen().send(id, "keep this while the desktop is offline") }.exceptionOrNull()

        assertEquals("device_offline", (error as HubException).code)
        assertTrue(actions.isEmpty())
        assertEquals("keep this while the desktop is offline", reopen().draft(id))
    }

    @Test fun boundConversationsKeepTheirStableDeviceAndSeparateRemoteContexts() {
        var disk = "[]"
        var desk = Device("desk-stable", "Office", "computer", "", "", true, listOf("task", "task.status"), 0)
        val sent = mutableListOf<Pair<String, JSONObject>>()
        val service = DeviceConversations(
            devices = { listOf(desk) }, load = { disk }, persist = { disk = it },
            invoke = { target, action, args ->
                assertEquals("desk-stable", target)
                assertEquals("task", action)
                sent += target to args
                JSONObject().put("state", "completed").put("text", "answer")
            },
        )
        val a = service.create(desk).getString("id")
        val b = service.create(desk).getString("id")
        desk = desk.copy(name = "Renamed Office")

        service.send(a, "context A")
        service.send(b, "context B")

        assertEquals("desk-stable", service.list().first { it.getString("id") == a }.getString("device"))
        assertEquals(setOf(a, b), sent.map { it.second.getString("conversation") }.toSet())
        assertNotEquals(sent[0].second.getString("conversation"), sent[1].second.getString("conversation"))
    }

}
