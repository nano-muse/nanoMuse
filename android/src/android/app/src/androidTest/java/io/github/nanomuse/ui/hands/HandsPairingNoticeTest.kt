package io.github.nanomuse.ui.hands

import android.Manifest
import android.app.Notification
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.RemoteInput
import android.content.Context
import android.content.Intent
import android.os.Bundle
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.filters.SdkSuppress
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.rule.GrantPermissionRule
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
@SdkSuppress(minSdkVersion = 33)
class HandsPairingNoticeTest {
    @get:Rule val notifications: GrantPermissionRule = GrantPermissionRule.grant(Manifest.permission.POST_NOTIFICATIONS)
    private val app = InstrumentationRegistry.getInstrumentation().targetContext
    private suspend fun active(): Notification = withTimeout(3_000) {
        val manager = app.getSystemService(NotificationManager::class.java)
        var result: Notification?
        do {
            result = manager.activeNotifications.singleOrNull { it.notification.channelId == "nanomuse-hands-pairing" }?.notification
            if (result == null) delay(20)
        } while (result == null)
        result
    }
    private fun reply(context: Context, action: Notification.Action, value: String) {
        val result = Intent()
        val input = action.remoteInputs.single()
        RemoteInput.addResultsToIntent(action.remoteInputs, result, Bundle().apply { putCharSequence(input.resultKey, value) })
        action.actionIntent.send(context, 0, result)
    }
    private fun assertRetired(action: Notification.Action) {
        var retired = false
        try { reply(app, action, "000000") } catch (_: PendingIntent.CanceledException) { retired = true }
        assertTrue(retired)
    }

    @Test fun systemReplyRequiresUnlockPreservesLeadingZeroAndIsConsumedOnce() = runBlocking {
        val shown = CompletableDeferred<Unit>()
        val waiting = async(Dispatchers.Default) { HandsPairingNotice.await(app) { shown.complete(Unit) } }
        withTimeout(4_000) { shown.await() }
        val notification = active()
        assertEquals(Notification.VISIBILITY_SECRET, notification.visibility)
        val action = notification.actions.single()
        assertTrue(action.isAuthenticationRequired)
        reply(app, action, "40000 000000")
        val answer = requireNotNull(withTimeout(4_000) { waiting.await() })
        assertEquals(40000, answer.port)
        assertEquals("000000", answer.code)
        assertRetired(action)
    }

    @Test fun dismissExpiryAndMalformedReplyCannotAuthorizeANewNotification() = runBlocking {
        for (mode in listOf("dismiss", "timeout", "bad code")) {
            val shown = CompletableDeferred<Unit>()
            val waiting = async(Dispatchers.Default) {
                HandsPairingNotice.await(app, if (mode == "timeout") 900 else 4_000) { shown.complete(Unit) }
            }
            withTimeout(4_000) { shown.await() }
            val notification = active()
            val action = notification.actions.single()
            when (mode) {
                "dismiss" -> notification.deleteIntent.send()
                "bad code" -> reply(app, action, "12345")
            }
            assertNull(withTimeout(5_000) { waiting.await() })
            assertRetired(action)
        }
    }
}
