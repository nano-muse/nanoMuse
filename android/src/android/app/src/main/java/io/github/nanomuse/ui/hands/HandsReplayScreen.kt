package io.github.nanomuse.ui.hands

import android.graphics.Bitmap
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.openminis.app.MinisApp
import com.openminis.app.R
import com.openminis.app.ui.settings.SettingsRow
import com.openminis.app.ui.settings.SettingsScaffold
import io.github.nanomuse.guard.AppAccess
import io.github.nanomuse.guard.SessionAccess
import io.github.nanomuse.hands.Hands
import io.github.nanomuse.hands.HandsAction
import io.github.nanomuse.hands.HandsReplay
import io.github.nanomuse.hands.HandsReplayAccess
import io.github.nanomuse.hands.HandsReplayStore
import io.github.nanomuse.sync.ConversationSync
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle
import java.util.Locale
import kotlin.math.roundToInt

@Composable
internal fun HandsReplayScreen(onBack: () -> Unit) {
    val ctx = LocalContext.current
    val life = LocalLifecycleOwner.current.lifecycle
    var visible by remember(life) { mutableStateOf(life.currentState.isAtLeast(Lifecycle.State.STARTED)) }
    DisposableEffect(life) {
        val observer = LifecycleEventObserver { _, _ -> visible = life.currentState.isAtLeast(Lifecycle.State.STARTED) }
        life.addObserver(observer)
        onDispose { life.removeObserver(observer) }
    }
    val changes by HandsReplayAccess.changes.collectAsState()
    val appLocked by AppAccess.locked.collectAsState()
    val protected by SessionAccess.protected.collectAsState()
    val hidden by ConversationSync.hidden.collectAsState()
    val sessionRepo = (ctx.applicationContext as? MinisApp)?.chatRepositoryOrNull
    val scope = remember(changes, appLocked, visible) { if (visible && !appLocked) HandsReplayAccess.ticket(ctx) else null }
    val title = stringResource(R.string.nm_hands_replay_title)
    if (scope == null || sessionRepo == null) {
        BackHandler(onBack = onBack)
        SettingsScaffold(title = title, onBack = onBack) {}
        return
    }
    key(scope, protected, hidden) {
        val chats by remember(sessionRepo) {
            sessionRepo.observeSessions().map { rows -> rows.associate { it.id to it.title } }.distinctUntilChanged()
        }.collectAsState(initial = emptyMap())
        val active by Hands.active.collectAsState()
        val allowed = remember(chats, protected, hidden) { chats.filterKeys { it !in protected && it !in hidden } }
        val runs by produceState<List<HandsReplay.Run>?>(null, scope, allowed, active) {
            value = null
            value = HandsReplayStore.runs(ctx, scope, allowed)
        }
        var selection by remember { mutableStateOf<HandsReplay.Run?>(null) }
        val selected = selection?.takeIf { it.session in allowed && HandsReplayAccess.current(ctx, scope) }
        if (selected != null) {
            BackHandler { selection = null }
            key(selected) { RunPlayer(selected, scope) { selection = null } }
        } else {
            BackHandler(onBack = onBack)
            SettingsScaffold(title = title, onBack = onBack, scrollable = false) {
                val list = runs
                when {
                    list == null -> CircularProgressIndicator(Modifier.align(Alignment.CenterHorizontally).padding(20.dp))
                    list.isEmpty() -> Feedback(stringResource(R.string.nm_hands_replay_empty))
                    else -> LazyColumn {
                        items(list, key = { "${it.session}/${it.id}" }) { run ->
                            if (run.session in allowed) SettingsRow(
                                title = run.chat?.takeIf { it.isNotBlank() } ?: dateLabel(run),
                                subtitle = dateLabel(run).takeIf { !run.chat.isNullOrBlank() },
                                onClick = { if (HandsReplayAccess.current(ctx, scope)) selection = run },
                            )
                        }
                    }
                }
            }
        }
    }
}

