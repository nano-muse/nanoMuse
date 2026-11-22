package io.github.nanomuse.goals

import java.time.LocalDate
import java.time.temporal.ChronoUnit

/** Date-only commitments use the person's local calendar, including across DST changes. */
object GoalDeadlines {
    data class Item(val goal: Goal, val due: LocalDate, val days: Long) {
        val nextStep get() = goal.steps.firstOrNull { !it.done && it.text.isNotBlank() }?.text
        val key get() = "${goal.id}/$due"
    }

    fun parse(value: String?): LocalDate? = value?.takeIf { it.length == 10 }
        ?.let { runCatching { LocalDate.parse(it) }.getOrNull() }?.takeIf { it.year in 1..9999 }

    private fun eligible(goal: Goal, protected: Set<String>): Boolean =
        goal.status == GoalStatus.ACTIVE && !goal.deadlineDismissed && goal.title.isNotBlank() &&
            !goal.isProtectedBy(protected) && (goal.steps.isEmpty() || goal.steps.any { !it.done && it.text.isNotBlank() })

    fun isCurrent(goal: Goal, shown: Item, today: LocalDate, protected: Set<String>): Boolean =
        goal.id == shown.goal.id && goal.due == shown.due &&
            ranked(listOf(goal), today, protected).isNotEmpty()

    /** A click on an old card cannot complete a different step or modify a protected goal. */
    fun completeStep(goal: Goal, shown: Item, today: LocalDate, protected: Set<String>): Goal {
        if (!isCurrent(goal, shown, today, protected) || goal.steps != shown.goal.steps || shown.nextStep == null) return goal
        val index = goal.steps.indexOfFirst { !it.done && it.text.isNotBlank() }
        return goal.copy(steps = goal.steps.mapIndexed { i, step -> if (i == index) step.copy(done = true) else step })
    }

    fun ranked(goals: List<Goal>, today: LocalDate, protected: Set<String>): List<Item> =
        goals.asSequence()
            .filter { eligible(it, protected) }
            .mapNotNull { goal -> goal.due?.let { Item(goal, it, ChronoUnit.DAYS.between(today, it)) } }
            .filter { it.days in -7..1 && it.goal.snoozedUntil?.isAfter(today) != true }
            .sortedWith(compareBy<Item> { if (it.days == 0L) 0 else if (it.days < 0) 1 else 2 }
                .thenByDescending { it.days }.thenBy { it.goal.id })
            .toList()

    /** The first morning when some eligible goal can surface; no daily polling of distant deadlines. */
    fun nextMorning(goals: List<Goal>, firstDay: LocalDate, protected: Set<String>, delivered: Set<String>): LocalDate? =
        goals.asSequence().filter { eligible(it, protected) }.mapNotNull { goal ->
            val due = goal.due ?: return@mapNotNull null
            if ("${goal.id}/$due" in delivered) return@mapNotNull null
            maxOf(firstDay, due.minusDays(1), goal.snoozedUntil ?: firstDay).takeUnless { it.isAfter(due.plusDays(7)) }
        }.minOrNull()
}
