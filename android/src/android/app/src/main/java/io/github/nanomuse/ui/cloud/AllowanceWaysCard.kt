package io.github.nanomuse.ui.cloud

import android.content.Context
import android.content.Intent
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Computer
import androidx.compose.material.icons.outlined.ContentCopy
import androidx.compose.material.icons.outlined.Devices
import androidx.compose.material.icons.outlined.Key
import androidx.compose.material.icons.outlined.Person
import androidx.compose.material.icons.outlined.PersonAdd
import androidx.compose.material.icons.outlined.Share
import androidx.compose.material.icons.outlined.StarOutline
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalClipboard
import io.github.nanomuse.ui.muse.setPlainText
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.openminis.app.R
import io.github.nanomuse.cloud.AllowanceSignal
import io.github.nanomuse.cloud.Capabilities
import io.github.nanomuse.cloud.CatalogueProvider
import io.github.nanomuse.cloud.NanoMuseCloud
import io.github.nanomuse.cloud.OwnKeyPresets
import io.github.nanomuse.cloud.ProviderCatalogue
import io.github.nanomuse.cloud.Region
import io.github.nanomuse.cloud.Ways
import io.github.nanomuse.ui.home.MuseTones

/** The public guide for bringing one's own key, when the relay did not name one. */
const val OWN_KEY_DOCS = "https://nanomuse.cn/own-key"

/** The in-app link that opens "add a provider" pre-filled for Alibaba Cloud Bailian. */
val OWN_KEY_DEEP_LINK: String = OwnKeyPresets.deepLink(OwnKeyPresets.BAILIAN)

/** The same, for OpenRouter — the form opens on "Sign in with OpenRouter" (OpenRouterOAuthManager). */
val OWN_KEY_OPENROUTER_DEEP_LINK: String = OwnKeyPresets.deepLink(OwnKeyPresets.OPENROUTER, signIn = true)

/** How many vendors the key list shows before "More providers". */
private const val SHOWN_FIRST = 3

/**
 * The ways on when the free allowance is spent (or nearly, or paused by the operator),
 * contract C11: one's own key — the vendors as the relay lists them for the region
 * (`spend.guidance`, [Ways.resolve]; the bundled [ProviderCatalogue] only when the relay sent
 * none), the region's first (Alibaba Cloud Bailian for mainland China, where it signs up
 * accounts; OpenRouter and OpenAI elsewhere), each saying what it covers (chat · screen ·
 * pictures · clips), *Add* opening the pre-filled provider form and *Get a key* the vendor's
 * key page; a subscription one already pays for (ChatGPT, Claude, Kimi, OpenRouter), *Sign in*
 * going through upstream's OAuth managers from the same form; and an invitation (both sides
 * gain). No vendor is recommended; the text says what each one covers. Shown on the account
 * page whenever the pool is spent or past 80 %, and in the chat when a turn was refused for
 * it. [exhausted] false = the heads-up wording; `info.paused` = the operator's switch, not use.
 */
