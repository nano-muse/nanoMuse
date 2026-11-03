package io.github.nanomuse.backup

import java.io.File
import java.nio.file.Files
import org.junit.Assert.*
import org.junit.Test

class ExportResumeTest {
    private fun fixture(block: (File, ExportResume) -> Unit) {
        val root = Files.createTempDirectory("export 空 # %").toFile()
        try { block(root, ExportResume(root, { "fixed-id" }, { 42 })) }
        finally { root.deleteRecursively() }
    }
    @Test fun restartPreservesIdentityCutoffAndCompletedCategories() = fixture { root, journal ->
        val run = journal.open("options", false, false)
        File(run.staging, "data").mkdirs()
        File(run.staging, "data/memory").writeText("snapshot")
        File(run.staging, "files.index.jsonl").writeText("complete\n")
        journal.completed(run, "memory", "statistics")
        File(run.staging, "files.index.jsonl").appendText("unfinished")
        File(run.staging, "data/partial").writeText("partial")
        val resumed = ExportResume(root, { "different" }, { 99 }).open("options", false, true)
        assertEquals("fixed-id", resumed.id)
        assertEquals(42L, resumed.snapshotAt)
        assertEquals("statistics", resumed.completed["memory"])
        assertEquals("complete\n", File(resumed.staging, "files.index.jsonl").readText())
        assertFalse(File(resumed.staging, "data/partial").exists())
    }
    @Test fun newRunCannotOverwritePendingExport() = fixture { _, journal ->
        journal.open("options", false, false)
        try { journal.open("options", false, false); fail("must ask to resume or discard") }
        catch (_: ExportResume.ResumeRequired) { }
    }
    @Test fun incompatibleOptionsAreRefused() = fixture { _, journal ->
        journal.open("first", false, false)
        try { journal.open("second", false, true); fail("must retain original options") }
        catch (_: IllegalArgumentException) { }
        assertEquals("first", journal.pending()!!.signature)
    }
    @Test fun encryptedRunCannotResumeWithoutPassphraseOrBecomePlaintext() = fixture { root, journal ->
        journal.open("options", true, false)
        try { journal.open("options", false, true); fail("must not downgrade") }
        catch (_: IllegalArgumentException) { }
        assertTrue(journal.pending()!!.encrypted)
        assertFalse(File(root, "pending.properties").readText().contains("passphrase"))
    }
    @Test fun corruptedCompletedDataIsNotPackaged() = fixture { _, journal ->
        val run = journal.open("options", false, false)
        File(run.staging, "data").mkdirs()
        File(run.staging, "data/memory").writeText("before")
        journal.completed(run, "memory", "statistics")
        File(run.staging, "data/memory").writeText("corrupt")
        try { journal.open("options", false, true); fail("must validate completed payload") }
        catch (_: IllegalStateException) { }
        assertNotNull(journal.pending())
    }
    @Test fun discardAndSuccessfulFinishRemoveOnlyThisJournal() = fixture { root, journal ->
        File(root, "unrelated").writeText("keep")
        journal.open("options", false, false)
        journal.discard()
        assertNull(journal.pending())
        val run = journal.open("options", false, false)
        journal.finish(run)
        assertNull(journal.pending())
        assertEquals("keep", File(root, "unrelated").readText())
    }
}
