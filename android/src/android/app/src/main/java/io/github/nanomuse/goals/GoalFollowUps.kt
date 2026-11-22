package io.github.nanomuse.goals

import android.app.AlarmManager
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.openminis.app.R
import com.openminis.app.scheduled.ScheduledTask
import com.openminis.app.scheduled.ScheduledTaskStore
import io.github.nanomuse.deeplink.OwnScheme
import io.github.nanomuse.guard.SessionAccess
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.LocalDate
import java.time.LocalTime
import java.time.ZonedDateTime

/** Deadlines are computed locally. Reading a card or receiving its optional notice never runs the goal. */
object GoalFollowUps {
    data class Settings(val cards: Boolean = true, val notify: Boolean = false)

    private const val CARDS = "feed.deadline_cards"
    private const val NOTIFY = "feed.deadline_notify"
    private const val DAY = "feed.deadline_last_day"
    private const val CHECKED = "feed.deadline_checked_day"
    private const val DELIVERED = "feed.deadline_delivered"
    private const val NOTIFICATION = 0x6E6D_4744
    private const val CHANNEL = "nanomuse_goal_deadlines"
    private const val ACTION = "io.github.nanomuse.GOAL_DEADLINE"
    private val morning = LocalTime.of(9, 0)
    private val evening = LocalTime.of(20, 0)
    private val state = MutableStateFlow(Settings())
    val settings = state.asStateFlow()
    private var observing = false
    private var active = false

    private fun prefs(context: Context) = context.getSharedPreferences("nanomuse", Context.MODE_PRIVATE)

    @Synchronized fun start(context: Context) {
        val app = context.applicationContext
        active = true
        val p = prefs(app)
        state.value = Settings(p.getBoolean(CARDS, true), p.getBoolean(NOTIFY, false))
        if (!observing) {
            observing = true
            CoroutineScope(Dispatchers.IO + SupervisorJob()).launch {
                combine(GoalStore.get(app).goals, SessionAccess.protected) { _, _ -> Unit }.collect {
                    synchronized(this@GoalFollowUps) { schedule(app) }
                }
            }
        }
        schedule(app)
    }

    /** Called before moving one account's goals and preferences off the live paths. */
    @Synchronized fun leave(context: Context) {
        active = false
        state.value = Settings(cards = false)
        cancel(context)
    }

    @Synchronized fun configure(context: Context, cards: Boolean = state.value.cards, notify: Boolean = state.value.notify) {
        if (!active) return
        val next = Settings(cards, cards && notify)
        prefs(context).edit().putBoolean(CARDS, next.cards).putBoolean(NOTIFY, next.notify).apply()
        state.value = next
        if (!next.notify) cancel(context) else schedule(context)
    }

    fun snooze(context: Context, item: GoalDeadlines.Item) = GoalStore.get(context).update(item.goal.id) {
        val today = LocalDate.now()
        if (GoalDeadlines.isCurrent(it, item, today, SessionAccess.protected.value)) it.copy(snoozedUntil = today.plusDays(1)) else it
    }

    fun dismiss(context: Context, item: GoalDeadlines.Item) = GoalStore.get(context).update(item.goal.id) {
        if (GoalDeadlines.isCurrent(it, item, LocalDate.now(), SessionAccess.protected.value)) it.copy(deadlineDismissed = true) else it
    }

    // Goal IDs are locally generated UUIDs and dates are canonical ISO strings. A string also
    // survives the existing account preferences stash, which does not serialize StringSet.
    private fun delivered(context: Context) = prefs(context).getString(DELIVERED, "").orEmpty()
        .lineSequence().filter { it.isNotEmpty() }.toSet()

    private fun alarm(context: Context) = PendingIntent.getBroadcast(
        context, NOTIFICATION, Intent(context, GoalDeadlineReceiver::class.java).setAction(ACTION),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
    )

    private fun cancel(context: Context) {
        context.getSystemService(AlarmManager::class.java).cancel(alarm(context))
        context.getSystemService(NotificationManager::class.java).cancel(NOTIFICATION)
    }

