package io.github.nanomuse.sync

import android.content.Context
import androidx.room.ColumnInfo
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Index
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

/*
 * What this phone remembers about sync, apart from the chats themselves: which local chat is
 * which `cid`, which local row is which `mid`, what was pushed, and the cursor. Its own small
 * database, so the OpenMinis schema (`minis.db`) stays as upstream ships it.
 */

/** A local chat ↔ a conversation of the account. */
@Entity(tableName = "sync_conversations", indices = [Index(value = ["cid"], unique = true)])
data class SyncConversation(
    @PrimaryKey val sessionId: String,
    val cid: String,
    /** `main` or `side`, fixed when the cid is minted or adopted. */
    val kind: String,
    /** The device that started it (ours for local chats; another for pulled ones — the drawer's badge). */
    val device: String,
    val deviceName: String,
    /** The title as the relay last heard it from us (or gave it to us). */
    val pushedTitle: String?,
    /** The relay knows this conversation. */
    val pushed: Boolean,
    /** Deleted here; the tombstone still has to go out. */
    val deleted: Boolean = false,
    /**
     * The account (`/v1/me` → `account.id`) this conversation was first pushed to or pulled
     * from (contract C10); null for a mapping from before 0.1.39 whose account is unknown.
     * Signed in as another account the chat stays on the phone, unseen and unpushed.
     */
    val owner: String? = null,
)

/** A local message row ↔ a `mid`. Rows that are not part of the transcript have no entry. */
@Entity(tableName = "sync_messages", indices = [Index(value = ["mid"], unique = true), Index(value = ["sessionId"])])
data class SyncMessage(
    @PrimaryKey val messageId: String,
    val mid: String,
    val sessionId: String,
    val pushed: Boolean,
    /** The device that wrote the row — blank for this phone's own; another id for a pulled one (contract C8's caption). */
    @ColumnInfo(defaultValue = "") val device: String = "",
    @ColumnInfo(defaultValue = "") val deviceName: String = "",
)

@Entity(tableName = "sync_meta")
data class SyncMeta(@PrimaryKey val key: String, val value: String)

/**
 * Whose chat a local session is (0.1.40, contract C12): the account key of
 * [io.github.nanomuse.account.AccountData] — the relay's account id — or `""` for a chat made
 * while nobody was signed in. Every session gets a row the first time it is seen; the lists
 * show the signed-in account's rows only, and a sign-out without *Keep* deletes them.
 */
@Entity(tableName = "session_owners", indices = [Index(value = ["owner"])])
data class SessionOwner(@PrimaryKey val sessionId: String, val owner: String)

/** The mapping store, as the engine sees it; [RoomSyncStore] on the phone, a map in tests. */
interface SyncStore {
    suspend fun meta(key: String): String?
    suspend fun putMeta(key: String, value: String?)
    suspend fun conversations(): List<SyncConversation>
    suspend fun conversation(sessionId: String): SyncConversation?
    suspend fun conversationByCid(cid: String): SyncConversation?
    suspend fun putConversation(c: SyncConversation)
    suspend fun removeConversation(sessionId: String)
    suspend fun messages(sessionId: String): List<SyncMessage>
    suspend fun messageByMid(mid: String): SyncMessage?
    /** The rows that came from the relay with a device on them (pulled, not this phone's own). */
    suspend fun pulledMessages(): List<SyncMessage>
    suspend fun putMessages(list: List<SyncMessage>)
    suspend fun removeMessages(messageIds: List<String>)
    suspend fun removeMessagesOf(sessionId: String)
    /** Everything goes out again on the next push (the switch turned back on). */
    suspend fun markAllUnpushed()
    suspend fun clear()

    companion object {
        const val CURSOR = "cursor"
        const val ACCOUNT = "account"
    }
}

@Dao
interface SyncDao {
    @Query("SELECT value FROM sync_meta WHERE `key` = :key")
    suspend fun meta(key: String): String?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun putMeta(row: SyncMeta)

    @Query("DELETE FROM sync_meta WHERE `key` = :key")
    suspend fun removeMeta(key: String)

    @Query("SELECT * FROM sync_conversations")
    suspend fun conversations(): List<SyncConversation>

    @Query("SELECT * FROM sync_conversations WHERE sessionId = :sessionId")
    suspend fun conversation(sessionId: String): SyncConversation?

    @Query("SELECT * FROM sync_conversations WHERE cid = :cid")
    suspend fun conversationByCid(cid: String): SyncConversation?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun putConversation(c: SyncConversation)

    @Query("DELETE FROM sync_conversations WHERE sessionId = :sessionId")
    suspend fun removeConversation(sessionId: String)

    @Query("SELECT * FROM sync_messages WHERE sessionId = :sessionId")
    suspend fun messages(sessionId: String): List<SyncMessage>

    @Query("SELECT EXISTS(SELECT 1 FROM sync_messages WHERE messageId IN (:ids) AND sessionId = :session AND device != '')")
    suspend fun includesPulled(session: String, ids: List<String>): Boolean

    @Query("SELECT * FROM sync_messages WHERE mid = :mid")
    suspend fun messageByMid(mid: String): SyncMessage?

    @Query("SELECT * FROM sync_messages WHERE device != ''")
    suspend fun pulledMessages(): List<SyncMessage>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun putMessages(list: List<SyncMessage>)

    @Query("DELETE FROM sync_messages WHERE messageId IN (:ids)")
    suspend fun removeMessages(ids: List<String>)

