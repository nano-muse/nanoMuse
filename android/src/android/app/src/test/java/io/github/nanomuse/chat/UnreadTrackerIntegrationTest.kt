package io.github.nanomuse.chat

import com.openminis.app.service.SessionActivityTracker
import com.openminis.app.service.SessionBadgeStore
import org.junit.Assert.*
import org.junit.Test

class UnreadTrackerIntegrationTest {
    @Test fun parallelRunsKeepTheirActivityAndUnreadStateSeparate() {
        val first = "drawer-first"
        val second = "drawer-second"
        try {
            SessionActivityTracker.setActive(first)
            SessionActivityTracker.setActive(second)
            assertTrue(SessionActivityTracker.activeSessions.value.containsAll(listOf(first, second)))

            SessionActivityTracker.setInactive(first)
            assertFalse(first in SessionActivityTracker.activeSessions.value)
            assertTrue(second in SessionActivityTracker.activeSessions.value)
            assertTrue(first in SessionBadgeStore.unread.value)
            assertFalse(second in SessionBadgeStore.unread.value)

            SessionActivityTracker.setPresent(first)
            assertFalse(first in SessionBadgeStore.unread.value)
            assertTrue(second in SessionActivityTracker.activeSessions.value)

            SessionActivityTracker.markReplyIncomplete(second)
            SessionActivityTracker.setInactive(second)
            assertFalse(second in SessionActivityTracker.activeSessions.value)
            assertFalse(second in SessionBadgeStore.unread.value)
        } finally {
            SessionActivityTracker.setAbsent(first)
            for (id in listOf(first, second)) {
                SessionActivityTracker.markReplyIncomplete(id)
                SessionActivityTracker.setInactive(id)
                SessionBadgeStore.clear(id)
            }
        }
    }

    @Test fun backgroundCompletionIsPublishedOnceAndOpeningClearsIt() {
        val id = "unread-tracker-complete"
        SessionActivityTracker.setActive(id)
        SessionActivityTracker.setInactive(id)
        assertTrue(id in SessionBadgeStore.unread.value)
        SessionActivityTracker.setPresent(id)
        assertFalse(id in SessionBadgeStore.unread.value)
        SessionActivityTracker.setInactive(id)
        assertFalse(id in SessionBadgeStore.unread.value)
        SessionActivityTracker.setAbsent(id)
    }
    @Test fun cancellationAndFailureDoNotBecomeUnreadReplies() {
        val cancelled = "unread-tracker-cancelled"
        SessionActivityTracker.setActive(cancelled)
        SessionActivityTracker.markReplyIncomplete(cancelled)
        SessionActivityTracker.setInactive(cancelled)
        assertFalse(cancelled in SessionBadgeStore.unread.value)
        val failed = "unread-tracker-failed"
        SessionActivityTracker.setActive(failed)
        SessionActivityTracker.markStreamError(failed)
        SessionActivityTracker.setInactive(failed)
        assertFalse(failed in SessionBadgeStore.unread.value)
    }
    @Test fun visibleCompletionLeavesTheExistingPauseBadgeIntact() {
        val id = "unread-tracker-visible"
        SessionBadgeStore.push(id, SessionBadgeStore.SessionBadgeState.PAUSED)
        SessionActivityTracker.setPresent(id)
        SessionActivityTracker.setActive(id)
        SessionActivityTracker.setInactive(id)
        assertFalse(id in SessionBadgeStore.unread.value)
        assertEquals(SessionBadgeStore.SessionBadgeState.PAUSED, SessionBadgeStore.headFor(id))
        SessionActivityTracker.setAbsent(id)
        SessionBadgeStore.clear(id)
    }
}
