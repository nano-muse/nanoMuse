package io.github.nanomuse.backup

import android.content.Context
import android.content.SharedPreferences
import com.openminis.app.backup.*
import com.openminis.app.data.db.AppDatabase
import java.io.File
import java.nio.file.Files
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import org.mockito.ArgumentMatchers.*
import org.mockito.Mockito.*

class RestoreRecoveryIntegrationTest {
    private fun context(root: File): Context {
        val context = mock(Context::class.java, RETURNS_DEEP_STUBS)
        `when`(context.filesDir).thenReturn(root)
        `when`(context.applicationContext).thenReturn(context)
        val prefs = mock(SharedPreferences::class.java)
        val editor = mock(SharedPreferences.Editor::class.java, RETURNS_SELF)
        `when`(prefs.edit()).thenReturn(editor)
        `when`(editor.commit()).thenReturn(true)
        `when`(context.getSharedPreferences(anyString(), anyInt())).thenReturn(prefs)
        return context
    }

    @Test fun importerRollsBackAFailedCategoryAndCanRetryTheSamePackage() = runBlocking {
        val root = Files.createTempDirectory("restore integration").toFile()
        try {
            val context = context(root)
            val db = mock(AppDatabase::class.java)
            val memory = File(root, "minis-global/memory").apply { mkdirs() }
            File(memory, "a.md").writeText("incoming a")
            File(memory, "z.md").writeText("incoming z")
            val summary = BackupExporter(context, db).export(BackupExporter.Options(
                categories = setOf(BackupCategory.MEMORY), includeCredentials = false))
            val extracted = File(root, "package")
            BackupZip.extract(summary.packageFile, extracted)
            File(memory, "a.md").writeText("original a")
            File(memory, "z.md").delete()
            File(memory, "z.md/keep").apply { parentFile!!.mkdirs(); writeText("original directory") }
            val importer = BackupImporter(context, db)
            val report = importer.import(BackupZip.packageRoot(extracted))
            assertNotNull(report.categories.single().failed)
            assertEquals("original a", File(memory, "a.md").readText())
            assertEquals("original directory", File(memory, "z.md/keep").readText())
            File(memory, "z.md").deleteRecursively()
            val retried = importer.import(BackupZip.packageRoot(extracted))
            assertNull(retried.categories.single().failed)
            assertEquals("incoming a", File(memory, "a.md").readText())
            assertEquals("incoming z", File(memory, "z.md").readText())
        } finally { root.deleteRecursively() }
    }

    @Test fun restartReconcilesBeforeAnyRepositoryIsRequired() {
        val root = Files.createTempDirectory("startup restore").toFile()
        try {
            val memory = File(root, "minis-global/memory").apply { mkdirs() }
            File(memory, "a").writeText("before")
            assertTrue(AndroidRestoreRecovery.begin(context(root), "memory"))
            File(memory, "a").writeText("after")
            File(memory, "new").writeText("new")
            assertEquals(listOf("memory"), AndroidRestoreRecovery.recover(context(root)))
            assertEquals("before", File(memory, "a").readText())
            assertFalse(File(memory, "new").exists())
        } finally { root.deleteRecursively() }
    }
}
