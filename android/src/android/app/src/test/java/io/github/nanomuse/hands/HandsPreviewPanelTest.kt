package io.github.nanomuse.hands

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Test

class HandsPreviewPanelTest {
    @Test
    fun missingRefreshKeepsThePreviousFrame() {
        val previous = Any()

        val update = retainPreviewFrame(previous, PreviewCapture.Pending)

        assertSame(previous, update.displayed)
        assertNull(update.retired)
        assertEquals(false, update.clear)
    }

    @Test
    fun aNewFrameReplacesAndRetiresThePreviousFrame() {
        val previous = Any()
        val next = Any()

        val update = retainPreviewFrame(previous, PreviewCapture.Frame(next))

        assertSame(next, update.displayed)
        assertSame(previous, update.retired)
        assertEquals(false, update.clear)
    }

    @Test
    fun aSecurityFailureClearsAndRetiresThePreviousFrame() {
        val previous = Any()

        val update = retainPreviewFrame(previous, PreviewCapture.Clear)

        assertNull(update.displayed)
        assertSame(previous, update.retired)
        assertEquals(true, update.clear)
    }

    @Test
    fun theFirstPendingRefreshDoesNotInventAPlaceholderFrame() {
        assertEquals(
            PreviewFrameUpdate<Any>(null, null, clear = false),
            retainPreviewFrame(null, PreviewCapture.Pending),
        )
    }
}
