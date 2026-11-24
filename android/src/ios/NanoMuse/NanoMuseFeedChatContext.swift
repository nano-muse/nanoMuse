// Only the local composer's text-only sends can enter the Feed index. A reference
// contains no message text. The original row and any completed reply are read again.
import Foundation
import SQLite3

enum NanoMuseFeedChatContext {
    struct Reference: Codable, Equatable {
        let session: String
        let message: String
        let at: Date
        var mainOnly: Bool? = nil // Older references were explicitly selected for Feed preparation.
    }

    static let maxReferences = 40
    static let textLength = 2...420

    // A promise made this Tuesday for next Friday needs its original row on day ten.
    // Its source can outlive the seven-day presentation window without reading old chat history.
    static func retained(_ refs: [Reference], now: Date, calendar: Calendar = .current) -> [Reference] {
        guard let cutoff = calendar.date(byAdding: .day, value: -21, to: now) else { return [] }
        return refs.suffix(maxReferences).filter { cutoff <= $0.at && $0.at <= now }
    }

    struct Turn {
        let ref: Reference
        let text: String
        let reply: String
    }

    struct Open {
        let ref: Reference
        var request: String
        var update: String?
        var revision: String
        var due: Date
    }

    private static func matches(_ pattern: String, _ text: String) -> Bool {
        text.range(of: pattern, options: [.regularExpression, .caseInsensitive]) != nil
    }

    private static func subject(_ text: String) -> Set<String> {
        NanoMuseFeedPreparation.topics(text).subtracting([
            "already", "send", "sent", "email", "draft", "submit", "submitted", "move", "moved", "done", "instead",
            "cancelled", "canceled", "friday", "monday", "tuesday", "wednesday", "thursday", "saturday", "sunday",
            "承诺", "答应", "发送", "发给", "已发", "发了", "取消", "改到", "周一", "周二", "周三", "周四", "周五", "周六", "周日"
        ])
    }

    private static let action = #"\b(send|email|contact|call|ask|confirm|book|submit|bring|present|deliver|draft|write|return|visit|meet)\b|发(?:送|给|邮件|一封|询)|發(?:送|給|郵件|一封)|联系|聯絡|写|寫|预约|預約|询问|詢問|提交|参观|參觀|汇报|匯報|复盘|復盤|评审|評審|送|带|帶|回信|回复|回覆|确认|確認"#
    private static let intent = #"\bI(?:['’]ll| will| promised| agreed| owe| have to| need to| must| plan to| am going to|'m going to)\b|(?:我|我们|我們).{0,24}(?:答应|答應|承诺|承諾|约好|約好|得|要|打算|必须|必須|会|會|负责|負責)|我.{0,4}(?:明天|后天|後天|今天|周[一二三四五六日天]|週[一二三四五六日天]).{0,25}"#
    private static let uncertain = #"\b(if|maybe|might|hypothetical|example|suppose|perhaps)\b|如果|假如|也许|也許|举例|舉例|可能|别人说|別人說"#
    private static let closed = #"\b(cancelled|canceled|called off|already (?:sent|done|finished|submitted|booked|contacted)|I (?:sent|did|finished|submitted|contacted|booked)|no longer need)\b|取消|我.{0,20}(?:发过了|發過了|已经发|已經發|发完了|發完了|发了|發了|办完|辦完|联系过|聯絡過|已联系|已聯絡|提交了)|(?:已[经經]?|都)(?:完成|处理|處理|办妥|辦妥)|不用(?:再|发|發|跟进|跟進)|办好了|辦好了|^(?:done|sent|finished|(?:已)?(?:发了|發了|搞定了?|完成了))[。.!！]?$"#
    private static let moved = #"\b(?:reschedule[d]?|move[d]?|postpone[d]?|push(?:ed)? it back|instead)\b|改(?:到|为|為|成|期)|推到|推迟|推遲|延到|延期|挪到"#
    private static let unqualified = #"^(?:I (?:already )?(?:sent|finished|did|submitted|booked) (?:it|that)|(?:it(?:'s| is)? |that's )?(?:already )?(?:done|sent|finished|cancelled|canceled)|(?:move(?:d)?|push(?:ed)?|postpone(?:d)?|reschedule(?:d)?) (?:it |that )?(?:to|until) .+|(?:我|这件事|這件事|那件事)?(?:已經|已经|已|都)?(?:发了|發了|搞定了?|完成了?|办好了|辦好了|提交了|取消了?|改期|延期|不用跟进了|不用跟進了)|(?:就|那就)?(?:改到|推到|推迟到|推遲到|挪到).+)[。.!！]?$"#

