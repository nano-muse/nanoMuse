package io.github.nanomuse.hands

import org.junit.Assert.*
import org.junit.Test

class HandsInspectionTest {
    @Test fun pauseAndResumeDiscardTheInflightPlan() {
        val control = HandsInspection()
        val first = control.observation()!!
        assertTrue(control.current(first))
        assertTrue(control.toggle())
        assertNull(control.observation())
        assertFalse(control.current(first))
        assertFalse(control.toggle())
        assertFalse(control.current(first))
        assertTrue(control.current(control.observation()!!))
    }
}
