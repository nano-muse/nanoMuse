package io.github.nanomuse.chat

import java.util.Locale

/** Distinguish input pressure from request-shape errors before retrying or rewriting history. */
object ContextErrors {
    fun isContextOverflow(error: Throwable): Boolean = isContextOverflow(error.message)

    fun isParameterRejection(error: Throwable): Boolean = isParameterRejection(error.message)

    /** Generic 400/413, byte limits and a mention of max_tokens are not evidence of overflow. */
    fun isContextOverflow(detail: String?): Boolean {
        val text = normalize(detail)
        if (text.isEmpty()) return false
        if (OVERFLOW_MARKERS.any(text::contains)) return true
        // OpenAI: "maximum context length is N ... you requested M tokens".
        // Anthropic: "input length and max_tokens exceed context limit: A + B > W".
        // These expressions name the exhausted input capacity, not an output parameter range.
        return INPUT_EXCEEDS_CONTEXT.containsMatchIn(text) ||
            CONTEXT_EXCEEDED.containsMatchIn(text) ||
            (MAXIMUM_CONTEXT_REQUEST.containsMatchIn(text) && !parameterHint(text))
    }

    /** Length errors win: many genuine overflows are HTTP 400 and mention max_tokens too. */
    fun isParameterRejection(detail: String?): Boolean {
        val text = normalize(detail)
        if (text.isEmpty() || isContextOverflow(text)) return false
        return parameterHint(text)
    }

    private fun parameterHint(text: String): Boolean = PARAMETER_MARKERS.any(text::contains) ||
        (PARAMETER_NAMES.any(text::contains) && VALUE_REJECTIONS.any(text::contains))

    private fun normalize(detail: String?): String = detail.orEmpty().lowercase(Locale.ROOT)
        .replace(Regex("\\s+"), " ")

    private val OVERFLOW_MARKERS = listOf(
        "context_length_exceeded",
        "context_window_exceeded",
        "prompt_too_long",
        "input_too_long",
        "input is too long",
        "input too long",
        "prompt is too long",
        "prompt too long",
        "too many input tokens",
        "reduce the length of the messages",
        "exceeds the context window",
        "exceeded the context window",
        "input exceeds the context",
        "输入过长",
        "输入内容过长",
        "输入长度超出",
        "输入长度超过",
        "超出上下文长度",
        "超过上下文长度",
        "超出上下文窗口",
        "超过上下文窗口",
        "上下文长度超限",
        "上下文窗口超限",
    )
    private val MAXIMUM_CONTEXT_REQUEST = Regex(
        "maximum context length.{0,200}(?:requested|resulted|exceeded|exceeds|reduce)",
    )
    private val INPUT_EXCEEDS_CONTEXT = Regex(
        "(?:input|prompt|messages|request).{0,160}exceed(?:s|ed)?.{0,60}" +
            "(?:context (?:window|length|limit)|maximum (?:input|prompt|context) (?:length|tokens))",
    )
    private val CONTEXT_EXCEEDED = Regex("context (?:length|window|limit) (?:is )?exceeded")
    private val PARAMETER_MARKERS = listOf(
        "unsupported parameter",
        "unknown parameter",
        "unrecognized request argument",
        "unrecognised request argument",
        "invalid parameter",
        "unexpected keyword argument",
        "extra_forbidden",
        "不支持的参数",
        "无效参数",
        "参数无效",
    )
    private val PARAMETER_NAMES = listOf(
        "max_tokens", "max_completion_tokens", "temperature", "top_p",
        "thinking", "reasoning", "参数",
    )
    private val VALUE_REJECTIONS = listOf(
        "not supported", "does not support", "unsupported", "not allowed", "must be", "must lie",
        "must satisfy", "invalid value", "invalid type", "out of range",
        "outside the range", "too large", "too small", "unknown", "unrecognized", "unrecognised",
        "extra fields not permitted", "不支持", "必须", "超出范围",
    )
}
