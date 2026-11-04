package io.github.nanomuse.guard

import android.app.Activity
import com.openminis.app.crash.CrashFrequencyDetector
import kotlinx.coroutines.flow.MutableStateFlow
import org.junit.Assert.*
import org.junit.Test
import org.mockito.Mockito.mock
import java.io.File

class CrashDiagnosticsAccessTest {
    @Test fun lockedEntryDoesNotConsumeReportsOrInvokeExportCloseFlow() {
        val pending = CrashFrequencyDetector::class.java.getDeclaredField("pendingShareFiles").apply { isAccessible = true }
        val state = AppAccess::class.java.getDeclaredField("_locked").apply { isAccessible = true }
        @Suppress("UNCHECKED_CAST")
        val locked = state.get(AppAccess) as MutableStateFlow<Boolean>
        val previousFiles = pending.get(CrashFrequencyDetector)
        val previousLocked = locked.value
        val files = listOf(File("private-crash-fixture.log"))
        var closed = false
        var exported = false
        try {
            pending.set(CrashFrequencyDetector, files)
            locked.value = true
            CrashFrequencyDetector.maybeShowOnActivity(mock(Activity::class.java),
                onClosed = { closed = true }, saveLauncher = { _, _ -> exported = true })
            assertSame("Authentication must precede consuming diagnostics", files, pending.get(CrashFrequencyDetector))
            assertFalse(closed)
            assertFalse(exported)
        } finally {
            pending.set(CrashFrequencyDetector, previousFiles)
            locked.value = previousLocked
        }
    }
    @Test fun lockedProviderImportCannotReachTheRepositoryOrShowAnOutcome() {
        val state = AppAccess::class.java.getDeclaredField("_locked").apply { isAccessible = true }
        @Suppress("UNCHECKED_CAST")
        val locked = state.get(AppAccess) as MutableStateFlow<Boolean>
        val previousLocked = locked.value
        val activity = mock(com.openminis.app.share.ShareReceiverActivity::class.java)
        val importer = com.openminis.app.share.ShareReceiverActivity::class.java
            .getDeclaredMethod("importProviderJson", String::class.java).apply { isAccessible = true }
        try {
            locked.value = true
            importer.invoke(activity, "{}")
            org.mockito.Mockito.verifyNoInteractions(activity)
        } finally { locked.value = previousLocked }
    }

}
