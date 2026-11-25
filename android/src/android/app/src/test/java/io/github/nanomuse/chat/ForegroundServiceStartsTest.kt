package io.github.nanomuse.chat

import org.junit.Assert.*
import org.junit.Test

class ForegroundServiceStartsTest {
    @Test fun leavingAColdChatStopsOnlyAfterForegroundPromotion() {
        val starts = ForegroundServiceStarts()
        val events = mutableListOf<String>()
        var ticket = 0L
        starts.start { ticket = it; events += "launch" }
        starts.stop { events += "premature stop" }
        starts.promoted(ticket) { events += "stop after promotion" }
        starts.promoted(ticket) { events += "duplicate stop" }
        assertEquals(listOf("launch", "stop after promotion"), events)
    }

    @Test fun aNewChatSupersedesTheDeferredStopAndStaleAcknowledgements() {
        val starts = ForegroundServiceStarts()
        val accepted = mutableListOf<Long>()
        val stopped = mutableListOf<String>()
        starts.start { accepted += it }
        starts.stop { stopped += "early" }
        starts.start { accepted += it }
        starts.promoted(accepted.first()) { stopped += "old" }
        starts.promoted(accepted.last()) { stopped += "new" }
        starts.stop { stopped += "idle" }
        assertEquals(listOf("idle"), stopped)
    }

    @Test fun rejectedStartPreservesTheEarlierRequestAndItsDeferredStop() {
        val starts = ForegroundServiceStarts()
        var ticket = 0L
        var stops = 0
        starts.start { ticket = it }
        starts.stop { stops++ }
        val error = runCatching { starts.start { throw IllegalStateException("background restricted") } }
        assertTrue(error.isFailure)
        starts.promoted(ticket) { stops++ }
        assertEquals(1, stops)
    }
}
