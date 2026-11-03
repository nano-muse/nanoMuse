package io.github.nanomuse.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import com.openminis.app.R
import com.openminis.app.service.SessionBadgeStore

@Composable
fun UnreadReplyDot(sessionId: String?, modifier: Modifier = Modifier) = UnreadReplyGroupDot(listOfNotNull(sessionId), modifier)

@Composable
fun UnreadReplyGroupDot(sessionIds: Collection<String>, modifier: Modifier = Modifier) {
    val unread by SessionBadgeStore.unread.collectAsState()
    if (sessionIds.none { it in unread }) return
    val label = stringResource(R.string.nm_reply_unread)
    Box(modifier.size(8.dp).background(MaterialTheme.colorScheme.error, CircleShape)
        .semantics { contentDescription = label })
}