private fun dateLabel(run: HandsReplay.Run): String = runCatching {
    val date = LocalDateTime.parse(run.id.take(15), DateTimeFormatter.ofPattern("uuuuMMdd-HHmmss", Locale.ROOT))
    date.format(DateTimeFormatter.ofLocalizedDateTime(FormatStyle.MEDIUM))
}.getOrDefault(run.id)

@Composable
private fun Feedback(text: String) {
    Text(text, Modifier.padding(20.dp), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
}

@Composable
private fun RunPlayer(run: HandsReplay.Run, ticket: HandsReplayAccess.Ticket, back: () -> Unit) {
    val ctx = LocalContext.current
    val active by Hands.active.collectAsState()
    var record by remember { mutableStateOf<HandsReplay.Record?>(null) }
    var loading by remember { mutableStateOf(true) }
    LaunchedEffect(run, ticket, active) {
        do {
            record = HandsReplayStore.record(ctx, ticket, run)
            loading = false
            if (active) delay(2000)
        } while (active && record?.outcome == null && HandsReplayAccess.current(ctx, ticket))
    }
    SettingsScaffold(title = dateLabel(run), onBack = back, scrollable = false) {
        val replay = record
        if (replay != null) {
            val status = when (replay.outcome) {
                "done" -> R.string.nm_tool_done
                "ask" -> R.string.nm_hands_your_turn
                "stopped" -> R.string.nm_coding_stopped
                "blocked", "max_steps", "failed" -> R.string.nm_hands_replay_unfinished
                else -> null
            }
            val mode = when (replay.mode) {
                "background" -> R.string.nm_hands_background_screen
                "foreground" -> R.string.nm_hands_replay_foreground
                else -> null
            }
            if (mode != null || status != null) {
                val text = listOfNotNull(mode?.let { stringResource(it) }, status?.let { stringResource(it) }).joinToString(" · ")
                Text(text, Modifier.padding(horizontal = 16.dp, vertical = 6.dp), style = MaterialTheme.typography.labelLarge)
            }
        }
        if (loading) { CircularProgressIndicator(Modifier.align(Alignment.CenterHorizontally).padding(20.dp)); return@SettingsScaffold }
        val frames = replay?.frames.orEmpty()
        if (frames.isEmpty()) { Feedback(stringResource(R.string.nm_hands_replay_no_steps)); return@SettingsScaffold }
        var selected by remember { mutableIntStateOf(0) }
        var playing by remember { mutableStateOf(false) }
        val index = selected.coerceIn(frames.indices)
        val frame = frames[index]
        var image by remember(frame) { mutableStateOf<Bitmap?>(null) }
        var fetching by remember(frame) { mutableStateOf(frame.screen) }
        LaunchedEffect(frame, ticket) {
            image = HandsReplayStore.screenshot(ctx, ticket, run, frame)
            fetching = false
        }
        LaunchedEffect(playing, index, fetching) {
            if (!playing || fetching) return@LaunchedEffect
            if (index == frames.lastIndex) { playing = false; return@LaunchedEffect }
            delay(1350)
            selected = index + 1
        }

        Box(Modifier.weight(1f).fillMaxWidth().padding(horizontal = 12.dp), contentAlignment = Alignment.Center) {
            val shot = image
            when {
                shot != null -> ReplayImage(shot, frame)
                fetching -> CircularProgressIndicator()
                else -> Feedback(stringResource(R.string.nm_hands_replay_no_image))
            }
        }
        Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)) {
            Text(stringResource(R.string.nm_hands_step, frame.number) + " · " + actionLabel(frame), style = MaterialTheme.typography.titleMedium)
            if (replay?.partial == true) Text(stringResource(R.string.nm_hands_replay_partial), style = MaterialTheme.typography.bodySmall)
            if (frames.size > 1) {
                Slider(value = index.toFloat(), onValueChange = { playing = false; selected = it.roundToInt() },
                    valueRange = 0f..frames.lastIndex.toFloat(), modifier = Modifier.fillMaxWidth())
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    TextButton(onClick = { playing = false; selected = index - 1 }, enabled = index > 0) {
                        Text(stringResource(R.string.nm_hands_replay_previous))
                    }
                    TextButton(onClick = {
                        if (!playing && index == frames.lastIndex) selected = 0
                        playing = !playing
                    }) { Text(stringResource(if (playing) R.string.nm_hands_replay_pause else R.string.quicktest_audio_play)) }
                    TextButton(onClick = { playing = false; selected = index + 1 }, enabled = index < frames.lastIndex) {
                        Text(stringResource(R.string.common_next))
                    }
                }
            }
        }
    }
}

