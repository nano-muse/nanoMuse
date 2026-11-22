package io.github.nanomuse.ui.hands

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Accessibility
import androidx.compose.material.icons.outlined.Layers
import androidx.compose.material.icons.outlined.PhoneAndroid
import androidx.compose.material.icons.outlined.Visibility
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import com.openminis.app.MinisApp
import com.openminis.app.R
import com.openminis.app.offload.ShizukuManager
import com.openminis.app.ui.settings.SettingsRow
import com.openminis.app.ui.settings.SettingsScaffold
import com.openminis.app.ui.settings.SettingsSection
import com.openminis.app.ui.settings.SettingsSwitchRow
import io.github.nanomuse.hands.Hands
import io.github.nanomuse.ui.home.MuseTones

const val ROUTE_HANDS = "nanomuse/hands"

/**
 * Settings → Hands. The switch (off by default), the three things the hands need — the
 * accessibility service, drawing over other apps, a model that sees pictures — each with
 * the button that fixes it, the screen model (a row that opens the picker of Settings →
 * Models), and the plain words on what the hands will and will not do.
 */
@Composable
fun HandsScreen(
    onBack: () -> Unit,
    onOpenProviders: () -> Unit,
    onOpenShizuku: () -> Unit,
    onOpenHandsModel: () -> Unit = onOpenProviders,
) {
    val context = LocalContext.current
    val repo = (context.applicationContext as? MinisApp)?.providerRepositoryOrNull
    val config = repo?.config?.collectAsState()?.value
    // Follows the preference itself, so a change made elsewhere while this page is open shows here.
    val enabled by remember(context) { Hands.enabledFlow(context) }.collectAsState(initial = Hands.enabled(context))
    var tick by remember { mutableIntStateOf(0) }
    val active by Hands.active.collectAsState()
    val shizuku by ShizukuManager.snapshot.collectAsState()

    // Permissions are granted in other apps; re-read when the user comes back.
    val owner = LocalLifecycleOwner.current
    DisposableEffect(owner) {
        val obs = LifecycleEventObserver { _, e -> if (e == Lifecycle.Event.ON_RESUME) tick++ }
        owner.lifecycle.addObserver(obs)
        onDispose { owner.lifecycle.removeObserver(obs) }
    }
    val readiness = remember(tick, config, shizuku) { Hands.readiness(context) }
    val visionEntries = remember(config) { Hands.visionEntries(context) }

    SettingsScaffold(title = stringResource(R.string.nm_hands_title), onBack = onBack) {
        Text(
            text = stringResource(R.string.nm_hands_intro),
            fontSize = 14.sp,
            lineHeight = 20.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 16.dp).padding(top = 12.dp),
        )

        SettingsSection(footer = stringResource(R.string.nm_hands_switch_footer)) {
            SettingsSwitchRow(
                title = stringResource(R.string.nm_hands_switch),
                subtitle = when {
                    active -> stringResource(R.string.nm_hands_status_working)
                    enabled && readiness.ready -> stringResource(R.string.nm_hands_status_ready)
                    enabled -> stringResource(R.string.nm_hands_status_missing)
                    else -> stringResource(R.string.nm_hands_status_off)
                },
                checked = enabled,
                onCheckedChange = { Hands.setEnabled(context, it) },
                icon = Icons.Outlined.PhoneAndroid,
                iconColor = if (enabled) MuseTones.action else MaterialTheme.colorScheme.onSurfaceVariant,
            )
            val supportsBackground = readiness.backgroundAndroidOk && readiness.secondaryDisplays
            SettingsSwitchRow(
                title = stringResource(R.string.nm_hands_background_screen),
                subtitle = stringResource(
                    if (supportsBackground) R.string.nm_hands_background_detail else R.string.nm_hands_background_unsupported,
                ),
                checked = readiness.backgroundScreen,
                enabled = !active && (supportsBackground || readiness.backgroundScreen),
                onCheckedChange = {
                    Hands.setBackgroundScreen(context, it)
                    tick++
                },
                icon = Icons.Outlined.Layers,
                showDivider = active,
            )
            if (active) {
                SettingsRow(
                    title = stringResource(R.string.nm_hands_stop_run),
                    onClick = { Hands.stopCurrent() },
                    showChevron = false,
                    showDivider = false,
                    titleColor = MaterialTheme.colorScheme.error,
                )
            }
        }

        // ── what it needs ──
        // C11: with no provider that has a model that sees, the footer is the one sentence that says which would
        SettingsSection(
            header = stringResource(R.string.nm_hands_section_needs),
            footer = when {
                visionEntries.isEmpty() -> stringResource(R.string.nm_cap_hands_unavailable)
                readiness.backgroundScreen -> null
                else -> stringResource(R.string.nm_hands_needs_footer)
            },
        ) {
            if (readiness.backgroundScreen) {
                NeedRow(
                    icon = Icons.Outlined.Layers,
                    title = stringResource(R.string.shizuku_title) + " ${Hands.BACKGROUND_MIN_SHIZUKU}+",
                    ok = readiness.shizukuReady,
                    okText = stringResource(R.string.nm_hands_need_granted),
                    fixText = when (shizuku.state) {
                        ShizukuManager.State.NOT_INSTALLED -> stringResource(R.string.shizuku_state_not_installed)
                        ShizukuManager.State.NOT_RUNNING -> stringResource(R.string.shizuku_state_not_running)
                        ShizukuManager.State.NEED_PERMISSION -> stringResource(R.string.shizuku_state_need_permission)
                        ShizukuManager.State.READY -> stringResource(R.string.check_update_available_subtitle, shizuku.version.toString(), "${Hands.BACKGROUND_MIN_SHIZUKU}+")
                    },
                    onFix = onOpenShizuku,
                )
            }
            NeedRow(
                icon = Icons.Outlined.Accessibility,
                title = stringResource(R.string.nm_hands_need_a11y),
                ok = readiness.serviceOn,
                okText = stringResource(R.string.nm_hands_need_on),
                fixText = stringResource(R.string.nm_hands_need_a11y_fix),
                onFix = { openAccessibilitySettings(context) },
            )
            NeedRow(
                icon = Icons.Outlined.Layers,
                title = stringResource(R.string.nm_hands_need_overlay),
                ok = readiness.overlayOk,
                okText = stringResource(R.string.nm_hands_need_granted),
                fixText = stringResource(R.string.nm_hands_need_overlay_fix),
                onFix = { openOverlaySettings(context) },
            )
            NeedRow(
                icon = Icons.Outlined.Visibility,
                title = stringResource(R.string.nm_hands_need_model),
                ok = readiness.model != null,
                // the model and how it was arrived at, so "why qwen-vl-max?" has its answer here
                okText = readiness.model?.let { m -> m.label + " · " + stringResource(whyText(m.why)) } ?: "",
                fixText = stringResource(R.string.nm_hands_need_model_fix),
                onFix = onOpenProviders,
                showDivider = !readiness.androidOk,
            )
            if (!readiness.androidOk) {
                SettingsRow(
                    title = stringResource(R.string.nm_hands_need_android),
                    subtitle = stringResource(R.string.nm_hands_need_android_sub),
                    showDivider = false,
                )
            }
        }

        // ── the screen model ── one row; the choice itself is the picker of Settings → Models
        // (0.1.41), so the hands' model has one place, not two.
        if (visionEntries.isNotEmpty()) {
            SettingsSection(header = stringResource(R.string.nm_hands_section_model), footer = stringResource(R.string.nm_hands_model_footer)) {
                SettingsRow(
                    title = stringResource(R.string.nm_models_hands_title),
                    subtitle = readiness.model?.let { m -> m.label + " · " + stringResource(whyText(m.why)) },
                    onClick = onOpenHandsModel,
                    showDivider = false,
                )
            }
        }

        // ── the rules ──
        SettingsSection(header = stringResource(R.string.nm_hands_section_rules)) {
            RuleRow(stringResource(R.string.nm_hands_rule_ladder))
            if (!readiness.backgroundScreen) RuleRow(stringResource(R.string.nm_hands_rule_secrets))
            RuleRow(stringResource(R.string.nm_hands_rule_approvals))
            RuleRow(stringResource(R.string.nm_hands_rule_stop))
            RuleRow(stringResource(R.string.nm_hands_rule_screenshots), last = true)
        }
        Spacer(Modifier.height(32.dp))
    }
}

