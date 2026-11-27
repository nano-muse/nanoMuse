package io.github.nanomuse.goals

import com.openminis.app.scheduled.ScheduledRepeatMode
import com.openminis.app.scheduled.ScheduledTask
import io.github.nanomuse.feed.FeedFlow
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.time.LocalDate
import java.time.ZoneId

class GoalDeadlinesTest {
    private val today = LocalDate.of(2026, 3, 8)
    private fun goal(id: String, days: Long = 0) = Goal(id = id, title = id, due = today.plusDays(days))
    private fun ranked(vararg goals: Goal) = GoalDeadlines.ranked(goals.toList(), today, setOf("locked"))

    @Test fun rankUsesLocalCalendarDaysAndDeterministicTieBreaks() {
        val items = ranked(goal("far", 2), goal("stale", -8), goal("tomorrow", 1), goal("yesterday", -1),
            goal("week", -7), goal("now-b"), goal("now-a"))
        assertEquals(listOf("now-a", "now-b", "yesterday", "week", "tomorrow"), items.map { it.goal.id })
    }

    @Test fun cardsAndAlarmsOmitInactiveProtectedAndCompletedGoals() {
        val hidden = listOf(goal("done").copy(status = GoalStatus.DONE), goal("paused").copy(status = GoalStatus.PAUSED),
            goal("protected").copy(sessionId = "locked"), goal("all checked").copy(steps = listOf(GoalStep("sent", true))),
            goal("dismissed").copy(deadlineDismissed = true), goal("undated").copy(due = null))
        assertTrue(GoalDeadlines.ranked(hidden, today, setOf("locked")).isEmpty())
        assertNull(GoalDeadlines.nextMorning(hidden, today, setOf("locked"), emptySet()))
    }

    @Test fun protectionOfEitherConversationDropsExistingCardsAndScheduledAlertsAfterReload() {
        val original = goal("renew").copy(sessionId = "goal-chat", sourceSessionId = "origin", steps = listOf(GoalStep("file")))
        val saved = Goal.fromJson(JSONObject(original.toJson().toString()))
        val oldCard = ranked(saved).single()
        for (protected in listOf(setOf("goal-chat"), setOf("origin"))) {
            assertTrue(saved.isProtectedBy(protected))
            assertTrue(GoalDeadlines.ranked(listOf(saved), today, protected).isEmpty())
            assertNull(GoalDeadlines.nextMorning(listOf(saved), today, protected, emptySet()))
            assertFalse(GoalDeadlines.isCurrent(saved, oldCard, today, protected))
            assertEquals(saved, GoalDeadlines.completeStep(saved, oldCard, today, protected))
        }
        val old = Goal.fromJson(original.toJson().apply { remove("sourceSessionId") })
        assertNull(old.sourceSessionId)
        assertFalse(old.isProtectedBy(setOf("origin")))
        assertTrue(old.isProtectedBy(setOf("goal-chat")))
    }

    @Test fun snoozingSurvivesRestartButResurfacesTomorrow() {
        val snoozed = goal("renew").copy(snoozedUntil = today.plusDays(1))
        val restored = Goal.fromJson(JSONObject(snoozed.toJson().toString()))
        assertTrue(ranked(restored).isEmpty())
        assertEquals(today.plusDays(1), GoalDeadlines.nextMorning(listOf(restored), today, emptySet(), emptySet()))
        assertEquals(-1L, GoalDeadlines.ranked(listOf(restored), today.plusDays(1), emptySet()).single().days)
    }

    @Test fun editingDeadlineClearsOnlyTheOldFeedback() {
        val hidden = goal("renew").copy(deadlineDismissed = true, snoozedUntil = today.plusDays(1))
        assertEquals(hidden, hidden.withDue(today))
        val changed = hidden.withDue(today.plusDays(1))
        assertEquals("renew", ranked(changed).single().goal.title)
        assertNull(changed.snoozedUntil)
        assertTrue(ranked(changed.withDue(null)).isEmpty())
    }

    @Test fun completingTheShownStepCannotAdvanceASecondOrAProtectedStep() {
        val g = goal("draft").copy(sessionId = "s", steps = listOf(GoalStep("sent", true), GoalStep("read"), GoalStep("read")))
        val card = ranked(g).single()
        assertEquals("read", card.nextStep)
        val updated = GoalDeadlines.completeStep(g, card, today, emptySet())
        assertEquals(listOf(true, true, false), updated.steps.map { it.done })
        assertEquals(updated, GoalDeadlines.completeStep(updated, card, today, emptySet()))
        assertEquals(g, GoalDeadlines.completeStep(g, card, today, setOf("s")))
        val final = GoalDeadlines.completeStep(updated, ranked(updated).single(), today, emptySet())
        assertTrue(ranked(final).isEmpty())
    }

    @Test fun distantGoalsSleepUntilThePreviousDayAndDeliveredDeadlinesStayQuiet() {
        val first = goal("early")
        val second = goal("later", 11)
        assertEquals(today.plusDays(10), GoalDeadlines.nextMorning(listOf(first, second), today, emptySet(), setOf("early/$today")))
        assertNull(GoalDeadlines.nextMorning(listOf(first), today.plusDays(8), emptySet(), emptySet()))
    }

    @Test fun oldMalformedAndMissingDatesCannotInventDeadlines() {
        listOf(null, "2026-02-29", "3/8/26", "2026-3-8", "0000-03-08").forEach { assertNull(GoalDeadlines.parse(it)) }
        assertNull(Goal.fromJson(JSONObject("""{"id":"old","title":"draft","due":null}""")).due)
        assertEquals(today, GoalDeadlines.parse(today.toString()))
        val old = Goal.fromJson(JSONObject("""{"id":"old","title":"draft"}"""))
        assertTrue(ranked(old).isEmpty())
    }

    @Test fun onlyTheScheduledFeedsExplicitSuccessfulQuietResultSuppressesItsNotice() {
        assertTrue(FeedFlow.quietResult(true, "  [quiet]\n"))
        assertFalse(FeedFlow.quietResult(false, "[quiet]"))
        assertFalse(FeedFlow.quietResult(true, ""))
        assertFalse(FeedFlow.quietResult(true, "[quiet]" + " ".repeat(200) + "failed"))
    }

    @Test fun checkInOnTheSameDaySuppressesTheExtraReminderEvenIfTheAlarmIsLate() {
        val zone = ZoneId.systemDefault()
        val now = today.atTime(10, 0).atZone(zone)
        val task = ScheduledTask(label = "Goal", timeOfDayHour = 9, timeOfDayMinute = 0, prompt = "Review", repeatMode = ScheduledRepeatMode.DAILY)
        assertTrue(GoalFollowUps.checksToday(task, now))
        assertFalse(GoalFollowUps.checksToday(null, now))
        assertFalse(GoalFollowUps.checksToday(task.copy(enabled = false), now))
        assertTrue(GoalFollowUps.checksToday(task.copy(enabled = false, lastFiredAt = now.minusHours(1).toInstant().toEpochMilli()), now))
        assertFalse(GoalFollowUps.checksToday(task.copy(startDateMs = now.plusDays(1).toInstant().toEpochMilli()), now))
    }

    @Test fun onlyExplicitIntegerCompletionIndicesAreAccepted() {
        assertEquals(setOf(2), GoalFlow.completedSteps(JSONObject("""{"completed_steps":[2,2.4,"3",null]}""")))
        assertTrue(GoalFlow.completedSteps(JSONObject("""{"progress":90}""")).isEmpty())
    }
}
