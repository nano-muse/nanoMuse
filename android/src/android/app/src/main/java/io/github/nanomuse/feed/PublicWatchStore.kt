package io.github.nanomuse.feed

import android.content.Context
import com.openminis.app.data.MemoryGlobalPrefs
import com.openminis.app.data.db.MessageEntity
import io.github.nanomuse.account.AccountData
import io.github.nanomuse.guard.AppAccess
import io.github.nanomuse.guard.SessionAccess
import io.github.nanomuse.home.MainChat
import io.github.nanomuse.sync.ConversationSync
import io.github.nanomuse.sync.SyncDatabase
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject

/** The feed.* keys travel with this account's existing Keep/Delete choices. */
internal object PublicWatchStore {
    private const val STATE = "feed.public_watches.state"
    private const val ACTIVE = "feed.public_watches.active"
    fun needsChecks(ctx: Context): Boolean = ctx.getSharedPreferences("nanomuse", Context.MODE_PRIVATE).getBoolean(ACTIVE, false)
    private val io = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var engine: PublicWatchEngine? = null
    private var epoch = 0L
    private var switching = false
    val changes = MutableStateFlow(0L)
    data class Scope(val owner: String, val epoch: Long)

    @Synchronized fun accountChange(leaving: Boolean) {
        switching = leaving
        epoch++
        changes.update { it + 1 }
    }
    @Synchronized fun scope(ctx: Context): Scope? {
        if (switching || AppAccess.locked.value) return null
        val main = MainChat.persisted(ctx)
        if (main != null && (SessionAccess.isProtected(main) || main in ConversationSync.hidden.value)) return null
        return Scope(AccountData.key(ctx), epoch)
    }

    @Synchronized fun rules(ctx: Context) = engine ?: PublicWatchEngine(
        ctx.assets.open("nanomuse/public-watches.js").bufferedReader().use { it.readText() }
    ).also { engine = it }

    @Synchronized fun invoke(ctx: Context, expected: Scope, op: String = "view", fields: JSONObject = JSONObject(), revision: Long? = null): JSONObject? {
        if (scope(ctx) != expected) return null
        val prefs = ctx.getSharedPreferences("nanomuse", Context.MODE_PRIVATE)
        val state = JSONObject(prefs.getString(STATE, "{}") ?: "{}")
        val rules = rules(ctx)
        val now = System.currentTimeMillis()
        fun input(action: String) = JSONObject().put("op", action).put("now", now).put("state", state)
        if (revision != null && rules.run(PublicWatchEngine.Entry.LEDGER, input("view")).getLong("revision") != revision) return null
        val input = input(op)
        for (key in fields.keys()) input.put(key, fields.get(key))
        val result = rules.run(PublicWatchEngine.Entry.LEDGER, input)
        if (scope(ctx) != expected) return null
        if (op != "view" && !result.has("error") && result.getJSONObject("state").toString() != state.toString()) {
            val rows = result.getJSONArray("watches")
            val active = result.getBoolean("enabled") && (0 until rows.length()).any { rows.getJSONObject(it).getString("status") == "active" }
            val oldActive = needsChecks(ctx)
            check(prefs.edit().putString(STATE, result.getJSONObject("state").toString()).putBoolean(ACTIVE, active).commit())
            if (active != oldActive) PublicWatchJob.schedule(ctx)
            if (active && (op == "edit" || op == "observe") && result.getLong("revision") != state.optLong("revision"))
                PublicWatchJob.catchUp(ctx, activated = true)
            changes.update { it + 1 }
        }
        return result
    }

    fun readable(ctx: Context, expected: Scope, main: String) =
        scope(ctx) == expected && main == MainChat.persisted(ctx) && !SessionAccess.isProtected(main) &&
            main !in ConversationSync.hidden.value

    /** Called only from the composer receipt path, never on imported history or tool output. */
    fun observe(ctx: Context, row: MessageEntity, receipt: String) {
        val expected = scope(ctx) ?: return
        val main = row.sessionId
        if (!readable(ctx, expected, main) || row.role != "user" || row.partsJson.length > 12_000) return
        val arr = runCatching { JSONArray(row.partsJson) }.getOrNull() ?: return
        val part = arr.optJSONObject(0) ?: return
        if (arr.length() != 1 || part.optString("type") != "text") return
        val text = part.optString("value").takeIf { it.isNotBlank() && it.length <= 6_000 } ?: return
        val app = ctx.applicationContext as? com.openminis.app.MinisApp ?: return
        io.launch {
            runCatching {
                ConversationSync.withStableChats {
                    if (!readable(app, expected, main) || !MemoryGlobalPrefs.isGlobalEnabled(app) ||
                        app.chatRepository.getSession(main)?.memoryEnabled != 1 ||
                        FeedChatEvidence.scope(app, main, true) != receipt ||
                        SyncDatabase.get(app).dao().ownedCandidates(expected.owner, listOf(main)).isEmpty()) return@withStableChats
                    val turn = JSONObject().put("id", FeedPreparation.hash(row.id)).put("text", text)
                        .put("at", row.createdAt).put("personal", true)
                    invoke(app, expected, "observe", JSONObject().put("turns", JSONArray().put(turn)))
                }
            }.onFailure { com.openminis.app.logging.AppLogger.warning("PublicWatches", "discovery deferred: ${it.javaClass.simpleName}") }
        }
    }
}
