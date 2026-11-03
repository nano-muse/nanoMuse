package io.github.nanomuse.sync

import com.openminis.app.data.FileMentionIndex
import io.github.nanomuse.hub.Device
import org.junit.Assert.*
import org.junit.Test

class DeviceMentionMenuTest {
    private fun device(id: String, name: String, online: Boolean = true, kind: String = "computer") =
        Device(id, name, kind, "Linux", "", online, listOf("task"), 0)
    private val file = FileMentionIndex.Entry("/var/minis/workspace/readme.md", FileMentionIndex.Scope.WORKSPACE, null, 0, false)

    @Test fun `online equipment appears above files only at the start of the message`() {
        val devices = listOf(device("a", "Mac Studio"), device("b", "Pixel", false), device("c", "console", kind = "web"))
        val entries = DeviceMentionMenu.entries("  @ma", 2, "ma", devices, listOf(file))
        assertEquals(listOf("Mac Studio", file.linuxPath), entries.map { it.linuxPath })
        assertEquals("a", entries.first().nmDevice?.id)
        assertEquals(listOf(file), DeviceMentionMenu.entries("read @ma", 5, "ma", devices, listOf(file)))
    }

    @Test fun `filtering preserves Unicode and ranks a prefix ahead of an interior match`() {
        val devices = listOf(device("a", "Office Mac"), device("b", "Mac 工作站"))
        assertEquals(listOf("Mac 工作站", "Office Mac"), DeviceMentionMenu.entries("@mac", 0, "MAC", devices, emptyList()).map { it.linuxPath })
        assertEquals("Mac 工作站", DeviceMentionMenu.entries("@工作", 0, "工作", devices, emptyList()).single().linuxPath)
        assertTrue(DeviceMentionMenu.entries("@", 0, "", emptyList(), emptyList()).isEmpty())
    }

    @Test fun `duplicate names insert a qualified full name which resolves to the selected id`() {
        val devices = listOf(device("one", "Desk"), device("two", "desk"))
        val entries = DeviceMentionMenu.entries("@", 0, "", devices, emptyList())
        val targets = devices.map { DeviceMention.Target(it.id, it.name) }
        for (entry in entries) {
            assertEquals(entry.nmDevice!!.id, DeviceMention.parse("@${entry.linuxPath} hello", targets)!!.target.id)
            assertTrue(entry.linuxPath.contains(entry.nmDevice!!.name))
        }
        assertNull(DeviceMention.parse("@desk hello", targets))
    }

    @Test fun `devices without task capability are not offered and the existing file remains unchanged`() {
        val noTasks = device("a", "Desk").copy(actions = listOf("info"))
        assertEquals(listOf(file), DeviceMentionMenu.entries("@", 0, "", listOf(noTasks), listOf(file)))
    }
}