@Composable
private fun ReplayImage(bitmap: Bitmap, frame: HandsReplay.Frame) {
    Image(bitmap.asImageBitmap(), stringResource(R.string.nm_hands_step, frame.number), Modifier.fillMaxSize(), contentScale = ContentScale.Fit)
    val start = frame.start ?: return
    val tint = MaterialTheme.colorScheme.primary
    Canvas(Modifier.fillMaxSize()) {
        val scale = minOf(size.width / bitmap.width, size.height / bitmap.height)
        val w = bitmap.width * scale
        val h = bitmap.height * scale
        fun location(point: HandsAction.Point) = Offset((size.width - w) / 2 + w * point.gx / HandsAction.GRID,
            (size.height - h) / 2 + h * point.gy / HandsAction.GRID)
        val at = location(start)
        frame.end?.let {
            val to = location(it)
            drawLine(Color.White, at, to, 6.dp.toPx())
            drawLine(tint, at, to, 3.dp.toPx())
            drawCircle(tint, 5.dp.toPx(), to)
        }
        drawCircle(Color.White, 12.dp.toPx(), at, style = Stroke(5.dp.toPx()))
        drawCircle(tint, 12.dp.toPx(), at, style = Stroke(3.dp.toPx()))
    }
}

@Composable
private fun actionLabel(frame: HandsReplay.Frame): String {
    val d = frame.detail
    return when (frame.action) {
        HandsReplay.Action.TAP -> if (d.isEmpty()) stringResource(R.string.nm_hands_fx_tap) else stringResource(R.string.nm_hands_fx_tap_target, d)
        HandsReplay.Action.DOUBLE -> if (d.isEmpty()) stringResource(R.string.nm_hands_fx_double_tap) else stringResource(R.string.nm_hands_fx_double_tap_target, d)
        HandsReplay.Action.HOLD -> if (d.isEmpty()) stringResource(R.string.nm_hands_fx_hold) else stringResource(R.string.nm_hands_fx_hold_target, d)
        HandsReplay.Action.SWIPE -> stringResource(R.string.nm_hands_fx_swipe)
        HandsReplay.Action.SCROLL -> stringResource(when (d) {
            "up" -> R.string.nm_hands_fx_scroll_up
            "left" -> R.string.nm_hands_fx_scroll_left
            "right" -> R.string.nm_hands_fx_scroll_right
            else -> R.string.nm_hands_fx_scroll_down
        })
        HandsReplay.Action.TYPE -> stringResource(R.string.nm_hands_replay_type)
        HandsReplay.Action.OPEN -> stringResource(R.string.nm_hands_fx_open, d)
        HandsReplay.Action.ENTER -> stringResource(R.string.nm_hands_fx_enter)
        HandsReplay.Action.BACK -> stringResource(R.string.nm_hands_fx_back)
        HandsReplay.Action.HOME -> stringResource(R.string.nm_hands_fx_home)
        HandsReplay.Action.WAIT -> stringResource(R.string.nm_hands_fx_wait, d.toIntOrNull() ?: 1)
        HandsReplay.Action.USER -> stringResource(R.string.nm_hands_your_turn)
        HandsReplay.Action.DONE -> stringResource(R.string.nm_tool_done)
        HandsReplay.Action.BLOCKED -> stringResource(R.string.nm_hands_replay_unfinished)
        HandsReplay.Action.OTHER -> stringResource(R.string.nm_hands_replay_observed)
    }
}
