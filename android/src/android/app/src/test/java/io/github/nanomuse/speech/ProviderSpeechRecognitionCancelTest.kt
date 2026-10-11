package io.github.nanomuse.speech

import android.content.ContextWrapper
import com.openminis.app.speech.ProviderSpeechRecognitionEngine
import com.openminis.app.speech.SegmentEndReason
import com.openminis.app.speech.VoiceActivityDetector
import com.openminis.app.speech.VoiceActivityListener
import kotlinx.coroutines.Job
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.atomic.AtomicBoolean

class ProviderSpeechRecognitionCancelTest {
    private val context = ContextWrapper(null)

    @Test
    fun cancelStopsTheOwnedVadCapture() {
        val engine = ProviderSpeechRecognitionEngine(context)
        val detector = detector()
        val capture = Job()
        // Model an active capture without starting AudioRecord or loading native VAD.
        flag(detector, "running").set(true)
        setField(detector, "captureJob", capture)
        setField(engine, "detector", detector)
        flag(engine, "recording").set(true)

        try {
            engine.cancel()

            assertTrue("the owned VAD capture job must be cancelled", capture.isCancelled)
            assertFalse(detector.isRunning)
            assertTrue(
                "cancel must use VAD cancellation, not normal stop",
                flag(detector, "cancelled").get(),
            )
            assertNull(field(engine, "detector"))
            assertTrue(flag(engine, "cancelled").get())
            assertFalse(flag(engine, "recording").get())
        } finally {
            detector.cancel()
        }
    }

    @Test
    fun cancelWithoutVadStillDiscardsPendingWork() {
        val engine = ProviderSpeechRecognitionEngine(context)
        val transcription = Job()
        val heldAudioFlush = Job()
        setField(engine, "transcribeJob", transcription)
        setField(engine, "holdFlushJob", heldAudioFlush)
        @Suppress("UNCHECKED_CAST")
        val pending = field(engine, "pendingSegments") as MutableList<ByteArray>
        pending.add(byteArrayOf(1, 2, 3))
        flag(engine, "recording").set(true)

        engine.cancel()

        assertTrue(transcription.isCancelled)
        assertTrue(heldAudioFlush.isCancelled)
        assertNull(field(engine, "holdFlushJob"))
        assertTrue(pending.isEmpty())
        assertTrue(flag(engine, "cancelled").get())
        assertFalse(flag(engine, "recording").get())
    }

    @Test
    fun stopKeepsTheNormalVadStopSemantics() {
        val engine = ProviderSpeechRecognitionEngine(context)
        val detector = detector()
        val capture = Job()
        flag(detector, "running").set(true)
        setField(detector, "captureJob", capture)
        setField(engine, "detector", detector)
        flag(engine, "recording").set(true)

        try {
            engine.stop()

            assertTrue(capture.isCancelled)
            assertFalse(detector.isRunning)
            assertFalse(flag(detector, "cancelled").get())
            assertNull(field(engine, "detector"))
            assertFalse(flag(engine, "cancelled").get())
            assertFalse(flag(engine, "recording").get())
        } finally {
            detector.cancel()
        }
    }

    private fun detector() = VoiceActivityDetector(context, object : VoiceActivityListener {
        override fun onVoiceEnd(wav: ByteArray, reason: SegmentEndReason, spokenSeconds: Float) = Unit
    })

    private fun field(owner: Any, name: String): Any? =
        owner.javaClass.getDeclaredField(name).apply { isAccessible = true }.get(owner)

    private fun setField(owner: Any, name: String, value: Any?) {
        owner.javaClass.getDeclaredField(name).apply { isAccessible = true }.set(owner, value)
    }

    private fun flag(owner: Any, name: String) = field(owner, name) as AtomicBoolean
}
