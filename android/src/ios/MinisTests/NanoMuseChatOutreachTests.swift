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
        case .seenCalendarChange, .seenPublicChange: return "seen"
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

    func testFreshCheckInsAndSavedChoicesAfterAnUpgrade() {
        let suite = "nanomuse-checkins-" + UUID().uuidString
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }

        XCTAssertTrue(NanoMuseChatOutreach.chatEnabled(in: defaults))
        XCTAssertTrue(NanoMuseFeedChatIndex.allowsChatCheckIn(in: defaults))
        XCTAssertNil(defaults.object(forKey: NanoMuseFeedChatIndex.setting))
        XCTAssertNil(defaults.object(forKey: NanoMuseCalendarWatch.selection))

        defaults.set(false, forKey: NanoMuseFeedChatIndex.setting)
        XCTAssertTrue(NanoMuseChatOutreach.chatEnabled(in: defaults))
        XCTAssertFalse(NanoMuseFeedChatIndex.allowsChatCheckIn(in: defaults))
        defaults.set(true, forKey: NanoMuseFeedChatIndex.setting)
        defaults.set(false, forKey: NanoMuseChatOutreach.preference)
        XCTAssertFalse(NanoMuseChatOutreach.chatEnabled(in: defaults))
        XCTAssertFalse(NanoMuseFeedChatIndex.allowsChatCheckIn(in: defaults))
    }

    func testPublicWatchDeliveryIsLocalAndAnEarlierReceiptSurvivesOtherDaysAndRestart() {
        let name = "account", first = "2026-11-25"
        execute("DELETE FROM messages")
        func send(_ key: String, _ day: String) -> NanoMuseOutreachJournal.Result {
            NanoMuseOutreachJournal.write(db: db, owner: name, session: "main", day: day, at: now, allowEmpty: true,
                candidate: { .init(text: "New issue", goalID: nil, publicReceipt: key) },
                dirty: { _ in XCTFail("Local watch notice queued for sync") })
        }
        XCTAssertTrue(NanoMuseOutreachJournal.readyForPublicReview(db: db, owner: name, session: "main", day: first, at: now))
        guard case .delivered(let id, _) = send("one", first) else { return XCTFail("First notice missing") }
        XCTAssertTrue(id.hasPrefix(NanoMuseOutreachJournal.localPublicPrefix))
        execute("DELETE FROM messages")
        XCTAssertFalse(NanoMuseOutreachJournal.readyForPublicReview(db: db, owner: name, session: "main", day: first, at: now))
        guard case .delivered = send("two", "2026-11-26") else { return XCTFail("Second notice missing") }
        execute("DELETE FROM messages")
        XCTAssertEqual(sqlite3_close(db), SQLITE_OK)
        XCTAssertEqual(sqlite3_open(databaseURL.path, &db), SQLITE_OK)
        guard case .seenPublicChange = send("one", "2026-11-27") else { return XCTFail("Earlier receipt replayed") }
        XCTAssertEqual(count("SELECT COUNT(*) FROM messages"), 0)
        XCTAssertTrue(NanoMuseOutreachJournal.readyForPublicReview(db: db, owner: name, session: "main", day: "2026-11-27", at: now))
    }

    func testSyncedCitationMatchingRequiresTheOriginalTitleAndFullURL() {
        let item = NanoMuseWatchItem(id: "watch", key: "issue", text: "Report *one*", url: "https://example.org/issue/1", kind: "github_repo", target: "owner/project")
        let result = NanoMuseOutreachJournal.write(db: db, owner: "owner", session: "main", day: "2026-11-25", at: now,
            candidate: { .init(text: #"Report \*one\*"# + "\n" + item.url, goalID: nil) }, dirty: { _ in })
        guard case .delivered(let msg, _) = result else { return XCTFail("Missing fixture") }
        XCTAssertEqual(NanoMuseOutreachJournal.matchingPublicNotices(db: db, session: "main", item: item), [msg])
        XCTAssertTrue(NanoMuseOutreachJournal.matchingPublicNotices(db: db, session: "main", item:
            .init(id: "watch", key: "other", text: "Another issue", url: item.url, kind: item.kind, target: item.target)).isEmpty)
        XCTAssertTrue(NanoMuseOutreachJournal.matchingPublicNotices(db: db, session: "main", item:
            .init(id: "watch", key: "other", text: item.text, url: "https://example.org/issue/11", kind: item.kind, target: item.target)).isEmpty)
    }

    func testPublicReviewUsesTheExactSelectedSourceAndRejectsMalformedResponses() throws {
        let item = NanoMuseWatchItem(id: "watch", key: "paper", text: "[A study](made-up) *title*", url: "https://example.org/work",
                                     kind: "research_work", target: "10.1234/work")
        XCTAssertEqual(NanoMusePublicReview.choice("{\"pick\":1}", count: 1), 1)
        XCTAssertEqual(NanoMusePublicReview.choice("{\"pick\":0}", count: 1), 0)
        for malformed in ["null", "{\"pick\":true}", "{\"pick\":2}", "{\"pick\":-1}", "OK"] {
            XCTAssertNil(NanoMusePublicReview.choice(malformed, count: 1))
        }
        let message = try XCTUnwrap(NanoMusePublicReview.message(item))
        XCTAssertTrue(message.contains(item.url))
        XCTAssertFalse(message.contains("[A study](made-up)"))
        let context = try XCTUnwrap(NanoMusePublicReview.historyText(displayed: message))
        let body = try XCTUnwrap(context.components(separatedBy: "\n").last?.data(using: .utf8))
        let decoded = try JSONDecoder().decode([String: String].self, from: body)
        XCTAssertEqual(decoded["source_url"], item.url)
        XCTAssertEqual(decoded["publisher_title"], message.components(separatedBy: "\n").first)
        XCTAssertEqual(decoded["offer_shown"], message.components(separatedBy: "\n").last)
        XCTAssertNil(NanoMusePublicReview.historyText(displayed: "Arbitrary notice"))
        XCTAssertNil(NanoMusePublicReview.message(.init(id: "watch", key: "x", text: "Title", url: "file:///private/file",
                                                        kind: "feed", target: "")))
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
