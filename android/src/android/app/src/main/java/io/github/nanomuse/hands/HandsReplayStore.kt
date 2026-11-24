package io.github.nanomuse.hands

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.ParcelFileDescriptor
import android.system.Os
import android.system.OsConstants
import com.openminis.app.MinisApp
import io.github.nanomuse.guard.SessionAccess
import io.github.nanomuse.sync.ConversationSync
import io.github.nanomuse.sync.SyncDatabase
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

internal object HandsReplayStore {
    private fun visible(ctx: Context, ticket: HandsReplayAccess.Ticket, session: String): Boolean =
        HandsReplayAccess.current(ctx, ticket) && !SessionAccess.isProtected(session) && session !in ConversationSync.hidden.value

    private suspend fun eligible(ctx: Context, ticket: HandsReplayAccess.Ticket, session: String): Boolean {
        if (!visible(ctx, ticket, session)) return false
        val repository = (ctx.applicationContext as? MinisApp)?.chatRepositoryOrNull ?: return false
        return SyncDatabase.get(ctx).dao().ownedCandidates(ticket.owner, listOf(session)).isNotEmpty() &&
            repository.getSession(session) != null && visible(ctx, ticket, session)
    }

    suspend fun runs(ctx: Context, ticket: HandsReplayAccess.Ticket, chats: Map<String, String?>) = withContext(Dispatchers.IO) {
        if (!HandsReplayAccess.current(ctx, ticket)) return@withContext emptyList()
        val root = ctx.filesDir.canonicalFile
        val owned = SyncDatabase.get(ctx).dao().sessionsOf(ticket.owner).toSet()
        val latest = java.util.PriorityQueue<HandsReplay.Run>(compareBy { it.id })
        for ((session, title) in chats) {
            if (!HandsReplayAccess.current(ctx, ticket)) return@withContext emptyList()
            if (session !in owned || !visible(ctx, ticket, session)) continue
            for (run in runCatching { HandsReplay.list(root, session, title) }.getOrDefault(emptyList())) {
                latest.add(run)
                if (latest.size > HandsTraces.KEEP_RUNS) latest.poll()
            }
        }
        latest.sortedByDescending { it.id }.filter { visible(ctx, ticket, it.session) }
    }

    suspend fun record(ctx: Context, ticket: HandsReplayAccess.Ticket, run: HandsReplay.Run): HandsReplay.Record? = withContext(Dispatchers.IO) {
        if (!eligible(ctx, ticket, run.session)) return@withContext null
        val dir = HandsReplay.runDir(ctx.filesDir.canonicalFile, run) ?: return@withContext null
        val data = read(dir.resolve("trace.jsonl"), HandsReplay.MAX_TRACE + 1, allowPrefix = true)
        val images = runCatching { HandsReplay.screenshots(dir) }.getOrDefault(emptySet())
        val result = read(dir.resolve("result.json"), 4096)
        HandsReplay.record(run.id, data, images, result).takeIf { eligible(ctx, ticket, run.session) }
    }

    suspend fun screenshot(ctx: Context, ticket: HandsReplayAccess.Ticket, run: HandsReplay.Run, frame: HandsReplay.Frame): Bitmap? =
        withContext(Dispatchers.IO) {
            if (!frame.screen || !eligible(ctx, ticket, run.session)) return@withContext null
            val dir = HandsReplay.runDir(ctx.filesDir.canonicalFile, run) ?: return@withContext null
            val data = read(dir.resolve("step-${frame.number}.jpg"), HandsReplay.MAX_SCREEN) ?: return@withContext null
            val options = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            BitmapFactory.decodeByteArray(data, 0, data.size, options)
            if (options.outMimeType != "image/jpeg" || options.outWidth !in 1..16384 || options.outHeight !in 1..16384) return@withContext null
            options.inJustDecodeBounds = false
            options.inSampleSize = 1
            while (maxOf(options.outWidth, options.outHeight) / options.inSampleSize > 1280) options.inSampleSize *= 2
            val bitmap = BitmapFactory.decodeByteArray(data, 0, data.size, options) ?: return@withContext null
            if (eligible(ctx, ticket, run.session)) bitmap else { bitmap.recycle(); null }
        }

    /** Verify the opened descriptor, including its resolved path and link count, before reading any bytes. */
    private fun read(file: File, limit: Int, allowPrefix: Boolean = false): ByteArray? = runCatching {
        val fd = Os.open(file.path, OsConstants.O_RDONLY or OsConstants.O_NOFOLLOW or OsConstants.O_NONBLOCK or OsConstants.O_CLOEXEC, 0)
        try {
            val stat = Os.fstat(fd)
            if (!OsConstants.S_ISREG(stat.st_mode) || stat.st_nlink != 1L || stat.st_size <= 0 ||
                (!allowPrefix && stat.st_size > limit)) return null
            val count = minOf(stat.st_size, limit.toLong()).toInt()
            ParcelFileDescriptor.dup(fd).use { descriptor ->
                if (Os.readlink("/proc/self/fd/${descriptor.fd}") != file.absolutePath) return null
                val data = ByteArray(count)
                var offset = 0
                while (offset < count) {
                    val n = Os.read(fd, data, offset, count - offset)
                    if (n <= 0) return null
                    offset += n
                }
                data
            }
        } finally { Os.close(fd) }
    }.getOrNull()
}
