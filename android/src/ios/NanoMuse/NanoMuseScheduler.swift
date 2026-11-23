//
//  NanoMuseScheduler.swift
//  nanoMuse
//
//  The iPhone's scheduler primitive: a due-list of routines (the daily
//  feed, goal check-ins, the routines made from Ideas) kept in a JSON file,
//  run by the app itself when it is in the foreground — on open, and while
//  it stays active — with a BGAppRefreshTask and local notifications for
//  the hours it is not. iOS gives an app no way to run a model turn on a
//  schedule while it sleeps: when a routine comes due and the app is not
//  up, the phone shows "Check-in: <goal> — open to run it", and the run
//  happens when the person opens the app. Android has WorkManager for this
//  (io.github.nanomuse.app.scheduled.*); the words here say what the phone can
//  and cannot do.
//

import Foundation
import BackgroundTasks
import UserNotifications
import UIKit

// MARK: - Model

struct NanoMuseRoutine: Codable, Identifiable, Equatable {
    enum Repeat: String, Codable, CaseIterable { case once, daily, weekdays }

    struct Run: Codable, Equatable {
        var at: Date
        var ok: Bool
        var note: String?
    }

    var id: String = UUID().uuidString
    var label: String
    var prompt: String
    var hour: Int
    var minute: Int
    var repeatMode: Repeat = .daily
    /// Goal checks run every N hours instead of at a time of day.
    var intervalHours: Int? = nil
    var enabled: Bool = true
    /// Hidden routines (goal check-ins, the feed) do not show under Routines.
    var hidden: Bool = false
    var goalId: String? = nil
    /// The conversation the runs land in; nil = a fresh side chat per run.
    var sessionId: String? = nil
    var createdAt: Date = Date()
    var lastFiredAt: Date? = nil
    var runs: [Run] = []

    var lastOk: Bool? { runs.first?.ok }

    /// "Checks every 6 hours" / "Daily 08:00" / "Weekdays 07:30" / "Once 18:00".
    var cadence: String {
        if let h = intervalHours, h > 0 {
            return h == 1 ? AppLocalized("Checks every hour") : String(format: AppLocalized("Checks every %d hours"), h)
        }
        let time = NanoMuseDay.clock(hour: hour, minute: minute)
        switch repeatMode {
        case .once: return String(format: AppLocalized("Once · %@"), time)
        case .daily: return String(format: AppLocalized("Daily · %@"), time)
        case .weekdays: return String(format: AppLocalized("Weekdays · %@"), time)
        }
    }

    // MARK: Due logic (pure, tested)

    /// The next moment this routine should run after `after`, or nil (a spent
    /// one-off, a disabled routine).
    func nextDue(after: Date, calendar: Calendar = .current) -> Date? {
        guard enabled else { return nil }
        if let hours = intervalHours, hours > 0 {
            // First check about a minute after creation, then every N hours.
            // Overdue reads as due now (the anchor is in the past); otherwise it is the next slot.
            return lastFiredAt.map { $0.addingTimeInterval(TimeInterval(hours) * 3600) }
                ?? createdAt.addingTimeInterval(60)
        }
        var components = calendar.dateComponents([.year, .month, .day], from: after)
        components.hour = hour
        components.minute = minute
        components.second = 0
        guard var candidate = calendar.date(from: components) else { return nil }
        // Already fired for this slot, or the slot is in the past → the next day that qualifies.
        var guardCount = 0
        while guardCount < 10 {
            guardCount += 1
            let firedThisSlot = lastFiredAt.map { $0 >= candidate } ?? false
            // A slot before the routine existed is not a missed one.
            let afterCreation = candidate > createdAt
            let qualifies: Bool = {
                switch repeatMode {
                case .once:
                    return lastFiredAt == nil
                case .daily:
                    return true
                case .weekdays:
                    let weekday = calendar.component(.weekday, from: candidate)
                    return weekday >= 2 && weekday <= 6
                }
            }()
            // In the future → the next run; already passed and never run → missed, due now.
            if qualifies && !firedThisSlot && afterCreation { return candidate }
            // A one-off that has run is spent; one made after today's time runs tomorrow.
            if repeatMode == .once && lastFiredAt != nil { return nil }
            guard let next = calendar.date(byAdding: .day, value: 1, to: candidate) else { return nil }
            candidate = next
        }
        return nil
    }

