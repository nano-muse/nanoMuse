import XCTest
@testable import Minis

final class NanoMuseGoalDeadlineTests: XCTestCase {
    private let zone = TimeZone(identifier: "America/Los_Angeles")!

    private func goal(_ title: String, _ due: String?) -> NanoMuseGoal {
        var goal = NanoMuseGoal(id: title, title: title)
        goal.changeDue(to: due)
        return goal
    }

    func testParsesOnlyRealExplicitDatesAndReadsLegacyGoals() throws {
        let leap = try XCTUnwrap(NanoMuseGoal.from(block: ["title": "Renew membership", "due": "2028-02-29"]))
        XCTAssertEqual(leap.goal.due, "2028-02-29")
        for invalid in ["tomorrow", "2026-02-29", "2026-13-05", "2026-3-01", "2026-03-00", "2026-03-01T09:00:00Z"] {
            XCTAssertNil(NanoMuseGoal.from(block: ["title": "Renew membership", "due": invalid])?.goal.due)
        }
        let encoded = try JSONEncoder().encode(goal("Existing", nil))
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: encoded) as? [String: Any])
        XCTAssertNil(object["due"])
        let old = try JSONDecoder().decode(NanoMuseGoal.self, from: encoded)
        XCTAssertNil(old.due)
        XCTAssertNil(old.dismissedDeadline)
        XCTAssertNil(old.deadlineSnoozedUntil)
    }

    func testSelectsOneRecentDeadlineInLocalCalendarOrder() throws {
        // At this UTC instant it is still March 8 on the US west coast, after the DST change.
        let now = try XCTUnwrap(ISO8601DateFormatter().date(from: "2026-03-09T06:00:00Z"))
        let today = goal("Today", "2026-03-08")
        let yesterday = goal("Yesterday", "2026-03-07")
        let oldest = goal("Last week", "2026-03-01")
        let tomorrow = goal("Tomorrow", "2026-03-09")
        let others = [goal("Stale", "2026-02-28"), goal("Later", "2026-03-10"), goal("No date", nil)]
        func next(_ goals: [NanoMuseGoal]) -> NanoMuseGoalDeadline? {
            NanoMuseGoalDeadline.next(in: goals + others, at: now, zone: zone)
        }
        XCTAssertNil(next([]))
        XCTAssertEqual(next([oldest, tomorrow, today, yesterday])?.goal.id, today.id)
        XCTAssertEqual(next([tomorrow, oldest, yesterday])?.goal.id, yesterday.id)
        XCTAssertEqual(next([tomorrow, oldest])?.daysAway, -7)
        XCTAssertEqual(next([tomorrow])?.daysAway, 1)
        XCTAssertEqual(NanoMuseGoalDeadline.tomorrow(after: now, in: zone), "2026-03-09")
        XCTAssertEqual(next([goal("B", today.due), goal("A", today.due)])?.goal.id, "A")
    }

    func testProtectingEitherConversationRemovesGoalFromFeedSelection() throws {
        let now = try XCTUnwrap(NanoMuseGoalDeadline.date("2026-11-02", in: zone))
        var privateGoal = goal("Today", "2026-11-02")
        privateGoal.sessionId = "tracking"
        privateGoal.sourceSessionId = "creation"
        let publicGoal = goal("Tomorrow", "2026-11-03")
        for protected in [Set(["tracking"]), Set(["creation"])] {
            let card = NanoMuseGoalDeadline.next(in: [privateGoal, publicGoal], at: now, zone: zone, excluding: protected)
            XCTAssertEqual(card?.goal.id, publicGoal.id)
        }
        XCTAssertEqual(NanoMuseGoalDeadline.next(in: [privateGoal], at: now, zone: zone)?.goal.id, privateGoal.id)
    }

    func testOptionalNoticePicksOnlyOneEligibleMorningAndDoesNotCatchUp() throws {
        let morning = try XCTUnwrap(ISO8601DateFormatter().date(from: "2026-11-02T16:00:00Z")) // 08:00 PST
        let afterNine = morning.addingTimeInterval(3601)
        let first = try XCTUnwrap(NanoMuseGoal.from(block: ["title": "Today", "due": "2026-11-02", "scheduled_checks": false])).goal
        var later = goal("Later", "2026-11-03")
        later.scheduledChecks = false
        func plan(_ goals: [NanoMuseGoal], _ now: Date = morning, protected: Set<String> = [], checked: Set<String> = []) -> NanoMuseGoalDeadline.Notice? {
            NanoMuseGoalDeadline.nextNotice(in: goals, at: now, zone: zone, excluding: protected, checkedGoals: checked)
        }
        var regular = goal("Regular checks", "2026-11-02")
        XCTAssertNil(plan([regular])) // awaiting creation of the default check
        regular.routineId = "created"
        let restored = try JSONDecoder().decode(NanoMuseGoal.self, from: JSONEncoder().encode(regular))
        XCTAssertNil(plan([restored], checked: [restored.id]))
        XCTAssertEqual(plan([restored])?.goalID, restored.id) // check disabled or deleted in Settings
        XCTAssertNil(plan([restored], checked: [restored.id])) // enabled again

        XCTAssertEqual(plan([first, later])?.goalID, first.id)
        XCTAssertEqual(plan([first])?.at, morning.addingTimeInterval(3600))
        XCTAssertEqual(plan([first, later], afterNine)?.goalID, later.id)
        XCTAssertNil(plan([first], checked: [first.id]))
        var privateGoal = first
        privateGoal.sourceSessionId = "protected"
        XCTAssertNil(plan([privateGoal], protected: ["protected"]))
        var changed = first
        changed.deadlineSnoozedUntil = "2026-11-03"
        XCTAssertEqual(plan([changed], afterNine)?.day, "2026-11-03")
        changed.changeDue(to: "2026-11-06")
        XCTAssertEqual(plan([changed])?.day, "2026-11-06")
        changed.dismissedDeadline = changed.due
        XCTAssertNil(plan([changed]))
        changed.dismissedDeadline = nil
        changed.status = .done
        XCTAssertNil(plan([changed]))
    }

    func testSnoozeDismissAndStepCompletionSurviveReload() throws {
        let now = try XCTUnwrap(NanoMuseGoalDeadline.date("2026-11-02", in: zone))
        var g = goal("Packing", "2026-11-02")
        g.steps = [NanoMuseGoalStep(text: "Packed", done: true), NanoMuseGoalStep(text: "Print ticket")]
        func next(_ date: Date) -> NanoMuseGoalDeadline? {
            NanoMuseGoalDeadline.next(in: [g], at: date, zone: zone)
        }
        XCTAssertEqual(next(now)?.goal.steps.first(where: { !$0.done })?.text, "Print ticket")
        let original = try XCTUnwrap(next(now))
        XCTAssertTrue(g.respond(to: original, with: .snooze(until: NanoMuseGoalDeadline.tomorrow(after: now, in: zone))))
        XCTAssertFalse(g.respond(to: original, with: .completeStep(g.steps[1].id)))
        g = try JSONDecoder().decode(NanoMuseGoal.self, from: JSONEncoder().encode(g))
        XCTAssertNil(next(now))
        let tomorrow = try XCTUnwrap(NanoMuseGoalDeadline.date("2026-11-03", in: zone))
        XCTAssertEqual(next(tomorrow)?.daysAway, -1)
        let expiredSnooze = try XCTUnwrap(next(tomorrow))
        XCTAssertTrue(g.respond(to: expiredSnooze, with: .hide))
        XCTAssertFalse(g.respond(to: expiredSnooze, with: .completeStep(g.steps[1].id)))
        g.changeDue(to: g.due)
        XCTAssertNil(next(tomorrow))
        g.changeDue(to: "2026-11-03")
        XCTAssertEqual(next(tomorrow)?.daysAway, 0)
        let changedDeadline = try XCTUnwrap(next(tomorrow))
        XCTAssertFalse(g.respond(to: expiredSnooze, with: .hide))
        g.status = .paused
        XCTAssertFalse(g.respond(to: changedDeadline, with: .hide))
        XCTAssertNil(next(tomorrow))
        g.status = .done
        XCTAssertNil(next(tomorrow))
        g.status = .active
        XCTAssertFalse(g.respond(to: changedDeadline, with: .completeStep(g.steps[0].id)))
        XCTAssertTrue(g.respond(to: changedDeadline, with: .completeStep(g.steps[1].id)))
        XCTAssertFalse(g.respond(to: changedDeadline, with: .completeStep(g.steps[1].id)))
        XCTAssertNil(next(tomorrow))
        g.changeDue(to: nil)
        XCTAssertNil(g.due)
    }
}
