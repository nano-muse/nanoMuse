package io.github.nanomuse.ui.feed

import android.Manifest
import android.content.Intent
import android.os.Build
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.selection.toggleable
import androidx.compose.material3.Checkbox
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.foundation.layout.Box
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.app.NotificationManagerCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import com.openminis.app.R
import io.github.nanomuse.goals.Goal
import io.github.nanomuse.goals.GoalDeadlines
import io.github.nanomuse.goals.GoalFollowUps
import io.github.nanomuse.goals.GoalStore
import io.github.nanomuse.guard.SessionAccess
import io.github.nanomuse.ui.home.MuseTones
import kotlinx.coroutines.delay
import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle

@Composable
internal fun currentGoalDeadline(): GoalDeadlines.Item? {
    val context = LocalContext.current
    val settings by GoalFollowUps.settings.collectAsState()
    if (!settings.cards) return null
    val goals by GoalStore.get(context).goals.collectAsState()
    val protected by SessionAccess.protected.collectAsState()
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val today by produceState(LocalDate.now(), lifecycle) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
            while (true) {
                value = LocalDate.now()
                delay(60_000)
            }
        }
    }
    return remember(goals, today, protected) { GoalDeadlines.ranked(goals, today, protected).firstOrNull() }
}

@Composable
internal fun GoalDeadlineCard(item: GoalDeadlines.Item, onOpenGoal: (Goal) -> Unit) {
    val context = LocalContext.current
    var menu by remember(item.key) { mutableStateOf(false) }
    FeedCard {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.Top) {
            Column(Modifier.weight(1f).clickable {
                GoalDeadlines.ranked(GoalStore.get(context).all(), LocalDate.now(), SessionAccess.protected.value)
                    .firstOrNull { it.key == item.key }?.let { onOpenGoal(it.goal) }
            }.padding(16.dp)) {
                val date = item.due.format(DateTimeFormatter.ofLocalizedDate(FormatStyle.MEDIUM))
                val label = when (item.days) {
                    0L -> stringResource(R.string.nm_deadline_today)
                    1L -> stringResource(R.string.nm_deadline_tomorrow)
                    else -> stringResource(R.string.nm_deadline_overdue, date)
                }
                Text(label, color = MuseTones.action, fontSize = 13.sp)
                Text(item.goal.title, fontWeight = FontWeight.SemiBold, fontSize = 17.sp, modifier = Modifier.padding(vertical = 4.dp))
                item.nextStep?.let { step ->
                    Row(Modifier.fillMaxWidth().toggleable(false, role = Role.Checkbox) {
                        GoalStore.get(context).update(item.goal.id) { goal ->
                            GoalDeadlines.completeStep(goal, item, LocalDate.now(), SessionAccess.protected.value)
                        }
                    }.padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(checked = false, onCheckedChange = null)
                        Text(step, modifier = Modifier.padding(start = 8.dp), style = MaterialTheme.typography.bodyMedium)
                    }
                }
            }
            Box {
                IconButton(onClick = { menu = true }) {
                    Icon(Icons.Filled.MoreVert, stringResource(R.string.nm_more))
                }
                DropdownMenu(menu, onDismissRequest = { menu = false }) {
                    DropdownMenuItem(text = { Text(stringResource(R.string.nm_deadline_snooze)) }, onClick = {
                        menu = false
                        GoalFollowUps.snooze(context, item)
                    })
                    DropdownMenuItem(text = { Text(stringResource(R.string.nm_deadline_hide)) }, onClick = {
                        menu = false
                        GoalFollowUps.dismiss(context, item)
                    })
                }
            }
        }
    }
}

@Composable
internal fun GoalDeadlineSettings() {
    val context = LocalContext.current
    val state by GoalFollowUps.settings.collectAsState()
    var permissionDenied by rememberSaveable { mutableStateOf(false) }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { allowed ->
        permissionDenied = !allowed
        if (allowed && GoalFollowUps.settings.value.cards) GoalFollowUps.configure(context, notify = true)
    }
    DeadlineSwitch(R.string.nm_deadline_cards, state.cards) { GoalFollowUps.configure(context, cards = it) }
    if (state.cards) {
        DeadlineSwitch(R.string.nm_deadline_alerts, state.notify) { checked ->
            when {
                !checked -> GoalFollowUps.configure(context, notify = false)
                NotificationManagerCompat.from(context).areNotificationsEnabled() -> GoalFollowUps.configure(context, notify = true)
                Build.VERSION.SDK_INT >= 33 && !permissionDenied -> permission.launch(Manifest.permission.POST_NOTIFICATIONS)
                else -> context.startActivity(Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName))
            }
        }
    }
}

@Composable
private fun DeadlineSwitch(label: Int, checked: Boolean, change: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().toggleable(checked, role = Role.Switch, onValueChange = change)
        .padding(horizontal = 14.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(stringResource(label), fontSize = 15.sp, modifier = Modifier.weight(1f))
        Switch(checked = checked, onCheckedChange = null)
    }
}
