package io.github.nanomuse.ui.hands

import android.Manifest
import android.app.Notification
import android.app.NotificationManager
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.filters.SdkSuppress
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.rule.GrantPermissionRule
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.After
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
@SdkSuppress(minSdkVersion = 33)
class HandsPairingNoticeTest {
    @get:Rule val notifications: GrantPermissionRule = GrantPermissionRule.grant(Manifest.permission.POST_NOTIFICATIONS)
    private val app = InstrumentationRegistry.getInstrumentation().targetContext

    private suspend fun active(matches: (Notification) -> Boolean = { true }): Notification = withTimeout(3_000) {
        val manager = app.getSystemService(NotificationManager::class.java)
        var result: Notification?
        do {
            result = manager.activeNotifications
                .map { it.notification }
                .firstOrNull { it.channelId in PairingChannel.IDS && matches(it) }
            if (result == null) delay(20)
        } while (result == null)
        result
    }

    @After
    fun clearNotification() {
        HandsPairingNotice.cancel(app)
    }

    @Test
    fun enterCodeNoticeUsesOneLocalInlineReplyAction() = runBlocking {
        HandsPairingNotice.show(app, PairingNotice.EnterCode(port = 40_000))
        val notification = active()
        assertTrue(notification.channelId in PairingChannel.IDS)
        assertEquals(Notification.CATEGORY_STATUS, notification.category)
        assertTrue(notification.flags and Notification.FLAG_LOCAL_ONLY != 0)
        assertTrue(notification.flags and Notification.FLAG_ONGOING_EVENT != 0)
        val action = notification.actions.single()
        assertEquals(Notification.Action.SEMANTIC_ACTION_REPLY, action.semanticAction)
        assertFalse(action.allowGeneratedReplies)
        assertFalse(action.isAuthenticationRequired)
        assertEquals(HandsPairingNotice.KEY_CODE, action.remoteInputs.single().resultKey)
    }

    @Test
    fun workingAndDoneReplaceThePairingPrompt() = runBlocking {
        HandsPairingNotice.show(app, PairingNotice.Working)
        val working = active { it.flags and Notification.FLAG_ONGOING_EVENT != 0 }
        assertTrue(working.flags and Notification.FLAG_ONGOING_EVENT != 0)
        assertTrue(working.actions.isNullOrEmpty())

        HandsPairingNotice.show(app, PairingNotice.Done)
        val done = active { it.flags and Notification.FLAG_ONGOING_EVENT == 0 }
        assertFalse(done.flags and Notification.FLAG_ONGOING_EVENT != 0)
        assertTrue(done.actions.isNullOrEmpty())
    }
}
