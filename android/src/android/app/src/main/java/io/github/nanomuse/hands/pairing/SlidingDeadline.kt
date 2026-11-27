// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 wangzan101 (Mika). Adapted for nanoMuse local wireless pairing.
package io.github.nanomuse.hands.pairing

import kotlinx.coroutines.Job
import kotlinx.coroutines.withTimeoutOrNull

/**
 * Sliding deadline measured from the most recent [extend] call.
 * Keeps pairing discovery, auto-read and notifications active for [lengthMs] from the last user visit.
 */
internal class SlidingDeadline(private val lengthMs: Long, private val now: () -> Long) {
    @Volatile private var until = 0L

    fun extend() {
        until = now() + lengthMs
    }

    /** Waits for [job] to finish while allowing [extend] to push back the deadline. */
    suspend fun await(job: Job): Boolean {
        while (true) {
            val left = until - now()
            if (left <= 0) return false
            if (withTimeoutOrNull(left) { job.join() } != null) return true
        }
    }
}
