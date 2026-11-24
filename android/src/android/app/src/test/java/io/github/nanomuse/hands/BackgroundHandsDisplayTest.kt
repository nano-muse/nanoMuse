package io.github.nanomuse.hands

import android.text.InputType
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class BackgroundHandsDisplayTest {
    @Test fun tallPhoneAndLandscapeTabletKeepTheirLogicalSizeAndAspect() {
        val phone = HandsViewport.fromDisplay(1080, 2400, 420)
        assertEquals(HandsViewport(720, 1600, 280), phone)
        assertEquals(288, phone.previewWidth)
        assertEquals(640, phone.previewHeight)
        val tablet = HandsViewport.fromDisplay(2560, 1600, 320)
        assertEquals(HandsViewport(1152, 720, 144), tablet)
        assertEquals(320, tablet.previewWidth)
        assertEquals(200, tablet.previewHeight)
        assertEquals(HandsViewport(600, 800, 160), HandsViewport.fromDisplay(600, 800, 160))
        assertThrows(IllegalArgumentException::class.java) { HandsViewport.fromDisplay(0, 800, 160) }
        assertThrows(IllegalArgumentException::class.java) { HandsViewport.fromDisplay(800, -1, 160) }
        assertThrows(IllegalArgumentException::class.java) { HandsViewport.fromDisplay(800, 600, 0) }
    }

    @Test fun previewRecognizesAllAndroidPasswordInputVariations() {
        for (variation in listOf(InputType.TYPE_TEXT_VARIATION_PASSWORD,
            InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD, InputType.TYPE_TEXT_VARIATION_WEB_PASSWORD)) {
            assertTrue(BackgroundHandsDisplay.isPasswordInput(
                InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE or variation))
        }
        assertTrue(BackgroundHandsDisplay.isPasswordInput(InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_VARIATION_PASSWORD))
        assertFalse(BackgroundHandsDisplay.isPasswordInput(InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_EMAIL_ADDRESS))
        assertFalse(BackgroundHandsDisplay.isPasswordInput(InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL))
    }
}
