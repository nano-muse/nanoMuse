package io.github.nanomuse.chat

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class ContextTrimStoreTest {
    @get:Rule
    val temporary = TemporaryFolder()

    private fun spill(content: String, kind: ContextTrimming.Kind = ContextTrimming.Kind.RESULT) =
        ContextTrimming.Spill("untrusted-key", "tool-id", "file_read", content, kind)

    private fun host(directory: File, path: String): File = File(directory, path.substringAfterLast('/'))

    @Test
    fun `full UTF8 payload is recoverable through a sandbox path`() {
        val directory = File(temporary.root, "session/offloads/tools")
        val original = "原始结果和 emoji 🐈\n".repeat(2_000)
        val path = ContextTrimStore(directory).write(spill(original))
        assertNotNull(path)
        assertTrue(path!!.startsWith(ContextTrimStore.LINUX_BASE + "/"))
        assertFalse(path.contains(temporary.root.path))
        assertEquals(original, host(directory, path).readText(Charsets.UTF_8))
        assertEquals(1, directory.listFiles()!!.size)
    }

    @Test
    fun `same content reuses its verified file without rewriting`() {
        val directory = temporary.newFolder("tools")
        val store = ContextTrimStore(directory)
        val original = spill("already saved".repeat(500))
        val path = store.write(original)!!
        val file = host(directory, path)
        assertTrue(file.setLastModified(1_600_000_000_000L))
        val modified = file.lastModified()
        val reused = store.write(original.copy(key = "another key", toolId = "another id"))
        assertEquals(path, reused)
        assertEquals(modified, file.lastModified())
        assertEquals(1, directory.listFiles()!!.size)
    }

    @Test
    fun `equal length corruption is detected by hash and replaced with complete original`() {
        val directory = temporary.newFolder("tools")
        val store = ContextTrimStore(directory)
        val original = spill("abc".repeat(2_000))
        val path = store.write(original)!!
        host(directory, path).writeText("xyz".repeat(2_000))
        assertEquals(path, store.write(original))
        assertEquals(original.content, host(directory, path).readText())
        assertEquals(1, directory.listFiles()!!.size)
    }

    @Test
    fun `different payloads cannot overwrite each other despite repeated tool ids`() {
        val directory = temporary.newFolder("tools")
        val store = ContextTrimStore(directory)
        val first = store.write(spill("first evidence"))!!
        val second = store.write(spill("second evidence"))!!
        assertNotEquals(first, second)
        assertEquals("first evidence", host(directory, first).readText())
        assertEquals("second evidence", host(directory, second).readText())
    }

    @Test
    fun `unwritable directory or failed publication returns no reference and leaves no temp file`() {
        val blockedDirectory = temporary.newFile("not-a-directory")
        assertNull(ContextTrimStore(blockedDirectory).write(spill("payload")))

        val directory = temporary.newFolder("tools")
        val store = ContextTrimStore(directory)
        val original = spill("publication must be complete")
        val path = store.write(original)!!
        val destination = host(directory, path)
        assertTrue(destination.delete())
        assertTrue(destination.mkdir())
        File(destination, "block-replacement").writeText("keep")
        assertNull(store.write(original))
        assertEquals(1, directory.listFiles()!!.size)
        assertEquals("keep", File(destination, "block-replacement").readText())
    }

    @Test
    fun `caller names cannot escape the offload directory`() {
        val directory = temporary.newFolder("tools")
        val input = spill("{\"content\":\"original\"}", ContextTrimming.Kind.ARGUMENTS).copy(
            key = "../../elsewhere", toolId = "../escape", toolName = "/outside",
        )
        val path = ContextTrimStore(directory).write(input)!!
        assertFalse(path.contains(".."))
        assertTrue(path.endsWith(".json"))
        assertEquals(input.content, host(directory, path).readText())
        assertEquals(1, directory.listFiles()!!.size)
    }
}
