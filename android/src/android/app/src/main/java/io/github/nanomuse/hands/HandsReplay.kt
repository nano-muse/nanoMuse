package io.github.nanomuse.hands

import org.json.JSONObject
import java.io.File
import java.nio.file.Files
import java.nio.file.LinkOption.NOFOLLOW_LINKS

/** Read models for archived screen runs. No trace string is a path or an executable action. */
internal object HandsReplay {
    const val MAX_TRACE = 2 * 1024 * 1024
    const val MAX_SCREEN = 4 * 1024 * 1024
    const val MAX_STEPS = 512
    private const val MAX_LINE = 64 * 1024
    private val runId = Regex("""\d{8}-\d{6}(?:-[A-Za-z0-9-]{1,64})?""")
    private val sessionId = Regex("""[A-Za-z0-9_-][A-Za-z0-9._-]{0,149}""")
    private val imageName = Regex("""step-([1-9]\d{0,7})\.jpg""")

    data class Run(val session: String, val id: String, val chat: String?)
    enum class Action { TAP, DOUBLE, HOLD, SWIPE, SCROLL, TYPE, ENTER, OPEN, BACK, HOME, WAIT, USER, DONE, BLOCKED, OTHER }
    data class Frame(val number: Int, val at: Long?, val action: Action, val screen: Boolean,
                     val start: HandsAction.Point? = null, val end: HandsAction.Point? = null, val detail: String = "")
    data class Record(val frames: List<Frame>, val partial: Boolean, val outcome: String?, val mode: String?)

    fun handsRoot(root: File, session: String): File? {
        if (!session.matches(sessionId)) return null
        var dir = root
        for (part in listOf("minis-sessions", session, "attachments", "hands")) {
            dir = File(dir, part)
            if (!Files.isDirectory(dir.toPath(), NOFOLLOW_LINKS)) return null
        }
        return dir
    }
    fun runDir(root: File, run: Run): File? =
        if (!run.id.matches(runId)) null else handsRoot(root, run.session)?.resolve(run.id)?.takeIf { Files.isDirectory(it.toPath(), NOFOLLOW_LINKS) }

    fun list(root: File, session: String, chat: String?): List<Run> {
        val folder = handsRoot(root, session) ?: return emptyList()
        return Files.newDirectoryStream(folder.toPath()).use { paths ->
            paths.asSequence().take(4096).mapNotNull { path ->
                val id = path.fileName.toString()
                if (id.matches(runId) && Files.isDirectory(path, NOFOLLOW_LINKS)) Run(session, id, chat) else null
            }.sortedByDescending { it.id }.take(HandsTraces.KEEP_RUNS).toList()
        }
    }

    fun screenshots(dir: File): Set<Int> = Files.newDirectoryStream(dir.toPath()).use { paths ->
        paths.asSequence().take(4096).mapNotNull { path ->
            imageName.matchEntire(path.fileName.toString())?.groupValues?.get(1)?.toIntOrNull()
                ?.takeIf { Files.isRegularFile(path, NOFOLLOW_LINKS) }
        }.toSortedSet()
    }

    fun record(id: String, trace: ByteArray?, images: Set<Int>, result: ByteArray?): Record {
        val frames = sortedMapOf<Int, Frame>()
        val candidateImages = images.sorted().take(MAX_STEPS).toSet()
        var partial = images.size > MAX_STEPS || (trace?.size ?: 0) > MAX_TRACE
        if (trace != null) {
            // Discard a trailing partial write rather than guessing an action from it.
            var begin = 0
            for (i in 0 until minOf(trace.size, MAX_TRACE)) {
                if (trace[i] != '\n'.code.toByte()) continue
                if (i - begin in 1..MAX_LINE) {
                    val row = runCatching { JSONObject(String(trace, begin, i - begin, Charsets.UTF_8)) }.getOrNull()
                    val n = (row?.opt("step") as? Number)?.toInt() ?: 0
                    if (row != null && n in 1..99_999_999) {
                        if (frames.size >= MAX_STEPS && n !in frames) { partial = true; break }
                        val canonical = "minis://attachments/hands/$id/step-$n.jpg"
                        val screen = n in candidateImages && row.opt("screen") == canonical
                        frames[n] = frame(n, row, screen)
                    }
                } else if (i - begin > MAX_LINE) partial = true
                begin = i + 1
            }
        }
        for (n in candidateImages) {
            // A protected/takeover or interrupted step can have a saved frame but no completed action row.
            if (frames.size == MAX_STEPS && n !in frames) { partial = true; break }
            frames.putIfAbsent(n, Frame(n, null, Action.OTHER, true))
        }
        val meta = result?.takeIf { it.size <= 4096 }?.let { runCatching { JSONObject(it.toString(Charsets.UTF_8)) }.getOrNull() }
        val outcome = meta?.optString("outcome")?.takeIf { it in setOf("done", "ask", "blocked", "stopped", "failed", "max_steps") }
        val mode = meta?.optString("mode")?.takeIf { it == "foreground" || it == "background" }
        return Record(frames.values.toList(), partial, outcome, mode)
    }

    private fun frame(n: Int, row: JSONObject, screen: Boolean): Frame {
        val at = (row.opt("at") as? Number)?.toLong()?.takeIf { it > 0 }
        val action = runCatching { HandsAction.parse(row.optString("reply")).action }.getOrNull()
        val result = row.optString("result")
        fun make(type: Action, start: HandsAction.Point? = null, end: HandsAction.Point? = null, detail: String = "") =
            Frame(n, at, type, screen, start, end, detail.take(80).replace(Regex("[\\p{Cc}\\p{Cf}]"), " "))
        if (result.startsWith("refused:", ignoreCase = true)) return make(Action.BLOCKED)
        return when (action) {
            is HandsAction.Click -> make(Action.TAP, action.at, detail = action.target)
            is HandsAction.DoubleTap -> make(Action.DOUBLE, action.at, detail = action.target)
            is HandsAction.LongPress -> make(Action.HOLD, action.at, detail = action.target)
            is HandsAction.Swipe -> make(Action.SWIPE, action.from, action.to)
            is HandsAction.Scroll -> make(Action.SCROLL, detail = action.direction)
            is HandsAction.InputText -> make(Action.TYPE) // no typed values or raw model reasoning in the viewer
            is HandsAction.OpenApp -> make(Action.OPEN, detail = action.appName)
            is HandsAction.KeyboardEnter -> make(Action.ENTER)
            is HandsAction.Back -> make(Action.BACK)
            is HandsAction.Home -> make(Action.HOME)
            is HandsAction.Wait -> make(Action.WAIT, detail = action.seconds.toString())
            is HandsAction.TakeOver, is HandsAction.AskUser -> make(Action.USER)
            is HandsAction.Status -> make(if (action.complete) Action.DONE else Action.BLOCKED)
            null -> make(Action.OTHER)
        }
    }
}