    /// True when the routine should run at `now` — its slot has passed and has not been run.
    func isDue(at now: Date, calendar: Calendar = .current) -> Bool {
        guard let due = nextDue(after: now, calendar: calendar) else { return false }
        return due <= now
    }
}

// MARK: - Store + runner

@MainActor
final class NanoMuseScheduler: ObservableObject {
    static let shared = NanoMuseScheduler()

    /// Also listed under BGTaskSchedulerPermittedIdentifiers in Info.plist.
    nonisolated static let backgroundTaskId = "io.github.nanomuse.app.scheduler"
    static let notificationCategory = "NANOMUSE_ROUTINE"
    private static let maxRunsKept = 10

    @Published private(set) var routines: [NanoMuseRoutine] = []
    /// Ids being run right now.
    @Published private(set) var running: Set<String> = []

    private var file: URL { NanoMuseDirs.root.appendingPathComponent("routines.json") }
    private var catchUpTask: Task<Void, Never>?
    private var notificationsTask: Task<Void, Never>?
    private var tickTimer: Timer?

    private init() {
        load()
    }

    // MARK: Persistence

    private func load() {
        guard let data = try? Data(contentsOf: file) else { return }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        routines = (try? decoder.decode([NanoMuseRoutine].self, from: data)) ?? []
    }

    /// C12: the file changed under the store — another account's routines are in place (or
    /// none). The list and the notifications follow.
    func reload() {
        // a catch-up under way was the account's that left: the routines still in its list
        // are not started (a run already talking to the model finishes in its own session)
        catchUpTask?.cancel()
        catchUpTask = nil
        routines = []
        load()
        refreshNotifications()
    }

    private func save() {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        if let data = try? encoder.encode(routines) {
            try? data.write(to: file, options: .atomic)
        }
        refreshNotifications()
    }

    // MARK: CRUD

    var visible: [NanoMuseRoutine] {
        routines.filter { !$0.hidden }.sorted { ($0.hour * 60 + $0.minute) < ($1.hour * 60 + $1.minute) }
    }

    func routine(id: String) -> NanoMuseRoutine? { routines.first { $0.id == id } }

    @discardableResult
    func create(_ routine: NanoMuseRoutine) -> NanoMuseRoutine {
        routines.append(routine)
        save()
        return routine
    }

    func update(_ routine: NanoMuseRoutine) {
        guard let i = routines.firstIndex(where: { $0.id == routine.id }) else { return }
        routines[i] = routine
        save()
    }

    func setEnabled(_ id: String, _ enabled: Bool) {
        guard var r = routine(id: id) else { return }
        r.enabled = enabled
        update(r)
    }

    func delete(_ id: String) {
        routines.removeAll { $0.id == id }
        save()
    }

    var checkedGoalIDs: Set<String> { Set(routines.compactMap { $0.enabled ? $0.goalId : nil }) }

    /// Routines that belong to a goal.
    func forGoal(_ goalId: String) -> [NanoMuseRoutine] { routines.filter { $0.goalId == goalId } }

    // MARK: Lifecycle hooks (MinisApp)

    /// Call from the app's init: BGTaskScheduler wants the handler before launch finishes.
    nonisolated static func registerBackgroundTask() {
        BGTaskScheduler.shared.register(forTaskWithIdentifier: Self.backgroundTaskId, using: nil) { task in
            guard let refresh = task as? BGAppRefreshTask else { task.setTaskCompleted(success: false); return }
            Task { @MainActor in
                NanoMuseScheduler.shared.handleBackgroundRefresh(refresh)
            }
        }
    }

