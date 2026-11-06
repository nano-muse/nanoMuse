package io.github.nanomuse.chat

import com.openminis.app.data.model.AgentContentPart
import com.openminis.app.data.model.LLMMessage
import java.security.MessageDigest
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import org.json.JSONArray
import org.json.JSONObject

/**
 * Request-only context maintenance, inspired by OpenMinis ContextTrimPlanner (GPL-3.0):
 * https://github.com/OpenMinis/OpenMinis/blob/1a71df0f381cefde80bf912b723de6f9831bc177/src/android/app/src/main/java/com/openminis/app/ui/chat/ContextTrimPlanner.kt
 *
 * Clear old reasoning, offload large results and arguments, then shorten smaller tool parts.
 * Whole steps may be archived only after the caller has allowed that last resort. Unlike the
 * upstream fallback truncation, a failed write here always leaves the original content intact.
 * The caller sends [Result.messages] as its outbound view and keeps the source history.
 * Neither persisted messages nor their mutable JSON arguments are modified.
 */
object ContextTrimming {
    data class Options(
        val stripReasoning: Boolean = true,
        val keepRecentIterations: Int = 3,
        val allowCollapse: Boolean = false,
        val allowOversizedLatestResult: Boolean = false,
    )

    enum class Kind { RESULT, ARGUMENTS, STEP }

    /** [key] includes a content digest so reusing a tool id cannot overwrite another payload. */
    data class Spill(
        val key: String,
        val toolId: String,
        val toolName: String,
        val content: String,
        val kind: Kind,
    )

    /** [source] is the original object, suitable as a key in an IdentityHashMap. */
    data class Edit(val source: LLMMessage, val replacement: LLMMessage?)

    data class Result(
        val messages: List<LLMMessage>,
        val beforeTokens: Int,
        val afterTokens: Int,
        val targetTokens: Int,
        val steps: List<String>,
        val edits: List<Edit>,
    ) {
        val reachedTarget: Boolean get() = afterTokens <= targetTokens
    }

    private const val LARGE_CHARS = 2_000
    private const val SMALL_CHARS = 400
    private const val OFFLOAD_PREFIX = "[CONTEXT OFFLOADED]"

    private data class Iteration(
        val assistant: Int,
        val carriers: List<Int>,
        val complete: Boolean,
    )

