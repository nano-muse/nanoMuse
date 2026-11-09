package io.github.nanomuse.hub

import com.openminis.app.data.db.MessageEntity
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.async
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.yield
import kotlinx.coroutines.launch
import kotlinx.coroutines.Job
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.withContext
import org.junit.Assert.*
import org.junit.Test

class HeadlessTurnTest {
    private fun row(id: String, role: String, text: String = "", error: String? = null) =
        MessageEntity(id, "session", role, text, 0L, sortOrder = 0, errorInfo = error)

    private val history = listOf(row("old-user", "user"), row("old-answer", "assistant", "same answer"))
    private val reply = history + listOf(row("new-user", "user"), row("new-answer", "assistant", "same answer"))

    @Test fun anUnstartedOrCompactingCallNeverReadsThePreviousAnswer() = runBlocking {
        val result = HeadlessTurn.run(
            turnId = "turn-a", timeoutMs = 1000,
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
        val result = execute { it.start(); it.saved("new-user"); it.requestStop(); it.complete(reply); it.jobEnded(true) }
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
            assertFalse(it.requestStop())
        }
        assertEquals(HeadlessTurn.Outcome.Completed("same answer"), result)
    }

    @Test fun aTimeoutStopsOnlyTheReceiptThatWasStarted() = runBlocking {
        var sent: HeadlessTurn.Receipt? = null
        var stopped: HeadlessTurn.Receipt? = null
        val result = HeadlessTurn.run(
            turnId = "turn-a", timeoutMs = 1,
            send = { sent = it; it.start(); it.saved("new-user") },
            stop = { stopped = it; it.requestStop() },
            text = { error("a timed-out turn has no completed result") },
        )
        assertEquals(HeadlessTurn.Outcome.TimedOut, result)
        assertSame(sent, stopped)
        assertTrue(checkNotNull(sent).pending)
        checkNotNull(sent).jobEnded(true)
        assertFalse(checkNotNull(sent).pending)
    }

    @Test fun aStopRequestDoesNotCompleteUntilItsOwningJobEnds() = runBlocking {
        val started = CompletableDeferred<HeadlessTurn.Receipt>()
        val result = async { execute { it.start(); it.saved("new-user"); started.complete(it) } }
        val receipt = started.await()
        assertTrue(HeadlessTurn.stop(receipt, "turn-a") {})
        receipt.complete(reply)
        yield()
        assertTrue(receipt.pending)
        assertFalse(result.isCompleted)
        receipt.jobEnded(true)
        assertEquals(HeadlessTurn.Outcome.Cancelled, result.await())
        assertFalse(receipt.pending)
    }

    @Test fun cancelledIsPublishedOnlyAfterTheChildFinishesCleanup() = runBlocking {
        val started = CompletableDeferred<HeadlessTurn.Receipt>()
        val cleaningUp = CompletableDeferred<Unit>()
        val releaseCleanup = CompletableDeferred<Unit>()
        var setup: Job? = null
        var stream: Job? = null
        val result = async {
            HeadlessTurn.run(
                turnId = "turn-a", timeoutMs = 5000,
                send = { receipt ->
                    receipt.start(); receipt.saved("new-user")
                    setup = launch {
                        stream = launch {
                            try {
                                started.complete(receipt)
                                awaitCancellation()
                            } finally {
                                withContext(NonCancellable) {
                                    cleaningUp.complete(Unit)
                                    releaseCleanup.await()
                                }
                            }
                        }
                    }.also { parent ->
                        parent.invokeOnCompletion { cause -> receipt.jobEnded(cause is CancellationException) }
                    }
                },
                stop = { error("this test must not time out") }, text = { it },
            )
        }
        val receipt = started.await()
        assertTrue(HeadlessTurn.stop(receipt, "turn-a") { checkNotNull(stream).cancel() })
        cleaningUp.await()
        yield()
        assertFalse(checkNotNull(setup).isCompleted)
        assertTrue(receipt.pending)
        assertFalse(result.isCompleted)
        releaseCleanup.complete(Unit)
        checkNotNull(setup).join()
        assertEquals(HeadlessTurn.Outcome.Cancelled, result.await())
        assertFalse(receipt.pending)
    }

    @Test fun cancellationBeforeTheStreamStartsStillSettlesFromTheSetupJob() = runBlocking {
        val result = execute { it.start(); it.requestStop(); it.fail(); it.jobEnded(true) }
        assertEquals(HeadlessTurn.Outcome.Cancelled, result)
    }

    @Test fun aLateRemoteStopDoesNotCancelOrMarkAFinishedRun() {
        val receipt = HeadlessTurn.Receipt("turn-a")
        receipt.start(); receipt.saved("new-user"); receipt.complete(reply)
        val running = HubTasks()
        running.started("socket-a", "caller", "conversation", "session")
        var cancelled = 0
        // The execution result is ready, but HubActions has not yet removed its run.
        assertFalse(running.stop("caller", "socket-a", null) {
            HeadlessTurn.stop(receipt, "turn-a") { cancelled++ }
        })
        assertEquals(0, cancelled)
        assertFalse(running.finished("socket-a"))
    }

    @Test fun aRemoteStopTargetsOnlyTheSameLiveTurnOnce() {
        val next = HeadlessTurn.Receipt("turn-b")
        next.start()
        var cancelled = 0
        assertFalse(HeadlessTurn.stop(next, "turn-a") { cancelled++ })
        assertEquals(0, cancelled)
        assertTrue(HeadlessTurn.stop(next, "turn-b") { cancelled++ })
        assertFalse(HeadlessTurn.stop(next, "turn-b") { cancelled++ })
        assertEquals(1, cancelled)
        assertTrue(next.pending)
        next.jobEnded(true)
        assertFalse(next.pending)
    }

    private suspend fun execute(send: (HeadlessTurn.Receipt) -> Unit) = HeadlessTurn.run(
        turnId = "turn-a", timeoutMs = 1000, send = send, stop = { error("this turn should settle") }, text = { it },
    )

    private suspend fun result(rows: List<MessageEntity>) = execute {
        // A turn that finishes before the caller starts waiting retains its own receipt.
        it.start(); it.saved("new-user"); it.complete(rows)
    }
}
