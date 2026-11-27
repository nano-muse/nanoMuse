package io.github.nanomuse.feed

import org.junit.Assert.*
import org.junit.Test

class CalendarChangesTest {
    private fun slot(id: String, a: Long, b: Long, repeats: Boolean = false) = CalendarChanges.Slot(id, a, b, repeats)
    private fun frame(vararg slots: CalendarChanges.Slot, at: Long = 1) = CalendarChanges.Snapshot(at, slots.toList())

    @Test fun onlyNewConflictsPromptEvenWithNoUserConversation() {
        val a = slot("a", 10, 40)
        val b = slot("b", 20, 50)
        assertNull(CalendarChanges.difference(null, frame(a, b)))
        assertEquals(CalendarChanges.Change(a, b, false), CalendarChanges.difference(frame(a), frame(a, b)))
        assertNull(CalendarChanges.difference(frame(a, b), frame(a, b)))
        assertNull(CalendarChanges.difference(frame(a), frame(a, slot("c", 40, 80))))
    }

    @Test fun movesKeepBothTimesAndIgnoreRoutineRecurrences() {
        val earlier = slot("a", 10, 20)
        val later = slot("a", 50, 60)
        assertEquals(CalendarChanges.Change(earlier, later, true), CalendarChanges.difference(frame(earlier), frame(later)))
        assertNull(CalendarChanges.difference(frame(earlier.copy(repeats=true)), frame(later.copy(repeats=true))))
    }

    @Test fun rollingHorizonStaleOrReversedClockDoNotManufactureChanges() {
        val cutoff = 48 * 3600_000L + 1
        assertNull(CalendarChanges.difference(frame(), frame(slot("a", cutoff, cutoff+10), slot("b", cutoff, cutoff+20), at=31)))
        assertNull(CalendarChanges.difference(frame(at=3), frame(slot("a", 10, 20), slot("b", 15, 30), at=1)))
        assertNull(CalendarChanges.difference(frame(), frame(slot("a", cutoff+10, cutoff+30), slot("b", cutoff+15, cutoff+25), at=cutoff+1)))
    }
}
