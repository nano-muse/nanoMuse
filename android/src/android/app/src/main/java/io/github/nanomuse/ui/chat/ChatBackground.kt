package io.github.nanomuse.ui.chat

import android.content.SharedPreferences
import androidx.annotation.StringRes
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.State
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import com.openminis.app.R
import com.openminis.app.ui.settings.getAppearancePrefs
import com.openminis.app.ui.theme.ChatColors
import com.openminis.app.ui.theme.ChatPalette

/** A local chat canvas choice. Text, bubbles and the app palette keep their theme colors. */
enum class ChatBackground(
    val id: String,
    @StringRes val label: Int,
    private val light: Color,
    private val dark: Color,
) {
    DEFAULT("default", R.string.nm_chat_background_default, Color.Unspecified, Color.Unspecified),
    WARM("warm", R.string.nm_chat_background_warm, Color(0xFFFFF7ED), Color(0xFF18120D)),
    BLUE("blue", R.string.nm_chat_background_blue, Color(0xFFF0F6FF), Color(0xFF0D141F)),
    GREEN("green", R.string.nm_chat_background_green, Color(0xFFF0F8F2), Color(0xFF0D1912)),
    PURPLE("purple", R.string.nm_chat_background_purple, Color(0xFFF7F2FC), Color(0xFF171020));

    fun color(palette: ChatPalette): Color = when {
        this == DEFAULT -> palette.background
        palette.isDark -> dark
        else -> light
    }

    companion object {
        const val KEY = "nm.chat_background"

        fun byId(id: String?): ChatBackground = entries.firstOrNull { it.id == id } ?: DEFAULT
    }
}

@Composable
fun rememberChatBackground(): State<ChatBackground> {
    val context = LocalContext.current
    val prefs = remember(context) { getAppearancePrefs(context) }
    val state = remember(prefs) { mutableStateOf(ChatBackground.byId(prefs.getString(ChatBackground.KEY, null))) }
    DisposableEffect(prefs) {
        val listener = SharedPreferences.OnSharedPreferenceChangeListener { updated, key ->
            if (key == null || key == ChatBackground.KEY) {
                state.value = ChatBackground.byId(updated.getString(ChatBackground.KEY, null))
            }
        }
        prefs.registerOnSharedPreferenceChangeListener(listener)
        state.value = ChatBackground.byId(prefs.getString(ChatBackground.KEY, null))
        onDispose { prefs.unregisterOnSharedPreferenceChangeListener(listener) }
    }
    return state
}

@Composable
fun rememberChatBackgroundColor(): Color {
    val background by rememberChatBackground()
    return background.color(ChatColors)
}
