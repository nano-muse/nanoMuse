package io.github.nanomuse.sandbox

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * The sandbox's offload socket is the app's own, so nanoMuse and OpenMinis start side by side
 * (#271), and the server binds that name, not upstream's.
 */
class OffloadSocketNameTest {
    private val appId = "io.github.nanomuse.app"

    @Test fun `the app's name carries the application id and is not upstream's`() {
        val name = OffloadSocketName.forApp(appId)
        assertEquals("io.github.nanomuse.app.native-offload", name)
        assertNotEquals(OffloadSocketName.UPSTREAM, name)
        assertTrue(name.startsWith("$appId."))
    }

    @Test fun `the per-process fallback is the app's name plus the pid`() {
        val name = OffloadSocketName.forProcess(appId, 24601)
        assertEquals("io.github.nanomuse.app.native-offload-24601", name)
        assertTrue(name.startsWith(OffloadSocketName.forApp(appId)))
    }

    @Test fun `both names fit an abstract socket address`() {
        // sun_path is 108 bytes; abstract names take one leading NUL (proot checks nlen + 1 < 108)
        for (name in listOf(OffloadSocketName.forApp(appId), OffloadSocketName.forProcess(appId, 9_999_999))) {
            assertTrue(name, name.toByteArray().size + 1 < 108)
            assertFalse(name, name.contains(':')) // proot splits its argument at the first colon
        }
    }

    @Test fun `the server binds the app's name and proot is told the bound one`() {
        val server = source("src/main/java/com/openminis/app/sandbox/NativeOffload.kt")
        assertTrue(server.contains("OffloadSocketName.forApp(BuildConfig.APPLICATION_ID)"))
        assertTrue(server.contains("OffloadSocketName.forProcess(BuildConfig.APPLICATION_ID"))
        assertFalse("upstream's bare name must never be bound", server.contains("LocalServerSocket(\"native-offload\")"))
        assertFalse("the bound name is a runtime value", server.contains("const val socketName"))
        for (rel in listOf(
            "src/main/java/com/openminis/app/sandbox/PersistentShell.kt",
            "src/main/java/com/openminis/app/sandbox/TerminalSession.kt",
            "src/main/java/com/openminis/app/sandbox/PRootKernel.kt",
        )) {
            assertTrue(rel, source(rel).contains("--native-offload=\${NativeOffloadServer.socketName}:"))
        }
    }

    private fun source(rel: String): String =
        listOf(rel, "app/$rel").map(::File).first { it.exists() }.readText()
}
