package io.github.nanomuse.community

import android.content.Context
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.StarOutline
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.openminis.app.R
import com.openminis.app.ui.components.openExternalUrl
import io.github.nanomuse.ui.home.MuseTones
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * The ask for a star, at the moments it is fair to make it: the first sign-in, a few finished
 * tasks (never the naming conversation), a new face, the allowance running out, a week or a
 * month of use, a goal reached. Which moments ask, at which counts, how far apart and how many
 * times in all is the relay's [Nudges.Policy]; everything else — what was asked and when, the
 * task and day counters, whether the person went — is the ledger in this phone's prefs.
 * Each ask is a card where the moment is, never a dialog; tapping through to GitHub, or
 * "I already starred", ends them all.
 */
object StarPrompt {
    /** The repository the star goes to (the policy may point elsewhere; see [url]). */
    const val REPO_URL = "https://github.com/nano-muse/nanoMuse"

    private const val PREFS = "nm.star"
    private const val KEY_STARRED = "starred"
    private const val KEY_TASKS = "tasks"
    private const val KEY_ASKS = "asks"
    private const val KEY_LAST_ASK_AT = "last_ask_at"
    private const val KEY_DAYS = "days"
    private const val KEY_LAST_DAY = "last_day"
    private const val DAY_MS = 24L * 60 * 60 * 1000

    enum class Moment(internal val key: String) {
        /** The account page the first time it is seen signed in: the allowance was just claimed. */
        SIGNED_IN("signed_in"),
        /** The person's finished tasks reached one of the policy's counts (3, 10, 30 by default). */
        TASKS("tasks"),
        /** A face was just drawn in the studio — a moment of delight. */
        NEW_LOOK("new_look"),
        /** The free allowance is used up: a row among the ways on. */
        EXHAUSTED("exhausted"),
        /** The app was opened on its 7th / 30th distinct day. */
        DAYS_USED("days_used"),
        /** A goal was marked achieved. */
        GOAL_DONE("goal_done"),
    }

    /** One concrete ask: the moment, and for the counted ones the count it fires at. */
    data class Ask(val moment: Moment, val n: Int = 0) {
        /** The ledger key; counted moments are spent per count ("tasks_3", "days_used_7"). */
        val key: String get() = if (n > 0) "${moment.key}_$n" else moment.key
    }

    /** What this phone remembers about the asks — pure data so the gate can be tested. */
    data class Ledger(
        /** The person has been to GitHub from one of the asks. */
        val starred: Boolean = false,
        /** Asks shown so far (a "Not now" counts). */
        val asks: Int = 0,
        /** When the last ask was shown, epoch ms (0 = never). */
        val lastAskAt: Long = 0L,
        /** Keys of the asks already spent. */
        val shown: Set<String> = emptySet(),
    )

    /** The policy and the ledger, decided — no Android in here. */
    object Gate {
        /** The policy lets this ask happen at all (the moment is on; a counted one is at a listed count). */
        fun allowed(policy: Nudges.Policy, ask: Ask): Boolean {
            if (!policy.enabled) return false
            val m = policy.moments
            return when (ask.moment) {
                Moment.SIGNED_IN -> m.signedIn
                Moment.TASKS -> ask.n in m.tasks
                Moment.NEW_LOOK -> m.newLook
                Moment.EXHAUSTED -> m.exhausted
                Moment.DAYS_USED -> ask.n in m.daysUsed
                Moment.GOAL_DONE -> m.goalDone
            }
        }

        /** Worth asking now: allowed, not spent, under the lifetime cap, past the cooldown, and the person has not gone. */
        fun due(policy: Nudges.Policy, ledger: Ledger, ask: Ask, now: Long): Boolean {
            if (ledger.starred || !allowed(policy, ask)) return false
            if (ask.key in ledger.shown) return false
            if (ledger.asks >= policy.maxAsks) return false
            if (ledger.lastAskAt > 0 && now - ledger.lastAskAt < policy.cooldownDays * DAY_MS) return false
            return true
        }

        /** The ask a finished-task count makes due, if the policy lists that count. */
        fun taskAsk(policy: Nudges.Policy, n: Int): Ask? = Ask(Moment.TASKS, n).takeIf { n in policy.moments.tasks }

        /** The ask a distinct-day count makes due, if the policy lists that count. */
        fun dayAsk(policy: Nudges.Policy, days: Int): Ask? = Ask(Moment.DAYS_USED, days).takeIf { days in policy.moments.daysUsed }

