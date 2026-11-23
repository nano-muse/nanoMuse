package io.github.nanomuse.feed

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
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.ProcessLifecycleOwner
import androidx.room.withTransaction
import com.openminis.app.MinisApp
import com.openminis.app.R
import com.openminis.app.data.db.MessageEntity
import com.openminis.app.data.repository.ChatRepository
import com.openminis.app.logging.AppLogger
import com.openminis.app.service.SessionActivityTracker
import com.openminis.app.service.SessionBadgeStore
import io.github.nanomuse.account.AccountData
import io.github.nanomuse.deeplink.OwnScheme
import io.github.nanomuse.guard.AppAccess
import io.github.nanomuse.sync.ConversationSync
import io.github.nanomuse.sync.Transcript
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import java.time.Duration
import java.time.Instant
import java.time.LocalTime
import java.time.ZonedDateTime

/** A check-in lives in the conversation in which the person made the commitment. */
internal object ChatCheckIns {
    private const val ENABLED = "feed.chat.checkins"
    private const val LAST_DAY = "feed.chat.checkin_day"
    private const val CODE = 0x6E6D_4349
    private const val CHANNEL = "nanomuse_chat_checkins"
    private const val ACTION = "io.github.nanomuse.CHAT_CHECKIN"
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("nanomuse", Context.MODE_PRIVATE)
    fun enabled(ctx: Context) = FeedChatEvidence.enabled(ctx) && prefs(ctx).getBoolean(ENABLED, false)

    fun configure(ctx: Context, on: Boolean) {
        prefs(ctx).edit().putBoolean(ENABLED, on && FeedChatEvidence.enabled(ctx)).apply()
        if (enabled(ctx)) schedule(ctx) else cancel(ctx)
    }

    private fun pending(ctx: Context) = PendingIntent.getBroadcast(ctx, CODE,
        Intent(ctx, Receiver::class.java).setAction(ACTION), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)

    fun cancel(ctx: Context) {
        ctx.getSystemService(AlarmManager::class.java).cancel(pending(ctx))
        ctx.getSystemService(NotificationManager::class.java).cancel(CODE)
    }

    /** Android can batch this wakeup. No exact-alarm permission or persistent service is needed. */
    fun schedule(ctx: Context, earliest: ZonedDateTime = ZonedDateTime.now().plusSeconds(2)) {
        if (!enabled(ctx)) return
        val whenDue = nextWindow(earliest, prefs(ctx).getString(LAST_DAY, null))
        ctx.getSystemService(AlarmManager::class.java).setAndAllowWhileIdle(
            AlarmManager.RTC_WAKEUP, whenDue.toInstant().toEpochMilli(), pending(ctx))
    }

    internal fun nextWindow(at: ZonedDateTime, deliveredDay: String?): ZonedDateTime {
        val morning = at.toLocalDate().atTime(9, 0).atZone(at.zone)
        return when {
            deliveredDay == at.toLocalDate().toString() || at.hour >= 20 -> morning.plusDays(1)
            at < morning -> morning
            else -> at
        }
    }

    internal fun due(facts: List<FeedPreparation.Fact>, now: ZonedDateTime) = facts.filter {
        it.kind == FeedPreparation.Kind.CHAT && it.chatSession.isNotEmpty() && it.dueOn == now.toLocalDate().toString()
    }.sortedWith(compareBy({ it.writtenAt }, { it.id }))

    internal fun ready(fact: FeedPreparation.Fact, now: ZonedDateTime): Boolean =
        now.hour in 9..19 && Duration.between(Instant.ofEpochMilli(fact.writtenAt), now.toInstant()) >= Duration.ofHours(1)

    fun isMessage(id: String) = id.startsWith("nm-checkin-")

    internal fun prefix(owner: String, now: ZonedDateTime) = "nm-checkin-" +
        FeedPreparation.hash(owner, now.toLocalDate().toString()) + "-"

