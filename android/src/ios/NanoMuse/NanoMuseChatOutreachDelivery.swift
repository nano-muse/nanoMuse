import Combine
import Foundation
import UIKit
import UserNotifications

@MainActor
final class NanoMuseChatOutreach: ObservableObject {
    static let shared = NanoMuseChatOutreach()
    nonisolated static let preference = "nanomuse.feed.chatOutreach"
    nonisolated static func chatEnabled(in defaults: UserDefaults = .standard) -> Bool {
        defaults.object(forKey: preference) as? Bool ?? true
    }
    nonisolated static let notificationID = "nanomuse.chat.outreach"
    private let permit = NanoMuseOutreachPermit()
    private var subscriptions = Set<AnyCancellable>()
    private var switching = false
    private var checking = false
    private var nextCalendarRead = Date.distantPast
    private var spent: (owner: String, day: String)?
    private var pendingTap: [String: String]?
    private var visibleMain: String?
    private var unreadMain: String?
    @Published private(set) var tapRevision = 0

    private var enabled: Bool {
        (Self.chatEnabled() || !NanoMuseCalendarWatch.selected.isEmpty) &&
        (UserDefaults.standard.object(forKey: "nanomuse.shell.enabled") as? Bool ?? true)
    }

    func changeAccount(_ leaving: Bool) {
        permit.revoke()
        NanoMusePublicWatches.shared.accountChanged(leaving)
        nextCalendarRead = .distantPast
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
        if !value { NanoMuseFeedChatIndex.clearMainOnlyReferences() }
        if value {
            NanoMuseScheduler.shared.requestNotificationPermission()
            Task { await check() }
        } else if !enabled { clearNotification() }
    }

    func setCalendars(_ selected: Set<String>, owner: String) {
        guard !switching, owner == NanoMuseAccountData.shared.current,
              selected.isEmpty || NanoMuseCalendarReader.readable else { return }
        permit.revoke()
        let defaults = UserDefaults.standard
        defaults.set(Array(selected).sorted(), forKey: NanoMuseCalendarWatch.selection)
        defaults.removeObject(forKey: NanoMuseCalendarWatch.baseline)
        nextCalendarRead = .distantPast
        if !selected.isEmpty {
            NanoMuseScheduler.shared.requestNotificationPermission()
            NanoMuseScheduler.shared.scheduleBackgroundRefresh()
            Task { await check() }
        } else if !enabled { clearNotification() }
    }

    func revokePublicWork() { permit.revoke() }

    func publicTicket(owner: String, session: String) -> UInt? {
        guard !switching, UserDefaults.standard.object(forKey: "nanomuse.shell.enabled") as? Bool ?? true, !Task.isCancelled,
              UIApplication.shared.isProtectedDataAvailable, !SessionLockStore.shared.appIsLocked,
              !SessionLockStore.shared.isLocked(session), !SessionActivityTracker.shared.activeSessions.contains(session),
              NanoMuseAccountData.shared.current == owner, NanoMuseAccountData.shared.owner(of: session) == owner,
              UserDefaults.standard.string(forKey: NanoMuseMainChat.key) == session else { return nil }
        observe()
        return permit.snapshot()
    }

    func canReviewPublic(owner: String, now: Date) -> Bool {
        Self.chatEnabled() && NanoMuseOutreachJournal.withinHours(now) &&
            !(spent?.owner == owner && (spent?.day ?? "") >= NanoMuseGoalDeadline.key(now))
    }

