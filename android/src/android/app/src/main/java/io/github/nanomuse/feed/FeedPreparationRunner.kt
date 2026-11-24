package io.github.nanomuse.feed

import android.content.Context
import com.openminis.app.MinisApp
import com.openminis.app.R
import com.openminis.app.data.MemoryGlobalPrefs
import com.openminis.app.debug.HeadlessChatRunner.PromptResult
import com.openminis.app.provider.ProviderFactory
import com.openminis.app.service.SessionActivityTracker
import com.openminis.app.scheduled.ScheduledTask
import com.openminis.app.scheduled.ScheduledRepeatMode
import io.github.nanomuse.account.AccountData
import io.github.nanomuse.cloud.Provenance
import io.github.nanomuse.feed.FeedPreparation.Fact
import io.github.nanomuse.feed.FeedPreparation.Kind
import io.github.nanomuse.goals.GoalStatus
import io.github.nanomuse.goals.GoalStore
import io.github.nanomuse.guard.AppAccess
import io.github.nanomuse.guard.SessionAccess
import io.github.nanomuse.sysfiles.SystemFiles
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.job
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout
import org.json.JSONObject
import java.io.File
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

/** One fresh, tool-free completion on selected records. No previous chat transcript is sent. */
internal object FeedPreparationRunner {
    class Run internal constructor(val owner: String, val taskId: String, val session: String, val epoch: Long)
    private var epoch = 0L
    private var switching = false
    private val writing = Mutex()
    private const val REVIEWED = "feed.preparation.reviewed"
    private const val ISSUED = "feed.preparation.issued"
    private const val PUBLISHED = "feed.preparation.date"
    private val quiet get() = PromptResult("Completed", "[quiet]", false)
    const val WRITTEN = "[prepared]"
    @Synchronized fun accountChange(leaving: Boolean) { switching = leaving; epoch++ }

    @Synchronized fun identify(context: Context, task: ScheduledTask): Run? =
        if (task.id == FeedFlow.taskId(context))
            Run(AccountData.key(context), task.id, FeedFlow.sessionId(context).orEmpty(), epoch)
        else null

    @Synchronized fun current(context: Context, run: Run): Boolean = !switching && epoch == run.epoch &&
        AccountData.key(context) == run.owner && FeedFlow.taskId(context) == run.taskId &&
        run.session.isNotEmpty() && FeedFlow.isFeedSession(context, run.session)

