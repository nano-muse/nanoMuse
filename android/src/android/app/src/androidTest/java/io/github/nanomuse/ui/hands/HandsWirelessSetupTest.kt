package io.github.nanomuse.ui.hands

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.openminis.app.R
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicBoolean

@RunWith(AndroidJUnit4::class)
class HandsWirelessSetupTest {
    @get:Rule val compose = createComposeRule()
    private fun label(id: Int) = InstrumentationRegistry.getInstrumentation().targetContext.getString(id)
    private fun click(id: Int) = compose.onNodeWithText(label(id)).performScrollTo().performClick()
    private fun awaitLabel(id: Int) = compose.waitUntil(10_000) {
        compose.onAllNodesWithText(label(id)).fetchSemanticsNodes().isNotEmpty()
    }

    @Test fun pairUsesSystemCodeAndDifferentConnectionPortThenForgetsOnConfirmation() {
        val ready = mutableStateOf(false)
        val calls = CopyOnWriteArrayList<String>()
        val forgotten = AtomicBoolean(false)
        compose.setContent { MaterialTheme {
            HandsWirelessForm(onBack = {}, ready = ready.value, pairedInitially = false, openSettings = { true },
                discover = { pairing -> calls += if (pairing) "pair-port" else "connect-port"; listOf(if (pairing) 40001 else 40002) },
                pair = { port, code -> assertEquals(40001, port); assertEquals("000000", code); calls += "pair" },
                activate = { port -> assertEquals(40002, port); calls += "activate"; ready.value = true },
                forget = { forgotten.set(true); ready.value = false },
            )
        } }
        val submit = compose.onNodeWithText(label(R.string.nm_hands_wireless_pair))
        submit.assertIsNotEnabled()
        val fields = compose.onAllNodes(hasSetTextAction())
        fields[1].performScrollTo().performTextReplacement("000000")
        fields[0].performScrollTo().performTextReplacement("65536")
        submit.assertIsNotEnabled()
        fields[0].performTextReplacement("")
        submit.assertIsEnabled().performScrollTo().performClick()
        awaitLabel(R.string.nm_hands_status_ready)
        assertEquals(listOf("pair-port", "pair", "connect-port", "activate"), calls.toList())
        click(R.string.nm_hands_wireless_forget)
        compose.onNodeWithText(label(R.string.cancel)).performClick()
        assertTrue(!forgotten.get())
        click(R.string.nm_hands_wireless_forget)
        compose.onNodeWithText(label(R.string.nm_devices_forget)).performClick()
        awaitLabel(R.string.nm_hands_wireless_pair_help)
        assertTrue(forgotten.get())
    }

    @Test fun deniedNotificationKeepsManualEntryAndReplyCanSupplyThePairingPort() {
        val ready = mutableStateOf(false)
        val denied = AtomicBoolean(true)
        val paired = CopyOnWriteArrayList<Int>()
        compose.setContent { MaterialTheme {
            HandsWirelessForm(onBack = {}, ready = ready.value, pairedInitially = false, openSettings = { true },
                discover = { assertTrue(!it); listOf(40002) },
                pair = { port, code -> assertEquals("000000", code); paired += port },
                activate = { port -> assertEquals(40002, port); ready.value = true }, forget = {},
                getNoticeReply = { if (denied.getAndSet(false)) throw HandsPairingNotice.Unavailable()
                    HandsPairingReply("000000", 40001) },
            )
        } }
        click(R.string.nm_hands_wireless_notification)
        awaitLabel(R.string.nm_hands_wireless_notification_disabled)
        assertEquals(2, compose.onAllNodes(hasSetTextAction()).fetchSemanticsNodes().size)
        assertTrue(paired.isEmpty())
        click(R.string.nm_hands_wireless_notification)
        awaitLabel(R.string.nm_hands_status_ready)
        assertEquals(listOf(40001), paired.toList())
    }

    @Test fun existingPairFallsBackToManualPortWhenDiscoveryIsAmbiguous() {
        val activated = CopyOnWriteArrayList<Int>()
        val ready = mutableStateOf(false)
        compose.setContent { MaterialTheme {
            HandsWirelessForm(onBack = {}, ready = ready.value, pairedInitially = true, openSettings = { true },
                discover = { assertTrue(!it); listOf(40001, 40002) },
                pair = { _, _ -> error("Existing pairing must be reused") },
                activate = { activated += it; ready.value = true }, forget = {},
            )
        } }
        awaitLabel(R.string.nm_hands_wireless_port_missing)
        assertTrue(activated.isEmpty())
        compose.onNode(hasSetTextAction()).performScrollTo().performTextReplacement("40005")
        click(R.string.nm_connectors_connect)
        awaitLabel(R.string.nm_hands_status_ready)
        assertEquals(listOf(40005), activated.toList())
    }
}
