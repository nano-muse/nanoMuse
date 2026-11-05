package io.github.nanomuse.chat

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

class ContextToolSequenceTest {
    @Test fun `Unicode tool growth is remeasured and no gain cannot loop forever`() = runTest {
        val budget = ContextBudget.forModel(65536, 4096)
        val guard = ContextMaintenance()
        var retained = "task instruction"
        var compacted = 0
        var stopped = false
        var calls = 0
        repeat(20) {
            if (!stopped) {
                calls++
                retained += "工具结果 ação 🧪".repeat(250)
                val action = guard.check(budget, { ContextEstimate.text(retained) }) { _, _ ->
                    compacted++
                    true // A summary was installed, but did not reduce the input.
                }
                stopped = action == ContextMaintenance.Action.STOP
                if (!stopped) assertTrue(ContextEstimate.text(retained) < budget.hardLimit)
            }
        }
        assertTrue(stopped)
        assertTrue(calls >= 10)
        assertTrue(compacted in 1..3)
        assertEquals(4096, budget.outputReserve)
    }

    @Test fun `a useful summary is measured again and cancellation propagates`() = runTest {
        val budget = ContextBudget.forModel(65536, 4096)
        var tokens = budget.hardLimit + 1
        assertEquals(ContextMaintenance.Action.COMPACTED,
            ContextMaintenance().check(budget, { tokens }) { _, _ ->
                tokens = budget.targetTokens
                true
            })
        assertTrue(tokens < budget.hardLimit)
        try {
            ContextMaintenance().check(budget, { budget.hardLimit }) { _, _ ->
                throw CancellationException("stopped")
            }
            fail("cancellation must escape")
        } catch (_: CancellationException) { }
    }
}
