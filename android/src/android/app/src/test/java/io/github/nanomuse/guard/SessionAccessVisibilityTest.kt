package io.github.nanomuse.guard

import org.junit.Assert.*
import org.junit.Test

class SessionAccessVisibilityTest {
    @Test fun leavingARetainedTabRelocksOnExitEvenWithoutStoppingTheActivity() {
        val locks = SessionLocks(setOf("chat"), {}, { 0L })
        val visibility = SessionAccessVisibility { locks.leave(it, -1) }
        locks.authenticate("chat", true)
        visibility.update("chat", true)
        assertFalse(locks.isLocked("chat", -1))
        visibility.update("chat", false)
        visibility.update("chat", true)
        assertTrue(locks.isLocked("chat", -1))
    }

    @Test fun switchingConversationsAndDisposalRevokeOnlyTheDepartedLease() {
        val locks = SessionLocks(setOf("first", "second"), {}, { 0L })
        val visibility = SessionAccessVisibility { locks.leave(it, -1) }
        locks.authenticate("first", true)
        locks.authenticate("second", true)
        visibility.update("first", true)
        visibility.update("second", true)
        assertTrue(locks.isLocked("first", -1))
        assertFalse(locks.isLocked("second", -1))
        visibility.update(null, false)
        assertTrue(locks.isLocked("second", -1))
    }

    @Test fun hidingATabPreservesAConfiguredTimedLease() {
        var now = 0L
        val locks = SessionLocks(setOf("chat"), {}, { now })
        val visibility = SessionAccessVisibility { locks.leave(it, 30) }
        locks.authenticate("chat", true)
        visibility.update("chat", true)
        visibility.update("chat", false)
        assertFalse(locks.isLocked("chat", 30))
        now = 30_000L
        assertTrue(locks.isLocked("chat", 30))
    }
}
