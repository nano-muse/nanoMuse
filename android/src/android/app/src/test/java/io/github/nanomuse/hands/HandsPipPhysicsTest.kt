package io.github.nanomuse.hands

// Adapted from Mika PipPhysicsTest.kt, Copyright 2026 wangzan101, Apache-2.0.
// nanoMuse modification: tests the system-overlay bounds used by Hands.

import org.junit.Assert.assertEquals
import org.junit.Test

class HandsPipPhysicsTest {
    private val bounds = HandsPipPhysics.Bounds(
        width = 1080f,
        height = 2400f,
        pipWidth = 360f,
        pipHeight = 640f,
        margin = 30f,
        top = 60f,
        bottom = 40f,
    )

    @Test
    fun previewCornersStayInsideSystemBars() {
        assertEquals(30f to 90f, bounds.position(HandsPipPhysics.Corner.TOP_START))
        assertEquals(690f to 1690f, bounds.position(HandsPipPhysics.Corner.BOTTOM_END))
        assertEquals(30f to 90f, bounds.clamp(-100f, -100f))
        assertEquals(690f to 1690f, bounds.clamp(2000f, 3000f))
    }

    @Test
    fun releaseVelocityCanChooseTheOppositeCorner() {
        assertEquals(
            HandsPipPhysics.Corner.BOTTOM_END,
            HandsPipPhysics.snapCorner(30f, 90f, 5000f, 5000f, bounds),
        )
        assertEquals(
            HandsPipPhysics.Corner.TOP_START,
            HandsPipPhysics.snapCorner(690f, 1690f, -5000f, -5000f, bounds),
        )
    }
}
