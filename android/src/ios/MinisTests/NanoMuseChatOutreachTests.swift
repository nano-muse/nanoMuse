import Foundation
import SQLite3
import XCTest
@testable import Minis

final class NanoMuseChatOutreachTests: XCTestCase {
    private var db: OpaquePointer?
    private var databaseURL: URL!
    private let now = Date(timeIntervalSince1970: 1_800_000_000)

    override func setUp() {
        super.setUp()
        databaseURL = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        XCTAssertEqual(sqlite3_open(databaseURL.path, &db), SQLITE_OK)
        execute("""
        CREATE TABLE sessions(id TEXT PRIMARY KEY, source TEXT, remote_origin_device_id TEXT, updated_at REAL);
        CREATE TABLE messages(id TEXT PRIMARY KEY, session_id TEXT, role TEXT, parts_json TEXT, created_at REAL,
          updated_at REAL, sort_order INTEGER, part_flags INTEGER, error_info TEXT);
        INSERT INTO sessions VALUES('main',NULL,NULL,0);
        INSERT INTO messages VALUES('first','main','assistant','[]',0,0,1,1,NULL);
        """)
    }
    override func tearDown() {
        sqlite3_close(db)
        db = nil
        try? FileManager.default.removeItem(at: databaseURL)
        super.tearDown()
    }

    private func execute(_ sql: String) { XCTAssertEqual(sqlite3_exec(db, sql, nil, nil, nil), SQLITE_OK) }
    private func count(_ sql: String) -> Int {
        var stmt: OpaquePointer?
        defer { sqlite3_finalize(stmt) }
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, sqlite3_step(stmt) == SQLITE_ROW else { return -1 }
        return Int(sqlite3_column_int64(stmt, 0))
    }
    private func deliver(owner: String = "owner", day: String = "2026-11-25", choice: Bool = true, calendarReceipt: String? = nil) -> String {
        let result = NanoMuseOutreachJournal.write(db: db, owner: owner, session: "main", day: day, at: now, allowEmpty: calendarReceipt != nil, candidate: {
            choice ? .init(text: "Do you want to prepare the museum inquiry?", goalID: nil, calendarReceipt: calendarReceipt) : nil
        }, dirty: { _ in })
        switch result {
        case .spent: return "spent"
        case .seenCalendarChange: return "seen"
        case .later: return "later"
        case .delivered(let id, _):
            XCTAssertTrue(id.hasPrefix(NanoMuseOutreachJournal.messagePrefix))
            return "sent"
        }
    }

    func testRealAssistantRowCanBeReadAfterRestartAndDeletionDoesNotReplayIt() {
        XCTAssertEqual(deliver(), "sent")
        XCTAssertEqual(sqlite3_close(db), SQLITE_OK)
        XCTAssertEqual(sqlite3_open(databaseURL.path, &db), SQLITE_OK)
        XCTAssertEqual(count("SELECT COUNT(*) FROM messages WHERE role='assistant' AND sort_order=2 AND parts_json LIKE '%museum%'"), 1)
        XCTAssertEqual(deliver(), "spent")
        execute("DELETE FROM messages WHERE sort_order=2")
        XCTAssertEqual(deliver(), "spent")
        XCTAssertEqual(deliver(day: "2026-11-24"), "spent")
        XCTAssertEqual(deliver(day: "2026-11-26"), "sent")
    }

    func testSourceRemovalAndCommitFailureLeaveBudgetAvailable() {
        XCTAssertEqual(deliver(choice: false), "later")
        execute("CREATE TRIGGER stop_write BEFORE UPDATE ON sessions BEGIN SELECT RAISE(ABORT,'fixture'); END;")
        XCTAssertEqual(deliver(), "later")
        XCTAssertEqual(count("SELECT COUNT(*) FROM messages"), 1)
        execute("DROP TRIGGER stop_write")
        XCTAssertEqual(deliver(), "sent")
    }

    func testDatabaseBusyRetriesAndReceiptsArePerOwner() {
        var other: OpaquePointer?
        XCTAssertEqual(sqlite3_open(databaseURL.path, &other), SQLITE_OK)
        defer { sqlite3_close(other) }
        XCTAssertEqual(sqlite3_exec(other, "BEGIN IMMEDIATE", nil, nil, nil), SQLITE_OK)
        XCTAssertEqual(deliver(), "later")
        XCTAssertEqual(sqlite3_exec(other, "COMMIT", nil, nil, nil), SQLITE_OK)
        XCTAssertEqual(deliver(), "sent")
        execute("DELETE FROM messages WHERE sort_order=2")
        XCTAssertEqual(deliver(owner: "second"), "sent")
        XCTAssertEqual(count("SELECT COUNT(*) FROM nm_outreach_day"), 2)
    }

    func testOnlySettledIdleLocalChatsReceiveMessages() {
        execute("UPDATE sessions SET remote_origin_device_id='peer'")
        XCTAssertEqual(deliver(), "later")
        execute("UPDATE sessions SET remote_origin_device_id=NULL, source='scheduled'")
        XCTAssertEqual(deliver(), "later")
        execute("UPDATE sessions SET source=NULL; UPDATE messages SET role='user'")
        XCTAssertEqual(deliver(), "later")
        execute("UPDATE messages SET role='assistant', part_flags=3")
        XCTAssertEqual(deliver(), "later")
        execute("UPDATE messages SET part_flags=1,error_info='stopped'")
        XCTAssertEqual(deliver(), "later")
        execute("UPDATE messages SET error_info=NULL, created_at=\(Int(now.timeIntervalSince1970) - 899)")
        XCTAssertEqual(deliver(), "later")
        execute("UPDATE messages SET created_at=\(Int(now.timeIntervalSince1970) - 900)")
        XCTAssertEqual(deliver(), "sent")
    }

    func testCalendarCanStartAnEmptyMainChatAndItsReceiptSurvivesDeletion() {
        execute("DELETE FROM messages")
        XCTAssertEqual(deliver(), "later")
        execute("UPDATE sessions SET remote_origin_device_id='peer'")
        XCTAssertEqual(deliver(calendarReceipt: "changed"), "later")
        execute("UPDATE sessions SET remote_origin_device_id=NULL")
        execute("CREATE TRIGGER stop_write BEFORE UPDATE ON sessions BEGIN SELECT RAISE(ABORT,'fixture'); END;")
        XCTAssertEqual(deliver(calendarReceipt: "changed"), "later")
        execute("DROP TRIGGER stop_write")
        XCTAssertEqual(deliver(calendarReceipt: "changed"), "sent")
        execute("DELETE FROM messages")
        XCTAssertEqual(deliver(day: "2026-11-26", calendarReceipt: "changed"), "seen")
        XCTAssertEqual(deliver(day: "2026-11-26", calendarReceipt: "different"), "sent")
    }

    func testLocalHoursAndRevocation() {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 8 * 3600)!
        for (hour, eligible) in [(8, false), (9, true), (19, true), (20, false)] {
            let date = calendar.date(from: DateComponents(year: 2026, month: 11, day: 25, hour: hour))!
            XCTAssertEqual(NanoMuseOutreachJournal.withinHours(date, calendar: calendar), eligible)
        }
        let permit = NanoMuseOutreachPermit()
        let earlier = permit.snapshot()
        permit.revoke()
        if case .later = permit.perform(earlier, { XCTFail("revoked writer ran"); return .spent }) {} else { XCTFail() }
    }
}
