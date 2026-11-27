package io.github.nanomuse.hands

// Adapted from Mika PipPhysics.kt, Copyright 2026 wangzan101, Apache-2.0.
// nanoMuse modification: View-overlay bounds and immediate corner snapping only.

import kotlin.math.hypot

/** Pure positioning rules for the draggable background-screen preview. */
internal object HandsPipPhysics {
    enum class Corner { TOP_START, TOP_END, BOTTOM_START, BOTTOM_END }

    data class Bounds(
        val width: Float,
        val height: Float,
        val pipWidth: Float,
        val pipHeight: Float,
        val margin: Float,
        val top: Float,
        val bottom: Float,
    ) {
        private val left: Float get() = margin
        private val right: Float get() = maxOf(left, width - pipWidth - margin)
        private val upper: Float get() = top + margin
        private val lower: Float get() = maxOf(upper, height - pipHeight - bottom - margin)

        fun position(corner: Corner): Pair<Float, Float> = when (corner) {
            Corner.TOP_START -> left to upper
            Corner.TOP_END -> right to upper
            Corner.BOTTOM_START -> left to lower
            Corner.BOTTOM_END -> right to lower
        }

        fun clamp(x: Float, y: Float): Pair<Float, Float> =
            x.coerceIn(left, right) to y.coerceIn(upper, lower)
    }

    fun project(velocity: Float): Float =
        (velocity / 1000f) * DECELERATION / (1f - DECELERATION)

    fun snapCorner(x: Float, y: Float, vx: Float, vy: Float, bounds: Bounds): Corner {
        val projectedX = x + project(vx)
        val projectedY = y + project(vy)
        return Corner.values().minBy { corner ->
            val (targetX, targetY) = bounds.position(corner)
            hypot(targetX - projectedX, targetY - projectedY)
        }
    }

    private const val DECELERATION = 0.998f
}
