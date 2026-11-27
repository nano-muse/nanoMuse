package io.github.nanomuse.chat

/**
 * Android requires every startForegroundService launch to reach startForeground before stopping.
 * Rapidly leaving a chat can request a stop while the service's start command is still queued.
 */
internal class ForegroundServiceStarts {
    private var sequence = 0L
    private var waitingFor: Long? = null
    private var stopRequested = false

    @Synchronized fun start(launch: (Long) -> Unit) {
        val ticket = ++sequence
        launch(ticket)
        // A rejected launch leaves the previous accepted start and its requested stop intact.
        waitingFor = ticket
        stopRequested = false
    }

    @Synchronized fun stop(stopService: () -> Unit) {
        stopRequested = true
        if (waitingFor == null) stopService()
    }

    @Synchronized fun promoted(ticket: Long, stopService: () -> Unit) {
        if (ticket != waitingFor) return
        waitingFor = null
        if (stopRequested) stopService()
    }
}
