package io.github.nanomuse.guard

import org.junit.Assert.*
import org.junit.Test

class SessionLocksTest {
    @Test fun protectionPersistsButAuthenticationDoesNot() {
        var saved = emptySet<String>()
        val state = SessionLocks(emptySet(), { saved = it }, { 1 })
        state.protect("a", true)
        assertTrue(state.isLocked("a", 0))
        state.authenticate("a", true)
        assertFalse(state.isLocked("a", 0))
        assertTrue(SessionLocks(saved, {}, { 1 }).isLocked("a", 0))
    }
    @Test fun refusedAuthenticationCannotChangeProtection() {
        val state = SessionLocks(emptySet(), {}, { 1 })
        state.protect("a", false)
        assertTrue(state.ids.isEmpty())
        state.protect("a", true)
        state.authenticate("a", false)
        state.unprotect("a", false)
        assertTrue(state.isLocked("a", 0))
    }
    @Test fun unlocksAreIsolatedAndExpire() {
        var now = 1L
        val state = SessionLocks(setOf("a", "b"), {}, { now })
        state.authenticate("a", true)
        assertFalse(state.isLocked("a", 30))
        assertTrue(state.isLocked("b", 30))
        now += 30_000
        assertTrue(state.isLocked("a", 30))
    }
    @Test fun leavingLocksOnlyTheOnExitPolicy() {
        val state = SessionLocks(setOf("a", "b"), {}, { 1 })
        state.authenticate("a", true); state.authenticate("b", true)
        state.leave("a", -1); state.leave("b", 0)
        assertTrue(state.isLocked("a", -1))
        assertFalse(state.isLocked("b", 0))
    }
    @Test fun deletingConversationRemovesProtectionAndUnlockState() {
        var saved = setOf("a")
        val state = SessionLocks(saved, { saved = it }, { 1 })
        state.authenticate("a", true)
        state.deleted("a")
        assertTrue(saved.isEmpty())
        state.protect("a", true)
        assertTrue(state.isLocked("a", 0))
    }
}
