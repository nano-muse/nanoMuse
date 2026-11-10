package io.github.nanomuse.hub

import com.openminis.app.data.db.MessageEntity
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.withTimeoutOrNull

/** Bind a headless result to the exact invocation's saved user row and terminal state. */
internal object HeadlessTurn {
    sealed interface Outcome {
        data object NotStarted : Outcome
        data object TimedOut : Outcome
        data object Cancelled : Outcome
        data object Failed : Outcome
        data class Completed(val text: String) : Outcome
    }

    sealed interface End {
        data class Completed(val partsJson: String) : End
        data object Failed : End
        data object Cancelled : End
    }

    class Receipt(val turnId: String) {
        var started = false
            private set
        var userId: String? = null
            private set
        private var stopRequested = false
        private val end = CompletableDeferred<End>()
        val pending: Boolean get() = started && !end.isCompleted
        fun start() { started = true }
        fun saved(id: String) { userId = id }
        @Synchronized fun complete(rows: List<MessageEntity>) {
            if (end.isCompleted || stopRequested) return
            val start = rows.indexOfFirst { it.id == userId && it.role == "user" }
            val reply = if (start < 0) null else rows.drop(start + 1).takeWhile { it.role != "user" }
                .lastOrNull { it.role == "assistant" }
            if (reply == null || !reply.errorInfo.isNullOrBlank()) fail()
            else end.complete(End.Completed(reply.partsJson))
        }
        @Synchronized fun fail() { if (!stopRequested) end.complete(End.Failed) }
        @Synchronized fun requestStop(): Boolean {
            if (!started || end.isCompleted || stopRequested) return false
            stopRequested = true
            return true
        }
        /** Only the owning coroutine's completion hook confirms that cancellation finished. */
        @Synchronized fun jobEnded(cancelled: Boolean) {
            if (cancelled || stopRequested) end.complete(End.Cancelled)
            else end.complete(End.Failed)
        }
        suspend fun awaitEnd(): End = end.await()
    }

    fun stop(receipt: Receipt?, turnId: String, cancel: () -> Unit): Boolean {
        if (receipt == null || receipt.turnId != turnId || !receipt.requestStop()) return false
        cancel()
        return true
    }

    suspend fun run(
        turnId: String,
        timeoutMs: Long,
        send: (Receipt) -> Unit,
        stop: (Receipt) -> Unit,
        text: (String) -> String?,
    ): Outcome {
        val receipt = Receipt(turnId)
        send(receipt)
        if (!receipt.started) return Outcome.NotStarted
        val partsJson = when (val end = withTimeoutOrNull(timeoutMs) { receipt.awaitEnd() }) {
            null -> { stop(receipt); return Outcome.TimedOut }
            End.Cancelled -> return Outcome.Cancelled
            End.Failed -> return Outcome.Failed
            is End.Completed -> end.partsJson
        }
        val answer = text(partsJson)?.trim().orEmpty()
        return if (answer.isEmpty()) Outcome.Failed else Outcome.Completed(answer)
    }
}
