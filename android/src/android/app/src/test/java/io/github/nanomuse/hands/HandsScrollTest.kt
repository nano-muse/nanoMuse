package io.github.nanomuse.hands

import org.junit.Assert.*
import org.junit.Test

class HandsScrollTest {
    @Test fun defaultScrollPreservesTheExistingGestureOnEvenAndOddScreens() {
        for ((w, h) in listOf(1000 to 2000, 721 to 1583)) {
            val dy = h * 30 / 100
            val down = HandsScroll.gesture("down", "normal", w, h)
            assertEquals(w / 2 to h / 2 + dy / 2 + dy / 4, down.from)
            assertEquals(w / 2 to h / 2 - dy / 2 - dy / 4, down.to)
            val up = HandsScroll.gesture("up", "normal", w, h)
            assertEquals(down.from, up.to)
            assertEquals(down.to, up.from)
        }
    }

    @Test fun largeScrollAddsVerticalReachWhileStayingInsideTheScreen() {
        val down = HandsScroll.gesture("down", "large", 1000, 2000)
        assertEquals(1300, down.from.second - down.to.second)
        assertTrue(down.from.second < 2000 && down.to.second > 0)
        assertEquals(HandsScroll.gesture("left", "normal", 1000, 2000),
            HandsScroll.gesture("left", "large", 1000, 2000))
    }

    @Test fun parserAcceptsOptionalLargeDistanceAndRejectsUnknownValues() {
        val normal = HandsAction.parse("Action: {\"action_type\":\"scroll\",\"direction\":\"down\"}").action
        val large = HandsAction.parse("Action: {\"action_type\":\"scroll\",\"direction\":\"up\",\"distance\":\"large\"}").action
        assertEquals(HandsAction.Scroll("down"), normal)
        assertEquals(HandsAction.Scroll("up", "large"), large)
        assertTrue(runCatching {
            HandsAction.parse("Action: {\"action_type\":\"scroll\",\"distance\":\"arbitrary\"}")
        }.exceptionOrNull() is HandsAction.Companion.FormatError)
    }
}
