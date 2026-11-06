package io.github.nanomuse.chat

/** Request budgets derived from the active model, including its configured context cap. */
object ContextBudget {
    private const val DEFAULT_OUTPUT_TOKENS = 4_096

    data class Plan(
        val window: Int,
        val fixedTokens: Int,
        val outputReserve: Int,
        val hardLimit: Int,
        val compactThreshold: Int,
        val offloadThreshold: Int,
        val targetTokens: Int,
        val offloadTarget: Int,
    ) {
        /** Budget for replayed turns after charging the system prompt, schemas and summary. */
        fun replayBudget(summaryTokens: Int = 0): Int =
            (targetTokens.toLong() - fixedTokens - summaryTokens.coerceAtLeast(0))
                .coerceAtLeast(0).toInt()
    }

    /**
     * Reserve the requested output, up to 15% of the window (at least 4096 when available).
     * Fixed instructions and schemas are counted before applying history watermarks. This
     * avoids a large fixed prompt causing repeated attempts to reach an impossible target.
     * This reserve sets maintenance watermarks, not the maximum generated reply. The caller
     * separately limits actual requested output to the space left by the outgoing input.
     */
    fun forModel(contextWindow: Int, maxOutputTokens: Int, fixedTokens: Int = 0): Plan {
        val window = contextWindow.coerceAtLeast(0)
        val fixed = fixedTokens.coerceAtLeast(0)
        val requested = maxOutputTokens.takeIf { it > 0 } ?: DEFAULT_OUTPUT_TOKENS
        val reserveCap = maxOf(DEFAULT_OUTPUT_TOKENS, share(window, 15))
        val reserve = minOf(requested, reserveCap, window)
        val hard = window - reserve
        val usable = (hard.toLong() - fixed).coerceAtLeast(0).toInt()
        fun watermark(percent: Int): Int =
            (fixed.toLong() + share(usable, percent)).coerceAtMost(hard.toLong()).toInt()
        val target = watermark(50)
        return Plan(
            window = window,
            fixedTokens = fixed,
            outputReserve = reserve,
            hardLimit = hard,
            compactThreshold = watermark(90),
            offloadThreshold = watermark(75),
            targetTokens = target,
            offloadTarget = target,
        )
    }

    private fun share(tokens: Int, percent: Int): Int = (tokens.toLong() * percent / 100).toInt()
}
