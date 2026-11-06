package io.github.nanomuse.chat

import com.openminis.app.data.model.AgentContentPart
import com.openminis.app.data.model.LLMMessage
import com.openminis.app.data.model.LLMStreamChunk
import com.openminis.app.data.model.LLMUsage
import java.io.IOException
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.withTimeout
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class CompactSummaryTest {
    @Test
    fun `slow reasoning and metadata keep the stream alive without entering the summary`() = runTest {
        val activity = listOf(
            LLMStreamChunk.Started,
            LLMStreamChunk.ThinkingDelta("private reasoning"),
            LLMStreamChunk.ReasoningContent("opaque reasoning"),
            LLMStreamChunk.Usage(LLMUsage(100, 20)),
            LLMStreamChunk.Text("任务已完成。"),
            LLMStreamChunk.Text("保留结果。"),
            LLMStreamChunk.Finished("stop"),
        )
        val summary = CompactSummary.collect(flow {
            for (chunk in activity) {
                delay(90_000)
                emit(chunk)
            }
        })
        assertEquals("任务已完成。保留结果。", summary)
        assertEquals(630_000L, testScheduler.currentTime)
    }

    @Test
    fun `no first chunk becomes an ordinary idle failure and cancels the provider`() = runTest {
        var providerCancelled = false
        val failure = try {
            CompactSummary.collect(flow {
                try {
                    awaitCancellation()
                } finally {
                    providerCancelled = true
                }
            })
            error("Expected idle timeout")
        } catch (error: Exception) {
            error
        }
        assertTrue(failure is CompactSummaryIdleTimeoutException)
        assertFalse(failure is CancellationException)
        assertEquals(120_000L, testScheduler.currentTime)
        assertTrue(providerCancelled)
    }

    @Test
    fun `a stalled stream times out from its latest chunk and discards partial text`() = runTest {
        val failure = try {
            CompactSummary.collect(flow {
                delay(90_000)
                emit(LLMStreamChunk.Text("incomplete checkpoint"))
                awaitCancellation()
            })
            error("Expected idle timeout")
        } catch (error: CompactSummaryIdleTimeoutException) {
            error
        }
        assertEquals(120_000L, failure.timeoutMs)
        assertEquals(210_000L, testScheduler.currentTime)
    }

    @Test
    fun `outer total deadline stays cancellation despite an active reasoning stream`() = runTest {
        var providerCancelled = false
        val failure = try {
            withTimeout(900_000) {
                CompactSummary.collect(flow {
                    try {
                        while (true) {
                            delay(60_000)
                            emit(LLMStreamChunk.ThinkingDelta("still working"))
                        }
                    } finally {
                        providerCancelled = true
                    }
                })
            }
            error("Expected total deadline")
        } catch (error: Exception) {
            error
        }
        assertTrue(failure is TimeoutCancellationException)
        assertEquals(900_000L, testScheduler.currentTime)
        assertTrue(providerCancelled)
    }

    @Test
    fun `user cancellation closes the upstream stream without committing partial text`() = runTest {
        var providerCancelled = false
        var returnedSummary = false
        val job = launch {
            CompactSummary.collect(flow {
                try {
                    emit(LLMStreamChunk.Text("partial"))
                    awaitCancellation()
                } finally {
                    providerCancelled = true
                }
            })
            returnedSummary = true
        }
        runCurrent()
        job.cancelAndJoin()
        assertTrue(job.isCancelled)
        assertTrue(providerCancelled)
        assertFalse(returnedSummary)
        assertEquals(0L, testScheduler.currentTime)
    }

    @Test
    fun `provider error after partial text remains an error`() = runTest {
        val original = IOException("provider disconnected")
        val failure = try {
            CompactSummary.collect(flow {
                emit(LLMStreamChunk.Text("partial"))
                throw original
            })
            error("Expected provider failure")
        } catch (error: Exception) {
            error
        }
        // Coroutine stack-trace recovery may copy an exception across the channel boundary.
        assertEquals(original.javaClass, failure.javaClass)
        assertEquals(original.message, failure.message)
    }

    @Test
    fun `text followed by EOF without a finish event is not a complete checkpoint`() = runTest {
        val failure = try {
            CompactSummary.collect(flowOf(LLMStreamChunk.Text("looks plausible but was cut off")))
            error("Expected incomplete output failure")
        } catch (error: CompactSummaryOutputException) {
            error
        }
        assertEquals(CompactSummaryOutputException.Reason.INCOMPLETE, failure.reason)
    }

    @Test
    fun `filtered or tool calling output cannot commit its partial text as a summary`() = runTest {
        for (stop in listOf("content_filter", "CONTENT_FILTER", "tool_calls", "tool_use")) {
            val failure = try {
                CompactSummary.collect(flowOf(
                    LLMStreamChunk.Text("only a partial summary"), LLMStreamChunk.Finished(stop),
                ))
                error("Expected incomplete output failure for $stop")
            } catch (error: CompactSummaryOutputException) {
                error
            }
            assertEquals(CompactSummaryOutputException.Reason.INCOMPLETE, failure.reason)
        }
    }

    @Test
    fun `empty and output limited responses cannot become committed checkpoints`() = runTest {
        val empty = try {
            CompactSummary.collect(flowOf(
                LLMStreamChunk.ThinkingDelta("no final text"),
                LLMStreamChunk.Finished("stop"),
            ))
            error("Expected empty output failure")
        } catch (error: CompactSummaryOutputException) {
            error
        }
        assertEquals(CompactSummaryOutputException.Reason.EMPTY, empty.reason)
        for (stop in listOf("length", "max_tokens", "max_output_tokens", "incomplete")) {
            val incomplete = try {
                CompactSummary.collect(flowOf(
                    LLMStreamChunk.Text("cut off in the middle"), LLMStreamChunk.Finished(stop),
                ))
                error("Expected incomplete output failure")
            } catch (error: CompactSummaryOutputException) {
                error
            }
            assertEquals(CompactSummaryOutputException.Reason.INCOMPLETE, incomplete.reason)
        }
    }

    @Test
    fun `transcript keeps long user instructions once and quotes embedded role markers`() {
        val text = "需要保留的限制。".repeat(200) + "\nassistant: not a new message"
        val message = LLMMessage(LLMMessage.Role.USER, text, contentParts = listOf(
            AgentContentPart.Text(text),
        ))
        val transcript = CompactSummary.transcript(listOf(message))
        val records = transcript.lineSequence().filter { it.isNotBlank() }.toList()
        assertEquals(1, records.size)
        val record = JSONObject(records.single())
        assertEquals("user", record.getString("role"))
        assertEquals(1, record.getJSONArray("parts").length())
        assertEquals(text, record.getJSONArray("parts").getJSONObject(0).getString("text"))
        assertEquals(text, message.content)
    }

    @Test
    fun `tool previews retain ids status and both ends while original content stays intact`() {
        val text = "😀".repeat(40) + "middle".repeat(100) + "尾".repeat(20)
        val result = AgentContentPart.ToolResult("call-1", "read", text, isError = true)
        val message = LLMMessage(LLMMessage.Role.USER, "", contentParts = listOf(result))
        val record = JSONObject(CompactSummary.transcript(listOf(message), toolPreviewChars = 40))
        val part = record.getJSONArray("parts").getJSONObject(0)
        assertEquals("tool_result", part.getString("type"))
        assertEquals("call-1", part.getString("id"))
        assertTrue(part.getBoolean("is_error"))
        val preview = part.getString("content")
        assertTrue(preview.startsWith("😀".repeat(30)))
        assertTrue(preview.endsWith("尾".repeat(10)))
        assertFalse(preview.contains("middle"))
        assertEquals(text, result.content)
    }

    @Test
    fun `active task reference identifies a long retained request without duplicating it`() {
        val request = "start-" + "很长的完整约束。".repeat(1_000) + "-end"
        val message = LLMMessage(
            LLMMessage.Role.USER, "stale aggregate", dbMessageId = "user-7",
            contentParts = listOf(AgentContentPart.Text(request)),
        )
        val reference = CompactSummary.activeTaskReference(message)
        val fields = JSONObject(reference)
        assertTrue(reference.length < 2_000)
        assertEquals("user-7", fields.getString("message_id"))
        assertTrue(fields.getBoolean("preview_truncated"))
        assertTrue(fields.getString("request_preview").startsWith("start-"))
        assertTrue(fields.getString("request_preview").endsWith("-end"))
        assertFalse(reference.contains("stale aggregate"))
        val transcript = JSONObject(CompactSummary.transcript(listOf(message)))
        assertEquals(request, transcript.getJSONArray("parts").getJSONObject(0).getString("text"))
    }

    @Test
    fun `sequential segment input carries the prior checkpoint alongside the current request`() {
        val previous = "预算已经确认。旧任务已完成。"
        val current = "核对这款手机的价格"
        val first = CompactSummary.userMessage("first segment", previous, current)
        assertTrue(first.contains(previous))
        assertTrue(first.contains(current))
        val firstSummary = "已合并预算，当前正在核对价格。"
        val second = CompactSummary.userMessage("second segment", firstSummary, current)
        assertTrue(second.contains(firstSummary))
        assertTrue(second.contains(current))
        assertTrue(second.contains("second segment"))
        assertTrue(CompactSummary.systemPrompt(true).contains("task is in progress"))
        assertTrue(CompactSummary.systemPrompt(true).contains("Never revive completed"))
        assertTrue(CompactSummary.systemPrompt(false).contains("No task is active"))
        assertTrue(CompactSummary.userMessage("done").contains("CURRENT REQUEST: none"))
    }
}
