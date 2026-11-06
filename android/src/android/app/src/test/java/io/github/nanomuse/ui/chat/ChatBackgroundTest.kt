package io.github.nanomuse.ui.chat

import androidx.compose.ui.graphics.luminance
import com.openminis.app.ui.theme.DarkChatPalette
import com.openminis.app.ui.theme.LightChatPalette
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ChatBackgroundTest {
    @Test fun `missing and unrecognized choices keep the existing canvas in either theme`() {
        for (id in listOf(null, "", "removed-color")) {
            val choice = ChatBackground.byId(id)
            assertEquals(ChatBackground.DEFAULT, choice)
            for (palette in listOf(LightChatPalette, DarkChatPalette)) {
                assertEquals(palette.background, choice.color(palette))
            }
        }
    }

    @Test fun `every background keeps primary text readable in both themes`() {
        for (palette in listOf(LightChatPalette, DarkChatPalette)) {
            for (choice in ChatBackground.entries) {
                val background = choice.color(palette)
                assertEquals(1f, background.alpha, 0f)
                val ink = palette.primaryText.luminance()
                val canvas = background.luminance()
                val contrast = (maxOf(ink, canvas) + 0.05f) / (minOf(ink, canvas) + 0.05f)
                assertTrue("${choice.id}, dark=${palette.isDark}: $contrast", contrast >= 4.5f)
                assertEquals(palette.isDark, canvas < 0.5f)
            }
        }
    }
}
