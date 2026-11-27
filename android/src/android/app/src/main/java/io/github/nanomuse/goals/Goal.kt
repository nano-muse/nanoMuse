package io.github.nanomuse.goals

import io.github.nanomuse.stringOrNull
import org.json.JSONArray
import org.json.JSONObject
import java.util.UUID

/** Muse's goal categories, in the order the Goals tab lists them. */
enum class GoalCategory(val key: String) {
    HEALTH("health"),
    RELATIONSHIPS("relationships"),
    FINANCE("finance"),
    CAREER("career"),
    INTERESTS("interests"),
    PRODUCTIVITY("productivity"),
    OTHER("other");

    companion object {
        fun fromKey(key: String?): GoalCategory = entries.firstOrNull { it.key == key } ?: OTHER
    }
}

enum class GoalStatus { ACTIVE, PAUSED, DONE }

data class GoalStep(val text: String, val done: Boolean = false) {
    fun toJson(): JSONObject = JSONObject().put("text", text).put("done", done)

    companion object {
        fun fromJson(o: JSONObject) = GoalStep(o.optString("text", ""), o.optBoolean("done", false))
    }
}

/**
 * A goal the agent keeps an eye on: what, why, how often to check, the steps it proposed, and
 * where it stands. The periodic check is a hidden ScheduledTask ([taskId]) that appends to the
 * goal's own session ([sessionId]); each check ends with a `nanomuse-goal-update` block that
 * [GoalStore.applyUpdate] folds back in here.
 */
data class Goal(
    val id: String = UUID.randomUUID().toString(),
    val title: String,
    val why: String = "",
    val category: GoalCategory = GoalCategory.OTHER,
    /** 0 = a daily check at [checkHour]:[checkMinute]; otherwise every N hours. */
    val checkEveryHours: Int = 0,
    val checkHour: Int = 9,
    val checkMinute: Int = 0,
    val steps: List<GoalStep> = emptyList(),
    val progress: Int = 0,
    val status: GoalStatus = GoalStatus.ACTIVE,
    val sessionId: String? = null,
    val taskId: String? = null,
    val lastNote: String? = null,
    val lastCheckedAt: Long? = null,
    val createdAt: Long = System.currentTimeMillis(),
    val updatedAt: Long = createdAt,
    val due: java.time.LocalDate? = null,
    val snoozedUntil: java.time.LocalDate? = null,
    val deadlineDismissed: Boolean = false,
    /** The conversation which created this goal. Older goals only recorded their own conversation. */
    val sourceSessionId: String? = null,
) {
    fun isProtectedBy(sessions: Set<String>): Boolean = sessionId in sessions || sourceSessionId in sessions

    fun withDue(date: java.time.LocalDate?): Goal =
        if (date == due) this else copy(due = date, snoozedUntil = null, deadlineDismissed = false)

    fun toJson(): JSONObject = JSONObject().apply {
        due?.let { put("due", it.toString()) }
        snoozedUntil?.let { put("snoozedUntil", it.toString()) }
        if (deadlineDismissed) put("deadlineDismissed", true)
        put("id", id)
        put("title", title)
        put("why", why)
        put("category", category.key)
        put("checkEveryHours", checkEveryHours)
        put("checkHour", checkHour)
        put("checkMinute", checkMinute)
        put("steps", JSONArray().apply { steps.forEach { put(it.toJson()) } })
        put("progress", progress)
        put("status", status.name)
        if (sessionId != null) put("sessionId", sessionId)
        if (sourceSessionId != null) put("sourceSessionId", sourceSessionId)
        if (taskId != null) put("taskId", taskId)
        if (lastNote != null) put("lastNote", lastNote)
        if (lastCheckedAt != null) put("lastCheckedAt", lastCheckedAt)
        put("createdAt", createdAt)
        put("updatedAt", updatedAt)
    }

    companion object {
        fun fromJson(o: JSONObject): Goal = Goal(
            id = o.optString("id", UUID.randomUUID().toString()),
            title = o.optString("title", ""),
            why = o.optString("why", ""),
            category = GoalCategory.fromKey(o.stringOrNull("category")),
            checkEveryHours = o.optInt("checkEveryHours", 0),
            checkHour = o.optInt("checkHour", 9),
            checkMinute = o.optInt("checkMinute", 0),
            steps = o.optJSONArray("steps")?.let { arr ->
                buildList { for (i in 0 until arr.length()) arr.optJSONObject(i)?.let { add(GoalStep.fromJson(it)) } }
            } ?: emptyList(),
            progress = o.optInt("progress", 0).coerceIn(0, 100),
            status = runCatching { GoalStatus.valueOf(o.optString("status", "ACTIVE")) }.getOrDefault(GoalStatus.ACTIVE),
            sessionId = o.stringOrNull("sessionId"),
            sourceSessionId = o.stringOrNull("sourceSessionId"),
            taskId = o.stringOrNull("taskId"),
            lastNote = o.stringOrNull("lastNote"),
            lastCheckedAt = if (o.has("lastCheckedAt")) o.optLong("lastCheckedAt") else null,
            createdAt = o.optLong("createdAt", System.currentTimeMillis()),
            updatedAt = o.optLong("updatedAt", System.currentTimeMillis()),
            due = GoalDeadlines.parse(o.stringOrNull("due")),
            snoozedUntil = GoalDeadlines.parse(o.stringOrNull("snoozedUntil")),
            deadlineDismissed = o.optBoolean("deadlineDismissed"),
        )
    }
}
