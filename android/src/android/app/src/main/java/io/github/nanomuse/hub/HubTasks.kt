package io.github.nanomuse.hub

import java.util.concurrent.ConcurrentHashMap

/**
 * The tasks other devices have running on this phone, so `stop {call}` or
 * `stop {conversation}` (docs/hub.md) can find the run to end. Pure bookkeeping: [HubActions] registers a task when its prompt starts and
 * clears it when the answer goes out; the unit tests exercise the lookup rules here.
 */
internal class HubTasks {
    private class Run(val senderId: String, val conversation: String, val sessionId: String) {
        @Volatile var stopped = false
    }

    private val runs = ConcurrentHashMap<String, Run>()

    /** The conversation a task from [senderId] lands in: the one it names, else one per device. */
    fun conversationKey(senderId: String, conversation: String?): String =
        conversation?.trim().orEmpty().ifBlank { "from-" + senderId.ifBlank { "unknown" } }

    fun started(callId: String, senderId: String, conversation: String, sessionId: String) {
        runs[callId] = Run(senderId, conversation, sessionId)
    }

    /** Forgets the run; true when a `stop` ended it, so the task answers `cancelled`. */
    fun finished(callId: String): Boolean = runs.remove(callId)?.stopped == true

    /**
     * The session a `stop` from [senderId] would end: an explicit [callId] selects only that run.
     * With no call id, select [conversation] or the sender's per-device conversation. Only
     * the device that asked for a task may stop it; null when there is nothing of theirs to stop.
     */
    fun find(senderId: String, callId: String?, conversation: String?): String? {
        val explicitCall = callId?.takeIf { it.isNotBlank() }
        val run = if (explicitCall != null) runs[explicitCall]
            else runs.values.firstOrNull {
                it.senderId == senderId && it.conversation == conversationKey(senderId, conversation)
            }
        return run?.takeIf { it.senderId == senderId }?.sessionId
    }

    /** The run in [sessionId] was ended by a `stop`; its task answers `cancelled` when it returns. */
    fun markStopped(sessionId: String) {
        runs.values.filter { it.sessionId == sessionId }.forEach { it.stopped = true }
    }

    companion object {
        /**
         * What this phone's Muse is told for a `task`. A web console speaks for the person
         * directly; a device's Muse gets [prefix] (who asked, from where). [language] is the
         * asking device's screen language (`task.language`, docs/hub.md, a BCP-47 tag): when it
         * is there the answer is asked for in it, so the person reads the result in the language
         * of the device they used; without it the model goes by the text. The line is English,
         * for the model, like the rest of the prompt's framing.
         */
        fun prompt(text: String, prefix: String?, language: String?): String {
            val tag = language.orEmpty().trim().take(20)
            return buildList {
                if (!prefix.isNullOrBlank()) add(prefix)
                if (tag.isNotEmpty()) add("Answer in the language tagged $tag; the device that asked shows its screens in it.")
                add(text)
            }.joinToString("\n\n")
        }
    }
}
