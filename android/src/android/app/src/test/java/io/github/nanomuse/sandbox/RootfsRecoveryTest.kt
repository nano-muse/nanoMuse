package io.github.nanomuse.sandbox

import android.content.Context
import android.content.SharedPreferences
import android.content.pm.ApplicationInfo
import android.content.res.AssetManager
import com.openminis.app.R
import com.openminis.app.sandbox.RootfsInstallState
import com.openminis.app.sandbox.RootfsManager
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import org.mockito.Mockito.*
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.FileNotFoundException
import java.nio.file.Files
import java.nio.file.LinkOption.NOFOLLOW_LINKS
import java.nio.file.Paths

class RootfsRecoveryTest {
    @get:Rule val tmp = TemporaryFolder()
    private val assets = mock(AssetManager::class.java)
    private lateinit var manager: RootfsManager
    private lateinit var root: File

    @Before fun setUp() {
        val context = mock(Context::class.java)
        `when`(context.filesDir).thenReturn(tmp.newFolder("files"))
        `when`(context.applicationInfo).thenReturn(ApplicationInfo().apply {
            nativeLibraryDir = tmp.newFolder("native").absolutePath
        })
        `when`(context.assets).thenReturn(assets)
        `when`(context.getString(R.string.nm_sandbox_proot_missing)).thenReturn("not found")
        `when`(context.getString(R.string.nm_sandbox_proot_not_executable)).thenReturn("not executable")
        val preferences = mock(SharedPreferences::class.java)
        `when`(preferences.edit()).thenReturn(mock(SharedPreferences.Editor::class.java, RETURNS_SELF))
        `when`(context.getSharedPreferences("mirror_settings", Context.MODE_PRIVATE)).thenReturn(preferences)
        val ctor = RootfsManager::class.java.getDeclaredConstructor(Context::class.java)
        ctor.isAccessible = true
        manager = ctor.newInstance(context)
        root = manager.rootfsDir.apply { mkdirs() }
        root.resolve(".arch").writeText("aarch64")
        `when`(assets.open("alpine-minirootfs.tar.gz")).thenThrow(FileNotFoundException())
    }

    @Test fun completeFirstInstallOpensTheTarOnce(): Unit = runBlocking {
        root.resolve(".arch").delete()
        `when`(assets.open("alpine-minirootfs.tar")).thenAnswer { bundledTar().inputStream() }
        manager.installIfNeeded()
        assertEquals("aarch64", root.resolve(".arch").readText())
        verify(assets, times(1)).open("alpine-minirootfs.tar")
    }

    @Test fun firstInstallKeepsTheMarkerAbsentIfTheShellCannotBeRecovered() {
        root.resolve(".arch").delete()
        `when`(assets.open("alpine-minirootfs.tar")).thenAnswer { bundledTar(includeShell = false).inputStream() }
        assertThrows(java.io.IOException::class.java) { runBlocking { manager.installIfNeeded() } }
        assertFalse(root.resolve(".arch").exists())
        assertTrue(manager.installState.value is RootfsInstallState.Failed)
        verify(assets, times(2)).open("alpine-minirootfs.tar")
    }

    @Test fun repairsTheShellAndDependenciesInAnInstalledRootfs(): Unit = runBlocking {
        val previousLib = root.resolve("lib/ld-musl-aarch64.so.1")
        previousLib.parentFile!!.mkdirs()
        previousLib.writeText("upgraded musl")
        root.resolve("keep").writeText("user data")
        `when`(assets.open("alpine-minirootfs.tar")).thenAnswer { bundledTar().inputStream() }
        manager.installIfNeeded()
        assertEquals("/bin/busybox", Files.readSymbolicLink(root.resolve("bin/sh").toPath()).toString())
        assertEquals("ld-musl-aarch64.so.1", Files.readSymbolicLink(root.resolve("lib/libc.musl-aarch64.so.1").toPath()).toString())
        assertEquals("busybox", root.resolve("bin/busybox").readText())
        assertTrue(root.resolve("bin/busybox").canExecute())
        assertEquals("upgraded musl", previousLib.readText())
        assertEquals("user data", root.resolve("keep").readText())
        manager.installIfNeeded()
        verify(assets, times(1)).open("alpine-minirootfs.tar")
    }