    /// The app is on screen: run what is due, and keep checking every minute while it stays up.
    func appBecameActive() {
        catchUp(reason: "active")
        tickTimer?.invalidate()
        tickTimer = Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.catchUp(reason: "tick") }
        }
        BGTaskScheduler.shared.cancel(taskRequestWithIdentifier: Self.backgroundTaskId)
    }

    /// The app is leaving the screen: ask for a refresh around the next due time, and make sure the reminders are set.
    func appWentBackground() {
        tickTimer?.invalidate()
        tickTimer = nil
        scheduleBackgroundRefresh()
        refreshNotifications()
    }

    /// The next due moment across all routines.
    func nextDue(after: Date = Date()) -> (routine: NanoMuseRoutine, at: Date)? {
        routines.compactMap { r in r.nextDue(after: after).map { (r, $0) } }.min { $0.1 < $1.1 }
    }

    func scheduleBackgroundRefresh() {
        guard let next = nextDue() else { return }
        let request = BGAppRefreshTaskRequest(identifier: Self.backgroundTaskId)
        request.earliestBeginDate = max(next.at, Date().addingTimeInterval(15 * 60))
        try? BGTaskScheduler.shared.submit(request)
    }

    /// iOS woke us for a moment: there is no time for a model turn, so the
    /// routines that came due get a notification each, and the next refresh is asked for.
    private func handleBackgroundRefresh(_ task: BGAppRefreshTask) {
        task.expirationHandler = { }
        let now = Date()
        for r in routines where r.isDue(at: now) && r.id != NanoMuseFeedFlow.routineId {
            postDueNotification(r, at: now)
        }
        scheduleBackgroundRefresh()
        task.setTaskCompleted(success: true)
    }

    // MARK: Running

    /// Run every routine that is due, one after the other.
    func catchUp(reason: String) {
        guard catchUpTask == nil else { return }
        let now = Date()
        let due = routines.filter { $0.isDue(at: now) && !running.contains($0.id) }
        guard !due.isEmpty else { return }
        let task = Task { @MainActor [self] in
            for r in due {
                if Task.isCancelled { break }
                _ = await run(r.id, trigger: reason)
            }
        }
        catchUpTask = task
        Task { @MainActor [self] in
            await task.value
            if catchUpTask == task { catchUpTask = nil }
        }
    }

    /// Run one routine now (from the UI or the catch-up). Returns whether the turn finished without an error.
    @discardableResult
    func run(_ id: String, trigger: String = "manual") async -> Bool {
        guard var r = routine(id: id), !running.contains(id) else { return false }
        running.insert(id)
        defer { running.remove(id) }
        // Mark the slot as taken first, so a crash mid-run does not re-run it on the next open.
        let startedAt = Date()
        r.lastFiredAt = startedAt
        update(r)

        let outcome: NanoMuseHeadless.Outcome
        if r.id == NanoMuseFeedFlow.routineId {
            outcome = await NanoMuseFeedWriter.run(r, manual: trigger == "manual" || trigger == "feed-now")
        } else {
            outcome = await NanoMuseHeadless.run(prompt: prompt(for: r), sessionId: r.sessionId, title: r.label,
                                                source: "nanomuse-routine", routine: r.label, run: runKind(r))
        }
        guard var fresh = routine(id: id) else { return outcome.ok }
        if fresh.sessionId == nil, let sid = outcome.sessionId { fresh.sessionId = sid }
        fresh.runs.insert(NanoMuseRoutine.Run(at: startedAt, ok: outcome.ok, note: outcome.note), at: 0)
        if fresh.runs.count > Self.maxRunsKept { fresh.runs = Array(fresh.runs.prefix(Self.maxRunsKept)) }
        if fresh.repeatMode == .once, fresh.intervalHours == nil { fresh.enabled = false }
        update(fresh)
        NanoMuseRoutineEvents.finished.send((fresh, outcome))
        return outcome.ok
    }

    private func prompt(for r: NanoMuseRoutine) -> String {
        if let goalId = r.goalId, let goal = NanoMuseGoalStore.shared.goal(id: goalId) {
            return NanoMuseGoalFlow.checkPrompt(goal)
        }
        return r.prompt
    }

    // MARK: Notifications

    /// One pending calendar notification per enabled routine, at its next time: "open to run it".
    func refreshNotifications() {
        notificationsTask?.cancel()
        notificationsTask = Task { [weak self] in
            let center = UNUserNotificationCenter.current()
            let pending = await center.pendingNotificationRequests()
            guard !Task.isCancelled, let self else { return }
            let ours = pending.filter { $0.identifier.hasPrefix("nanomuse-routine-") }.map(\.identifier)
            center.removePendingNotificationRequests(withIdentifiers: ours)
            let now = Date()
            // iOS keeps 64 pending requests per app; the soonest routines get the slots.
            let soon = self.routines
                .filter { $0.id != NanoMuseFeedFlow.routineId }
                .compactMap { r in r.enabled ? r.nextDue(after: now).map { (r, $0) } : nil }
                .filter { $0.1 > now.addingTimeInterval(30) }
                .sorted { $0.1 < $1.1 }
                .prefix(20)
            for (r, at) in soon {
                let content = self.notificationContent(for: r)
                let components = Calendar.current.dateComponents([.year, .month, .day, .hour, .minute], from: at)
                let trigger = UNCalendarNotificationTrigger(dateMatching: components, repeats: false)
                try? await center.add(UNNotificationRequest(identifier: "nanomuse-routine-\(r.id)", content: content, trigger: trigger))
            }
        }
    }

    private func postDueNotification(_ r: NanoMuseRoutine, at now: Date) {
        let content = notificationContent(for: r)
        let request = UNNotificationRequest(identifier: "nanomuse-due-\(r.id)-\(Int(now.timeIntervalSince1970))", content: content, trigger: nil)
        UNUserNotificationCenter.current().add(request) { _ in }
    }

    private func notificationContent(for r: NanoMuseRoutine) -> UNMutableNotificationContent {
        let content = UNMutableNotificationContent()
        if let goalId = r.goalId, let goal = NanoMuseGoalStore.shared.goal(id: goalId) {
            content.title = String(format: AppLocalized("Check-in: %@"), goal.title)
        } else {
            content.title = r.label.isEmpty ? AppLocalized("Routine") : r.label
        }
        content.body = AppLocalized("Open nanoMuse to run it. The phone cannot run the agent while the app is asleep.")
        content.sound = .default
        content.categoryIdentifier = Self.notificationCategory
        var info: [String: Any] = ["nanomuse.routine": r.id]
        if let sid = r.sessionId { info["sessionId"] = sid }
        content.userInfo = info
        return content
    }

    /// Who a routine's turn is for the relay's record (NanoMuseProvenance): the feed's, a goal's, or a schedule's.
    func runKind(_ r: NanoMuseRoutine) -> String {
        if r.goalId != nil { return NanoMuseProvenance.runGoal }
        if r.id == NanoMuseFeedFlow.routineId || (r.sessionId.map { NanoMuseFeedFlow.isFeedSession($0) } ?? false) { return NanoMuseProvenance.runFeed }
        return NanoMuseProvenance.runSchedule
    }

    /// Ask once; iOS keeps the answer.
    func requestNotificationPermission() {
        Task {
            let center = UNUserNotificationCenter.current()
            let settings = await center.notificationSettings()
            defer { NanoMuseDeadlineNotifications.shared.refresh() }
            guard settings.authorizationStatus == .notDetermined else { return }
            _ = try? await center.requestAuthorization(options: [.alert, .sound, .badge])
        }
    }
}

