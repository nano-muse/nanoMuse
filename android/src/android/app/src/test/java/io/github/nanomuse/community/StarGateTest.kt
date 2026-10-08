package io.github.nanomuse.community

import io.github.nanomuse.community.StarPrompt.Ask
import io.github.nanomuse.community.StarPrompt.Gate
import io.github.nanomuse.community.StarPrompt.Ledger
import io.github.nanomuse.community.StarPrompt.Moment
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class StarGateTest {

    private val policy = Nudges.Policy.DEFAULT
    private val day = 24L * 60 * 60 * 1000
    private val now = 1_800_000_000_000L

    @Test
    fun `a fresh phone may be asked at every moment the policy lists`() {
        val fresh = Ledger()
        assertTrue(Gate.due(policy, fresh, Ask(Moment.SIGNED_IN), now))
        assertTrue(Gate.due(policy, fresh, Ask(Moment.TASKS, 3), now))
        assertTrue(Gate.due(policy, fresh, Ask(Moment.NEW_LOOK), now))
        assertTrue(Gate.due(policy, fresh, Ask(Moment.EXHAUSTED), now))
        assertTrue(Gate.due(policy, fresh, Ask(Moment.DAYS_USED, 7), now))
        assertTrue(Gate.due(policy, fresh, Ask(Moment.GOAL_DONE), now))
    }

    @Test
    fun `counted moments fire only at the listed counts`() {
        assertNull(Gate.taskAsk(policy, 1))
        assertNull(Gate.taskAsk(policy, 2))
        assertEquals(Ask(Moment.TASKS, 3), Gate.taskAsk(policy, 3))
        assertNull(Gate.taskAsk(policy, 4))
        assertEquals(Ask(Moment.TASKS, 10), Gate.taskAsk(policy, 10))
        assertEquals(Ask(Moment.TASKS, 30), Gate.taskAsk(policy, 30))
        assertNull(Gate.dayAsk(policy, 6))
        assertEquals(Ask(Moment.DAYS_USED, 7), Gate.dayAsk(policy, 7))
        assertEquals(Ask(Moment.DAYS_USED, 30), Gate.dayAsk(policy, 30))
        // The first task is never a moment any more.
        assertFalse(Gate.due(policy, Ledger(), Ask(Moment.TASKS, 1), now))
    }

    @Test
    fun `each ask is spent once, per count for the counted ones`() {
        val after3 = Ledger(asks = 1, lastAskAt = now - 30 * day, shown = setOf("tasks_3"))
        assertFalse(Gate.due(policy, after3, Ask(Moment.TASKS, 3), now))
        assertTrue(Gate.due(policy, after3, Ask(Moment.TASKS, 10), now))
        assertEquals("tasks_3", Ask(Moment.TASKS, 3).key)
        assertEquals("days_used_7", Ask(Moment.DAYS_USED, 7).key)
        assertEquals("signed_in", Ask(Moment.SIGNED_IN).key)
    }

    @Test
    fun `enabled=false silences every ask`() {
        val off = policy.copy(enabled = false)
        Moment.values().forEach { m ->
            val ask = if (m == Moment.TASKS) Ask(m, 3) else if (m == Moment.DAYS_USED) Ask(m, 7) else Ask(m)
            assertFalse(m.name, Gate.due(off, Ledger(), ask, now))
        }
    }

    @Test
    fun `a moment the operator switched off stays quiet, the others still ask`() {
        val p = policy.copy(moments = policy.moments.copy(signedIn = false, goalDone = false, tasks = listOf(5)))
        assertFalse(Gate.due(p, Ledger(), Ask(Moment.SIGNED_IN), now))
        assertFalse(Gate.due(p, Ledger(), Ask(Moment.GOAL_DONE), now))
        assertFalse(Gate.due(p, Ledger(), Ask(Moment.TASKS, 3), now))
        assertTrue(Gate.due(p, Ledger(), Ask(Moment.TASKS, 5), now))
        assertTrue(Gate.due(p, Ledger(), Ask(Moment.NEW_LOOK), now))
    }

    @Test
    fun `the cooldown keeps asks a week apart`() {
        val justAsked = Ledger(asks = 1, lastAskAt = now - 2 * day, shown = setOf("signed_in"))
        assertFalse(Gate.due(policy, justAsked, Ask(Moment.TASKS, 3), now))
        val weekLater = justAsked.copy(lastAskAt = now - 7 * day)
        assertTrue(Gate.due(policy, weekLater, Ask(Moment.TASKS, 3), now))
        // A policy with no cooldown asks back to back.
        assertTrue(Gate.due(policy.copy(cooldownDays = 0), justAsked, Ask(Moment.TASKS, 3), now))
    }

    @Test
    fun `the lifetime cap ends the asks, Not now included`() {
        val capped = Ledger(asks = 4, lastAskAt = now - 60 * day, shown = setOf("signed_in", "tasks_3", "tasks_10", "new_look"))
        assertFalse(Gate.due(policy, capped, Ask(Moment.TASKS, 30), now))
        assertFalse(Gate.due(policy, capped, Ask(Moment.GOAL_DONE), now))
        assertTrue(Gate.due(policy.copy(maxAsks = 5), capped, Ask(Moment.GOAL_DONE), now))
    }

    @Test
    fun `a tap on the star, or I already starred, ends every ask for good`() {
        // starred with nothing ever shown: what "I already starred" on the first card leaves behind
        val starred = Ledger(starred = true)
        assertEquals(0, starred.asks)
        assertFalse(Gate.due(policy, starred, Ask(Moment.TASKS, 3), now))
        assertFalse(Gate.due(policy, starred, Ask(Moment.EXHAUSTED), now))
        val generous = policy.copy(cooldownDays = 0, maxAsks = 99)
        Moment.values().forEach { m ->
            val ask = if (m == Moment.TASKS) Ask(m, 3) else if (m == Moment.DAYS_USED) Ask(m, 7) else Ask(m)
            assertFalse(m.name, Gate.due(generous, starred, ask, now + 365 * day))
        }
    }

    @Test
    fun `a task is a turn the person started after the naming is over`() {
        assertTrue(Gate.countsAsTask(personStarted = true, firstConversationOver = true))
        // Still naming the agent: nothing counts, however the turn started.
        assertFalse(Gate.countsAsTask(personStarted = true, firstConversationOver = false))
        // Routines, the feed, goal checks: not the person's turns.
        assertFalse(Gate.countsAsTask(personStarted = false, firstConversationOver = true))
        assertFalse(Gate.countsAsTask(personStarted = false, firstConversationOver = false))
    }

    @Test
    fun `the day counter moves once per calendar day`() {
        assertEquals(1, Gate.nextDays(0, null, "2026-10-05"))
        assertEquals(1, Gate.nextDays(1, "2026-10-05", "2026-10-05"))
        assertEquals(2, Gate.nextDays(1, "2026-10-05", "2026-10-06"))
        assertEquals(7, Gate.nextDays(6, "2026-09-01", "2026-10-06"))
    }
}
