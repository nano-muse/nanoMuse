import Foundation
import SQLite3

/// The receipt and the actual assistant turn commit together. Removing a message or restarting
/// the app cannot cause a second interruption that day. Only the last day per account is kept.
enum NanoMuseOutreachJournal {
    static let messagePrefix = "nm-outreach-"

    static let localPublicPrefix = "nm-outreach-public-"

    struct Candidate {
        let text: String
        let goalID: String?
        var calendarReceipt: String? = nil
        var publicReceipt: String? = nil
    }
    enum Result {
        case later, spent, seenCalendarChange, seenPublicChange, delivered(String, Candidate)
    }

    static func withinHours(_ at: Date, calendar: Calendar = .current) -> Bool {
        (9..<20).contains(calendar.component(.hour, from: at))
    }

    private static let readySQL = """
        SELECT 1 FROM sessions s WHERE s.id=? AND COALESCE(s.source,'')='' AND s.remote_origin_device_id IS NULL
          AND ((?='1' AND NOT EXISTS (SELECT 1 FROM messages WHERE session_id=?))
            OR EXISTS (SELECT 1 FROM (SELECT role, created_at, part_flags, error_info FROM messages WHERE session_id=?
              ORDER BY sort_order DESC LIMIT 1) WHERE role='assistant' AND part_flags=1 AND error_info IS NULL AND created_at<=CAST(? AS REAL)))
        """

    /// Return only row IDs. A synced public notice consists of the exact publisher title and
    /// citation on separate lines. Matching both also distinguishes new items at an unchanged URL.
    static func matchingPublicNotices(db: OpaquePointer?, session: String, item: NanoMuseWatchItem) -> [String] {
        let sql = """
        SELECT id, parts_json FROM (SELECT id, role, part_flags, parts_json FROM messages WHERE session_id=?
          ORDER BY sort_order DESC LIMIT 32) WHERE role='assistant' AND part_flags=1 AND length(CAST(parts_json AS BLOB))<=12000
        """
        var stmt: OpaquePointer?
        defer { sqlite3_finalize(stmt) }
        guard let db, sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return [] }
        sqlite3_bind_text(stmt, 1, (session as NSString).utf8String, -1, unsafeBitCast(-1, to: sqlite3_destructor_type.self))
        var matched = [String]()
        func unescape(_ text: String) -> String {
            text.replacingOccurrences(of: #"\\([\\*_`<>|\[\]{}()#+.!~-])"#, with: "$1", options: .regularExpression)
        }
        while sqlite3_step(stmt) == SQLITE_ROW {
            guard let id = sqlite3_column_text(stmt, 0), let raw = sqlite3_column_text(stmt, 1),
                  let parts = try? JSONDecoder().decode([ContentPart].self, from: Data(String(cString: raw).utf8)),
                  parts.count == 1, case .text(let value) = parts.first else { continue }
            let lines = value.components(separatedBy: .newlines).map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
            guard lines.count >= 2, lines.contains(item.url), lines.contains(where: { unescape($0) == item.text }) else { continue }
            matched.append(String(cString: id))
        }
        return matched
    }

