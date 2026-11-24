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
import io.github.nanomuse.guard.SessionAccess
import io.github.nanomuse.home.MainChat
import io.github.nanomuse.sync.SyncDatabase
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

/** Local chat and calendar follow-ups share the same account, delivery budget and alarm. */
internal object ChatCheckIns {
    private const val LAST_DAY = "feed.chat.checkin_day"
    private const val CODE = 0x6E6D_4349
    private const val CHANNEL = "nanomuse_chat_checkins"
    private const val ACTION = "io.github.nanomuse.CHAT_CHECKIN"
    private val scope = CoroutineScope(Dispatchers.IO + SupervisorJob())
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("nanomuse", Context.MODE_PRIVATE)
    fun enabled(ctx: Context) = FeedChatEvidence.checkInsEnabled(ctx)

    fun configure(ctx: Context, on: Boolean) {
        FeedChatEvidence.setCheckIns(ctx, on)
        reschedule(ctx)
    }

    fun reschedule(ctx: Context) {
        if (enabled(ctx) || CalendarChanges.enabled(ctx)) schedule(ctx) else cancel(ctx)
    }

    private fun pending(ctx: Context) = PendingIntent.getBroadcast(ctx, CODE,
        Intent(ctx, Receiver::class.java).setAction(ACTION), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)

    fun cancel(ctx: Context) {
        ctx.getSystemService(AlarmManager::class.java).cancel(pending(ctx))
        ctx.getSystemService(NotificationManager::class.java).cancel(CODE)
    }

    /** Android can batch this wakeup. No exact-alarm permission or persistent service is needed. */
    fun schedule(ctx: Context, earliest: ZonedDateTime = ZonedDateTime.now().plusSeconds(2)) {
        if (!(enabled(ctx) && FeedChatEvidence.hasReferences(ctx)) && !CalendarChanges.enabled(ctx)) return
        val whenDue = if (CalendarChanges.needsBaseline(ctx)) earliest
            else nextWindow(earliest, prefs(ctx).getString(LAST_DAY, null))
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

    private data class Note(val session: String, val key: String, val body: String, val allowed: () -> Boolean)

    private suspend fun check(app: MinisApp): ZonedDateTime {
        val now = ZonedDateTime.now()
        val day = now.toLocalDate().toString()
        val tomorrow = now.toLocalDate().plusDays(1).atTime(LocalTime.of(9, 0)).atZone(now.zone)
        val retry = now.plusMinutes(30)
        val p = prefs(app)
        val window = nextWindow(now, p.getString(LAST_DAY, null))
        if (!app.subsystemsReady() || AppAccess.locked.value) return retry
        if (window != now && !CalendarChanges.needsBaseline(app)) return window

        return ConversationSync.withStableChats {
            val owner = AccountData.key(app)
            val consent = CalendarChanges.scope(app)
            val main = MainChat.persisted(app)
            fun mainAccessible() = main != null && main == MainChat.persisted(app) &&
                main !in ConversationSync.hidden.value && !SessionAccess.isProtected(main) &&
                !AppAccess.locked.value && AccountData.key(app) == owner
            val ownedMain = main != null && mainAccessible() &&
                SyncDatabase.get(app).dao().ownedCandidates(owner, listOf(main)).isNotEmpty()
            val scan = if (consent != null && ownedMain) CalendarChanges.scan(app, consent, now.toInstant().toEpochMilli()) else null
            if (scan != null && scan.change == null && mainAccessible()) CalendarChanges.accept(app, scan)
            if (window != now) return@withStableChats window

            var sent: Note? = null
            val next = app.database.withTransaction {
                val dayId = prefix(owner, now)
                val delivered = app.database.openHelper.writableDatabase.query(
                    "SELECT 1 FROM messages WHERE id GLOB ? LIMIT 1", arrayOf<Any>("$dayId*")
                ).use { it.moveToFirst() }
                if (delivered || p.getString(LAST_DAY, null) == day) return@withTransaction tomorrow
                val calNote = if (scan?.change != null && main != null && !SessionActivityTracker.isActive(main)) {
                    val session = app.chatRepository.getSession(main)
                    if (session != null && now.toInstant().toEpochMilli() - session.updatedAt >= Duration.ofMinutes(15).toMillis()) {
                        Note(main, "calendar", CalendarChanges.message(app, scan.change)) {
                            mainAccessible() && CalendarChanges.scope(app) == consent
                        }
                    } else null
                } else null
                val chatFacts = if (calNote == null && enabled(app)) due(FeedChatEvidence.facts(app, now.toLocalDate(), forCheckIn = true), now) else emptyList()
                val note = calNote ?: commitment(app, now, chatFacts) ?: return@withTransaction if (
                    consent != null || chatFacts.isNotEmpty()) retry else tomorrow
                fun allowed() = note.allowed() && AccountData.key(app) == owner &&
                    !SessionActivityTracker.isActive(note.session) && !AppAccess.locked.value &&
                    ZonedDateTime.now().let { it.toLocalDate() == now.toLocalDate() && it.hour in 9..19 }
                if (!allowed()) return@withTransaction retry
                val dao = app.chatRepository.dao
                val parts = Transcript.partsJson(note.body, emptyList())
                val row = MessageEntity(id = dayId + note.key, sessionId = note.session, role = "assistant",
                    partsJson = parts, createdAt = now.toInstant().toEpochMilli(), sortOrder = dao.nextSortOrder(note.session))
                dao.insertMessage(row)
                dao.updateLastMessage(note.session, ChatRepository.extractTextPreview(parts), row.createdAt)
                if (!allowed()) throw Withdrawn()
                sent = note
                tomorrow
            }
            sent?.let { note ->
                if (note.key == "calendar" && scan != null && note.allowed()) CalendarChanges.accept(app, scan)
                p.edit().putString(LAST_DAY, day).commit()
                ConversationSync.localAssistantAppended(note.session)
                val viewing = withContext(Dispatchers.Main.immediate) {
                    ProcessLifecycleOwner.get().lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED) &&
                        note.session in SessionActivityTracker.presentSessions.value
                }
                if (!viewing && note.allowed() && AccountData.key(app) == owner && !AppAccess.locked.value) {
                    SessionBadgeStore.replies.received(note.session)
                    notify(app, note.session)
                }
            }
            next
        }
    }

    private fun commitment(app: MinisApp, now: ZonedDateTime, facts: List<FeedPreparation.Fact>): Note? {
        if (!enabled(app)) return null
        val consent = FeedChatEvidence.scope(app, "", true) ?: return null
        val fact = facts.firstOrNull {
            ready(it, now) && !SessionActivityTracker.isActive(it.chatSession)
        } ?: return null
        return Note(fact.chatSession, fact.id, app.getString(R.string.nm_chat_checkin_body, fact.text)) {
            enabled(app) && FeedChatEvidence.scope(app, fact.chatSession, true) == consent
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