    private static func date(in text: String, at: Date, calendar: Calendar) -> Date? {
        let start = calendar.startOfDay(for: at)
        // A single explicit date is required. Two alternatives or a range cannot establish a deadline.
        let datePattern = #"(?<![0-9])\d{4}-\d{2}-\d{2}(?![0-9])|\b(?:day after tomorrow|tomorrow|tonight|today|sunday|monday|tuesday|wednesday|thursday|friday|saturday)\b|后天|後天|明天|明早|明晚|明日|今天|今晚|今日|(?:周|週|星期)[一二三四五六日天]"#
        guard let matcher = try? NSRegularExpression(pattern: datePattern, options: .caseInsensitive),
              matcher.numberOfMatches(in: text, range: NSRange(text.startIndex..., in: text)) == 1 else { return nil }
        if let r = text.range(of: #"(?<![0-9])\d{4}-\d{2}-\d{2}(?![0-9])"#, options: .regularExpression) {
            let parts = text[r].split(separator: "-").compactMap { Int($0) }
            guard parts.count == 3, let date = calendar.date(from: DateComponents(year: parts[0], month: parts[1], day: parts[2])),
                  calendar.component(.day, from: date) == parts[2] else { return nil }
            return date
        }
        let days: Int
        if matches(#"\bday after tomorrow\b|后天|後天"#, text) { days = 2 }
        else if matches(#"\btomorrow\b|明天|明早|明晚|明日"#, text) { days = 1 }
        else if matches(#"\btoday\b|\btonight\b|今天|今晚|今日"#, text) { days = 0 }
        else {
            let weekdays = ["sunday|(?:周|週|星期)[日天]", "monday|(?:周|週|星期)一", "tuesday|(?:周|週|星期)二",
                            "wednesday|(?:周|週|星期)三", "thursday|(?:周|週|星期)四", "friday|(?:周|週|星期)五", "saturday|(?:周|週|星期)六"]
            guard let index = weekdays.firstIndex(where: { matches($0, text) }) else { return nil }
            let weekday = calendar.component(.weekday, from: start)
            if matches(#"\bnext\b|下(?:个|個)?(?:周|週|星期)"#, text) {
                let sinceMonday = (weekday + 5) % 7
                days = 7 - sinceMonday + (index + 6) % 7
            } else {
                days = (index + 1 - weekday + 7) % 7
            }
        }
        return calendar.date(byAdding: .day, value: days, to: start)
    }

    private static func delivered(_ reply: String, request: String) -> Bool {
        guard reply.count >= 30, !matches(#"\b(?:cannot|can't|unable to) (?:write|draft)\b|无法(?:起草|撰写)|無法(?:起草|撰寫)"#, reply) else { return false }
        let actual = matches(#"(?m)^\s*(?:dear\s|subject:|hi [\w \[\]]+[,，]|您好[，！,:：]|各位[，：]|主题[：:]|主旨[：:]|[-*]\s+\[ \])|以下(?:是|为|為).{0,16}(?:草稿|初稿|邮件|郵件)[：:]|here(?:'s| is) (?:the |your |a )?(?:draft|email|message):"#, reply)
        return actual && !NanoMuseFeedPreparation.topics(request).isDisjoint(with: NanoMuseFeedPreparation.topics(reply))
    }

    /// Resolve corrections within a single discussion. A subject-free "already sent" can
    /// refer to the immediately preceding commitment only when it is unambiguous.
    static func outstanding(_ input: [Turn], now: Date, calendar: Calendar = .current) -> [Open] {
        var open: [Open] = []
        var previous: [String: String] = [:]
        let today = calendar.startOfDay(for: now)
        let limit = calendar.date(byAdding: .day, value: 7, to: today) ?? today
        for turn in input.sorted(by: { $0.ref.at < $1.ref.at }) {
            let text = turn.text
            let sid = turn.ref.session
            guard !matches(uncertain, text),
                  !matches(#"\bnot (?:yet |already )?(?:done|sent|cancelled|canceled|submitted|finished)|\b(?:haven['’]t|have not|didn['’]t) (?:yet )?(?:send|sent|finish|cancel|submit)|(?:还|還)?(?:没|沒|尚未|未曾)(?:有)?(?:发|發|完成|办|辦|取消|提交|处理|處理)"#, text) else { previous[sid] = nil; continue }
            let terms = subject(text)
            let local = open.indices.filter { open[$0].ref.session == sid }
            let subjects = local.filter { !subject(open[$0].request).isDisjoint(with: terms) }
            let previousOnly = local.count == 1 && previous[sid] == open[local[0]].ref.message
            let correction = matches(moved, text) || matches(closed, text)
            if correction {
                let target: Int? = subjects.count == 1 ? subjects.first :
                    (subjects.isEmpty && previousOnly && text.count <= 32 && matches(unqualified, text) ? local.first : nil)
                if let i = target {
                    if matches(moved, text), let move = text.range(of: moved, options: [.regularExpression, .caseInsensitive]),
                       let changed = date(in: String(text[move.lowerBound...]), at: turn.ref.at, calendar: calendar) {
                        open[i].due = changed
                        open[i].update = text
                        open[i].revision = turn.ref.message
                        previous[sid] = open[i].ref.message
                    } else {
                        open.remove(at: i)
                        previous[sid] = nil
                    }
                }
                continue
            }
            // A later request can receive the actual draft in the same chat.
            open.removeAll { $0.ref.session == sid && delivered(turn.reply, request: $0.request)
                && !NanoMuseFeedPreparation.topics($0.request).isDisjoint(with: terms) }
            previous[sid] = nil
            guard !matches(#"\b(?:not|never|won.t|don.t|was told|you said|s?he said)\b|不要|不想|不用|不打算|不再|举例|舉例|[“「『>]"#, text),
                  !text.hasSuffix("?"), !text.hasSuffix("？"), matches(intent, text), matches(action, text),
                  let due = date(in: text, at: turn.ref.at, calendar: calendar),
                  !delivered(turn.reply, request: text) else { continue }
            if let existing = open.first(where: { $0.ref.session == sid && $0.due == due && $0.request.caseInsensitiveCompare(text) == .orderedSame }) {
                previous[sid] = existing.ref.message
                continue
            }
            open.append(Open(ref: turn.ref, request: text, revision: turn.ref.message, due: due))
            previous[sid] = turn.ref.message
        }
        return open.filter { today <= $0.due && $0.due <= limit }.sorted { $0.due < $1.due }
    }

    /// Only a single local text part (no attachment, routing envelope or tool result) is eligible.
    /// Never deserialize a full chat. A missing, oversized or unrecognised reply is ambiguous.
    static func read(_ references: [Reference], db: OpaquePointer?) -> [Turn] {
        let sql = """
        SELECT m.parts_json, m.created_at, m.sort_order FROM messages m
        JOIN sessions s ON s.id=m.session_id
        WHERE m.id=? AND s.id=? AND m.role='user' AND s.memory_enabled=1
          AND COALESCE(s.source,'')='' AND s.remote_origin_device_id IS NULL
          AND length(CAST(m.parts_json AS BLOB)) <= 2800
        """
        var msg: OpaquePointer?
        var next: OpaquePointer?
        defer { sqlite3_finalize(msg); sqlite3_finalize(next) }
        let nextSQL = """
        SELECT role, CASE WHEN role='assistant' AND part_flags=1 AND length(CAST(parts_json AS BLOB))<=24000 THEN parts_json END,
          part_flags, error_info FROM messages WHERE session_id=? AND sort_order>?
          ORDER BY sort_order LIMIT 12
        """
        guard sqlite3_prepare_v2(db, sql, -1, &msg, nil) == SQLITE_OK,
              sqlite3_prepare_v2(db, nextSQL, -1, &next, nil) == SQLITE_OK else { return [] }
        return references.suffix(maxReferences).compactMap { ref -> Turn? in
            sqlite3_reset(msg); sqlite3_reset(next)
            sqlite3_bind_text(msg, 1, (ref.message as NSString).utf8String, -1, unsafeBitCast(-1, to: sqlite3_destructor_type.self))
            sqlite3_bind_text(msg, 2, (ref.session as NSString).utf8String, -1, unsafeBitCast(-1, to: sqlite3_destructor_type.self))
            guard sqlite3_step(msg) == SQLITE_ROW, let raw = sqlite3_column_text(msg, 0),
                  let parts = try? JSONDecoder().decode([ContentPart].self, from: Data(String(cString: raw).utf8)),
                  parts.count == 1, case .text(let text) = parts[0], textLength.contains(text.count),
                  !text.contains("{{vault:"), !text.contains("<system"), !text.contains("```") else { return nil }
            sqlite3_bind_text(next, 1, (ref.session as NSString).utf8String, -1, unsafeBitCast(-1, to: sqlite3_destructor_type.self))
            sqlite3_bind_int64(next, 2, sqlite3_column_int64(msg, 2))
            var reply = ""
            var completed = false
            while sqlite3_step(next) == SQLITE_ROW {
                guard let rawRole = sqlite3_column_text(next, 0) else { return nil }
                let role = String(cString: rawRole)
                let flags = sqlite3_column_int(next, 2)
                if role == "user" { break }
                guard role == "assistant", flags == 1 else { continue }
                guard sqlite3_column_type(next, 3) == SQLITE_NULL, let raw = sqlite3_column_text(next, 1),
                      let parts = try? JSONDecoder().decode([ContentPart].self, from: Data(String(cString: raw).utf8)) else { return nil }
                reply = parts.compactMap { part -> String? in if case .text(let value) = part { return value }; return nil }.joined(separator: "\n")
                completed = true
                break
            }
            // A cancellation should take effect even before the assistant answers.
            guard completed || matches(closed, text) || matches(moved, text) else { return nil }
            return Turn(ref: Reference(session: ref.session, message: ref.message, at: Date(timeIntervalSince1970: sqlite3_column_double(msg, 1))),
                        text: text, reply: String(reply.prefix(1200)))
        }
    }
}

extension Notification.Name {
    static let nmFeedChatChanged = Notification.Name("NanoMuseFeedChatChanged")
}

@MainActor
enum NanoMuseFeedChatIndex {
    nonisolated static let setting = "nanomuse.feed.chat.enabled"
    private static let index = "nanomuse.feed.chat.references"
    private(set) static var epoch = UUID()
    nonisolated static var enabled: Bool { UserDefaults.standard.bool(forKey: setting) }

    struct Ticket {
        let owner: String
        let generation: UUID
    }

    static func invalidate() {
        epoch = UUID()
        NanoMuseFeedStore.shared.invalidateChatCards()
        NotificationCenter.default.post(name: .nmFeedChatChanged, object: nil)
    }

    static func setEnabled(_ value: Bool) {
        guard value != enabled || UserDefaults.standard.object(forKey: setting) == nil else { return }
        UserDefaults.standard.set(value, forKey: setting)
        invalidate()
        if !value {
            UserDefaults.standard.removeObject(forKey: index)
            NanoMuseFeedStore.shared.discardChatCards()
        }
    }

    nonisolated static func allowsChatCheckIn(in defaults: UserDefaults = .standard) -> Bool {
        NanoMuseChatOutreach.chatEnabled(in: defaults) && (defaults.object(forKey: setting) as? Bool ?? true)
    }

    private static func canUse(_ session: String) -> Bool {
        (UserDefaults.standard.object(forKey: "memory.global.enabled") as? Bool ?? true)
            && !SessionLockStore.shared.appIsLocked && !SessionLockStore.shared.isLocked(session)
            && !NanoMuseFeedFlow.isFeedSession(session)
            && NanoMuseAccountData.shared.owner(of: session) == NanoMuseAccountData.shared.current
    }

    static func allows(_ session: String) -> Bool { enabled && canUse(session) }

    private static func isMain(_ session: String) -> Bool {
        session == UserDefaults.standard.string(forKey: NanoMuseMainChat.key)
    }

    static func ticket(session: String?, memory: Bool) -> Ticket? {
        guard enabled || allowsChatCheckIn(), memory, !SessionLockStore.shared.appIsLocked else { return nil }
        if let session, !canUse(session) || (!enabled && !isMain(session)) { return nil }
        return Ticket(owner: NanoMuseAccountData.shared.current, generation: epoch)
    }

    private static func savedReferences(now: Date) -> [NanoMuseFeedChatContext.Reference] {
        guard let data = UserDefaults.standard.data(forKey: index),
              let refs = try? JSONDecoder().decode([NanoMuseFeedChatContext.Reference].self, from: data) else { return [] }
        return NanoMuseFeedChatContext.retained(refs, now: now)
    }

    static func references(now: Date, forMainChat session: String? = nil) -> [NanoMuseFeedChatContext.Reference] {
        if let session {
            guard allowsChatCheckIn(), isMain(session), canUse(session) else { return [] }
            return savedReferences(now: now).filter { $0.session == session }
        }
        guard enabled, !SessionLockStore.shared.appIsLocked else { return [] }
        return savedReferences(now: now).filter { $0.mainOnly != true && canUse($0.session) }
    }

    static func clearMainOnlyReferences() {
        epoch = UUID()
        let remaining = savedReferences(now: Date()).filter { $0.mainOnly != true }
        if remaining.isEmpty {
            UserDefaults.standard.removeObject(forKey: index)
        } else if let data = try? JSONEncoder().encode(remaining) {
            UserDefaults.standard.set(data, forKey: index)
        }
    }

    static func record(_ ticket: Ticket, session: String, message: String) {
        guard ticket.owner == NanoMuseAccountData.shared.current, ticket.generation == epoch, canUse(session),
              enabled || (allowsChatCheckIn() && isMain(session)) else { return }
        let now = Date()
        var refs = savedReferences(now: now).filter { $0.message != message }
        refs.append(.init(session: session, message: message, at: now, mainOnly: enabled ? nil : true))
        if let data = try? JSONEncoder().encode(Array(refs.suffix(NanoMuseFeedChatContext.maxReferences))) {
            UserDefaults.standard.set(data, forKey: index)
            NanoMuseFeedStore.shared.invalidateChatCards()
            NotificationCenter.default.post(name: .nmFeedChatChanged, object: nil)
        }
    }
}
