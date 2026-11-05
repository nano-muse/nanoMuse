package io.github.nanomuse.guard

import org.junit.Assert.*
import org.junit.Test

class AccessLeaseTest {
    @Test fun restartStartsLockedEvenWhenTimeoutIsNever() {
        assertFalse(AccessLease { 100 }.isUnlocked(0))
    }
    @Test fun unsuccessfulAuthenticationDoesNotUnlock() {
        val lease = AccessLease { 100 }
        lease.authenticate(false)
        assertFalse(lease.isUnlocked(0))
    }
    @Test fun successfulAuthenticationExpiresAtTheBoundary() {
        var now = 100L
        val lease = AccessLease { now }
        lease.authenticate(true)
        now += 29_999
        assertTrue(lease.isUnlocked(30))
        now++
        assertFalse(lease.isUnlocked(30))
    }
    @Test fun lockOnExitIsExplicitAndNeverTimeoutIsStillRevocable() {
        val lease = AccessLease { 100 }
        lease.authenticate(true)
        assertTrue(lease.isUnlocked(-1))
        lease.lock()
        assertFalse(lease.isUnlocked(0))
    }
    @Test fun appTimeoutMeasuresBackgroundRatherThanTimeSpentUsingTheApp() {
        var now = 100L
        val lease = AccessLease { now }
        lease.authenticate(true)
        now += 1_000_000
        lease.background()
        now += 29_999
        lease.foreground(30)
        assertTrue(lease.isUnlocked(0))
        lease.background()
        now += 30_000
        lease.foreground(30)
        assertFalse(lease.isUnlocked(0))
    }
    @Test fun shortSystemTransitionsDoNotRelockButRealExitDoes() {
        var now = 1L
        val lease = AccessLease { now }
        lease.authenticate(true)
        lease.background()
        now += 14_999
        lease.foreground(-1)
        assertTrue(lease.isUnlocked(0))
        lease.background()
        now += 15_000
        lease.foreground(-1)
        assertFalse(lease.isUnlocked(0))
    }
}
