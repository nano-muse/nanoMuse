import Foundation
import SQLite3
import XCTest
@testable import Minis

final class NanoMuseFeedChatTests: XCTestCase {
    typealias Context = NanoMuseFeedChatContext
    private let day = Date(timeIntervalSince1970: 1_795_392_000)
    private var calendar: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        return calendar
    }

    private func turn(_ text: String, _ step: Int, session: String = "local", reply: String = "Understood.") -> Context.Turn {
        .init(ref: .init(session: session, message: "turn-\(step)", at: day.addingTimeInterval(Double(step))),
              text: text, reply: reply)
    }

    func testTracksUnfinishedCommitmentsAndUsesNewDueDate() throws {
        let plan = turn("我答应明天把 Atlas 的清单发给编辑。", 1)
        let correction = turn("Atlas 清单从明天改到后天。", 2)
        let open = try XCTUnwrap(Context.outstanding([correction, plan], now: day, calendar: calendar).first)
        XCTAssertEqual(open.update, correction.text)
        XCTAssertEqual(open.ref, plan.ref)
        XCTAssertEqual(open.due, calendar.date(byAdding: .day, value: 2, to: calendar.startOfDay(for: day)))
        XCTAssertTrue(Context.outstanding([plan, correction, turn("Atlas 清单我已经发了。", 3)], now: day, calendar: calendar).isEmpty)
    }

    func testIgnoresQuestionsHypotheticalsNegationAndDeliveredDrafts() {
        let plan = "I will email the Atlas editor tomorrow"
        for text in ["Can I send the Atlas email tomorrow?", "Maybe I will email the Atlas editor tomorrow",
                     "I will not email the Atlas editor tomorrow", "I will email the Atlas editor", "She said I will email the Atlas editor tomorrow"] {
            XCTAssertTrue(Context.outstanding([turn(text, 1)], now: day, calendar: calendar).isEmpty, text)
        }
        let draft = "Dear Atlas editor,\nPlease review the two options in our attached agenda."
        XCTAssertTrue(Context.outstanding([turn(plan, 1, reply: draft)], now: day, calendar: calendar).isEmpty)
        XCTAssertTrue(Context.outstanding([turn(plan, 1), turn("Please draft the Atlas message", 2, reply: draft)], now: day, calendar: calendar).isEmpty)
        XCTAssertEqual(Context.outstanding([turn(plan, 1), turn("I already sent the Atlas email", 2, session: "other")], now: day, calendar: calendar).count, 1)
    }

    func testUnnamedCorrectionRequiresOnePrecedingCommitment() {
        let a = turn("I will email the Atlas editor tomorrow", 1)
        let b = turn("I will book the Cedar flight tomorrow", 2)
        let done = turn("I already sent it.", 3)
        XCTAssertTrue(Context.outstanding([a, done], now: day, calendar: calendar).isEmpty)
        XCTAssertEqual(Context.outstanding([a, b, done], now: day, calendar: calendar).count, 2)
        XCTAssertEqual(Context.outstanding([a, turn("I already sent the Cedar letter", 2)], now: day, calendar: calendar).count, 1)
    }

    func testNextWeekUsesCalendarWeekAndAmbiguousDatesStaySilent() throws {
        let tuesday = try XCTUnwrap(calendar.date(from: DateComponents(year: 2026, month: 11, day: 24)))
        func scheduled(_ text: String) -> [Context.Open] {
            let turn = Context.Turn(ref: .init(session: "local", message: "m", at: tuesday), text: text, reply: "OK")
            return Context.outstanding([turn], now: tuesday, calendar: calendar)
        }
        XCTAssertTrue(scheduled("我答应下周五提交 Atlas 清单。").isEmpty) // Ten days away, outside the preparation horizon.
        XCTAssertEqual(scheduled("我答应周五提交 Atlas 清单。").first?.due, calendar.date(byAdding: .day, value: 3, to: tuesday))
        XCTAssertEqual(scheduled("我答应下周一提交 Atlas 清单。").first?.due, calendar.date(byAdding: .day, value: 6, to: tuesday))
        XCTAssertTrue(scheduled("我答应周三或周五提交 Atlas 清单。").isEmpty)
        let request = turn("我明天要提交 Atlas 清单。", 1)
        let status = turn("Atlas 清单我还没提交。", 2)
        XCTAssertEqual(Context.outstanding([request, status], now: day, calendar: calendar).count, 1)
    }

    func testCrossWeekPromiseRemainsThroughDueDayAndTracksLaterChanges() throws {
        let tuesday = try XCTUnwrap(calendar.date(from: DateComponents(year: 2026, month: 11, day: 24)))
        func date(_ offset: Int) -> Date { calendar.date(byAdding: .day, value: offset, to: tuesday)! }
        func message(_ text: String, on offset: Int) -> Context.Turn {
            .init(ref: .init(session: "local", message: "m-\(offset)", at: date(offset)), text: text, reply: "OK")
        }
        func active(_ turns: [Context.Turn], on offset: Int) -> [Context.Open] {
            let now = date(offset)
            let refs = Context.retained(turns.map(\.ref), now: now, calendar: calendar)
            return Context.outstanding(turns.filter { refs.contains($0.ref) }, now: now, calendar: calendar)
        }
        let promise = message("我答应下周五提交 Atlas 清单。", on: 0)
        XCTAssertTrue(active([promise], on: 2).isEmpty)
        for offset in 3...10 {
            XCTAssertEqual(active([promise], on: offset).first?.due, date(10))
        }
        XCTAssertTrue(active([promise], on: 11).isEmpty)
        let move = message("Atlas 清单改到下周一。", on: 9)
        XCTAssertEqual(active([promise, move], on: 13).first?.due, date(13))
        XCTAssertTrue(active([promise, move], on: 14).isEmpty)
        let done = message("Atlas 清单已经完成。", on: 11)
        XCTAssertTrue(active([promise, move, done], on: 12).isEmpty)
        let cancel = message("Atlas 清单取消了。", on: 9)
        XCTAssertTrue(active([promise, cancel], on: 10).isEmpty)
        for status in ["取消", "已完成", "发了", "改期"] {
            XCTAssertTrue(active([promise, message(status, on: 9)], on: 10).isEmpty, status)
        }
        XCTAssertTrue(Context.retained([promise.ref], now: date(22), calendar: calendar).isEmpty)
        let refs = (0..<41).map { Context.Reference(session: "chat", message: "m-\($0)", at: tuesday) }
        XCTAssertEqual(Context.retained(refs, now: tuesday, calendar: calendar), Array(refs.dropFirst()))
    }

    func testReadsOriginalRowsAndChecksCurrentMemoryAndOrigin() throws {
        var db: OpaquePointer?
        XCTAssertEqual(sqlite3_open(":memory:", &db), SQLITE_OK)
        defer { sqlite3_close(db) }
        func execute(_ sql: String) { XCTAssertEqual(sqlite3_exec(db, sql, nil, nil, nil), SQLITE_OK) }
        execute("""
            CREATE TABLE sessions(id TEXT, source TEXT, memory_enabled INT, remote_origin_device_id TEXT);
            CREATE TABLE messages(id TEXT, session_id TEXT, role TEXT, created_at REAL, parts_json TEXT, sort_order INT, part_flags INT, error_info TEXT);
            INSERT INTO sessions VALUES ('local', NULL, 1, NULL);
            INSERT INTO messages VALUES ('turn-1','local','user',1,'[{"type":"text","value":"I will submit the Atlas report tomorrow"}]',1,1,NULL);
            INSERT INTO messages VALUES ('a','local','assistant',2,'[{"type":"text","value":"Understood."}]',2,1,NULL);
            """)
        let ref = turn("", 1).ref
        XCTAssertEqual(Context.read([ref], db: db).first?.reply, "Understood.")
        XCTAssertTrue(Context.read([.init(session: "other", message: ref.message, at: day)], db: db).isEmpty)
        execute("UPDATE sessions SET memory_enabled=0")
        XCTAssertTrue(Context.read([ref], db: db).isEmpty)
        execute("UPDATE sessions SET memory_enabled=1, remote_origin_device_id='other'")
        XCTAssertTrue(Context.read([ref], db: db).isEmpty)
        execute("UPDATE sessions SET remote_origin_device_id=NULL, source='shortcut'")
        XCTAssertTrue(Context.read([ref], db: db).isEmpty)
        execute("UPDATE sessions SET source=NULL; DELETE FROM messages WHERE role='assistant'")
        execute(#"UPDATE messages SET parts_json='[{"type":"text","value":"取消"}]' WHERE id='turn-1'"#)
        XCTAssertEqual(Context.read([ref], db: db).first?.text, "取消")
        execute("DELETE FROM messages WHERE id='turn-1'")
        XCTAssertTrue(Context.read([ref], db: db).isEmpty)
    }
}
