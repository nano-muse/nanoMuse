package io.github.nanomuse.hands

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class HandsRunMemoryTest {
    @Test fun notesRequireTheSameConversationAndResolvedApp() {
        val memory = HandsRunMemory({ 0L })
        memory.finish(memory.begin("chat-a", "example.reader"), "Read details", "done", "Read ten pages", listOf("scroll down"))
        assertTrue(memory.begin("chat-a", "example.reader")!!.previous!!.contains("Read ten pages"))
        assertNull(memory.begin("chat-b", "example.reader")!!.previous)
        assertNull(memory.begin("chat-a", "example.browser")!!.previous)
        assertNull(memory.begin("chat-a", null))
        assertNull(memory.begin(null, "example.reader"))
        assertNull(memory.begin("", "example.reader"))
    }

    @Test fun expiryAndCapacityBoundRetainedNotes() {
        var now = 0L
        val memory = HandsRunMemory({ now }, ttlMs = 100, capacity = 2)
        for (chat in listOf("old", "middle", "recent")) {
            memory.finish(memory.begin(chat, "example.reader"), "task", "done", chat, emptyList())
        }
        assertNull(memory.begin("old", "example.reader")!!.previous)
        assertNotNull(memory.begin("middle", "example.reader")!!.previous)
        now = 100L
        assertNull(memory.begin("middle", "example.reader")!!.previous)
        assertNull(memory.begin("recent", "example.reader")!!.previous)
    }

    @Test fun clearRemovesAllAppsAndRejectsAnInflightCompletion() {
        val memory = HandsRunMemory({ 0L })
        for (app in listOf("example.reader", "example.browser")) {
            memory.finish(memory.begin("chat", app), "task", "done", "old", emptyList())
        }
        val active = memory.begin("chat", "example.reader")
        memory.clear("chat")
        memory.finish(active, "task", "done", "late result", emptyList())
        assertNull(memory.begin("chat", "example.reader")!!.previous)
        assertNull(memory.begin("chat", "example.browser")!!.previous)
    }

    @Test fun accountChangesInvalidateBothStoredAndInflightNotes() {
        val memory = HandsRunMemory({ 0L })
        val active = memory.begin("chat", "example.reader")
        memory.finish(active, "task", "done", "old", emptyList())
        memory.clearAll()
        memory.finish(active, "task", "done", "late", emptyList())
        assertNull(memory.begin("chat", "example.reader")!!.previous)
    }

    @Test fun stoppedStateAndBoundedUnicodeNotesRemainData() {
        val memory = HandsRunMemory({ 0L })
        val ticket = memory.begin("chat", "example.reader")
        val large = "🔎".repeat(10_000)
        memory.finish(ticket, large, "stopped", large, List(100) { large })
        val note = memory.begin("chat", "example.reader")!!.previous!!
        val value = JSONObject(note)
        assertEquals("stopped", value.getString("outcome"))
        assertEquals(8, value.getJSONArray("last_steps").length())
        assertTrue(note.length < 8_000)
        assertFalse(note.contains('\uFFFD'))
    }
}
