package io.github.nanomuse.chat

import com.openminis.app.data.model.AgentContentPart
import com.openminis.app.data.model.LLMMessage

/** Optional verbatim replay of messages that a complete checkpoint already covers. */
object CheckpointReplay {
    private data class Step(val assistant: Int, val carriers: List<Int>, val replaceable: Boolean)

    /**
     * Use only after building a successful checkpoint, and only for its covered replay prefix.
     * Uncovered post-anchor messages belong to the caller and must never enter this function.
     *
     * A giant latest turn must not defeat its own checkpoint by replaying every old step. Keep
     * user text and attachments verbatim, plus the last [keepRecentIterations] tool iterations.
     * If that still exceeds [maxTokens], keep the last iteration. Only complete, unambiguous
     * pairs and plain assistant narrative can be replaced by the checkpoint. A signed chain,
     * dangling call/result, mixed user/tool message or attachment stays intact even over budget.
     */
    fun retainCovered(
        messages: List<LLMMessage>,
        maxTokens: Int,
        keepRecentIterations: Int = 3,
        estimate: (List<LLMMessage>) -> Int = { ContextEstimate.request(it) },
    ): List<LLMMessage> {
        require(keepRecentIterations > 0) { "At least one recent tool iteration must be retained" }
        val before = estimate(messages)
        val target = maxTokens.coerceAtLeast(0)
        if (before <= target || messages.isEmpty()) return messages

        val steps = steps(messages)
        // A signature can bind a provider-specific continuation chain. Without an adapter
        // proof that it can be separated, preserve everything from its first signed call.
        val signedStart = messages.indexOfFirst { message ->
            message.contentParts.any {
                it is AgentContentPart.ToolUse && !it.thoughtSignature.isNullOrEmpty()
            }
        }.takeIf { it >= 0 } ?: messages.size

        fun candidate(keep: Int): List<LLMMessage> {
            val removed = mutableSetOf<Int>()
            for (step in steps.dropLast(keep)) {
                if (!step.replaceable || step.assistant >= signedStart ||
                    step.carriers.any { it >= signedStart }
                ) continue
                removed += step.assistant
                removed += step.carriers
            }
            for ((index, message) in messages.withIndex()) {
                if (index < signedStart && message.role == LLMMessage.Role.ASSISTANT &&
                    message.imageParts.isEmpty() && message.audioParts.isEmpty() &&
                    message.contentParts.all { it is AgentContentPart.Text }
                ) removed += index
            }
            return if (removed.isEmpty()) messages else messages.filterIndexed { index, _ -> index !in removed }
        }

        var best = messages
        var bestTokens = before
        for (keep in listOf(keepRecentIterations, 1).distinct()) {
            val candidate = candidate(keep)
            val tokens = estimate(candidate)
            if (tokens < bestTokens) {
                best = candidate
                bestTokens = tokens
            }
            if (bestTokens <= target) break
        }
        return best
    }

    private fun steps(messages: List<LLMMessage>): List<Step> {
        val parts = messages.flatMap { it.contentParts }
        val callCounts = parts.filterIsInstance<AgentContentPart.ToolUse>()
            .groupingBy { it.id }.eachCount()
        val resultCounts = parts.filterIsInstance<AgentContentPart.ToolResult>()
            .groupingBy { it.id }.eachCount()
        return messages.mapIndexedNotNull { index, message ->
            if (message.role != LLMMessage.Role.ASSISTANT) return@mapIndexedNotNull null
            val calls = message.contentParts.filterIsInstance<AgentContentPart.ToolUse>()
            if (calls.isEmpty()) return@mapIndexedNotNull null
            val ids = calls.map { it.id }.toSet()
            val carriers = mutableListOf<Int>()
            val found = mutableSetOf<String>()
            var safe = calls.all {
                it.id.isNotEmpty() && callCounts[it.id] == 1 && resultCounts[it.id] == 1 &&
                    it.thoughtSignature.isNullOrEmpty()
            } && message.imageParts.isEmpty() && message.audioParts.isEmpty() &&
                message.contentParts.all { it is AgentContentPart.Text || it is AgentContentPart.ToolUse }
            for (following in index + 1 until messages.size) {
                val carrier = messages[following]
                if (carrier.role != LLMMessage.Role.USER) break
                val results = carrier.contentParts.filterIsInstance<AgentContentPart.ToolResult>()
                if (results.isEmpty()) break
                if (results.any { it.id !in ids }) {
                    safe = false
                    break
                }
                carriers += following
                found += results.map { it.id }
                safe = safe && carrier.content.isEmpty() &&
                    carrier.imageParts.isEmpty() && carrier.audioParts.isEmpty() &&
                    carrier.contentParts.all { it is AgentContentPart.ToolResult && it.imageData == null }
                if (found == ids) break
            }
            Step(index, carriers, safe && found == ids)
        }
    }
}
