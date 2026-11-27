package io.github.nanomuse.feed

import android.content.ContentUris
import android.content.Context
import android.provider.CalendarContract.Events
import android.provider.CalendarContract.Instances
import android.text.format.DateUtils
import com.openminis.app.R
import com.openminis.app.offload.CalendarManager
import io.github.nanomuse.account.AccountData
import java.time.Duration
import java.util.UUID

/** Work with busy intervals only. Event titles, guests, notes and calendar account names stay in CalendarProvider. */
internal object CalendarChanges {
    private const val SWITCH = "feed.calendar.checkins"
    private const val SNAPSHOT = "feed.calendar.busy"
    private const val LIMIT = 128
    private val horizon = Duration.ofHours(48).toMillis()
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("nanomuse", Context.MODE_PRIVATE)

    data class Slot(val id: String, val start: Long, val end: Long, val repeats: Boolean = false)
    data class Snapshot(val at: Long, val slots: List<Slot>)
    data class Change(val first: Slot, val second: Slot, val moved: Boolean)
    data class Scan(val consent: String, val baseline: Snapshot, val change: Change?)

    fun enabled(ctx: Context) = scope(ctx) != null
    @Synchronized fun scope(ctx: Context): String? {
        val p = prefs(ctx)
        val token = p.getString(SWITCH, null) ?: return null
        if (!CalendarManager.hasPermission(ctx)) {
            p.edit().remove(SWITCH).remove(SNAPSHOT).apply()
            return null
        }
        return FeedPreparation.hash(AccountData.key(ctx), token)
    }

    @Synchronized fun configure(ctx: Context, on: Boolean) {
        val edit = prefs(ctx).edit().remove(SNAPSHOT)
        if (on && CalendarManager.hasPermission(ctx)) edit.putString(SWITCH, UUID.randomUUID().toString())
        else edit.remove(SWITCH)
        edit.apply()
        ChatCheckIns.reschedule(ctx)
    }

    fun needsBaseline(ctx: Context) = scope(ctx) != null && !prefs(ctx).contains(SNAPSHOT)

    private fun overlaps(a: Slot, b: Slot) = a.start < b.end && b.start < a.end
    private fun previous(slot: Slot, old: Snapshot) = old.slots.firstOrNull {
        it.id == slot.id && (!slot.repeats && !it.repeats || it.start == slot.start)
    }

    internal fun difference(old: Snapshot?, next: Snapshot): Change? {
        if (old == null || next.at < old.at || next.at - old.at >= horizon) return null
        // Events first encountered solely because the 48-hour window advanced are not new changes.
        val oldEnd = old.at + horizon
        val upcoming = next.slots.filter { it.end > next.at && it.start < oldEnd }.sortedBy { it.start }
        for ((index, a) in upcoming.withIndex()) {
            for (b in upcoming.drop(index + 1)) {
                if (b.start >= a.end) break
                if (a.id == b.id) continue
                val beforeA = previous(a, old)
                val beforeB = previous(b, old)
                if (beforeA == null || beforeB == null || !overlaps(beforeA, beforeB)) return Change(a, b, false)
            }
        }
        for (slot in upcoming) {
            val before = previous(slot, old) ?: continue
            if (!slot.repeats && before.start != slot.start) return Change(before, slot, true)
        }
        return null
    }

    private fun read(ctx: Context, at: Long): Snapshot? {
        val uri = Instances.CONTENT_URI.buildUpon().also {
            ContentUris.appendId(it, at)
            ContentUris.appendId(it, at + horizon)
        }.build()
        val projection = arrayOf(Instances.EVENT_ID, Events.CALENDAR_ID, Instances.BEGIN, Instances.END,
            Events.RRULE, Events.RDATE, Events.ORIGINAL_ID)
        val where = "${Instances.VISIBLE}=1 AND ${Events.ALL_DAY}=0 AND ${Events.AVAILABILITY}=? " +
            "AND (${Events.STATUS} IS NULL OR ${Events.STATUS}!=?) AND (${Events.SELF_ATTENDEE_STATUS} IS NULL OR ${Events.SELF_ATTENDEE_STATUS}!=?)"
        val args = arrayOf(Events.AVAILABILITY_BUSY.toString(), Events.STATUS_CANCELED.toString(),
            android.provider.CalendarContract.Attendees.ATTENDEE_STATUS_DECLINED.toString())
        return ctx.contentResolver.query(uri, projection, where, args, "${Instances.BEGIN} ASC")?.use { c ->
            val slots = mutableListOf<Slot>()
            while (c.moveToNext()) {
                if (slots.size >= LIMIT) return@use null // Never compare a partial calendar with a full snapshot.
                val start = c.getLong(2)
                val end = c.getLong(3)
                if (end <= start || end <= at || start >= at + horizon) continue
                slots += Slot(FeedPreparation.hash(c.getLong(1).toString(), c.getLong(0).toString()), start, end,
                    !c.getString(4).isNullOrBlank() || !c.getString(5).isNullOrBlank() || !c.isNull(6))
            }
            Snapshot(at, slots)
        }
    }

    private fun unpack(raw: String?, consent: String): Snapshot? {
        if (raw == null) return null
        return runCatching {
            val lines = raw.lines()
            if (lines.first() != consent || lines.size > LIMIT + 2) return null
            Snapshot(lines[1].toLong(), lines.drop(2).map { line ->
                val (id, start, end, repeat) = line.split(' ')
                Slot(id, start.toLong(), end.toLong(), repeat == "1")
            })
        }.getOrNull()
    }

    fun scan(ctx: Context, consent: String, at: Long): Scan? {
        val previous = unpack(prefs(ctx).getString(SNAPSHOT, null), consent)
        val current = read(ctx, at) ?: return null
        return if (scope(ctx) == consent) Scan(consent, current, difference(previous, current)) else null
    }

    @Synchronized fun accept(ctx: Context, scan: Scan) {
        if (scope(ctx) != scan.consent) return
        val snapshot = buildString {
            append(scan.consent).append('\n').append(scan.baseline.at)
            for (slot in scan.baseline.slots) append("\n${slot.id} ${slot.start} ${slot.end} ${if (slot.repeats) 1 else 0}")
        }
        prefs(ctx).edit().putString(SNAPSHOT, snapshot).apply()
    }

    fun message(ctx: Context, change: Change): String {
        val flags = DateUtils.FORMAT_SHOW_DATE or DateUtils.FORMAT_SHOW_TIME or DateUtils.FORMAT_ABBREV_MONTH
        fun range(s: Slot) = DateUtils.formatDateRange(ctx, s.start, s.end, flags)
        return ctx.getString(if (change.moved) R.string.nm_calendar_moved else R.string.nm_calendar_overlap,
            range(change.first), range(change.second))
    }
}
