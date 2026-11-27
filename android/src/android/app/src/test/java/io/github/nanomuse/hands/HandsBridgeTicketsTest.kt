package io.github.nanomuse.hands

import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class HandsBridgeTicketsTest {
    @Test fun oneCorrectClaimBeforeExpiryAndNoReplay() {
        val permits = HandsBridgeTickets()
        permits.issue("first", 100)
        assertNull(permits.consume("other", 101))
        val claim = permits.consume("first", 102)
        assertNotNull(claim)
        assertTrue(permits.current(claim!!))
        assertNull(permits.consume("first", 103))
        permits.issue("second", 200)
        assertFalse(permits.current(claim))
        assertNull(permits.consume("second", 90_200))
    }

    @Test fun disconnectRevokesBothUnusedAndInFlightClaims() {
        val permits = HandsBridgeTickets()
        permits.issue("unused", 10)
        permits.clear()
        assertNull(permits.consume("unused", 11))
        permits.issue("in flight", 12)
        val claim = permits.consume("in flight", 13)!!
        permits.clear()
        assertFalse(permits.current(claim))
    }
}
