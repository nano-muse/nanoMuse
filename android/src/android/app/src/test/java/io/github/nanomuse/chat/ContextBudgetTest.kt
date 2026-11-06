package io.github.nanomuse.chat

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ContextBudgetTest {
    @Test
    fun `own key 128k requests are not constrained by a 32k maintenance target`() {
        val budget = ContextBudget.forModel(128_000, 8_192, fixedTokens = 2_000)
        assertEquals(8_192, budget.outputReserve)
        assertEquals(119_808, budget.hardLimit)
        assertEquals(108_027, budget.compactThreshold)
        assertEquals(90_356, budget.offloadThreshold)
        assertEquals(60_904, budget.targetTokens)
        assertEquals(56_904, budget.replayBudget(summaryTokens = 2_000))
        assertTrue(32_038 < budget.offloadThreshold)
    }

    @Test
    fun `large model output limits reserve at most fifteen percent of the actual window`() {
        val native = ContextBudget.forModel(1_000_000, 128_000)
        val capped = ContextBudget.forModel(128_000, 128_000)
        assertEquals(128_000, native.outputReserve)
        assertEquals(19_200, capped.outputReserve)
        assertEquals(108_800, capped.hardLimit)
        assertTrue(capped.compactThreshold < capped.hardLimit)
        assertTrue(capped.offloadThreshold < capped.compactThreshold)
    }

    @Test
    fun `large fixed prompts do not create unattainable replay targets`() {
        val tight = ContextBudget.forModel(32_000, 8_192, fixedTokens = 21_000)
        assertEquals(4_800, tight.outputReserve)
        assertEquals(27_200, tight.hardLimit)
        assertEquals(26_580, tight.compactThreshold)
        assertEquals(24_100, tight.targetTokens)
        assertEquals(1_100, tight.replayBudget(summaryTokens = 2_000))
        val unusable = ContextBudget.forModel(32_000, 8_192, fixedTokens = 40_000)
        assertEquals(unusable.hardLimit, unusable.compactThreshold)
        assertEquals(0, unusable.replayBudget())
    }

    @Test
    fun `unknown small and extreme windows never wrap or create negative budgets`() {
        for (window in listOf(-1, 0, 1, 2_000, 16_000, Int.MAX_VALUE)) {
            val budget = ContextBudget.forModel(window, Int.MAX_VALUE, fixedTokens = Int.MAX_VALUE)
            assertTrue(budget.outputReserve >= 0)
            assertTrue(budget.hardLimit >= 0)
            assertTrue(budget.compactThreshold <= budget.hardLimit)
            assertTrue(budget.targetTokens <= budget.hardLimit)
            assertEquals(0, budget.replayBudget(Int.MAX_VALUE))
        }
        assertEquals(4_096, ContextBudget.forModel(128_000, 0).outputReserve)
        assertEquals(1024, ContextBudget.forModel(128_000, 1024).outputReserve)
    }
}
