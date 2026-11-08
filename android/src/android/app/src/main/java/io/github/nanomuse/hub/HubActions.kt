package io.github.nanomuse.hub

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.net.Uri
import android.os.Build
import android.util.Base64
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.openminis.app.MinisApp
import com.openminis.app.R
import com.openminis.app.accessibility.MinisAccessibilityService
import com.openminis.app.data.MemoryGlobalPrefs
import com.openminis.app.debug.HeadlessChatRunner
import com.openminis.app.logging.AppLogger
import com.openminis.app.sandbox.PRootKernel
import io.github.nanomuse.sandbox.SandboxPaths
import com.openminis.app.sandbox.ShellExecutor
import com.openminis.app.service.AgentForegroundService
import io.github.nanomuse.cloud.Provenance
import io.github.nanomuse.guard.GateOutcome
import io.github.nanomuse.guard.GuardKind
import io.github.nanomuse.guard.RiskAssessment
import io.github.nanomuse.guard.RiskClass
import io.github.nanomuse.guard.RiskDecision
import io.github.nanomuse.guard.RiskGate
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File

/**
 * What the other devices may ask of this phone, and how each is carried out here.
 *
 *  - `info`, `files`, `file.get`, `file.put`, `shell`: the phone's Linux sandbox — the same
 *    filesystem and shell the agent itself uses; never Android's own storage or shell.
 *  - `open`, `notify`: a URL to the matching app, a notification on this phone.
 *  - `screen`: a picture of the screen, when the accessibility service is on (Hands).
 *  - `task`: a whole task in words for this phone's own agent, in a conversation of its own;
 *    whatever needs an approval shows the usual card here, on the phone.
 *
 * The caller has already judged a `shell` command before sending it (the desktop's guard, the
 * phone's ShellGuard); "Remote control" off refuses everything but `info`. With it on, the
 * person holding this phone still agrees before another device runs, reads or writes something
 * here (0.1.31): the usual card, allowed once or always for that device — a grant listed under
 * Permissions like the others. `notify` and `info` never ask; a `task` runs under this phone's
 * own guard.
 */
object HubActions {
    private const val TAG = "HubActions"
    private const val FILE_LIMIT = 8L * 1024 * 1024
    private const val TASK_TIMEOUT_MS = 10 * 60 * 1000L
    private const val CHANNEL = "nanomuse_hub"
    private const val PREFS = "nanomuse"
    /** What another device does *to* this phone: the person here agrees first. */
    private val GATED = setOf("shell", "files", "file.get", "file.put", "open", "screen")
    /** Cards of tasks running here that travelled to the device that asked (card id → device id). */
    private val relayed = java.util.concurrent.ConcurrentHashMap<String, String>()
    /** Tasks running here for other devices, so `stop` can find them. */
    private val running = HubTasks()

    fun handle(context: Context, call: IncomingCall) {
        if (call.action == "info") { call.result(info(context)); return }
        if (!Hub.remoteControl(context)) { call.fail("not_allowed", "${Hub.name(context)} is set not to be operated from other devices"); return }
        AppLogger.info(TAG, "${call.senderName} → ${call.action}")
        if (call.action in GATED && !permitted(context, call)) {
            call.fail("not_allowed", "the person holding ${Hub.name(context)} did not allow ${call.senderName} to do that")
            return
        }
        try {
            when (call.action) {
                "shell" -> shell(context, call)
                "files" -> call.result(files(context, call.args.optString("path").ifBlank { "/root" }))
                "file.get" -> call.result(fileGet(context, call.args.optString("path")))
                "file.put" -> call.result(filePut(context, call.args.optString("path"), call.args.optString("data"), call.args.optBoolean("force")))
                "open" -> call.result(open(context, call.args.optString("url")))
                "screen" -> call.result(screen())
                "notify" -> call.result(notify(context, call.args.optString("text"), call.args.optString("title").ifBlank { "nanoMuse" }, call.senderName))
                "task" -> call.result(task(context, call))
                "task.status" -> call.result(PersistentTaskEndpoint.get(context).status(
                    PersistentTaskEndpoint.owner(context, call), call.args.optString("turn_id"),
                ))
                "approve" -> approve(call)
                "stop" -> call.result(JSONObject().put("stopped", stop(context, call)))
                else -> call.fail("unknown_action", "this phone does not do '${call.action}'")
            }
        } catch (e: Refused) {
            call.fail(e.code, e.message ?: e.code)
        }
    }

