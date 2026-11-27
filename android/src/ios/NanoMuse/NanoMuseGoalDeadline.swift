// Local, date-only goal deadlines. The Feed can show these without a model or a background wake.
import Foundation

struct NanoMuseGoalDeadline {
    enum Response { case snooze(until: String), hide, completeStep(String) }

    let goal: NanoMuseGoal
    let due: Date
    let daysAway: Int

    static let preference = "nanomuse.feed.goal_deadlines"
    static let notifyPreference = "nanomuse.feed.deadline_notifications"

    struct Notice: Equatable {
        let goalID: String
        let due: String
        let day: String
        let at: Date
    }

    /// Schedule only the next 09:00 deadline. Never replay a missed morning or stack notices.
    static func nextNotice(
        in goals: [NanoMuseGoal], at now: Date, zone: TimeZone = .current,
        excluding protectedSessions: Set<String>, checkedGoals: Set<String>
    ) -> Notice? {
        let calendar = calendar(in: zone)
        return goals.compactMap { goal -> Notice? in
            guard goal.canShowDeadline(excluding: protectedSessions),
                  !goal.hasActiveChecks(in: checkedGoals),
                  let due = goal.due, let date = Self.date(due, in: zone) else { return nil }
            let day = max(due, goal.deadlineSnoozedUntil ?? due)
            guard let local = Self.date(day, in: zone),
                  let age = calendar.dateComponents([.day], from: date, to: local).day, age <= 7,
                  let at = calendar.date(bySettingHour: 9, minute: 0, second: 0, of: local), at > now else { return nil }
            return Notice(goalID: goal.id, due: due, day: day, at: at)
        }.min { ($0.at, $0.due, $0.goalID) < ($1.at, $1.due, $1.goalID) }
    }

    private static func calendar(in zone: TimeZone) -> Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = zone
        return calendar
    }

    static func key(_ date: Date, in zone: TimeZone = .current) -> String {
        let parts = calendar(in: zone).dateComponents([.year, .month, .day], from: date)
        return String(format: "%04d-%02d-%02d", parts.year!, parts.month!, parts.day!)
    }

    /// Reject invalid dates instead of rolling a February deadline into March.
    static func date(_ key: String?, in zone: TimeZone = .current) -> Date? {
        guard let key, key.utf8.count == 10 else { return nil }
        let parts = key.split(separator: "-", omittingEmptySubsequences: false)
        guard parts.count == 3, let year = Int(parts[0]), year > 0,
              let month = Int(parts[1]), let day = Int(parts[2]) else { return nil }
        let calendar = calendar(in: zone)
        guard let date = calendar.date(from: DateComponents(year: year, month: month, day: day, hour: 12)),
              Self.key(date, in: zone) == key else { return nil }
        return date
    }

    static func tomorrow(after now: Date, in zone: TimeZone = .current) -> String {
        let calendar = calendar(in: zone)
        return key(calendar.date(byAdding: .day, value: 1, to: now)!, in: zone)
    }

    /// Today first, then the most recently missed deadline, then tomorrow.
    static func next(
        in goals: [NanoMuseGoal], at now: Date, zone: TimeZone = .current,
        excluding protectedSessions: Set<String> = []
    ) -> Self? {
        let calendar = calendar(in: zone)
        let start = calendar.startOfDay(for: now)
        let today = key(now, in: zone)
        return goals.compactMap { goal -> Self? in
            guard goal.canShowDeadline(excluding: protectedSessions),
                  let due = date(goal.due, in: zone), goal.deadlineSnoozedUntil.map({ $0 <= today }) ?? true,
                  let days = calendar.dateComponents([.day], from: start, to: calendar.startOfDay(for: due)).day,
                  (-7...1).contains(days) else { return nil }
            return Self(goal: goal, due: due, daysAway: days)
        }.min {
            func rank(_ days: Int) -> Int { days == 1 ? 8 : -days }
            let lhs = rank($0.daysAway), rhs = rank($1.daysAway)
            return lhs == rhs ? $0.goal.id < $1.goal.id : lhs < rhs
        }
    }
}

extension NanoMuseGoal {
    /// Once set up, Settings can disable or delete a routine independently of its goal.
    /// Before a new goal's routine exists, respect the choice made during creation.
    func hasActiveChecks(in checkedGoals: Set<String>) -> Bool {
        checkedGoals.contains(id) || (routineId == nil && hasScheduledChecks)
    }

    func canShowDeadline(excluding protectedSessions: Set<String>) -> Bool {
        status == .active && due != nil && dismissedDeadline != due && !usesProtectedSession(in: protectedSessions)
            && (steps.isEmpty || steps.contains(where: { !$0.done }))
    }

    func usesProtectedSession(in ids: Set<String>) -> Bool {
        (sessionId.map(ids.contains) ?? false) || (sourceSessionId.map(ids.contains) ?? false)
    }

    mutating func changeDue(to value: String?) {
        guard value != due, value == nil || NanoMuseGoalDeadline.date(value) != nil else { return }
        due = value
        dismissedDeadline = nil
        deadlineSnoozedUntil = nil
    }

    /// An old card must never change a new deadline or mark a different step done.
    mutating func respond(to card: NanoMuseGoalDeadline, with response: NanoMuseGoalDeadline.Response) -> Bool {
        guard id == card.goal.id, status == .active, let due, due == card.goal.due,
              dismissedDeadline != due, deadlineSnoozedUntil == card.goal.deadlineSnoozedUntil else { return false }
        switch response {
        case .snooze(let until):
            deadlineSnoozedUntil = until
        case .hide:
            dismissedDeadline = due
        case .completeStep(let id):
            guard let index = steps.firstIndex(where: { !$0.done }), steps[index].id == id else { return false }
            steps[index].done = true
        }
        return true
    }
}