    /**
     * [measure] must count the exact outbound request, including its fixed prompt and tools.
     * [spill] returns a model-readable file path only after the entire write has succeeded.
     * Ordinary write failures are recoverable; coroutine cancellation always propagates.
     */
    suspend fun trim(
        messages: List<LLMMessage>,
        targetTokens: Int,
        measure: (List<LLMMessage>) -> Int,
        spill: suspend (Spill) -> String?,
        options: Options = Options(),
    ): Result {
        val coroutine = currentCoroutineContext()
        coroutine.ensureActive()
        val target = targetTokens.coerceAtLeast(0)
        val before = measure(messages)
        if (before <= target || messages.isEmpty()) {
            return Result(messages, before, before, target, emptyList(), emptyList())
        }
        val iterations = iterations(messages)
        // Even an unanswered iteration occupies a protected tail slot. Never edit its call,
        // arguments, reasoning or partial results while a tool could still be running.
        val older = iterations.dropLast(options.keepRecentIterations.coerceAtLeast(1))
            .filter { it.complete }
        val working = messages.map<LLMMessage, LLMMessage?> { it }.toMutableList()
        var size = before
        val steps = mutableListOf<String>()
        val saved = mutableMapOf<String, String?>()

        suspend fun save(content: String, id: String, name: String, kind: Kind): String? {
            coroutine.ensureActive()
            val key = "${kind.name.lowercase()}-${digest("$id\u0000$name\u0000$content")}"
            if (saved.containsKey(key)) return saved[key]
            val path = try {
                spill(Spill(key, id, name, content, kind))?.takeIf { it.isNotBlank() }
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                null
            }
            coroutine.ensureActive()
            saved[key] = path
            return path
        }

        fun accept(changes: Map<Int, LLMMessage?>, stage: String): Boolean {
            coroutine.ensureActive()
            if (changes.isEmpty()) return false
            val candidate = working.mapIndexedNotNull { index, current ->
                if (changes.containsKey(index)) changes[index] else current
            }
            val measured = measure(candidate)
            coroutine.ensureActive()
            // Long paths and short originals can make a reference bigger than the source.
            // The request must shrink, even when the caller uses a calibrated token meter.
            if (measured >= size) return false
            for ((index, message) in changes) working[index] = message
            size = measured
            if (stage !in steps) steps += stage
            return true
        }

        if (options.stripReasoning) {
            for (iteration in older) {
                coroutine.ensureActive()
                if (size <= target) break
                val message = working[iteration.assistant] ?: continue
                if (!message.reasoningContent.isNullOrEmpty()) {
                    accept(mapOf(iteration.assistant to message.copy(reasoningContent = "")), "reasoning")
                }
            }
        }

        // Results precede arguments: they usually account for most of a tool-heavy request.
        // The second pass keeps small results verbatim unless larger parts were insufficient.
        for (limit in listOf(LARGE_CHARS, SMALL_CHARS)) {
            for (iteration in older) {
                coroutine.ensureActive()
                if (size <= target) break
                for (index in iteration.carriers) {
                    if (size <= target) break
                    val message = working[index] ?: continue
                    val parts = message.contentParts.map { part ->
                        if (part !is AgentContentPart.ToolResult ||
                            part.content.length <= limit || isOffloaded(part.content)
                        ) part else {
                            val path = save(part.content, part.id, part.name, Kind.RESULT)
                            if (path == null) part else part.copy(content = resultReference(path))
                        }
                    }
                    if (parts != message.contentParts) {
                        accept(mapOf(index to message.copy(contentParts = parts)), "results")
                    }
                }
            }
            for (iteration in older) {
                coroutine.ensureActive()
                if (size <= target) break
                val message = working[iteration.assistant] ?: continue
                val parts = message.contentParts.map { part ->
                    if (part !is AgentContentPart.ToolUse) part else {
                        val keys = part.input.keys().asSequence().filter { key ->
                            val value = part.input.opt(key)
                            value is String && value.length > limit && !isOffloaded(value)
                        }.toList()
                        if (keys.isEmpty()) part else {
                            val path = save(part.input.toString(), part.id, part.name, Kind.ARGUMENTS)
                            if (path == null) part else {
                                val copy = JSONObject(part.input.toString())
                                for (key in keys) copy.put(key, argumentReference(path, key))
                                part.copy(input = copy)
                            }
                        }
                    }
                }
                if (parts != message.contentParts) {
                    accept(mapOf(iteration.assistant to message.copy(contentParts = parts)), "arguments")
                }
            }
        }

        // A single completed result can exceed the whole window. In hard-pressure recovery,
        // archive that payload without touching its call, reasoning or neighbouring user text.
        // Small recent results remain verbatim, and images stay with the image-budget layer.
        if (options.allowOversizedLatestResult && size > target) {
            val latest = iterations.takeLast(options.keepRecentIterations.coerceAtLeast(1))
                .lastOrNull { it.complete }
            val threshold = maxOf(target / 2, 4_096)
            for (index in latest?.carriers.orEmpty()) {
                coroutine.ensureActive()
                if (size <= target) break
                val message = working[index] ?: continue
                val parts = message.contentParts.map { part ->
                    if (part !is AgentContentPart.ToolResult || isOffloaded(part.content) ||
                        ContextEstimate.text(part.content) < threshold
                    ) part else {
                        val path = save(part.content, part.id, part.name, Kind.RESULT)
                        if (path == null) part else part.copy(content = latestResultReference(part.content, path))
                    }
                }
                if (parts != message.contentParts) {
                    accept(mapOf(index to message.copy(contentParts = parts)), "latest-result")
                }
            }
        }

        if (options.allowCollapse) {
            for (iteration in older) {
                coroutine.ensureActive()
                if (size <= target) break
                if (!canCollapse(messages, iteration)) continue
                val assistant = messages[iteration.assistant]
                val calls = assistant.contentParts.filterIsInstance<AgentContentPart.ToolUse>()
                val archive = archive(messages, iteration)
                val path = save(archive, calls.first().id, calls.first().name, Kind.STEP) ?: continue
                val outcomes = iteration.carriers.flatMap { messages[it].contentParts }
                    .filterIsInstance<AgentContentPart.ToolResult>()
                val status = if (outcomes.any { it.isError }) "included an error" else "returned results"
                val names = calls.joinToString(", ") { it.name }
                val notice = "$OFFLOAD_PREFIX Earlier completed tool step ($names, $status). " +
                    "Original calls, results and assistant text: $path. Use file_read to inspect them."
                val changes = iteration.carriers.associateWith<Int, LLMMessage?> { null }.toMutableMap()
                changes[iteration.assistant] = assistant.copy(
                    content = notice,
                    contentParts = listOf(AgentContentPart.Text(notice)),
                    reasoningContent = "",
                )
                accept(changes, "steps")
            }
        }

        val edits = messages.indices.mapNotNull { index ->
            if (working[index] === messages[index]) null else Edit(messages[index], working[index])
        }
        val result = if (edits.isEmpty()) messages else working.filterNotNull()
        return Result(result, before, size, target, steps, edits)
    }

