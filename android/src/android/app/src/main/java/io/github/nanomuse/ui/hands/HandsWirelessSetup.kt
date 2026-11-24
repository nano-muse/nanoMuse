package io.github.nanomuse.ui.hands

import android.Manifest
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.provider.Settings
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import com.openminis.app.R
import com.openminis.app.offload.ShizukuManager
import com.openminis.app.ui.settings.SettingsRow
import com.openminis.app.ui.settings.SettingsScaffold
import com.openminis.app.ui.settings.SettingsSection
import io.github.nanomuse.hands.HandsDisplayBridge
import io.github.nanomuse.hands.pairing.HandsWireless
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Job
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
internal fun HandsWirelessSetup(onBack: () -> Unit, onOpenShizuku: () -> Unit) {
    val context = LocalContext.current
    val app = context.applicationContext
    val shizuku by ShizukuManager.snapshot.collectAsState()
    val ready by HandsDisplayBridge.ready.collectAsState()
    var permission by remember { mutableStateOf<CompletableDeferred<Boolean>?>(null) }
    val permissionLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        permission?.complete(granted)
    }
    HandsWirelessForm(
        onBack = onBack,
        ready = ready,
        pairedInitially = remember(app) { HandsWireless.hasIdentity(app) },
        openSettings = { openDeveloperOptions(context) },
        discover = { pairing -> HandsWireless.discover(app, pairing) },
        pair = { port, code -> HandsWireless.pair(app, port, code) },
        activate = { port -> HandsWireless.activate(app, port) },
        forget = { HandsWireless.forget(app) },
        getNoticeReply = {
            if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(app, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                val answer = CompletableDeferred<Boolean>()
                permission = answer
                try {
                    permissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
                    if (!answer.await()) throw HandsPairingNotice.Unavailable()
                } finally { permission = null }
            }
            HandsPairingNotice.await(app) { openDeveloperOptions(context) }
        },
        optionalShizuku = onOpenShizuku.takeIf { shizuku.state != ShizukuManager.State.NOT_INSTALLED },
    )
}

