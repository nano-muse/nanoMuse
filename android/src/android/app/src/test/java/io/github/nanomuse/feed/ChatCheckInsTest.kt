package io.github.nanomuse.feed

import io.github.nanomuse.sync.LocalMessage
import io.github.nanomuse.sync.Transcript
import org.junit.Assert.*
import org.junit.Test
import java.time.LocalDate
import java.time.ZoneId
import java.time.ZonedDateTime

class ChatCheckInsTest {
    private val zone = ZoneId.of("Europe/Berlin")
    private val today = LocalDate.of(2026, 3, 29)
    private val nine = today.atTime(9, 0).atZone(zone)
    private val request = "I promised to email the museum tomorrow to arrange a visit."
    private fun line(id: String, text: String, at: ZonedDateTime, assistant: Boolean = false) =
        ChatCommitments.Line("mine", id, !assistant, assistant, text, at.toInstant().toEpochMilli())
    private fun facts(vararg lines: ChatCommitments.Line) = ChatCommitments.facts(lines.toList(), today, "Chat", zone)

    @Test fun dateAndAgeChooseWhatMeritsAnInterruption() {
        val previous = line("pledge", request, nine.minusDays(1))
        val underHour = line("typed", "I need to contact the museum today.", nine.minusMinutes(5))
        val later = line("later", "I promised to contact the library tomorrow.", nine)
        val undated = line("undated", "I promised to email the museum.", nine.minusDays(1))
        val candidates = ChatCheckIns.due(facts(previous, underHour, later, undated), nine)
        assertEquals(listOf(previous.text, underHour.text), candidates.map { it.text })
        val first = candidates.first()
        assertEquals("mine", first.chatSession)
        assertTrue(ChatCheckIns.ready(first, nine))
        assertFalse(ChatCheckIns.ready(candidates[1], nine))
        assertTrue(ChatCheckIns.ready(candidates[1], nine.plusHours(1)))
        assertFalse(ChatCheckIns.ready(first, nine.minusHours(1)))
        assertFalse(ChatCheckIns.ready(first, nine.withHour(20)))
        assertEquals(nine, ChatCheckIns.nextWindow(nine.minusHours(1), null))
        assertEquals(nine.plusDays(1), ChatCheckIns.nextWindow(nine, today.toString()))
        assertEquals(nine.plusDays(1), ChatCheckIns.nextWindow(nine.withHour(20), null))
        assertEquals(ChatCheckIns.prefix("local", nine), ChatCheckIns.prefix("local", nine.plusHours(6)))
        assertNotEquals(ChatCheckIns.prefix("local", nine), ChatCheckIns.prefix("second", nine))
    }

    @Test fun aDirectReplyResolvesOnlyTheCommitmentTheAssistantAskedAbout() {
        val museum = line("museum", request, nine.minusDays(1))
        val library = line("library", "I promised to review the library budget tomorrow and submit it.", nine.minusDays(1))
        val original = facts(museum, library).first { it.text == request }
        val messageId = ChatCheckIns.prefix("local", nine) + original.id
        val reminder = line(messageId, "You mentioned this plan for today: $request", nine, assistant = true)
        assertEquals(2, facts(museum, library, reminder).size)
        for (response in listOf("done", "办完了", "发了")) {
            val reply = line("reply", response, nine.plusMinutes(1))
            assertTrue(ChatCommitments.relevant(response))
            assertEquals(listOf(library.text), facts(museum, library, reminder, reply).map { it.text })
        }
        val updated = facts(museum, library, reminder, line("reply", "Move it to Friday", nine.plusMinutes(1)))
        assertEquals(listOf(library.text), ChatCheckIns.due(updated, nine).map { it.text })
        assertEquals(2, updated.size)
        val unrelated = line("other", "We talked about moving house.", nine.plusMinutes(1))
        assertEquals(2, facts(museum, library, reminder, unrelated, line("ambiguous", "done", nine.plusMinutes(2))).size)
    }

    @Test fun syncKeepsThePreviousAnswerAndTheCheckInAsSeparateRealMessages() {
        fun row(id: String, role: String, body: String) = LocalMessage(id, "mine", role, Transcript.partsJson(body, emptyList()), 5)
        val messages = listOf(row("human", "user", request), row("answer", "assistant", "Understood."),
            row("nm-checkin-day-fact", "assistant", "How is it going?"), row("reply", "user", "I sent it."))
        val wire = Transcript.items(messages)
        assertEquals(listOf("human", "answer", "nm-checkin-day-fact", "reply"), wire.map { it.messageId })
        assertEquals(listOf("user", "assistant", "assistant", "user"), wire.map { it.role })
    }
}
