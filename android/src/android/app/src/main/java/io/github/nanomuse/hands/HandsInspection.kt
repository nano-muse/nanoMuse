package io.github.nanomuse.hands

/** A pause invalidates every plan made from an earlier picture, even after a quick resume.
 * An action already admitted can finish. Only the operator thread admits actions. */
internal class HandsInspection {
    private var revision = 0L
    private var paused = false

    @Synchronized fun toggle(): Boolean {
        paused = !paused
        revision++
        return paused
    }

    @Synchronized fun observation(): Long? = if (paused) null else revision
    @Synchronized fun current(ticket: Long) = !paused && revision == ticket
}