    @Synchronized fun schedule(context: Context, now: ZonedDateTime = ZonedDateTime.now()) {
        if (!active || !state.value.notify || !state.value.cards) return
        val alarms = context.getSystemService(AlarmManager::class.java)
        val pi = alarm(context)
        val today = now.toLocalDate()
        val checked = prefs(context).getString(CHECKED, null) == today.toString()
        val first = if (now.toLocalTime() >= evening || checked) today.plusDays(1) else today
        val date = GoalDeadlines.nextMorning(GoalStore.get(context).all(), first, SessionAccess.protected.value, delivered(context))
        if (date == null) {
            alarms.cancel(pi)
        } else {
            // A daily suggestion can wait for Android's power budget; no exact-alarm permission.
            val morningMs = date.atTime(morning).atZone(now.zone).toInstant().toEpochMilli()
            val earliestMs = now.toInstant().toEpochMilli() + 1_000L
            alarms.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, maxOf(morningMs, earliestMs), pi)
        }
    }

    @Synchronized fun onAlarm(context: Context) {
        if (!active || !state.value.notify || !state.value.cards) return
        val now = ZonedDateTime.now()
        val today = now.toLocalDate()
        try {
            val p = prefs(context)
            if (now.toLocalTime() < morning || now.toLocalTime() >= evening || p.getString(CHECKED, null) == today.toString()) return
            p.edit().putString(CHECKED, today.toString()).apply()
            if (p.getString(DAY, null) == today.toString()) return
            val all = GoalStore.get(context).all()
            val seen = delivered(context)
            val tasks = ScheduledTaskStore(context).all().associateBy { it.id }
            val item = GoalDeadlines.ranked(all, today, SessionAccess.protected.value).firstOrNull {
                it.key !in seen && !checksToday(tasks[it.goal.taskId], now)
            } ?: return
            val manager = context.getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(NotificationChannel(CHANNEL, context.getString(R.string.nm_deadline_alerts), NotificationManager.IMPORTANCE_DEFAULT))
            if (!NotificationManagerCompat.from(context).areNotificationsEnabled() ||
                manager.getNotificationChannel(CHANNEL).importance == NotificationManager.IMPORTANCE_NONE) return
            val intent = OwnScheme.intent(context, Uri.parse("minis://feed"), flags = 0)
            val open = PendingIntent.getActivity(context, NOTIFICATION, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
            val notice = NotificationCompat.Builder(context, CHANNEL)
                .setSmallIcon(R.drawable.ic_stat_nanomuse)
                .setContentTitle(context.getString(R.string.nm_deadline_alerts))
                .setContentText(context.getString(R.string.nm_deadline_notice))
                .setContentIntent(open).setAutoCancel(true).setOnlyAlertOnce(true)
                .setVisibility(NotificationCompat.VISIBILITY_SECRET)
                .setTimeoutAfter(java.time.Duration.between(now, today.atTime(evening).atZone(now.zone)).toMillis())
                .build()
            val validKeys = all.mapNotNull { goal -> goal.due?.let { "${goal.id}/$it" } }.toSet()
            // Reserve durably before posting so replay or process death cannot repeat an alert.
            if (p.edit().putString(DAY, today.toString()).putString(DELIVERED, (seen.intersect(validKeys) + item.key).joinToString("\n")).commit()) {
                try { manager.notify(NOTIFICATION, notice) } catch (_: SecurityException) { /* System permission was revoked. */ }
            }
        } finally {
            schedule(context, now)
        }
    }

    internal fun checksToday(task: ScheduledTask?, now: ZonedDateTime): Boolean {
        task ?: return false
        val day = now.toLocalDate()
        fun onDay(ms: Long) = Instant.ofEpochMilli(ms).atZone(now.zone).toLocalDate() == day
        if (task.lastFiredAt?.let(::onDay) == true) return true
        if (!task.enabled) return false
        val interval = task.intervalMinutes
        val at = if (interval != null && interval > 0) {
            val last = task.lastFiredAt
            if (last == null) task.createdAt + 60_000L else last + interval * 60_000L
        } else task.nextTriggerMs(day.atStartOfDay(now.zone).toInstant().toEpochMilli())
        return at?.let(::onDay) == true
    }

    class GoalDeadlineReceiver : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            if (intent.action == ACTION) onAlarm(context) else schedule(context)
        }
    }
}
