package io.github.nanomuse.feed

import android.content.Context
import com.openminis.app.R
import com.openminis.app.logging.AppLogger
import io.github.nanomuse.sandbox.FeedSandboxScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import java.io.File
import java.util.Locale

/**
 * The feed on disk: `minis-global/nanomuse/feed/<day>/<NN>.md` posts and the one-paragraph
 * `feed-preferences.md` that steers them. Lives for the process; every write refreshes [posts].
 */
object FeedStore {
    private const val TAG = "Feed"
    private const val MAX_POSTS_PER_DAY = 12
    private const val KEEP_DAYS = 30

    private lateinit var root: File
    private lateinit var prefsFile: File
    private lateinit var appContext: Context

    private val _posts = MutableStateFlow<List<FeedPost>>(emptyList())
    /** Newest day first; inside a day the newest batch first, each batch in the model's order. */
    val posts: StateFlow<List<FeedPost>> = _posts

    private val _preferences = MutableStateFlow("")
    val preferences: StateFlow<String> = _preferences

    fun init(context: Context) {
        appContext = context.applicationContext
        val base = File(context.filesDir, "minis-global/nanomuse")
        root = File(base, "feed").apply { mkdirs() }
        prefsFile = File(base, "feed-preferences.md")
        reload()
        refreshSandbox()
    }

    @Synchronized fun reload() {
        val all = root.listFiles()?.filter(FeedPost::isDayDir)
            ?.sortedByDescending { it.name }
            ?.flatMap { day -> day.listFiles()?.mapNotNull(FeedPost::parse).orEmpty().sortedWith(DAY_ORDER) }
            .orEmpty()
        _posts.value = all
        _preferences.value = runCatching { prefsFile.takeIf { it.exists() }?.readText() }.getOrNull()
            ?.trim().orEmpty().ifEmpty { defaultPreferences() }
    }

    fun defaultPreferences(): String = appContext.getString(R.string.nm_feed_default_preferences)

    fun savePreferences(text: String) {
        runCatching {
            prefsFile.parentFile?.mkdirs()
            prefsFile.writeText(text.trim() + "\n")
        }.onFailure { AppLogger.warning(TAG, "preferences not saved: ${it.message}") }
        _preferences.value = text.trim().ifEmpty { defaultPreferences() }
    }

    @Synchronized fun setLiked(post: FeedPost, liked: Boolean) {
        val updated = post.copy(liked = liked)
        runCatching { post.file.writeText(updated.serialize()) }
            .onSuccess { refreshSandbox() }
            .onFailure { AppLogger.warning(TAG, "like not saved: ${it.message}") }
        _posts.value = _posts.value.map { if (it.file == post.file) updated else it }
    }

    @Synchronized fun delete(post: FeedPost) {
        runCatching { post.file.delete() }
            .onSuccess { refreshSandbox() }
        _posts.value = _posts.value.filterNot { it.file == post.file }
    }

    /** Writes a batch for today and reports posts omitted by the daily limit. */
    @Synchronized fun append(drafts: List<Draft>, now: Long = System.currentTimeMillis()): AppendResult {
        if (drafts.isEmpty()) return AppendResult(emptyList(), 0)
        val day = java.time.Instant.ofEpochMilli(now).atZone(java.time.ZoneId.systemDefault()).toLocalDate().toString()
        val dir = File(root, day).apply { mkdirs() }
        var next = (dir.listFiles()?.mapNotNull { FeedPost.parse(it)?.index }?.maxOrNull() ?: 0) + 1
        val plan = FeedWriteCapacity.plan(next - 1, drafts.size, MAX_POSTS_PER_DAY)
        if (plan.droppedByLimit > 0) {
            AppLogger.warning(TAG, "daily limit of $MAX_POSTS_PER_DAY posts reached; ${plan.droppedByLimit} draft(s) not written")
        }
        val written = mutableListOf<FeedPost>()
        for (d in drafts.take(plan.acceptedCount)) {
            val file = File(dir, "%02d.md".format(Locale.ROOT, next))
            val post = FeedPost(
                day = day, index = next, title = d.title.trim().take(80), type = d.type, emoji = d.emoji,
                body = d.body.trim(), source = d.source, createdAt = now, liked = false, file = file,
                preparation = d.preparation, goalId = d.goalId, sourceSessions = d.sourceSessions, chatBased = d.chatBased,
            )
            runCatching { file.writeText(post.serialize()) }
                .onSuccess { written += post; next++ }
                .onFailure { AppLogger.warning(TAG, "post not written: ${it.message}") }
        }
        prune()
        reload()
        refreshSandbox()
        AppLogger.info(TAG, "wrote ${written.size} post(s) for $day")
        return AppendResult(written, plan.droppedByLimit)
    }

    /** Remaining slots today, calculated using the same daily cap as [append]. */
    fun remainingCapacity(now: Long = System.currentTimeMillis()): Int {
        val day = java.time.Instant.ofEpochMilli(now).atZone(java.time.ZoneId.systemDefault()).toLocalDate().toString()
        val dir = File(root, day)
        val lastIndex = dir.listFiles()?.mapNotNull { FeedPost.parse(it)?.index }?.maxOrNull() ?: 0
        return FeedWriteCapacity.plan(lastIndex, 0, MAX_POSTS_PER_DAY).remainingCapacity
    }

    private fun refreshSandbox() {
        runCatching { FeedSandboxScope.refresh(appContext) }
            .onFailure { AppLogger.warning(TAG, "sandbox feed not refreshed: ${it.message}") }
    }

    private fun prune() {
        val days = root.listFiles()?.filter(FeedPost::isDayDir)?.sortedByDescending { it.name }.orEmpty()
        days.drop(KEEP_DAYS).forEach { it.deleteRecursively() }
    }

    fun hasAnyPost(): Boolean = _posts.value.isNotEmpty()

    fun latestDay(): String? = _posts.value.firstOrNull()?.day

    data class Draft(
        val title: String,
        val type: String,
        val emoji: String,
        val body: String,
        val source: List<String>,
        val preparation: String = "",
        val goalId: String = "",
        val sourceSessions: List<String> = emptyList(),
        val chatBased: Boolean = false,
    )

    data class AppendResult(val written: List<FeedPost>, val droppedByLimit: Int)

    /**
     * The order of one day's posts on the page. A batch is written in one go, so its posts share
     * a `created` time: the newest batch (the evening's) comes first, and inside a batch the posts
     * keep their numbering, which is the model's order, most important first. Sorting the whole
     * day by index put the morning's batch on top and the newest one at the bottom (#555).
     */
    val DAY_ORDER: Comparator<FeedPost> = compareByDescending<FeedPost> { it.createdAt }.thenBy { it.index }
}