    @Test fun repairsBehindAnAbsoluteGuestDirectoryLink(): Unit = runBlocking {
        val relocated = root.resolve("guest-bin").apply { mkdirs() }
        Files.createSymbolicLink(root.resolve("bin").toPath(), Paths.get("/guest-bin"))
        Files.createSymbolicLink(relocated.resolve("sh").toPath(), Paths.get("/bin/busybox"))
        `when`(assets.open("alpine-minirootfs.tar")).thenAnswer { bundledTar().inputStream() }
        manager.installIfNeeded()
        assertEquals("busybox", relocated.resolve("busybox").readText())
        assertEquals("musl", root.resolve("lib/ld-musl-aarch64.so.1").readText())
    }

    @Test fun leavesAReplacementShellAlone(): Unit = runBlocking {
        val bash = root.resolve("bin/bash")
        bash.parentFile!!.mkdirs()
        bash.writeText("custom shell")
        bash.setExecutable(true)
        val sh = root.resolve("bin/sh").toPath()
        Files.createSymbolicLink(sh, Paths.get("/bin/bash"))
        manager.installIfNeeded()
        assertEquals("/bin/bash", Files.readSymbolicLink(sh).toString())
        assertFalse(root.resolve("bin/busybox").exists())
        verify(assets, never()).open(anyString())
    }

    @Test fun truncatedArchiveCanBeRetriedWithoutPublishingAPartialProgram(): Unit = runBlocking {
        val tar = bundledTar()
        `when`(assets.open("alpine-minirootfs.tar")).thenReturn(
            tar.copyOf(514).inputStream(), tar.inputStream(),
        )
        assertThrows(java.io.EOFException::class.java) { runBlocking { manager.installIfNeeded() } }
        assertTrue(manager.installState.value is RootfsInstallState.Failed)
        assertFalse(Files.exists(root.resolve("bin/sh").toPath(), NOFOLLOW_LINKS))
        assertFalse(root.resolve("bin/busybox").exists())
        manager.installIfNeeded()
        assertEquals("busybox", root.resolve("bin/busybox").readText())
    }

    @Test fun keepsAFileInstalledByTheGuestDuringRepair() {
        val busybox = root.resolve("bin/busybox")
        AlpineShellFiles.restoreMissing(root) { staging, names ->
            for (name in names) {
                val entry = staging.resolve(name)
                entry.parentFile!!.mkdirs()
                entry.writeText("packaged")
            }
            busybox.parentFile!!.mkdirs()
            busybox.writeText("concurrent guest install")
        }
        assertEquals("concurrent guest install", busybox.readText())
    }

    @Test fun nativeBinaryErrorsDistinguishMissingAndNonExecutable() {
        fun error() = assertThrows(IllegalStateException::class.java) {
            runBlocking { manager.installProotIfNeeded() }
        }.message.orEmpty()
        assertTrue(error().contains("not found"))
        manager.prootBinary.writeText("test")
        assertTrue(error().contains("not executable"))
    }

    // A POSIX tar with the same four bootstrap members and link targets as the shipped Alpine image.
    private fun bundledTar(includeShell: Boolean = true): ByteArray {
        val tar = ByteArrayOutputStream()
        fun entry(name: String, content: String, link: String = "") {
            val header = ByteArray(512)
            "./$name".toByteArray().copyInto(header)
            "0000755".toByteArray().copyInto(header, 100)
            content.length.toString(8).toByteArray().copyInto(header, 124)
            header[156] = (if (link.isEmpty()) '0' else '2').code.toByte()
            link.toByteArray().copyInto(header, 157)
            tar.write(header)
            tar.write(content.toByteArray())
            tar.write(ByteArray((512 - content.length % 512) % 512))
        }
        entry("bin/busybox", "busybox")
        if (includeShell) entry("bin/sh", "", "/bin/busybox")
        entry("lib/libc.musl-aarch64.so.1", "", "ld-musl-aarch64.so.1")
        entry("lib/ld-musl-aarch64.so.1", "musl")
        entry("keep", "packaged default")
        tar.write(ByteArray(1024))
        return tar.toByteArray()
    }
}
