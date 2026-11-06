package io.github.nanomuse.chat

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ContextErrorsTest {
    @Test
    fun `actual input overflow is recoverable including provider wording and Chinese`() {
        val details = listOf(
            "[400] context_length_exceeded",
            "Your input exceeds the context window of this model",
            "This model's maximum context length is 128000 tokens. You requested 140000 tokens.",
            "Your messages resulted in 140000 tokens and exceed the maximum context length.",
            "input length and `max_tokens` exceed context limit: 120000 + 16000 > 128000",
            "context length exceeded",
            "Prompt is too long: 140000 input tokens",
            "Too many input tokens. Please reduce the length of the messages.",
            "输入内容过长，请缩短输入后重试",
            "请求超出上下文窗口，请减少历史记录",
        )
        for (detail in details) {
            assertTrue(detail, ContextErrors.isContextOverflow(detail))
            assertFalse(detail, ContextErrors.isParameterRejection(detail))
        }
    }

    @Test
    fun `unsupported or out of range parameters are not context overflow`() {
        val details = listOf(
            "max_tokens is not supported; use max_completion_tokens instead",
            "max_tokens must be between 1 and 8192",
            "max_tokens must be below the maximum context length. Requested output is too large.",
            "max_tokens is too large: the maximum allowed output is 8192",
            "Invalid value for max_tokens: out of range",
            "temperature must be 1 for this model",
            "Unsupported parameter: temperature",
            "reasoning.effort: 'none' is not supported",
            "This model does not support reasoning_effort",
            "Unknown parameter: enable_thinking",
            "Invalid parameter 'thinking_budget': must be smaller than max_tokens",
            "extra_forbidden: extra_body.thinking",
            "参数 temperature 不支持此值",
            "max_tokens 必须小于 8192",
        )
        for (detail in details) {
            assertFalse(detail, ContextErrors.isContextOverflow(detail))
            assertTrue(detail, ContextErrors.isParameterRejection(detail))
        }
    }

    @Test
    fun `mentioning output limits inside an actual input overflow still permits splitting`() {
        val detail = "Invalid parameter max_tokens: input length and max_tokens exceed context limit"
        assertTrue(ContextErrors.isContextOverflow(detail))
        assertFalse(ContextErrors.isParameterRejection(detail))
    }

    @Test
    fun `ambiguous statuses bytes quota and unrelated errors never request context recovery`() {
        val details = listOf(
            "HTTP 400 invalid_request_error",
            "HTTP 413 Request too large: exceeds the maximum allowed number of bytes",
            "Rate limit exceeded: too many tokens per minute",
            "The request failed; max_tokens was 8192",
            "Connection reset by peer",
            "Content policy rejected the input",
            "Model not found",
            "",
        )
        for (detail in details) {
            assertFalse(detail, ContextErrors.isContextOverflow(detail))
            assertFalse(detail, ContextErrors.isParameterRejection(detail))
        }
        assertFalse(ContextErrors.isContextOverflow(null as String?))
        assertFalse(ContextErrors.isParameterRejection(null as String?))
    }

    @Test
    fun `exception wrappers preserve case insensitive multiline provider details`() {
        assertTrue(ContextErrors.isContextOverflow(IllegalStateException(
            "Provider error: INPUT LENGTH AND max_tokens\nEXCEED CONTEXT LIMIT",
        )))
        assertTrue(ContextErrors.isParameterRejection(IllegalArgumentException(
            "Provider error: TEMPERATURE\nMUST BE 1",
        )))
        assertFalse(ContextErrors.isContextOverflow(Exception()))
    }
}
