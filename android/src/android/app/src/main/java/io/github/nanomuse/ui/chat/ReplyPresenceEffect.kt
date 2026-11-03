package io.github.nanomuse.ui.chat

import androidx.compose.runtime.*
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.openminis.app.service.SessionActivityTracker
import io.github.nanomuse.chat.ReplyPresence

/** Both layouts report only a resumed, visible chat, including a promoted draft's real ID. */
@Composable
fun ReplyPresenceEffect(sessionId: String, visible: Boolean) {
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val presence = remember { ReplyPresence(SessionActivityTracker::setPresent, SessionActivityTracker::setAbsent) }
    val currentId by rememberUpdatedState(sessionId)
    val currentVisible by rememberUpdatedState(visible)
    SideEffect { presence.update(sessionId, visible && lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) }
    DisposableEffect(lifecycle) {
        fun update() = presence.update(currentId, currentVisible && lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED))
        val observer = LifecycleEventObserver { _, _ -> update() }
        lifecycle.addObserver(observer)
        update()
        onDispose {
            lifecycle.removeObserver(observer)
            presence.update(null, false)
        }
    }
}
