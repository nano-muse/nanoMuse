package io.github.nanomuse.chat

import java.io.File
import java.io.FileOutputStream
import java.security.MessageDigest
import kotlinx.coroutines.CancellationException

/**
 * Complete, recoverable tool payloads for [ContextTrimming]. The directory belongs to one
 * session and is mounted by the existing sandbox at [LINUX_BASE]. No host path enters a stub.
 */
class ContextTrimStore(private val directory: File) {
    companion object {
        const val LINUX_BASE = "/var/minis/offloads/tools"
    }

    /** Returns a sandbox path only after its bytes have been written and verified. */
    fun write(spill: ContextTrimming.Spill): String? {
        var temporary: File? = null
        try {
            val bytes = spill.content.toByteArray(Charsets.UTF_8)
            val hash = MessageDigest.getInstance("SHA-256").digest(bytes)
            val digest = hash.joinToString("") { "%02x".format(it) }
            val extension = if (spill.kind == ContextTrimming.Kind.RESULT) "txt" else "json"
            // Never interpolate tool names, ids or the caller's cache key into a filename.
            val name = "nm-context-${spill.kind.name.lowercase()}-$digest.$extension"
            val destination = File(directory, name)
            val linuxPath = "$LINUX_BASE/$name"
            if (matches(destination, bytes.size.toLong(), hash)) return linuxPath
            if (!directory.isDirectory && !directory.mkdirs()) return null

            val pending = File.createTempFile(".$name.", ".tmp", directory)
            temporary = pending
            FileOutputStream(pending).use { output ->
                output.write(bytes)
                output.fd.sync()
            }
            if (!matches(pending, bytes.size.toLong(), hash)) return null
            // Both names live in the same directory. rename publishes the complete file,
            // without exposing a half-written destination to a concurrent model read.
            if (!pending.renameTo(destination)) {
                // Another writer may have published the same content in the meantime.
                return if (matches(destination, bytes.size.toLong(), hash)) linuxPath else null
            }
            return if (matches(destination, bytes.size.toLong(), hash)) linuxPath else null
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: Exception) {
            // The caller keeps the full original payload when storage is unavailable.
            return null
        } finally {
            // Best-effort cleanup must not replace a cancellation or storage failure.
            try {
                temporary?.delete()
            } catch (_: SecurityException) {
                // An unremovable temp file is never advertised to the model.
            }
        }
    }

    private fun matches(file: File, length: Long, hash: ByteArray): Boolean {
        if (!file.isFile || file.length() != length) return false
        val digest = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { input ->
            val buffer = ByteArray(8_192)
            while (true) {
                val count = input.read(buffer)
                if (count < 0) break
                digest.update(buffer, 0, count)
            }
        }
        return MessageDigest.isEqual(hash, digest.digest())
    }
}
