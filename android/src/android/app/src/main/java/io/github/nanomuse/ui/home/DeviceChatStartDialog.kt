package io.github.nanomuse.ui.home

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.openminis.app.R
import io.github.nanomuse.hub.Device

/** Shared destination chooser for the normal new-chat action and Devices. */
@Composable
internal fun DeviceChatStartDialog(
    devices: List<Device>,
    onLocal: () -> Unit,
    onDevice: (Device) -> Unit,
    onDismiss: () -> Unit,
    showLocal: Boolean = true,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.nm_drawer_new_chat)) },
        text = {
            Column(Modifier.heightIn(max = 440.dp).verticalScroll(rememberScrollState())) {
                if (showLocal) {
                    TextButton(
                        onClick = onLocal,
                        modifier = Modifier.fillMaxWidth().testTag("device-chat-local"),
                    ) {
                        Text(stringResource(R.string.nm_device_chat_here))
                    }
                }
                devices.filter { it.kind != "web" }.forEach { device ->
                    TextButton(
                        onClick = { onDevice(device) },
                        modifier = Modifier.fillMaxWidth().testTag("device-chat-target:${device.id}"),
                    ) {
                        val icon = if (device.isPhone) "📱" else "▣"
                        val status = when {
                            !device.online -> stringResource(R.string.nm_devices_offline)
                            "task.status" !in device.actions -> stringResource(R.string.nm_hub_err_unknown_action)
                            else -> null
                        }
                        Text("$icon ${device.name} · ${device.id.takeLast(6)}${status?.let { " · $it" }.orEmpty()}")
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text(stringResource(android.R.string.cancel)) } },
    )
}
