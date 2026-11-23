package io.github.nanomuse.feed

import org.json.JSONArray
import java.time.DayOfWeek
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.temporal.TemporalAdjusters

/** Local, consented composer text can nominate a commitment. Replies can retire it but
 * never become model input. We deliberately skip ambiguous corrections and old relative dates. */
internal object ChatCommitments {
    data class Line(val session: String, val id: String, val person: Boolean, val assistant: Boolean, val text: String, val at: Long)
    private val personal = Regex("""\bI(?:'ll|’ll| will| need to| have to| promised| agreed| owe| must| am going to)|\bwe (?:promised|agreed|need to|have to|will)\b|我(?:们|們)?(?:.{0,8})(?:答应|答應|约好|約好|要|得|打算|计划|計劃|承诺|承諾)|(?:明天|后天|後天|下周).{0,5}我""", RegexOption.IGNORE_CASE)
    private val action = Regex("""\b(?:send|write|ask|contact|call|visit|book|email|deliver|present|bring|meet|submit|confirm|follow up)\b|联系|聯繫|发给|發給|发送|發送|询问|詢問|预约|預約|参观|參觀|拜访|拜訪|汇报|彙報|开场|開場|邮件|郵件|复盘|復盤|提交|确认|確認|交稿|带上|帶上""", RegexOption.IGNORE_CASE)
    private val hypothetical = Regex("""\b(?:if|suppose|might|hypothetical|would I|should I)\b|如果|假如|假设|假設|要不要|是不是|要是|举个例|舉個例""", RegexOption.IGNORE_CASE)
    private val closed = Regex("""\b(?:cancelled|canceled|called off|^done[.!]?$|already (?:sent|emailed|wrote|called|booked|submitted|confirmed|delivered|completed|done|finished|handled)|I(?:'ve| have)? (?:sent|emailed|called|booked|submitted|confirmed|delivered|completed|finished)|no longer (?:need|going))\b|已(?:经|經)?(?:取消|完成|提交|送达|送達|确认|確認|发送|發送|发出|發出|处理|處理|办妥|辦妥|办完|辦完|发给|發給|发过|發過|发了|發了|联系|聯繫|订好|訂好)|取消了|提交了|完成了|搞定了|不用了|办好了|辦好了|不用再|不去了|办完了|辦完了|发完了|發完了|联系好了|聯繫好了""", RegexOption.IGNORE_CASE)
    private val negated = Regex("""\b(?:not|never|isn't|wasn't|haven't)\s+(?:yet\s+|been\s+)?(?:cancelled|canceled|sent|submitted|confirmed|done|finished)\b|没(?:有)?取消|沒(?:有)?取消|还没|還沒|并未|並未""", RegexOption.IGNORE_CASE)
    private val shifted = Regex("""\b(?:reschedul\w*|postpon\w*|moved to|pushed back|instead of)\b|改(?:到|为|為|期)|挪到|推迟|推遲|延后|延後""", RegexOption.IGNORE_CASE)
    private val disclaimed = Regex("""\b(?:I|we) (?:do not|don't|did not|didn't|won't|will not|never)\b|我(?:们|們)?(?:不想|不用|不要|不打算|不再|没有|沒有)|他说|他說|她说|她說|[“”「」"<>]""", RegexOption.IGNORE_CASE)
    private val asksForDraft = Regex("""(?:can|could|would) you (?:write|draft)|draft (?:it|that|this|the)|write (?:it|that|this) for me|帮我(?:写|起草|拟)|幫我(?:寫|起草|擬)""", RegexOption.IGNORE_CASE)
    private val artifact = Regex("""(?:^|\n)\s*(?:subject:|dear\s|hello\s|主题[：:]|主旨[：:]|尊敬的|您好[，！!：:]|各位[，：]|[-*]\s+\[[ x]\])|写好了.{0,8}(?:如下|草稿)|here(?:'s| is) (?:your|the) draft""", RegexOption.IGNORE_CASE)
    private val dateToken = Regex("""(?<!\d)\d{4}-\d{2}-\d{2}(?!\d)""")
    private val tomorrow = Regex("""\btomorrow\b|明[天早晚]""", RegexOption.IGNORE_CASE)
    private val today = Regex("""\b(?:today|tonight)\b|今[天晚]""", RegexOption.IGNORE_CASE)
    private val weekday = Regex("""(?:\bon |\bnext |\bby )?(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b|(?:下?[周週]|星期|礼拜|禮拜)([一二三四五六日天])""", RegexOption.IGNORE_CASE)

    private val uncertainTime = Regex("""\b(?:or|either|undecided|not sure when)\b|或者|还是|還是|或|没定|沒定|待定""", RegexOption.IGNORE_CASE)
    private val newTime = Regex("""\b(?:to|until|for)\s+|改(?:到|为|為)|挪到|推[迟遲]到|延[后後]到""", RegexOption.IGNORE_CASE)

