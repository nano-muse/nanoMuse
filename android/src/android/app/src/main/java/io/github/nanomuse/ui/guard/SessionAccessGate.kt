package io.github.nanomuse.ui.guard

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.openminis.app.R
import io.github.nanomuse.guard.SessionAccess
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/** Runs before the screen obtains its ViewModel, including deep-link and notification entry. */
@Composable
fun SessionAccessGate(sessionId: String, visible: Boolean = true): Boolean {
    SessionAccess.initialize(LocalContext.current)
    val revision by SessionAccess.revision.collectAsState()
    var tick by remember(sessionId) { mutableIntStateOf(0) }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    val visibility = remember { io.github.nanomuse.guard.SessionAccessVisibility(SessionAccess::leave) }
    val currentId by rememberUpdatedState(sessionId)
    val currentVisible by rememberUpdatedState(visible)
    SideEffect { visibility.update(sessionId, visible && lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)) }
    DisposableEffect(lifecycle) {
        fun update() = visibility.update(currentId, currentVisible && lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED))
        val observer = LifecycleEventObserver { _, _ -> update() }
        lifecycle.addObserver(observer)
        update()
        onDispose { lifecycle.removeObserver(observer); visibility.update(null, false) }
    }
    LaunchedEffect(sessionId) { while (true) { delay(1000); tick++ } }
    val locked = remember(sessionId, revision, tick) { SessionAccess.isLocked(sessionId) }
    if (locked) {
        val authenticate = rememberAccessAuthenticator()
        val title = stringResource(R.string.nm_session_protected)
        Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.Center) {
            Text(title, style = MaterialTheme.typography.headlineSmall)
            Text(stringResource(R.string.nm_access_hint))
            Button(onClick = { authenticate(title) { SessionAccess.authenticate(sessionId, it) } }) {
                Text(stringResource(R.string.nm_access_unlock))
            }
        }
    }
    return !locked
}

@Composable
fun SessionAccessMenuItem(sessionId: String, persistSessionId: suspend () -> String = { sessionId }, dismiss: () -> Unit) {
    val protected by SessionAccess.protected.collectAsState()
    val authenticate = rememberAccessAuthenticator()
    val scope = rememberCoroutineScope()
    var busy by remember { mutableStateOf(false) }
    val title = stringResource(if (sessionId in protected) R.string.nm_session_unprotect else R.string.nm_session_protect)
    DropdownMenuItem(enabled = !busy, text = { Text(title) }, onClick = {
        busy = true
        authenticate(title) { success ->
            scope.launch {
                try {
                    if (sessionId in protected) SessionAccess.unprotect(sessionId, success)
                    else SessionAccess.protectPersisted(success, persistSessionId)
                } finally { busy = false; dismiss() }
            }
        }
    })
}

/** One native-authentication callback for context-menu export, duplication and title generation. */
@Composable
fun rememberProtectedSessionAction(): (String, () -> Unit) -> Unit {
    val authenticate = rememberAccessAuthenticator()
    val title = stringResource(R.string.nm_session_protected)
    return { id, action -> SessionAccess.authorizeAction(id, { result -> authenticate(title, result) }, action) }
}

@Composable
fun rememberProtectedBackupAction(): (Boolean, () -> Unit) -> Unit {
    val authenticate = rememberAccessAuthenticator()
    val title = stringResource(R.string.backup_title)
    return { includesChats, action -> SessionAccess.authorizeExport(includesChats, { result -> authenticate(title, result) }, action) }
}
