package io.github.nanomuse.backup

import org.junit.Assert.*
import org.junit.Test
import java.io.File
import java.nio.file.Files

class RestoreRecoveryTest {
    private fun fixture(block: (File, File, RestoreRecovery) -> Unit) {
        val root = Files.createTempDirectory("restore Unicode 空 # %").toFile()
        try {
            val live = File(root, "live").apply { mkdirs() }
            block(root, live, RestoreRecovery(File(root, "journal"), mapOf("memory" to FileRecoveryTarget(live))))
        } finally { root.deleteRecursively() }
    }

    @Test fun interruptedCategoryRestoresOverwritesAndRemovesNewFiles() = fixture { root, live, journal ->
        File(live, "old").writeText("before")
        journal.begin("memory")
        File(live, "old").writeText("after")
        File(live, "new").writeText("new")
        val restarted = RestoreRecovery(File(root, "journal"), mapOf("memory" to FileRecoveryTarget(live)))
        assertEquals(listOf("memory"), restarted.recover())
        assertEquals("before", File(live, "old").readText())
        assertFalse(File(live, "new").exists())
        assertTrue(restarted.recover().isEmpty())
    }

    @Test fun completedCategoryIsKept() = fixture { _, live, journal ->
        File(live, "old").writeText("before")
        journal.begin("memory")
        File(live, "old").writeText("after")
        journal.complete("memory")
        assertTrue(journal.recover().isEmpty())
        assertEquals("after", File(live, "old").readText())
    }

    @Test fun previouslyAbsentTargetIsRemoved() = fixture { _, live, journal ->
        live.deleteRecursively()
        journal.begin("memory")
        live.mkdirs()
        File(live, "new").writeText("new")
        journal.recover()
        assertFalse(live.exists())
    }

    @Test fun failedRecoveryRetainsSnapshotForRetry() = fixture { root, live, journal ->
        File(live, "old").writeText("before")
        journal.begin("memory")
        File(live, "old").writeText("after")
        val failing = object : RecoveryTarget {
            override fun snapshot(destination: File) = error("unused")
            override fun restore(snapshot: File) = error("disk unavailable")
        }
        try {
            RestoreRecovery(File(root, "journal"), mapOf("memory" to failing)).recover()
            fail("must report recovery failure")
        } catch (_: IllegalStateException) { }
        assertEquals(listOf("memory"), journal.recover())
        assertEquals("before", File(live, "old").readText())
    }

    @Test fun unknownCategoryCannotChooseAPath() = fixture { _, _, journal ->
        try { journal.begin("../outside"); fail("must reject unknown target") }
        catch (_: IllegalArgumentException) { }
    }

    @Test fun secondBeginCannotOverwritePendingRecovery() = fixture { _, live, journal ->
        File(live, "old").writeText("before")
        journal.begin("memory")
        File(live, "old").writeText("after")
        try { journal.begin("memory"); fail("must retain original snapshot") }
        catch (_: IllegalStateException) { }
        journal.recover()
        assertEquals("before", File(live, "old").readText())
    }

    @Test fun redirectedParentCannotWriteOutsideAllowedStorage() = fixture { root, live, journal ->
        File(live, "old").writeText("before")
        journal.begin("memory")
        live.deleteRecursively()
        val outside = Files.createTempDirectory("outside recovery").toFile()
        try {
            File(outside, "keep").writeText("outside")
            Files.createSymbolicLink(live.toPath(), outside.toPath())
            try { journal.recover(); fail("must not follow a replaced target") }
            catch (_: IllegalStateException) { }
            assertEquals("outside", File(outside, "keep").readText())
            Files.delete(live.toPath())
            journal.recover()
            assertEquals("before", File(live, "old").readText())
        } finally { outside.deleteRecursively() }
    }
}
