package io.github.nanomuse.sync

import io.github.nanomuse.guard.GateOutcome
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

@OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
class RemoteTaskApprovalsTest {
    private fun event(stage: String = "approval") = JSONObject().put("stage", stage).put("approval_id", "one").put("preview", "Send")

    @Test fun `the existing gate decides and a duplicate card is answered only once`() = runTest {
        val replies = mutableListOf<Pair<String, Boolean>>()
        var decisions = 0
        val approvals = RemoteTaskApprovals(this, "session", "Desk", { id, allow -> replies += id to allow }, {
            decisions++; GateOutcome.Allowed("standing grant")
        })
        approvals.event(event()); approvals.event(event())
        runCurrent()
        assertEquals(1, decisions)
        assertEquals(listOf("one" to true), replies)
        assertEquals(listOf("standing grant"), approvals.notices)
        approvals.close()
    }

    @Test fun `a remote decision withdraws the local card without sending another answer`() = runTest {
        var withdrawn = false
        var replies = 0
        val approvals = RemoteTaskApprovals(this, "session", "Desk", { _, _ -> replies++ }, {
            try { awaitCancellation() } finally { withdrawn = true }
        })
        approvals.event(event()); runCurrent()
        approvals.event(event("approval_result")); runCurrent()
        assertTrue(withdrawn)
        assertEquals(0, replies)
        approvals.close()
    }

    @Test fun `closed calls cannot show late approval cards`() = runTest {
        var decisions = 0
        val approvals = RemoteTaskApprovals(this, "session", "Desk", { _, _ -> }, { decisions++; GateOutcome.Denied("no") })
        approvals.close()
        approvals.event(event()); runCurrent()
        assertEquals(0, decisions)
    }
}
