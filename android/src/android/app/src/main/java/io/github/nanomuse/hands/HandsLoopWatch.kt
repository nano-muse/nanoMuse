package io.github.nanomuse.hands

import kotlin.math.abs

/**
 * Notices when the hands go round in circles: the same action, again, on a screen that did
 * not change since the last one. The prompt's rule 5 asks the model to change tack after two
 * tries; this is the floor under it, the same one the runtime has (docs/gui.md): a line in the
 * history at the third identical step, a stop at the sixth — one model call with a screenshot
 * per step is what a loop costs, for up to thirty minutes without it.
 *
 * Pure Kotlin: fed the fingerprint of each screenshot ([print], a small grid of grey levels the
 * operator samples while it looks for a protected screen) and the action decided on it. Taps a
 * few pixels apart count as the same tap; a swipe or scroll the same way, text typed again, the
 * same key again likewise. Taking over, asking and finishing never count: they end or pause.
 */
class HandsLoopWatch(private val noteAt: Int = NOTE_AT, private val stopAt: Int = STOP_AT) {
    enum class Verdict { FINE, NOTE, STOP }

    private var lastPrint: IntArray? = null
    private var lastAction: HandsAction? = null

    /** Steps in a row, this one included, with the same action on an unchanged screen. */
    var streak: Int = 0
        private set

    /** [print] is the screen the model saw when it chose [action]; returns what to do about it. */
    fun step(print: IntArray, action: HandsAction): Verdict {
        val previous = lastAction
        val repeats = previous != null && sameAction(previous, action) &&
            lastPrint?.let { sameScreen(it, print) } == true
        streak = if (repeats) streak + 1 else 1
        lastPrint = print
        lastAction = action
        return when {
            !counts(action) -> { streak = 0; Verdict.FINE }
            streak >= stopAt -> Verdict.STOP
            streak >= noteAt -> Verdict.NOTE
            else -> Verdict.FINE
        }
    }

    companion object {
        /** The third identical step gets a line in the history. */
        const val NOTE_AT = 3

        /** The sixth stops the run. */
        const val STOP_AT = 6

        /** Grid units (of 1000) within which two taps are the same tap: about 3 % of the screen. */
        const val SAME_TAP = 30

        /** A cell counts as changed when its grey level moved by more than this (of 255). */
        const val CELL_DELTA = 24

        /** The screen counts as unchanged while at most this share of its cells changed (the clock, a cursor). */
        const val CHANGED_SHARE = 0.03

        /** What the model says to the next turn at the third identical step. */
        const val NOTE =
            "You have done the same thing three times and the screen has not changed. Do not repeat it: " +
                "try another element, scroll, go back, or finish with goal_status infeasible and say what you found."

        /** The reason the run ends with at the sixth. */
        fun stopReason(action: HandsAction): String =
            "the hands stopped: ${STOP_AT} steps in a row did the same thing (${action.describe()}) and the screen did not change"

        /** Whether a step of [action] can be part of a loop at all. */
        fun counts(action: HandsAction): Boolean = when (action) {
            is HandsAction.TakeOver, is HandsAction.AskUser, is HandsAction.Status -> false
            else -> true
        }

        /** The same action, as a person would judge it: the same tap give or take a few pixels, the same swipe, the same text. */
        fun sameAction(a: HandsAction, b: HandsAction): Boolean = when (a) {
            is HandsAction.Click -> b is HandsAction.Click && near(a.at, b.at)
            is HandsAction.DoubleTap -> b is HandsAction.DoubleTap && near(a.at, b.at)
            is HandsAction.LongPress -> b is HandsAction.LongPress && near(a.at, b.at)
            is HandsAction.Swipe -> b is HandsAction.Swipe && near(a.from, b.from) && near(a.to, b.to)
            is HandsAction.Scroll -> b is HandsAction.Scroll && a.direction == b.direction
            is HandsAction.InputText -> b is HandsAction.InputText && a.text == b.text
            is HandsAction.OpenApp -> b is HandsAction.OpenApp && a.appName.equals(b.appName, ignoreCase = true)
            is HandsAction.Wait -> b is HandsAction.Wait
            HandsAction.KeyboardEnter, HandsAction.Back, HandsAction.Home -> a === b
            is HandsAction.TakeOver, is HandsAction.AskUser, is HandsAction.Status -> false
        }

        private fun near(a: HandsAction.Point, b: HandsAction.Point): Boolean =
            abs(a.gx - b.gx) <= SAME_TAP && abs(a.gy - b.gy) <= SAME_TAP

        /** Two fingerprints of the same shape whose cells mostly agree. Different shapes (a rotation) are a change. */
        fun sameScreen(a: IntArray, b: IntArray): Boolean {
            if (a.size != b.size || a.isEmpty()) return false
            var changed = 0
            for (i in a.indices) if (abs(a[i] - b[i]) > CELL_DELTA) changed++
            return changed <= a.size * CHANGED_SHARE
        }
    }
}