private fun openDeveloperOptions(context: Context): Boolean {
    val developer = Settings.Global.getInt(context.contentResolver, Settings.Global.DEVELOPMENT_SETTINGS_ENABLED, 0) != 0
    val actions = if (developer) listOf(Settings.ACTION_APPLICATION_DEVELOPMENT_SETTINGS, Settings.ACTION_SETTINGS)
        else listOf(Settings.ACTION_DEVICE_INFO_SETTINGS, Settings.ACTION_SETTINGS)
    return actions.any { action ->
        try {
            context.startActivity(Intent(action).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            true
        } catch (_: ActivityNotFoundException) { false }
        catch (_: SecurityException) { false }
    }
}

@Composable
internal fun HandsWirelessForm(
    onBack: () -> Unit, ready: Boolean, pairedInitially: Boolean, openSettings: () -> Boolean,
    discover: suspend (pairing: Boolean) -> List<Int>, pair: suspend (Int, String) -> Unit,
    activate: suspend (Int) -> Unit, forget: suspend () -> Unit,
    getNoticeReply: (suspend () -> HandsPairingReply?)? = null, optionalShizuku: (() -> Unit)? = null,
) {
    BackHandler(onBack = onBack)
    val scope = rememberCoroutineScope()
    var paired by remember { mutableStateOf(pairedInitially) }
    var pairAgain by remember { mutableStateOf(false) }
    val pairing = !paired || pairAgain
    var port by remember(pairing) { mutableStateOf("") }
    // The system code is transient. Do not save it across recreation, log it or expose it in an error.
    var code by remember(pairing) { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var notice by remember { mutableStateOf<Int?>(null) }
    var confirmForget by remember { mutableStateOf(false) }
    var noticeJob by remember { mutableStateOf<Job?>(null) }
    var awaitingNotice by remember { mutableStateOf(false) }
    fun runAction(onError: Int, block: suspend () -> Unit): Job? {
        if (busy) return null
        busy = true
        notice = null
        return scope.launch {
            try { block() } catch (cancelled: CancellationException) { throw cancelled }
            catch (_: Exception) { notice = onError }
            finally { busy = false }
        }
    }
    suspend fun findPort(input: String, forPair: Boolean): Int? {
        if (input.isNotEmpty()) return input.toIntOrNull()?.takeIf { it in 1..65535 }
        return withContext(Dispatchers.IO) { discover(forPair) }.distinct().singleOrNull()?.takeIf { it in 1..65535 }
    }
    suspend fun connect(input: String) {
        val connection = findPort(input, false)
        if (connection == null) notice = R.string.nm_hands_wireless_port_missing
        else withContext(Dispatchers.IO) { activate(connection) }
    }
    suspend fun pairPhone(enteredPort: String, enteredCode: String) {
        val pairingPort = findPort(enteredPort, true)
        if (pairingPort == null) {
            notice = R.string.nm_hands_wireless_port_missing
            return
        }
        code = ""
        withContext(Dispatchers.IO) { pair(pairingPort, enteredCode) }
        paired = true
        pairAgain = false
        try { connect("") } catch (cancelled: CancellationException) { throw cancelled }
        catch (_: Exception) { notice = R.string.nm_hands_wireless_connect_error }
    }
    // Opening setup explicitly requests a connection. Reuse a previous pairing once.
    LaunchedEffect(Unit) {
        if (pairedInitially && !ready) runAction(R.string.nm_hands_wireless_connect_error) { connect("") }
    }
    SettingsScaffold(title = stringResource(R.string.nm_hands_wireless_title), onBack = onBack) {
        SettingsSection(footer = stringResource(R.string.nm_hands_wireless_prepare)) {
            SettingsRow(
                title = stringResource(R.string.nm_hands_wireless_settings),
                onClick = { if (!openSettings()) notice = R.string.nm_hands_wireless_prepare },
                showDivider = false,
            )
        }
        if (ready && !pairAgain) {
            SettingsSection { SettingsRow(title = stringResource(R.string.nm_hands_status_ready), showDivider = false) }
        } else {
            val validPort = port.isEmpty() || port.toIntOrNull()?.let { it in 1..65535 } == true
            SettingsSection {
                Column(Modifier.fillMaxWidth().padding(16.dp)) {
                    Text(stringResource(if (pairing) R.string.nm_hands_wireless_pair_help else R.string.nm_hands_wireless_connect_help))
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        value = port, onValueChange = { if (it.length <= 5 && it.all { c -> c in '0'..'9' }) port = it },
                        enabled = !busy, singleLine = true, isError = !validPort,
                        label = { Text(stringResource(R.string.nm_network_port)) },
                        supportingText = { Text(stringResource(R.string.nm_hands_wireless_auto_port)) },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                        modifier = Modifier.fillMaxWidth(),
                    )
                    if (pairing) {
                        OutlinedTextField(
                            value = code, onValueChange = { if (it.length <= 6 && it.all { c -> c in '0'..'9' }) code = it },
                            enabled = !busy, singleLine = true,
                            label = { Text(stringResource(R.string.nm_hands_wireless_code)) },
                            visualTransformation = PasswordVisualTransformation(),
                            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
                            modifier = Modifier.fillMaxWidth(),
                        )
                    }
                    Spacer(Modifier.height(8.dp))
                    Button(enabled = !busy && validPort && (!pairing || code.length == 6), onClick = {
                        val isPairing = pairing
                        val enteredCode = code
                        val enteredPort = port
                        runAction(if (isPairing) R.string.nm_hands_wireless_pair_error else R.string.nm_hands_wireless_connect_error) {
                            if (isPairing) pairPhone(enteredPort, enteredCode) else connect(enteredPort)
                        }
                    }) {
                        Text(stringResource(if (busy) R.string.backup_working else if (pairing) R.string.nm_hands_wireless_pair else R.string.nm_connectors_connect))
                    }
                    if (pairing && getNoticeReply != null) {
                        if (awaitingNotice) {
                            TextButton(onClick = { noticeJob?.cancel() }) { Text(stringResource(R.string.cancel)) }
                        } else {
                            TextButton(enabled = !busy && validPort, onClick = {
                                val enteredPort = port
                                noticeJob = runAction(R.string.nm_hands_wireless_pair_error) {
                                    awaitingNotice = true
                                    val reply = try { getNoticeReply() }
                                    catch (_: HandsPairingNotice.Unavailable) {
                                        notice = R.string.nm_hands_wireless_notification_disabled
                                        return@runAction
                                    } finally { awaitingNotice = false }
                                    if (reply == null) {
                                        notice = R.string.nm_hands_wireless_notification_again
                                        return@runAction
                                    }
                                    pairPhone(reply.port?.toString() ?: enteredPort, reply.code)
                                }
                            }) { Text(stringResource(R.string.nm_hands_wireless_notification)) }
                        }
                    }
                }
            }
        }
        notice?.let { Text(stringResource(it), modifier = Modifier.padding(horizontal = 24.dp, vertical = 8.dp), color = MaterialTheme.colorScheme.error) }
        if (paired) {
            SettingsSection {
                if (!ready && !pairAgain) SettingsRow(
                    title = stringResource(R.string.nm_hands_wireless_pair),
                    onClick = if (busy) null else { { pairAgain = true; notice = null } },
                )
                SettingsRow(
                    title = stringResource(R.string.nm_hands_wireless_forget),
                    onClick = if (busy) null else { { confirmForget = true } },
                    showDivider = false,
                )
            }
        }
        optionalShizuku?.let { SettingsSection { SettingsRow(title = stringResource(R.string.shizuku_title), onClick = it, showDivider = false) } }
        Spacer(Modifier.height(24.dp))
    }
    if (confirmForget) {
        AlertDialog(onDismissRequest = { confirmForget = false },
            title = { Text(stringResource(R.string.nm_hands_wireless_forget)) },
            text = { Text(stringResource(R.string.nm_hands_wireless_forget_hint)) },
            confirmButton = { TextButton(onClick = {
                confirmForget = false
                runAction(R.string.nm_hands_wireless_forget_error) {
                    withContext(Dispatchers.IO) { forget() }
                    paired = false
                    pairAgain = false
                    port = ""
                    code = ""
                }
            }) { Text(stringResource(R.string.nm_devices_forget)) } },
            dismissButton = { TextButton(onClick = { confirmForget = false }) { Text(stringResource(R.string.cancel)) } },
        )
    }
}
