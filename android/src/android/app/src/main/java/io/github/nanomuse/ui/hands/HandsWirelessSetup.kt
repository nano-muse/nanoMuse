// SPDX-License-Identifier: Apache-2.0
// Adapted from Mika (Copyright 2026 wangzan101) for nanoMuse background screen wireless setup.
package io.github.nanomuse.ui.hands

import android.Manifest
import android.content.Context
import android.database.ContentObserver
import android.os.Build
import android.os.Handler
import android.os.Looper
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.outlined.Key
import androidx.compose.material.icons.outlined.Notifications
import androidx.compose.material.icons.outlined.PhoneAndroid
import androidx.compose.material.icons.outlined.PriorityHigh
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.Saver
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.openminis.app.R
import com.openminis.app.accessibility.MinisAccessibilityService
import com.openminis.app.offload.ShizukuManager
import com.openminis.app.ui.settings.SettingsRow
import com.openminis.app.ui.settings.SettingsScaffold
import com.openminis.app.ui.settings.SettingsSection
import io.github.nanomuse.hands.HandsDisplayBridge
import io.github.nanomuse.hands.pairing.DeveloperSettings
import io.github.nanomuse.hands.pairing.HandsWireless
import io.github.nanomuse.hands.pairing.PairingChannelHealth
import io.github.nanomuse.hands.pairing.PairingCode
import io.github.nanomuse.hands.pairing.PairingNotifyIssue
import io.github.nanomuse.hands.pairing.SetupInputs
import io.github.nanomuse.hands.pairing.SetupPhase
import io.github.nanomuse.hands.pairing.SetupStep
import io.github.nanomuse.hands.pairing.SetupSuspect
import io.github.nanomuse.hands.pairing.SetupView
import io.github.nanomuse.hands.pairing.StepMark
import io.github.nanomuse.hands.pairing.WirelessFailure
import io.github.nanomuse.hands.pairing.WirelessFix
import io.github.nanomuse.hands.pairing.WirelessSetupFlow
import io.github.nanomuse.hands.pairing.WirelessStatus
import io.github.nanomuse.ui.home.MuseTones
import kotlinx.coroutines.launch

private val StepSetSaver = Saver<Set<SetupStep>, String>(
    save = { set -> set.joinToString(",") { it.name } },
    restore = { s -> s.split(',').mapNotNull { n -> SetupStep.entries.firstOrNull { it.name == n } }.toSet() },
)

private val OkGreen = Color(0xFF1F8F4E)
private val WarnAmber = Color(0xFFB26A00)

/**
 * Six-step guided setup for the Android background screen via local wireless debugging.
 * Mirrors Mika's flow: watches system toggles live, auto-reads the 6-digit pairing code through
 * the accessibility service when enabled, falls back to a heads-up RemoteInput notification, and
 * keeps manual entry collapsed as a last resort.
 */