    static func readyForPublicReview(db: OpaquePointer?, owner: String, session: String, day: String, at: Date) -> Bool {
        guard let db, sqlite3_exec(db, "CREATE TABLE IF NOT EXISTS nm_outreach_day(owner TEXT PRIMARY KEY, day TEXT NOT NULL)", nil, nil, nil) == SQLITE_OK else { return false }
        var stmt: OpaquePointer?
        let sql = readySQL + " AND NOT EXISTS (SELECT 1 FROM nm_outreach_day WHERE owner=? AND day>=?)"
        defer { sqlite3_finalize(stmt) }
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return false }
        let values = [session, "1", session, session, String(at.addingTimeInterval(-15 * 60).timeIntervalSince1970), owner, day]
        for (i, value) in values.enumerated() {
            sqlite3_bind_text(stmt, Int32(i + 1), (value as NSString).utf8String, -1, unsafeBitCast(-1, to: sqlite3_destructor_type.self))
        }
        return sqlite3_step(stmt) == SQLITE_ROW
    }

    static func write(db: OpaquePointer?, owner: String, session: String, day: String, at: Date,
                      allowEmpty: Bool = false, candidate: () -> Candidate?, dirty: (String) -> Void) -> Result {
        guard let db, sqlite3_exec(db, "BEGIN IMMEDIATE", nil, nil, nil) == SQLITE_OK else { return .later }
        var committed = false
        defer { if !committed { sqlite3_exec(db, "ROLLBACK", nil, nil, nil) } }
        guard sqlite3_exec(db, "CREATE TABLE IF NOT EXISTS nm_outreach_day(owner TEXT PRIMARY KEY, day TEXT NOT NULL)", nil, nil, nil) == SQLITE_OK else { return .later }
        func statement(_ sql: String, _ values: [String]) -> OpaquePointer? {
            var stmt: OpaquePointer?
            guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return nil }
            for (i, text) in values.enumerated() {
                sqlite3_bind_text(stmt, Int32(i + 1), (text as NSString).utf8String, -1, unsafeBitCast(-1, to: sqlite3_destructor_type.self))
            }
            return stmt
        }
        func step(_ sql: String, _ values: [String]) -> Int32 {
            guard let stmt = statement(sql, values) else { return SQLITE_ERROR }
            defer { sqlite3_finalize(stmt) }
            return sqlite3_step(stmt)
        }
        let available = step("SELECT 1 FROM nm_outreach_day WHERE owner=? AND day>=?", [owner, day])
        if available == SQLITE_ROW { return .spent }
        guard available == SQLITE_DONE else { return .later }
        // Wait for a completed, idle conversation. Reading a session from another device or
        // interleaving a prompt with a pending user/tool call would change its meaning.
        let stamp = String(at.timeIntervalSince1970)
        guard step(readySQL, [session, allowEmpty ? "1" : "0", session, session, String(at.addingTimeInterval(-15 * 60).timeIntervalSince1970)]) == SQLITE_ROW,
              let choice = candidate(), let data = try? JSONEncoder().encode([ContentPart.text(choice.text)]),
              let parts = String(data: data, encoding: .utf8) else { return .later }
        if let receipt = choice.calendarReceipt {
            guard sqlite3_exec(db, "CREATE TABLE IF NOT EXISTS nm_outreach_calendar(owner TEXT PRIMARY KEY, receipt TEXT NOT NULL)", nil, nil, nil) == SQLITE_OK else { return .later }
            let seen = step("SELECT 1 FROM nm_outreach_calendar WHERE owner=? AND receipt=?", [owner, receipt])
            if seen == SQLITE_ROW { return .seenCalendarChange }
            guard seen == SQLITE_DONE,
                  step("INSERT OR REPLACE INTO nm_outreach_calendar(owner,receipt) VALUES(?,?)", [owner, receipt]) == SQLITE_DONE else { return .later }
        }
        if let receipt = choice.publicReceipt {
            guard sqlite3_exec(db, "CREATE TABLE IF NOT EXISTS nm_outreach_public(owner TEXT, receipt TEXT, PRIMARY KEY(owner,receipt))", nil, nil, nil) == SQLITE_OK else { return .later }
            let seen = step("SELECT 1 FROM nm_outreach_public WHERE owner=? AND receipt=?", [owner, receipt])
            if seen == SQLITE_ROW { return .seenPublicChange }
            guard seen == SQLITE_DONE, step("INSERT INTO nm_outreach_public(owner,receipt) VALUES(?,?)", [owner, receipt]) == SQLITE_DONE else { return .later }
        }
        let id = (choice.publicReceipt == nil ? messagePrefix : localPublicPrefix) + UUID().uuidString.lowercased()
        let sql = """
        INSERT INTO messages(id,session_id,role,parts_json,created_at,updated_at,sort_order,part_flags)
        SELECT ?,?,'assistant',?,?,?,COALESCE(MAX(sort_order),-1)+1,1 FROM messages WHERE session_id=?
        """
        guard step(sql, [id, session, parts, stamp, stamp, session]) == SQLITE_DONE,
              step("INSERT OR REPLACE INTO nm_outreach_day(owner,day) VALUES(?,?)", [owner, day]) == SQLITE_DONE,
              step("UPDATE sessions SET updated_at=? WHERE id=?", [stamp, session]) == SQLITE_DONE else { return .later }
        if choice.publicReceipt == nil { dirty(id) }
        guard sqlite3_exec(db, "COMMIT", nil, nil, nil) == SQLITE_OK else { return .later }
        committed = true
        return .delivered(id, choice)
    }
}

/// Revocation and the short SQLite write are ordered even when the main actor switches accounts
/// while ChatStore is processing a request. Never await or call the UI while holding this lock.
final class NanoMuseOutreachPermit: @unchecked Sendable {
    private let lock = NSLock()
    private var generation: UInt = 0
    func snapshot() -> UInt { lock.lock(); defer { lock.unlock() }; return generation }
    func revoke() { lock.lock(); defer { lock.unlock() }; generation &+= 1 }
    func perform(_ version: UInt, _ operation: () -> NanoMuseOutreachJournal.Result) -> NanoMuseOutreachJournal.Result {
        lock.lock()
        defer { lock.unlock() }
        return generation == version ? operation() : .later
    }
}