    class Refused(val code: String, message: String) : Exception(message)

    /**
     * The card for another device's request: "Allow “Desk” to operate this phone?", the
     * command or path in the preview box, *always for Desk* bound to the device's id.
     */
    private fun permitted(context: Context, call: IncomingCall): Boolean {
        val senderId = call.from.optString("id").ifBlank { call.senderName }
        val what = listOf("command", "path", "url", "text").firstNotNullOfOrNull { k -> call.args.optString(k).trim().ifEmpty { null } }.orEmpty()
        val assessment = RiskAssessment(
            riskClass = RiskClass.REMOTE,
            reason = context.getString(R.string.nm_hub_remote_reason, call.senderName),
            target = "device:$senderId",
        )
        val preview = if (what.isEmpty()) call.action else "${call.action}: ${what.take(300)}"
        val outcome = runBlocking {
            RiskGate.check("hub:$senderId", GuardKind.DEVICE, assessment, preview, pageUrl = call.senderName, elementText = call.action)
        }
        return outcome is GateOutcome.Allowed
    }

    // ── info ───────────────────────────────────────────────────────────────

    fun info(context: Context): JSONObject = JSONObject()
        .put("name", Hub.name(context))
        .put("os", "Android ${Build.VERSION.RELEASE}")
        .put("model", "${Build.MANUFACTURER} ${Build.MODEL}")
        .put("app", "nanoMuse ${Hub.VERSION}")
        .put("sandbox", if (PRootKernel.isBooted) "ready" else "not booted")
        .put("screen", MinisAccessibilityService.getInstance() != null)
        .put("actions", JSONArray(Hub.ACTIONS))
        .put("note", "shell and files live in the phone's Linux sandbox (Alpine); use `task` for anything that needs the phone's apps")

    // ── the sandbox ────────────────────────────────────────────────────────

    private fun shell(context: Context, call: IncomingCall) {
        val command = call.args.optString("command").trim()
        if (command.isEmpty()) { call.fail("usage", "a command is required"); return }
        boot(context)
        val timeoutS = call.args.optInt("timeout", 120).coerceIn(1, 900)
        val cwd = call.args.optString("cwd").trim()
        val full = if (cwd.isNotEmpty()) "cd ${shellQuote(cwd)} && $command" else command
        val r = runBlocking { ShellExecutor.execute(context, full, timeout = timeoutS * 1000L) }
        call.result(
            JSONObject()
                .put("exit_code", r.exitCode)
                .put("stdout", r.output.take(200_000))
                .put("stderr", "")
                .put("timed_out", r.exitCode == 124 || r.durationMs >= timeoutS * 1000L)
                .put("duration_ms", r.durationMs),
        )
    }

    private fun shellQuote(s: String): String = "'" + s.replace("'", "'\\''") + "'"

    /** The sandbox boots on first use, exactly as it does for the phone's own agent. */
    private fun boot(context: Context) {
        if (PRootKernel.isBooted) return
        try {
            runBlocking { PRootKernel.boot(context.applicationContext) }
        } catch (e: Exception) {
            throw Refused("sandbox_not_ready", "the phone's sandbox could not start: ${e.message}")
        }
    }

    /** A sandbox path → the host file behind it; `~` is the sandbox home. */
    private fun host(context: Context, path: String): File {
        boot(context)
        val linux = when {
            path.isBlank() || path == "~" -> "/root"
            path.startsWith("~/") -> "/root/" + path.removePrefix("~/")
            path.startsWith("minis://attachments/") -> "/var/minis/attachments/" + path.removePrefix("minis://attachments/")
            !path.startsWith("/") -> "/root/$path"
            else -> path
        }
        // Confined to the sandbox: `..` and symlinks out of the rootfs resolve to nothing.
        return SandboxPaths.host(context, linux, null)
            ?: throw Refused("not_found", "$path is not inside the phone's sandbox")
    }

    private fun files(context: Context, path: String): JSONObject {
        val dir = host(context, path)
        if (!dir.exists()) throw Refused("not_found", "$path does not exist on the phone")
        val entries = JSONArray()
        if (dir.isFile) {
            entries.put(entry(dir))
        } else {
            dir.listFiles()?.sortedWith(compareBy({ !it.isDirectory }, { it.name.lowercase() }))?.take(2000)?.forEach { entries.put(entry(it)) }
        }
        return JSONObject().put("path", path).put("entries", entries)
    }

