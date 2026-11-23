import Foundation
import SQLite3

/// The receipt and the actual assistant turn commit together. Removing a message or restarting
/// the app cannot cause a second interruption that day. Only the last day per account is kept.
enum NanoMuseOutreachJournal {
    static let messagePrefix = "nm-outreach-"

    struct Candidate {
        let text: String
        let goalID: String?
    }
    enum Result {
        case later, spent, delivered(String, Candidate)
    }

    static func withinHours(_ at: Date, calendar: Calendar = .current) -> Bool {
        (9..<20).contains(calendar.component(.hour, from: at))
    }

    static func write(db: OpaquePointer?, owner: String, session: String, day: String, at: Date,
                      candidate: () -> Candidate?, dirty: (String) -> Void) -> Result {
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
        let ready = """
        SELECT 1 FROM sessions s WHERE s.id=? AND COALESCE(s.source,'')='' AND s.remote_origin_device_id IS NULL
          AND EXISTS (SELECT 1 FROM (SELECT role, created_at, part_flags, error_info FROM messages WHERE session_id=?
              ORDER BY sort_order DESC LIMIT 1) WHERE role='assistant' AND part_flags=1 AND error_info IS NULL AND created_at<=CAST(? AS REAL))
        """
        let stamp = String(at.timeIntervalSince1970)
        guard step(ready, [session, session, String(at.addingTimeInterval(-15 * 60).timeIntervalSince1970)]) == SQLITE_ROW,
              let choice = candidate(), let data = try? JSONEncoder().encode([ContentPart.text(choice.text)]),
              let parts = String(data: data, encoding: .utf8) else { return .later }
        let id = messagePrefix + UUID().uuidString.lowercased()
        let sql = """
        INSERT INTO messages(id,session_id,role,parts_json,created_at,updated_at,sort_order,part_flags)
        SELECT ?,?,'assistant',?,?,?,COALESCE(MAX(sort_order),-1)+1,1 FROM messages WHERE session_id=?
        """
        guard step(sql, [id, session, parts, stamp, stamp, session]) == SQLITE_DONE,
              step("INSERT OR REPLACE INTO nm_outreach_day(owner,day) VALUES(?,?)", [owner, day]) == SQLITE_DONE,
              step("UPDATE sessions SET updated_at=? WHERE id=?", [stamp, session]) == SQLITE_DONE else { return .later }
        dirty(id)
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
