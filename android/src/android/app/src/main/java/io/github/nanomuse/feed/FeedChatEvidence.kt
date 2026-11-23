package io.github.nanomuse.feed

import android.content.Context
import android.content.SharedPreferences
import android.os.FileObserver
import androidx.room.InvalidationTracker
import androidx.sqlite.db.SimpleSQLiteQuery
import com.openminis.app.MinisApp
import com.openminis.app.R
import com.openminis.app.data.MemoryGlobalPrefs
import com.openminis.app.data.db.MessageEntity
import io.github.nanomuse.account.AccountData
import io.github.nanomuse.guard.AppAccess
import io.github.nanomuse.guard.SessionAccess
import io.github.nanomuse.sync.SyncDatabase
import io.github.nanomuse.sysfiles.SystemFiles
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.launch
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.conflate
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import org.json.JSONArray
import java.time.LocalDate
import java.time.ZoneId
import java.util.UUID

/** Account-scoped opt-in. Only the row identity is recorded, so edits and deletion take
 * effect on the next read. No transcript copy and no backfill of old or automated messages. */
object FeedChatEvidence {
    private const val SWITCH = "feed.chat.scope"
    private const val REFERENCES = "feed.chat.rows"
    private const val MAX_ROWS = 64
    private fun prefs(context: Context) = context.getSharedPreferences("nanomuse", Context.MODE_PRIVATE)
    val revision = MutableStateFlow(0L)
    private var changing = false

    @Synchronized fun accountChange(leaving: Boolean) { changing = leaving; revision.update { it + 1 } }
    fun enabled(context: Context): Boolean = prefs(context).contains(SWITCH)

    @Synchronized fun enable(context: Context, value: Boolean) {
        if (changing || value == enabled(context)) return
        val edit = prefs(context).edit().remove(REFERENCES)
        if (value) edit.putString(SWITCH, UUID.randomUUID().toString()) else edit.remove(SWITCH)
        edit.apply()
        if (!value) ChatCheckIns.configure(context, false)
        revision.update { it + 1 }
    }

    /** Snapshot consent at the actual composer action, including when the send is queued. */
    @Synchronized fun scope(context: Context, session: String, memory: Boolean): String? {
        if (!memory || changing || AppAccess.locked.value || !MemoryGlobalPrefs.isGlobalEnabled(context) ||
            SessionAccess.isProtected(session)) return null
        val nonce = prefs(context).getString(SWITCH, null) ?: return null
        return FeedPreparation.hash(AccountData.key(context), nonce)
    }

    private data class Ref(val session: String, val id: String, val textHash: String)
    private fun references(context: Context): List<Ref> {
        val arr = runCatching { JSONArray(prefs(context).getString(REFERENCES, "[]")) }.getOrNull() ?: return emptyList()
        return (0 until minOf(arr.length(), MAX_ROWS)).mapNotNull {
            arr.optJSONArray(it)?.let { row -> if (row.length() == 3) Ref(row.optString(0), row.optString(1), row.optString(2)) else null }
        }
    }

    @Synchronized fun recorded(context: Context, receipt: String?, row: MessageEntity, memory: Boolean) {
        if (receipt == null || row.role != "user" || receipt != scope(context, row.sessionId, memory)) return
        val text = ChatCommitments.plain(row.partsJson, person = true)
        if (text.isEmpty() || !ChatCommitments.relevant(text)) return
        val refs = listOf(Ref(row.sessionId, row.id, FeedPreparation.hash(text))) + references(context)
        val arr = JSONArray()
        refs.distinct().take(MAX_ROWS).forEach { arr.put(JSONArray(listOf(it.session, it.id, it.textHash))) }
        prefs(context).edit().putString(REFERENCES, arr.toString()).apply()
        ChatCheckIns.schedule(context)
        revision.update { it + 1 }
    }

