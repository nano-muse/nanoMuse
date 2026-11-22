package io.github.nanomuse.ui.guard

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import com.openminis.app.R
import com.openminis.app.ui.settings.SettingsChoiceRow
import com.openminis.app.ui.settings.SettingsScaffold
import com.openminis.app.ui.settings.SettingsSection
import com.openminis.app.ui.settings.SettingsSwitchRow
import com.openminis.app.ui.settings.SettingsValueRow
import io.github.nanomuse.guard.AccessAuthentication
import io.github.nanomuse.guard.AccessLease
import io.github.nanomuse.guard.AppAccess
import io.github.nanomuse.guard.SessionAccess
import io.github.nanomuse.ui.home.MuseTones

const val ROUTE_LOCK_SETTINGS = "nanomuse_lock_settings"

private enum class LockScope { APP, CONVERSATION }

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LockSettingsScreen(onBack: () -> Unit) {
    val context = LocalContext.current
    val authenticate = rememberAccessAuthenticator()
    var appEnabled by remember { mutableStateOf(AppAccess.enabled) }
    var appTimeout by remember { mutableIntStateOf(AppAccess.timeout) }
    var chatTimeout by remember { mutableIntStateOf(SessionAccess.timeout) }
    var available by remember { mutableStateOf(AccessAuthentication.available(context)) }
    var confirming by remember { mutableStateOf(false) }
    var picker by rememberSaveable { mutableStateOf<LockScope?>(null) }
    val appTitle = stringResource(R.string.nm_access_settings)
    val appAfter = stringResource(R.string.nm_lock_app_after_background)
    val chatAfter = stringResource(R.string.nm_lock_chat_relock)
    val chatTitle = stringResource(R.string.nm_session_settings)

    fun refresh() {
        available = AccessAuthentication.available(context)
        appEnabled = AppAccess.enabled
        appTimeout = AppAccess.timeout
        chatTimeout = SessionAccess.timeout
    }
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) { refresh() }

    fun confirmChange(title: String, save: (Boolean) -> Unit) {
        if (confirming || !available) return
        confirming = true
        authenticate(title) { success ->
            save(success && AccessAuthentication.available(context))
            refresh()
            confirming = false
        }
    }

    SettingsScaffold(title = stringResource(R.string.nm_access_settings_title), onBack = onBack) {
        SettingsSection(
            footer = stringResource(if (available) R.string.nm_lock_app_hint else R.string.nm_access_unavailable),
        ) {
            SettingsSwitchRow(
                title = appTitle,
                checked = appEnabled,
                enabled = available && !confirming,
                onCheckedChange = { enabled ->
                    confirmChange(appTitle) { success -> AppAccess.configure(enabled, AppAccess.timeout, success) }
                },
                showDivider = appEnabled,
            )
            if (appEnabled) {
                SettingsValueRow(
                    title = appAfter,
                    value = lockTimeoutLabel(appTimeout, LockScope.APP),
                    onClick = if (available && !confirming) ({ picker = LockScope.APP }) else null,
                    showDivider = false,
                )
            }
        }
        SettingsSection(
            header = stringResource(R.string.nm_lock_chat_group),
            footer = stringResource(R.string.nm_lock_chat_hint, stringResource(R.string.nm_session_protect)),
        ) {
            SettingsValueRow(
                title = chatAfter,
                value = lockTimeoutLabel(chatTimeout, LockScope.CONVERSATION),
                onClick = if (available && !confirming) ({ picker = LockScope.CONVERSATION }) else null,
                showDivider = false,
            )
        }
    }

    picker?.let { scope ->
        val app = scope == LockScope.APP
        val selected = if (app) appTimeout else chatTimeout
        ModalBottomSheet(
            onDismissRequest = { picker = null },
            sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
            containerColor = MuseTones.surface,
        ) {
            Column(Modifier.verticalScroll(rememberScrollState()).selectableGroup()) {
                Text(
                    text = if (app) appAfter else chatTitle,
                    style = MaterialTheme.typography.titleMedium,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
                )
                for (seconds in AppAccess.TIMEOUTS) {
                    SettingsChoiceRow(
                        title = lockTimeoutLabel(seconds, scope),
                        selected = seconds == selected,
                        onSelect = {
                            picker = null
                            if (seconds != selected) {
                                confirmChange(if (app) appTitle else chatTitle) { success ->
                                    if (app) {
                                        AppAccess.configure(AppAccess.enabled, seconds, success)
                                    } else {
                                        SessionAccess.configureTimeout(seconds, success)
                                    }
                                }
                            }
                        },
                        showDivider = seconds != AppAccess.TIMEOUTS.last(),
                    )
                }
            }
        }
    }
}

@Composable
private fun lockTimeoutLabel(seconds: Int, scope: LockScope): String = when {
    seconds == -1 && scope == LockScope.CONVERSATION -> stringResource(R.string.nm_lock_chat_on_leave)
    seconds == -1 -> stringResource(R.string.nm_access_seconds, AccessLease.BACKGROUND_GRACE_SECONDS)
    seconds == 0 -> stringResource(R.string.nm_access_never)
    seconds == 3600 -> stringResource(R.string.nm_lock_one_hour)
    seconds >= 60 -> stringResource(R.string.nm_reach_minutes, seconds / 60)
    else -> stringResource(R.string.nm_access_seconds, seconds)
}
