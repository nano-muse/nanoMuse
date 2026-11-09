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
        data class Completed(val rows: List<MessageEntity>) : End
        data object Failed : End
        data object Cancelled : End
    }

    class Receipt {
        var started = false
            private set
        var userId: String? = null
            private set
        private val end = CompletableDeferred<End>()
        fun start() { started = true }
        fun saved(id: String) { userId = id }
        fun complete(rows: List<MessageEntity>) { end.complete(End.Completed(rows.toList())) }
        fun fail() { end.complete(End.Failed) }
        fun cancel(): Boolean = end.complete(End.Cancelled)
        suspend fun awaitEnd(): End = end.await()
    }

    suspend fun run(
        timeoutMs: Long,
        send: (Receipt) -> Unit,
        stop: (Receipt) -> Unit,
        text: (String) -> String?,
    ): Outcome {
        val receipt = Receipt()
        send(receipt)
        if (!receipt.started) return Outcome.NotStarted
        val rows = when (val end = withTimeoutOrNull(timeoutMs) { receipt.awaitEnd() }) {
            null -> { stop(receipt); return Outcome.TimedOut }
            End.Cancelled -> return Outcome.Cancelled
            End.Failed -> return Outcome.Failed
            is End.Completed -> end.rows
        }
        val id = receipt.userId ?: return Outcome.Failed
        val start = rows.indexOfFirst { it.id == id && it.role == "user" }
        if (start < 0) return Outcome.Failed
        val reply = rows.drop(start + 1).takeWhile { it.role != "user" }
            .lastOrNull { it.role == "assistant" } ?: return Outcome.Failed
        if (!reply.errorInfo.isNullOrBlank()) return Outcome.Failed
        val answer = text(reply.partsJson)?.trim().orEmpty()
        return if (answer.isEmpty()) Outcome.Failed else Outcome.Completed(answer)
    }
}