    suspend fun prepare(app: MinisApp, run: Run, task: ScheduledTask, automatic: Boolean): PromptResult =
        withContext(Dispatchers.IO) {
            if (!writing.tryLock()) return@withContext quiet
            try {
                fun permitted() = current(app, run) && !AppAccess.locked.value &&
                    !SessionAccess.isProtected(run.session) && FeedFlow.task(app)?.let { live ->
                        // A fired one-shot alarm disarms itself before handing the work off.
                        val armedOnce = task.enabled && task.repeatMode == ScheduledRepeatMode.ONCE && live.repeatMode == task.repeatMode
                        (!automatic || live.enabled || armedOnce) && live.prompt == task.prompt &&
                            live.modelBinding == task.modelBinding && live.modelId == task.modelId
                    } == true
                if (!permitted()) return@withContext quiet
                val today = LocalDate.now()
                val prefs = app.getSharedPreferences("nanomuse", Context.MODE_PRIVATE)
                if (prefs.getString(PUBLISHED, null) == today.toString() || FeedStore.remainingCapacity() == 0)
                    return@withContext quiet
                val session = app.chatRepository.getSession(run.session) ?: return@withContext quiet
                val instructions = FeedStore.preferences.value + "\n" + task.prompt
                val language = app.resources.configuration.locales[0].toLanguageTag()
                val reviewed = runCatching { JSONObject(prefs.getString(REVIEWED, "{}") ?: "{}") }.getOrDefault(JSONObject())
                val oldest = today.minusDays(14).toString()
                fun reviewKey(id: String) = FeedPreparation.hash(id, instructions, language)
                // Keep only identifiers once cards are deleted. The same records stay dismissed
                // across restarts and feed pruning, even if the writer rephrases a card.
                val issued = prefs.getString(ISSUED, "").orEmpty().split(',').filter { it.isNotEmpty() }.toSet()
                val published = issued + FeedStore.posts.value.map { it.preparation }
                suspend fun facts(): List<Fact> {
                    val live = app.chatRepository.getSession(run.session) ?: return emptyList()
                    return gather(app, today, live.memoryEnabled != 0 && MemoryGlobalPrefs.isGlobalEnabled(app))
                }
                val pairs = FeedPreparation.unseen(facts(), published) { pair ->
                    reviewed.optString(reviewKey(pair.id)) >= oldest
                }
                fun sourcesVisible(): Boolean {
                    val locked = SessionAccess.protected.value.mapTo(hashSetOf()) { FeedPreparation.hash(it) }
                    return pairs.none { p -> (p.left.sourceSessions + p.right.sourceSessions).any { it in locked } }
                }
                if (pairs.isEmpty() || !permitted() || !sourcesVisible()) return@withContext quiet
                val repo = app.providerRepository
                val binding = (task.modelBinding ?: session.modelBinding)?.let { JSONObject(it) }
                val usable = repo.allVisibleEntries().filter { entry ->
                    entry.model.isTextOutput && repo.instance(entry.providerInstanceId)?.let { it.isEnabled && repo.hasAnyCredential(it) } == true
                }
                val entry = when (binding?.optString("type")) {
                    "entry" -> usable.find { it.id == binding.getString("entryId") }
                    "group" -> repo.group(binding.getString("groupId"))?.let { group ->
                        val available = repo.availableMemberEntries(group).filter { it.model.isTextOutput }
                        available.find { it.id == binding.optString("lastEntryId") } ?: available.firstOrNull()
                    }
                    else -> usable.find { it.model.id == (task.modelId ?: session.modelId) }
                }
                checkNotNull(entry) { app.getString(R.string.nm_feed_routine_needs_model) }
                val instance = checkNotNull(repo.instance(entry.providerInstanceId))
                val provider = ProviderFactory.create(instance, repo.usableApiKey(instance).orEmpty(), entry.model, app, record = false)
                val reply = try {
                    Provenance.arm(run.session, Provenance.RUN_FEED)
                    withTimeout(90_000L) {
                        val request = currentCoroutineContext().job
                        withContext(Dispatchers.Main.immediate) { SessionActivityTracker.setFeedPreparation { request.cancel() } }
                        val chatPairs = pairs.filter { it.left.kind == Kind.CHAT || it.right.kind == Kind.CHAT }
                        if (!permitted() || chatPairs.isNotEmpty() &&
                            FeedPreparation.revalidate(chatPairs, facts()).size != chatPairs.size) return@withTimeout "[quiet]"
                        if (!permitted() || !sourcesVisible()) return@withTimeout "[quiet]"
                        withContext(Provenance.Session(run.session)) {
                            FeedPreparation.request(provider, pairs, instructions, language)
                        }
                    }
                } finally {
                    Provenance.disarm(run.session)
                    withContext(NonCancellable + Dispatchers.Main.immediate) { SessionActivityTracker.setFeedPreparation(null) }
                }

                if (!permitted() || LocalDate.now() != today) return@withContext quiet
                val live = app.chatRepository.getSession(run.session) ?: return@withContext quiet
                if (session.memoryEnabled != live.memoryEnabled || session.modelBinding != live.modelBinding ||
                    session.modelId != live.modelId) return@withContext quiet
                // The goal, its protection, the diary or the instructions may have changed during generation.
                val evidenceRevision = FeedChatEvidence.revision.value
                val nowFacts = facts()
                synchronized(this@FeedPreparationRunner) {
                    if (!permitted() || FeedStore.preferences.value + "\n" + task.prompt != instructions) return@synchronized quiet
                    if (!sourcesVisible() || evidenceRevision != FeedChatEvidence.revision.value) return@synchronized quiet
                    val valid = FeedPreparation.revalidate(pairs, nowFacts)
                    val proposed = FeedPreparation.draft(reply, valid)
                    if (proposed == null && reply.trim() != "[quiet]") return@synchronized quiet
                    val draft = proposed?.let { FeedFlow.dropDuplicateBodies(listOf(it), FeedStore.posts.value).singleOrNull() }
                    if (draft != null && (FeedStore.posts.value.any { it.preparation == draft.preparation } ||
                            FeedStore.append(listOf(draft)).written.isEmpty())) return@synchronized quiet
                    val keep = JSONObject()
                    for (key in reviewed.keys()) if (reviewed.optString(key) >= oldest) keep.put(key, reviewed.getString(key))
                    val ids = if (draft == null) valid.map { it.id } else listOf(draft.preparation)
                    ids.forEach { keep.put(reviewKey(it), today.toString()) }
                    prefs.edit().apply {
                        if (draft != null) {
                            val selected = valid.single { it.id == draft.preparation }
                            FeedPreparation.relatedAtPublication(selected, nowFacts).forEach { keep.put(reviewKey(it), today.toString()) }
                            putString(ISSUED, (issued + draft.preparation).joinToString(","))
                            putString(PUBLISHED, today.toString())
                        }
                        putString(REVIEWED, keep.toString())
                    }.apply()
                    if (draft == null) quiet else PromptResult("Completed", WRITTEN, false)
                }
            } finally { writing.unlock() }
        }

