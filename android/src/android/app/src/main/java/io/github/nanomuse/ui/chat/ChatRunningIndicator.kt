package io.github.nanomuse.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import com.openminis.app.R
import com.openminis.app.service.SessionActivityTracker

/** An active turn is local process state, separate from completion and approval state. */
@Composable
fun ChatRunningIndicator(sessionId: String?, color: Color, modifier: Modifier = Modifier) {
    val activeSessions by SessionActivityTracker.activeSessions.collectAsState()
    if (sessionId == null || sessionId !in activeSessions) return
    RunningMark(color, modifier)
}

@Composable
private fun RunningMark(color: Color, modifier: Modifier = Modifier) {
    val label = stringResource(R.string.nm_chat_in_progress)
    CircularProgressIndicator(
        modifier = modifier.size(12.dp).semantics { contentDescription = label },
        color = color,
        strokeWidth = 1.5.dp,
    )
}

/** Layout previews, with sample unread dots; these do not mutate the app's session stores. */
@Composable
private fun RunningIndicatorPreview(dark: Boolean) {
    MaterialTheme(colorScheme = if (dark) darkColorScheme() else lightColorScheme()) {
        Column(
            Modifier.background(MaterialTheme.colorScheme.background).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            for ((title, active, unread) in listOf(
                Triple("Main chat", true, false),
                Triple("A long side-chat title that should leave room for its status", true, true),
                Triple("Completed reply", false, true),
                Triple("Idle chat", false, false),
            )) {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Text(title, Modifier.weight(1f), color = MaterialTheme.colorScheme.onBackground,
                        maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                        if (active) RunningMark(MaterialTheme.colorScheme.onSurfaceVariant)
                        if (unread) Box(Modifier.size(8.dp).background(MaterialTheme.colorScheme.error, CircleShape))
                    }
                }
            }
        }
    }
}

@Preview(name = "Chat activity, light", widthDp = 320)
@Composable
private fun ChatActivityLightPreview() = RunningIndicatorPreview(dark = false)

@Preview(name = "Chat activity, dark", widthDp = 320)
@Composable
private fun ChatActivityDarkPreview() = RunningIndicatorPreview(dark = true)
