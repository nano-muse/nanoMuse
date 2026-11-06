package io.github.nanomuse.chat

import com.openminis.app.data.model.AgentContentPart
import com.openminis.app.data.model.LLMMessage

/** Request-only views of compacted history. The saved conversation is never truncated. */
object CompactHistory {
    /**
     * Keep a contiguous suffix of whole user turns within [maxTokens]. A tool-result message
     * is not a turn boundary, even though it has the USER role. Always retain the newest turn:
     * a summary of earlier work must not replace the person's active request or its results.
     * If that turn alone exceeds the budget, the caller's context guard still decides what fits.
     * Set [keepNewestTurn] false only for optional history preceding a separately protected
     * current user turn. In that case every old turn may be dropped when no whole turn fits.
     * If a user message arrived between a tool call and its result, widen the retained prefix
     * to the call's whole user turn. Recheck until the boundary cuts no such pair.
     * [requiredToolIds] names results outside this slice whose calls must remain in the replay,
     * even when an optional replay has no budget left.
     */
    fun retainRecentTurns(
        messages: List<LLMMessage>,
        maxTokens: Int,
        keepNewestTurn: Boolean = true,
        requiredToolIds: Set<String> = emptySet(),
        estimate: (List<LLMMessage>) -> Int = { ContextEstimate.request(it) },
    ): List<LLMMessage> {
        val starts = messages.indices.filter { index ->
            ContextTurns.isUserRequest(messages[index])
        }
        val firstCalls = mutableMapOf<String, Int>()
        val results = mutableListOf<Pair<Int, String>>()
        messages.forEachIndexed { index, message ->
            for (part in message.contentParts) when (part) {
                is AgentContentPart.ToolUse -> firstCalls.putIfAbsent(part.id, index)
                is AgentContentPart.ToolResult -> results += index to part.id
                else -> Unit
            }
        }
        val requiredCall = requiredToolIds.mapNotNull { firstCalls[it] }.minOrNull()
        val mustKeep = keepNewestTurn || requiredCall != null
        if (starts.size < 2) {
            return if (!mustKeep && estimate(messages) > maxTokens) emptyList() else messages
        }
        fun pairedStart(candidate: Int): Int {
            var boundary = candidate
            while (true) {
                val earlierCall = results.asSequence()
                    .filter { (index, _) -> index >= boundary }
                    .mapNotNull { (_, id) -> firstCalls[id]?.takeIf { it < boundary } }
                    .minOrNull() ?: return boundary
                boundary = starts.lastOrNull { it <= earlierCall } ?: 0
            }
        }

        val requiredStart = requiredCall?.let { call -> starts.lastOrNull { it <= call } ?: 0 }
        var start = pairedStart(minOf(starts.last(), requiredStart ?: starts.last()))
        if (!mustKeep && estimate(messages.subList(start, messages.size)) > maxTokens) {
            return emptyList()
        }
        for (candidate in starts.asReversed()) {
            if (candidate >= start) continue
            val paired = pairedStart(candidate)
            if (estimate(messages.subList(paired, messages.size)) > maxTokens) break
            start = paired
        }
        return if (start == 0) messages else messages.subList(start, messages.size).toList()
    }

    /** Results with a preceding post-anchor call do not depend on an older copy of the id. */
    fun externalToolResultIds(messages: List<LLMMessage>): Set<String> {
        val calls = mutableSetOf<String>()
        val external = mutableSetOf<String>()
        for (message in messages) {
            for (part in message.contentParts) when (part) {
                is AgentContentPart.ToolUse -> calls += part.id
                is AgentContentPart.ToolResult -> if (part.id !in calls) external += part.id
                else -> Unit
            }
        }
        return external
    }

    /** Charge the summary and fixed request cost before replaying whole recent turns. */
    fun retainForBudget(
        messages: List<LLMMessage>,
        budget: ContextBudget.Plan,
        summaryTokens: Int = 0,
        keepNewestTurn: Boolean = true,
        requiredToolIds: Set<String> = emptySet(),
        estimate: (List<LLMMessage>) -> Int = { ContextEstimate.request(it) },
    ): List<LLMMessage> = retainRecentTurns(
        messages, budget.replayBudget(summaryTokens), keepNewestTurn, requiredToolIds, estimate,
    )

    /** Providers serialize parts instead of [LLMMessage.content] when parts are present. */
    fun prependSummary(message: LLMMessage, summary: String): LLMMessage {
        if (summary.isBlank()) return message
        return message.copy(
            content = summary + "\n\n" + message.content,
            contentParts = if (message.contentParts.isEmpty()) emptyList() else {
                listOf(AgentContentPart.Text(summary + "\n\n")) + message.contentParts
            },
        )
    }
}
