package io.github.nanomuse.ui.chat

import android.content.ClipboardManager
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.openminis.app.R
import com.openminis.app.ui.chat.InlineErrorBanner
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ChatErrorDetailsTest {
    @get:Rule val compose = createComposeRule()

    @Test fun detailsCopiesTheEntireErrorAndKeepsRetrySeparate() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val message = "service error: " + "diagnostic ".repeat(160) + "invalid part"
        val clipboard = context.getSystemService(ClipboardManager::class.java)
        var retries = 0
        compose.setContent {
            InlineErrorBanner(message) { retries++ }
        }
        compose.onNodeWithText(context.getString(R.string.nm_reach_details)).performClick()
        compose.onNodeWithText(context.getString(R.string.common_copy)).performClick()
        compose.runOnIdle { assertEquals(message, clipboard.primaryClip?.getItemAt(0)?.text?.toString()) }
        assertEquals(0, retries)
        compose.onNodeWithText(context.getString(android.R.string.ok)).performClick()
        compose.onNodeWithText(context.getString(R.string.chat_longpress_retry)).performClick()
        assertEquals(1, retries)
    }
}
