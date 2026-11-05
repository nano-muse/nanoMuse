package io.github.nanomuse.guard

import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.launch
import androidx.lifecycle.Lifecycle
import org.junit.Assert.*
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class NativeAccessTest {
    @Test fun returningFromFilePickerRechecksAccessAfterLifecycleResume() = runTest {
        val resumed = MutableStateFlow(Lifecycle.State.STARTED)
        val locked = MutableStateFlow(false)
        var exports = 0
        val operation = launch { awaitNativeAccess(resumed, locked); exports++ }
        runCurrent()
        assertEquals(0, exports)
        locked.value = true
        resumed.value = Lifecycle.State.RESUMED
        runCurrent()
        assertEquals(0, exports)
        locked.value = false
        runCurrent()
        assertEquals(1, exports)
        assertTrue(operation.isCompleted)
    }
    @Test fun unlockingAnotherActivityDoesNotReleaseAnExportAfterItsOwnerPaused() = runTest {
        val resumed = MutableStateFlow(Lifecycle.State.RESUMED)
        val locked = MutableStateFlow(true)
        var exports = 0
        val operation = launch { awaitNativeAccess(resumed, locked); exports++ }
        runCurrent()
        resumed.value = Lifecycle.State.STARTED
        runCurrent()
        locked.value = false
        runCurrent()
        assertEquals("A resumed owner is still required when access returns", 0, exports)
        resumed.value = Lifecycle.State.RESUMED
        runCurrent()
        assertEquals(1, exports)
        assertTrue(operation.isCompleted)
    }
    @Test fun relockingClosesAnAlreadyOpenDiagnosticWindowOnce() = runTest {
        val locked = MutableStateFlow(false)
        var closed = 0
        val job = watchNativeAccess(locked, this) { closed++ }
        assertEquals(0, closed)
        locked.value = true
        runCurrent()
        assertEquals(1, closed)
        assertTrue(job.isCompleted)
        locked.value = false; locked.value = true
        runCurrent()
        assertEquals(1, closed)
    }
    @Test fun lockedWindowClosesImmediatelyAndDismissedWindowsStopObserving() = runTest {
        val locked = MutableStateFlow(true)
        var closed = 0
        watchNativeAccess(locked, this) { closed++ }
        assertEquals(1, closed)
        locked.value = false
        val dismissed = watchNativeAccess(locked, this) { closed++ }
        dismissed.cancel()
        locked.value = true
        runCurrent()
        assertEquals(1, closed)
    }
}
