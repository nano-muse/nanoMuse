package io.github.nanomuse.ui.cloud

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.openminis.app.R
import io.github.nanomuse.cloud.NanoMuseCloud
import io.github.nanomuse.hub.Device
import io.github.nanomuse.hub.DeviceConversations
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

@Composable
internal fun DeviceConversationPanel(devices: List<Device>) {
    val context = LocalContext.current
    val account = NanoMuseCloud.account(context)?.accountId?.takeIf { it.isNotBlank() } ?: return
    val service = remember(context, account) { DeviceConversations.open(context, account) }
    val scope = rememberCoroutineScope()
    var rows by remember(account) { mutableStateOf(emptyList<JSONObject>()) }
    var selected by remember(account) { mutableStateOf("") }
    val drafts = remember(account) { mutableStateMapOf<String, String>() }
    var events by remember(account, selected) { mutableStateOf(emptyList<JSONObject>()) }
    var error by remember(account) { mutableStateOf(false) }
    var sending by remember(account) { mutableStateOf(false) }
    val chat = rows.find { it.optString("id") == selected }
    val device = devices.find { it.id == chat?.optString("device") }
    val activeDevice = chat?.let { row ->
        devices.find { it.id == DeviceConversations.target(row, DeviceConversations.pending(row)) }
    }

    fun save(row: JSONObject) {
        val id = row.getString("id")
        rows = if (rows.any { it.getString("id") == id }) rows.map { if (it.getString("id") == id) row else it } else rows + row
    }
    fun run(work: suspend () -> Unit) {
        scope.launch {
            error = false
            try { work() } catch (cancelled: kotlinx.coroutines.CancellationException) {
                throw cancelled
            } catch (_: Exception) { error = true }
        }
    }
    LaunchedEffect(service) {
        runCatching { withContext(Dispatchers.IO) { service.list() } }.onSuccess { rows = it }.onFailure { error = true }
    }
    LaunchedEffect(service, selected, activeDevice?.online) {
        events = emptyList()
        if (selected.isBlank() || activeDevice?.online != true) return@LaunchedEffect
        val id = selected
        while (true) {
            runCatching { withContext(Dispatchers.IO) { service.refresh(id) } }
                .onSuccess { (row, progress) -> save(row); events = progress }
            delay(2500)
        }
    }

    Text(stringResource(R.string.nm_device_chats), style = MaterialTheme.typography.titleMedium)
    devices.filter { it.online && "task.status" in it.actions }.forEach { target ->
        TextButton(onClick = {
            run {
                val row = withContext(Dispatchers.IO) { service.create(target) }
                save(row)
                selected = row.getString("id")
            }
        }) {
            Text("${stringResource(R.string.nm_device_chat_start)} · ${target.name} · ${target.id.takeLast(6)}")
        }
    }
    rows.forEach { row ->
        TextButton(onClick = { selected = row.getString("id") }) {
            val current = devices.find { it.id == row.optString("device") }
            val prompt = DeviceConversations.turns(row).firstOrNull()?.optString("text")?.take(48) ?: row.getString("id").take(8)
            Text("${deviceLabel(row, current)} · $prompt", color = deviceColor(row.getString("device")))
        }
    }
    if (error && chat == null) Text(stringResource(R.string.nm_hub_err_generic), color = MaterialTheme.colorScheme.error)

    chat?.let { row ->
        val id = row.getString("id")
        val pending = DeviceConversations.pending(row) != null
        val turns = DeviceConversations.turns(row)
        val text = drafts[id].orEmpty()
        AlertDialog(
            onDismissRequest = { selected = "" },
            title = { Text(deviceLabel(row, device), color = deviceColor(row.getString("device"))) },
            text = {
                Column(Modifier.heightIn(max = 440.dp).verticalScroll(rememberScrollState())) {
                    Text(stringResource(if (device?.online == true) R.string.nm_devices_online else R.string.nm_devices_offline))
                    turns.forEach { turn ->
                        turn.optJSONObject("destination")?.let { Text("${it.getString("name")} · ${it.getString("id").takeLast(6)}") }
                        Text(turn.getString("text"), style = MaterialTheme.typography.titleSmall)
                        val status = when (turn.optString("state")) {
                            "accepted" -> stringResource(R.string.nm_coding_working)
                            "unknown" -> stringResource(R.string.nm_device_chat_uncertain)
                            "interrupted" -> stringResource(R.string.nm_device_chat_interrupted)
                            "cancelled" -> stringResource(R.string.nm_coding_stopped)
                            "failed" -> stringResource(R.string.nm_coding_failed, turn.optString("error"))
                            else -> turn.optString("answer")
                        }
                        Text(status)
                    }
                    if (pending) events.forEach { event ->
                        Text(event.optString("text", event.optString("summary", event.optString("preview"))))
                        if (event.optString("stage") == "approval") Row {
                            for (allow in listOf(true, false)) {
                                TextButton(onClick = {
                                    run { withContext(Dispatchers.IO) { service.approve(id, event.getString("approval_id"), allow) } }
                                }) { Text(stringResource(if (allow) R.string.nm_risk_allow_once else R.string.nm_risk_deny)) }
                            }
                        }
                    }
                    OutlinedTextField(text, { drafts[id] = it }, Modifier.fillMaxWidth(),
                        label = { Text(stringResource(R.string.nm_coding_send_hint, device?.name ?: row.optString("name"))) })
                    if (error) Text(stringResource(R.string.nm_hub_err_generic), color = MaterialTheme.colorScheme.error)
                }
            },
            confirmButton = {
                val maySend = text.trimStart().startsWith("@") || (device?.online == true &&
                    turns.none { !it.has("destination") && it.optString("error") == "context_lost" })
                TextButton(enabled = !sending && !pending && maySend && text.isNotBlank(), onClick = {
                    sending = true
                    run {
                        try {
                            save(withContext(Dispatchers.IO) { service.send(id, text) })
                            if (drafts[id] == text) drafts.remove(id)
                        } finally { sending = false }
                    }
                }) { Text(stringResource(R.string.nm_coding_send)) }
            },
            dismissButton = {
                Row {
                    if (pending) TextButton(enabled = activeDevice?.online == true, onClick = {
                        run { withContext(Dispatchers.IO) { service.stop(id) } }
                    }) { Text(stringResource(R.string.nm_coding_stop)) }
                    TextButton(onClick = { selected = "" }) { Text(stringResource(android.R.string.cancel)) }
                }
            },
        )
    }
}

private fun deviceLabel(row: JSONObject, device: Device?): String {
    val icon = if ((device?.kind ?: row.optString("kind")) == "phone") "📱" else "▣"
    return "$icon ${device?.name ?: row.getString("name")} · ${row.getString("device").takeLast(6)}"
}

private fun deviceColor(id: String): Color = Color.hsl(Math.floorMod(id.hashCode(), 360).toFloat(), 0.42f, 0.48f)
