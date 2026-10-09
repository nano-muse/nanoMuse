package io.github.nanomuse.ui.header

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.PlatformTextStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.material3.Text
import com.openminis.app.R
import com.openminis.app.service.SessionActivityTracker
import com.openminis.app.ui.theme.ChatColors
import io.github.nanomuse.deeplink.OwnScheme
import io.github.nanomuse.ui.avatar.AgentMood

/**
 * The one line under the name in the chat header, Muse style: what the agent is doing right now
 * ("Starting browser", "Searching 12306…") or that it is waiting on you. Null when idle, and the
 * caller shows its usual provider · model rows instead — that is the one place nanoMuse differs
 * from Muse, which has a single model and nothing to pick.
 *
 * With the steps hidden from the chat (the default) this line is the whole account of the work,
 * so it never says just "thinking": the step under way while a tool runs, "Writing the reply"
 * while the words arrive, and between the two the request it is on (`request`, a short brief of
 * what the person asked), so the gap between steps reads as progress rather than silence.
 */
@Composable
fun rememberNanoMuseStatusLine(
    isStreaming: Boolean,
    mood: AgentMood,
    replying: Boolean = false,
    request: String? = null,
): String? {
    val toolTitle by SessionActivityTracker.currentToolTitle.collectAsState()
    val toolRunning by SessionActivityTracker.isToolRunning.collectAsState()
    // between two steps the last step's words stay up (the model is choosing the next one),
    // so the line reads as progress — the same names as the pills — rather than a generic verb
    val lastToolTitle by SessionActivityTracker.lastToolTitle.collectAsState()
    val pendingRisk by io.github.nanomuse.guard.RiskGate.pending.collectAsState()
    // The avatar flow's own statuses ("Generating options", "Finalizing avatar"), as on Muse.
    val avatarStage by io.github.nanomuse.avatar.AvatarFlow.stage.collectAsState()
    val avatarSlots by io.github.nanomuse.avatar.AvatarStudio.slots.collectAsState()
    val avatarStatus = when (avatarStage) {
        is io.github.nanomuse.avatar.AvatarFlow.Stage.Choosing ->
            if (avatarSlots.any { it is io.github.nanomuse.avatar.AvatarStudio.Slot.Loading }) stringResource(R.string.nm_avatar_status_options) else null
        is io.github.nanomuse.avatar.AvatarFlow.Stage.Finalizing -> stringResource(R.string.nm_avatar_status_finalizing)
        io.github.nanomuse.avatar.AvatarFlow.Stage.Idle -> null
    }
    // The clips, after the poses: "Animating 2/4" until the video model is through.
    val motion by io.github.nanomuse.avatar.AvatarMotion.progress.collectAsState()
    val motionStatus = motion?.takeIf { it.running }?.let { stringResource(R.string.nm_avatar_status_animating, it.done + 1, it.total) }
    return when {
        mood == AgentMood.WAITING && pendingRisk != null -> stringResource(R.string.nm_risk_needs_approval)
        mood == AgentMood.WAITING -> stringResource(R.string.nm_status_waiting)
        avatarStatus != null -> avatarStatus
        isStreaming && toolRunning && !toolTitle.isNullOrBlank() -> toolTitle
        isStreaming && replying -> stringResource(R.string.nm_status_replying)
        isStreaming && !lastToolTitle.isNullOrBlank() -> lastToolTitle
        isStreaming && !request.isNullOrBlank() -> stringResource(R.string.nm_status_on, request)
        isStreaming -> stringResource(R.string.nm_status_working)
        motionStatus != null -> motionStatus
        else -> null
    }
}

/** How much of the request the status line quotes. */
private const val REQUEST_BRIEF_CHARS = 36

/**
 * The request in a breath, for the status line: its first line, whitespace folded, cut at a
 * word where it can be, with an ellipsis when something was left out. Null for nothing.
 */
fun requestBrief(text: String?): String? {
    val line = text?.lineSequence()?.map { it.trim() }?.firstOrNull { it.isNotEmpty() }
        ?.replace(Regex("\\s+"), " ") ?: return null
    if (line.length <= REQUEST_BRIEF_CHARS) return line
    val cut = line.take(REQUEST_BRIEF_CHARS)
    val atWord = cut.lastIndexOf(' ')
    return (if (atWord >= REQUEST_BRIEF_CHARS / 2) cut.substring(0, atWord) else cut).trimEnd() + "…"
}

/** Height of the two provider/model rows it replaces, so the app bar never jumps. */
private val STATUS_LINE_HEIGHT = 27.dp

@Composable
fun NanoMuseStatusLine(text: String, mood: AgentMood) {
    Box(
        modifier = Modifier.height(STATUS_LINE_HEIGHT).padding(horizontal = 4.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = text,
            fontSize = 12.sp,
            lineHeight = 14.sp,
            fontWeight = FontWeight.Medium,
            color = if (mood == AgentMood.WAITING) ChatColors.sendButton else ChatColors.secondaryText,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            style = TextStyle(platformStyle = PlatformTextStyle(includeFontPadding = false)),
        )
    }
}

/** Opens Settings → Soul, where the name, icon and style live. Tapping the face is the shortcut. */
fun openSoulSettings(context: Context) {
    runCatching { context.startActivity(OwnScheme.intent(context, Uri.parse("minis://settings/soul"), Intent.FLAG_ACTIVITY_SINGLE_TOP)) }
}

/** Opens the agent's profile page (today's activity, approvals, daily, soul & memory). Tapping the face is the shortcut, as in Muse. */
fun openAgentProfile(context: Context) {
    runCatching { context.startActivity(OwnScheme.intent(context, Uri.parse("minis://settings/profile"), Intent.FLAG_ACTIVITY_SINGLE_TOP)) }
}

/** Opens the avatar studio (the face, its moods, the image model) — the advanced entry behind the profile page. */
fun openAvatarStudio(context: Context) {
    runCatching { context.startActivity(OwnScheme.intent(context, Uri.parse("minis://settings/avatar"), Intent.FLAG_ACTIVITY_SINGLE_TOP)) }
}
