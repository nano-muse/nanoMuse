package io.github.nanomuse.hands

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class HandsCurrentRunTest {
    @Test
    fun chatStopOnlyReachesTheRunOwnedByThatSession() {
        val reasons = mutableListOf<String>()
        val target = HandsStopTarget { reasons += it }
        Hands.setActive(false)
        assertTrue(Hands.claim())
        try {
            Hands.attachCurrent(target, "chat-a", "run-a")
            assertFalse(Hands.stopCurrentForSession("chat-b"))
            assertTrue(Hands.stopCurrentForSession("chat-a", "from chat a"))
            assertEquals(listOf("from chat a"), reasons)
        } finally {
            Hands.releaseCurrent(target)
            Hands.setActive(false)
        }
    }

    @Test
    fun lateReleaseCannotDetachANewerOwner() {
        val old = HandsStopTarget {}
        var stopped = false
        val current = HandsStopTarget { stopped = true }
        Hands.setActive(false)
        assertTrue(Hands.claim())
        try {
            Hands.attachCurrent(old, "old-chat", "old-run")
            Hands.attachCurrent(current, "new-chat", "new-run")
            Hands.releaseCurrent(old)
            assertTrue(Hands.stopCurrentForSession("new-chat"))
            assertTrue(stopped)
        } finally {
            Hands.releaseCurrent(current)
            Hands.setActive(false)
        }
    }
}
