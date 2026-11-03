package io.github.nanomuse.backup

import android.content.Context
import com.openminis.app.backup.*
import com.openminis.app.data.db.AppDatabase
import java.io.File
import java.nio.file.Files
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import kotlinx.coroutines.Job
import kotlinx.coroutines.CancellationException
import org.junit.Assert.*
import org.junit.Test
import org.mockito.Mockito.*

class BackupResumeIntegrationTest {
    @Test fun resumedExporterProducesAVerifiablePackageWithOriginalMemorySnapshot() = runBlocking {
        val root = Files.createTempDirectory("resume integration 空").toFile()
        try {
            val context = mock(Context::class.java, RETURNS_DEEP_STUBS)
            `when`(context.filesDir).thenReturn(root)
            `when`(context.applicationContext).thenReturn(context)
            `when`(context.cacheDir).thenReturn(File(root, "cache"))
            val db = mock(AppDatabase::class.java)
            val memory = File(root, "minis-global/memory/day.md").apply { parentFile!!.mkdirs(); writeText("original memory") }
            memory.setLastModified(1)
            val options = BackupExporter.Options(categories = setOf(BackupCategory.MEMORY), includeCredentials = false)
            try {
                BackupExporter(context, db).export(options) { if (it.startsWith("Writing manifest")) error("simulated process interruption") }
                fail("must interrupt before archive")
            } catch (_: IllegalStateException) { }
            val pending = ExportResume(File(root, "backup-resume")).pending()!!
            memory.writeText("later memory")
            val summary = BackupExporter(context, db).export(options.copy(resumeInterrupted = true))
            assertEquals(pending.id, summary.backupId)
            java.util.zip.ZipFile(summary.packageFile).use { zip ->
                val entry = zip.entries().asSequence().first { it.name.endsWith("data/memory/day.md") }
                assertEquals("original memory", zip.getInputStream(entry).reader().readText())
                assertFalse(zip.entries().asSequence().any { it.name.contains("checkpoint.properties") || it.name.contains("pending.properties") })
            }
            val extracted = File(root, "extracted")
            BackupZip.extract(summary.packageFile, extracted)
            val packageRoot = BackupZip.packageRoot(extracted)
            val reader = BackupPackageReader(packageRoot)
            assertTrue(reader.verifyIntegrity(reader.readManifest()).isEmpty())
            memory.delete()
            BackupImporter(context, db).import(packageRoot)
            assertEquals("original memory", memory.readText())
            assertNull(ExportResume(File(root, "backup-resume")).pending())
        } finally { root.deleteRecursively() }
    }

    @Test fun interruptedEncryptionResumesAsAnEncryptedVerifiableBackup() = runBlocking {
        val root = Files.createTempDirectory("encrypted resume").toFile()
        try {
            val context = mock(Context::class.java, RETURNS_DEEP_STUBS)
            `when`(context.filesDir).thenReturn(root)
            `when`(context.cacheDir).thenReturn(File(root, "cache"))
            `when`(context.applicationContext).thenReturn(context)
            val db = mock(AppDatabase::class.java)
            File(root, "minis-global/memory/day.md").apply { parentFile!!.mkdirs(); writeText("encrypted original"); setLastModified(1) }
            val options = BackupExporter.Options(categories = setOf(BackupCategory.MEMORY), includeCredentials = false,
                passphrase = "test-only-encryption-password")
            try {
                BackupExporter(context, db).export(options) { if (it.startsWith("Writing manifest")) error("interrupted encryption packaging") }
                fail("must interrupt")
            } catch (_: IllegalStateException) { }
            assertNotNull(BackupExporter.interrupted(context))
            val summary = BackupExporter(context, db).export(options.copy(resumeInterrupted = true))
            val extracted = File(root, "extracted")
            BackupZip.extract(summary.packageFile, extracted)
            val reader = BackupPackageReader(BackupZip.packageRoot(extracted))
            val manifest = reader.readManifest()
            assertNotNull(manifest.encryption)
            assertTrue(reader.verifyIntegrity(manifest).isEmpty())
            reader.unlock("test-only-encryption-password", manifest).destroy()
        } finally { root.deleteRecursively() }
    }

    @Test fun corruptStagedBlobIsRefusedInsteadOfReused() {
        val root = Files.createTempDirectory("resume blob").toFile()
        try {
            val source = File(root, "source").apply { writeText("original") }
            val staging = File(root, "staging").apply { mkdirs() }
            val store = BackupBlobStore(staging, null)
            val outcome = store.addFile(source, "shared/a") as BackupBlobStore.Outcome.Stored
            BackupFileIndexWriter(File(staging, "files.index.jsonl")).use { writer ->
                writer.write(BackupFileIndexEntry(path = "shared/a", size = source.length(), sha256 = outcome.sha256))
            }
            File(staging, "blobs/${outcome.sha256.take(2)}/${outcome.sha256}").writeText("corrupt!")
            try { BackupBlobStore(staging, null).rehydrateFromFileIndex(File(staging, "files.index.jsonl"), strict = true); fail("must reject corruption") }
            catch (_: IllegalStateException) { }
        } finally { root.deleteRecursively() }
    }

    @Test fun cancellationKeepsCheckpointsAndDoesNotProduceAFinishedPackage() = runBlocking {
        val root = Files.createTempDirectory("cancel export").toFile()
        try {
            val context = mock(Context::class.java, RETURNS_DEEP_STUBS)
            `when`(context.filesDir).thenReturn(root)
            `when`(context.applicationContext).thenReturn(context)
            val db = mock(AppDatabase::class.java)
            File(root, "minis-global/memory/day.md").apply { parentFile!!.mkdirs(); writeText("snapshot"); setLastModified(1) }
            val options = BackupExporter.Options(categories = setOf(BackupCategory.MEMORY), includeCredentials = false)
            val execution = Job()
            try {
                withContext(execution) {
                    BackupExporter(context, db).export(options) { if (it.startsWith("Writing manifest")) execution.cancel() }
                }
                fail("must cancel before packaging")
            } catch (_: CancellationException) { }
            assertNotNull(BackupExporter.interrupted(context))
            assertTrue(BackupExporter.backupsDirectory(context).listFiles().orEmpty().none { it.extension == "minisbak" })
            val resumed = BackupExporter(context, db).export(options.copy(resumeInterrupted = true))
            assertTrue(resumed.packageFile.isFile)
        } finally { root.deleteRecursively() }
    }
}
