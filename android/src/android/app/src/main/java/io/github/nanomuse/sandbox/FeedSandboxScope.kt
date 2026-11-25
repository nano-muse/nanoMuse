package io.github.nanomuse.sandbox

import android.content.Context
import java.io.File
import java.nio.file.Files
import java.nio.file.StandardCopyOption

/**
 * A disposable, read-only view of Feed posts for the agent sandbox.
 *
 * The real Feed belongs to the app. PRoot bind mounts have no read-only flag, so binding the
 * source would let an arbitrary shell command rewrite likes. Instead, only valid post Markdown
 * files are copied one directory deep into a cache mirror. Tool writes are rejected, shell
 * wrappers reject normal write commands, and a bypass can damage only this mirror. Refreshing
 * restores the mirror from the app-owned source.
 */
object FeedSandboxScope {
    const val LINUX_ROOT = "/var/minis/feed"

    private const val SOURCE_RELATIVE = "minis-global/nanomuse/feed"
    private const val MIRROR_RELATIVE = "feed-sandbox-scopes"
    private val DAY_NAME = Regex("^\\d{4}-\\d{2}-\\d{2}$")
    private val POST_NAME = Regex("^\\d{2}\\.md$")
    private val lock = Any()

    fun sourceRoot(context: Context): File = File(context.filesDir, SOURCE_RELATIVE)

    fun mirrorRoot(context: Context, scopeId: String = "tools"): File =
        File(File(context.cacheDir, MIRROR_RELATIVE), safeScopeId(scopeId))

    fun isReadOnlyPath(linuxPath: String): Boolean =
        linuxPath == LINUX_ROOT || linuxPath.startsWith("$LINUX_ROOT/")

    fun writeError(linuxPath: String): String =
        "Error: $linuxPath is inside the read-only Feed view and cannot be modified."

    fun refresh(context: Context, scopeId: String = "tools"): File =
        refresh(sourceRoot(context), mirrorRoot(context, scopeId))

    fun clear(context: Context, scopeId: String) = synchronized(lock) {
        val mirror = mirrorRoot(context, scopeId)
        makeWritable(mirror)
        mirror.deleteRecursively()
    }

    internal fun refresh(source: File, mirror: File): File = synchronized(lock) {
        makeWritable(mirror)
        mirror.deleteRecursively()
        mirror.mkdirs()

        source.listFiles()
            ?.asSequence()
            ?.filter { it.isDirectory && !Files.isSymbolicLink(it.toPath()) && DAY_NAME.matches(it.name) }
            ?.sortedBy { it.name }
            ?.forEach { day ->
                val targetDay = File(mirror, day.name).apply { mkdirs() }
                day.listFiles()
                    ?.asSequence()
                    ?.filter { it.isFile && !Files.isSymbolicLink(it.toPath()) && POST_NAME.matches(it.name) }
                    ?.sortedBy { it.name }
                    ?.filter { post ->
                        // Prepared cards quote private records. Keep them in the person's Feed;
                        // an already-running shell can outlive changes to a source chat lock.
                        !post.bufferedReader().use { reader ->
                            val header = reader.readLine()
                            header == "---" && reader.lineSequence().takeWhile { it != "---" }.take(16).any { it.startsWith("preparation: ") }
                        }
                    }
                    ?.forEach { post ->
                        Files.copy(
                            post.toPath(),
                            File(targetDay, post.name).toPath(),
                            StandardCopyOption.REPLACE_EXISTING,
                        )
                    }
            }

        lockDown(mirror)
        mirror
    }

    private fun makeWritable(file: File) {
        if (!file.exists()) return
        file.setWritable(true, true)
        if (file.isDirectory && !Files.isSymbolicLink(file.toPath())) {
            file.listFiles()?.forEach(::makeWritable)
        }
    }

    private fun lockDown(file: File) {
        if (!file.exists() || Files.isSymbolicLink(file.toPath())) return
        if (file.isDirectory) file.listFiles()?.forEach(::lockDown)
        file.setWritable(false, false)
        file.setReadable(true, false)
        if (file.isDirectory) file.setExecutable(true, false)
    }

    private fun safeScopeId(scopeId: String): String =
        scopeId.replace(Regex("[^A-Za-z0-9._-]"), "_").take(100).ifEmpty { "anonymous" }
}
