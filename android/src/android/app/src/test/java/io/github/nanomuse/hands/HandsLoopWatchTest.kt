package io.github.nanomuse.hands

import io.github.nanomuse.hands.HandsLoopWatch.Verdict
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** The hands stop going round in circles: a note at the third identical step, a stop at the sixth. */
class HandsLoopWatchTest {
    private fun screen(seed: Int): IntArray = IntArray(240) { (it * 7 + seed) % 256 }
    private fun tap(x: Int, y: Int, label: String = "OK") = HandsAction.Click(HandsAction.Point(x, y), label)

    @Test fun `the same tap on the same screen notes at three and stops at six`() {
        val w = HandsLoopWatch()
        val s = screen(0)
        assertEquals(Verdict.FINE, w.step(s, tap(500, 500)))
        assertEquals(Verdict.FINE, w.step(s, tap(500, 500)))
        assertEquals(Verdict.NOTE, w.step(s, tap(510, 495))) // a few pixels apart is the same tap
        assertEquals(Verdict.NOTE, w.step(s, tap(500, 500)))
        assertEquals(Verdict.NOTE, w.step(s, tap(500, 500)))
        assertEquals(Verdict.STOP, w.step(s, tap(500, 500)))
        assertEquals(6, w.streak)
    }

    @Test fun `a screen that changed breaks the streak`() {
        val w = HandsLoopWatch()
        w.step(screen(0), tap(500, 500))
        w.step(screen(0), tap(500, 500))
        assertEquals(Verdict.FINE, w.step(screen(90), tap(500, 500)))
        assertEquals(1, w.streak)
    }

    @Test fun `another action breaks the streak`() {
        val w = HandsLoopWatch()
        val s = screen(0)
        w.step(s, tap(500, 500))
        w.step(s, tap(500, 500))
        assertEquals(Verdict.FINE, w.step(s, HandsAction.Scroll("down")))
        assertEquals(Verdict.FINE, w.step(s, tap(500, 500)))
        assertEquals(1, w.streak)
    }

    @Test fun `a tap far away is not the same tap`() {
        val w = HandsLoopWatch()
        val s = screen(0)
        w.step(s, tap(500, 500))
        w.step(s, tap(500, 500))
        assertEquals(Verdict.FINE, w.step(s, tap(600, 500)))
    }

    @Test fun `scrolling the same way at the end of a list counts, typing the same text counts`() {
        val w = HandsLoopWatch()
        val s = screen(0)
        repeat(2) { w.step(s, HandsAction.Scroll("down")) }
        assertEquals(Verdict.NOTE, w.step(s, HandsAction.Scroll("down")))
        val w2 = HandsLoopWatch()
        repeat(2) { w2.step(s, HandsAction.InputText("hello", "search")) }
        assertEquals(Verdict.NOTE, w2.step(s, HandsAction.InputText("hello", "search")))
    }

    @Test fun `taking over, asking and finishing never count`() {
        val w = HandsLoopWatch()
        val s = screen(0)
        repeat(8) { assertEquals(Verdict.FINE, w.step(s, HandsAction.TakeOver("login"))) }
        repeat(8) { assertEquals(Verdict.FINE, w.step(s, HandsAction.AskUser("which one?"))) }
        assertEquals(Verdict.FINE, w.step(s, HandsAction.Status(true, "done")))
    }

    @Test fun `the clock in the status bar does not make a new screen`() {
        val a = screen(0)
        val b = a.copyOf().also { it[3] = 255 - it[3]; it[4] = 255 - it[4] } // two cells of 240
        assertTrue(HandsLoopWatch.sameScreen(a, b))
        val c = a.copyOf().also { for (i in 0 until 12) it[i] = 255 - it[i] } // a whole row
        assertFalse(HandsLoopWatch.sameScreen(a, c))
        assertFalse(HandsLoopWatch.sameScreen(a, IntArray(100))) // another shape: a rotation
    }

    @Test fun `the reason names the action`() {
        assertTrue(HandsLoopWatch.stopReason(tap(1, 1, "Next")).contains("tap “Next”"))
    }
}
