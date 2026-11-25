package io.github.nanomuse.hands

import android.content.Context
import com.openminis.app.R
import java.util.concurrent.atomic.AtomicLong
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * The local, display-safe status of one screen run.
 *
 * It deliberately carries no model reasoning, typed value, screen text or target label. The
 * floating preview and the originating chat may show this state without exposing private input.
 */
internal object HandsRunProgress {
    enum class Phase(val terminal: Boolean = false) {
        STARTING,
        CONNECTING,
        OPENING_APP,
        LOOKING,
        ACTING,
        PAUSED,
        WAITING_USER,
        WAITING_APPROVAL,
        STOPPING,
        CLEANING,
        DONE(true),
        NEEDS_USER(true),
        BLOCKED(true),
        STOPPED(true),
        FAILED(true),
    }

    enum class Action {
        TAP,
        DOUBLE_TAP,
        HOLD,
        SWIPE,
        SCROLL_UP,
        SCROLL_DOWN,
        SCROLL_LEFT,
        SCROLL_RIGHT,
        TYPE,
        ENTER,
        OPEN_APP,
        BACK,
        HOME,
        WAIT,
        CHECK_RESULT,
        OTHER,
    }

    data class Snapshot(
        val owner: Long,
        val sessionId: String?,
        val runId: String,
        val background: Boolean,
        val appLabel: String?,
        val phase: Phase,
        val step: Int,
        val action: Action?,
    ) {
        val active: Boolean get() = !phase.terminal
    }

    @JvmInline
    value class Token internal constructor(internal val owner: Long)

    private val ids = AtomicLong(0)
    private val _state = MutableStateFlow<Snapshot?>(null)
    val state: StateFlow<Snapshot?> = _state.asStateFlow()

    @Synchronized
    fun begin(
        sessionId: String?,
        runId: String,
        background: Boolean,
        appLabel: String?,
    ): Token {
        val token = Token(ids.incrementAndGet())
        _state.value = Snapshot(
            owner = token.owner,
            sessionId = sessionId,
            runId = runId,
            background = background,
            appLabel = appLabel,
            phase = Phase.STARTING,
            step = 0,
            action = null,
        )
        return token
    }

    @Synchronized
    fun update(
        token: Token,
        phase: Phase,
        step: Int? = null,
        action: Action? = null,
        appLabel: String? = null,
    ): Boolean {
        val current = _state.value?.takeIf { it.owner == token.owner } ?: return false
        if (current.phase.terminal) return false
        _state.value = current.copy(
            phase = phase,
            step = step ?: current.step,
            action = action,
            appLabel = appLabel ?: current.appLabel,
        )
        return true
    }

    @Synchronized
    fun finish(token: Token, phase: Phase, step: Int): Boolean {
        require(phase.terminal)
        val current = _state.value?.takeIf { it.owner == token.owner } ?: return false
        _state.value = current.copy(phase = phase, step = step, action = null)
        return true
    }

    @Synchronized
    fun clear(token: Token) {
        if (_state.value?.owner == token.owner) _state.value = null
    }

    /** Localized, bounded text for the chat tool pill. */
    fun describe(context: Context, state: Snapshot): String {
        val detail = when (state.phase) {
            Phase.STARTING, Phase.CLEANING -> context.getString(R.string.nm_hands_status_working)
            Phase.CONNECTING -> context.getString(R.string.nm_hands_wireless_step_connect)
            Phase.OPENING_APP -> state.appLabel?.let {
                context.getString(R.string.nm_hands_fx_open, it)
            } ?: context.getString(R.string.nm_hands_status_working)
            Phase.LOOKING -> context.getString(R.string.nm_hands_looking)
            Phase.ACTING -> actionText(context, state.action, state.appLabel)
            Phase.PAUSED -> context.getString(R.string.nm_goal_status_paused)
            Phase.WAITING_USER, Phase.NEEDS_USER -> context.getString(R.string.nm_hands_your_turn)
            Phase.WAITING_APPROVAL -> context.getString(R.string.nm_hands_approval_title)
            Phase.STOPPING, Phase.STOPPED -> context.getString(R.string.nm_hands_stop)
            Phase.DONE -> context.getString(R.string.nm_hands_wireless_done)
            Phase.BLOCKED, Phase.FAILED -> context.getString(R.string.nm_hands_background_protected)
        }
        return if (state.step > 0 && state.phase !in setOf(
                Phase.CONNECTING,
                Phase.OPENING_APP,
                Phase.CLEANING,
                Phase.DONE,
                Phase.NEEDS_USER,
                Phase.BLOCKED,
                Phase.STOPPED,
                Phase.FAILED,
            )
        ) {
            "${context.getString(R.string.nm_hands_step, state.step)} · $detail"
        } else {
            detail
        }
    }

    private fun actionText(context: Context, action: Action?, appLabel: String?): String = when (action) {
        Action.TAP -> context.getString(R.string.nm_hands_fx_tap)
        Action.DOUBLE_TAP -> context.getString(R.string.nm_hands_fx_double_tap)
        Action.HOLD -> context.getString(R.string.nm_hands_fx_hold)
        Action.SWIPE -> context.getString(R.string.nm_hands_fx_swipe)
        Action.SCROLL_UP -> context.getString(R.string.nm_hands_fx_scroll_up)
        Action.SCROLL_DOWN -> context.getString(R.string.nm_hands_fx_scroll_down)
        Action.SCROLL_LEFT -> context.getString(R.string.nm_hands_fx_scroll_left)
        Action.SCROLL_RIGHT -> context.getString(R.string.nm_hands_fx_scroll_right)
        Action.TYPE -> context.getString(R.string.nm_hands_replay_type)
        Action.ENTER -> context.getString(R.string.nm_hands_fx_enter)
        Action.OPEN_APP -> appLabel?.let { context.getString(R.string.nm_hands_fx_open, it) }
            ?: context.getString(R.string.nm_hands_status_working)
        Action.BACK -> context.getString(R.string.nm_hands_fx_back)
        Action.HOME -> context.getString(R.string.nm_hands_fx_home)
        Action.WAIT, Action.CHECK_RESULT, Action.OTHER, null ->
            context.getString(R.string.nm_hands_looking)
    }
}