@Composable
private fun NeedRow(
    icon: ImageVector,
    title: String,
    ok: Boolean,
    okText: String,
    fixText: String,
    onFix: () -> Unit,
    showDivider: Boolean = true,
) {
    SettingsRow(
        title = title,
        subtitle = if (ok) okText else fixText,
        icon = icon,
        iconColor = if (ok) MuseTones.action else MaterialTheme.colorScheme.onSurfaceVariant,
        onClick = if (ok) null else onFix,
        showChevron = false,
        showDivider = showDivider,
        minHeight = 64.dp,
        trailing = {
            Text(
                text = stringResource(if (ok) R.string.nm_hands_need_ok else R.string.nm_hands_need_set_up),
                fontSize = 14.sp,
                fontWeight = FontWeight.Medium,
                color = if (ok) MaterialTheme.colorScheme.onSurfaceVariant else MuseTones.action,
            )
        },
    )
}

@Composable
private fun RuleRow(text: String, last: Boolean = false) {
    SettingsRow(title = text, showDivider = !last, minHeight = 48.dp)
}

private fun openAccessibilitySettings(context: Context) {
    try {
        context.startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    } catch (_: Throwable) {
        runCatching { context.startActivity(Intent(Settings.ACTION_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
    }
}

/** The sentence for how the screen model was arrived at ([Hands.screenModel]). */
private fun whyText(why: Hands.Why): Int = when (why) {
    Hands.Why.CHOSEN -> R.string.nm_hands_why_chosen
    Hands.Why.CHAT_PROVIDER -> R.string.nm_hands_why_chat_provider
    Hands.Why.DEFAULT -> R.string.nm_hands_why_default
    Hands.Why.CHAT -> R.string.nm_hands_why_chat
    Hands.Why.GROUP -> R.string.nm_hands_why_group
    Hands.Why.MENU -> R.string.nm_hands_why_menu
    Hands.Why.VISION_GROUP -> R.string.nm_hands_why_vision_group
    Hands.Why.ANY -> R.string.nm_hands_why_any
}

private fun openOverlaySettings(context: Context) {
    try {
        context.startActivity(
            Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:${context.packageName}")).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
        )
    } catch (_: Throwable) {
        runCatching { context.startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
    }
}