@Composable
fun AllowanceWaysCard(
    info: AllowanceSignal.Exhausted,
    exhausted: Boolean,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val clipboard = LocalClipboard.current
    val account = remember { NanoMuseCloud.account(context) }
    val inviteBonus = info.inviteBonusCny.takeIf { it > 0 } ?: account?.inviteBonusCny?.takeIf { it > 0 } ?: 5.0
    val inviteeBonus = info.inviteeBonusCny.takeIf { it > 0 } ?: account?.inviteeBonusCny?.takeIf { it > 0 } ?: inviteBonus
    var copied by remember { mutableStateOf(false) }
    LaunchedEffect(copied) { if (copied) { kotlinx.coroutines.delay(1500); copied = false } }
    // The star row shows when the policy makes this moment due (StarPrompt: once, past the
    // cooldown, under the cap) and goes once the person has been to GitHub from any ask.
    val starAsk = remember(exhausted) {
        val ask = io.github.nanomuse.community.StarPrompt.Ask(io.github.nanomuse.community.StarPrompt.Moment.EXHAUSTED)
        when {
            !exhausted -> false
            io.github.nanomuse.community.StarPrompt.shownThisRun(ask) -> true // the card scrolled back into view
            io.github.nanomuse.community.StarPrompt.due(context, ask) -> { io.github.nanomuse.community.StarPrompt.markShown(context, ask); true }
            else -> false
        }
    }
    var starred by remember { mutableStateOf(io.github.nanomuse.community.StarPrompt.starred(context)) }
    val link = info.inviteUrl.ifBlank { account?.inviteUrl.orEmpty() }.ifBlank {
        "https://nanomuse.cn/web/?invite=" + account?.inviteCode.orEmpty()
    }
    // the ways as the relay lists them (`guidance`, contract C11) first — the one sent with the
    // refusal, else the one kept from /v1/me — and the bundled catalogue only when it sent none
    val mainland = remember { Region.mainland(context) }
    val chinese = remember { ProviderCatalogue.chinese(context) }
    val ways = remember(info.guidance, mainland) {
        Ways.resolve(info.guidance ?: NanoMuseCloud.guidance(context), ProviderCatalogue.load(context), mainland, chinese)
    }
    val guideUrl = info.ownKeyDocs.ifBlank { account?.ownKeyDocs.orEmpty() }.ifBlank { ways.docs }.ifBlank { OWN_KEY_DOCS }
    val vendors = ways.vendors
    val signIns = ways.signIns
    val locals = ways.locals
    val signedIn = remember { NanoMuseCloud.isSignedIn(context) }
    var more by remember { mutableStateOf(false) }

    Surface(
        shape = RoundedCornerShape(20.dp),
        color = MuseTones.surface,
        border = BorderStroke(1.dp, MuseTones.hairline),
        modifier = modifier.fillMaxWidth().widthIn(max = 400.dp),
    ) {
        Column(Modifier.padding(14.dp)) {
            Text(
                text = when {
                    info.paused -> stringResource(R.string.nm_ways_title_paused)
                    info.dailyCap -> stringResource(R.string.nm_ways_title_day)
                    exhausted -> stringResource(R.string.nm_ways_title_out)
                    else -> stringResource(R.string.nm_ways_title_warn, money(info.leftCny), money(info.grantCny))
                },
                fontSize = 15.sp,
                fontWeight = FontWeight.SemiBold,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Text(
                text = stringResource(
                    when {
                        info.paused -> R.string.nm_ways_paused_sub
                        info.dailyCap -> R.string.nm_ways_day_sub
                        else -> R.string.nm_ways_sub
                    },
                ),
                fontSize = 13.sp,
                lineHeight = 18.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 2.dp),
            )
            Spacer(Modifier.height(10.dp))

            // ① one's own key — the region's vendor first, then the rest, each with what it covers
            val first = vendors.firstOrNull()
            Way(
                Icons.Outlined.Key,
                MuseTones.action,
                stringResource(R.string.nm_ways_key_title),
                stringResource(if (mainland) R.string.nm_ways_region_cn else R.string.nm_ways_region_global),
            ) {
                if (first != null) {
                    Button(
                        onClick = { openPreset(context, first.id) },
                        shape = CircleShape,
                        contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 14.dp, vertical = 6.dp),
                        colors = ButtonDefaults.buttonColors(containerColor = MuseTones.action, contentColor = Color.White),
                    ) {
                        Text(stringResource(R.string.nm_ways_add_named, first.displayName(chinese)), fontSize = 13.sp, fontWeight = FontWeight.Medium)
                    }
                    Spacer(Modifier.width(6.dp))
                    TextButton(onClick = { openUrl(context, first.keyUrl(mainland)) }) {
                        Text(stringResource(R.string.nm_ways_get_key), fontSize = 13.sp, color = MuseTones.action)
                    }
                }
                TextButton(onClick = { openUrl(context, guideUrl) }) { Text(stringResource(R.string.nm_ways_key_guide), fontSize = 13.sp, color = MuseTones.action) }
            }
            val listed = if (more) vendors else vendors.take(SHOWN_FIRST)
            listed.forEach { v -> VendorRow(v, covers = Capabilities.covers(context, v.capabilities), chinese = chinese, mainland = mainland, signIn = false) }
            if (vendors.size > SHOWN_FIRST) {
                Text(
                    stringResource(if (more) R.string.nm_ways_less else R.string.nm_ways_more),
                    fontSize = 13.sp,
                    color = MuseTones.action,
                    fontWeight = FontWeight.Medium,
                    modifier = Modifier.clickable { more = !more }.padding(start = 28.dp, top = 6.dp, bottom = 4.dp, end = 8.dp),
                )
            }

            // ② a subscription one already pays for — the vendor's sign-in, through the same form
            if (signIns.isNotEmpty()) {
                Way(Icons.Outlined.Person, Color(0xFF2E9E6B), stringResource(R.string.nm_ways_sub_title), stringResource(R.string.nm_ways_sub_body)) {}
                signIns.forEach { s ->
                    VendorRow(
                        s.vendor,
                        covers = Capabilities.covers(context, s.covers),
                        chinese = chinese,
                        mainland = mainland,
                        signIn = true,
                        brand = s.name,
                        // the honest line about the ChatGPT sign-in: the relay's when it sent one, else ours
                        note = if (s.auth == ProviderCatalogue.AUTH_CHATGPT) ways.chatgptCaveat.ifBlank { stringResource(R.string.nm_ways_chatgpt_note) } else null,
                    )
                }
            }

            // ③ a model of one's own — the catalogue's local servers, on a computer the person owns
            if (locals.isNotEmpty()) {
                Way(
                    Icons.Outlined.Computer,
                    Color(0xFF5B8DEF),
                    stringResource(R.string.nm_ways_local_title),
                    stringResource(R.string.nm_ways_local_body, locals.joinToString(", ") { it.displayName(chinese) }),
                ) {
                    locals.forEach { v ->
                        TextButton(onClick = { openPreset(context, v.id) }, contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 8.dp)) {
                            Text(stringResource(R.string.nm_ways_add_named, v.displayName(chinese)), fontSize = 13.sp, color = MuseTones.action)
                        }
                    }
                }
            }

            // ④ the person's computer, when the account has one: the turn runs there
            if (signedIn) {
                Way(Icons.Outlined.Devices, Color(0xFF2E9E6B), stringResource(R.string.nm_ways_computer_title), stringResource(R.string.nm_ways_computer_body)) {
                    TextButton(onClick = { com.openminis.app.ui.chat.ChatLinkResolver.dispatchDeepLink(context, "minis://settings/devices") }) {
                        Text(stringResource(R.string.nm_ways_devices), fontSize = 13.sp, color = MuseTones.action)
                    }
                }
            }

            // ⑤ an invitation: both sides gain
            Way(Icons.Outlined.PersonAdd, Color(0xFF7C5CFF), stringResource(R.string.nm_ways_invite_title, money(inviteBonus), money(inviteeBonus)), null) {
                TextButton(onClick = {
                    val text = context.getString(R.string.nm_cloud_invite_share_text, account?.inviteCode.orEmpty(), link)
                    val send = Intent(Intent.ACTION_SEND).apply { type = "text/plain"; putExtra(Intent.EXTRA_TEXT, text) }
                    runCatching {
                        context.startActivity(Intent.createChooser(send, context.getString(R.string.nm_cloud_invite_share)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                    }
                }) {
                    Icon(Icons.Outlined.Share, contentDescription = null, modifier = Modifier.size(15.dp), tint = MuseTones.action)
                    Spacer(Modifier.width(5.dp))
                    Text(stringResource(R.string.nm_ways_invite_share), fontSize = 13.sp, color = MuseTones.action)
                }
                TextButton(onClick = { clipboard.setPlainText("nanoMuse", link); copied = true }) {
                    Icon(Icons.Outlined.ContentCopy, contentDescription = null, modifier = Modifier.size(15.dp), tint = MuseTones.action)
                    Spacer(Modifier.width(5.dp))
                    Text(stringResource(if (copied) R.string.nm_cloud_invite_copied else R.string.nm_ways_invite_copy), fontSize = 13.sp, color = MuseTones.action)
                }
            }

            // ⑥ a star — asked only when the pool is spent, and only until the person went
            if (starAsk && !starred) {
                Way(Icons.Outlined.StarOutline, Color(0xFFF5A623), remember { io.github.nanomuse.community.StarPrompt.text(context, io.github.nanomuse.community.StarPrompt.Ask(io.github.nanomuse.community.StarPrompt.Moment.EXHAUSTED)) }, null) {
                    TextButton(onClick = { io.github.nanomuse.community.StarPrompt.open(context); starred = true }) {
                        Icon(Icons.Outlined.StarOutline, contentDescription = null, modifier = Modifier.size(15.dp), tint = MuseTones.action)
                        Spacer(Modifier.width(5.dp))
                        Text(stringResource(R.string.nm_star_action), fontSize = 13.sp, color = MuseTones.action)
                    }
                    TextButton(onClick = { io.github.nanomuse.community.StarPrompt.markStarred(context); starred = true }) {
                        Text(stringResource(R.string.nm_star_done), fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        }
    }
}

/** The pre-filled provider form for a catalogue vendor; with [signIn], open on its sign-in. */
private fun openPreset(context: Context, id: String, signIn: Boolean = false) {
    com.openminis.app.ui.chat.ChatLinkResolver.dispatchDeepLink(context, OwnKeyPresets.deepLink(id, signIn))
}

private fun openUrl(context: Context, url: String) {
    if (url.isBlank()) return
    runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, android.net.Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
}

/**
 * One vendor: its name, what it covers, and the way in — *Add* (the pre-filled form) and
 * *Get a key* (the vendor's key page), or *Sign in* for a plan. [note] under the row is the
 * honest line about a sign-in whose access is the vendor's to keep.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun VendorRow(v: CatalogueProvider, covers: String, chinese: Boolean, mainland: Boolean, signIn: Boolean, brand: String? = null, note: String? = null) {
    val context = LocalContext.current
    val brand = brand ?: if (signIn) Ways.planName(v.signIn.orEmpty(), v, chinese) else v.displayName(chinese)
    Row(Modifier.fillMaxWidth().padding(start = 28.dp, top = 4.dp, bottom = 2.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(brand, fontSize = 13.sp, fontWeight = FontWeight.Medium, lineHeight = 17.sp, color = MaterialTheme.colorScheme.onSurface)
            Text(covers, fontSize = 12.sp, lineHeight = 16.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        FlowRow(horizontalArrangement = Arrangement.End, verticalArrangement = Arrangement.Center) {
            if (signIn) {
                TextButton(onClick = { openPreset(context, v.id, signIn = true) }, contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 8.dp)) {
                    Text(stringResource(R.string.nm_ways_sign_in), fontSize = 13.sp, color = MuseTones.action)
                }
            } else {
                TextButton(onClick = { openPreset(context, v.id) }, contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 8.dp)) {
                    Text(stringResource(R.string.nm_ways_add), fontSize = 13.sp, color = MuseTones.action)
                }
                if (v.keyUrl(mainland).isNotBlank()) {
                    TextButton(onClick = { openUrl(context, v.keyUrl(mainland)) }, contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 8.dp)) {
                        Text(stringResource(R.string.nm_ways_get_key), fontSize = 13.sp, color = MuseTones.action)
                    }
                }
            }
        }
    }
    if (note != null) {
        Text(
            note,
            fontSize = 12.sp,
            lineHeight = 16.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(start = 28.dp, end = 8.dp, bottom = 4.dp),
        )
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Way(icon: ImageVector, tint: Color, title: String, body: String?, actions: @Composable () -> Unit) {
    Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.Top) {
        Icon(icon, contentDescription = null, tint = tint, modifier = Modifier.padding(top = 2.dp).size(18.dp))
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            Text(title, fontSize = 14.sp, fontWeight = FontWeight.Medium, lineHeight = 19.sp, color = MaterialTheme.colorScheme.onSurface)
            if (body != null) {
                Text(body, fontSize = 12.sp, lineHeight = 17.sp, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 2.dp))
            }
            // three actions do not always fit one line (a button, the key page, the guide)
            FlowRow(verticalArrangement = Arrangement.Center, modifier = Modifier.padding(top = 4.dp)) { actions() }
        }
    }
}
