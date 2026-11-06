package io.github.nanomuse.chat

import com.openminis.app.data.model.AgentContentPart
import com.openminis.app.data.model.LLMMessage
import com.openminis.app.data.model.LLMStreamChunk
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

/** Exercise the request view, local offload, summary stream and capacity guard together. */
@OptIn(ExperimentalCoroutinesApi::class)
class ContextRecoveryTest {
    private val prompt = "按用户当前请求核对来源。"
    private val budget = ContextBudget.forModel(
        128_000, 8_192, fixedTokens = ContextEstimate.request(emptyList(), prompt),
    )

    private fun user(text: String) = LLMMessage(LLMMessage.Role.USER, text)
    private fun assistant(text: String) = LLMMessage(LLMMessage.Role.ASSISTANT, text)
    private fun measure(messages: List<LLMMessage>) = ContextEstimate.request(messages, prompt)

    /** Two earlier Chinese turns followed by a new question, priced by the real estimator. */
    private fun mainChatAt(tokens: Int): List<LLMMessage> {
        val history = mutableListOf(
            user("之前讨论手机预算"), assistant("预算已经确认，旧问题已回答。"),
            user("再比较一下之前的型号"), assistant(""),
            user("iPhone duo的价格"),
        )
        val remaining = tokens - measure(history)
        require(remaining >= 0)
        history[3] = assistant("旧".repeat(remaining / 2) + "a".repeat(remaining % 2 * 4))
        check(measure(history) == tokens)
        return history.toList()
    }

    private fun toolRound(id: String, result: String): List<LLMMessage> = listOf(
        LLMMessage(LLMMessage.Role.ASSISTANT, "", contentParts = listOf(
            AgentContentPart.ToolUse(id, "file_read", JSONObject().put("path", "$id.txt")),
        )),
        LLMMessage(LLMMessage.Role.USER, "", contentParts = listOf(
            AgentContentPart.ToolResult(id, "file_read", result),
        )),
    )

    @Test
    fun `old 32038 token main chat proceeds and later large results offload before any summary`() = runTest {
        val original = mainChatAt(32_038)
        val activeRequest = original.last()
        val guard = ContextMaintenance()
        assertEquals(ContextMaintenance.Action.PROCEED, guard.check(budget, { measure(original) }) { _, _ ->
            error("The existing conversation and new question fit without a summary")
        })

        val largeOutput = "网页价格与型号记录。".repeat(2_500)
        val newest = toolRound("verify", "型号已核对") +
            toolRound("price", "价格来源已确认") + toolRound("currency", "币种已核对")
        val expanded = original + toolRound("source-1", largeOutput) +
            toolRound("source-2", largeOutput) + toolRound("source-3", largeOutput) + newest
        val expandedTokens = measure(expanded)
        assertTrue(expandedTokens > budget.hardLimit)
        val saved = linkedMapOf<String, String>()
        val trimmed = ContextTrimming.trim(expanded, budget.offloadTarget, ::measure, { spill ->
            val path = "/var/minis/offloads/${spill.key}.txt"
            saved[path] = spill.content
            path
        })

        assertTrue(trimmed.reachedTarget)
        assertEquals(3, saved.size)
        assertTrue(saved.values.all { it == largeOutput })
        assertSame(activeRequest, trimmed.messages[original.lastIndex])
        assertEquals(newest, trimmed.messages.takeLast(newest.size))
        val referenced = trimmed.messages.flatMap { it.contentParts }
            .filterIsInstance<AgentContentPart.ToolResult>()
        assertTrue(saved.keys.all { path -> referenced.any { it.content.contains(path) } })
        assertEquals(ContextMaintenance.Action.PROCEED, guard.check(budget, { measure(trimmed.messages) }) { _, _ ->
            error("Local offload already made room for the answer")
        })
        assertEquals(0, guard.attempts)
        assertEquals(expandedTokens, measure(expanded))
        assertEquals(32_038, measure(original))
    }

