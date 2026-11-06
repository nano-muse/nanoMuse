package io.github.nanomuse.chat

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

class ContextMaintenanceTest {
    private val budget = ContextBudget.forModel(128_000, 16_384, 4_000)

    @Test fun `existing Chinese conversation at 32038 does not summarize`() = runTest {
        val guard = ContextMaintenance()
        assertEquals(ContextMaintenance.Action.PROCEED, guard.check(budget, { 32_038 }) { _, _ ->
            error("32k is not this model's capacity or maintenance target")
        })
        assertEquals(0, guard.attempts)
    }

    @Test fun `soft summary failure continues and defers later tool results`() = runTest {
        val guard = ContextMaintenance()
        var tokens = budget.compactThreshold
        assertEquals(ContextMaintenance.Action.PROCEED, guard.check(budget, { tokens }) { _, _ -> false })
        assertTrue(guard.softDeferred)
        tokens += 500
        assertEquals(ContextMaintenance.Action.PROCEED, guard.check(budget, { tokens }) { _, _ ->
            error("failed maintenance must not run again after every tool")
        })
        assertEquals(1, guard.attempts)
    }

    @Test fun `hard pressure retries a deferred failure then stops`() = runTest {
        val guard = ContextMaintenance()
        var tokens = budget.compactThreshold
        guard.check(budget, { tokens }) { _, _ -> false }
        tokens = budget.hardLimit
        assertEquals(ContextMaintenance.Action.STOP, guard.check(budget, { tokens }) { _, n ->
            assertEquals(2, n)
            false
        })
    }

    @Test fun `partial reduction below hard limit does not immediately summarize again`() = runTest {
        val guard = ContextMaintenance()
        var tokens = budget.hardLimit + 1_000
        assertEquals(ContextMaintenance.Action.COMPACTED, guard.check(budget, { tokens }) { _, _ ->
            tokens = budget.compactThreshold + 1
            true
        })
        assertEquals(ContextMaintenance.Action.PROCEED, guard.check(budget, { tokens }) { _, _ ->
            error("partial reduction already made room")
        })
    }

    @Test fun `no gain at hard capacity cannot proceed`() = runTest {
        assertEquals(ContextMaintenance.Action.STOP,
            ContextMaintenance().check(budget, { budget.hardLimit }) { _, _ -> true })
    }

    @Test fun `a failed summary followed by successful local trimming can proceed`() = runTest {
        var tokens = budget.hardLimit
        assertEquals(ContextMaintenance.Action.PROCEED,
            ContextMaintenance().check(budget, { tokens }) { _, _ ->
                tokens = budget.targetTokens
                false
            })
    }

    @Test fun `one calibration only overflow probe is allowed per run`() = runTest {
        val guard = ContextMaintenance(maxCompactions = 1)
        repeat(2) { attempt ->
            assertEquals(if (attempt == 0) ContextMaintenance.Action.PROCEED else ContextMaintenance.Action.STOP,
                guard.check(budget, { budget.hardLimit + 1 }, { budget.hardLimit - 1 }) { _, _ -> false })
        }
        assertEquals(1, guard.attempts)
    }

    @Test fun `hard pressure has a bounded number of genuine reduction attempts`() = runTest {
        val guard = ContextMaintenance()
        var tokens = budget.hardLimit + 30_000
        repeat(3) {
            assertEquals(ContextMaintenance.Action.COMPACTED, guard.check(budget, { tokens }) { _, _ ->
                tokens -= 5_000
                true
            })
        }
        assertEquals(ContextMaintenance.Action.STOP, guard.check(budget, { tokens }) { _, _ ->
            error("three attempts are already spent")
        })
    }

    @Test fun `small models leave output room without expensive summaries`() = runTest {
        val small = ContextBudget.forModel(16_000, 4_096)
        val guard = ContextMaintenance()
        assertEquals(ContextMaintenance.Action.PROCEED, guard.check(small, { small.hardLimit - 1 }) { _, _ ->
            error("small window does not summarize")
        })
        assertEquals(ContextMaintenance.Action.STOP, guard.check(small, { small.hardLimit }) { _, _ ->
            error("small window does not summarize")
        })
    }

    @Test fun `cancel propagates without resuming an answer`() = runTest {
        val cancellation = CancellationException("user stopped")
        try {
            ContextMaintenance().check(budget, { budget.compactThreshold }) { _, _ -> throw cancellation }
            fail("expected cancellation")
        } catch (caught: CancellationException) {
            assertSame(cancellation, caught)
        }
    }

    @Test fun `model windows give different maintenance thresholds`() = runTest {
        val large = ContextBudget.forModel(1_000_000, 32_000)
        assertEquals(ContextMaintenance.Action.PROCEED,
            ContextMaintenance().check(large, { 128_000 }) { _, _ -> error("large model still fits") })
        val capped = ContextBudget.forModel(64_000, 16_384)
        assertEquals(ContextMaintenance.Action.STOP,
            ContextMaintenance().check(capped, { 64_000 }) { _, _ -> false })
    }
}