    private suspend fun check(app: MinisApp): ZonedDateTime {
        val now = ZonedDateTime.now()
        val tomorrow = now.toLocalDate().plusDays(1).atTime(LocalTime.of(9, 0)).atZone(now.zone)
        val retry = now.plusHours(1)
        val p = prefs(app)
        val next = nextWindow(now, p.getString(LAST_DAY, null))
        if (!enabled(app) || next != now) return next
        if (!app.subsystemsReady() || AppAccess.locked.value) return retry

        // Account sign-in/out uses this same mutex while moving chats and their preferences.
        return ConversationSync.withStableChats {
            val owner = AccountData.key(app)
            val consent = FeedChatEvidence.scope(app, "", true) ?: return@withStableChats retry
            fun current() = enabled(app) && FeedChatEvidence.scope(app, "", true) == consent &&
                AccountData.key(app) == owner && ZonedDateTime.now().let { it.toLocalDate() == now.toLocalDate() && it.hour in 9..19 }
            if (!current()) return@withStableChats retry
            var session: String? = null
            val outcome = app.database.withTransaction {
                val dayId = prefix(owner, now)
                // The same transaction checks for an earlier delivery, rereads live evidence and inserts.
                val delivered = app.database.openHelper.writableDatabase.query(
                    "SELECT 1 FROM messages WHERE id GLOB ? LIMIT 1", arrayOf<Any>("$dayId*")
                ).use { it.moveToFirst() }
                if (delivered || p.getString(LAST_DAY, null) == now.toLocalDate().toString()) return@withTransaction tomorrow
                val facts = due(FeedChatEvidence.facts(app, now.toLocalDate()), now)
                val fact = facts.firstOrNull { ready(it, now) && !SessionActivityTracker.isActive(it.chatSession) }
                    ?: return@withTransaction if (facts.isEmpty()) tomorrow else retry
                val target = fact.chatSession
                val body = app.getString(R.string.nm_chat_checkin_body, fact.text)
                val parts = Transcript.partsJson(body, emptyList())
                val dao = app.chatRepository.dao
                val row = MessageEntity(id = dayId + fact.id, sessionId = target, role = "assistant",
                    partsJson = parts, createdAt = now.toInstant().toEpochMilli(), sortOrder = dao.nextSortOrder(target))
                fun allowed() = current() && FeedChatEvidence.scope(app, target, true) == consent &&
                    !SessionActivityTracker.isActive(target)
                if (!allowed()) return@withTransaction retry
                dao.insertMessage(row)
                dao.updateLastMessage(target, ChatRepository.extractTextPreview(parts), row.createdAt)
                if (!allowed()) throw Withdrawn()
                session = target
                tomorrow
            }
            session?.let { target ->
                p.edit().putString(LAST_DAY, now.toLocalDate().toString()).commit()
                ConversationSync.localAssistantAppended(target)
                val viewing = withContext(Dispatchers.Main.immediate) {
                    ProcessLifecycleOwner.get().lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED) &&
                        target in SessionActivityTracker.presentSessions.value
                }
                if (!viewing && current() && FeedChatEvidence.scope(app, target, true) == consent) {
                    SessionBadgeStore.replies.received(target)
                    notify(app, target)
                }
            }
            outcome
        }
    }

    private class Withdrawn : IllegalStateException()

    private fun notify(ctx: Context, session: String) {
        val manager = ctx.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel(CHANNEL, ctx.getString(R.string.nm_chat_checkin_setting), NotificationManager.IMPORTANCE_DEFAULT))
        if (!NotificationManagerCompat.from(ctx).areNotificationsEnabled() || manager.getNotificationChannel(CHANNEL).importance == NotificationManager.IMPORTANCE_NONE) return
        val open = OwnScheme.intent(ctx, Uri.Builder().scheme("minis").authority("session").appendPath(session).build(), 0)
        val notice = NotificationCompat.Builder(ctx, CHANNEL).setSmallIcon(R.drawable.ic_stat_nanomuse)
            .setContentTitle(ctx.getString(R.string.app_name)).setContentText(ctx.getString(R.string.nm_reply_unread))
            .setContentIntent(PendingIntent.getActivity(ctx, CODE, open, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT))
            .setVisibility(NotificationCompat.VISIBILITY_SECRET).setOnlyAlertOnce(true).setAutoCancel(true).build()
        try { manager.notify(CODE, notice) } catch (_: SecurityException) { /* Chat delivery is independent of OS notifications. */ }
    }

    class Receiver : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            val app = context.applicationContext as? MinisApp ?: return
            if (intent.action != ACTION) { schedule(app); return }
            val broadcast = goAsync()
            scope.launch {
                try {
                    val next = withTimeout(7_000L) { check(app) }
                    schedule(app, next)
                } catch (e: Exception) {
                    if (e !is Withdrawn) AppLogger.warning("ChatCheckIns", "check deferred: ${e.javaClass.simpleName}")
                    schedule(app, ZonedDateTime.now().plusHours(1))
                } finally {
                    broadcast.finish()
                }
            }
        }
    }
}
