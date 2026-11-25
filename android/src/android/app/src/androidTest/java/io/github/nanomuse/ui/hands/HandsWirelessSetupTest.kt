package io.github.nanomuse.ui.hands

import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.nanomuse.hands.pairing.PairingDiscovery
import io.github.nanomuse.hands.pairing.SetupInputs
import io.github.nanomuse.hands.pairing.SetupView
import io.github.nanomuse.hands.pairing.WirelessFailure
import io.github.nanomuse.hands.pairing.WirelessSetupFlow
import io.github.nanomuse.hands.pairing.WirelessStatus
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

    private fun pairingView(
        discovery: PairingDiscovery = PairingDiscovery.Idle,
        notificationsAllowed: Boolean = true,
    ): SetupView = WirelessSetupFlow.view(
        SetupInputs(
            developerOptions = true,
            wirelessDebugging = true,
            status = WirelessStatus.NotPaired,
            discovery = discovery,
            notificationsAllowed = notificationsAllowed,
            usbDebugging = true,
            accessibility = false,
            accessibilitySkipped = true,
        ),
    )

    private fun connectionFailureView(): SetupView = WirelessSetupFlow.view(
        SetupInputs(
            developerOptions = true,
            wirelessDebugging = true,
            status = WirelessStatus.Failed(WirelessFailure.ConnectFailed),
            usbDebugging = true,
            accessibility = true,
        ),
    )

    private fun render(
        view: SetupView,
        onSubmit: (String, Int?) -> Unit = { _, _ -> },
        onConnectPort: (Int) -> Unit = {},
        onAllowNotifications: () -> Unit = {},
    ) {
        compose.setContent {
            MaterialTheme {
                HandsWirelessSetupContent(
                    view = view,
                    paired = false,
                    scanning = false,
                    onStepAction = {},
                    onFailureFix = {},
                    onAllowNotifications = onAllowNotifications,
                    onOpenPairingChannel = {},
                    onAppInfo = {},
                    onSkipAccessibility = {},
                    onConfirmStep = {},
                    onSubmit = onSubmit,
                    onConnectPort = onConnectPort,
                    onRevisit = {},
                    onStartRepair = {},
                    onRequestForget = {},
                    onClose = {},
                )
            }
        }
    }

    @Test
    fun manualFallbackValidatesAndNormalizesCodeAndPort() {
        val submitted = CopyOnWriteArrayList<Pair<String, Int?>>()
        render(pairingView(), onSubmit = { code, port -> submitted += code to port })

        compose.onNodeWithTag("setup-manual").performScrollTo().performClick()
        compose.onNodeWithTag("setup-code").performScrollTo().performTextReplacement("000 000")
        compose.onNodeWithTag("setup-port").performScrollTo().performTextReplacement("65536")
        compose.onNodeWithTag("setup-submit").performScrollTo().performClick()
        assertTrue(submitted.isEmpty())

        compose.onNodeWithTag("setup-port").performTextReplacement("40001")
        compose.onNodeWithTag("setup-submit").performScrollTo().performClick()
        assertEquals(listOf("000000" to 40001), submitted.toList())
    }

    @Test
    fun discoveredPairingPortKeepsManualPortHidden() {
        val submitted = CopyOnWriteArrayList<Pair<String, Int?>>()
        render(
            pairingView(PairingDiscovery.Found(40001)),
            onSubmit = { code, port -> submitted += code to port },
        )

        compose.onNodeWithTag("setup-manual").performScrollTo().performClick()
        assertTrue(compose.onAllNodesWithTag("setup-port").fetchSemanticsNodes().isEmpty())
        compose.onNodeWithTag("setup-code").performScrollTo().performTextReplacement("000000")
        compose.onNodeWithTag("setup-submit").performScrollTo().performClick()
        assertEquals(listOf("000000" to null), submitted.toList())
    }

    @Test
    fun notificationAndConnectionRecoveryActionsUseTheirDedicatedCallbacks() {
        val notificationRequested = AtomicBoolean(false)
        render(
            pairingView(notificationsAllowed = false),
            onAllowNotifications = { notificationRequested.set(true) },
        )
        compose.onNodeWithTag("setup-notify-fix").performScrollTo().performClick()
        assertTrue(notificationRequested.get())

        val ports = CopyOnWriteArrayList<Int>()
        render(connectionFailureView(), onConnectPort = ports::add)
        compose.onNodeWithTag("setup-connect-port")
            .performScrollTo()
            .performTextReplacement("192.168.1.2:40005")
        compose.onNodeWithTag("setup-connect-port-submit").performScrollTo().performClick()
        assertEquals(listOf(40005), ports.toList())
    }
}
