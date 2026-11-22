package io.github.nanomuse.hands

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class HandsAppsTest {
    @Test fun backgroundTargetsRequireAnExactPackageOrAnUnambiguousFullLabel() {
        val first = HandsApps.App("Calendar", "example.personal")
        val second = HandsApps.App("Calendar", "example.work")
        val notes = HandsApps.App("My Notes", "example.notes")
        val imitator = HandsApps.App("example.notes", "example.other")
        val apps = listOf(first, second, notes, imitator)

        assertNull(HandsApps.exactTarget(apps, "calendar"))
        assertNull(HandsApps.exactTarget(apps, "notes"))
        assertNull(HandsApps.exactTarget(apps, "My Notes extra"))
        assertEquals(notes, HandsApps.exactTarget(apps, " my notes "))
        assertEquals(notes, HandsApps.exactTarget(apps, "example.notes"))
        assertEquals(second, HandsApps.exactTarget(apps, "example.work"))
    }
}
