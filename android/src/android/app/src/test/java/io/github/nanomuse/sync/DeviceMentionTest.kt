package io.github.nanomuse.sync

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** "@Mac do this": which device, and the message without the mention (contract C7, rule 8). */
class DeviceMentionTest {
    private val devices = listOf(
        DeviceMention.Target("desk-1", "MacBook Pro"),
        DeviceMention.Target("pixel-1", "Pixel 8"),
        DeviceMention.Target("pixel-2", "Pixel 8 Pro"),
        DeviceMention.Target("win-1", "Office PC"),
    )

    @Test fun `the whole name, case-insensitive, with the mention taken out`() {
        val m = DeviceMention.parse("@macbook pro tidy the downloads folder", devices)!!
        assertEquals("desk-1", m.target.id)
        assertEquals("tidy the downloads folder", m.text)
    }

    @Test fun `the longest name wins`() {
        assertEquals("pixel-2", DeviceMention.parse("@Pixel 8 Pro open the camera", devices)!!.target.id)
        assertEquals("pixel-1", DeviceMention.parse("@Pixel 8 open the camera", devices)!!.target.id)
    }

    @Test fun `a prefix of the name is enough`() {
        val m = DeviceMention.parse("@mac: build the project", devices)!!
        assertEquals("desk-1", m.target.id)
        assertEquals("build the project", m.text)
        assertEquals("win-1", DeviceMention.parse("@office, open the report", devices)!!.target.id)
    }

    @Test fun `no mention, no match, nothing to do`() {
        assertNull(DeviceMention.parse("tidy the downloads folder", devices))
        assertNull(DeviceMention.parse("@nobody do it", devices))
        assertNull(DeviceMention.parse("@ do it", devices))
        assertNull(DeviceMention.parse("@mac do it", emptyList()))
        // an address in the middle is not a mention
        assertNull(DeviceMention.parse("ask @mac to do it", devices))
    }

    @Test fun `the mention alone leaves an empty text for the caller to keep as typed`() {
        assertEquals("", DeviceMention.parse("@MacBook Pro", devices)!!.text)
    }

    @Test fun `the note names the device and the way there`() {
        val note = DeviceMention.note("MacBook Pro", "desk-1")
        assertTrue(note.startsWith("The person addressed MacBook Pro (id desk-1)"))
        assertTrue(note.contains("nanomuse-pc task"))
        assertTrue(note.contains("--on \"desk-1\""))
        assertTrue(note.contains("report what it did"))
    }
}