    /** Only unambiguous complete pairs are eligible, including parallel calls in one message. */
    private fun iterations(messages: List<LLMMessage>): List<Iteration> {
        val callCounts = messages.flatMap { it.contentParts }
            .filterIsInstance<AgentContentPart.ToolUse>().groupingBy { it.id }.eachCount()
        val resultCounts = messages.flatMap { it.contentParts }
            .filterIsInstance<AgentContentPart.ToolResult>().groupingBy { it.id }.eachCount()
        return messages.mapIndexedNotNull { index, message ->
            if (message.role != LLMMessage.Role.ASSISTANT) return@mapIndexedNotNull null
            val calls = message.contentParts.filterIsInstance<AgentContentPart.ToolUse>()
            if (calls.isEmpty()) return@mapIndexedNotNull null
            val ids = calls.map { it.id }.toSet()
            val carriers = mutableListOf<Int>()
            val found = mutableSetOf<String>()
            var safe = calls.all {
                it.id.isNotBlank() && callCounts[it.id] == 1 && resultCounts[it.id] == 1 &&
                    it.thoughtSignature.isNullOrEmpty()
            } && message.contentParts.none { it is AgentContentPart.ToolResult }
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
                if (found == ids) break
            }
            Iteration(index, carriers, safe && found == ids)
        }
    }

    private fun canCollapse(messages: List<LLMMessage>, iteration: Iteration): Boolean {
        val assistant = messages[iteration.assistant]
        if (assistant.imageParts.isNotEmpty() || assistant.audioParts.isNotEmpty() ||
            assistant.contentParts.any { it is AgentContentPart.ImageData }
        ) return false
        return iteration.carriers.all { index ->
            val message = messages[index]
            // A carrier can also contain the user's text or the injected summary. Keep it.
            message.content.isEmpty() && message.imageParts.isEmpty() && message.audioParts.isEmpty() &&
                message.contentParts.all { it is AgentContentPart.ToolResult && it.imageData == null }
        }
    }

    private fun archive(messages: List<LLMMessage>, iteration: Iteration): String {
        val rows = JSONArray()
        for (index in listOf(iteration.assistant) + iteration.carriers) {
            val message = messages[index]
            val parts = JSONArray()
            for (part in message.contentParts) parts.put(when (part) {
                is AgentContentPart.Text -> JSONObject().put("type", "text").put("text", part.text)
                is AgentContentPart.ToolUse -> JSONObject().put("type", "tool_use")
                    .put("id", part.id).put("name", part.name).put("input", JSONObject(part.input.toString()))
                is AgentContentPart.ToolResult -> JSONObject().put("type", "tool_result")
                    .put("id", part.id).put("name", part.name).put("content", part.content)
                    .put("is_error", part.isError)
                    .put("image_linux_path", part.imageLinuxPath ?: JSONObject.NULL)
                    .put("image_mime_type", part.imageMimeType ?: JSONObject.NULL)
                is AgentContentPart.ImageData -> error("Image-bearing steps cannot be collapsed")
            })
            rows.put(JSONObject().put("role", message.role.value).put("content", message.content)
                .put("reasoning", message.reasoningContent ?: JSONObject.NULL).put("parts", parts))
        }
        return JSONObject().put("format", "nanomuse-context-step-v1").put("messages", rows).toString()
    }

    private fun isOffloaded(text: String): Boolean = text.trimStart().startsWith(OFFLOAD_PREFIX)

    private fun resultReference(path: String): String =
        "$OFFLOAD_PREFIX Original tool output: $path. Use file_read to retrieve it."

    private fun argumentReference(path: String, field: String): String =
        "$OFFLOAD_PREFIX Historical argument '$field' is stored in $path. " +
            "This is a reference, not the original argument. Read the JSON before reusing its value."

    private fun latestResultReference(content: String, path: String): String =
        "$OFFLOAD_PREFIX Oversized completed tool output. Full output: $path. " +
            "Use file_read to retrieve the needed section.\n" +
            "Start preview:\n${content.take(160)}\nEnd preview:\n${content.takeLast(160)}"

    private fun digest(text: String): String = MessageDigest.getInstance("SHA-256")
        .digest(text.toByteArray(Charsets.UTF_8)).joinToString("") { "%02x".format(it) }
}
