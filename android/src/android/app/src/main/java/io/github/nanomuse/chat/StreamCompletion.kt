package io.github.nanomuse.chat

import com.openminis.app.data.model.LLMError
import com.openminis.app.data.model.LLMStreamChunk
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.flow

/** A closed SSE socket is not a completed model turn without a terminal frame. */
fun Flow<LLMStreamChunk>.failOnIncompleteCompletion(): Flow<LLMStreamChunk> = flow {
    var finished = false
    collect { chunk ->
        if (chunk is LLMStreamChunk.Finished) {
            finished = true
        }
        emit(chunk)
    }
    // This runs only after normal EOF. Cancellation and transport errors retain their
    // original cause. The agent retries this model request before executing any tools.
    if (!finished) {
        throw LLMError.TransientError(StreamFailure.INCOMPLETE)
    }
}

/** Match the provider detail at the UI boundary, without requiring Context in a stream. */
object StreamFailure {
    const val INCOMPLETE = "Connection ended before the response completed"

    fun userText(error: String, interruptedText: String): String =
        error.replace(INCOMPLETE, interruptedText)
}