        /**
         * A task, for the counter: a turn the person started (typed, dictated, tapped an idea or
         * goal card), after the first conversation was over. Turns while the agent is still being
         * named never count, nor do background runs (routines, the feed, goal checks, heartbeats).
         */
        fun countsAsTask(personStarted: Boolean, firstConversationOver: Boolean): Boolean =
            personStarted && firstConversationOver

        /** How the day counter moves: one more only when [today] differs from the last day seen. */
        fun nextDays(days: Int, lastDay: String?, today: String): Int = if (lastDay == today) days else days + 1
    }

    private fun prefs(context: Context) = context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    /** The relay's policy in force (the built-in default without one). */
    fun policy(context: Context): Nudges.Policy = Nudges.current(context)

    /** Where the star goes: the policy's URL (the repository by default). */
    fun url(context: Context): String = policy(context).url

    /** The ledger as the prefs hold it. */
    fun ledger(context: Context): Ledger {
        val p = prefs(context)
        val all = p.all
        val shown = all.entries.filter { (k, v) -> v == true && k != KEY_STARRED }.map { it.key }.toSet()
        // Phones from before the ledger: the asks they already saw count toward the cap.
        val asks = if (all.containsKey(KEY_ASKS)) p.getInt(KEY_ASKS, 0) else shown.size
        return Ledger(
            starred = p.getBoolean(KEY_STARRED, false),
            asks = asks,
            lastAskAt = p.getLong(KEY_LAST_ASK_AT, 0L),
            shown = shown,
        )
    }

    /** Still worth asking this now. */
    fun due(context: Context, ask: Ask): Boolean = Gate.due(policy(context), ledger(context), ask, System.currentTimeMillis())

    fun due(context: Context, moment: Moment): Boolean = due(context, Ask(moment))

    /** The person has been to GitHub from one of the asks. */
    fun starred(context: Context): Boolean = prefs(context).getBoolean(KEY_STARRED, false)

    private val shownThisRun = java.util.Collections.synchronizedSet(mutableSetOf<String>())

    /** The card was shown (or waved away): this ask is spent, the cooldown starts, the cap moves. */
    fun markShown(context: Context, ask: Ask) {
        val p = prefs(context)
        val asks = ledger(context).asks + 1
        p.edit().putBoolean(ask.key, true).putInt(KEY_ASKS, asks).putLong(KEY_LAST_ASK_AT, System.currentTimeMillis()).apply()
        shownThisRun += ask.key
    }

    /** Shown since the app started: a row that is part of a card stays while that card is around. */
    fun shownThisRun(ask: Ask): Boolean = ask.key in shownThisRun

    fun markShown(context: Context, moment: Moment) = markShown(context, Ask(moment))

    /**
     * The star is done: the person went to GitHub from any "Star on GitHub" or said "I already
     * starred". No ask comes back on this phone, whatever the cooldown and the asks left.
     */
    fun markStarred(context: Context) {
        prefs(context).edit().putBoolean(KEY_STARRED, true).apply()
        _pending.value = null
    }

    /** Off to GitHub, and no more asking anywhere. */
    fun open(context: Context) {
        markStarred(context)
        openExternalUrl(context, url(context))
    }

    // ── the counters ────────────────────────────────────────────────────────

    /** One more finished task the person started; returns the count so far on this phone. */
    fun countTask(context: Context): Int {
        val p = prefs(context)
        val n = p.getInt(KEY_TASKS, 0) + 1
        p.edit().putInt(KEY_TASKS, n).apply()
        return n
    }

    /** The ask a task count makes due right now, if any (not yet marked shown). */
    fun taskAsk(context: Context, n: Int): Ask? = Gate.taskAsk(policy(context), n)?.takeIf { due(context, it) }

    /**
     * The app came to the foreground: one more distinct calendar day, when it is one. An ask the
     * day count makes due is offered to whatever screen shows it (the main chat).
     */
    fun dayOpened(context: Context) {
        val p = prefs(context)
        val today = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(Date())
        val days = Gate.nextDays(p.getInt(KEY_DAYS, 0), p.getString(KEY_LAST_DAY, null), today)
        p.edit().putInt(KEY_DAYS, days).putString(KEY_LAST_DAY, today).apply()
        Gate.dayAsk(policy(context), days)?.let { offer(context, it) }
    }

