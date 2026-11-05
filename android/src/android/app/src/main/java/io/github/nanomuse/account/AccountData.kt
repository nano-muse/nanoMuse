package io.github.nanomuse.account

import android.content.Context
import com.openminis.app.MinisApp
import com.openminis.app.logging.AppLogger
import com.openminis.app.scheduled.ScheduledTask
import com.openminis.app.scheduled.ScheduledTaskManager
import io.github.nanomuse.cloud.NanoMuseCloud
import io.github.nanomuse.sync.SessionOwner
import io.github.nanomuse.sync.SyncDatabase
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * What of this phone belongs to the signed-in account, and what happens to it when the
 * account leaves (contract C12, 0.1.40; the table is in `docs/sync.md`).
 *
 * - **Chats** are rows in OpenMinis' database; each has an owner row in ours
 *   (`session_owners`), written the first time the session is seen ([reconcile], [claim]).
 *   The lists show the signed-in owner's; a sign-out without *Keep* deletes the account's
 *   rows, messages, attachments (hands traces included) and sync mappings.
 * - **Files** — the agent's memory of the person (`minis-global/memory`), the feed, the
 *   goals, the face, the shared workspace ([AccountScope.accountPaths]) — and the account's
 *   **preferences** ([AccountScope.accountPrefPrefixes]) and **routines** (the scheduled
 *   tasks) sit at their fixed paths while the account is signed in, so upstream reads them
 *   where it always did. When the account leaves they are put aside under
 *   `minis-global/nanomuse/accounts/<key>/` (*Keep*) or deleted, and the next account's
 *   come back from its own folder or start empty. Signed out, the phone's own set
 *   (`_local`) is in place.
 * - Settings (providers and keys, appearance, hands, the hub's device identity, grants) are
 *   the phone's and never move.
 */
object AccountData {
    private const val TAG = "AccountData"
    private const val PREFS = "nanomuse"
    private const val STASH = "minis-global/nanomuse/accounts"

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    @Volatile private var app: Context? = null

    /** App start; the hooks in upstream code find the context here. */
    fun init(context: Context) {
        app = context.applicationContext
    }

    /** The key the signed-in account's data is filed under; [AccountScope.LOCAL] while signed out. */
    fun key(context: Context): String =
        AccountScope.key(NanoMuseCloud.account(context)?.accountId, NanoMuseCloud.apiKey(context))

    private fun prefs(context: Context) = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    // -- whose chat is whose ------------------------------------------------------------------

    /**
     * Every session has an owner after this; returns the sessions the lists leave out for
     * [current] (the signed-in account's key, or the one given). Cheap: two small queries.
     */
    suspend fun reconcile(context: Context, current: String = key(context)): Set<String> {
        val ctx = context.applicationContext
        val repo = (ctx as? MinisApp)?.chatRepositoryOrNull ?: return emptySet()
        val dao = SyncDatabase.get(ctx).dao()
        val ids = repo.dao.listSessions().map { it.id }
        val owners = dao.owners().associate { it.sessionId to it.owner }
        val syncOwners = dao.conversations().associate { it.sessionId to it.owner }
        val r = AccountScope.reconcile(ids, owners, syncOwners, current)
        if (r.claimed.isNotEmpty()) dao.putOwners(r.claimed.map { (id, owner) -> SessionOwner(id, owner) })
        if (r.stale.isNotEmpty()) dao.removeOwners(r.stale.toList())
        return r.hidden
    }

    /** A chat made now belongs to whoever is signed in now (the hook in `ChatRepository.createSession`). */
    fun claim(sessionId: String) {
        val ctx = app ?: return
        scope.launch {
            runCatching { SyncDatabase.get(ctx).dao().putOwners(listOf(SessionOwner(sessionId, key(ctx)))) }
                .onFailure { AppLogger.warning(TAG, "owner not written for $sessionId: ${it.message}") }
        }
    }

    /** The same, from a coroutine that already runs off the main thread. */
    suspend fun claimNow(context: Context, sessionId: String, owner: String = key(context)) {
        SyncDatabase.get(context.applicationContext).dao().putOwners(listOf(SessionOwner(sessionId, owner)))
    }

    /** The sessions owned by [account]. */
    suspend fun sessionsOf(context: Context, account: String): List<String> =
        SyncDatabase.get(context.applicationContext).dao().sessionsOf(account)

    // -- leaving and entering -----------------------------------------------------------------

    /**
     * The account filed under [account] leaves this phone — a sign-out, a switch, *Delete
     * account*, or a key the relay refused. With [keep] its chats stay in the database (hidden
     * by their owner rows until it is back) and its files, preferences and routines are put
     * aside; without, every one of them is deleted. Call it while [account] is still the
     * signed-in key, and inside `ConversationSync.exclusive` so no push sees the chats go.
     */
    suspend fun leave(context: Context, account: String, keep: Boolean) {
        io.github.nanomuse.hands.HandsRunMemory.shared.clearAll()
        val ctx = context.applicationContext
        stopWork()
        runCatching { reconcile(ctx, account) }.onFailure { AppLogger.warning(TAG, "reconcile before leaving: ${it.message}") }
        if (!keep) deleteChats(ctx, account)
        val stash = File(ctx.filesDir, "$STASH/${AccountScope.dirName(account)}")
        if (keep) stash.mkdirs() else stash.deleteRecursively()
        for (rel in AccountScope.accountPaths) {
            val src = File(ctx.filesDir, rel)
            if (!src.exists()) continue
            if (keep) move(src, File(stash, rel)) else src.deleteRecursively()
        }
        // the preferences that are the account's: remembered on the side, then gone from the file
        val p = prefs(ctx)
        val mine = p.all.filterKeys { AccountScope.isAccountPref(it) }
        if (keep && mine.isNotEmpty()) {
            val o = JSONObject()
            for ((k, v) in mine) o.put(k, v)
            runCatching { File(stash, "prefs.json").writeText(o.toString()) }
        }
        p.edit().apply { mine.keys.forEach { remove(it) } }.apply()
        // the routines: alarms off, the list on the side or gone
        runCatching {
            val manager = ScheduledTaskManager(ctx)
            val tasks = manager.list()
            if (keep && tasks.isNotEmpty()) File(stash, "routines.json").writeText(JSONArray().apply { tasks.forEach { put(it.toJson()) } }.toString())
            tasks.forEach { manager.delete(it.id) }
        }.onFailure { AppLogger.warning(TAG, "routines not put aside: ${it.message}") }
        reloadStores(ctx)
        AppLogger.info(TAG, "account left: ${if (keep) "kept aside" else "removed"}")
    }

    /**
     * What runs for the account stops before its files move: the face being drawn or animated,
     * a screen task under way. Each is asked to stop and waited for, so a result arriving late
     * cannot land in the next account's folder (a feed run ends on its own: the agent runner
     * owns it and writes through the stores, which [reloadStores] re-points).
     */
    private suspend fun stopWork() {
        runCatching { io.github.nanomuse.avatar.AvatarFlow.cancel() }
        runCatching { io.github.nanomuse.avatar.AvatarStudio.stopRuns() }
        runCatching { io.github.nanomuse.avatar.AvatarMotion.stop() }
        runCatching { io.github.nanomuse.hands.Hands.stopCurrent("the account left this phone") }
    }

    /**
     * The account filed under [account] is the signed-in one from now on: what was put aside
     * for it comes back to the fixed paths (nothing, for a first sign-in), the routines are
     * scheduled again, and the stores re-read.
     */
    suspend fun enter(context: Context, account: String) {
        val ctx = context.applicationContext
        val stash = File(ctx.filesDir, "$STASH/${AccountScope.dirName(account)}")
        if (stash.isDirectory) {
            for (rel in AccountScope.accountPaths) {
                val src = File(stash, rel)
                if (!src.exists()) continue
                val dst = File(ctx.filesDir, rel)
                dst.deleteRecursively()
                move(src, dst)
            }
            runCatching {
                val saved = File(stash, "prefs.json").takeIf { it.exists() }?.let { JSONObject(it.readText()) }
                if (saved != null) {
                    val e = prefs(ctx).edit()
                    for (k in saved.keys()) {
                        when (val v = saved.get(k)) {
                            is Boolean -> e.putBoolean(k, v)
                            is Int -> e.putInt(k, v)
                            is Long -> e.putLong(k, v)
                            is Double -> e.putFloat(k, v.toFloat())
                            else -> e.putString(k, v.toString())
                        }
                    }
                    e.apply()
                }
            }.onFailure { AppLogger.warning(TAG, "preferences not restored: ${it.message}") }
            runCatching {
                val saved = File(stash, "routines.json").takeIf { it.exists() }?.let { JSONArray(it.readText()) }
                if (saved != null) {
                    val manager = ScheduledTaskManager(ctx)
                    for (i in 0 until saved.length()) saved.optJSONObject(i)?.let { manager.create(ScheduledTask.fromJson(it)) }
                }
            }.onFailure { AppLogger.warning(TAG, "routines not restored: ${it.message}") }
            stash.deleteRecursively()
        }
        runCatching { reconcile(ctx, account) }
        reloadStores(ctx)
        // the feed's switch and routine are this account's now; a missing routine is made again
        runCatching { io.github.nanomuse.feed.FeedFlow.refresh(ctx) }
    }

    /** `minis-global/nanomuse/accounts/` holds something for [account]. */
    fun hasKept(context: Context, account: String): Boolean =
        File(context.filesDir, "$STASH/${AccountScope.dirName(account)}").isDirectory

    // -- internals ----------------------------------------------------------------------------

    private suspend fun deleteChats(ctx: Context, account: String) {
        val repo = (ctx as? MinisApp)?.chatRepositoryOrNull ?: return
        val dao = SyncDatabase.get(ctx).dao()
        val ids = dao.sessionsOf(account)
        if (ids.isEmpty()) return
        // the mappings first: a push that ran now would otherwise read the gap as a deletion
        // and send tombstones for chats that still exist on the account's other devices
        ids.chunked(500).forEach { dao.removeMessagesOfAll(it); dao.removeConversations(it) }
        for (id in ids) {
            runCatching {
                repo.dao.deleteMessages(id)
                repo.dao.deleteSession(id)
                io.github.nanomuse.guard.Grants.clearSession(id)
                File(ctx.filesDir, "minis-sessions/$id").deleteRecursively()
            }.onFailure { AppLogger.warning(TAG, "chat $id not removed: ${it.message}") }
        }
        ids.chunked(500).forEach { dao.removeOwners(it) }
        AppLogger.info(TAG, "removed ${ids.size} chat(s) of the account that left")
    }

    private fun move(src: File, dst: File) {
        dst.parentFile?.mkdirs()
        if (dst.exists()) dst.deleteRecursively()
        if (src.renameTo(dst)) return
        // another file system (it is not): copy, then delete
        if (src.isDirectory) src.copyRecursively(dst, overwrite = true) else src.copyTo(dst, overwrite = true)
        src.deleteRecursively()
    }

    private fun reloadStores(ctx: Context) {
        runCatching { io.github.nanomuse.feed.FeedStore.reload() }
        runCatching { io.github.nanomuse.goals.GoalStore.get(ctx).reload() }
        runCatching { io.github.nanomuse.avatar.AvatarStore.reload() }
        runCatching { io.github.nanomuse.avatar.OwnClip.rescan() }
        runCatching { com.openminis.app.agent.SoulStore.refreshCache(ctx) }
        runCatching { io.github.nanomuse.home.MainChat.reset() }
    }
}
