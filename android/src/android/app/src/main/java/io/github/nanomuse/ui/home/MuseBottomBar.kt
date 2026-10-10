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
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
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
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import dev.chrisbanes.haze.HazeState
import dev.chrisbanes.haze.HazeStyle
import dev.chrisbanes.haze.hazeEffect

/**
 * nanoMuse's bottom bar: a floating frosted-glass pill, five glyphs, icons only. The pill blurs
 * whatever is behind it (Haze, in the Pixel taskbar's manner) and carries a hairline edge. The
 * current tab shows a filled glyph on a soft indicator pill that springs in; the others are
 * outlined. No labels — the fill and the indicator are the state.
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
    Box(
        modifier = modifier
            .fillMaxWidth()
            .windowInsetsPadding(WindowInsets.navigationBars)
            .padding(bottom = 12.dp),
        contentAlignment = Alignment.Center,
    ) {
        Row(
            modifier = Modifier
                .hazeEffect(state = hazeState) {
                    style = HazeStyle(
                        backgroundColor = barBackground,
                        blurRadius = 28.dp,
                        noiseFactor = 0.08f,
                        // tints named explicitly: HazeStyle has a twin constructor taking tint: HazeTint?
                        tints = emptyList(),
                    )
                }
                .clip(CircleShape)
                .border(
                    width = 1.dp,
                    color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.5f),
                    shape = CircleShape,
                )
                .padding(horizontal = 14.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(2.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            HomeTab.entries.forEach { tab ->
                val isSelected = tab == selected
                val indicator by animateColorAsState(
                    targetValue = if (isSelected) MaterialTheme.colorScheme.primaryContainer
                    else Color.Transparent,
                    animationSpec = spring(stiffness = Spring.StiffnessMediumLow),
                    label = "nmTabIndicator",
                )
                Box(
                    modifier = Modifier
                        .size(width = 60.dp, height = 46.dp)
                        .clip(CircleShape)
                        .background(indicator)
                        .clickable(
                            interactionSource = remember { MutableInteractionSource() },
                            indication = null,
                            onClick = { onSelect(tab) },
                        ),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        imageVector = if (isSelected) tab.selectedIcon else tab.icon,
                        contentDescription = stringResource(tab.label),
                        tint = if (isSelected) MaterialTheme.colorScheme.onPrimaryContainer
                        else MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.size(26.dp),
                    )
                }
            }
        }
    }
}