    // ── asks that arrive away from the screen that shows them ───────────────

    private val _pending = MutableStateFlow<Ask?>(null)

    /** An ask that became due somewhere without a place to show it; the right screen takes it. */
    val pending: StateFlow<Ask?> = _pending.asStateFlow()

    /** Hold [ask] for its screen when it is due now; the screen re-checks and marks it on show. */
    fun offer(context: Context, ask: Ask) {
        if (due(context, ask)) _pending.value = ask
    }

    fun offer(context: Context, moment: Moment) = offer(context, Ask(moment))

    /** The pending ask was shown or is no longer wanted. */
    fun clearPending(ask: Ask? = null) {
        if (ask == null || _pending.value == ask) _pending.value = null
    }

    // ── copy ────────────────────────────────────────────────────────────────

    /**
     * The card's sentence for an ask: the one the operator set in the relay's console
     * ([Nudges.Policy.sentence] — `text_zh` first in Chinese, then `text`), else the app's own
     * line for the moment in the device language. The title and the buttons are always the app's.
     */
    fun text(context: Context, ask: Ask): String =
        policy(context).sentence(language(context)) ?: builtInText(context, ask)

    /** The UI language as the app's resources resolve it (the same reading as the ideas list). */
    private fun language(context: Context): String? =
        context.resources.configuration.locales[0]?.language ?: Locale.getDefault().language

    /** The app's own line for an ask, in the device language. */
    fun builtInText(context: Context, ask: Ask): String = when (ask.moment) {
        Moment.SIGNED_IN -> context.getString(R.string.nm_star_signed_in)
        Moment.TASKS -> context.resources.getQuantityString(R.plurals.nm_star_tasks, ask.n, ask.n)
        Moment.NEW_LOOK -> context.getString(R.string.nm_star_new_look)
        Moment.EXHAUSTED -> context.getString(R.string.nm_star_exhausted)
        Moment.DAYS_USED -> when (ask.n) {
            7 -> context.getString(R.string.nm_star_days_used_week)
            30 -> context.getString(R.string.nm_star_days_used_month)
            else -> context.resources.getQuantityString(R.plurals.nm_star_days_used, ask.n, ask.n)
        }
        Moment.GOAL_DONE -> context.getString(R.string.nm_star_goal_done)
    }
}

/** The amber of the star, the one colour the card adds. */
private val StarAmber = Color(0xFFF5A623)

/**
 * One card: the star, a line or two saying why, "Star on GitHub", "Not now" and "I already
 * starred". [text] is the line for the moment; [onDone] runs after any button so the caller can
 * drop the card.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun StarNudgeCard(
    text: String,
    modifier: Modifier = Modifier,
    onDone: () -> Unit,
) {
    val context = LocalContext.current
    Surface(
        shape = RoundedCornerShape(20.dp),
        color = MuseTones.surface,
        border = BorderStroke(1.dp, MuseTones.hairline),
        modifier = modifier.fillMaxWidth().widthIn(max = 400.dp),
    ) {
        Column(Modifier.padding(14.dp)) {
            Row(verticalAlignment = Alignment.Top) {
                Icon(Icons.Outlined.StarOutline, contentDescription = null, tint = StarAmber, modifier = Modifier.padding(top = 1.dp).size(20.dp))
                Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f)) {
                    Text(
                        text = stringResource(R.string.nm_star_title),
                        fontSize = 15.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                    Text(
                        text = text,
                        fontSize = 13.sp,
                        lineHeight = 18.sp,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(top = 3.dp),
                    )
                }
            }
            Spacer(Modifier.height(8.dp))
            // three actions do not always fit one line in every language
            FlowRow(verticalArrangement = Arrangement.Center, modifier = Modifier.padding(start = 30.dp)) {
                Button(
                    onClick = { StarPrompt.open(context); onDone() },
                    shape = CircleShape,
                    contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 14.dp, vertical = 6.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = MuseTones.action, contentColor = Color.White),
                ) { Text(stringResource(R.string.nm_star_action), fontSize = 13.sp, fontWeight = FontWeight.Medium) }
                Spacer(Modifier.width(6.dp))
                TextButton(onClick = onDone) {
                    Text(stringResource(R.string.nm_star_later), fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                TextButton(onClick = { StarPrompt.markStarred(context); onDone() }) {
                    Text(stringResource(R.string.nm_star_done), fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
    }
}
