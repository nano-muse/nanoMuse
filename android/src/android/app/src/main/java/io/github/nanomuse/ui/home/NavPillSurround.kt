package io.github.nanomuse.ui.home

import androidx.compose.foundation.shape.CircleShape
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawWithCache
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.ClipOp
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Outline
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.clipPath
import androidx.compose.ui.unit.Dp

/**
 * Paints the selected chat canvas outside the pill, including the gap below the chat composer.
 * Attached before the pill's clip/Haze modifiers, this uses its actual outline
 * without covering the glass or becoming part of Haze's scrolling source.
 */
internal fun Modifier.chatNavPillSurround(color: Color, extent: Dp, topGap: Dp): Modifier = drawWithCache {
    val outline = CircleShape.createOutline(size, layoutDirection, this)
    val opening = Path().apply {
        when (outline) {
            is Outline.Rounded -> addRoundRect(outline.roundRect)
            is Outline.Rectangle -> addRect(outline.rect)
            is Outline.Generic -> addPath(outline.path)
        }
    }
    // Cover the shared composer gap above the pill, the side gutters and the
    // lower navigation inset. Match layout's pixel rounding at the upper edge.
    // The window clips the outer extent.
    val extentPx = extent.toPx()
    val topGapPx = topGap.roundToPx().toFloat()
    onDrawWithContent {
        clipPath(opening, clipOp = ClipOp.Difference) {
            drawRect(
                color = color,
                topLeft = Offset(-extentPx, -topGapPx),
                size = Size(size.width + extentPx * 2f, size.height + extentPx + topGapPx),
            )
        }
        drawContent()
    }
}
