package io.github.nanomuse.chat

import com.openminis.app.data.model.LLMError
import com.openminis.app.data.model.LLMMessage
import com.openminis.app.ui.chat.ChatViewModel.Companion.shouldSplitOnError
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class CompactSummaryBudgetTest {
    @Test
    fun `transcript inside the window cannot reduce summary output to one token`() {
        val failure = try {
            val output = CompactSummaryBudget.outputTokens(127_999, 128_000, 16_384)
            error("Expected a split before sending a request with only $output output tokens")
        } catch (error: LLMError.ProviderError) {
            error
        }
        assertTrue(shouldSplitOnError(failure))
    }

    @Test
    fun `full summary output fits exactly at the input boundary`() {
        assertEquals(8_192, CompactSummaryBudget.outputTokens(119_808, 128_000, 16_384))
    }

    @Test
    fun `input one token past the reserved output boundary needs splitting`() {
        val failure = try {
            CompactSummaryBudget.outputTokens(119_809, 128_000, 16_384)
            error("Expected a split instead of shrinking summary output")
        } catch (error: LLMError.ProviderError) {
            error
        }
        assertTrue(shouldSplitOnError(failure))
    }

    @Test
    fun `provider output cap remains the summary ceiling`() {
        assertEquals(2_048, CompactSummaryBudget.outputTokens(125_952, 128_000, 2_048))
        assertEquals(512, CompactSummaryBudget.outputTokens(127_488, 128_000, 512))
    }

    @Test
    fun `small model windows reserve at most half for summary output`() {
        assertEquals(4_096, CompactSummaryBudget.outputTokens(4_096, 8_192, 16_384))
        assertEquals(2_048, CompactSummaryBudget.outputTokens(2_048, 4_096, 16_384))
        assertEquals(512, CompactSummaryBudget.outputTokens(3_584, 4_096, 512))
        val failure = try {
            CompactSummaryBudget.outputTokens(2_049, 4_096, 16_384)
            error("Expected small-window input to split")
        } catch (error: LLMError.ProviderError) {
            error
        }
        assertTrue(shouldSplitOnError(failure))
    }

    @Test
    fun `unusable windows never send zero or negative output limits`() {
        for (window in listOf(-1, 0, 1)) {
            val failure = try {
                CompactSummaryBudget.outputTokens(0, window, 8_192)
                error("Expected unusable window to fail before sending")
            } catch (error: LLMError.ProviderError) {
                error
            }
            assertTrue(shouldSplitOnError(failure))
        }
    }

    @Test
    fun `unknown output limits use the regular budget fallback`() {
        for (limit in listOf(-1, 0)) {
            assertEquals(4_096, CompactSummaryBudget.outputTokens(1_000, 128_000, limit))
        }
    }

    @Test
    fun `summary prompt and checkpoint wrapper count before reserving output`() {
        val history = listOf(
            LLMMessage(LLMMessage.Role.USER, "first history ".repeat(4_000)),
            LLMMessage(LLMMessage.Role.ASSISTANT, "second history ".repeat(4_000)),
        )
        val transcript = CompactSummary.transcript(history)
        val prompt = CompactSummary.systemPrompt(hasActiveTask = true)
        fun inputTokens(messages: List<LLMMessage>): Int {
            val userMessage = CompactSummary.userMessage(
                CompactSummary.transcript(messages), "previous checkpoint", "current request",
            )
            return ContextEstimate.request(
                listOf(LLMMessage(LLMMessage.Role.USER, userMessage)), prompt,
            )
        }
        val input = inputTokens(history)
        val window = input + 8_192 - 1
        assertTrue(ContextEstimate.text(transcript) + 8_192 < window)
        val failure = try {
            CompactSummaryBudget.outputTokens(input, window, 16_384)
            error("Expected wrapper and prompt overhead to trigger splitting")
        } catch (error: LLMError.ProviderError) {
            error
        }
        assertTrue(shouldSplitOnError(failure))
        for (message in history) {
            assertEquals(8_192,
                CompactSummaryBudget.outputTokens(inputTokens(listOf(message)), window, 16_384))
        }
    }
}
