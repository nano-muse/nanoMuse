package io.github.nanomuse.hub

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.Executors

class PersistentTurnsTest {
    private val fixture = JSONObject(checkNotNull(javaClass.getResourceAsStream("/hub-turn-contract.json")).bufferedReader().use { it.readText() })
    private val owner = TurnOwner("account-a", "phone-a", fixture.getString("conversation"))
    private val turn = fixture.getString("turn")
    private val other = fixture.getString("other")

    @Test fun durableAcceptanceAndResultRecovery() {
        var disk = "{}"
        val store = PersistentTurns(disk) { disk = it }
        assertTrue(store.accept(owner, turn) { "session-a" }.accepted)
        assertEquals(fixture.getJSONObject("accepted").toString(), store.status(owner, turn).toString())
        assertEquals(fixture.getJSONObject("interrupted").toString(), PersistentTurns(disk) {}.status(owner, turn).toString())
        store.finish(owner, turn, fixture.getJSONObject("completed"))
        val reopened = PersistentTurns(disk) {}
        assertEquals("one answer", reopened.status(owner, turn)?.getString("text"))
        assertFalse(reopened.accept(owner, turn) { error("must not create or execute again") }.accepted)
        assertNull(reopened.status(owner.copy(caller = "phone-b"), turn))
        assertNull(reopened.status(owner.copy(account = "account-b"), turn))
        assertEquals("session-a", reopened.accept(owner, other) { error("must reuse context") }.session)
    }

    @Test fun concurrentDuplicateIsAcceptedOnce() {
        val store = PersistentTurns("{}") {}
        val pool = Executors.newFixedThreadPool(2)
        try {
            val results = List(2) { pool.submit<Boolean> { store.accept(owner, turn) { "session-a" }.accepted } }
            assertEquals(1, results.count { it.get() })
            assertEquals("busy", runCatching { store.accept(owner, other) { "session-b" } }
                .exceptionOrNull()?.let { (it as HubActions.Refused).code })
        } finally {
            pool.shutdownNow()
        }
    }

    @Test fun aWriteFailureDoesNotAcknowledgeAcceptance() {
        val store = PersistentTurns("{}") { error("write failed") }
        assertTrue(runCatching { store.accept(owner, turn) { "session-a" } }.isFailure)
        assertNull(store.status(owner, turn))
    }

    @Test fun liveProgressReplacesPartialTextAndExpiresApproval() {
        var now = 0L
        val live = LiveTurn("call") { now }
        live.record(JSONObject().put("stage", "text").put("text", "one").put("partial", true))
        live.record(JSONObject().put("stage", "text").put("text", "one two").put("partial", true))
        live.record(JSONObject().put("stage", "approval").put("approval_id", "one").put("timeout", 2))
        assertEquals("one two", live.events().getJSONObject(0).getString("text"))
        assertEquals(2, live.events().length())
        now = 2000L
        assertEquals(1, live.events().length())
    }
}
