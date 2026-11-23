import Combine
import Foundation
import UIKit
import UserNotifications

@MainActor
final class NanoMuseChatOutreach: ObservableObject {
    static let shared = NanoMuseChatOutreach()
    nonisolated static let preference = "nanomuse.feed.chatOutreach"
    nonisolated static let notificationID = "nanomuse.chat.outreach"
    private let permit = NanoMuseOutreachPermit()
    private var subscriptions = Set<AnyCancellable>()
    private var switching = false
    private var checking = false
    private var spent: (owner: String, day: String)?
    private var pendingTap: [String: String]?
    private var visibleMain: String?
    private var unreadMain: String?
    @Published private(set) var tapRevision = 0

    private var enabled: Bool {
        UserDefaults.standard.bool(forKey: Self.preference) &&
        (UserDefaults.standard.object(forKey: "nanomuse.shell.enabled") as? Bool ?? true)
    }

    func changeAccount(_ leaving: Bool) {
        permit.revoke()
        switching = leaving
        spent = nil
        pendingTap = nil
        unreadMain = nil
        visibleMain = nil
        clearNotification()
    }

    func setEnabled(_ value: Bool) {
        permit.revoke()
        UserDefaults.standard.set(value, forKey: Self.preference)
        if value {
            NanoMuseScheduler.shared.requestNotificationPermission()
            Task { await check() }
        } else { clearNotification() }
    }

    private func clearNotification() {
        let center = UNUserNotificationCenter.current()
        center.removePendingNotificationRequests(withIdentifiers: [Self.notificationID])
        center.removeDeliveredNotifications(withIdentifiers: [Self.notificationID])
    }

    // The Muse shell keeps the chat mounted behind its other tabs. A cached view model
    // cannot tell whether the person can actually see this conversation.
    func showingMain(_ session: String?) {
        visibleMain = session
        guard let session, unreadMain == session, UIApplication.shared.applicationState == .active,
              !switching, !SessionLockStore.shared.appIsLocked, !SessionLockStore.shared.isLocked(session),
              NanoMuseAccountData.shared.owner(of: session) == NanoMuseAccountData.shared.current else { return }
        unreadMain = nil
        clearNotification()
        NotificationCenter.default.post(name: .nmChatOutreachDelivered, object: session)
    }

    private func observe() {
        guard subscriptions.isEmpty else { return }
        let lock = SessionLockStore.shared
        lock.$lockedSessionIds.dropFirst().sink { [permit] _ in permit.revoke() }.store(in: &subscriptions)
        lock.$appIsLocked.dropFirst().sink { [permit] _ in permit.revoke() }.store(in: &subscriptions)
        SessionActivityTracker.shared.$activeSessions.dropFirst().sink { [permit] _ in permit.revoke() }.store(in: &subscriptions)
        NanoMuseGoalStore.shared.$goals.dropFirst().sink { [permit] _ in permit.revoke() }.store(in: &subscriptions)
        NanoMuseScheduler.shared.$routines.dropFirst().sink { [permit] _ in permit.revoke() }.store(in: &subscriptions)
        NotificationCenter.default.publisher(for: .nmFeedChatChanged).sink { [permit] _ in permit.revoke() }.store(in: &subscriptions)
    }

    func nextRefresh(after now: Date) -> Date? {
        guard enabled, !switching else { return nil }
        let calendar = Calendar.current
        if NanoMuseOutreachJournal.withinHours(now), spent?.day != NanoMuseGoalDeadline.key(now) {
            return now.addingTimeInterval(60 * 60)
        }
        return calendar.nextDate(after: now, matching: DateComponents(hour: 9, minute: 0), matchingPolicy: .nextTime)
    }

    func check(now: Date = Date()) async {
        guard !checking, !Task.isCancelled, enabled, !switching, NanoMuseOutreachJournal.withinHours(now),
              UIApplication.shared.isProtectedDataAvailable, !SessionLockStore.shared.appIsLocked,
              let session = UserDefaults.standard.string(forKey: NanoMuseMainChat.key),
              !SessionLockStore.shared.isLocked(session), !SessionActivityTracker.shared.activeSessions.contains(session) else { return }
        let accounts = NanoMuseAccountData.shared
        let owner = accounts.current
        guard accounts.owner(of: session) == owner else { return }
        let day = NanoMuseGoalDeadline.key(now)
        if let spent, spent.owner == owner && spent.day >= day { return }
        observe()
        let version = permit.snapshot()
        let excluded = SessionLockStore.shared.lockedSessionIds
        let checked = NanoMuseScheduler.shared.checkedGoalIDs
        let showGoals = UserDefaults.standard.object(forKey: NanoMuseGoalDeadline.preference) as? Bool ?? true
        let goals = showGoals ? NanoMuseGoalStore.shared.goals.filter {
            $0.due == day && $0.canShowDeadline(excluding: excluded) && !$0.hasActiveChecks(in: checked)
                && ($0.deadlineSnoozedUntil ?? day) <= day
                && [$0.sourceSessionId, $0.sessionId].compactMap { $0 }.allSatisfy { accounts.owner(of: $0) == owner }
        }.sorted { $0.createdAt < $1.createdAt } : []
        let refs = NanoMuseFeedChatIndex.references(now: now).filter { $0.session == session }
        guard !goals.isEmpty || !refs.isEmpty else { return }
        checking = true
        defer { checking = false }
        let result = await ChatStore.shared.nmDeliverOutreach(owner: NanoMuseAccountData.dirName(owner), session: session,
            day: day, now: now, references: refs, goal: goals.first, permit: permit, version: version)
        guard !switching, enabled, accounts.current == owner else { return }
        switch result {
        case .later: return
        case .spent: spent = (owner, day)
        case .delivered(_, let item):
            spent = (owner, day)
            guard !SessionLockStore.shared.appIsLocked, !SessionLockStore.shared.isLocked(session),
                  UserDefaults.standard.string(forKey: NanoMuseMainChat.key) == session else { return }
            NanoMuseSync.shared.conversationChanged(session)
            unreadMain = session
            showingMain(visibleMain)
            if unreadMain == session {
                SessionBadgeStore.shared.pushFront(.unread, for: session)
                // A separate 09:00 goal alert may already have been delivered for this goal.
                if item.goalID == nil || !UserDefaults.standard.bool(forKey: NanoMuseGoalDeadline.notifyPreference) {
                    let content = UNMutableNotificationContent()
                    content.title = "nanoMuse"
                    content.body = AppLocalized("I left you a message in our chat.")
                    content.sound = .default
                    content.userInfo = ["owner": NanoMuseAccountData.dirName(owner), "chat": session]
                    try? await UNUserNotificationCenter.current().add(.init(identifier: Self.notificationID, content: content, trigger: nil))
                    if !enabled || switching || accounts.current != owner || unreadMain != session { clearNotification() }
                }
            }
        }
    }

    func tapped(_ info: [String: String]) { pendingTap = info; tapRevision &+= 1 }
    func takeTap() -> Bool {
        guard !SessionLockStore.shared.appIsLocked, let info = pendingTap else { return false }
        pendingTap = nil
        guard enabled, !switching, let session = info["chat"],
              UserDefaults.standard.string(forKey: NanoMuseMainChat.key) == session,
              !SessionLockStore.shared.isLocked(session) else { return false }
        let accounts = NanoMuseAccountData.shared
        return accounts.owner(of: session) == accounts.current && info["owner"] == NanoMuseAccountData.dirName(accounts.current)
    }
}

extension Notification.Name {
    static let nmChatOutreachDelivered = Notification.Name("NanoMuseChatOutreachDelivered")
}