    @Query("DELETE FROM sync_messages WHERE sessionId = :sessionId")
    suspend fun removeMessagesOf(sessionId: String)

    @Query("UPDATE sync_messages SET pushed = 0")
    suspend fun unpushMessages()

    @Query("UPDATE sync_conversations SET pushed = 0")
    suspend fun unpushConversations()

    @Query("DELETE FROM sync_messages")
    suspend fun clearMessages()

    @Query("DELETE FROM sync_conversations")
    suspend fun clearConversations()

    @Query("DELETE FROM sync_meta")
    suspend fun clearMeta()

    // -- whose chat is whose (C12) --

    @Query("SELECT * FROM session_owners")
    suspend fun owners(): List<SessionOwner>

    @Query("SELECT sessionId FROM session_owners WHERE owner = :owner")
    suspend fun sessionsOf(owner: String): List<String>

    @Query("SELECT sessionId FROM session_owners WHERE owner = :owner AND sessionId IN (:ids)")
    suspend fun ownedCandidates(owner: String, ids: List<String>): List<String>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun putOwners(list: List<SessionOwner>)

    @Query("DELETE FROM session_owners WHERE sessionId IN (:ids)")
    suspend fun removeOwners(ids: List<String>)

    @Query("DELETE FROM sync_conversations WHERE sessionId IN (:ids)")
    suspend fun removeConversations(ids: List<String>)

    @Query("DELETE FROM sync_messages WHERE sessionId IN (:ids)")
    suspend fun removeMessagesOfAll(ids: List<String>)
}

@Database(entities = [SyncConversation::class, SyncMessage::class, SyncMeta::class, SessionOwner::class], version = 4, exportSchema = false)
abstract class SyncDatabase : RoomDatabase() {
    abstract fun dao(): SyncDao

    companion object {
        @Volatile private var instance: SyncDatabase? = null

        /** 0.1.37: which device wrote a pulled row, for the per-message caption. The ids and the cursor must survive. */
        private val MIGRATION_1_2 = object : Migration(1, 2) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE sync_messages ADD COLUMN device TEXT NOT NULL DEFAULT ''")
                db.execSQL("ALTER TABLE sync_messages ADD COLUMN deviceName TEXT NOT NULL DEFAULT ''")
            }
        }

        /**
         * 0.1.39 (contract C10): whose conversation a mapping is. Every mapping that exists was
         * minted for the account in `sync_meta.account` — until now a change of account wiped
         * the store — so they all become that account's; a store with no account stays null.
         */
        private val MIGRATION_2_3 = object : Migration(2, 3) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("ALTER TABLE sync_conversations ADD COLUMN owner TEXT")
                db.execSQL("UPDATE sync_conversations SET owner = (SELECT value FROM sync_meta WHERE `key` = 'account')")
            }
        }

        /** 0.1.40 (contract C12): whose chat every local session is; filled by [io.github.nanomuse.account.AccountData.reconcile] at the first start. */
        private val MIGRATION_3_4 = object : Migration(3, 4) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL("CREATE TABLE IF NOT EXISTS session_owners (sessionId TEXT NOT NULL PRIMARY KEY, owner TEXT NOT NULL)")
                db.execSQL("CREATE INDEX IF NOT EXISTS index_session_owners_owner ON session_owners(owner)")
            }
        }

        fun get(context: Context): SyncDatabase = instance ?: synchronized(this) {
            instance ?: Room.databaseBuilder(context.applicationContext, SyncDatabase::class.java, "nanomuse_sync.db")
                .addMigrations(MIGRATION_1_2, MIGRATION_2_3, MIGRATION_3_4)
                .fallbackToDestructiveMigration()
                .build()
                .also { instance = it }
        }
    }
}

class RoomSyncStore(private val dao: SyncDao) : SyncStore {
    constructor(context: Context) : this(SyncDatabase.get(context).dao())

    override suspend fun meta(key: String): String? = dao.meta(key)
    override suspend fun putMeta(key: String, value: String?) {
        if (value == null) dao.removeMeta(key) else dao.putMeta(SyncMeta(key, value))
    }
    override suspend fun conversations(): List<SyncConversation> = dao.conversations()
    override suspend fun conversation(sessionId: String): SyncConversation? = dao.conversation(sessionId)
    override suspend fun conversationByCid(cid: String): SyncConversation? = dao.conversationByCid(cid)
    override suspend fun putConversation(c: SyncConversation) = dao.putConversation(c)
    override suspend fun removeConversation(sessionId: String) = dao.removeConversation(sessionId)
    override suspend fun messages(sessionId: String): List<SyncMessage> = dao.messages(sessionId)
    override suspend fun messageByMid(mid: String): SyncMessage? = dao.messageByMid(mid)
    override suspend fun pulledMessages(): List<SyncMessage> = dao.pulledMessages()
    override suspend fun putMessages(list: List<SyncMessage>) {
        if (list.isNotEmpty()) dao.putMessages(list)
    }
    override suspend fun removeMessages(messageIds: List<String>) {
        messageIds.chunked(500).forEach { dao.removeMessages(it) }
    }
    override suspend fun removeMessagesOf(sessionId: String) = dao.removeMessagesOf(sessionId)
    override suspend fun markAllUnpushed() {
        dao.unpushMessages()
        dao.unpushConversations()
    }
    override suspend fun clear() {
        dao.clearMessages()
        dao.clearConversations()
        dao.clearMeta()
    }
}
