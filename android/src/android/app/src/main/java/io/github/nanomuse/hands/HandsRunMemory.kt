package io.github.nanomuse.hands

import org.json.JSONArray
import org.json.JSONObject

/** A bounded, process-local note for the next explicit task in the same chat and app. */
class HandsRunMemory(
    private val clock: () -> Long = { System.nanoTime() / 1_000_000 },
    private val ttlMs: Long = 30 * 60_000L,
    private val capacity: Int = 32,
) {
    internal data class Key(val session: String, val app: String)
    class Ticket internal constructor(internal val key: Key, internal val generation: Long, val previous: String?)
    private data class Entry(val at: Long, val note: String)
    private val entries = LinkedHashMap<Key, Entry>(16, 0.75f, true)
    private var generation = 0L

    init { require(ttlMs > 0 && capacity > 0) }

    @Synchronized fun begin(sessionId: String?, packageName: String?): Ticket? {
        if (sessionId.isNullOrBlank() || packageName.isNullOrBlank()) return null
        val now = clock()
        entries.entries.removeAll { now - it.value.at >= ttlMs }
        val key = Key(sessionId, packageName)
        return Ticket(key, generation, entries[key]?.note)
    }

    @Synchronized fun finish(ticket: Ticket?, task: String, outcome: String, result: String, steps: List<String>) {
        if (ticket == null || ticket.generation != generation) return
        val note = JSONObject()
            .put("previous_task", bounded(task, 512))
            .put("outcome", outcome)
            .put("result", bounded(result, 1_536))
            .put("last_steps", JSONArray(steps.takeLast(8).map { bounded(it, 160) }))
            .toString()
        entries[ticket.key] = Entry(clock(), note)
        while (entries.size > capacity) entries.remove(entries.keys.first())
    }

    /** Also invalidates an in-flight run so it cannot restore cleared history on completion. */
    @Synchronized fun clear(sessionId: String) {
        generation++
        entries.keys.removeAll { it.session == sessionId }
    }

    @Synchronized fun clearAll() { generation++; entries.clear() }

    private fun bounded(text: String, count: Int): String = if (text.codePointCount(0, text.length) <= count) text
        else text.substring(0, text.offsetByCodePoints(0, count)) + "…"

    companion object { val shared = HandsRunMemory() }
}
