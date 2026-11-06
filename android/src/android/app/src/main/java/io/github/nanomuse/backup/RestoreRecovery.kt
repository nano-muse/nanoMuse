package io.github.nanomuse.backup

import java.io.File
import java.io.FileOutputStream
import java.nio.file.Files
import java.nio.file.StandardCopyOption

/** The journal stores target names, never paths supplied by a backup. */
interface RecoveryTarget {
    fun snapshot(destination: File)
    fun restore(snapshot: File)
}

class RestoreRecovery(private val directory: File, private val targets: Map<String, RecoveryTarget>) {
    @Synchronized fun begin(category: String) {
        val target = requireNotNull(targets[category]) { "Unknown recovery target" }
        require(category.matches(Regex("[a-z_]+")))
        val pending = File(directory, category)
        check(!pending.exists()) { "Recovery must finish before another restore" }
        directory.mkdirs()
        val preparing = File(directory, "$category.preparing")
        preparing.deleteRecursively()
        check(preparing.mkdirs())
        target.snapshot(preparing)
        check(preparing.renameTo(pending)) { "Cannot publish recovery snapshot" }
    }

    @Synchronized fun complete(category: String) {
        require(category in targets)
        val pending = File(directory, category)
        if (!pending.exists()) return
        val done = File(directory, "$category.completed")
        check(!done.exists() || done.deleteRecursively())
        check(pending.renameTo(done)) { "Cannot commit recovered category" }
        done.deleteRecursively()
    }

    @Synchronized fun recover(): List<String> {
        val recovered = mutableListOf<String>()
        for (category in targets.keys) {
            val pending = File(directory, category)
            if (!pending.exists()) continue
            targets.getValue(category).restore(pending)
            complete(category)
            recovered += category
        }
        return recovered
    }
}

/** Persistent copy-aside. A retry always reads the unchanged original snapshot. */
class FileRecoveryTarget(private val live: File, private val boundary: File = requireNotNull(live.parentFile)) : RecoveryTarget {
    override fun snapshot(destination: File) {
        validateTarget()
        if (live.exists()) copy(live, File(destination, "payload"))
        durableWrite(File(destination, "present"), live.exists().toString().toByteArray())
    }

    override fun restore(snapshot: File) {
        validateTarget()
        val present = File(snapshot, "present").readText().toBooleanStrict()
        val replacement = File(live.parentFile, ".${live.name}.restore-replacement")
        replacement.deleteRecursively()
        if (present) copy(File(snapshot, "payload"), replacement)
        check(!live.exists() || live.deleteRecursively()) { "Cannot replace recovery target" }
        if (present) check(replacement.renameTo(live)) { "Cannot install recovery target" }
    }

    private fun validateTarget() {
        val base = boundary.absoluteFile.toPath().normalize()
        var current: java.nio.file.Path? = live.absoluteFile.toPath().normalize()
        check(current!!.startsWith(base) && current != base) { "Recovery target escaped its storage boundary" }
        while (current != null && current.startsWith(base)) {
            check(!Files.isSymbolicLink(current)) { "Recovery refuses symbolic links" }
            current = current.parent
        }
    }

    private fun copy(source: File, destination: File) {
        check(!Files.isSymbolicLink(source.toPath())) { "Recovery refuses symbolic links" }
        if (source.isDirectory) {
            check(destination.mkdirs() || destination.isDirectory)
            for (child in checkNotNull(source.listFiles())) copy(child, File(destination, child.name))
        } else {
            check(source.isFile) { "Missing recovery payload" }
            destination.parentFile?.mkdirs()
            source.inputStream().use { input ->
                FileOutputStream(destination).use { output -> input.copyTo(output); output.fd.sync() }
            }
        }
    }
}

internal fun durableWrite(file: File, bytes: ByteArray) {
    file.parentFile?.mkdirs()
    val next = File(file.parentFile, "${file.name}.next")
    FileOutputStream(next).use { it.write(bytes); it.fd.sync() }
    Files.move(next.toPath(), file.toPath(), StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE)
}
