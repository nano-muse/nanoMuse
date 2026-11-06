package com.openminis.app.data

import com.openminis.app.ui.chat.ChatViewModel
// nanoMuse: separate provider inactivity from the shared deadline across all summary segments.
import com.openminis.app.data.model.LLMStreamChunk
import io.github.nanomuse.chat.CompactSummary
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

// nanoMuse: active reasoning can exceed the old transcript-size deadline without stalling.
/** Bound idle waits, total elapsed time, and split fan-out independently. */
@OptIn(ExperimentalCoroutinesApi::class)
class CompactBudgetTest {

    @Test
    fun `inactivity expires before the shared total deadline`() {
        assertEquals(120_000L, CompactSummary.IDLE_TIMEOUT_MS)
        assertEquals(900_000L, ChatViewModel.COMPACT_MAX_TOTAL_MS)
        assertTrue(CompactSummary.IDLE_TIMEOUT_MS < ChatViewModel.COMPACT_MAX_TOTAL_MS)
    }

    @Test
    fun `call budget is well under what the depth cap alone permits`() {
        assertEquals(6, ChatViewModel.MAX_COMPACT_LLM_CALLS)
        // depth<3 allows 1+2+4+8 = 15 leaf calls. The budget is what actually
        // bounds wall-clock when each call is slow rather than failing fast.
        val depthCapWorstCase = 1 + 2 + 4 + 8
        assertTrue(
            "call budget must materially cut the depth-cap worst case",
            ChatViewModel.MAX_COMPACT_LLM_CALLS < depthCapWorstCase,
        )
        // Still enough for a full first split (1 + 2) plus a deeper rescue,
        // so the mechanism that exists to save an over-length compaction
        // is not budgeted out of existence.
        assertTrue(
            "budget must still allow a first split plus a rescue",
            ChatViewModel.MAX_COMPACT_LLM_CALLS >= 5,
        )
    }

    @Test
    fun `sequential segments share one total deadline even when each stream stays active`() = runTest {
        var calls = 0
        var completed = 0
        try {
            withTimeout(ChatViewModel.COMPACT_MAX_TOTAL_MS) {
                repeat(ChatViewModel.MAX_COMPACT_LLM_CALLS) {
                    calls += 1
                    CompactSummary.collect(flow {
                        repeat(4) {
                            delay(90_000)
                            emit(LLMStreamChunk.ThinkingDelta("working"))
                        }
                        emit(LLMStreamChunk.Text("checkpoint"))
                        emit(LLMStreamChunk.Finished("stop"))
                    })
                    completed += 1
                }
            }
            error("Expected shared deadline")
        } catch (_: TimeoutCancellationException) {
            assertEquals(900_000L, testScheduler.currentTime)
            assertEquals(3, calls)
            assertEquals(2, completed)
        }
    }
}