    internal suspend fun facts(app: MinisApp, today: LocalDate): List<FeedPreparation.Fact> {
        val receipt = scope(app, "", true) ?: return emptyList()
        val refs = references(app)
        if (refs.isEmpty()) return emptyList()
        val owned = SyncDatabase.get(app).dao().ownedCandidates(AccountData.key(app), refs.map { it.session }.distinct()).toHashSet()
        val eligible = refs.filter { it.session in owned && !SessionAccess.isProtected(it.session) }
        val cutoff = today.minusDays(ChatCommitments.HISTORY_DAYS - 1).atStartOfDay(ZoneId.systemDefault()).toInstant().toEpochMilli()
        val label = app.getString(R.string.nm_tab_chat)
        return buildList {
            for ((session, markers) in eligible.groupBy { it.session }.entries.take(8)) {
                val chat = app.chatRepository.getSession(session) ?: continue
                if (chat.memoryEnabled == 0 || chat.source == "scheduled" || FeedFlow.isFeedSession(app, session) ||
                    scope(app, session, true) != receipt) continue
                // The bounded projection avoids decoding a large tool payload or assistant trace
                // just to determine whether a writer has already delivered a usable answer.
                val ids = markers.associate { it.id to it.textHash }
                val slots = ids.keys.joinToString(",") { "?" }
                val query = SimpleSQLiteQuery("""SELECT session_id, id, role, created_at,
                    CASE WHEN (role = 'assistant' OR id IN ($slots)) AND length(parts_json) <= 8192 THEN parts_json ELSE '' END AS parts_json
                    FROM (SELECT session_id, id, role, created_at, parts_json, sort_order FROM messages
                    WHERE session_id = ? ORDER BY sort_order DESC LIMIT 48)
                    WHERE created_at >= ? AND role IN ('user', 'assistant') ORDER BY sort_order DESC""", arrayOf<Any>(*ids.keys.toTypedArray(), session, cutoff))
                val lines = app.chatRepository.dao.runMessageSearchQuery(query).asReversed().map { row ->
                    val assistant = row.role == "assistant"
                    val local = row.role == "user" && row.id in ids
                    val text = if (local || assistant) ChatCommitments.plain(row.partsJson, local) else ""
                    val person = local && text.isNotEmpty() && FeedPreparation.hash(text) == ids[row.id]
                    ChatCommitments.Line(session, row.id, person, assistant, text, row.createdAt)
                }
                if (scope(app, session, true) == receipt) addAll(ChatCommitments.facts(lines, today, label))
            }
        }
    }

    /** Watch edits/deletions even when the Feed is already on screen. */
    internal fun changes(app: MinisApp) = callbackFlow {
        val observer = object : InvalidationTracker.Observer("messages", "sessions") {
            override fun onInvalidated(tables: Set<String>) { trySend(Unit) }
        }
        val pref = app.getSharedPreferences("minis_memory_prefs", Context.MODE_PRIVATE)
        val listener = SharedPreferences.OnSharedPreferenceChangeListener { _, _ -> trySend(Unit) }
        app.database.invalidationTracker.addObserver(observer)
        pref.registerOnSharedPreferenceChangeListener(listener)
        val directory = requireNotNull(SystemFiles.USER.file(app).parentFile)
        @Suppress("DEPRECATION")
        val files = object : FileObserver(directory.absolutePath, CLOSE_WRITE or MOVED_FROM or MOVED_TO or DELETE or DELETE_SELF) {
            override fun onEvent(event: Int, path: String?) {
                if (path == null || path.endsWith(".md")) trySend(Unit)
            }
        }
        files.startWatching()
        val midnight = launch {
            val zone = ZoneId.systemDefault()
            while (true) {
                val next = LocalDate.now(zone).plusDays(1).atStartOfDay(zone).toInstant().toEpochMilli()
                delay((next - System.currentTimeMillis()).coerceAtLeast(1000L))
                trySend(Unit)
            }
        }
        trySend(Unit)
        awaitClose {
            midnight.cancel()
            files.stopWatching()
            pref.unregisterOnSharedPreferenceChangeListener(listener)
            app.database.invalidationTracker.removeObserver(observer)
        }
    }.conflate().flowOn(Dispatchers.IO)
}