    private fun entry(f: File): JSONObject = JSONObject()
        .put("name", f.name)
        .put("type", if (f.isDirectory) "dir" else "file")
        .put("size", f.length())
        .put("mtime", f.lastModified() / 1000)

    private fun fileGet(context: Context, path: String): JSONObject {
        val f = host(context, path)
        if (!f.isFile) throw Refused("not_found", "$path is not a file on the phone")
        if (f.length() > FILE_LIMIT) throw Refused("too_large", "${f.name} is ${f.length()} bytes; the limit over the hub is $FILE_LIMIT")
        return JSONObject()
            .put("path", path).put("name", f.name).put("bytes", f.length()).put("mime", mime(f.name))
            .put("data", Base64.encodeToString(f.readBytes(), Base64.NO_WRAP))
    }

    private fun filePut(context: Context, path: String, data: String, force: Boolean): JSONObject {
        if (path.isBlank()) throw Refused("usage", "a path is required")
        val f = host(context, path)
        if (f.isDirectory) throw Refused("is_dir", "$path is a folder")
        if (f.exists() && !force) throw Refused("exists", "$path already exists on the phone; force replaces it")
        val bytes = Base64.decode(data, Base64.DEFAULT)
        f.parentFile?.mkdirs()
        val tmp = File(f.parentFile, f.name + ".nanomuse-part")
        tmp.writeBytes(bytes)
        if (!tmp.renameTo(f)) { f.writeBytes(bytes); tmp.delete() }
        return JSONObject().put("path", path).put("bytes", bytes.size)
    }

    private fun mime(name: String): String = when (name.substringAfterLast('.', "").lowercase()) {
        "png" -> "image/png"; "jpg", "jpeg" -> "image/jpeg"; "gif" -> "image/gif"; "webp" -> "image/webp"
        "pdf" -> "application/pdf"; "txt" -> "text/plain"; "md" -> "text/markdown"; "json" -> "application/json"; "csv" -> "text/csv"
        else -> "application/octet-stream"
    }

    // ── the phone itself ───────────────────────────────────────────────────

    private fun open(context: Context, url: String): JSONObject {
        val target = url.trim()
        if (target.isEmpty()) throw Refused("usage", "a URL is required")
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(target)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        return try {
            context.startActivity(intent)
            JSONObject().put("ok", true).put("url", target)
        } catch (e: Exception) {
            throw Refused("no_app", "nothing on the phone opens $target: ${e.message}")
        }
    }

