package io.github.nanomuse.sandbox

/**
 * The name of the sandbox's offload socket, the Linux abstract socket the app listens on
 * and proot connects to for the commands it hands back to the app (`--native-offload=`).
 *
 * Abstract sockets live in one namespace for every app on the device, so a name has to be
 * the app's own: OpenMinis binds `native-offload`, and a second app binding the same name
 * fails with EADDRINUSE and, upstream, dies in `onCreate` before its first screen (#271).
 * nanoMuse's name carries the application id instead, and when even that is taken after
 * the bind retries (a previous process of ours the kernel has not reaped yet) the server
 * falls back to a per-process name rather than giving up. proot is told whichever name
 * was bound, on its command line, so nothing else needs to know.
 */
object OffloadSocketName {
    /** Upstream's name; what OpenMinis binds. Never ours. */
    const val UPSTREAM = "native-offload"

    /** The app's own name: `<applicationId>.native-offload`. */
    fun forApp(applicationId: String): String = "$applicationId.$UPSTREAM"

    /** The fallback when the app's name is still held: `<applicationId>.native-offload-<pid>`. */
    fun forProcess(applicationId: String, pid: Int): String = "${forApp(applicationId)}-$pid"
}
