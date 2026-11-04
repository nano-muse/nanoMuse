package io.github.nanomuse.sync

import android.content.Context
import androidx.room.withTransaction
import com.openminis.app.MinisApp
import com.openminis.app.R
import com.openminis.app.data.db.AppDatabase
import com.openminis.app.data.db.ChatSessionEntity
import com.openminis.app.data.db.MessageEntity
import com.openminis.app.data.repository.ChatRepository
import io.github.nanomuse.home.MainChat
import java.util.UUID

/** A local chat, as much of it as sync needs. Times in milliseconds. */
data class LocalSession(val id: String, val title: String?, val createdAt: Long, val updatedAt: Long)

/** The phone's chats as the engine reads and writes them; [RoomChats] on the phone, a map in tests. */
interface LocalChats {
    suspend fun sessions(): List<LocalSession>
    suspend fun session(id: String): LocalSession?
    /** In the order the chat shows them. */
    suspend fun messages(sessionId: String): List<LocalMessage>
    /** The main chat's persisted id; null while the home is still an unsaved draft. */
    suspend fun mainSessionId(): String?
    /**
     * The home conversation changes (contract C10: it follows the account): [id] becomes the
     * main chat; null leaves the home on an unsaved draft until the person writes. In tests,
     * the field.
     */
    suspend fun setMainSession(id: String?)
    /** A chat that arrived from another device; with [main] it becomes the home conversation. Returns its id. */
    suspend fun createSession(title: String?, createdAt: Long, updatedAt: Long, main: Boolean): String
    suspend fun renameSession(id: String, title: String?, updatedAt: Long)
    suspend fun deleteSession(id: String)
    suspend fun clearMessages(sessionId: String)
    /** A message from another device, placed by [createdAt] among the chat's rows. Returns the row id. */
    suspend fun insertMessage(sessionId: String, role: String, text: String, attachments: List<Attachment>, createdAt: Long): String
    suspend fun deleteMessage(id: String)
    /**
     * What the chat showed on the app's own behalf before its first row — the scripted opening
     * of the first conversation, which is never written to the database — so the other devices
     * see that conversation from its first word (contract C8). Empty for every other chat; the
     * ids must be the same on every call, since they are mapped to mids like rows.
     */
    suspend fun prelude(sessionId: String): List<TranscriptItem> = emptyList()
    /**
     * Runs [block] as one write to the chats' database, so a pulled page — three hundred rows
     * on a fresh device (C9) — lands at once instead of three hundred times. In tests, just the block.
     */
    suspend fun <T> transaction(block: suspend () -> T): T = block()
}

/** The OpenMinis database, read and written through its own DAO — no schema change, no upstream call that would push again. */
class RoomChats(private val context: Context, private val repo: ChatRepository) : LocalChats {
    private val dao get() = repo.dao
    private val db get() = AppDatabase.getInstance(context).openHelper.writableDatabase

    // The person's own chats. What the phone started on its own — routines, goals, the feed, work for
    // another device, all `source = "scheduled"` — stays here, as on the iPhone and the desktop.
    // Contract C12: a chat another account owns, or one made while signed out, is not this account's to push.
    override suspend fun sessions(): List<LocalSession> {
        val account = io.github.nanomuse.account.AccountData.key(context)
        val others = SyncDatabase.get(context).dao().owners().filter { it.owner != account }.map { it.sessionId }.toSet()
        return dao.listSessions().filter { it.source != "scheduled" && it.id !in others }.map { it.local() }
    }

    override suspend fun session(id: String): LocalSession? = dao.getSession(id)?.local()

    override suspend fun messages(sessionId: String): List<LocalMessage> {
        // in safe mode the loader answers with no rows; read as "every row is gone" that would tombstone the chat
        check(!com.openminis.app.crash.CrashFrequencyDetector.isSafeMode()) { "safe mode: the chats cannot be read" }
        return repo.loadMessages(sessionId).map { LocalMessage(it.id, it.sessionId, it.role, it.partsJson, it.createdAt) }
    }

    override suspend fun mainSessionId(): String? = MainChat.persisted(context)?.takeIf { dao.getSession(it) != null }

