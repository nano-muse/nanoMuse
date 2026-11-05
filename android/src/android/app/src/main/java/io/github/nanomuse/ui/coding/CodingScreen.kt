package io.github.nanomuse.ui.coding

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.outlined.Send
import androidx.compose.material.icons.outlined.Build
import androidx.compose.material.icons.outlined.Computer
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Stop
import androidx.compose.material.icons.outlined.Terminal
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Scaffold
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.openminis.app.R
import com.openminis.app.logging.AppLogger
import io.github.nanomuse.coding.CodingBridge
import io.github.nanomuse.coding.CodingBridge.Agent
import io.github.nanomuse.coding.CodingBridge.LiveRun
import io.github.nanomuse.coding.CodingBridge.Message
import io.github.nanomuse.coding.CodingBridge.Session
import io.github.nanomuse.hub.Device
import io.github.nanomuse.hub.Hub
import io.github.nanomuse.hub.HubErrors
import io.github.nanomuse.sysfiles.SystemFiles
import io.github.nanomuse.ui.home.MuseTones
import io.github.nanomuse.ui.muse.MuseCard
import io.github.nanomuse.ui.muse.MuseGap
import io.github.nanomuse.ui.muse.MuseRow
import io.github.nanomuse.ui.muse.MuseRowDivider
import io.github.nanomuse.ui.muse.MuseSectionLabel
import io.github.nanomuse.ui.muse.MuseTopAppBar
import kotlinx.coroutines.launch

const val ROUTE_CODING = "nanomuse/coding"

