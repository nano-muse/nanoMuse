package io.github.nanomuse.ui.models

import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.ChatBubbleOutline
import androidx.compose.material.icons.outlined.CloudQueue
import androidx.compose.material.icons.outlined.Image
import androidx.compose.material.icons.outlined.Movie
import androidx.compose.material.icons.outlined.TouchApp
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.openminis.app.MinisApp
import com.openminis.app.R
import com.openminis.app.ui.settings.SettingsRow
import com.openminis.app.ui.settings.SettingsScaffold
import com.openminis.app.ui.settings.SettingsSection
import com.openminis.app.ui.settings.SettingsSwitchRow
import io.github.nanomuse.cloud.Capabilities
import io.github.nanomuse.cloud.NanoMuseCloud
import io.github.nanomuse.models.ModelSlots
import io.github.nanomuse.models.ModelSlots.Slot
import io.github.nanomuse.ui.home.MuseTones

const val ROUTE_MODELS = "nanomuse/models"
const val ROUTE_MODEL_PICK = "nanomuse/models/pick/{slot}"
fun modelPickRoute(slot: Slot): String = "nanomuse/models/pick/${slot.defaultsKey}"

/** The slot's title (`Chat`, `Operating the screen`, `Making pictures`, `Making clips`). */
fun slotTitle(slot: Slot): Int = when (slot) {
    Slot.CHAT -> R.string.nm_models_chat_title
    Slot.HANDS -> R.string.nm_models_hands_title
    Slot.IMAGE -> R.string.nm_models_image_title
    Slot.VIDEO -> R.string.nm_models_video_title
}

/** The slot's one-line subtitle, what the feature does. */
fun slotSubtitle(slot: Slot): Int = when (slot) {
    Slot.CHAT -> R.string.nm_models_chat_sub
    Slot.HANDS -> R.string.nm_models_hands_sub
    Slot.IMAGE -> R.string.nm_models_image_sub
    Slot.VIDEO -> R.string.nm_models_video_sub
}

private fun slotIcon(slot: Slot): ImageVector = when (slot) {
    Slot.CHAT -> Icons.Outlined.ChatBubbleOutline
    Slot.HANDS -> Icons.Outlined.TouchApp
    Slot.IMAGE -> Icons.Outlined.Image
    Slot.VIDEO -> Icons.Outlined.Movie
}

/**
 * Settings → Models (0.1.41 "Choice"): the four slots — chat, operating the screen, making
 * pictures, making clips — each showing `<provider> · <model>` and opening a picker; a slot
 * nothing can serve shows the one sentence that says which provider would, and *Add a
 * provider*. The page ends with *Add a provider* too. Chat here is the default for new chats
 * (the same `defaultPrimaryGroupId` the upstream Model groups screen edits), so the two agree.
 */
