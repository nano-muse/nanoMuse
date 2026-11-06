package io.github.nanomuse.models

import com.openminis.app.data.model.LLMMessage
import com.openminis.app.data.model.LLMModel
import com.openminis.app.data.model.ThinkingLevel
import com.openminis.app.provider.openai.OpenAIProvider
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.util.concurrent.TimeUnit

class QwenThinkingTest {
    private lateinit var server: MockWebServer

    @Before
    fun setUp() {
        server = MockWebServer()
        server.start()
    }

    @After
    fun tearDown() {
        server.shutdown()
    }

    /** Exercise the same public send path used by compact summaries, with a local SSE reply. */
    private fun capture(
        modelId: String,
        level: ThinkingLevel,
        path: String = "/dashscope.aliyuncs.com/compatible-mode/v1",
        maxTokens: Int = 4_096,
    ): JSONObject = runBlocking {
        server.enqueue(MockResponse().setHeader("Content-Type", "text/event-stream").setBody(
            "data: {\"choices\":[{\"delta\":{\"role\":\"assistant\",\"content\":\"ok\"}}]}\n\n" +
                "data: {\"choices\":[{\"delta\":{},\"finish_reason\":\"stop\"}]}\n\n" +
                "data: [DONE]\n\n",
        ))
        val provider = OpenAIProvider(
            apiKey = "test-key",
            model = LLMModel(
                id = modelId,
                displayName = modelId,
                provider = "TestProvider",
                supportsReasoning = true,
            ),
            basePath = server.url(path).toString().trimEnd('/'),
        )
        val response = provider.sendMessage(
            messages = listOf(LLMMessage(LLMMessage.Role.USER, "Summarize the earlier conversation.")),
            systemPrompt = "Keep the current request and completed results.",
            maxTokens = maxTokens,
            thinkingLevel = level,
        )
        assertEquals("ok", response.text)
        val request = checkNotNull(server.takeRequest(5, TimeUnit.SECONDS))
        JSONObject(request.body.readUtf8())
    }

    @Test
    fun `summary OFF explicitly disables Qwen Max and both documented snapshot IDs`() {
        for (modelId in listOf("qwen3.8-max", "qwen3.8-max-0902", "qwen3.8-max-2026-09-02")) {
            val body = capture(modelId, ThinkingLevel.OFF)
            assertFalse(body.getBoolean("enable_thinking"))
            assertFalse(body.getJSONObject("extra_body").getBoolean("enable_thinking"))
            assertFalse(body.has("thinking_budget"))
            assertFalse(body.getJSONObject("extra_body").has("thinking_budget"))
            assertFalse(body.has("reasoning_effort"))
        }
    }

    @Test
    fun `Qwen Max thinking ON retains its existing toggle and bounded budget`() {
        val body = capture("qwen3.8-max", ThinkingLevel.LOW, maxTokens = 8_192)
        assertTrue(body.getBoolean("enable_thinking"))
        assertTrue(body.getJSONObject("extra_body").getBoolean("enable_thinking"))
        assertEquals(4_096, body.getInt("thinking_budget"))
        assertEquals(4_096, body.getJSONObject("extra_body").getInt("thinking_budget"))
        assertFalse(body.has("reasoning_effort"))
    }

    @Test
    fun `thinking only and unverified Qwen variants retain their previous OFF request`() {
        for (modelId in listOf(
            "qwen3.8-2.4t-a95b", "qwen3.7-max-preview", "qwen3-32b", "qwen3.8-max-preview",
        )) {
            val body = capture(modelId, ThinkingLevel.OFF)
            assertFalse("do not send an unsupported toggle to $modelId", body.has("enable_thinking"))
            assertFalse(body.has("thinking_budget"))
            assertFalse(body.has("extra_body"))
        }
    }

    @Test
    fun `higher priority endpoint rules still control the wire format`() {
        for (path in listOf("/openrouter.ai/api/v1", "/mistral.ai/v1")) {
            val body = capture("qwen3.8-max", ThinkingLevel.OFF, path)
            assertFalse(body.has("enable_thinking"))
            assertFalse(body.has("extra_body"))
            assertFalse(body.has("thinking_budget"))
        }
    }
}
