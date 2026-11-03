package io.github.nanomuse.ui.guard

import androidx.compose.foundation.layout.Column
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import com.openminis.app.R
import com.openminis.app.backup.BackupExporter
import io.github.nanomuse.backup.ExportResume
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Resume and discard share the exporter's process-wide lock with scheduled runs. */
@Composable
fun BackupResumeActions(running: Boolean, onResume: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var pending by remember { mutableStateOf<ExportResume.Run?>(null) }
    var discard by remember { mutableStateOf(false) }
    var failed by remember { mutableStateOf(false) }
    LaunchedEffect(running) {
        if (!running) {
            runCatching { withContext(Dispatchers.IO) { BackupExporter.interrupted(context) } }
                .onSuccess { pending = it }.onFailure { failed = true }
        }
    }
    if (pending != null && !running) Column {
        Text(stringResource(R.string.nm_backup_resume_hint))
        TextButton(onClick = onResume) { Text(stringResource(R.string.nm_backup_resume)) }
        TextButton(onClick = { discard = true }) { Text(stringResource(R.string.nm_backup_discard)) }
    }
    if (failed) Text(stringResource(R.string.nm_backup_resume_hint))
    if (discard) AlertDialog(onDismissRequest = { discard = false },
        title = { Text(stringResource(R.string.nm_backup_discard)) },
        text = { Text(stringResource(R.string.nm_backup_resume_hint)) },
        confirmButton = { TextButton(onClick = {
            val id = pending?.id
            discard = false
            if (id != null) scope.launch {
                runCatching { withContext(Dispatchers.IO) { BackupExporter.discardInterrupted(context, id) } }
                    .onSuccess { pending = null }.onFailure { failed = true }
            }
        }) { Text(stringResource(android.R.string.ok)) } },
        dismissButton = { TextButton(onClick = { discard = false }) { Text(stringResource(android.R.string.cancel)) } })
}