/**
 * The coding agents on the account's computers — Cursor, Codex, Claude Code — seen and steered
 * from the phone: which are installed and busy, their recent sessions with the last exchange,
 * a session's transcript, and a message to any of them, the answer streaming back over the hub.
 * Everything goes through the runtime on that computer (`coding.*` hub actions); nothing is
 * read from the phone itself.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CodingScreen(onBack: () -> Unit, onOpenDevices: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val devices by Hub.devices.collectAsState()
    val connected by Hub.connected.collectAsState()
    val me = remember { Hub.deviceId(context) }
    val computers = devices.filter { it.id != me && it.online && it.actions.contains("coding.sessions") }
    var chosenId by remember { mutableStateOf<String?>(null) }
    val computer = computers.firstOrNull { it.id == chosenId } ?: computers.firstOrNull()

    var agents by remember { mutableStateOf<List<Agent>>(emptyList()) }
    var sessions by remember { mutableStateOf<List<Session>>(emptyList()) }
    var filter by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var open by remember { mutableStateOf<Session?>(null) }
    var newWith by remember { mutableStateOf<Agent?>(null) }

    fun load() {
        val dev = computer ?: return
        if (loading) return
        loading = true
        error = null
        scope.launch {
            try {
                agents = CodingBridge.agents(dev.id)
                sessions = CodingBridge.sessions(dev.id, null)
            } catch (e: Exception) {
                AppLogger.info("CodingScreen", "list failed: ${e.message}")
                error = HubErrors.describe(context, e)
            }
            loading = false
        }
    }
    LaunchedEffect(computer?.id) { if (computer != null) load() else { agents = emptyList(); sessions = emptyList() } }

    val current = open
    if (current != null && computer != null) {
        BackHandler { open = null }
        SessionScreen(
            computer = computer,
            session = current,
            agentName = agents.firstOrNull { it.id == current.agent }?.name ?: current.agent,
            onBack = { open = null; load() },
        )
        return
    }

    Scaffold(
        containerColor = MuseTones.canvas,
        topBar = {
            MuseTopAppBar(
                title = { Text(stringResource(R.string.nm_coding_title)) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = stringResource(R.string.settings_back))
                    }
                },
                actions = {
                    if (computer != null) {
                        IconButton(onClick = { load() }, enabled = !loading) {
                            if (loading) {
                                CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp, color = MuseTones.action)
                            } else {
                                Icon(Icons.Outlined.Refresh, contentDescription = stringResource(R.string.nm_coding_refresh))
                            }
                        }
                    }
                },
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState()),
        ) {
            Spacer(Modifier.height(8.dp))
            if (computer == null) {
                MuseCard {
                    Column(Modifier.padding(16.dp)) {
                        Icon(Icons.Outlined.Terminal, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.size(28.dp))
                        Spacer(Modifier.height(10.dp))
                        Text(stringResource(R.string.nm_coding_title), style = MaterialTheme.typography.titleMedium)
                        Text(
                            text = stringResource(R.string.nm_coding_intro),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(top = 6.dp),
                        )
                        Spacer(Modifier.height(10.dp))
                        Text(
                            text = stringResource(if (connected) R.string.nm_coding_no_computer else R.string.nm_devices_off),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                        // nanoMuse: a computer that is missing here has nearly always signed in with another account — say which this phone uses
                        val accountHint = remember { io.github.nanomuse.cloud.NanoMuseCloud.account(context)?.hint }
                        if (connected && !accountHint.isNullOrBlank()) {
                            Text(
                                text = stringResource(R.string.nm_coding_account_hint, accountHint),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.padding(top = 6.dp),
                            )
                        }
                    }
                    MuseRowDivider(inset = 16.dp)
                    MuseRow(title = stringResource(R.string.nm_devices_title), icon = Icons.Outlined.Computer, onClick = onOpenDevices)
                }
            } else {
                // -- which computer, and what is installed there ----------------------------
                MuseCard {
                    var menu by remember { mutableStateOf(false) }
                    Box {
                        MuseRow(
                            title = computer.name,
                            icon = Icons.Outlined.Computer,
                            value = computer.os.ifBlank { null },
                            chevron = computers.size > 1,
                            onClick = { if (computers.size > 1) menu = true },
                        )
                        DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                            computers.forEach { c ->
                                DropdownMenuItem(text = { Text(c.name) }, onClick = { chosenId = c.id; menu = false })
                            }
                        }
                    }
                    if (agents.isNotEmpty()) {
                        MuseRowDivider(inset = 16.dp)
                        Row(
                            modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState())
                                .padding(horizontal = 16.dp, vertical = 12.dp),
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            AgentChip(stringResource(R.string.nm_coding_all), selected = filter == null, running = 0, installed = true) { filter = null }
                            agents.forEach { a ->
                                val status = stringResource(when {
                                    a.running > 0 -> R.string.nm_coding_running
                                    a.installed -> R.string.nm_coding_installed
                                    else -> R.string.nm_coding_not_installed
                                })
                                AgentChip("${a.name} · $status", selected = filter == a.id, running = a.running, installed = a.installed) {
                                    filter = if (filter == a.id) null else a.id
                                }
                            }
                        }
                    }
                }
                error?.let {
                    Text(
                        text = it,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                        modifier = Modifier.padding(horizontal = 32.dp, vertical = 8.dp),
                    )
                }

                // -- start something new ---------------------------------------------------
                val installed = agents.filter { it.installed }
                if (installed.isNotEmpty()) {
                    MuseSectionLabel(stringResource(R.string.nm_coding_new))
                    MuseCard {
                        installed.forEachIndexed { i, a ->
                            if (i > 0) MuseRowDivider()
                            MuseRow(
                                title = stringResource(R.string.nm_coding_new_with, a.name),
                                icon = Icons.Outlined.Add,
                                value = a.version.ifBlank { null },
                                onClick = { newWith = a },
                            )
                        }
                    }
                }

                // -- recent sessions --------------------------------------------------------
                MuseSectionLabel(stringResource(R.string.nm_coding_sessions))
                val shown = sessions.filter { filter == null || it.agent == filter }
                MuseCard {
                    if (shown.isEmpty()) {
                        Text(
                            text = if (loading) stringResource(R.string.nm_cloud_refreshing) else stringResource(R.string.nm_coding_no_sessions),
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(16.dp),
                        )
                    }
                    shown.forEachIndexed { i, s ->
                        if (i > 0) MuseRowDivider(inset = 16.dp)
                        SessionRow(
                            session = s,
                            agentName = agents.firstOrNull { it.id == s.agent }?.name ?: s.agent,
                            onClick = { open = s },
                        )
                    }
                }
                MuseGap()
                Text(
                    text = stringResource(R.string.nm_coding_intro),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(horizontal = 32.dp),
                )
            }
            Spacer(Modifier.height(24.dp))
        }
    }

    newWith?.let { agent ->
        NewConversationDialog(
            agent = agent,
            workspaces = sessions.filter { it.agent == agent.id }.map { it.workspace }.filter { it.isNotBlank() }.distinct().take(8),
            onDismiss = { newWith = null },
            onStart = { workspace ->
                newWith = null
                open = Session(
                    agent = agent.id, id = "", title = "", workspace = workspace, updatedAt = System.currentTimeMillis() / 1000,
                    messages = 0, status = "idle", lastUser = "", lastAssistant = "", resumable = true,
                )
            },
        )
    }
}

/** One agent as a chip: its name, a dot when something of it is running, greyed when not installed. */
@Composable
private fun AgentChip(label: String, selected: Boolean, running: Int, installed: Boolean, onClick: () -> Unit) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier
            .clip(RoundedCornerShape(50))
            .background(if (selected) MaterialTheme.colorScheme.onSurface else MuseTones.fill)
            .clickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 7.dp),
    ) {
        if (running > 0) {
            Box(Modifier.size(7.dp).clip(CircleShape).background(Color(0xFF34C759)))
            Spacer(Modifier.width(6.dp))
        }
        Text(
            text = label,
            maxLines = 1,
            softWrap = false,
            fontSize = 13.sp,
            fontWeight = FontWeight.Medium,
            color = when {
                selected -> MuseTones.surface
                installed -> MaterialTheme.colorScheme.onSurface
                else -> MaterialTheme.colorScheme.onSurfaceVariant
            },
        )
    }
}