    internal suspend fun visibleChatCards(app: MinisApp): Set<String> = withContext(Dispatchers.IO) {
        val feed = FeedFlow.sessionId(app)?.let { app.chatRepository.getSession(it) }
        if (feed == null || feed.memoryEnabled == 0 || !MemoryGlobalPrefs.isGlobalEnabled(app) ||
            SessionAccess.isProtected(feed.id) || AppAccess.locked.value || !FeedChatEvidence.enabled(app)) emptySet()
        else FeedPreparation.candidates(gather(app, LocalDate.now(), true))
            .filter { it.left.kind == Kind.CHAT || it.right.kind == Kind.CHAT }.mapTo(hashSetOf()) { it.id }
    }

    internal suspend fun mayDiscuss(app: MinisApp, post: FeedPost): Boolean {
        if (!post.chatBased) return true
        val revision = FeedChatEvidence.revision.value
        val live = visibleChatCards(app)
        return revision == FeedChatEvidence.revision.value && post.preparation in live &&
            !AppAccess.locked.value && post.visibleWith(SessionAccess.protected.value) && post in FeedStore.posts.value
    }

    private suspend fun gather(app: MinisApp, today: LocalDate, memory: Boolean): List<Fact> = buildList {
        val protected = SessionAccess.protected.value
        val goals = GoalStore.get(app).all().filter {
            it.status == GoalStatus.ACTIVE && !it.isProtectedBy(protected) &&
                !it.deadlineDismissed && it.snoozedUntil?.isAfter(today) != true
        }
        goals.sortedByDescending { it.updatedAt }.take(24).forEach { goal ->
            val steps = goal.steps.filterNot { it.done }.map { it.text.trim() }.filter { it.isNotEmpty() }.take(3)
            if (goal.steps.isNotEmpty() && steps.isEmpty()) return@forEach
            val near = goal.due?.let { !it.isAfter(today.plusDays(7)) && !it.isBefore(today.minusDays(7)) } == true
            val recent = !Instant.ofEpochMilli(goal.updatedAt).atZone(ZoneId.systemDefault()).toLocalDate().isBefore(today.minusDays(6))
            val text = (listOf(goal.title, goal.why) + steps.map { "☐ $it" } + listOfNotNull(goal.lastNote, goal.due?.toString()))
                .filter { it.isNotBlank() }.joinToString("\n") { it.take(180) }.take(700)
            val sessions = listOfNotNull(goal.sessionId, goal.sourceSessionId).mapTo(mutableSetOf()) { FeedPreparation.hash(it) }
            add(Fact(Kind.GOAL, "goal/${goal.id}", goal.title.take(80), text, sessions, if (near) 10 else 3, near || recent, goal.id))
        }
        if (!memory) return@buildList
        addAll(FeedChatEvidence.facts(app, today))
        val dir = File(app.filesDir, "minis-global/memory")
        fun read(file: File, kind: Kind, priority: Int) {
            if (!file.isFile || java.nio.file.Files.isSymbolicLink(file.toPath())) return
            val text = runCatching { java.io.RandomAccessFile(file, "r").use { reader ->
                val bytes = ByteArray(minOf(reader.length(), 12_000L).toInt())
                val start = if (kind == Kind.DIARY) reader.length() - bytes.size else 0L
                reader.seek(start)
                reader.readFully(bytes)
                val excerpt = bytes.toString(Charsets.UTF_8)
                if (start == 0L) excerpt else excerpt.substringAfter('\n', "")
            } }.getOrNull() ?: return
            val lines = text.lineSequence().map { it.trim().trimStart('-', '*', ' ').trim().take(400) }
                .filter { it.length >= 8 && !it.startsWith('#') && !it.startsWith("<!--") && !it.startsWith("```") }
                .distinct().toList()
            val latest = if (kind == Kind.DIARY) lines.takeLast(8) else lines.take(8)
            latest.forEach { add(Fact(kind, file.name, file.name, it, priority = priority, timely = kind == Kind.DIARY)) }
        }
        for (offset in 0L until 7) read(File(dir, "${today.minusDays(offset)}.md"), Kind.DIARY, 7 - offset.toInt())
        read(File(dir, "GLOBAL.md"), Kind.MEMORY, 0)
        read(SystemFiles.USER.file(app), Kind.MEMORY, 0)
    }
}
