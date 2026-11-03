package io.github.nanomuse.chat

import org.junit.Assert.*
import org.junit.Test

class ReplyPresenceTest {
    @Test fun openingMuseOrClassicClearsUnreadAndVisibleCompletionStaysRead() {
        val unread = UnreadReplies()
        val visible = mutableSetOf<String>()
        val presence = ReplyPresence({ visible.add(it); unread.opened(it) }, { visible.remove(it) })
        unread.started("chat"); unread.finished("chat", true, false)
        presence.update("chat", true)
        assertTrue(unread.ids.isEmpty())
        unread.started("chat"); unread.finished("chat", true, "chat" in visible)
        assertTrue(unread.ids.isEmpty())
    }

    @Test fun retainedHiddenTabAndBackgroundDoNotCountAsVisible() {
        val visible = mutableSetOf<String>()
        val presence = ReplyPresence({ visible.add(it) }, { visible.remove(it) })
        presence.update("chat", true)
        presence.update("chat", false)
        assertTrue(visible.isEmpty())
        presence.update("chat", false)
        assertTrue(visible.isEmpty())
        presence.update("chat", true)
        assertEquals(setOf("chat"), visible)
        presence.update(null, false)
        assertTrue(visible.isEmpty())
    }

    @Test fun switchingAndDraftPromotionDoNotCreateAnIdleServiceGap() {
        val events = mutableListOf<String>()
        val presence = ReplyPresence({ events.add("present:$it") }, { events.add("absent:$it") })
        presence.update("draft", true)
        presence.update("real", true)
        presence.update("real", true)
        assertEquals(listOf("present:draft", "present:real", "absent:draft"), events)
    }
}