// MARK: - Events

enum NanoMuseRoutineEvents {
    /// A routine finished; the feed and the goals listen.
    static let finished = NanoMuseSignal<(NanoMuseRoutine, NanoMuseHeadless.Outcome)>()
}

/// A tiny broadcaster: observers by id, no Combine.
final class NanoMuseSignal<Value> {
    private var handlers: [UUID: (Value) -> Void] = [:]

    @discardableResult
    func observe(_ handler: @escaping (Value) -> Void) -> UUID {
        let id = UUID()
        handlers[id] = handler
        return id
    }

    func cancel(_ id: UUID) { handlers[id] = nil }

    func send(_ value: Value) { handlers.values.forEach { $0(value) } }
}

// MARK: - Headless runs

/// Runs one prompt in a session with the app's own chat pipeline and waits
/// for the turn to end — what the Shortcuts intents do (`QuickTaskIntent`).
enum NanoMuseHeadless {
    struct Outcome {
        var ok: Bool
        var sessionId: String?
        var text: String
        var note: String?
    }

    /// Creates the session when `sessionId` is nil or gone; the turn's last assistant text comes back.
    /// With `routine` (the routine's label) the turn is marked as the routine's, not the person's:
    /// its row is a quiet line in the chat and the model is told so for this one turn
    /// (`NanoMuseRoutineWakes`). `run` names who starts the turn for the relay's record
    /// (`schedule`, `feed`, `goal`, `hub`; NanoMuseProvenance); nil leaves it the person's.
    @MainActor
    static func run(prompt: String, sessionId: String?, title: String?, source: String, routine: String? = nil, run: String? = nil, timeout: TimeInterval = 10 * 60) async -> Outcome {
        guard ProviderConfigStore.shared.defaultPrimaryGroupId != nil || !ProviderConfigStore.shared.modelEntries.isEmpty else {
            return Outcome(ok: false, sessionId: sessionId, text: "", note: AppLocalized("Add a model first; routines are run by your agent."))
        }
        let vm: AIChatViewModel
        var sid = sessionId
        if let sid, await ChatStore.shared.sessionExists(id: sid) {
            let cached = ViewModelCache.shared.getOrCreate(for: sid)
            vm = cached.vm
            if cached.isNew { await vm.loadSession() }
        } else {
            vm = ViewModelCache.shared.createDraft()
            vm.sessionSource = source
            vm.suppressGeneralCompletionNotification = true
            let created = await vm.ensureSessionReturningId()
            if let title, !title.isEmpty {
                await ChatStore.shared.updateSessionTitle(created, title: String(title.prefix(60)))
            }
            ViewModelCache.shared.cacheDraft(vm, sessionId: created)
            sid = created
        }
        if vm.isProcessing {
            for await processing in vm.$isProcessing.values where !processing { break }
        }
        let wake = routine.map { NanoMuseRoutineWakes.Wake(label: String($0.trimmingCharacters(in: .whitespaces).prefix(60)), at: Date()) }
        if let wake, let session = sid {
            NanoMuseSessionAddenda.add(session: session, tag: NanoMuseRoutineWakes.addendumTag, text: NanoMuseRoutineWakes.framing(label: wake.label, at: wake.at), turns: 1)
        }
        // who starts this turn, for every model call it makes, until it ends (relay 0.31)
        if let run, let session = sid { NanoMuseProvenance.arm(session: session, run: run) }
        vm.inputText = prompt
        vm.send()
        // a send that did not start (the guard in `send`) leaves the next turn the person's
        if run != nil, !vm.isProcessing, let session = sid { NanoMuseProvenance.disarm(session: session) }
        // `send` appends the user row before it suspends: mark it now, so it is drawn as the
        // routine's line from its first frame and remembered under its row id once persisted.
        // A send that did not start (the guard in `send`) leaves no mark and no framing.
        if let wake, let session = sid {
            let trimmed = prompt.trimmingCharacters(in: .whitespacesAndNewlines)
            if vm.isProcessing, let row = vm.messages.last(where: { $0.role == .user }), row.nmRoutine == nil, row.content == trimmed {
                row.nmRoutine = wake
            } else if !vm.isProcessing {
                NanoMuseSessionAddenda.remove(session: session, tag: NanoMuseRoutineWakes.addendumTag)
            }
        }
        // Wait for the loop to end, with a ceiling.
        let deadline = Date().addingTimeInterval(timeout)
        var finished = !vm.isProcessing
        while !finished && Date() < deadline {
            try? await Task.sleep(nanoseconds: 500_000_000)
            finished = !vm.isProcessing
        }
        let text = SendPromptIntent.extractResponseText(from: vm)
        let failed = vm.errorMessage != nil || vm.messages.last?.error != nil || !finished
        return Outcome(ok: !failed, sessionId: sid ?? vm.sessionId, text: text, note: failed ? (vm.errorMessage ?? (finished ? nil : AppLocalized("Took too long"))) : nil)
    }
}