@Composable
fun ModelsScreen(
    onBack: () -> Unit,
    onPick: (Slot) -> Unit,
    onAddProvider: () -> Unit,
    onOpenMedia: () -> Unit,
) {
    val context = LocalContext.current
    val repo = (context.applicationContext as? MinisApp)?.providerRepositoryOrNull
    val config = repo?.config?.collectAsState()?.value
    val changed by ModelSlots.lastChanged.collectAsState()
    var tick by remember { mutableIntStateOf(0) }

    // The hands, image and video choices live in preferences, not in the config flow: re-read
    // when the picker pops back.
    val owner = LocalLifecycleOwner.current
    DisposableEffect(owner) {
        val obs = LifecycleEventObserver { _, e -> if (e == Lifecycle.Event.ON_RESUME) tick++ }
        owner.lifecycle.addObserver(obs)
        onDispose { owner.lifecycle.removeObserver(obs) }
    }

    SettingsScaffold(title = stringResource(R.string.nm_models_title), onBack = onBack) {
        Text(
            text = stringResource(R.string.nm_models_intro),
            fontSize = 14.sp,
            lineHeight = 20.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 16.dp).padding(top = 12.dp),
        )
        // Signed in: the one switch for the Cloud as a model source. It is upstream's
        // `isEnabled` on the Cloud provider instance, so the automatic order, the pickers, the
        // hands and the side calls all read the same flag; the sign-in stays (sync, the hub).
        val cloudId = remember(config) { NanoMuseCloud.instance(context)?.id }
        val cloudInstance = config?.instances?.firstOrNull { it.id == cloudId }
        if (cloudInstance != null && remember(config) { NanoMuseCloud.isSignedIn(context) }) {
            val cloudOn = cloudInstance.isEnabled
            // Off is refused while the chat model is still the account's and no model of the
            // person's own could take it: the switch stays on and this one sentence says why.
            var refused by remember { mutableStateOf(false) }
            SettingsSection(footer = stringResource(if (cloudOn) R.string.nm_models_cloud_on_sub else R.string.nm_models_cloud_off_sub)) {
                SettingsSwitchRow(
                    title = stringResource(R.string.nm_models_cloud_switch),
                    checked = cloudOn,
                    onCheckedChange = { refused = !NanoMuseCloud.setModelsOn(context, it) },
                    icon = Icons.Outlined.CloudQueue,
                    iconColor = if (cloudOn) MuseTones.action else MaterialTheme.colorScheme.onSurfaceVariant,
                    showDivider = false,
                )
                if (refused) {
                    Text(
                        text = stringResource(R.string.nm_models_cloud_off_refused),
                        fontSize = 13.sp,
                        lineHeight = 18.sp,
                        color = MaterialTheme.colorScheme.error,
                        modifier = Modifier.padding(horizontal = 16.dp).padding(bottom = 12.dp),
                    )
                }
            }
        }
        Slot.values().forEach { slot ->
            val value = remember(config, tick, changed) { ModelSlots.current(context, slot) }
            val hasOptions = remember(config, tick) { ModelSlots.groups(context, slot).isNotEmpty() }
            val videoOff = remember(tick, changed) { slot == Slot.VIDEO && ModelSlots.videoOff(context) }
            val footer = buildString {
                append(stringResource(slotSubtitle(slot)))
                if (slot == Slot.CHAT && changed == Slot.CHAT) append(" ").append(stringResource(R.string.nm_models_chat_applies))
            }
            SettingsSection(footer = footer) {
                SettingsRow(
                    title = stringResource(slotTitle(slot)),
                    subtitle = when {
                        value != null -> value.label(context)
                        videoOff -> stringResource(R.string.nm_media_video_off_option)
                        hasOptions -> stringResource(R.string.nm_media_not_set)
                        else -> Capabilities.unavailableLine(context, slot.capability)
                    },
                    icon = slotIcon(slot),
                    iconColor = if (value != null) MuseTones.action else MaterialTheme.colorScheme.onSurfaceVariant,
                    onClick = if (hasOptions || videoOff) ({ onPick(slot) }) else null,
                    showDivider = !hasOptions,
                    minHeight = 72.dp,
                )
                if (!hasOptions) {
                    SettingsRow(
                        title = stringResource(R.string.nm_media_add_provider),
                        titleColor = MuseTones.action,
                        onClick = onAddProvider,
                        showChevron = false,
                        showDivider = false,
                    )
                }
            }
        }
        SettingsSection(footer = stringResource(R.string.nm_models_media_more_sub)) {
            SettingsRow(
                title = stringResource(R.string.nm_media_add_provider),
                onClick = onAddProvider,
                showChevron = true,
            )
            SettingsRow(
                title = stringResource(R.string.nm_models_media_more),
                onClick = onOpenMedia,
                showDivider = false,
            )
        }
        Spacer(Modifier.height(32.dp))
    }
}

/** The small `Recommended` mark before a picker row. */
@Composable
fun RecommendedMark() {
    Text(
        text = stringResource(R.string.nm_media_recommended),
        fontSize = 11.sp,
        fontWeight = FontWeight.Medium,
        color = MuseTones.action,
        modifier = Modifier.padding(end = 8.dp),
    )
}
