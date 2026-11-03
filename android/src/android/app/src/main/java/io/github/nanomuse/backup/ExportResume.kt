package io.github.nanomuse.backup

import java.io.File
import java.io.FileOutputStream
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.MessageDigest
import java.util.Properties
import java.util.UUID

class ExportResume(private val root: File, private val id: () -> String = { UUID.randomUUID().toString() },
    private val clock: () -> Long = System::currentTimeMillis) {
    class ResumeRequired : IllegalStateException("An interrupted backup needs resume or discard in Backup and restore.")
    data class Run(val id: String, val snapshotAt: Long, val signature: String, val encrypted: Boolean,
        val staging: File, val completed: Map<String, String>)
    private val marker get() = File(root, "pending.properties")
    fun pending(): Run? {
        if (!marker.isFile) return null
        val p = read(marker)
        val runId = p.getProperty("id")
        require(runId.matches(Regex("[a-zA-Z0-9-]+")))
        val staging = File(root, runId)
        val checkpoint = File(staging, "checkpoint.properties")
        val done = if (checkpoint.exists()) read(checkpoint).stringPropertyNames().filter { it.startsWith("done.") }
            .associate { it.removePrefix("done.") to read(checkpoint).getProperty(it) } else emptyMap()
        return Run(runId, p.getProperty("snapshot").toLong(), p.getProperty("signature"),
            p.getProperty("encrypted").toBooleanStrict(), File(staging, "payload"), done)
    }
    @Synchronized fun open(signature: String, encrypted: Boolean, resume: Boolean): Run {
        val prior = pending()
        if (prior != null) {
            if (!resume) throw ResumeRequired()
            require(prior.signature == signature && prior.encrypted == encrypted) { "Backup options changed; discard the interrupted run first." }
            prepare(prior)
            return prior
        }
        val p = Properties().apply {
            setProperty("id", id()); setProperty("snapshot", clock().toString())
            setProperty("signature", signature); setProperty("encrypted", encrypted.toString())
        }
        write(marker, p)
        return pending()!!.also { it.staging.mkdirs() }
    }
    @Synchronized fun completed(run: Run, category: String, statistics: String) {
        require(category.matches(Regex("[a-z_]+")))
        check(pending()?.id == run.id)
        val file = File(run.staging.parentFile, "checkpoint.properties")
        val checkpoint = if (file.exists()) read(file) else Properties()
        checkpoint.setProperty("done.$category", statistics)
        checkpoint.setProperty("indexLength", File(run.staging, "files.index.jsonl").length().toString())
        checkpoint.stringPropertyNames().filter { it.startsWith("hash.") }.forEach { checkpoint.remove(it) }
        val data = File(run.staging, "data")
        if (data.exists()) for (member in data.walkTopDown().filter { it.isFile }) {
            check(!Files.isSymbolicLink(member.toPath()))
            FileOutputStream(member, true).use { it.fd.sync() }
            checkpoint.setProperty("hash.${member.relativeTo(run.staging).invariantSeparatorsPath}", digest(member))
        }
        File(run.staging, "files.index.jsonl").takeIf { it.exists() }?.let { index ->
            FileOutputStream(index, true).use { it.fd.sync() }
        }
        write(file, checkpoint)
    }

    private fun prepare(run: Run) {
        val checkpoint = File(run.staging.parentFile, "checkpoint.properties")
        val p = if (checkpoint.exists()) read(checkpoint) else Properties()
        val preserved = p.stringPropertyNames().filter { it.startsWith("hash.") }.map { it.removePrefix("hash.") }.toSet()
        for (path in preserved) {
            require(path.startsWith("data/") && path.split('/').none { it == ".." })
            val file = File(run.staging, path)
            check(file.canonicalFile.toPath().startsWith(run.staging.canonicalFile.toPath()))
            check(file.isFile && digest(file) == p.getProperty("hash.$path")) {
                "Staged backup data changed; discard this interrupted run."
            }
        }
        File(run.staging, "data").takeIf { it.exists() }?.walkBottomUp()?.forEach { file ->
            if (file.isFile && file.relativeTo(run.staging).invariantSeparatorsPath !in preserved) check(file.delete())
        }
        val length = p.getProperty("indexLength", "0").toLong()
        val index = File(run.staging, "files.index.jsonl")
        check(index.length() >= length) { "Staged backup index is incomplete; discard this interrupted run." }
        if (index.exists()) java.io.RandomAccessFile(index, "rw").use { it.setLength(length); it.fd.sync() }
    }
    fun discard() {
        val run = pending() ?: return
        val directory = requireNotNull(run.staging.parentFile).canonicalFile
        check(directory.toPath().startsWith(root.canonicalFile.toPath()) && directory != root.canonicalFile)
        val completed = File(root, "completed.properties")
        Files.move(marker.toPath(), completed.toPath(), StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE)
        check(directory.deleteRecursively())
        completed.delete()
    }
    fun finish(run: Run) { check(pending()?.id == run.id); discard() }
    private fun read(file: File) = Properties().apply { file.inputStream().use { load(it) } }
    private fun digest(file: File): String {
        val hash = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(65536)
            while (true) { val n = input.read(buffer); if (n < 0) break; hash.update(buffer, 0, n) }
        }
        return hash.digest().joinToString("") { "%02x".format(it) }
    }
    private fun write(file: File, properties: Properties) {
        requireNotNull(file.parentFile).mkdirs()
        val next = File(file.parentFile, "${file.name}.next")
        FileOutputStream(next).use { properties.store(it, null); it.fd.sync() }
        Files.move(next.toPath(), file.toPath(), StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE)
    }
}
