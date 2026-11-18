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
        throw LLMError.TransientError("Connection ended before the response completed")
    }
}