@Composable
private fun SessionRow(session: Session, agentName: String, onClick: () -> Unit) {
    val context = LocalContext.current
    Row(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(
                text = session.title.ifBlank { session.lastUser.ifBlank { stringResource(R.string.nm_coding_untitled) } },
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Spacer(Modifier.height(2.dp))
            Text(
                text = listOf(
                    agentName,
                    session.workspace.substringAfterLast('/').ifBlank { null },
                    if (session.status == "running") stringResource(R.string.nm_coding_running) else SystemFiles.relative(context, session.updatedAt * 1000),
                ).filterNotNull().joinToString(" · "),
                style = MaterialTheme.typography.bodySmall,
                color = if (session.status == "running") Color(0xFF34C759) else MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            if (session.lastAssistant.isNotBlank()) {
                Spacer(Modifier.height(4.dp))
                Text(
                    text = session.lastAssistant,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        if (session.status == "running") {
            Spacer(Modifier.width(10.dp))
            CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp, color = Color(0xFF34C759))
        }
    }
}

@Composable
private fun NewConversationDialog(agent: Agent, workspaces: List<String>, onDismiss: () -> Unit, onStart: (workspace: String) -> Unit) {
    var workspace by remember { mutableStateOf(workspaces.firstOrNull() ?: "") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.nm_coding_new_with, agent.name)) },
        text = {
            Column {
                OutlinedTextField(
                    value = workspace,
                    onValueChange = { workspace = it },
                    label = { Text(stringResource(R.string.nm_coding_workspace)) },
                    singleLine = true,
                    shape = RoundedCornerShape(12.dp),
                    colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = MuseTones.action, cursorColor = MuseTones.action, focusedLabelColor = MuseTones.action),
                    modifier = Modifier.fillMaxWidth(),
                )
                if (workspaces.size > 1) {
                    Spacer(Modifier.height(8.dp))
                    workspaces.drop(if (workspace == workspaces.first()) 1 else 0).take(5).forEach { w ->
                        Text(
                            text = w,
                            fontSize = 12.sp,
                            fontFamily = FontFamily.Monospace,
                            color = MuseTones.action,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.fillMaxWidth().clickable { workspace = w }.padding(vertical = 4.dp),
                        )
                    }
                }
                Spacer(Modifier.height(8.dp))
                Text(
                    text = stringResource(R.string.nm_coding_workspace_hint),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        },
        confirmButton = {
            TextButton(onClick = { onStart(workspace.trim()) }) { Text(stringResource(R.string.nm_coding_start), color = MuseTones.action) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) } },
    )
}

