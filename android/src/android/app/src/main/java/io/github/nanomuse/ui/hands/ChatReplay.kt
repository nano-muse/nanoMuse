package io.github.nanomuse.ui.hands

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.History
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.compose.ui.window.SecureFlagPolicy
import com.openminis.app.R
import io.github.nanomuse.feed.FeedFlow
import io.github.nanomuse.guard.SessionAccess
import io.github.nanomuse.hands.HandsReplay
import io.github.nanomuse.hands.HandsReplayAccess
import io.github.nanomuse.hands.HandsReplayStore
import io.github.nanomuse.sync.ConversationSync
import kotlinx.coroutines.launch

internal data class ChatReplaySelection(val run: HandsReplay.Run, val ticket: HandsReplayAccess.Ticket)

@Composable
internal fun ChatReplayButton(session: String, runId: String, onOpen: (ChatReplaySelection) -> Unit) {
    val ctx = LocalContext.current
    val ticket = replayTicket() ?: return
    val protected by SessionAccess.protected.collectAsState()
    val hidden by ConversationSync.hidden.collectAsState()
    val feed by FeedFlow.hidden.collectAsState()
    if (session in protected || session in hidden || session in feed) return
    key(session, runId, ticket) {
        val run = remember { HandsReplay.Run(session, runId, null) }
        var available by remember { mutableStateOf(false) }
        val scope = rememberCoroutineScope()
        LaunchedEffect(run, ticket) { available = HandsReplayStore.hasRecording(ctx, ticket, run) }
        if (available) TextButton(
            onClick = {
                scope.launch {
                    available = HandsReplayStore.hasRecording(ctx, ticket, run)
                    if (available && HandsReplayAccess.current(ctx, ticket)) onOpen(ChatReplaySelection(run, ticket))
                }
            },
            modifier = Modifier.padding(horizontal = 12.dp),
        ) {
            Icon(Icons.Outlined.History, contentDescription = null, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(6.dp))
            Text(stringResource(R.string.nm_hands_replay_open))
        }
    }
}

@Composable
internal fun ChatReplayDialog(selection: ChatReplaySelection, onDismiss: () -> Unit) {
    Dialog(onDismissRequest = onDismiss, properties = DialogProperties(
        usePlatformDefaultWidth = false, securePolicy = SecureFlagPolicy.SecureOn,
    )) {
        Box(Modifier.fillMaxSize()) { HandsReplayScreen(direct = selection, onBack = onDismiss) }
    }
}