@Composable
internal fun HandsWirelessSetup(
    onBack: () -> Unit,
    onOpenShizuku: () -> Unit,
    repairInitially: Boolean = false,
) {
    val context = LocalContext.current
    val app = context.applicationContext
    val scope = rememberCoroutineScope()
    val owner = LocalLifecycleOwner.current

    val shizuku by ShizukuManager.snapshot.collectAsState()
    val bridgeReady by HandsDisplayBridge.ready.collectAsState()
    val wirelessStatus by HandsWireless.status.collectAsState()
    val discovery by HandsWireless.pairingDiscovery.collectAsState()
    val scanningPorts by HandsWireless.scanningPorts.collectAsState()
    val repairing by HandsPairingCoordinator.repairing.collectAsState()
    val a11yInstance by MinisAccessibilityService.instanceFlow.collectAsState()

    var repairStarted by rememberSaveable { mutableStateOf(false) }
    if (repairInitially && !repairStarted) {
        repairStarted = true
        HandsPairingCoordinator.startRepair()
    }

    var confirmed by rememberSaveable(stateSaver = StepSetSaver) { mutableStateOf(emptySet<SetupStep>()) }
    var revisit by rememberSaveable { mutableStateOf<SetupStep?>(null) }
    var askedNotifications by rememberSaveable { mutableStateOf(false) }
    var accessibilitySkipped by rememberSaveable { mutableStateOf(false) }
    var tick by remember { mutableIntStateOf(0) }
    var confirmForget by remember { mutableStateOf(false) }
    var forgetError by remember { mutableStateOf(false) }

    val notificationPermissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { tick++ }

    fun requestNotifications() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU && !HandsPairingNotice.notificationsEnabled(app)) {
            notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        } else {
            DeveloperSettings.launchFirst(context, DeveloperSettings.appNotificationsPage(app.packageName))
        }
    }

    // Watch system Settings.Global switches in real time while the setup page is open.
    DisposableEffect(app) {
        val handler = Handler(Looper.getMainLooper())
        val observer = object : ContentObserver(handler) {
            override fun onChange(selfChange: Boolean) {
                HandsWireless.refreshState(app)
                tick++
            }
        }
        val cr = app.contentResolver
        runCatching { cr.registerContentObserver(DeveloperSettings.developerOptionsUri, false, observer) }
        runCatching { cr.registerContentObserver(DeveloperSettings.usbDebuggingUri, false, observer) }
        runCatching { cr.registerContentObserver(DeveloperSettings.wirelessDebuggingUri, false, observer) }
        HandsWireless.refreshState(app)
        onDispose { runCatching { cr.unregisterContentObserver(observer) } }
    }

    val channelPlan = remember(tick) { HandsPairingNotice.ensureChannel(app) }
    val devOptionsOn = remember(tick) { DeveloperSettings.developerOptions(app.contentResolver) }
    val usbDebugOn = remember(tick) { DeveloperSettings.usbDebugging(app.contentResolver) }
    val wirelessDebugOn = remember(tick) { DeveloperSettings.wirelessDebugging(app.contentResolver) }
    val wirelessMissing = remember(tick) { DeveloperSettings.wirelessDebuggingMissing(app.contentResolver) }
    val devPageMissing = remember(tick) { DeveloperSettings.developerOptionsPageMissing(app.packageManager) }
    val notificationsAllowed = remember(tick) { HandsPairingNotice.notificationsEnabled(app) }
    val restrictedSettings = remember(tick) { DeveloperSettings.restrictedSettingsLikely(app) }
    val pairedNow = remember(tick, wirelessStatus, bridgeReady) { HandsWireless.hasIdentity(app) }

    val effectiveBridgeStatus = remember(wirelessStatus, bridgeReady) {
        if (bridgeReady) WirelessStatus.Running else wirelessStatus
    }

    val inputs = SetupInputs(
        developerOptions = devOptionsOn,
        wirelessDebugging = wirelessDebugOn,
        status = effectiveBridgeStatus,
        discovery = discovery,
        notificationsAllowed = notificationsAllowed,
        pairingChannel = channelPlan.health,
        repair = repairing,
        usbDebugging = usbDebugOn,
        accessibility = a11yInstance != null,
        accessibilitySkipped = accessibilitySkipped,
        restrictedSettings = restrictedSettings,
        confirmed = confirmed,
        revisit = revisit,
        wirelessMissing = wirelessMissing,
        developerSettingsMissing = devPageMissing,
    )
    val view = WirelessSetupFlow.view(inputs)

    // Re-read permissions and system switches on resume; extend 10-minute pairing watch on stop.
    DisposableEffect(owner, view.current) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_RESUME -> {
                    HandsWireless.refreshState(app)
                    tick++
                }
                Lifecycle.Event.ON_STOP -> {
                    if (view.current == SetupStep.PairingCode) {
                        HandsPairingCoordinator.begin(app)
                    }
                }
                else -> Unit
            }
        }
        owner.lifecycle.addObserver(observer)
        onDispose { owner.lifecycle.removeObserver(observer) }
    }

    // Auto-return from a revisited step once its toggle transitions from off to on.
    val revisitDetected = revisit?.let { WirelessSetupFlow.detected(it, inputs) }
    var revisitSawOff by rememberSaveable(revisit) { mutableStateOf(false) }
    LaunchedEffect(revisit, revisitDetected) {
        if (revisitDetected == false) revisitSawOff = true
        else if (revisitDetected == true && revisitSawOff) revisit = null
    }
    LaunchedEffect(view.phase) {
        if (view.phase == SetupPhase.Working || view.phase == SetupPhase.Success) revisit = null
    }

    // Start background discovery, auto-read and silent notification prep as soon as we reach step 5.
    LaunchedEffect(view.current) {
        if (view.current == SetupStep.PairingCode) {
            accessibilitySkipped = true
            HandsPairingCoordinator.begin(app)
        }
    }

    // Prompt once for notification permission when reaching pairing with notifications disabled.
    val notificationsOff = view.notifyIssue == PairingNotifyIssue.NotificationsOff
    LaunchedEffect(notificationsOff) {
        if (notificationsOff && !askedNotifications) {
            askedNotifications = true
            requestNotifications()
        }
    }

    // Automatically connect when already paired and wireless debugging is on.
    LaunchedEffect(view.phase, effectiveBridgeStatus, repairing) {
        if (!repairing && view.phase == SetupPhase.Working && effectiveBridgeStatus == WirelessStatus.WirelessDebuggingOff) {
            HandsWireless.connectAndActivate(app)
        }
    }

    val close = {
        if (view.phase == SetupPhase.Guide || view.phase == SetupPhase.Failed) {
            HandsPairingCoordinator.end(app)
        } else {
            HandsPairingCoordinator.cancelRepair()
        }
        onBack()
    }
    BackHandler(onBack = close)

    HandsWirelessSetupContent(
        view = view,
        paired = pairedNow,
        scanning = scanningPorts,
        forgetError = forgetError,
        optionalShizuku = onOpenShizuku.takeIf { shizuku.state != ShizukuManager.State.NOT_INSTALLED },
        onStepAction = { step ->
            when (step) {
                SetupStep.DeveloperOptions -> DeveloperSettings.launchFirst(context, DeveloperSettings.aboutPhone())
                SetupStep.UsbDebugging -> DeveloperSettings.launchFirst(context, DeveloperSettings.usbDebuggingPage())
                SetupStep.Accessibility -> DeveloperSettings.launchFirst(context, DeveloperSettings.accessibilityPage())
                SetupStep.WirelessDebugging -> DeveloperSettings.launchFirst(context, DeveloperSettings.wirelessDebuggingPage())
                SetupStep.PairingCode -> {
                    HandsPairingCoordinator.begin(app)
                    DeveloperSettings.launchFirst(context, DeveloperSettings.wirelessDebuggingPage())
                }
                SetupStep.Connect -> Unit
            }
        },
        onFailureFix = { fix ->
            when (fix) {
                WirelessFix.Retry -> scope.launch { HandsWireless.retry(app) }
                WirelessFix.RePair -> {
                    HandsPairingCoordinator.startRepair()
                    HandsPairingCoordinator.begin(app)
                    DeveloperSettings.launchFirst(context, DeveloperSettings.wirelessDebuggingPage())
                }
                WirelessFix.OpenWifi -> DeveloperSettings.launchFirst(context, DeveloperSettings.wifiPage())
                WirelessFix.OpenWirelessDebugging -> DeveloperSettings.launchFirst(context, DeveloperSettings.wirelessDebuggingPage())
            }
        },
        onAllowNotifications = ::requestNotifications,
        onOpenPairingChannel = {
            DeveloperSettings.launchFirst(context, DeveloperSettings.channelNotificationsPage(app.packageName, channelPlan.id))
        },
        onAppInfo = {
            DeveloperSettings.launchFirst(context, DeveloperSettings.appInfoPage(app.packageName))
        },
        onSkipAccessibility = {
            accessibilitySkipped = true
            revisit = null
        },
        onConfirmStep = { step ->
            confirmed = confirmed + step
            revisit = null
        },
        onSubmit = { code, port ->
            HandsPairingCoordinator.submit(app, code, port)
        },
        onConnectPort = { port ->
            scope.launch { HandsWireless.connectAndActivate(app, manualPort = port) }
        },
        onRevisit = { step -> revisit = step },
        onStartRepair = {
            HandsPairingCoordinator.startRepair()
            HandsPairingCoordinator.begin(app)
        },
        onRequestForget = { confirmForget = true },
        onClose = close,
    )

    if (confirmForget) {
        AlertDialog(
            onDismissRequest = { confirmForget = false },
            title = { Text(stringResource(R.string.nm_hands_wireless_forget)) },
            text = { Text(stringResource(R.string.nm_hands_wireless_forget_hint)) },
            confirmButton = {
                TextButton(onClick = {
                    confirmForget = false
                    forgetError = false
                    scope.launch {
                        runCatching {
                            HandsPairingCoordinator.end(app)
                            HandsWireless.forget(app)
                        }.onFailure { forgetError = true }
                        tick++
                    }
                }) {
                    Text(stringResource(R.string.nm_devices_forget), color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = {
                TextButton(onClick = { confirmForget = false }) {
                    Text(stringResource(R.string.cancel))
                }
            },
        )
    }
}

@Composable
internal fun HandsWirelessSetupContent(
    view: SetupView,
    paired: Boolean,
    scanning: Boolean,
    forgetError: Boolean = false,
    optionalShizuku: (() -> Unit)? = null,
    onStepAction: (SetupStep) -> Unit,
    onFailureFix: (WirelessFix) -> Unit,
    onAllowNotifications: () -> Unit,
    onOpenPairingChannel: () -> Unit,
    onAppInfo: () -> Unit,
    onSkipAccessibility: () -> Unit,
    onConfirmStep: (SetupStep) -> Unit,
    onSubmit: (code: String, port: Int?) -> Unit,
    onConnectPort: (Int) -> Unit,
    onRevisit: (SetupStep?) -> Unit,
    onStartRepair: () -> Unit,
    onRequestForget: () -> Unit,
    onClose: () -> Unit,
) {
    val canRevisit = view.phase == SetupPhase.Guide || view.phase == SetupPhase.Failed
    fun revisitable(step: SetupStep): Boolean =
        canRevisit &&
            step != view.current &&
            step in WirelessSetupFlow.REVISITABLE &&
            view.marks.getValue(step) in setOf(StepMark.Done, StepMark.Skipped, StepMark.Failed)

    SettingsScaffold(
        title = stringResource(R.string.nm_hands_wireless_title),
        onBack = onClose,
        scrollable = false,
    ) {
        Column(
            modifier = Modifier
                .weight(1f)
                .verticalScroll(rememberScrollState()),
        ) {
            if (view.phase == SetupPhase.Unavailable) {
                SettingsSection {
                    Column(Modifier.fillMaxWidth().padding(16.dp).testTag("setup-unavailable")) {
                        Text(
                            stringResource(R.string.nm_hands_wireless_unavailable),
                            style = MaterialTheme.typography.titleSmall,
                            fontWeight = FontWeight.SemiBold,
                        )
                        Spacer(Modifier.height(6.dp))
                        Text(
                            stringResource(R.string.nm_hands_wireless_unavailable_reason),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
            } else {
                Text(
                    text = stringResource(
                        if (view.phase == SetupPhase.Success) R.string.nm_hands_wireless_success
                        else R.string.nm_hands_wireless_intro,
                    ),
                    fontSize = 14.sp,
                    lineHeight = 20.sp,
                    fontWeight = if (view.phase == SetupPhase.Success) FontWeight.SemiBold else FontWeight.Normal,
                    color = if (view.phase == SetupPhase.Success) OkGreen else MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier
                        .padding(horizontal = 16.dp)
                        .padding(top = 12.dp, bottom = 4.dp)
                        .testTag(if (view.phase == SetupPhase.Success) "setup-success" else "setup-intro"),
                )

                SettingsSection {
                    SetupStep.entries.forEachIndexed { index, step ->
                        if (index > 0) {
                            HorizontalDivider(
                                modifier = Modifier.padding(start = 56.dp),
                                thickness = 0.5.dp,
                                color = MuseTones.hairline,
                            )
                        }
                        SetupStepRow(
                            step = step,
                            mark = view.marks.getValue(step),
                            current = step == view.current,
                            onClick = if (revisitable(step)) ({ onRevisit(step) }) else null,
                        ) {
                            if (step == view.current) {
                                CurrentStepBody(
                                    step = step,
                                    view = view,
                                    onStepAction = onStepAction,
                                    onFailureFix = onFailureFix,
                                    onAllowNotifications = onAllowNotifications,
                                    onOpenPairingChannel = onOpenPairingChannel,
                                    onAppInfo = onAppInfo,
                                    onSkipAccessibility = onSkipAccessibility,
                                    onConfirmStep = onConfirmStep,
                                    onSubmit = onSubmit,
                                    onConnectPort = onConnectPort,
                                    onRevisit = onRevisit,
                                )
                            }
                            if (step == SetupStep.Connect && view.phase == SetupPhase.Working) {
                                WorkingLine(scanning = scanning)
                            }
                        }
                    }
                }

                if (SetupStep.entries.any(::revisitable)) {
                    Text(
                        text = stringResource(R.string.nm_hands_wireless_revisit_note),
                        fontSize = 12.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(horizontal = 20.dp, vertical = 4.dp),
                    )
                }
                if (view.phase != SetupPhase.Success) {
                    Text(
                        text = stringResource(R.string.nm_hands_wireless_skip_note),
                        fontSize = 12.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(horizontal = 20.dp, vertical = 4.dp),
                    )
                }

                if (paired && view.phase != SetupPhase.Working) {
                    SettingsSection {
                        SettingsRow(
                            title = stringResource(R.string.nm_hands_wireless_repair),
                            subtitle = stringResource(R.string.nm_hands_wireless_repair_sub),
                            onClick = onStartRepair,
                        )
                        SettingsRow(
                            title = stringResource(R.string.nm_hands_wireless_forget),
                            titleColor = MaterialTheme.colorScheme.error,
                            onClick = onRequestForget,
                            showDivider = false,
                        )
                    }
                }

                if (forgetError) {
                    Text(
                        text = stringResource(R.string.nm_hands_wireless_forget_error),
                        color = MaterialTheme.colorScheme.error,
                        fontSize = 13.sp,
                        modifier = Modifier.padding(horizontal = 20.dp, vertical = 6.dp),
                    )
                }

                optionalShizuku?.let { openShizuku ->
                    SettingsSection {
                        SettingsRow(
                            title = stringResource(R.string.shizuku_title),
                            onClick = openShizuku,
                            showDivider = false,
                        )
                    }
                }
            }
            Spacer(Modifier.height(16.dp))
        }

        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 10.dp),
        ) {
            if (view.phase == SetupPhase.Success) {
                Text(
                    text = stringResource(R.string.nm_hands_wireless_success_note),
                    fontSize = 12.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.fillMaxWidth().padding(bottom = 10.dp),
                )
                Button(
                    onClick = onClose,
                    modifier = Modifier.fillMaxWidth().testTag("setup-done"),
                    colors = ButtonDefaults.buttonColors(containerColor = MuseTones.action),
                ) {
                    Text(stringResource(R.string.nm_hands_wireless_done))
                }
            } else {
                TextButton(
                    onClick = onClose,
                    modifier = Modifier.fillMaxWidth().testTag("setup-later"),
                ) {
                    Text(stringResource(R.string.nm_hands_wireless_later))
                }
            }
        }
    }
}

@Composable
private fun SetupStepRow(
    step: SetupStep,
    mark: StepMark,
    current: Boolean,
    onClick: (() -> Unit)?,
    body: @Composable () -> Unit,
) {
    val copy = stepCopy(step)
    val muted = MaterialTheme.colorScheme.onSurfaceVariant
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(horizontal = 16.dp, vertical = 14.dp)
            .testTag("setup-step-${step.name}"),
        horizontalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        StepBadge(number = step.ordinal + 1, mark = mark)
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = stringResource(copy.title),
                    modifier = Modifier.weight(1f),
                    fontSize = 15.sp,
                    fontWeight = if (mark == StepMark.Current || mark == StepMark.Failed) FontWeight.SemiBold else FontWeight.Medium,
                    color = if (mark == StepMark.Todo || mark == StepMark.Skipped) muted else MaterialTheme.colorScheme.onSurface,
                )
                if (mark == StepMark.Done) {
                    Text(
                        text = stringResource(copy.done),
                        fontSize = 12.sp,
                        fontWeight = FontWeight.Medium,
                        color = OkGreen,
                    )
                }
                if (mark == StepMark.Skipped) {
                    Text(
                        text = stringResource(R.string.nm_hands_wireless_skipped),
                        fontSize = 12.sp,
                        color = muted,
                    )
                }
            }
            if (!current) {
                Text(
                    text = stringResource(copy.brief),
                    fontSize = 13.sp,
                    lineHeight = 18.sp,
                    color = muted,
                    modifier = Modifier.padding(top = 2.dp),
                )
            }
            body()
        }
    }
}

