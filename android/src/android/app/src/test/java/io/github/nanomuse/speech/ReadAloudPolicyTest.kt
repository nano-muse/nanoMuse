package io.github.nanomuse.speech

import com.openminis.app.speech.VoiceOutputState
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ReadAloudPolicyTest {
    @Test
    fun explicitSelectionWorksWithAutomaticRepliesOffAndStillHonoursMute() {
        val enabled = VoiceOutputState.isEnabled.value
        val muted = VoiceOutputState.isMuted.value
        try {
            VoiceOutputState.setEnabled(false)
            VoiceOutputState.setMuted(false)
            assertFalse(VoiceOutputState.canPlay)
            assertTrue(VoiceOutputState.permitsPlayback(manualSelection = true))
            VoiceOutputState.setEnabled(true)
            assertTrue(VoiceOutputState.canPlay)
            VoiceOutputState.setMuted(true)
            assertFalse(VoiceOutputState.canPlay)
            assertFalse(VoiceOutputState.permitsPlayback(manualSelection = true))
        } finally {
            VoiceOutputState.setEnabled(enabled)
            VoiceOutputState.setMuted(muted)
        }
    }
}
