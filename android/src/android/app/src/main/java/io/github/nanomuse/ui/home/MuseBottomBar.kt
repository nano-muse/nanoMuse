package io.github.nanomuse.ui.home

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.spring
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import dev.chrisbanes.haze.HazeState
import dev.chrisbanes.haze.HazeStyle
import dev.chrisbanes.haze.hazeEffect
import io.github.nanomuse.ui.chat.NM_CHAT_COMPOSER_BOTTOM_GAP

/**
 * nanoMuse's bottom bar: a floating frosted-glass pill, five glyphs, icons only. The pill blurs
 * whatever is behind it (Haze, in the Pixel taskbar's manner) and carries a hairline edge. The
 * current tab shows a filled glyph on a soft indicator pill that springs in; the others are
 * outlined. No labels: the fill and the indicator are the state.
 */
@Composable
fun MuseBottomBar(
    selected: HomeTab,
    onSelect: (HomeTab) -> Unit,
    hazeState: HazeState,
    modifier: Modifier = Modifier,
) {
    // Hoisted out of the hazeEffect block: Haze 1.x's block is not a @Composable scope,
    // so MaterialTheme lookups cannot happen inside it.
    val barBackground = MaterialTheme.colorScheme.surfaceContainer.copy(alpha = 0.55f)
    // The selected tab: a white disc with a black glyph in the dark theme,
    // inverted in light. Follows the chat background, not the system setting,
    // since the app has its own theme override.
    val nmDark = MaterialTheme.colorScheme.background.luminance() < 0.5f
    val chatBackground by io.github.nanomuse.ui.chat.rememberChatBackground()
    val chatCanvas = chatBackground.color(com.openminis.app.ui.theme.ChatColors)
    val nmSelectedBg = if (nmDark) Color.White else Color.Black
    val nmSelectedFg = if (nmDark) Color.Black else Color.White
    val window = LocalConfiguration.current
    val surroundExtent = maxOf(window.screenWidthDp, window.screenHeightDp).dp
    Box(
        modifier = modifier
            .fillMaxWidth()
            .windowInsetsPadding(WindowInsets.navigationBars)
            .padding(bottom = 12.dp)
            // The pill is as wide as the composer above it: the same 16 dp
            // margins ChatScreen gives the home composer, so the two capsules
            // stack with one edge. A wide screen caps it and centres it.
            .padding(horizontal = PILL_INSET),
        contentAlignment = Alignment.Center,
    ) {
        Row(
            modifier = Modifier
                // widthIn before fillMaxWidth: the other way round the fill
                // pins the constraints and the cap has nothing to shrink.
                .widthIn(max = PILL_MAX_WIDTH)
                .fillMaxWidth()
                // Keep the chat surround outside the glass and its blur source.
                .then(
                    if (selected == HomeTab.CHAT && (nmDark || chatBackground != io.github.nanomuse.ui.chat.ChatBackground.DEFAULT)) {
                        Modifier.chatNavPillSurround(
                            color = chatCanvas,
                            extent = surroundExtent,
                            topGap = NM_CHAT_COMPOSER_BOTTOM_GAP,
                        )
                    } else Modifier,
                )
                // Clip first: it must wrap the haze drawing, otherwise the
                // blurred rect paints unclipped and the pill's ends look square.
                .clip(CircleShape)
                .hazeEffect(state = hazeState) {
                    style = HazeStyle(
                        backgroundColor = barBackground,
                        blurRadius = 28.dp,
                        noiseFactor = 0.08f,
                        // tints named explicitly: HazeStyle has a twin constructor taking tint: HazeTint?
                        tints = emptyList(),
                    )
                }
                .border(
                    width = 1.dp,
                    color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f),
                    shape = CircleShape,
                )
                .padding(horizontal = 14.dp, vertical = PILL_PADDING_V),
            horizontalArrangement = Arrangement.spacedBy(2.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            HomeTab.entries.forEach { tab ->
                val isSelected = tab == selected
                val indicator by animateColorAsState(
                    targetValue = if (isSelected) nmSelectedBg
                    else Color.Transparent,
                    animationSpec = spring(stiffness = Spring.StiffnessMediumLow),
                    label = "nmTabIndicator",
                )
                // Five slots share the pill's width; the indicator disc keeps
                // its 60 x 46 inside the slot (narrower only when the slot is).
                Box(
                    modifier = Modifier
                        .weight(1f)
                        .height(TAB_HEIGHT)
                        // a tab for TalkBack, with its state: the glyph alone would read as a
                        // plain button and the current one as any other
                        .semantics { role = Role.Tab; this.selected = isSelected }
                        .clickable(
                            interactionSource = remember { MutableInteractionSource() },
                            indication = null,
                            onClick = { onSelect(tab) },
                        ),
                    contentAlignment = Alignment.Center,
                ) {
                    Box(
                        modifier = Modifier
                            .widthIn(max = TAB_WIDTH)
                            .fillMaxWidth()
                            .height(TAB_HEIGHT)
                            .clip(CircleShape)
                            .background(indicator),
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(
                            imageVector = if (isSelected) tab.selectedIcon else tab.icon,
                            contentDescription = stringResource(tab.label),
                            tint = if (isSelected) nmSelectedFg
                            else MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.size(26.dp),
                        )
                    }
                }
            }
        }
    }
}

/** The composer's horizontal margin in the home shell (ChatScreen, `nmPill`). */
private val PILL_INSET = 16.dp

/** Wider screens get a centred pill of this width, not a bar across the window. */
private val PILL_MAX_WIDTH = 420.dp

/** Vertical padding inside the pill; the bar's height follows from it (46 + 2 x 6 = 58). */
private val PILL_PADDING_V = 6.dp

/** The indicator disc behind the selected glyph. */
private val TAB_WIDTH = 60.dp
private val TAB_HEIGHT = 46.dp