@Composable
private fun StepBadge(number: Int, mark: StepMark) {
    val bg = when (mark) {
        StepMark.Done -> OkGreen
        StepMark.Current -> MuseTones.action
        StepMark.Failed -> MaterialTheme.colorScheme.error
        StepMark.Todo, StepMark.Skipped -> MuseTones.fill
    }
    Box(
        modifier = Modifier.size(28.dp).clip(CircleShape).background(bg),
        contentAlignment = Alignment.Center,
    ) {
        when (mark) {
            StepMark.Done -> Icon(Icons.Filled.Check, contentDescription = null, modifier = Modifier.size(16.dp), tint = Color.White)
            StepMark.Failed -> Icon(Icons.Outlined.PriorityHigh, contentDescription = null, modifier = Modifier.size(16.dp), tint = Color.White)
            else -> Text(
                text = "$number",
                fontSize = 12.sp,
                fontWeight = FontWeight.Bold,
                color = if (mark == StepMark.Current) Color.White else MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun CurrentStepBody(
    step: SetupStep,
    view: SetupView,
    onStepAction: (SetupStep) -> Unit,
    onFailureFix: (WirelessFix) -> Unit,
    onAllowNotifications: () -> Unit,
    onOpenPairingChannel: () -> Unit,
    onAppInfo: () -> Unit,
    onSkipAccessibility: () -> Unit,
    onConfirmStep: (SetupStep) -> Unit,
    onSubmit: (String, Int?) -> Unit,
    onConnectPort: (Int) -> Unit,
    onRevisit: (SetupStep?) -> Unit,
) {
    val copy = stepCopy(step)
    Text(
        text = stringResource(copy.body),
        fontSize = 13.sp,
        lineHeight = 19.sp,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(top = 4.dp),
    )

    view.failure?.let { failed ->
        val (failTitle, failBody) = failureCopy(failed.reason)
        Column(
            modifier = Modifier
                .padding(top = 10.dp)
                .fillMaxWidth()
                .clip(RoundedCornerShape(10.dp))
                .background(MaterialTheme.colorScheme.errorContainer.copy(alpha = 0.55f))
                .padding(12.dp),
        ) {
            Text(
                text = stringResource(failTitle),
                fontSize = 14.sp,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.error,
            )
            Text(
                text = stringResource(failBody),
                fontSize = 12.sp,
                lineHeight = 17.sp,
                color = MaterialTheme.colorScheme.onSurface,
                modifier = Modifier.padding(top = 3.dp),
            )
        }
        ActionPill(
            text = stringResource(fixLabel(failed.fix)),
            primary = true,
            tag = "setup-fix",
            onClick = { onFailureFix(failed.fix) },
        )
        if (step == SetupStep.Connect && failed.reason == WirelessFailure.ConnectFailed) {
            ConnectPortFallback(onConnect = onConnectPort)
        }
    }

    view.suspect?.let { suspect ->
        val suspectText = when {
            suspect.step == SetupStep.DeveloperOptions -> stringResource(R.string.nm_hands_wireless_suspect_dev)
            suspect.unreadable -> stringResource(R.string.nm_hands_wireless_suspect_wifi_unreadable)
            else -> stringResource(R.string.nm_hands_wireless_suspect_wifi_off)
        }
        Column(
            modifier = Modifier
                .padding(top = 10.dp)
                .fillMaxWidth()
                .clip(RoundedCornerShape(10.dp))
                .background(WarnAmber.copy(alpha = 0.12f))
                .padding(12.dp)
                .testTag("setup-suspect"),
        ) {
            Text(text = suspectText, fontSize = 12.sp, lineHeight = 18.sp, color = MaterialTheme.colorScheme.onSurface)
        }
        ActionPill(
            text = stringResource(R.string.nm_hands_wireless_suspect_go_back, stringResource(stepCopy(suspect.step).title)),
            primary = view.failure == null,
            tag = "setup-suspect-back",
            onClick = { onRevisit(suspect.step) },
        )
    }

    val fixNotificationsFirst = step == SetupStep.PairingCode && view.needsNotifications && !view.autoRead
    if (step == SetupStep.PairingCode) {
        val channelName = stringResource(R.string.nm_hands_wireless_channel_name)
        when (view.notifyIssue) {
            PairingNotifyIssue.NotificationsOff -> {
                Text(
                    text = stringResource(R.string.nm_hands_wireless_need_notif),
                    fontSize = 12.sp,
                    color = WarnAmber,
                    modifier = Modifier.padding(top = 8.dp),
                )
                ActionPill(
                    text = stringResource(R.string.nm_hands_wireless_allow_notif),
                    primary = fixNotificationsFirst,
                    tag = "setup-notify-fix",
                    onClick = onAllowNotifications,
                )
            }
            PairingNotifyIssue.ChannelOff -> {
                Text(
                    text = stringResource(R.string.nm_hands_wireless_channel_off, channelName),
                    fontSize = 12.sp,
                    color = WarnAmber,
                    modifier = Modifier.padding(top = 8.dp),
                )
                ActionPill(
                    text = stringResource(R.string.nm_hands_wireless_open_channel, channelName),
                    primary = fixNotificationsFirst,
                    tag = "setup-notify-fix",
                    onClick = onOpenPairingChannel,
                )
            }
            PairingNotifyIssue.NotHeadsUp -> if (!view.autoRead) {
                Column(
                    modifier = Modifier
                        .padding(top = 10.dp)
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(10.dp))
                        .background(WarnAmber.copy(alpha = 0.12f))
                        .padding(12.dp)
                        .testTag("setup-pairing-lowered"),
                ) {
                    Text(
                        text = stringResource(R.string.nm_hands_wireless_channel_lowered, channelName),
                        fontSize = 12.sp,
                        lineHeight = 18.sp,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                }
                ActionPill(
                    text = stringResource(R.string.nm_hands_wireless_open_heads_up),
                    primary = false,
                    tag = "setup-pairing-lowered-open",
                    onClick = onOpenPairingChannel,
                )
            }
            null -> Unit
        }
        if (view.autoRead) AutoReadHintCard() else NotifyGuideCard()
        if (view.portFound && !view.autoRead) {
            Text(
                text = stringResource(R.string.nm_hands_wireless_port_found),
                fontSize = 12.sp,
                color = OkGreen,
                modifier = Modifier.padding(top = 8.dp),
            )
        }
    }

    val isA11yStep = step == SetupStep.Accessibility
    if (view.failure == null && copy.action != null) {
        ActionPill(
            text = stringResource(copy.action),
            primary = !fixNotificationsFirst,
            tag = "setup-action",
            onClick = { onStepAction(step) },
        )
    }
    if (isA11yStep && view.showAppInfo) {
        ActionPill(
            text = stringResource(R.string.nm_hands_wireless_app_info),
            primary = false,
            tag = "setup-app-info",
            onClick = onAppInfo,
        )
    }
    if (isA11yStep) {
        ActionPill(
            text = stringResource(R.string.nm_hands_wireless_a11y_skip),
            primary = false,
            tag = "setup-skip-a11y",
            onClick = onSkipAccessibility,
        )
    }
    if (step in WirelessSetupFlow.CONFIRMABLE) {
        ActionPill(
            text = stringResource(R.string.nm_hands_wireless_turned_on_next),
            primary = false,
            tag = "setup-confirm",
            onClick = { onConfirmStep(step) },
        )
    }
    if (step == SetupStep.PairingCode) {
        ManualCodeFallback(askPort = !view.portFound, onSubmit = onSubmit)
    }
    if (view.revisiting) {
        Text(
            text = stringResource(R.string.nm_hands_wireless_revisit_back),
            fontSize = 13.sp,
            color = MuseTones.action,
            modifier = Modifier
                .padding(top = 8.dp)
                .clickable { onRevisit(null) }
                .padding(vertical = 4.dp)
                .testTag("setup-revisit-back"),
        )
    }
}

@Composable
private fun AutoReadHintCard() {
    Row(
        modifier = Modifier
            .padding(top = 10.dp)
            .fillMaxWidth()
            .clip(RoundedCornerShape(10.dp))
            .background(OkGreen.copy(alpha = 0.12f))
            .padding(12.dp)
            .testTag("setup-pairing-hint"),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Icon(Icons.Filled.Check, contentDescription = null, modifier = Modifier.size(20.dp), tint = OkGreen)
        Column {
            Text(
                text = stringResource(R.string.nm_hands_wireless_auto_read),
                fontSize = 13.sp,
                lineHeight = 18.sp,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                text = stringResource(
                    R.string.nm_hands_wireless_auto_read_fallback,
                    stringResource(R.string.nm_hands_wireless_notify_enter_title),
                ),
                fontSize = 12.sp,
                lineHeight = 17.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 4.dp),
            )
        }
    }
}

@Composable
private fun NotifyGuideCard() {
    val lines = listOf(
        stringResource(R.string.nm_hands_wireless_guide_1),
        stringResource(R.string.nm_hands_wireless_guide_2),
        stringResource(R.string.nm_hands_wireless_guide_3, stringResource(R.string.nm_hands_wireless_notify_action)),
    )
    val icons = listOf(Icons.Outlined.PhoneAndroid, Icons.Outlined.Notifications, Icons.Outlined.Key)
    Column(
        modifier = Modifier
            .padding(top = 10.dp)
            .fillMaxWidth()
            .clip(RoundedCornerShape(10.dp))
            .background(MuseTones.action.copy(alpha = 0.08f))
            .padding(12.dp)
            .testTag("setup-pairing-guide"),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        lines.forEachIndexed { index, line ->
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Box(
                    modifier = Modifier.size(22.dp).clip(CircleShape).background(MuseTones.action),
                    contentAlignment = Alignment.Center,
                ) {
                    Text("${index + 1}", fontSize = 11.sp, fontWeight = FontWeight.Bold, color = Color.White)
                }
                Icon(icons[index], contentDescription = null, modifier = Modifier.size(18.dp), tint = MuseTones.action)
                Text(
                    text = line,
                    modifier = Modifier.weight(1f),
                    fontSize = 13.sp,
                    fontWeight = FontWeight.Medium,
                    color = MaterialTheme.colorScheme.onSurface,
                )
            }
        }
    }
}

@Composable
private fun ManualCodeFallback(askPort: Boolean, onSubmit: (String, Int?) -> Unit) {
    var open by rememberSaveable { mutableStateOf(false) }
    var code by remember { mutableStateOf("") }
    var port by rememberSaveable { mutableStateOf("") }
    var errorRes by remember { mutableStateOf<Int?>(null) }

    Text(
        text = stringResource(R.string.nm_hands_wireless_manual_toggle),
        fontSize = 13.sp,
        color = MuseTones.action,
        modifier = Modifier
            .padding(top = 10.dp)
            .clickable { open = !open }
            .padding(vertical = 4.dp)
            .testTag("setup-manual"),
    )
    if (!open) return

    Text(
        text = stringResource(R.string.nm_hands_wireless_manual_hint),
        fontSize = 12.sp,
        lineHeight = 17.sp,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    OutlinedTextField(
        value = code,
        onValueChange = { code = it; errorRes = null },
        modifier = Modifier.fillMaxWidth().padding(top = 6.dp).testTag("setup-code"),
        label = { Text(stringResource(R.string.nm_hands_wireless_code_label)) },
        singleLine = true,
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
    )
    if (askPort) {
        OutlinedTextField(
            value = port,
            onValueChange = { port = it; errorRes = null },
            modifier = Modifier.fillMaxWidth().padding(top = 6.dp).testTag("setup-port"),
            label = { Text(stringResource(R.string.nm_hands_wireless_port_label)) },
            supportingText = { Text(stringResource(R.string.nm_hands_wireless_port_hint)) },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
        )
    }
    errorRes?.let { res ->
        Text(
            text = stringResource(res),
            fontSize = 12.sp,
            color = MaterialTheme.colorScheme.error,
            modifier = Modifier.padding(top = 4.dp),
        )
    }
    ActionPill(
        text = stringResource(R.string.nm_hands_wireless_submit),
        primary = true,
        tag = "setup-submit",
        onClick = {
            val normalizedCode = PairingCode.normalize(code)
            val parsedPort = if (askPort && port.isNotBlank()) PairingCode.port(port) else null
            errorRes = when {
                normalizedCode == null -> R.string.nm_hands_wireless_code_invalid
                askPort && port.isNotBlank() && parsedPort == null -> R.string.nm_hands_wireless_port_invalid
                else -> null
            }
            if (errorRes == null && normalizedCode != null) {
                code = ""
                onSubmit(normalizedCode, parsedPort)
            }
        },
    )
}

@Composable
private fun ConnectPortFallback(onConnect: (Int) -> Unit) {
    var port by rememberSaveable { mutableStateOf("") }
    var invalid by remember { mutableStateOf(false) }

    OutlinedTextField(
        value = port,
        onValueChange = { port = it; invalid = false },
        modifier = Modifier.fillMaxWidth().padding(top = 10.dp).testTag("setup-connect-port"),
        label = { Text(stringResource(R.string.nm_hands_wireless_connect_port_label)) },
        supportingText = {
            Text(
                text = stringResource(
                    if (invalid) R.string.nm_hands_wireless_port_invalid else R.string.nm_hands_wireless_connect_port_hint,
                ),
                color = if (invalid) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant,
            )
        },
        singleLine = true,
        isError = invalid,
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
    )
    ActionPill(
        text = stringResource(R.string.nm_hands_wireless_connect_port_submit),
        primary = false,
        tag = "setup-connect-port-submit",
        onClick = {
            val parsed = PairingCode.parseConnectPort(port)
            invalid = parsed == null
            if (parsed != null) onConnect(parsed)
        },
    )
}

@Composable
private fun WorkingLine(scanning: Boolean) {
    Row(
        modifier = Modifier.padding(top = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        CircularProgressIndicator(modifier = Modifier.size(16.dp), color = MuseTones.action, strokeWidth = 2.dp)
        Text(
            text = stringResource(
                if (scanning) R.string.nm_hands_wireless_scanning_ports else R.string.nm_hands_wireless_working,
            ),
            fontSize = 13.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.testTag("setup-working"),
        )
    }
}

@Composable
private fun ActionPill(text: String, primary: Boolean, tag: String? = null, onClick: () -> Unit) {
    val mod = Modifier.padding(top = 10.dp).then(if (tag != null) Modifier.testTag(tag) else Modifier)
    if (primary) {
        Button(
            onClick = onClick,
            modifier = mod,
            colors = ButtonDefaults.buttonColors(containerColor = MuseTones.action),
        ) {
            Text(text)
        }
    } else {
        FilledTonalButton(onClick = onClick, modifier = mod) {
            Text(text)
        }
    }
}

private data class StepCopyRes(
    val title: Int,
    val body: Int,
    val action: Int?,
    val done: Int,
    val brief: Int,
)

private fun stepCopy(step: SetupStep): StepCopyRes = when (step) {
    SetupStep.DeveloperOptions -> StepCopyRes(
        title = R.string.nm_hands_wireless_step_dev,
        body = R.string.nm_hands_wireless_step_dev_body,
        action = R.string.nm_hands_wireless_step_dev_action,
        done = R.string.nm_hands_wireless_done_on,
        brief = R.string.nm_hands_wireless_step_dev_brief,
    )
    SetupStep.UsbDebugging -> StepCopyRes(
        title = R.string.nm_hands_wireless_step_usb,
        body = R.string.nm_hands_wireless_step_usb_body,
        action = R.string.nm_hands_wireless_step_usb_action,
        done = R.string.nm_hands_wireless_done_on,
        brief = R.string.nm_hands_wireless_step_usb_brief,
    )
    SetupStep.Accessibility -> StepCopyRes(
        title = R.string.nm_hands_wireless_step_a11y,
        body = R.string.nm_hands_wireless_step_a11y_body,
        action = R.string.nm_hands_wireless_step_a11y_action,
        done = R.string.nm_hands_wireless_done_on,
        brief = R.string.nm_hands_wireless_step_a11y_brief,
    )
    SetupStep.WirelessDebugging -> StepCopyRes(
        title = R.string.nm_hands_wireless_step_wifi_adb,
        body = R.string.nm_hands_wireless_step_wifi_adb_body,
        action = R.string.nm_hands_wireless_step_wifi_adb_action,
        done = R.string.nm_hands_wireless_done_on,
        brief = R.string.nm_hands_wireless_step_wifi_adb_brief,
    )
    SetupStep.PairingCode -> StepCopyRes(
        title = R.string.nm_hands_wireless_step_pair,
        body = R.string.nm_hands_wireless_step_pair_body,
        action = R.string.nm_hands_wireless_step_pair_action,
        done = R.string.nm_hands_wireless_done_paired,
        brief = R.string.nm_hands_wireless_step_pair_brief,
    )
    SetupStep.Connect -> StepCopyRes(
        title = R.string.nm_hands_wireless_step_connect,
        body = R.string.nm_hands_wireless_step_connect_body,
        action = null,
        done = R.string.nm_hands_wireless_done_connected,
        brief = R.string.nm_hands_wireless_step_connect_brief,
    )
}

private fun failureCopy(reason: WirelessFailure): Pair<Int, Int> = when (reason) {
    WirelessFailure.WrongCode -> R.string.nm_hands_wireless_fail_wrong_code to R.string.nm_hands_wireless_fail_wrong_code_body
    WirelessFailure.PairingWindowClosed -> R.string.nm_hands_wireless_fail_window_closed to R.string.nm_hands_wireless_fail_window_closed_body
    WirelessFailure.NoWifi -> R.string.nm_hands_wireless_fail_no_wifi to R.string.nm_hands_wireless_fail_no_wifi_body
    WirelessFailure.ConnectFailed -> R.string.nm_hands_wireless_fail_connect to R.string.nm_hands_wireless_fail_connect_body
    WirelessFailure.AuthorizationRevoked -> R.string.nm_hands_wireless_fail_revoked to R.string.nm_hands_wireless_fail_revoked_body
    WirelessFailure.HelperStartFailed -> R.string.nm_hands_wireless_fail_helper to R.string.nm_hands_wireless_fail_helper_body
    WirelessFailure.Unknown -> R.string.nm_hands_wireless_fail_unknown to R.string.nm_hands_wireless_fail_unknown_body
}

private fun fixLabel(fix: WirelessFix): Int = when (fix) {
    WirelessFix.Retry -> R.string.nm_hands_wireless_fix_retry
    WirelessFix.RePair -> R.string.nm_hands_wireless_fix_repair
    WirelessFix.OpenWifi -> R.string.nm_hands_wireless_fix_wifi
    WirelessFix.OpenWirelessDebugging -> R.string.nm_hands_wireless_fix_wireless
}