    override suspend fun setMainSession(id: String?) {
        if (id == null) MainChat.clear(context) else MainChat.set(context, id)
    }

    override suspend fun createSession(title: String?, createdAt: Long, updatedAt: Long, main: Boolean): String {
        // a model for the row: the one the newest chat uses, else the first the person has
        val modelId = dao.listSessions().firstOrNull()?.modelId
            ?: (context.applicationContext as? MinisApp)?.providerRepositoryOrNull?.allVisibleEntries()?.firstOrNull()?.model?.id
            ?: "unknown"
        val session = ChatSessionEntity(
            id = UUID.randomUUID().toString(),
            title = title?.takeIf { it.isNotBlank() },
            modelId = modelId,
            createdAt = createdAt,
            updatedAt = updatedAt,
            source = "sync",
        )
        dao.insertSession(session)
        io.github.nanomuse.account.AccountData.claimNow(context, session.id) // C12: the account's, from its first row
        if (main) MainChat.set(context, session.id)
        return session.id
    }

    override suspend fun renameSession(id: String, title: String?, updatedAt: Long) {
        dao.updateSessionTitle(id, title.orEmpty(), updatedAt)
    }

    override suspend fun deleteSession(id: String) {
        io.github.nanomuse.hands.HandsRunMemory.shared.clear(id)
        dao.deleteMessages(id)
        dao.deleteSession(id)
        io.github.nanomuse.guard.Grants.clearSession(id)
    }

    override suspend fun clearMessages(sessionId: String) {
        io.github.nanomuse.hands.HandsRunMemory.shared.clear(sessionId)
        dao.deleteMessages(sessionId)
        dao.updateLastMessage(sessionId, null, System.currentTimeMillis())
    }

    override suspend fun insertMessage(sessionId: String, role: String, text: String, attachments: List<Attachment>, createdAt: Long): String {
        val lines = attachments.map { context.getString(R.string.nm_sync_attachment_note, it.name) }
        val partsJson = Transcript.partsJson(text, lines)
        // in time order: rows that came later move down one place
        val after = db.query("SELECT sort_order FROM messages WHERE session_id = ? AND created_at > ? ORDER BY sort_order ASC LIMIT 1", arrayOf<Any>(sessionId, createdAt))
        val sortOrder = after.use { c -> if (c.moveToFirst()) c.getInt(0) else -1 }
        val order = if (sortOrder >= 0) {
            db.execSQL("UPDATE messages SET sort_order = sort_order + 1 WHERE session_id = ? AND sort_order >= ?", arrayOf<Any>(sessionId, sortOrder))
            sortOrder
        } else {
            dao.nextSortOrder(sessionId)
        }
        val row = MessageEntity(
            id = UUID.randomUUID().toString(),
            sessionId = sessionId,
            role = role,
            partsJson = partsJson,
            createdAt = createdAt,
            sortOrder = order,
        )
        dao.insertMessage(row)
        if (sortOrder < 0) {
            // the newest row: the drawer's preview and order follow it
            val session = dao.getSession(sessionId)
            val stamp = maxOf(createdAt, session?.updatedAt ?: 0L)
            dao.updateLastMessage(sessionId, ChatRepository.extractTextPreview(partsJson), stamp)
        }
        return row.id
    }

    override suspend fun deleteMessage(id: String) {
        db.execSQL("DELETE FROM messages WHERE id = ?", arrayOf(id))
    }

    override suspend fun <T> transaction(block: suspend () -> T): T =
        AppDatabase.getInstance(context).withTransaction { block() }

    // the first conversation's opening ("what should I call you?") lives in the view model only;
    // it goes out as one assistant line dated just before the chat, under a fixed id
    override suspend fun prelude(sessionId: String): List<TranscriptItem> {
        val intro = io.github.nanomuse.onboarding.FirstConversation.introOf(context, sessionId) ?: return emptyList()
        val at = dao.getSession(sessionId)?.createdAt ?: return emptyList()
        return listOf(TranscriptItem("nm-intro:$sessionId", "assistant", intro, emptyList(), at - 1000))
    }

    // a blank title and none are the same thing to the relay
    private fun ChatSessionEntity.local() = LocalSession(id, title?.takeIf { it.isNotBlank() }, createdAt, updatedAt)
}
