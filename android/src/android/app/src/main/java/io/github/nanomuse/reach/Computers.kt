package io.github.nanomuse.reach

import android.content.Context
import com.openminis.app.logging.AppLogger
import io.github.nanomuse.hub.Hub
import io.github.nanomuse.hub.HubException
import org.json.JSONObject
import java.io.File
import java.io.IOException

/**
 * The other devices of the account, as the phone's `nanomuse-pc` sees them, and the calls to
 * them. Everything travels through the hub: a computer joins by running nanoMuse Desktop
 * signed in to the same nanoMuse Cloud account, on any network, and answers the actions
 * itself. (Until 0.1.23 a computer could also be paired over the local network with a
 * stand-alone host script; that path is gone — one way in, the same on every network.)
 *
 * Approvals for what runs there are decided here, on the phone, before a request is sent.
 */
object Computers {
    const val DEEP_LINK = Hub.DEEP_LINK

    data class Computer(
        val id: String,
        val name: String,
        val os: String,
        val hubId: String,
        val kind: String = "computer",
        val online: Boolean = true,
        val lastSeen: Long = 0L,
    ) {
        val address: String get() = "hub"
    }

    private fun asComputer(d: io.github.nanomuse.hub.Device) = Computer(
        id = "hub:" + d.id, name = d.name, os = d.os, hubId = d.id, kind = d.kind, online = d.online, lastSeen = d.lastSeen,
    )

    /** The devices reachable through the hub right now, as computers: other computers and other phones alike. */
    fun hubDevices(context: Context, computersOnly: Boolean = false): List<Computer> =
        Hub.others(context).filter { it.online && (!computersOnly || it.isComputer) }.map(::asComputer)

    /** Every computer of the account the hub knows, online or not, for the settings page. */
    fun known(context: Context): List<Computer> = Hub.others(context).filter { it.isComputer }.map(::asComputer)

    /** Every device a command may go to right now. */
    fun all(context: Context): List<Computer> = hubDevices(context)

    /** By name (case-insensitive), by id; with none named, the only or the first computer. */
    fun resolve(context: Context, nameOrNull: String?): Computer? {
        val all = all(context)
        if (nameOrNull.isNullOrBlank()) return all.firstOrNull { it.kind == "computer" } ?: all.firstOrNull()
        val q = nameOrNull.trim()
        return all.firstOrNull { it.name.equals(q, true) } ?: all.firstOrNull { it.id == q || it.hubId == q }
            ?: all.firstOrNull { it.name.contains(q, true) }
            ?: when (q.lowercase()) {
                "pc", "computer", "desktop", "电脑", "mac", "windows" -> all.filter { it.kind == "computer" }.singleOrNull()
                "phone", "手机" -> all.filter { it.kind == "phone" }.singleOrNull()
                else -> null
            }
    }

    // ── the calls ──────────────────────────────────────────────────────────

    class ReachException(val code: Int, message: String) : IOException(message)

    // The actions travel as JSON frames; the desktop answers them itself.
    private fun hub(c: Computer, action: String, args: JSONObject = JSONObject(), timeoutMs: Long = 120_000L, onEvent: ((JSONObject) -> Unit)? = null): JSONObject =
        try {
            Hub.call(c.hubId, action, args, timeoutMs, onEvent)
        } catch (e: HubException) {
            throw ReachException(
                when (e.code) { "device_offline", "disconnected" -> 503; "timeout" -> 504; "not_allowed" -> 403; "not_found" -> 404; "exists" -> 409; else -> 400 },
                e.message ?: e.code,
            )
        }

    @Throws(IOException::class)
    fun info(c: Computer): JSONObject = hub(c, "info", timeoutMs = 15_000L)

    /** Runs [command] in the computer's shell; the caller has already had it approved. */
    @Throws(IOException::class)
    fun shell(c: Computer, command: String, cwd: String?, timeoutS: Int): JSONObject {
        val body = JSONObject().put("command", command).put("timeout", timeoutS).apply { if (!cwd.isNullOrBlank()) put("cwd", cwd) }
        return hub(c, "shell", body, timeoutMs = timeoutS * 1000L + 30_000L)
    }

    @Throws(IOException::class)
    fun files(c: Computer, path: String?): JSONObject = hub(c, "files", JSONObject().apply { if (path != null) put("path", path) })

    @Throws(IOException::class)
    fun getFile(c: Computer, path: String, dest: File): Long {
        val bytes = android.util.Base64.decode(hub(c, "file.get", JSONObject().put("path", path), timeoutMs = 300_000L).optString("data"), android.util.Base64.DEFAULT)
        dest.parentFile?.mkdirs()
        dest.writeBytes(bytes)
        return bytes.size.toLong()
    }

    @Throws(IOException::class)
    fun putFile(c: Computer, local: File, remotePath: String, force: Boolean = false): JSONObject {
        val data = android.util.Base64.encodeToString(local.readBytes(), android.util.Base64.NO_WRAP)
        return hub(c, "file.put", JSONObject().put("path", remotePath).put("data", data).put("force", force), timeoutMs = 300_000L)
    }

