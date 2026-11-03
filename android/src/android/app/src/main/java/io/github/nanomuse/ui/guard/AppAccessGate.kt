package io.github.nanomuse.ui.guard

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveableStateHolder
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.openminis.app.R
import io.github.nanomuse.guard.AppAccess
import io.github.nanomuse.guard.AccessAuthentication
import io.github.nanomuse.guard.DeviceCredential

fun Context.accessActivity(): Activity? = when (this) {
    is Activity -> this
    is ContextWrapper -> baseContext.accessActivity()
    else -> null
}

@Composable
fun rememberAccessAuthenticator(): (String, (Boolean) -> Unit) -> Unit {
    val context = LocalContext.current
    val activity = context.accessActivity()
    var pending by remember { mutableStateOf<((Boolean) -> Unit)?>(null) }
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        pending?.invoke(result.resultCode == Activity.RESULT_OK)
        pending = null
    }
    return { title, callback ->
        if (activity == null || !AccessAuthentication.available(context) || pending != null) callback(false)
        else if (DeviceCredential.promptsItself()) AccessAuthentication.confirm(activity, title, callback)
        else {
            val intent = DeviceCredential.keyguardIntent(context, title, title)
            if (intent == null) callback(false)
            else { pending = callback; launcher.launch(intent) }
        }
    }
}

/** Same entry gate for both layouts and incoming shares; save navigation across re-locks. */
fun ComponentActivity.secureSetContent(content: @Composable () -> Unit) {
    AppAccess.initialize(this)
    setContent { MaterialTheme { AppAccessGate(content) } }
}

@Composable
fun AppAccessGate(content: @Composable () -> Unit) {
    val locked by AppAccess.locked.collectAsState()
    val holder = rememberSaveableStateHolder()
    if (!locked) holder.SaveableStateProvider("unlocked") { content() }
    else {
        val context = LocalContext.current
        val authenticate = rememberAccessAuthenticator()
        val title = stringResource(R.string.nm_access_locked)
        var busy by remember { mutableStateOf(false) }
        BackHandler { context.accessActivity()?.moveTaskToBack(true) }
        Column(Modifier.fillMaxSize().padding(32.dp), verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally) {
            Text(title, style = MaterialTheme.typography.headlineSmall)
            Spacer(Modifier.height(16.dp))
            Text(stringResource(R.string.nm_access_hint))
            Button(enabled = !busy, onClick = {
                busy = true
                authenticate(title) { success -> AppAccess.authenticated(success); busy = false }
            }) { Text(stringResource(R.string.nm_access_unlock)) }
        }
    }
}

@Composable
fun AppAccessSettings() {
    var show by remember { mutableStateOf(false) }
    var enabled by remember { mutableStateOf(AppAccess.enabled) }
    var timeout by remember { mutableIntStateOf(AppAccess.timeout) }
    val context = LocalContext.current
    val authenticate = rememberAccessAuthenticator()
    val title = stringResource(R.string.nm_access_settings)
    TextButton(onClick = { show = true }) { Text(title) }
    if (show) AlertDialog(onDismissRequest = { show = false }, title = { Text(title) }, text = {
        Column {
            Text(stringResource(R.string.nm_access_hint))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Checkbox(checked = enabled, onCheckedChange = { enabled = it })
                Text(title)
            }
            for (seconds in AppAccess.TIMEOUTS) Row(verticalAlignment = Alignment.CenterVertically) {
                RadioButton(selected = timeout == seconds, onClick = { timeout = seconds })
                Text(when (seconds) {
                    -1 -> stringResource(R.string.nm_access_on_exit)
                    0 -> stringResource(R.string.nm_access_never)
                    else -> stringResource(R.string.nm_access_seconds, seconds)
                })
            }
            if (!AccessAuthentication.available(context)) Text(stringResource(R.string.nm_access_unavailable))
        }
    }, confirmButton = {
        TextButton(enabled = AccessAuthentication.available(context), onClick = {
            authenticate(title) { success -> if (AppAccess.configure(enabled, timeout, success)) show = false }
        }) { Text(stringResource(android.R.string.ok)) }
    }, dismissButton = {
        TextButton(onClick = { show = false }) { Text(stringResource(android.R.string.cancel)) }
    })
}