    private fun screen(): JSONObject {
        val svc = MinisAccessibilityService.getInstance() ?: throw Refused("no_screen", "the phone's accessibility service is off; turn on Hands in Settings")
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) throw Refused("no_screen", "screenshots need Android 11")
        val shot = svc.captureScreenshot(timeoutMs = 6_000)
        val bmp = shot.bitmap ?: throw Refused("no_screen", "screenshot failed: ${shot.errorMessage ?: shot.errorCode}")
        val scaled = if (bmp.width > 1080) Bitmap.createScaledBitmap(bmp, 1080, (bmp.height * 1080f / bmp.width).toInt().coerceAtLeast(1), true) else bmp
        val out = ByteArrayOutputStream()
        scaled.compress(Bitmap.CompressFormat.JPEG, 80, out)
        if (scaled !== bmp) scaled.recycle()
        val bytes = out.toByteArray()
        return JSONObject().put("mime", "image/jpeg").put("bytes", bytes.size).put("data", Base64.encodeToString(bytes, Base64.NO_WRAP))
    }

    private fun notify(context: Context, text: String, title: String, from: String): JSONObject {
        if (text.isBlank()) throw Refused("usage", "text is required")
        val nm = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && nm.getNotificationChannel(CHANNEL) == null) {
            nm.createNotificationChannel(NotificationChannel(CHANNEL, context.getString(R.string.nm_hub_channel), NotificationManager.IMPORTANCE_DEFAULT))
        }
        val open = context.packageManager.getLaunchIntentForPackage(context.packageName)?.let {
            PendingIntent.getActivity(context, 0, it, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        }
        val n = NotificationCompat.Builder(context, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_nanomuse)
            .setContentTitle(title)
            .setContentText(text)
            .setSubText(from)
            .setStyle(NotificationCompat.BigTextStyle().bigText(text))
            .setAutoCancel(true)
            .apply { if (open != null) setContentIntent(open) }
            .build()
        // Android 13+ asks the person before an app may notify, and a channel can be silenced
        // on its own; `notify` would then drop the notice without a word, and the caller would
        // tell the person it was shown.
        val blocked = !NotificationManagerCompat.from(context).areNotificationsEnabled() ||
            (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O &&
                nm.getNotificationChannel(CHANNEL)?.importance == NotificationManager.IMPORTANCE_NONE)
        if (blocked) {
            return JSONObject().put("ok", false).put("shown", false).put("message", "notifications are not allowed for nanoMuse on this phone")
        }
        return try {
            nm.notify((System.currentTimeMillis() % 100_000).toInt() + 40_000, n)
            JSONObject().put("ok", true).put("shown", true)
        } catch (e: SecurityException) {
            JSONObject().put("ok", false).put("shown", false).put("message", "notifications are not allowed for nanoMuse on this phone")
        }
    }

    // ── a task for this phone's agent ──────────────────────────────────────

    private fun task(context: Context, call: IncomingCall): JSONObject {
        val text = call.args.optString("text").trim()
        if (text.isEmpty()) throw Refused("usage", "text is required")
        val app = context.applicationContext as? MinisApp
        if (app == null || !app.subsystemsReady()) throw Refused("not_ready", "nanoMuse on the phone is still starting")
        val senderId = call.from.optString("id")
        val conversation = running.conversationKey(senderId, call.args.optString("conversation"))
        if (call.args.has("turn_id")) {
            val owner = PersistentTaskEndpoint.owner(context, call)
            return PersistentTaskEndpoint.get(context).run(owner, call.args.optString("turn_id"), call, create = {
                if (!call.args.optBoolean("new_conversation")) throw Refused("context_lost", "The remote conversation no longer exists")
                runBlocking { createTaskSession(app, call.senderName) } ?: throw Refused("no_model", "The phone has no model configured")
            }) { sessionId, emit ->
                if (PersistentTaskEndpoint.owner(context, call) != owner) throw Refused("denied", "The account changed")
                if (runBlocking { app.chatRepository.dao.getSession(sessionId) } == null) {
                    throw Refused("context_lost", "The remote conversation no longer exists")
                }
                executeTask(app, call, text, conversation, sessionId, emit)
            }
        }
        val sessionId = runBlocking { sessionFor(app, conversation, call.senderName) }
            ?: throw Refused("no_model", "the phone has no model to think with; sign in to nanoMuse Cloud there")
        return executeTask(app, call, text, conversation, sessionId)
    }

    private fun executeTask(
        context: MinisApp, call: IncomingCall, text: String, conversation: String, sessionId: String,
        emit: (JSONObject) -> Unit = call::event,
    ): JSONObject {
        val senderId = call.from.optString("id")
        emit(JSONObject().put("stage", "thinking").put("session", sessionId))
        AgentForegroundService.startService(context, sessionCount = 1, toolStatus = context.getString(R.string.nm_hub_task_from, call.senderName))
        val prompt = HubTasks.prompt(
            text,
            prefix = if (call.senderKind == "web") null else context.getString(R.string.nm_hub_task_prefix, call.senderName),
            language = call.args.optString("language"),
        )
        val relay = relayApprovals(context, call, sessionId, emit)
        running.started(call.id, senderId, conversation, sessionId)
        Provenance.arm(sessionId, Provenance.RUN_HUB) // the turn is another device's, for the record
        val stopped: Boolean
        val result = try {
            runBlocking {
                HeadlessChatRunner.prompt(context = context, sessionId = sessionId, text = prompt, attachments = emptyList(), thinkingLevel = null, wait = true, timeoutMs = TASK_TIMEOUT_MS)
            }
        } finally {
            relay.cancel()
            stopped = running.finished(call.id)
        }
        if (stopped) throw Refused("cancelled", "${call.senderName} stopped this task")
        val answer = result.responseText?.trim().orEmpty()
        if (result.timedOut) throw Refused("timeout", "the phone's agent did not finish within ten minutes")
        if (result.status == "Error" && answer.isEmpty()) throw Refused("failed", "the phone's agent could not run this")
        return JSONObject().put("text", answer.ifBlank { "(no answer)" }).put("conversation", conversation).put("session", sessionId)
            .put("device", Hub.name(context)).put("status", result.status)
    }

    /**
     * While a task from another device runs here, its approval cards travel to that device as
     * `approval` events (docs/hub.md), so the person can answer from where they are — the card
     * on this phone's screen stays too, and whichever side answers first decides. The decision
     * goes back as `approval_result`.
     */
    private fun relayApprovals(context: Context, call: IncomingCall, sessionId: String, emit: (JSONObject) -> Unit): CoroutineScope {
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
        val seen = HashSet<String>()
        scope.launch {
            RiskGate.pending.collect { req ->
                if (req != null && req.sessionId == sessionId && seen.add(req.id)) {
                    relayed[req.id] = call.from.optString("id")
                    emit(
                        JSONObject().put("stage", "approval").put("approval_id", req.id).put("preview", req.preview)
                            .put("risk", req.assessment.riskClass.name.lowercase()).put("reason", req.assessment.reason)
                            .put("device", Hub.name(context)).put("timeout", RiskGate.TIMEOUT_MS / 1000),
                    )
                }
            }
        }
        scope.launch {
            val reported = HashSet<String>()
            RiskGate.recent.collect { recent ->
                for ((req, decision) in recent) {
                    if (req.id in seen && reported.add(req.id)) {
                        relayed.remove(req.id)
                        val status = when (decision) {
                            RiskDecision.DENY -> "denied"
                            RiskDecision.TIMEOUT -> "expired"
                            else -> "approved"
                        }
                        emit(JSONObject().put("stage", "approval_result").put("approval_id", req.id).put("status", status))
                    }
                }
            }
        }
        return scope
    }

    /**
     * `stop {call}` or `stop {conversation}` from the device that asked for a task: ends the run
     * here after the step in flight, the way Stop in the chat does; the task then answers
     * `cancelled`. Only the asker's own runs; `{stopped: false}` when there is nothing to end.
     */
    private fun stop(context: Context, call: IncomingCall): Boolean {
        val id = if (call.args.has("turn_id")) {
            PersistentTaskEndpoint.get(context).callId(PersistentTaskEndpoint.owner(context, call), call.args.optString("turn_id"))
                ?: return false
        } else call.args.optString("call")
        val conversation = call.args.optString("conversation").takeUnless { call.args.has("turn_id") }
        return running.stop(call.from.optString("id"), id, conversation) { sessionId ->
            runBlocking { runCatching { HeadlessChatRunner.cancel(context, sessionId) }.getOrDefault(false) }
        }
    }

    /**
     * `approve {approval_id, allow}` from the device that asked for the task: decides the card
     * here — only a card of its own run that travelled to it, never the card asking the person
     * here whether that device may do something.
     */
    private fun approve(call: IncomingCall) {
        val id = call.args.optString("approval_id")
        if (id.isBlank()) { call.fail("usage", "approval_id is required"); return }
        if (relayed[id] != call.from.optString("id")) { call.result(JSONObject().put("ok", false).put("approval_id", id)); return }
        val allow = call.args.optBoolean("allow", false)
        RiskGate.decide(id, if (allow) RiskDecision.ALLOW_ONCE else RiskDecision.DENY, by = RiskGate.BY_OTHER_DEVICE)
        call.result(JSONObject().put("ok", true).put("approval_id", id).put("status", if (allow) "approved" else "denied"))
    }

    /** One conversation per remote conversation id, created like a goal's own: seeded from the default group. */
    private suspend fun sessionFor(app: MinisApp, conversation: String, sender: String): String? {
        val p = app.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val key = "hub.session.$conversation"
        p.getString(key, null)?.let { existing ->
            if (runCatching { app.chatRepository.dao.getSession(existing) }.getOrNull() != null) return existing
        }
        val sessionId = createTaskSession(app, sender) ?: return null
        p.edit().putString(key, sessionId).apply()
        return sessionId
    }

    private suspend fun createTaskSession(app: MinisApp, sender: String): String? {
        val providers = app.providerRepository
        val defaultGroupId = providers.defaultPrimaryGroupId
        val seedModelId = defaultGroupId
            ?.let { providers.group(it) }
            ?.let { g -> providers.availableMemberEntries(g).firstOrNull()?.model?.id }
            ?: providers.allVisibleEntries().firstOrNull()?.baseModel?.id
            ?: return null
        val session = app.chatRepository.createSession(
            modelId = seedModelId,
            title = app.getString(R.string.nm_hub_session_title, sender),
            memoryEnabled = MemoryGlobalPrefs.isGlobalEnabled(app),
        )
        app.chatRepository.dao.updateSource(session.id, "scheduled")
        if (defaultGroupId != null) {
            app.chatRepository.updateSessionBinding(session.id, """{"type":"group","groupId":"$defaultGroupId"}""", seedModelId)
        }
        return session.id
    }
}
