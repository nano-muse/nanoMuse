package io.github.nanomuse.speech

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.openminis.app.speech.VoiceOutputState
import com.openminis.app.ui.chat.LazyReadAloudPlayer
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ReadAloudSelectionTest {
    @Test fun tappingReadAloudQueuesSpeechWithAutomaticRepliesOff() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        instrumentation.runOnMainSync {
            val context = instrumentation.targetContext
            VoiceOutputState.init(context)
            val enabled = VoiceOutputState.isEnabled.value
            val muted = VoiceOutputState.isMuted.value
            val reader = LazyReadAloudPlayer(context)
            try {
                VoiceOutputState.setEnabled(false)
                VoiceOutputState.setMuted(false)
                reader.speak("Read this selected message.")
                assertTrue(VoiceOutputState.activePlayer?.isSpeaking?.value == true)
                assertFalse(VoiceOutputState.isEnabled.value)
                VoiceOutputState.setMuted(true)
                reader.speak("Muted selection")
                assertFalse(VoiceOutputState.activePlayer?.isSpeaking?.value == true)
            } finally {
                reader.shutdown()
                VoiceOutputState.setEnabled(enabled)
                VoiceOutputState.setMuted(muted)
            }
        }
    }
}