    @Test
    fun `active summary beyond 150 seconds installs once and resumes with the current request`() = runTest {
        val original = mainChatAt(budget.compactThreshold + 100)
        var outbound = original
        var checkpoint: String? = null
        val guard = ContextMaintenance()
        val action = guard.check(budget, { measure(outbound) }) { _, _ ->
            val complete = CompactSummary.collect(flow {
                repeat(3) {
                    delay(70_000)
                    emit(LLMStreamChunk.ThinkingDelta("仍在整理历史"))
                }
                emit(LLMStreamChunk.Text("旧型号和预算已确认。当前任务是核对最新手机价格。"))
                emit(LLMStreamChunk.Finished("stop"))
            })
            val kept = CompactHistory.retainForBudget(
                original, budget, summaryTokens = ContextEstimate.text(complete),
            )
            outbound = listOf(CompactHistory.prependSummary(kept.first(), complete)) + kept.drop(1)
            checkpoint = complete
            true
        }

        assertEquals(210_000L, testScheduler.currentTime)
        assertEquals(ContextMaintenance.Action.COMPACTED, action)
        assertNotNull(checkpoint)
        assertTrue(outbound.first().content.contains(original.last().content))
        assertTrue(measure(outbound) < budget.compactThreshold)
        assertEquals(budget.compactThreshold + 100, measure(original))
        assertEquals(ContextMaintenance.Action.PROCEED, guard.check(budget, { measure(outbound) }) { _, _ ->
            error("The installed checkpoint must not immediately trigger another summary")
        })
        assertEquals(1, guard.attempts)
    }

    @Test
    fun `idle summary preserves the checkpoint and only hard capacity stops the request`() = runTest {
        for (tokens in listOf(budget.compactThreshold, budget.hardLimit)) {
            val original = mainChatAt(tokens)
            var checkpoint = "上一次成功保存的摘要"
            val guard = ContextMaintenance()
            var idleFailure: CompactSummaryIdleTimeoutException? = null
            val action = guard.check(budget, { measure(original) }) { _, _ ->
                try {
                    val complete = CompactSummary.collect(flow {
                        emit(LLMStreamChunk.ThinkingDelta("开始整理"))
                        awaitCancellation()
                    })
                    checkpoint = complete
                    true
                } catch (error: CompactSummaryIdleTimeoutException) {
                    idleFailure = error
                    false
                }
            }
            assertNotNull(idleFailure)
            assertEquals("上一次成功保存的摘要", checkpoint)
            assertEquals(tokens, measure(original))
            assertEquals(
                if (tokens < budget.hardLimit) ContextMaintenance.Action.PROCEED else ContextMaintenance.Action.STOP,
                action,
            )
            assertEquals(1, guard.attempts)
        }
        assertEquals(240_000L, testScheduler.currentTime)
    }

    @Test
    fun `cancel during summary leaves the checkpoint and request view unchanged`() = runTest {
        val original = mainChatAt(budget.compactThreshold + 100)
        var outbound = original
        var checkpoint = "之前的有效摘要"
        var action: ContextMaintenance.Action? = null
        var providerCancelled = false
        val guard = ContextMaintenance()
        val job = launch {
            action = guard.check(budget, { measure(outbound) }) { _, _ ->
                val complete = CompactSummary.collect(flow {
                    try {
                        emit(LLMStreamChunk.Text("尚未完成的摘要"))
                        awaitCancellation()
                    } finally {
                        providerCancelled = true
                    }
                })
                checkpoint = complete
                outbound = listOf(CompactHistory.prependSummary(original.last(), complete))
                true
            }
        }
        runCurrent()
        job.cancelAndJoin()
        assertTrue(providerCancelled)
        assertTrue(job.isCancelled)
        assertNull(action)
        assertEquals("之前的有效摘要", checkpoint)
        assertSame(original, outbound)
        assertEquals(1, guard.attempts)
        assertEquals(0L, testScheduler.currentTime)
    }
    @Test
    fun `failed summary cannot replace known server usage with a smaller heuristic`() = runTest {
        val messages = listOf(LLMMessage(LLMMessage.Role.USER, "继续处理当前任务"))
        val budget = ContextBudget.forModel(128_000, 16_384)
        val calibration = ContextEstimate.Calibration()
        val meter = ContextUsageMeter()
        val snapshot = meter.snapshot("route", "model", messages)
        val raw = ContextEstimate.request(messages)
        meter.observe(snapshot, budget.hardLimit + 1, raw)
        var measured = 0
        val guard = ContextMaintenance()
        val action = guard.check(
            budget,
            measure = { meter.estimate(snapshot, raw, calibration).also { measured = it } },
            measureUncalibrated = { if (meter.lastEstimateUsedAnchor) measured else raw },
        ) { _, _ -> false }
        assertEquals(ContextMaintenance.Action.STOP, action)
        assertTrue(meter.lastEstimateUsedAnchor)
        assertFalse(guard.calibrationProbeGranted)
    }

}
