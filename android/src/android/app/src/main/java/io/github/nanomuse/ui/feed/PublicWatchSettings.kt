package io.github.nanomuse.ui.feed

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.openminis.app.R
import io.github.nanomuse.feed.PublicWatchStore
import io.github.nanomuse.guard.AppAccess
import io.github.nanomuse.guard.SessionAccess
import io.github.nanomuse.home.MainChat
import io.github.nanomuse.sync.ConversationSync
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

@Composable
internal fun PublicWatchSettings() {
    val context = LocalContext.current
    val change by PublicWatchStore.changes.collectAsState()
    val locked by AppAccess.locked.collectAsState()
    val protected by SessionAccess.protected.collectAsState()
    val hidden by ConversationSync.hidden.collectAsState()
    val main by MainChat.sessionId.collectAsState()
    val owner = remember(change, locked, main, protected, hidden) { PublicWatchStore.scope(context) }
    var expanded by remember(owner) { mutableStateOf(false) }
    var state by remember(owner) { mutableStateOf<JSONObject?>(null) }
    var error by remember(owner) { mutableStateOf(false) }
    var saving by remember(owner) { mutableStateOf(false) }
    var target by remember(owner) { mutableStateOf("") }
    var kind by remember(owner) { mutableStateOf("github_repo") }
    var linking by remember(owner) { mutableStateOf<String?>(null) }
    val jobs = rememberCoroutineScope()
    LaunchedEffect(owner, change, expanded) {
        if (owner != null && expanded) {
            val read = withContext(Dispatchers.IO) { runCatching { PublicWatchStore.invoke(context, owner) }.getOrNull() }
            state = read
            if (read == null) error = true
        }
    }
    fun edit(fields: JSONObject, saved: () -> Unit = {}) {
        val current = state ?: return
        val scope = owner ?: return
        if (saving) return
        saving = true
        jobs.launch {
            val result = withContext(Dispatchers.IO) { runCatching {
                PublicWatchStore.invoke(context, scope, "edit", fields.put("revision", current.getLong("revision")))
            }.getOrNull() }
            if (PublicWatchStore.scope(context) == scope) {
                error = result == null || result.has("error")
                state = withContext(Dispatchers.IO) { runCatching { PublicWatchStore.invoke(context, scope) }.getOrNull() }
                if (!error) saved()
            }
            saving = false
        }
    }
    Column(Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 4.dp)) {
        Text(stringResource(R.string.nm_public_sources), Modifier.fillMaxWidth()
            .clickable(enabled = owner != null) { expanded = !expanded }.padding(vertical = 12.dp), fontSize = 15.sp)
        if (!expanded || owner == null) return@Column
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(stringResource(R.string.nm_public_hint), Modifier.weight(1f), style = MaterialTheme.typography.bodySmall)
            Switch(checked = state?.optBoolean("enabled") == true, enabled = state != null && !saving,
                onCheckedChange = { edit(JSONObject().put("enabled", it)) })
        }
        val watches = state?.optJSONArray("watches")
        for (i in 0 until (watches?.length() ?: 0)) {
            val watch = watches!!.getJSONObject(i)
            val id = watch.getString("id")
            val status = watch.getString("status")
            val scholar = watch.getString("kind") == "scholar_profile"
            val label = watch.getString("label")
            Text(label, Modifier.padding(top = 8.dp), style = MaterialTheme.typography.titleSmall)
            val statusText = stringResource(when (status) {
                "suggested" -> R.string.nm_public_suggested
                "paused" -> R.string.nm_goal_status_paused
                else -> R.string.enabled
            })
            val origin = stringResource(when (watch.optString("origin")) {
                "chat" -> R.string.nm_public_chat
                "recurring" -> R.string.nm_public_recurring
                "connected" -> R.string.nm_public_connected
                else -> R.string.nm_public_manual
            })
            Text("$statusText · $origin", style = MaterialTheme.typography.bodySmall)
            if (label != watch.optString("target")) Text(watch.optString("target"), style = MaterialTheme.typography.bodySmall)
            if (watch.optBoolean("unavailable")) Text(stringResource(R.string.nm_public_unavailable), style = MaterialTheme.typography.bodySmall)
            Row {
                val action = when (status) { "suggested" -> "confirm"; "active" -> "pause"; else -> "resume" }
                TextButton(enabled = !saving, onClick = {
                    if (scholar) { linking = id; kind = "research_author"; target = "" }
                    else edit(JSONObject().put("id", id).put("action", action))
                }) { Text(stringResource(when { scholar -> R.string.nm_public_link; status == "suggested" -> R.string.nm_public_follow
                    status == "active" -> R.string.nm_goal_pause; else -> R.string.nm_goal_resume })) }
                TextButton(enabled = !saving, onClick = { edit(JSONObject().put("id", id).put("action", "dismiss")) {
                    if (linking == id) linking = null
                } }) { Text(stringResource(R.string.nm_own_clip_mood_remove)) }
            }
        }
        val labels = linkedMapOf("github_repo" to "GitHub · owner/repo", "github_user" to "GitHub · @user",
            "research_author" to "OpenAlex / ORCID", "research_work" to "DOI",
            "research_topic" to stringResource(R.string.nm_public_topic), "feed" to stringResource(R.string.nm_public_website),
            "scholar_profile" to "Google Scholar")
        var menu by remember(owner) { mutableStateOf(false) }
        Box {
            TextButton(onClick = { menu = true }) { Text(labels.getValue(kind) + " ▾") }
            DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                labels.filterKeys { linking == null || it in setOf("research_author", "research_work") }.forEach { (id, name) ->
                    DropdownMenuItem(text = { Text(name) }, onClick = { kind = id; menu = false })
                }
            }
        }
        OutlinedTextField(value = target, onValueChange = { target = it.take(400); error = false }, singleLine = true,
            modifier = Modifier.fillMaxWidth(), label = { Text(labels.getValue(kind)) })
        Row {
            TextButton(enabled = target.isNotBlank() && state != null && !saving, onClick = {
                val fields = JSONObject().put("kind", kind).put("target", target.trim())
                linking?.let { fields.put("id", it).put("action", "confirm") }
                edit(fields) { target = ""; linking = null }
            }) { Text(stringResource(if (linking == null) R.string.nm_public_follow else R.string.nm_public_link)) }
            if (linking != null) TextButton(onClick = { linking = null; target = "" }) { Text(stringResource(R.string.nm_cancel)) }
        }
        if (error) Text(stringResource(R.string.nm_public_error), color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
    }
}
