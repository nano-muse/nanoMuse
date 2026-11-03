package io.github.nanomuse.chat

import org.junit.Assert.*
import org.junit.Test

class UnreadRepliesTest {
    @Test fun successfulBackgroundReplyIsUnreadUntilOpened() {
        val state = UnreadReplies()
        state.started("a")
        state.finished("a", success = true, visible = false)
        assertEquals(setOf("a"), state.ids)
        state.opened("a")
        assertTrue(state.ids.isEmpty())
    }
    @Test fun visibleRepliesAndFailuresAndCancellationsAreNotUnread() {
        val state = UnreadReplies()
        state.started("a"); state.finished("a", true, true)
        state.started("b"); state.finished("b", false, false)
        assertTrue(state.ids.isEmpty())
    }
    @Test fun duplicateCompletionCannotReaddAnOpenedReply() {
        val state = UnreadReplies()
        state.started("a"); state.finished("a", true, false)
        state.opened("a")
        state.finished("a", true, false)
        assertTrue(state.ids.isEmpty())
    }
    @Test fun conversationsAreIndependentAndLaterRunsCanBecomeUnread() {
        val state = UnreadReplies()
        for (id in listOf("a", "b")) { state.started(id); state.finished(id, true, false) }
        state.opened("a")
        assertEquals(setOf("b"), state.ids)
        state.started("a"); state.finished("a", true, false)
        assertEquals(setOf("a", "b"), state.ids)
    }
    @Test fun restartingDoesNotRestoreUnread() {
        val state = UnreadReplies()
        state.started("a"); state.finished("a", true, false)
        assertTrue(UnreadReplies().ids.isEmpty())
    }
    @Test fun deletingConversationDropsItsPendingRunAndBadge() {
        val state = UnreadReplies()
        state.started("a"); state.removed("a"); state.finished("a", true, false)
        assertTrue(state.ids.isEmpty())
    }
}
