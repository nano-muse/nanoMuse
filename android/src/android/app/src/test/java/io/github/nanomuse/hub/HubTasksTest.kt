package io.github.nanomuse.hub

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** `stop {call}` and `stop {conversation}` find the asker's own run here and nothing else. */
class HubTasksTest {
    @Test fun `the conversation is the one named, else one per device`() {
        val t = HubTasks()
        assertEquals("from-desk", t.conversationKey("desk", null))
        assertEquals("from-desk", t.conversationKey("desk", "  "))
        assertEquals("from-unknown", t.conversationKey("", null))
        assertEquals("notes", t.conversationKey("desk", " notes "))
    }

    @Test fun `the prompt carries the asker's language when the frame names one`() {
        assertEquals("do it", HubTasks.prompt("do it", prefix = null, language = null))
        assertEquals("From Desk.\n\ndo it", HubTasks.prompt("do it", prefix = "From Desk.", language = "  "))
        assertEquals(
            "From Desk.\n\nAnswer in the language tagged zh-Hans; the device that asked shows its screens in it.\n\ndo it",
            HubTasks.prompt("do it", prefix = "From Desk.", language = " zh-Hans "),
        )
        // a web console speaks for the person directly: no prefix, the language still counts
        assertEquals(
            "Answer in the language tagged fr; the device that asked shows its screens in it.\n\ndo it",
            HubTasks.prompt("do it", prefix = null, language = "fr"),
        )
    }

    @Test fun `stop by call id, by conversation, or by the sender's default conversation`() {
        val t = HubTasks()
        t.started("c1", "desk", "from-desk", "s1")
        t.started("c2", "desk", "notes", "s2")
        assertEquals("s1", t.find("desk", "c1", null))
        assertEquals("s2", t.find("desk", null, "notes"))
        assertEquals("s1", t.find("desk", null, null))
        assertEquals("s2", t.find("desk", "", "notes"))
    }

    @Test fun `another device cannot stop a run it did not ask for`() {
        val t = HubTasks()
        t.started("c1", "desk", "from-desk", "s1")
        assertNull(t.find("laptop", "c1", null))
        assertNull(t.find("laptop", null, "from-desk"))
        assertNull(t.find("desk", "nope", "nothing"))
    }

    @Test fun `a stopped task answers cancelled, a finished one does not`() {
        val t = HubTasks()
        t.started("c1", "desk", "from-desk", "s1")
        t.started("c2", "desk", "notes", "s2")
        t.markStopped("s1")
        assertTrue(t.finished("c1"))
        assertFalse(t.finished("c2"))
        assertFalse("forgotten after it finished", t.finished("c1"))
        assertNull(t.find("desk", "c1", null))
    }

    @Test fun `a delayed stop for a finished call never falls back to the next conversation run`() {
        val t = HubTasks()
        t.started("old", "desk", "from-desk", "old-session")
        t.finished("old")
        t.started("next", "desk", "from-desk", "new-session")
        assertNull(t.find("desk", "old", null))
        assertNull(t.find("desk", "missing", "from-desk"))
        assertEquals("new-session", t.find("desk", null, null))
    }

    @Test fun `conversation lookup selects only the requesting device's run`() {
        val t = HubTasks()
        t.started("other", "laptop", "notes", "other-session")
        t.started("own", "desk", "notes", "own-session")
        assertEquals("own-session", t.find("desk", null, "notes"))
        assertNull(t.find("desk", "other", "notes"))
    }
}
