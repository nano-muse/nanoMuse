package io.github.nanomuse.ui.chat

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Block
import androidx.compose.material.icons.outlined.CloudOff
import androidx.compose.material.icons.outlined.HourglassEmpty
import androidx.compose.material.icons.outlined.PauseCircle
import androidx.compose.material.icons.outlined.UnfoldLess
import androidx.compose.material.icons.outlined.VpnKey
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.openminis.app.R
import com.openminis.app.ui.chat.ChatLinkResolver
import io.github.nanomuse.cloud.NanoMuseCloud
import io.github.nanomuse.cloud.RelayRefusal
import io.github.nanomuse.ui.home.MuseTones

/** The in-app link that starts a new chat (the 413's way on). */
private const val NEW_CHAT_DEEP_LINK = "minis://action/new_chat"

/** The in-app link that opens Settings → nanoMuse Cloud (sign in again, pick another model). */
private const val CLOUD_DEEP_LINK = "minis://settings/cloud"

/**
 * A turn the relay refused (docs/parity.md, item 35): one plain sentence from
 * [NanoMuseCloud.describe] and the button that fits — *New chat* for a message too large,
 * *New chat* (and *Try again*) for a content check that declined the words, *Sign in* for a key
 * the relay no longer takes, *Open Settings* for a model that left the
 * menu or an account the relay does not take, *Try again* for the rest (busy, the provider
 * behind the relay, the operator's switches). The relay's own sentence is shown under ours
 * only where it adds something (a disabled account, an unknown code). The desktop's
 * `refusalCard` is the shape; the allowance ones have their own card (`AllowanceWaysCard`).
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun RelayRefusalCard(refusal: RelayRefusal.Refusal, onRetry: () -> Unit, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val sentence = NanoMuseCloud.describe(context, refusal.toException())
    val (icon, tint) = when (refusal.kind) {
        RelayRefusal.Kind.TOO_LARGE -> Icons.Outlined.UnfoldLess to Color(0xFFE0772C)
        RelayRefusal.Kind.CONTENT_REJECTED -> Icons.Outlined.Block to Color(0xFFE0772C)
        RelayRefusal.Kind.SIGNED_OUT, RelayRefusal.Kind.DISABLED -> Icons.Outlined.VpnKey to MuseTones.action
        RelayRefusal.Kind.BUSY -> Icons.Outlined.HourglassEmpty to Color(0xFF7C5CFF)
        RelayRefusal.Kind.SERVICE_PAUSED, RelayRefusal.Kind.SYNC_PAUSED, RelayRefusal.Kind.HUB_PAUSED -> Icons.Outlined.PauseCircle to Color(0xFF7C5CFF)
        else -> Icons.Outlined.CloudOff to Color(0xFFE0772C)
    }
    // the relay's own sentence is worth a line only where ours is general
    val showRelayText = refusal.message.isNotBlank() && !refusal.message.startsWith("HTTP ") &&
        (refusal.kind == RelayRefusal.Kind.DISABLED || refusal.kind == RelayRefusal.Kind.OTHER) && refusal.message != sentence

    Surface(
        shape = RoundedCornerShape(20.dp),
        color = MuseTones.surface,
        border = BorderStroke(1.dp, MuseTones.hairline),
        modifier = modifier.fillMaxWidth().widthIn(max = 400.dp).padding(top = 4.dp),
    ) {
        Column(Modifier.padding(14.dp)) {
            Row(verticalAlignment = Alignment.Top) {
                Icon(icon, contentDescription = null, tint = tint, modifier = Modifier.padding(top = 2.dp).size(18.dp))
                Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f)) {
                    Text(sentence, fontSize = 14.sp, lineHeight = 19.sp, fontWeight = FontWeight.Medium, color = MaterialTheme.colorScheme.onSurface)
                    if (showRelayText) {
                        Text(
                            stringResource(R.string.nm_refusal_relay_says, refusal.message),
                            fontSize = 13.sp,
                            lineHeight = 18.sp,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(top = 2.dp),
                        )
                    }
                }
            }
            FlowRow(verticalArrangement = Arrangement.Center, modifier = Modifier.padding(top = 10.dp)) {
                when (refusal.kind) {
                    RelayRefusal.Kind.TOO_LARGE -> Primary(stringResource(R.string.nm_refusal_new_chat)) { ChatLinkResolver.dispatchDeepLink(context, NEW_CHAT_DEEP_LINK) }
                    // the words are the matter: a new chat leaves them behind; *Try again* sends the same ones once more, by choice
                    RelayRefusal.Kind.CONTENT_REJECTED -> {
                        Primary(stringResource(R.string.nm_refusal_new_chat)) { ChatLinkResolver.dispatchDeepLink(context, NEW_CHAT_DEEP_LINK) }
                        Secondary(stringResource(R.string.nm_reach_try_again), onRetry)
                    }
                    RelayRefusal.Kind.SIGNED_OUT -> {
                        Primary(stringResource(R.string.nm_refusal_sign_in)) { ChatLinkResolver.dispatchDeepLink(context, CLOUD_DEEP_LINK) }
                        Secondary(stringResource(R.string.nm_reach_try_again), onRetry)
                    }
                    RelayRefusal.Kind.DISABLED, RelayRefusal.Kind.MODEL -> {
                        Primary(stringResource(R.string.nm_refusal_open_settings)) { ChatLinkResolver.dispatchDeepLink(context, CLOUD_DEEP_LINK) }
                    }
                    RelayRefusal.Kind.OTHER -> {
                        Primary(stringResource(R.string.nm_reach_try_again), onRetry)
                        Secondary(stringResource(R.string.nm_refusal_open_settings)) { ChatLinkResolver.dispatchDeepLink(context, CLOUD_DEEP_LINK) }
                    }
                    else -> Primary(stringResource(R.string.nm_reach_try_again), onRetry)
                }
            }
        }
    }
}

@Composable
private fun Primary(label: String, onClick: () -> Unit) {
    Button(
        onClick = onClick,
        shape = CircleShape,
        contentPadding = PaddingValues(horizontal = 14.dp, vertical = 6.dp),
        colors = ButtonDefaults.buttonColors(containerColor = MuseTones.action, contentColor = Color.White),
    ) {
        Text(label, fontSize = 13.sp, fontWeight = FontWeight.Medium)
    }
    Spacer(Modifier.width(6.dp))
}

@Composable
private fun Secondary(label: String, onClick: () -> Unit) {
    TextButton(onClick = onClick) { Text(label, fontSize = 13.sp, color = MuseTones.action) }
}
