package io.github.nanomuse.ui.home

import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.assertIsDisplayed
import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.nanomuse.hub.Device
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class DeviceChatStartDialogTest {
    @get:Rule val compose = createComposeRule()

    @Test fun aLongDestinationListKeepsTheLastDeviceReachable() {
        val devices = (1..24).map { device("desk-$it", "Desk $it", online = true, persistent = true) }
        var selected = ""
        compose.setContent {
            DeviceChatStartDialog(devices, onLocal = {}, onDevice = { selected = it.id }, onDismiss = {})
        }
        compose.onNodeWithTag("device-chat-target:desk-24")
            .performScrollTo().assertIsDisplayed().performClick()
        assertEquals("desk-24", selected)
    }

    @Test fun localChoiceStartsALocalChat() {
        var local = false
        compose.setContent {
            DeviceChatStartDialog(
                devices = emptyList(),
                onLocal = { local = true },
                onDevice = {},
                onDismiss = {},
            )
        }

        compose.onNodeWithTag("device-chat-local").performClick()

        assertEquals(true, local)
    }

    @Test fun duplicateNamesSelectByStableDeviceId() {
        val devices = listOf(
            device("desk-a1b2c3", "Office", online = true, persistent = true),
            device("desk-d4e5f6", "Office", online = true, persistent = true),
        )
        var selected = ""
        compose.setContent {
            DeviceChatStartDialog(devices, onLocal = {}, onDevice = { selected = it.id }, onDismiss = {})
        }

        compose.onNodeWithTag("device-chat-target:desk-a1b2c3").performClick()

        assertEquals("desk-a1b2c3", selected)
    }

    @Test fun offlineAndLegacyDestinationsKeepTheirSelectableDraftRoute() {
        val devices = listOf(
            device("offline-123456", "Offline", online = false, persistent = true),
            device("legacy-123456", "Legacy", online = true, persistent = false),
        )
        var selected = ""
        compose.setContent {
            DeviceChatStartDialog(devices, onLocal = {}, onDevice = { selected = it.id }, onDismiss = {})
        }

        compose.onNodeWithTag("device-chat-target:offline-123456").performClick()
        assertEquals("offline-123456", selected)
        compose.onNodeWithTag("device-chat-target:legacy-123456").performClick()
        assertEquals("legacy-123456", selected)
    }

    private fun device(id: String, name: String, online: Boolean, persistent: Boolean) = Device(
        id = id,
        name = name,
        kind = "computer",
        os = "",
        version = "",
        online = online,
        actions = if (persistent) listOf("task", "task.status") else listOf("task"),
        lastSeen = 0,
    )
}