    @Throws(IOException::class)
    fun open(c: Computer, url: String): JSONObject = hub(c, "open", JSONObject().put("url", url))

    /** A picture of the computer's screen, or null when it cannot take one. */
    @Throws(IOException::class)
    fun screen(c: Computer): Pair<ByteArray, String>? {
        val r = try { hub(c, "screen", timeoutMs = 60_000L) } catch (e: ReachException) { if (e.message?.contains("no_screen") == true || e.code == 400) return null else throw e }
        return android.util.Base64.decode(r.optString("data"), android.util.Base64.DEFAULT) to r.optString("mime").ifBlank { "image/jpeg" }
    }

    /** Sends a notification to the device. */
    @Throws(IOException::class)
    fun notify(c: Computer, text: String, title: String?): JSONObject =
        hub(c, "notify", JSONObject().put("text", text).apply { if (!title.isNullOrBlank()) put("title", title) })

    /**
     * Hands a whole task to the Muse running on the device and waits for its answer. Progress
     * arrives through [onEvent]; an `approval` event is a question from that Muse, answered with
     * `approve` — the caller decides how (on the phone: the usual card).
     */
    @Throws(IOException::class)
    fun task(context: Context, c: Computer, text: String, onEvent: (JSONObject) -> Unit): JSONObject =
        hub(
            c,
            "task",
            JSONObject().put("text", text).put("from", Hub.name(context)).put("language", uiLanguage(context)),
            timeoutMs = io.github.nanomuse.hub.HubClient.TASK_TIMEOUT_MS,
            onEvent = onEvent,
        )

    /**
     * The language of this phone's screens as a BCP-47 tag (`zh-Hans-CN`, `en-US`): the hub's
     * optional `language` on `task` (docs/hub.md), so the Muse on the other device answers in
     * it instead of guessing from the text. Older runtimes ignore the field.
     */
    fun uiLanguage(context: Context): String =
        (context.resources.configuration.locales[0] ?: java.util.Locale.getDefault()).toLanguageTag()

    fun approve(c: Computer, approvalId: String, allow: Boolean) {
        runCatching { hub(c, "approve", JSONObject().put("approval_id", approvalId).put("allow", allow), timeoutMs = 30_000L) }
    }

    /** True when the device answers `info` within a few seconds. */
    fun reachable(c: Computer): Boolean = try {
        info(c); true
    } catch (t: Throwable) {
        AppLogger.info(TAG, "${c.name} unreachable: ${t.message}"); false
    }

    // ── what the agent is told ─────────────────────────────────────────────

    fun promptParagraph(context: Context): String {
        val all = all(context)
        val onHub = Hub.isConnected
        return buildString {
            append("## Your devices (nanoMuse)\n")
            if (all.isEmpty()) {
                append("No other device is connected right now. The way to add a computer: install nanoMuse Desktop there (https://nanomuse.cn/#download) and sign in with the same nanoMuse Cloud account as this phone — it appears under [Devices](${Hub.DEEP_LINK}) within seconds, on any network. ")
                append("When the user wants something done on their PC or Mac, say so in one line and point to the desktop app. ")
                if (!onHub) append("This phone is not on the hub itself; signing in to nanoMuse Cloud puts it there. ")
            } else {
                append("Connected: ").append(all.joinToString("; ") { "${it.name} (${it.kind}, ${it.os}, via the hub — any network)" }).append(". ")
                append("`nanomuse-pc run \"<command>\" [--on <device>] [--cwd <dir>] [--timeout <s>]` runs a shell command there and returns exit code, stdout and stderr — the same approval rules as the phone's shell apply, decided on this phone before anything is sent; ")
                append("`nanomuse-pc ls [<path>]` lists a folder; `nanomuse-pc get <remote> [--name <file>]` copies a file into this chat's attachments (pictures then render with `![…](minis://attachments/<file>)`); `nanomuse-pc put <local> <remote>` copies one there; ")
                append("`nanomuse-pc open <url>` opens a page there; `nanomuse-pc screen` takes a picture of its screen into the attachments; `nanomuse-pc notify \"<text>\"` shows a notification there; `nanomuse-pc status` says which devices answer. ")
                append("`nanomuse-pc task \"<what to do, in plain words, with every detail>\" --on <device>` hands a whole task to the Muse running on that device and returns its answer — use it when the job needs that device's own apps, files, screen or judgement (a computer's browser or documents, another phone's apps); it may take minutes, and if that Muse needs an approval the card shows here. ")
                append("The other device's shell is the user's own account: same care as with `rm`, `git push --force` or anything that sends. When it does not answer, say it is offline and point to [Devices](${Hub.DEEP_LINK}).")
            }
        }
    }

    private const val TAG = "Computers"
}
