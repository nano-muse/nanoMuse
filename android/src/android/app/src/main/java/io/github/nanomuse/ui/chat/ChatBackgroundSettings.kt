package io.github.nanomuse.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.openminis.app.R
import com.openminis.app.ui.settings.SettingsChoiceRow
import com.openminis.app.ui.settings.SettingsSection
import com.openminis.app.ui.settings.getAppearancePrefs
import com.openminis.app.ui.theme.ChatColors

@Composable
fun ChatBackgroundSettings() {
    val context = LocalContext.current
    val prefs = remember(context) { getAppearancePrefs(context) }
    val selected by rememberChatBackground()
    SettingsSection(
        header = stringResource(R.string.nm_chat_background_title),
        footer = stringResource(R.string.nm_chat_background_footer),
    ) {
        ChatBackground.entries.forEachIndexed { index, background ->
            SettingsChoiceRow(
                title = stringResource(background.label),
                selected = selected == background,
                onSelect = {
                    prefs.edit().apply {
                        if (background == ChatBackground.DEFAULT) remove(ChatBackground.KEY)
                        else putString(ChatBackground.KEY, background.id)
                    }.apply()
                },
                leading = {
                    Box(
                        Modifier.size(24.dp)
                            .background(background.color(ChatColors), CircleShape)
                            .border(1.dp, ChatColors.separator, CircleShape),
                    )
                },
                showDivider = index < ChatBackground.entries.lastIndex,
            )
        }
    }
}