    fun latestDay(statement: String, written: LocalDate): LocalDate? {
        val text = if (shifted.containsMatchIn(statement)) {
            val destination = statement.substringBefore(" instead of ", statement)
            val last = newTime.findAll(destination).lastOrNull()
            if (last == null) destination else destination.substring(last.range.last + 1)
        } else statement
        if (uncertainTime.containsMatchIn(text)) return null
        dateToken.findAll(text).lastOrNull()?.let { return runCatching { LocalDate.parse(it.value) }.getOrNull() }
        if ("后天" in text || "後天" in text || "day after tomorrow" in text.lowercase()) return written.plusDays(2)
        weekday.findAll(text).lastOrNull()?.let { match ->
            val d = match.groupValues[1].takeIf { it.isNotEmpty() }?.let { DayOfWeek.valueOf(it.uppercase(java.util.Locale.ROOT)) }
                ?: DayOfWeek.of(("一二三四五六日天".indexOf(match.groupValues[2]) + 1).coerceAtMost(7))
            if (match.value.startsWith("下周") || match.value.startsWith("下週")) return written.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY)).plusWeeks(1).plusDays(d.value - 1L)
            return written.with(TemporalAdjusters.nextOrSame(d))
        }
        return when {
            tomorrow.containsMatchIn(text) -> written.plusDays(1)
            today.containsMatchIn(text) -> written
            else -> null
        }
    }

    fun relevant(text: String): Boolean = closed.containsMatchIn(text) || shifted.containsMatchIn(text) ||
        asksForDraft.containsMatchIn(text) || personal.containsMatchIn(text) && action.containsMatchIn(text)

    fun facts(lines: List<Line>, now: LocalDate, label: String, zone: ZoneId = ZoneId.systemDefault()): List<FeedPreparation.Fact> {
        val open = mutableListOf<Line>()
        var previous: Line? = null
        for (line in lines) {
            val text = line.text
            if (line.assistant) {
                val prior = previous
                if (prior != null && prior.session == line.session && (text.isBlank() ||
                        text.length >= 32 && artifact.containsMatchIn(text) && FeedPreparation.sameSubject(prior.text, text))) open.remove(prior)
                continue
            }
            val preceding = previous
            previous = null
            if (!line.person || text.isBlank() || hypothetical.containsMatchIn(text)) continue
            val closing = closed.containsMatchIn(text) && !negated.containsMatchIn(text)
            val moving = shifted.containsMatchIn(text)
            val inChat = open.filter { it.session == line.session }
            if (closing || moving) {
                val matching = inChat.filter { FeedPreparation.sameSubject(it.text, text) }
                val affected = if (matching.isEmpty() && inChat.size == 1 && text.length <= 26 &&
                    (text.matches(Regex("""(?:办完了|辦完了|取消了|已发了|已發了|完成了|搞定了|提交了|不用了|done|already sent)[。.!！]?""", RegexOption.IGNORE_CASE)) ||
                        moving && text.matches(Regex("""(?:改到|挪到|推迟到|推遲到|moved to |rescheduled to )[\p{L}\d\-:： ]{1,16}[。.！!]?""", RegexOption.IGNORE_CASE)))) inChat else matching
                open.removeAll(affected.toSet())
                if (moving && affected.size == 1 && latestDay(text, date(line, zone)) != null) {
                    val prior = affected.single()
                    // Keep both verbatim records. Use the revised time only when checking expiry.
                    val revised = line.copy(id = prior.id + "/" + line.id, text = prior.text.substringBefore('\n') + "\n" + text)
                    open += revised
                    previous = revised
                }
                continue
            }
            if (asksForDraft.containsMatchIn(text)) {
                previous = inChat.singleOrNull { FeedPreparation.sameSubject(it.text, text) } ?: preceding?.takeIf { it in inChat }
                continue
            }
            if (!disclaimed.containsMatchIn(text) && personal.containsMatchIn(text) && action.containsMatchIn(text) && !text.endsWith("?") && !text.endsWith("？")) {
                open += line
                previous = line
            }
        }
        return open.mapNotNull { line ->
            val written = date(line, zone)
            val specified = latestDay(line.text.substringAfterLast('\n'), written)
            val due = specified ?: written.plusDays(2)
            if (uncertainTime.containsMatchIn(line.text.substringAfterLast('\n')) || written > now || due < now || due > now.plusDays(7)) null else FeedPreparation.Fact(
                FeedPreparation.Kind.CHAT, "chat/${line.session}/${line.id}", label, line.text,
                setOf(FeedPreparation.hash(line.session)), priority = if (due <= now.plusDays(1)) 12 else 8, chatDay = written.toString(), dueOn = specified?.toString().orEmpty(),
            )
        }
    }

    private fun date(line: Line, zone: ZoneId) = Instant.ofEpochMilli(line.at).atZone(zone).toLocalDate()

    /** Only a short, standalone text part. Never use tool output, attachment paths or pasted documents. */
    fun plain(parts: String, person: Boolean): String {
        if (parts.isEmpty()) return ""
        val array = runCatching { JSONArray(parts) }.getOrNull() ?: return ""
        if (person && array.length() != 1) return ""
        for (i in 0 until array.length()) {
            val part = array.optJSONObject(i) ?: continue
            if (part.optString("type") != "text") continue
            val text = part.optString("value").trim()
            if (person && (text.length !in 2..500 || text.contains('\n') || text.contains('`') || text.startsWith("<"))) return ""
            if (text.isNotEmpty()) return text.take(if (person) 500 else 1500)
        }
        return ""
    }
}
