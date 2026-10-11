package io.github.nanomuse.ui.home

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding

import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Archive
import androidx.compose.material.icons.outlined.Description
import androidx.compose.material.icons.outlined.Devices
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material.icons.outlined.Forum
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material.icons.outlined.Terminal
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LocalTextStyle
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.openminis.app.R
import com.openminis.app.data.db.ChatSessionEntity
import com.openminis.app.data.repository.ChatRepository
import com.openminis.app.ui.theme.ChatColors
import java.text.DateFormat
import java.util.Date

/**
 * Muse's chats drawer: the agent's name, the "main chat" row, then side chats by topic, with
 * search, settings and "new" along the bottom. The archive glyph beside the section title opens
 * the full OpenMinis session list (folders, groups, search, bulk actions) — nothing upstream is
 * lost, it just moved one tap away.
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun SideChatDrawer(
    agentName: String,
    chatRepository: ChatRepository,
    mainSessionId: String?,
    currentSessionId: String?,
    onOpenMain: () -> Unit,
    onOpenSession: (String) -> Unit,
    onNewChat: () -> Unit,
    onAllChats: () -> Unit,
    onSettings: () -> Unit,
    onSetMain: (String) -> Unit,
    onSystemFiles: (() -> Unit)? = null,
    onDevices: (() -> Unit)? = null,
    onCoding: (() -> Unit)? = null,
) {
    val sessions by chatRepository.observeSessions().collectAsState(initial = emptyList())
    // nanoMuse: the account's other devices, for the row under the main chat
    val hubConnected by io.github.nanomuse.hub.Hub.connected.collectAsState()
    val hubDevices by io.github.nanomuse.hub.Hub.devices.collectAsState()
    val context = androidx.compose.ui.platform.LocalContext.current
    val othersOnline = remember(hubDevices) { hubDevices.count { it.online && it.kind != "web" && it.id != io.github.nanomuse.hub.Hub.deviceId(context) } }
    // nanoMuse: computers whose runtime can show and steer coding agents (Cursor, Codex, Claude Code)
    val codingComputers = remember(hubDevices) {
        hubDevices.count { it.online && it.actions.contains("coding.sessions") && it.id != io.github.nanomuse.hub.Hub.deviceId(context) }
    }
    // nanoMuse: a chat from another device of the account is the same chat here (contract C8) — no
    // badge per chat; the turns written elsewhere carry "From Pixel 8" in the bubble instead
    var query by remember { mutableStateOf("") }
    val sideChats = remember(sessions, mainSessionId, query) {
        sessions
            .filter { it.id != mainSessionId }
            .filter { query.isBlank() || (it.title ?: "").contains(query, ignoreCase = true) }
            .sortedWith(compareByDescending<ChatSessionEntity> { it.pinnedAt ?: 0L }.thenByDescending { it.updatedAt })
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(ChatColors.background)
            .statusBarsPadding()
            .navigationBarsPadding(),
    ) {
        // nanoMuse: Muse's drawer voice — the agent name big and plain, rows in
        // quiet pills, everything monochrome.
        val nmDark = ChatColors.isDark
        val nmRowSelected = if (nmDark) Color.White.copy(alpha = 0.09f) else Color.Black.copy(alpha = 0.06f)
        val nmInk = ChatColors.primaryText
        val nmMuted = ChatColors.secondaryText
        Text(
            text = agentName,
            fontSize = 28.sp,
            fontWeight = FontWeight.Bold,
            color = nmInk,
            modifier = Modifier.padding(start = 20.dp, top = 22.dp, end = 20.dp, bottom = 18.dp),
        )

        // Main chat row — selected when it is what the chat tab shows.
        val mainSelected = currentSessionId == null || currentSessionId == mainSessionId
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier
                .padding(horizontal = 12.dp)
                .fillMaxWidth()
                .clip(RoundedCornerShape(12.dp))
                .background(if (mainSelected) nmRowSelected else Color.Transparent)
                .clickable(onClick = onOpenMain)
                .padding(horizontal = 14.dp, vertical = 13.dp),
        ) {
            Icon(Icons.Outlined.Home, contentDescription = null, modifier = Modifier.size(22.dp), tint = nmInk)
            Spacer(Modifier.size(14.dp))
            Text(
                text = stringResource(R.string.nm_drawer_main_chat),
                fontSize = 16.sp,
                fontWeight = FontWeight.Medium,
                color = nmInk,
            )
        }

        // nanoMuse: Devices — the account's other Muses, one tap away like a chat (docs/every-device.md)
        if (onDevices != null) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier
                    .padding(horizontal = 12.dp)
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(12.dp))
                    .clickable(onClick = onDevices)
                    .padding(horizontal = 14.dp, vertical = 13.dp),
            ) {
                Icon(Icons.Outlined.Devices, contentDescription = null, modifier = Modifier.size(22.dp), tint = nmInk)
                Spacer(Modifier.size(14.dp))
                Text(
                    text = stringResource(R.string.nm_devices_title),
                    fontSize = 16.sp,
                    fontWeight = FontWeight.Medium,
                    color = nmInk,
                    modifier = Modifier.weight(1f),
                )
                Text(
                    text = when {
                        !hubConnected -> stringResource(R.string.nm_devices_off)
                        othersOnline == 0 -> stringResource(R.string.nm_hub_service_alone_short)
                        else -> pluralStringResource(R.plurals.nm_hub_service_devices, othersOnline, othersOnline)
                    },
                    fontSize = 13.sp,
                    color = nmMuted,
                )
            }
        }

        // nanoMuse: Coding — the coding agents on the account's computers, shown once one is online
        if (onCoding != null && codingComputers > 0) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier
                    .padding(horizontal = 12.dp)
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(12.dp))
                    .clickable(onClick = onCoding)
                    .padding(horizontal = 14.dp, vertical = 13.dp),
            ) {
                Icon(Icons.Outlined.Terminal, contentDescription = null, modifier = Modifier.size(22.dp), tint = nmInk)
                Spacer(Modifier.size(14.dp))
                Text(
                    text = stringResource(R.string.nm_coding_title),
                    fontSize = 16.sp,
                    fontWeight = FontWeight.Medium,
                    color = nmInk,
                    modifier = Modifier.weight(1f),
                )
                Text(
                    text = codingComputers.toString(),
                    fontSize = 13.sp,
                    color = nmMuted,
                )
            }
        }

        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.padding(start = 26.dp, end = 12.dp, top = 14.dp),
        ) {
            Text(
                text = stringResource(R.string.nm_drawer_side_chats).uppercase(),
                fontSize = 12.sp,
                fontWeight = FontWeight.SemiBold,
                letterSpacing = 1.sp,
                color = nmMuted,
                modifier = Modifier.weight(1f),
            )
            IconButton(onClick = onAllChats) {
                Icon(
                    Icons.Outlined.Archive,
                    contentDescription = stringResource(R.string.nm_drawer_all_chats),
                    tint = nmMuted,
                    modifier = Modifier.size(20.dp),
                )
            }
        }

        if (sideChats.isEmpty()) {
            Column(
                modifier = Modifier.weight(1f).fillMaxWidth().padding(horizontal = 32.dp),
                verticalArrangement = Arrangement.Center,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Icon(
                    Icons.Outlined.Forum,
                    contentDescription = null,
                    tint = nmMuted,
                    modifier = Modifier.size(30.dp),
                )
                Spacer(Modifier.height(10.dp))
                Text(
                    text = stringResource(R.string.nm_drawer_empty_title),
                    fontSize = 17.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = nmInk,
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    text = stringResource(R.string.nm_drawer_empty_body),
                    fontSize = 13.sp,
                    color = nmMuted,
                    textAlign = TextAlign.Center,
                )
            }
        } else {
            LazyColumn(modifier = Modifier.weight(1f).fillMaxWidth(), contentPadding = androidx.compose.foundation.layout.PaddingValues(vertical = 4.dp)) {
                items(sideChats, key = { it.id }) { session ->
                    SideChatRow(
                        session = session,
                        selected = session.id == currentSessionId,
                        selectedFill = nmRowSelected,
                        ink = nmInk,
                        muted = nmMuted,
                        onClick = { onOpenSession(session.id) },
                        onSetMain = { onSetMain(session.id) },
                    )
                }
            }
        }

        // Bottom strip: settings · search · new — Muse's circular buttons round a search pill.
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier
                .fillMaxWidth()
                .padding(start = 12.dp, end = 12.dp, bottom = 10.dp, top = 6.dp),
        ) {
            Box(
                modifier = Modifier
                    .size(44.dp)
                    .clip(CircleShape)
                    .background(nmRowSelected)
                    .clickable(onClick = onSettings),
                contentAlignment = Alignment.Center,
            ) {
                Icon(Icons.Outlined.Settings, contentDescription = stringResource(R.string.nm_drawer_settings), tint = nmInk, modifier = Modifier.size(22.dp))
            }
            if (onSystemFiles != null) {
                Spacer(Modifier.size(8.dp))
                Box(
                    modifier = Modifier
                        .size(44.dp)
                        .clip(CircleShape)
                        .background(nmRowSelected)
                        .clickable(onClick = onSystemFiles),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(Icons.Outlined.Description, contentDescription = stringResource(R.string.nm_sysfiles_title), tint = nmInk, modifier = Modifier.size(22.dp))
                }
            }
            Spacer(Modifier.size(8.dp))
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier
                    .weight(1f)
                    .height(44.dp)
                    .clip(CircleShape)
                    .background(nmRowSelected)
                    .padding(horizontal = 14.dp),
            ) {
                Icon(Icons.Outlined.Search, contentDescription = null, tint = nmMuted, modifier = Modifier.size(18.dp))
                Spacer(Modifier.size(8.dp))
                Box(Modifier.weight(1f)) {
                    if (query.isEmpty()) {
                        Text(
                            stringResource(R.string.nm_drawer_search),
                            color = nmMuted,
                            fontSize = 15.sp,
                        )
                    }
                    BasicTextField(
                        value = query,
                        onValueChange = { query = it },
                        singleLine = true,
                        textStyle = LocalTextStyle.current.copy(color = nmInk, fontSize = 15.sp),
                        cursorBrush = SolidColor(nmInk),
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
            }
            Spacer(Modifier.size(8.dp))
            Box(
                modifier = Modifier
                    .size(44.dp)
                    .clip(CircleShape)
                    .background(nmRowSelected)
                    .clickable(onClick = onNewChat),
                contentAlignment = Alignment.Center,
            ) {
                Icon(Icons.Outlined.Edit, contentDescription = stringResource(R.string.nm_drawer_new_chat), tint = nmInk, modifier = Modifier.size(22.dp))
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun SideChatRow(
    session: ChatSessionEntity,
    selected: Boolean,
    selectedFill: androidx.compose.ui.graphics.Color,
    ink: androidx.compose.ui.graphics.Color,
    muted: androidx.compose.ui.graphics.Color,
    onClick: () -> Unit,
    onSetMain: () -> Unit,
) {
    var menu by remember { mutableStateOf(false) }
    Box {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier
                .padding(horizontal = 12.dp, vertical = 1.dp)
                .fillMaxWidth()
                .clip(RoundedCornerShape(12.dp))
                .background(if (selected) selectedFill else Color.Transparent)
                .combinedClickable(onClick = onClick, onLongClick = { menu = true })
                .padding(horizontal = 14.dp, vertical = 11.dp),
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = session.title?.takeIf { it.isNotBlank() } ?: stringResource(R.string.nm_drawer_untitled),
                    fontSize = 15.sp,
                    color = ink,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Spacer(Modifier.size(10.dp))
            Text(
                text = relativeDay(androidx.compose.ui.platform.LocalContext.current, session.updatedAt),
                fontSize = 12.sp,
                color = muted,
            )
        }
        DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
            DropdownMenuItem(
                text = { Text(stringResource(R.string.nm_drawer_set_main)) },
                onClick = { menu = false; onSetMain() },
            )
        }
    }
}

internal fun relativeDay(context: android.content.Context, ms: Long): String {
    val now = System.currentTimeMillis()
    val diff = now - ms
    return when {
        diff < 60_000L -> context.getString(R.string.nm_time_just_now)
        android.text.format.DateUtils.isToday(ms) -> DateFormat.getTimeInstance(DateFormat.SHORT).format(Date(ms))
        diff < 7L * 24 * 3600_000L -> java.text.SimpleDateFormat("EEE", java.util.Locale.getDefault()).format(Date(ms))
        else -> DateFormat.getDateInstance(DateFormat.SHORT).format(Date(ms))
    }
}
