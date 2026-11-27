package io.github.nanomuse.chat

import com.openminis.app.data.model.LLMError
import com.openminis.app.data.model.LLMMessage
import com.openminis.app.data.model.LLMModel
import com.openminis.app.data.model.LLMStreamChunk
import com.openminis.app.provider.openai.OpenAIProvider
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.isActive
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.SocketPolicy
import org.junit.Assert.*
import org.junit.Test

class StreamCompletionTest {
    @Test fun `partial text without terminal reason preserves deltas and raises retryable failure`() = runBlocking {
        val seen = mutableListOf<LLMStreamChunk>()
        val error = runCatching {
            flowOf(LLMStreamChunk.Text("partial"))
                .failOnIncompleteCompletion().toList(seen)
        }.exceptionOrNull()
        assertTrue(error is LLMError.TransientError)
        assertEquals("partial", (seen.first() as LLMStreamChunk.Text).text)
        assertTrue(currentCoroutineContext().isActive)
    }

    @Test fun `normal stop and output length limits are completed turns`() = runBlocking {
        for (reason in listOf(null, "stop", "length", "tool_calls", "max_tokens")) {
            val chunks = flowOf(LLMStreamChunk.Text("answer"), LLMStreamChunk.Finished(reason))
                .failOnIncompleteCompletion().toList()
            assertEquals(reason, (chunks.last() as LLMStreamChunk.Finished).stopReason)
        }
    }

    @Test fun `cancellation remains cancellation after partial output`() = runBlocking {
        val cancellation = CancellationException("stopped")
        val error = runCatching {
            flow<LLMStreamChunk> { emit(LLMStreamChunk.Text("partial")); throw cancellation }
                .failOnIncompleteCompletion().collect()
        }.exceptionOrNull()
        assertSame(cancellation, error)
    }

    @Test fun `interruption detail is localized inside final and retry messages`() {
        assertEquals("Transient error: localized, retrying", StreamFailure.userText(
            "Transient error: ${StreamFailure.INCOMPLETE}, retrying", "localized",
        ))
        assertEquals("different failure", StreamFailure.userText("different failure", "localized"))
    }

    @Test fun `socket abort after text is an ordinary network error and the caller stays active`() = runBlocking {
        val server = MockWebServer()
        server.start()
        try {
            val firstEvent = "data: {\"choices\":[{\"delta\":{\"content\":\"partial answer\"}}]}\n\n"
            server.enqueue(MockResponse().setHeader("Content-Type", "text/event-stream")
                .setBody(firstEvent + ": padding\n\n".repeat(2000))
                .setSocketPolicy(SocketPolicy.DISCONNECT_DURING_RESPONSE_BODY))
            val provider = OpenAIProvider("test-key", LLMModel.gpt4oMini,
                server.url("/v1").toString().trimEnd('/'))
            val chunks = mutableListOf<LLMStreamChunk>()
            val error = runCatching {
                provider.streamMessage(listOf(LLMMessage(LLMMessage.Role.USER, "hello")), null, 256)
                    .toList(chunks)
            }.exceptionOrNull()
            assertTrue("expected NetworkError, got $error", error is LLMError.NetworkError)
            assertTrue(chunks.any { it is LLMStreamChunk.Text && it.text.isNotEmpty() })
            assertTrue("the retry countdown must still be able to suspend", currentCoroutineContext().isActive)
        } finally {
            server.shutdown()
        }
    }
}