    func deliverPublic(_ item: NanoMuseOutreachJournal.Candidate, owner: String, session: String, ticket: UInt) async -> Bool {
        let now = Date()
        guard publicTicket(owner: owner, session: session) == ticket,
              canReviewPublic(owner: owner, now: now) else { return false }
        let day = NanoMuseGoalDeadline.key(now)
        let result = await ChatStore.shared.nmDeliverOutreach(owner: NanoMuseAccountData.dirName(owner), session: session,
            day: day, now: now, references: [], goal: nil, permit: permit, version: ticket, publicItem: item)
        guard !switching, NanoMuseAccountData.shared.current == owner else { return false }
        if case .seenPublicChange = result { return true }
        await show(result, session: session, owner: owner, day: day)
        if case .delivered = result { return true }
        return false
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

    private func dueGoal(on day: String, owner: String) -> NanoMuseGoal? {
        guard UserDefaults.standard.object(forKey: NanoMuseGoalDeadline.preference) as? Bool ?? true else { return nil }
        let excluded = SessionLockStore.shared.lockedSessionIds
        let checked = NanoMuseScheduler.shared.checkedGoalIDs
        let accounts = NanoMuseAccountData.shared
        return NanoMuseGoalStore.shared.goals.filter {
            $0.due == day && $0.canShowDeadline(excluding: excluded) && !$0.hasActiveChecks(in: checked)
                && ($0.deadlineSnoozedUntil ?? day) <= day
                && [$0.sourceSessionId, $0.sessionId].compactMap { $0 }.allSatisfy { accounts.owner(of: $0) == owner }
        }.min { $0.createdAt < $1.createdAt }
    }

    func check(now: Date = Date()) async {
        guard !checking, !Task.isCancelled, enabled, !switching, UIApplication.shared.isProtectedDataAvailable,
              !SessionLockStore.shared.appIsLocked else { return }
        let accounts = NanoMuseAccountData.shared
        let owner = accounts.current
        let sessionID = UserDefaults.standard.string(forKey: NanoMuseMainChat.key)
        if let session = sessionID, accounts.owner(of: session) != owner || SessionLockStore.shared.isLocked(session)
            || SessionActivityTracker.shared.activeSessions.contains(session) { return }
        observe()
        checking = true
        defer { checking = false }
        let version = permit.snapshot()
        let day = NanoMuseGoalDeadline.key(now)
        let canSend = NanoMuseOutreachJournal.withinHours(now) && !(spent?.owner == owner && (spent?.day ?? "") >= day)
        let selection = NanoMuseCalendarWatch.selected
        let defaults = UserDefaults.standard
        var sample: NanoMuseCalendarChanges.Snapshot?
        var calendarItem: NanoMuseOutreachJournal.Candidate?
        if !selection.isEmpty {
            if !NanoMuseCalendarReader.readable {
                defaults.removeObject(forKey: NanoMuseCalendarWatch.baseline)
            } else if now >= nextCalendarRead && (canSend || defaults.data(forKey: NanoMuseCalendarWatch.baseline) == nil) {
                nextCalendarRead = now.addingTimeInterval(10 * 60)
                sample = await NanoMuseCalendarReader.shared.snapshot(selection, at: now)
                guard !Task.isCancelled, permit.snapshot() == version, !switching, accounts.current == owner,
                      selection == NanoMuseCalendarWatch.selected, NanoMuseCalendarReader.readable else { return }
                if let sample {
                    calendarItem = NanoMuseCalendarWatch.compare(sample)
                    if calendarItem == nil { NanoMuseCalendarWatch.save(sample) }
                }
            }
        }
        guard canSend, let session = sessionID, defaults.string(forKey: NanoMuseMainChat.key) == session else { return }
        let chatEnabled = Self.chatEnabled(in: defaults)
        let goal = chatEnabled ? dueGoal(on: day, owner: owner) : nil
        let refs = chatEnabled ? NanoMuseFeedChatIndex.references(now: now, forMainChat: session) : []
        guard calendarItem != nil || goal != nil || !refs.isEmpty else { return }
        let result = await ChatStore.shared.nmDeliverOutreach(owner: NanoMuseAccountData.dirName(owner), session: session,
            day: day, now: now, references: refs, goal: goal, permit: permit, version: version, calendarItem: calendarItem)
        guard !switching, enabled, accounts.current == owner else { return }
        if let sample, permit.snapshot() == version, selection == NanoMuseCalendarWatch.selected, NanoMuseCalendarReader.readable {
            switch result {
            case .seenCalendarChange: NanoMuseCalendarWatch.save(sample)
            case .delivered(_, let item) where item.calendarReceipt != nil: NanoMuseCalendarWatch.save(sample)
            default: break
            }
        }
        await show(result, session: session, owner: owner, day: day)
    }

    private func show(_ result: NanoMuseOutreachJournal.Result, session: String, owner: String, day: String) async {
        switch result {
        case .later, .seenCalendarChange, .seenPublicChange: return
        case .spent: spent = (owner, day)
        case .delivered(_, let item):
            spent = (owner, day)
            guard !SessionLockStore.shared.appIsLocked, !SessionLockStore.shared.isLocked(session),
                  UserDefaults.standard.string(forKey: NanoMuseMainChat.key) == session else { return }
            if item.publicReceipt == nil { NanoMuseSync.shared.conversationChanged(session) }
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
