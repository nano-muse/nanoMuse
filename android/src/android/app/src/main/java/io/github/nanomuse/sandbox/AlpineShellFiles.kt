package io.github.nanomuse.sandbox

import java.io.File
import java.io.IOException
import java.nio.file.FileAlreadyExistsException
import java.nio.file.Files
import java.nio.file.LinkOption.NOFOLLOW_LINKS
import java.nio.file.Path

/** Restore the bundled Alpine shell without overwriting installed packages or user files. */
internal object AlpineShellFiles {
    private val members = listOf(
        "lib/ld-musl-aarch64.so.1", "lib/libc.musl-aarch64.so.1", "bin/busybox", "bin/sh",
    )

    fun restoreMissing(rootfs: File, extract: (File, Set<String>) -> Unit) {
        val root = rootfs.toPath()
        val bin = guestDirectory(root, "bin")
        val shell = bin.resolve("sh")
        // Alpine ships an absolute guest link. A host-side exists() follows it into Android.
        if (Files.exists(shell, NOFOLLOW_LINKS)) {
            if (!Files.isSymbolicLink(shell)) return
            val target = Files.readSymbolicLink(shell).toString()
            if (target != "/bin/busybox" && target != "busybox") return
        }

        val lib = guestDirectory(root, "lib")
        val missing = members.associateWith { name ->
            val parent = if (name.startsWith("bin/")) bin else lib
            parent.resolve(name.substringAfter('/'))
        }.filterValues { Files.notExists(it, NOFOLLOW_LINKS) }
        if (missing.isEmpty()) return

        val staging = Files.createTempDirectory(root.parent, ".shell-repair-")
        try {
            extract(staging.toFile(), missing.keys)
            for ((name, destination) in missing) {
                val source = staging.resolve(name)
                Files.createDirectories(destination.parent)
                try {
                    // link(2) publishes complete file contents and fails if someone created it first.
                    if (Files.isSymbolicLink(source)) {
                        Files.createSymbolicLink(destination, Files.readSymbolicLink(source))
                    } else {
                        Files.createLink(destination, source)
                    }
                } catch (_: FileAlreadyExistsException) {
                    // A concurrent guest install has supplied this path.
                }
            }
        } finally {
            Files.walk(staging).use { paths ->
                paths.sorted(Comparator.reverseOrder()).forEach { Files.delete(it) }
            }
        }
    }

    /** Interpret directory symlinks inside the guest even when they start with a slash. */
    private fun guestDirectory(root: Path, directory: String): Path {
        val pending = ArrayDeque(listOf(directory))
        var location = root
        var links = 0
        while (pending.isNotEmpty()) {
            when (val part = pending.removeFirst()) {
                "." -> continue
                ".." -> if (location != root) location = location.parent
                else -> {
                    location = location.resolve(part)
                    if (Files.isSymbolicLink(location)) {
                        if (++links > 40) throw IOException("Too many symlinks resolving /$directory")
                        val target = Files.readSymbolicLink(location)
                        location = if (target.isAbsolute) root else location.parent
                        target.toList().asReversed().forEach { pending.addFirst(it.toString()) }
                    }
                }
            }
        }
        return location
    }
}
