import Combine
import Foundation
import UserNotifications

/// One replaceable, account-bound, on-device request. It opens the Feed and never runs a goal.
@MainActor
final class NanoMuseDeadlineNotifications: ObservableObject {
    static let shared = NanoMuseDeadlineNotifications()
    nonisolated static let identifier = "nanomuse.goal.deadline"
    nonisolated static let ownerKey = "nanomuse.deadline.owner"
    private let center = UNUserNotificationCenter.current()
    private var observers = Set<AnyCancellable>()
    private var revision: UInt = 0
    private var worker: Task<Void, Never>?
    private var switching = false
    private var tap: [String: String]?
    @Published private(set) var tapVersion = 0
    @Published private(set) var denied = false

    private var owner: String { NanoMuseAccountData.dirName(NanoMuseAccountData.shared.current) }
    private var enabled: Bool {
        let prefs = UserDefaults.standard
        return !switching && prefs.bool(forKey: NanoMuseGoalDeadline.notifyPreference)
            && (prefs.object(forKey: NanoMuseGoalDeadline.preference) as? Bool ?? true)
            && (prefs.object(forKey: "nanomuse.shell.enabled") as? Bool ?? true)
    }
    func start() {
        guard observers.isEmpty else { return }
        NanoMuseGoalStore.shared.$goals.sink { [weak self] _ in self?.refresh() }.store(in: &observers)
        NanoMuseScheduler.shared.$routines.sink { [weak self] _ in self?.refresh() }.store(in: &observers)
        SessionLockStore.shared.$lockedSessionIds.sink { [weak self] _ in self?.refresh() }.store(in: &observers)
    }

    func accountChanging(_ changing: Bool) {
        switching = changing
        if changing {
            tap = nil
            center.removePendingNotificationRequests(withIdentifiers: [Self.identifier])
            center.removeDeliveredNotifications(withIdentifiers: [Self.identifier])
        }
        refresh()
    }

    /// Serialize notification-center writes, including an account switch while an add is in flight.
    func refresh() {
        revision &+= 1
        guard worker == nil else { return }
        worker = Task { @MainActor in
            while true {
                let started = revision
                await reconcile(started)
                if started == revision { worker = nil; return }
            }
        }
    }

    private func reconcile(_ started: UInt) async {
        guard enabled else {
            center.removePendingNotificationRequests(withIdentifiers: [Self.identifier])
            center.removeDeliveredNotifications(withIdentifiers: [Self.identifier])
            return
        }
        let settings = await center.notificationSettings()
        guard started == revision else { return }
        let blocked = settings.authorizationStatus == .denied
        if denied != blocked { denied = blocked }
        guard [.authorized, .provisional, .ephemeral].contains(settings.authorizationStatus) else {
            center.removePendingNotificationRequests(withIdentifiers: [Self.identifier])
            return
        }
        let pending = await center.pendingNotificationRequests().first { $0.identifier == Self.identifier }
        let delivered = await center.deliveredNotifications().first { $0.request.identifier == Self.identifier }
        guard started == revision else { return }
        let now = Date()
        if let delivered, !stillRelevant(delivered.request.content.userInfo as? [String: String], now: now) {
            center.removeDeliveredNotifications(withIdentifiers: [Self.identifier])
        }
        guard let plan = NanoMuseGoalDeadline.nextNotice(
            in: NanoMuseGoalStore.shared.goals, at: now,
            excluding: SessionLockStore.shared.lockedSessionIds, checkedGoals: NanoMuseScheduler.shared.checkedGoalIDs
        ) else {
            if pending != nil { center.removePendingNotificationRequests(withIdentifiers: [Self.identifier]) }
            return
        }
        let info = [Self.ownerKey: owner, "goal": plan.goalID, "due": plan.due, "day": plan.day]
        if pending?.content.userInfo as? [String: String] == info,
           let trigger = pending?.trigger as? UNCalendarNotificationTrigger,
           trigger.nextTriggerDate() == plan.at { return }
        let content = UNMutableNotificationContent()
        content.title = "nanoMuse"
        content.body = AppLocalized("Open your Feed to review a goal deadline.")
        content.sound = .default
        content.userInfo = info
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = .current
        var components = calendar.dateComponents([.year, .month, .day, .hour, .minute], from: plan.at)
        components.calendar = Calendar(identifier: .gregorian)
        let trigger = UNCalendarNotificationTrigger(dateMatching: components, repeats: false)
        do {
            try await center.add(UNNotificationRequest(identifier: Self.identifier, content: content, trigger: trigger))
        } catch {
            // A failed replacement must not leave an earlier deadline scheduled.
            center.removePendingNotificationRequests(withIdentifiers: [Self.identifier])
            AppLogger(category: "NanoMuseDeadlineNotifications").warning("Could not schedule the goal deadline notification.")
        }
    }

    private func stillRelevant(_ info: [String: String]?, now: Date) -> Bool {
        guard enabled, let info, info[Self.ownerKey] == owner, let id = info["goal"],
              let goal = NanoMuseGoalStore.shared.goal(id: id), let due = goal.due,
              due == info["due"], let day = info["day"], day <= NanoMuseGoalDeadline.key(now),
              info["day"] == max(due, goal.deadlineSnoozedUntil ?? due),
              NanoMuseGoalDeadline.next(in: [goal], at: now, excluding: SessionLockStore.shared.lockedSessionIds) != nil,
              !goal.hasActiveChecks(in: NanoMuseScheduler.shared.checkedGoalIDs) else { return false }
        return true
    }

    func tapped(_ info: [String: String]) {
        tap = info
        tapVersion &+= 1
    }

    /// The shell consumes a cold or warm tap only after the app lock opens.
    func takeTap() -> Bool {
        guard !SessionLockStore.shared.appIsLocked, let info = tap else { return false }
        tap = nil
        return stillRelevant(info, now: Date())
    }
}
