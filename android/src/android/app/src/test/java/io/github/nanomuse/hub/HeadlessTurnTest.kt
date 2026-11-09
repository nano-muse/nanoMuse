package io.github.nanomuse.hub

import com.openminis.app.data.db.MessageEntity
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

class HeadlessTurnTest {
    private fun row(id: String, role: String, text: String = "", error: String? = null) =
        MessageEntity(id, "session", role, text, 0L, sortOrder = 0, errorInfo = error)

    private val history = listOf(row("old-user", "user"), row("old-answer", "assistant", "same answer"))
    private val reply = history + listOf(row("new-user", "user"), row("new-answer", "assistant", "same answer"))

    @Test fun anUnstartedOrCompactingCallNeverReadsThePreviousAnswer() = runBlocking {
        val result = HeadlessTurn.run(
            timeoutMs = 1000,
            // The VM refuses a compacting session, or returns before claiming this run.
            send = { it.complete(history) }, stop = { error("an unstarted turn must not stop another run") },
            text = { error("old history is not a result") },
        )
        assertEquals(HeadlessTurn.Outcome.NotStarted, result)
    }

    @Test fun setupFailureWithoutASavedUserRowCannotReuseHistory() = runBlocking {
        val result = execute { it.start(); it.complete(history) }
        assertEquals(HeadlessTurn.Outcome.Failed, result)
    }

    @Test fun aSavedUserWithoutItsOwnAnswerDoesNotReuseTheOldAnswer() = runBlocking {
        assertEquals(HeadlessTurn.Outcome.Failed, result(history + row("new-user", "user")))
    }

    @Test fun identicalTextInANewAssistantRowIsAValidReply() = runBlocking {
        assertEquals(HeadlessTurn.Outcome.Completed("same answer"), result(reply))
    }

    @Test fun aLaterLocalTurnsAnswerCannotReplaceThisTurnsReply() = runBlocking {
        val rows = history + listOf(
            row("new-user", "user"), row("new-answer", "assistant", "this reply"),
            row("local-user", "user"), row("local-answer", "assistant", "another reply"),
        )
        assertEquals(HeadlessTurn.Outcome.Completed("this reply"), result(rows))
        assertEquals(HeadlessTurn.Outcome.Failed, result(rows.filterNot { it.id == "new-answer" }))
    }

    @Test fun emptyAndErroredAnswersNeverCompleteTheTurn() = runBlocking {
        for (answer in listOf(row("new-answer", "assistant", "  "), row("new-answer", "assistant", "partial", "provider failed"))) {
            assertEquals(HeadlessTurn.Outcome.Failed, result(history + listOf(row("new-user", "user"), answer)))
        }
    }

    @Test fun aRemovedUserRowCannotBorrowAnotherTurnsAnswer() = runBlocking {
        assertEquals(HeadlessTurn.Outcome.Failed, result(history + row("different-answer", "assistant", "unrelated")))
    }

    @Test fun aLocalStopWithAPartialReplyStaysCancelled() = runBlocking {
        val result = execute { it.start(); it.saved("new-user"); it.cancel(); it.complete(reply) }
        assertEquals(HeadlessTurn.Outcome.Cancelled, result)
    }

    @Test fun aHandledFailureWithAPartialReplyStaysFailed() = runBlocking {
        val result = execute { it.start(); it.saved("new-user"); it.fail(); it.complete(reply) }
        assertEquals(HeadlessTurn.Outcome.Failed, result)
    }

    @Test fun completionPinsTheResultBeforeARetryOrQueuedTurn() = runBlocking {
        val rows = reply.toMutableList()
        val result = execute {
            it.start(); it.saved("new-user"); it.complete(rows)
            rows[rows.lastIndex] = row("replacement-answer", "assistant", "retry output")
            assertFalse(it.cancel())
        }
        assertEquals(HeadlessTurn.Outcome.Completed("same answer"), result)
    }

    @Test fun aTimeoutStopsOnlyTheReceiptThatWasStarted() = runBlocking {
        var sent: HeadlessTurn.Receipt? = null
        var stopped: HeadlessTurn.Receipt? = null
        val result = HeadlessTurn.run(
            timeoutMs = 1,
            send = { sent = it; it.start(); it.saved("new-user") },
            stop = { stopped = it; it.cancel() },
            text = { error("a timed-out turn has no completed result") },
        )
        assertEquals(HeadlessTurn.Outcome.TimedOut, result)
        assertSame(sent, stopped)
    }

    private suspend fun execute(send: (HeadlessTurn.Receipt) -> Unit) = HeadlessTurn.run(
        timeoutMs = 1000, send = send, stop = { error("this turn should settle") }, text = { it },
    )

    private suspend fun result(rows: List<MessageEntity>) = execute {
        // A turn that finishes before the caller starts waiting retains its own receipt.
        it.start(); it.saved("new-user"); it.complete(rows)
    }
}