/**
 * One session: the transcript as it is on the computer, the run in progress streaming under it
 * (text, tool calls), and the composer. A message goes out as `coding.send` and the screen
 * follows it until the agent is done; then the transcript is re-read from disk.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SessionScreen(computer: Device, session: Session, agentName: String, onBack: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var sessionId by remember { mutableStateOf(session.id) }
    var transcript by remember { mutableStateOf<List<Message>>(emptyList()) }
    var live by remember { mutableStateOf<LiveRun?>(null) }
    var draft by remember { mutableStateOf("") }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val listState = rememberLazyListState()

    fun reload() {
        if (sessionId.isBlank()) return
        loading = true
        scope.launch {
            try {
                transcript = CodingBridge.transcript(computer.id, session.agent, sessionId)
                error = null
            } catch (e: Exception) {
                AppLogger.info("CodingScreen", "transcript failed: ${e.message}")
                error = HubErrors.describe(context, e)
            }
            loading = false
        }
    }
    LaunchedEffect(sessionId) { reload() }
    LaunchedEffect(transcript.size, live?.output?.length, live?.current?.length) {
        val n = transcript.size + (if (live != null) 1 else 0)
        if (n > 0) listState.animateScrollToItem(n - 1)
    }

    fun send() {
        val text = draft.trim()
        if (text.isEmpty() || live?.status == "running") return
        draft = ""
        error = null
        val run = LiveRun(text = text)
        live = run
        scope.launch {
            try {
                val final = CodingBridge.send(
                    device = computer.id,
                    agent = session.agent,
                    text = text,
                    sessionId = sessionId,
                    workspace = session.workspace,
                    onUpdate = { updated -> live = updated },
                )
                live = final
                if (final.sessionId.isNotBlank() && final.sessionId != sessionId) sessionId = final.sessionId else reload()
            } catch (e: Exception) {
                AppLogger.info("CodingScreen", "send failed: ${e.message}")
                live = live?.copy(status = "failed", error = HubErrors.describe(context, e))
            }
        }
    }

    Scaffold(
        containerColor = MuseTones.canvas,
        topBar = {
            MuseTopAppBar(
                title = {
                    Column {
                        Text(
                            text = session.title.ifBlank { stringResource(R.string.nm_coding_new_with, agentName) },
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            fontSize = 16.sp,
                        )
                        Text(
                            text = listOf(agentName, computer.name, session.workspace.substringAfterLast('/').ifBlank { null }).filterNotNull().joinToString(" · "),
                            fontSize = 12.sp,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = stringResource(R.string.settings_back))
                    }
                },
                actions = {
                    IconButton(onClick = { reload() }, enabled = !loading && sessionId.isNotBlank()) {
                        Icon(Icons.Outlined.Refresh, contentDescription = stringResource(R.string.nm_coding_refresh))
                    }
                },
            )
        },
        bottomBar = {
            // an IDE chat the CLI cannot reopen: the message opens a new chat in the same
            // workspace with the last exchange quoted — the placeholder says so
            val continuesAsNew = !session.resumable && sessionId == session.id && live?.status != "running"
            Composer(
                draft = draft,
                onDraft = { draft = it },
                hint = if (continuesAsNew) stringResource(R.string.nm_coding_continue_new_hint) else stringResource(R.string.nm_coding_send_hint, agentName),
                running = live?.status == "running",
                onSend = { send() },
                onStop = {
                    val id = live?.id ?: return@Composer
                    scope.launch { runCatching { CodingBridge.stop(computer.id, id) } }
                },
            )
        },
    ) { padding ->
        LazyColumn(
            state = listState,
            modifier = Modifier.fillMaxSize().padding(padding),
            contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 16.dp, vertical = 12.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            if (transcript.isEmpty() && live == null) {
                item {
                    Text(
                        text = when {
                            loading -> stringResource(R.string.nm_cloud_refreshing)
                            error != null -> error ?: ""
                            sessionId.isBlank() -> stringResource(R.string.nm_coding_fresh_hint, agentName)
                            else -> stringResource(R.string.nm_coding_no_transcript)
                        },
                        style = MaterialTheme.typography.bodySmall,
                        color = if (error != null) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(8.dp),
                    )
                }
            }
            items(transcript) { m -> Bubble(m.role, m.text) }
            live?.let { run ->
                // The exchange in flight, unless the transcript re-read already has it.
                val absorbed = run.status != "running" && transcript.any { it.role == "user" && it.text.trim() == run.text.trim() }
                if (!absorbed) {
                    item { Bubble("user", run.text) }
                    item { LiveBlock(run) }
                }
            }
        }
    }
}

@Composable
private fun Bubble(role: String, text: String) {
    val mine = role == "user"
    Row(Modifier.fillMaxWidth(), horizontalArrangement = if (mine) Arrangement.End else Arrangement.Start) {
        Box(
            modifier = Modifier
                .widthIn(max = 320.dp)
                .clip(RoundedCornerShape(topStart = 18.dp, topEnd = 18.dp, bottomStart = if (mine) 18.dp else 6.dp, bottomEnd = if (mine) 6.dp else 18.dp))
                .background(if (mine) MaterialTheme.colorScheme.onSurface else MuseTones.surface)
                .padding(horizontal = 14.dp, vertical = 10.dp),
        ) {
            Text(
                text = text,
                fontSize = 14.sp,
                lineHeight = 20.sp,
                color = if (mine) MuseTones.surface else MaterialTheme.colorScheme.onSurface,
            )
        }
    }
}

/** The agent's answer as it streams: finished paragraphs, the one being written, tool calls, the end. */
@Composable
private fun LiveBlock(run: LiveRun) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Start) {
        Column(
            modifier = Modifier
                .widthIn(max = 340.dp)
                .clip(RoundedCornerShape(topStart = 18.dp, topEnd = 18.dp, bottomStart = 6.dp, bottomEnd = 18.dp))
                .background(MuseTones.surface)
                .border(1.dp, if (run.status == "running") MuseTones.action.copy(alpha = 0.35f) else Color.Transparent, RoundedCornerShape(18.dp))
                .padding(horizontal = 14.dp, vertical = 10.dp),
        ) {
            val body = listOf(run.output, run.current).filter { it.isNotBlank() }.joinToString("\n")
            if (body.isNotBlank()) {
                Text(text = body, fontSize = 14.sp, lineHeight = 20.sp, color = MaterialTheme.colorScheme.onSurface)
            }
            if (run.lastTool.isNotBlank() && run.status == "running") {
                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = if (body.isNotBlank()) 8.dp else 0.dp)) {
                    Icon(Icons.Outlined.Build, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.size(14.dp))
                    Spacer(Modifier.width(6.dp))
                    Text(
                        text = run.lastTool,
                        fontSize = 12.sp,
                        fontFamily = FontFamily.Monospace,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
            val foot = when (run.status) {
                "running" -> if (body.isBlank() && run.lastTool.isBlank()) stringResource(R.string.nm_coding_working) else null
                "failed" -> stringResource(R.string.nm_coding_failed, run.error.ifBlank { "?" })
                "stopped" -> stringResource(R.string.nm_coding_stopped)
                else -> if (run.tools > 0) stringResource(R.string.nm_coding_tools, run.tools) else null
            }
            if (foot != null) {
                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = if (body.isNotBlank()) 8.dp else 0.dp)) {
                    if (run.status == "running") {
                        CircularProgressIndicator(modifier = Modifier.size(12.dp), strokeWidth = 1.5.dp, color = MuseTones.action)
                        Spacer(Modifier.width(8.dp))
                    }
                    Text(
                        text = foot,
                        fontSize = 12.sp,
                        color = if (run.status == "failed") MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
    }
}

@Composable
private fun Composer(draft: String, onDraft: (String) -> Unit, hint: String, running: Boolean, onSend: () -> Unit, onStop: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .background(MuseTones.canvas)
            .imePadding()
            .padding(horizontal = 12.dp, vertical = 10.dp),
        verticalAlignment = Alignment.Bottom,
    ) {
        OutlinedTextField(
            value = draft,
            onValueChange = onDraft,
            placeholder = { Text(hint, color = MaterialTheme.colorScheme.onSurfaceVariant) },
            maxLines = 5,
            shape = RoundedCornerShape(22.dp),
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Default),
            colors = OutlinedTextFieldDefaults.colors(
                focusedBorderColor = MuseTones.action,
                unfocusedBorderColor = MuseTones.hairline,
                focusedContainerColor = MuseTones.surface,
                unfocusedContainerColor = MuseTones.surface,
                cursorColor = MuseTones.action,
            ),
            modifier = Modifier.weight(1f),
        )
        Spacer(Modifier.width(10.dp))
        val canSend = draft.isNotBlank() && !running
        Box(
            modifier = Modifier
                .size(48.dp)
                .clip(CircleShape)
                .background(
                    when {
                        running -> MaterialTheme.colorScheme.error
                        canSend -> MuseTones.action
                        else -> MuseTones.fill
                    },
                )
                .clickable(enabled = running || canSend) { if (running) onStop() else onSend() },
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                imageVector = if (running) Icons.Outlined.Stop else Icons.AutoMirrored.Outlined.Send,
                contentDescription = stringResource(if (running) R.string.nm_coding_stop else R.string.nm_coding_send),
                tint = if (running || canSend) Color.White else MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.size(20.dp),
            )
        }
    }
}
