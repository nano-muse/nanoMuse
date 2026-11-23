import Foundation
import XCTest
@testable import Minis

final class NanoMuseCalendarChangesTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 1_800_000_000)
    private func slot(_ id: String, _ start: Int, _ stop: Int) -> NanoMuseCalendarChanges.Slot {
        .init(key: id, start: now.addingTimeInterval(Double(start * 60)), end: now.addingTimeInterval(Double(stop * 60)))
    }
    private func read(_ slots: [NanoMuseCalendarChanges.Slot], after hours: Int = 0) -> NanoMuseCalendarChanges.Snapshot {
        let at = now.addingTimeInterval(Double(hours * 3600))
        return .init(read: at, through: at.addingTimeInterval(48 * 3600), slots: slots)
    }

    func testFirstReadAndStaleBaselineAreSilent() {
        let a = slot("a", 60, 120), b = slot("b", 100, 140)
        XCTAssertNil(NanoMuseCalendarChanges.next(previous: nil, current: read([a, b])))
        XCTAssertNil(NanoMuseCalendarChanges.next(previous: read([], after: -37), current: read([a, b])))
        XCTAssertNil(NanoMuseCalendarChanges.next(previous: read([a, b]), current: read([b, a])))
    }

    func testNewOverlapPrecedesMoveAndExcludesTouchingAndPastSlots() {
        let a = slot("a", 60, 120), b = slot("b", 120, 180), changed = slot("b", 95, 155)
        XCTAssertEqual(NanoMuseCalendarChanges.next(previous: read([a, b]), current: read([changed, a])), .conflict(a, changed))
        XCTAssertNil(NanoMuseCalendarChanges.next(previous: read([a]), current: read([a, b])))
        XCTAssertNil(NanoMuseCalendarChanges.next(previous: read([]), current: read([slot("past", -100, -15), slot("now", -20, 10)])))
    }

    func testUpcomingMoveRequiresFifteenMinutesAndPreviouslyCoveredHorizon() {
        let a = slot("a", 75, 95), early = slot("a", 60, 80)
        XCTAssertEqual(NanoMuseCalendarChanges.next(previous: read([a]), current: read([early])), .moved(from: a, to: early))
        XCTAssertNil(NanoMuseCalendarChanges.next(previous: read([a]), current: read([slot("a", 61, 81)])))
        XCTAssertNil(NanoMuseCalendarChanges.next(previous: read([a]), current: read([])))
        XCTAssertNil(NanoMuseCalendarChanges.next(previous: read([], after: -30), current: read([slot("a", 1200, 1280), slot("b", 1210, 1290)])))
        XCTAssertNil(NanoMuseCalendarChanges.next(previous: read([]), current: read([slot("a", 1500, 1550), slot("b", 1520, 1600)])))
    }
}
