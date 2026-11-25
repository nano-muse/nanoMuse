//
//  NanoMuseGoals.swift
//  nanoMuse
//
//  Goals, Muse style: shaped in the chat (three short questions), handed
//  over by the model as a ```nanomuse-goal``` block, turned into a goal
//  with its own conversation and a hidden check-in routine; every check
//  ends with a ```nanomuse-goal-update``` block that flows back here.
//  Android: io.github.nanomuse.goals.*.
//

import Foundation
import SwiftUI

// MARK: - Model

enum NanoMuseGoalCategory: String, Codable, CaseIterable, Identifiable {
    case health, relationships, finance, career, interests, productivity, other
    var id: String { rawValue }

    static func from(_ key: String?) -> NanoMuseGoalCategory {
        NanoMuseGoalCategory(rawValue: (key ?? "").lowercased()) ?? .other
    }

    var label: String {
        switch self {
        case .health: return AppLocalized("Health")
        case .relationships: return AppLocalized("Relationships")
        case .finance: return AppLocalized("Finance")
        case .career: return AppLocalized("Career")
        case .interests: return AppLocalized("Interests")
        case .productivity: return AppLocalized("Productivity")
        case .other: return AppLocalized("Other")
        }
    }

    var symbol: String {
        switch self {
        case .health: return "heart"
        case .relationships: return "person.2"
        case .finance: return "banknote"
        case .career: return "briefcase"
        case .interests: return "paintpalette"
        case .productivity: return "checkmark.circle"
        case .other: return "flag"
        }
    }
}

enum NanoMuseGoalStatus: String, Codable { case active, paused, done }

struct NanoMuseGoalStep: Codable, Equatable, Identifiable {
    var id: String = UUID().uuidString
    var text: String
    var done: Bool = false
}

struct NanoMuseGoal: Codable, Identifiable, Equatable {
    var id: String = UUID().uuidString
    var title: String
    var why: String = ""
    var category: NanoMuseGoalCategory = .other
    /// 0 = a daily check at `checkHour:checkMinute`; otherwise every N hours.
    var checkEveryHours: Int = 0
    var checkHour: Int = 9
    var checkMinute: Int = 0
    var steps: [NanoMuseGoalStep] = []
    var progress: Int = 0
    var status: NanoMuseGoalStatus = .active
    var sessionId: String? = nil
    var routineId: String? = nil
    /// Local calendar dates travel with the account's goal file, including its Feed choices.
    var due: String? = nil
    var sourceSessionId: String? = nil
    var scheduledChecks: Bool? = nil
    var hasScheduledChecks: Bool { scheduledChecks ?? true }
    var dismissedDeadline: String? = nil
    var deadlineSnoozedUntil: String? = nil
    var lastNote: String? = nil
    var lastCheckedAt: Date? = nil
    var createdAt: Date = Date()
    var updatedAt: Date = Date()

    /// "Checks every 2 hours" / "Checks daily at 08:00".
    var cadence: String {
        if checkEveryHours > 0 {
            return checkEveryHours == 1 ? AppLocalized("Checks every hour") : String(format: AppLocalized("Checks every %d hours"), checkEveryHours)
        }
        return String(format: AppLocalized("Checks daily at %@"), NanoMuseDay.clock(hour: checkHour, minute: checkMinute))
    }

    // MARK: From the model's block (pure, tested)

    /// A goal from a `nanomuse-goal` block; nil when there is no usable title.
    static func from(block o: [String: Any]) -> (goal: NanoMuseGoal, firstCheck: String)? {
        let title = (o["title"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        guard !title.isEmpty else { return nil }
        let everyRaw = (o["check_every_hours"] as? NSNumber)?.intValue ?? Int(o["check_every_hours"] as? String ?? "") ?? 0
        let every = min(max(everyRaw, 0), 24 * 7)
        let time = NanoMuseDay.parseClock(o["check_time"] as? String) ?? parseLooseTime(o["check_time"] as? String) ?? (9, 0)
        let steps = ((o["steps"] as? [Any]) ?? []).compactMap { ($0 as? String)?.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .prefix(6)
            .map { NanoMuseGoalStep(text: $0) }
        var goal = NanoMuseGoal(title: String(title.prefix(60)))
        goal.why = (o["why"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        goal.category = .from(o["category"] as? String)
        goal.scheduledChecks = o["scheduled_checks"] as? Bool
        goal.checkEveryHours = every
        goal.checkHour = time.hour
        goal.checkMinute = time.minute
        goal.steps = Array(steps)
        goal.changeDue(to: o["due"] as? String)
        let first = (o["first_check"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return (goal, first)
    }

    /// "9:00", "at 18:30" → the time inside.
    private static func parseLooseTime(_ s: String?) -> (hour: Int, minute: Int)? {
        guard let s, let regex = try? NSRegularExpression(pattern: "(\\d{1,2}):(\\d{2})") else { return nil }
        let ns = s as NSString
        guard let m = regex.firstMatch(in: s, range: NSRange(location: 0, length: ns.length)),
              let h = Int(ns.substring(with: m.range(at: 1))), let min = Int(ns.substring(with: m.range(at: 2))) else { return nil }
        return (Swift.min(Swift.max(h, 0), 23), Swift.min(Swift.max(min, 0), 59))
    }

    /// What a `nanomuse-goal-update` block changes.
    struct Update: Equatable {
        var goalId: String?
        var progress: Int?
        var status: NanoMuseGoalStatus?
        var note: String?

        init?(block o: [String: Any]) {
            goalId = (o["goal_id"] as? String).flatMap { $0.isEmpty ? nil : $0 }
            if let n = o["progress"] as? NSNumber { progress = min(max(n.intValue, 0), 100) }
            else if let s = o["progress"] as? String, let n = Int(s) { progress = min(max(n, 0), 100) }
            switch (o["status"] as? String ?? "").lowercased() {
            case "on_track", "active": status = .active
            case "attention": status = .active
            case "done": status = .done
            case "paused": status = .paused
            default: status = nil
            }
            note = (o["note"] as? String).flatMap { $0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : $0 }
            if goalId == nil && progress == nil && status == nil && note == nil { return nil }
        }
    }
}

// MARK: - Store

@MainActor
final class NanoMuseGoalStore: ObservableObject {
    static let shared = NanoMuseGoalStore()

    @Published private(set) var goals: [NanoMuseGoal] = []

    private var file: URL { NanoMuseDirs.root.appendingPathComponent("goals.json") }

    private init() { load() }

    private func load() {
        guard let data = try? Data(contentsOf: file) else { return }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        goals = (try? decoder.decode([NanoMuseGoal].self, from: data)) ?? []
    }

    /// C12: the file changed under the store — another account's goals are in place (or none).
    func reload() {
        goals = []
        load()
    }

    private func save() {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        if let data = try? encoder.encode(goals) { try? data.write(to: file, options: .atomic) }
    }

    func goal(id: String) -> NanoMuseGoal? { goals.first { $0.id == id } }
    func forSession(_ sessionId: String) -> NanoMuseGoal? { goals.first { $0.sessionId == sessionId } }

    var tracking: [NanoMuseGoal] { goals.filter { $0.status != .done }.sorted { $0.createdAt > $1.createdAt } }
    var finished: [NanoMuseGoal] { goals.filter { $0.status == .done }.sorted { $0.updatedAt > $1.updatedAt } }

    func upsert(_ goal: NanoMuseGoal) {
        var g = goal
        g.updatedAt = Date()
        if let i = goals.firstIndex(where: { $0.id == goal.id }) { goals[i] = g } else { goals.append(g) }
        save()
    }

    func setDue(_ due: String?, for id: String) {
        guard var goal = goal(id: id), goal.due != due else { return }
        goal.changeDue(to: due)
        upsert(goal)
    }

    func respond(to card: NanoMuseGoalDeadline, with response: NanoMuseGoalDeadline.Response) {
        let locks = SessionLockStore.shared
        guard !locks.appIsLocked, var goal = goal(id: card.goal.id),
              !goal.usesProtectedSession(in: locks.lockedSessionIds),
              goal.respond(to: card, with: response) else { return }
        upsert(goal)
    }

    func delete(_ id: String) {
        goals.removeAll { $0.id == id }
        save()
    }

    func applyUpdate(_ update: NanoMuseGoal.Update, fallbackGoalId: String?) {
        guard let id = update.goalId ?? fallbackGoalId, var g = goal(id: id) else { return }
        if let p = update.progress { g.progress = p }
        let wasDone = g.status == .done
        if let s = update.status {
            g.status = s
            if s == .done { g.progress = 100 }
        }
        if let n = update.note { g.lastNote = n }
        g.lastCheckedAt = Date()
        upsert(g)
        if g.status == .done, let rid = g.routineId { NanoMuseScheduler.shared.setEnabled(rid, false) }
        if g.status == .done, !wasDone { NanoMuseStar.shared.goalDone() } // C1
    }
}

// MARK: - Flow

enum NanoMuseGoalFlow {
    static let addendumTag = "nanomuse-goal-create"
    static let blockGoal = "goal"
    static let blockUpdate = "goal-update"

    /// "I'd like to create a Health goal." — the message sent on the person's behalf; the steering goes into the addendum.
    @MainActor
    static func startCreation(session: String, category: NanoMuseGoalCategory) -> String {
        NanoMuseSessionAddenda.add(session: session, tag: addendumTag, text: creationAddendum(category), turns: 8)
        return String(format: AppLocalized("I'd like to create a %@ goal."), category.label)
    }

    static func creationAddendum(_ category: NanoMuseGoalCategory) -> String {
        """
        ## Creating a goal (nanoMuse)
        The user just chose to create a goal in the "\(category.rawValue)" category from the Goals tab.
        Shape it together: ask at most three short questions, ONE message at a time,
        in the user's language: (1) what exactly they want to achieve, (2) why it matters and by
        when, (3) how often you should check in (every N hours, or daily at a time). Two or three
        sentences per message; if the user already answered something, skip that question.
        When you have enough, reply with one warm sentence of confirmation and then EXACTLY ONE fenced
        code block tagged `nanomuse-goal` containing JSON with these keys:
        {"title": "<= 40 chars", "why": "one sentence", "category": "\(category.rawValue)",
         "due": "YYYY-MM-DD only if the user supplied a deadline, otherwise omit this key",
         "scheduled_checks": <false only if the user asks for no regular checks or deadline reminders only, otherwise true>,
         "check_every_hours": <integer, 0 means a daily check>, "check_time": "HH:MM" (used when check_every_hours is 0),
         "steps": ["3 to 5 short steps you will take or track"], "first_check": "what you will do at the first check"}
        Today's local date is \(NanoMuseGoalDeadline.key(Date())). Preserve the user's stated deadline as a local calendar date; leave due out if no definite date was agreed.
        Do not describe the block or mention JSON; the app renders it as a card. Say nothing after the block.
        Later, checks for this goal will happen in their own conversation when the app is open; on the iPhone the app cannot run while it is asleep, so the person is reminded to open it.
        """
    }

    /// After every finished turn: goal blocks become goals, update blocks update them.
    @MainActor
    static func afterTurn(session: String, assistantText: String?) {
        guard let text = assistantText, !text.isEmpty else { return }
        let store = NanoMuseGoalStore.shared
        if NanoMuseFences.contains(text, kind: blockGoal), let o = NanoMuseFences.lastObject(blockGoal, in: text) {
            if NanoMuseSessionAddenda.has(session: session, tag: addendumTag) || !alreadyCreated(from: o) {
                if let made = NanoMuseGoal.from(block: o) {
                    var goal = made.goal
                    goal.sourceSessionId = session
                    store.upsert(goal)
                    let first = made.firstCheck
                    Task { @MainActor [goal] in await setUp(goal, firstCheck: first) }
                }
            }
            NanoMuseSessionAddenda.remove(session: session, tag: addendumTag)
        }
        if NanoMuseFences.contains(text, kind: blockUpdate) {
            for o in NanoMuseFences.objects(blockUpdate, in: text) {
                guard let update = NanoMuseGoal.Update(block: o) else { continue }
                store.applyUpdate(update, fallbackGoalId: store.forSession(session)?.id)
            }
        }
    }

    @MainActor
    private static func alreadyCreated(from o: [String: Any]) -> Bool {
        let title = String((o["title"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines).prefix(60))
        guard !title.isEmpty else { return true }
        return NanoMuseGoalStore.shared.goals.contains { $0.title == title }
    }

    /// The goal's own conversation and its hidden check-in routine.
    @MainActor
    static func setUp(_ goal: NanoMuseGoal, firstCheck: String) async {
        let store = NanoMuseGoalStore.shared
        guard var g = store.goal(id: goal.id) else { return }
        if g.sessionId == nil {
            let vm = ViewModelCache.shared.createDraft()
            vm.sessionSource = "nanomuse-goal"
            let sid = await vm.ensureSessionReturningId()
            await ChatStore.shared.updateSessionTitle(sid, title: String(g.title.prefix(60)))
            // A date or a step may have changed while the chat was being created.
            guard let current = store.goal(id: goal.id) else { return }
            g = current
            ViewModelCache.shared.cacheDraft(vm, sessionId: sid)
            if g.sessionId == nil { g.sessionId = sid }
        }
        if g.routineId == nil {
            var routine = NanoMuseRoutine(
                label: String(format: AppLocalized("Goal check: %@"), g.title),
                prompt: checkPrompt(g, firstCheck: firstCheck),
                hour: g.checkHour,
                minute: g.checkMinute
            )
            routine.hidden = true
            routine.enabled = g.status == .active && g.hasScheduledChecks
            routine.goalId = g.id
            routine.sessionId = g.sessionId
            routine.intervalHours = g.checkEveryHours > 0 ? g.checkEveryHours : nil
            NanoMuseScheduler.shared.create(routine)
            g.routineId = routine.id
        }
        store.upsert(g)
        if g.hasScheduledChecks { NanoMuseScheduler.shared.requestNotificationPermission() }
    }

    /// The one line each check sends into the goal's conversation.
    static func checkPrompt(_ goal: NanoMuseGoal, firstCheck: String? = nil) -> String {
        var s = String(format: AppLocalized("Time to check on this goal: %@"), goal.title)
        if let first = firstCheck?.trimmingCharacters(in: .whitespacesAndNewlines), !first.isEmpty, goal.lastCheckedAt == nil {
            s += "\n" + String(format: AppLocalized("First time round: %@"), first)
        }
        return s
    }

    /// The system-prompt addendum of a goal's conversation; nil for every other one.
    @MainActor
    static func systemAddendum(session: String) -> String? {
        guard let goal = NanoMuseGoalStore.shared.forSession(session) else { return nil }
        let cadence = goal.checkEveryHours > 0 ? "every \(goal.checkEveryHours) hour(s)" : "daily at \(NanoMuseDay.clock(hour: goal.checkHour, minute: goal.checkMinute))"
        let steps = goal.steps.isEmpty ? "(none yet)" : goal.steps.enumerated().map { "\($0.offset + 1). [\($0.element.done ? "x" : " ")] \($0.element.text)" }.joined(separator: "\n")
        var s = "## This conversation tracks a goal (nanoMuse)\n"
        s += "Goal: \(goal.title)\n"
        if !goal.why.isEmpty { s += "Why: \(goal.why)\n" }
        if let due = goal.due { s += "User's deadline (local date): \(due)\n" }
        s += "Steps:\n\(steps)\n"
        s += (goal.hasActiveChecks(in: NanoMuseScheduler.shared.checkedGoalIDs) ? "Checks run \(cadence)" : "Scheduled checks are off") + "; progress so far \(goal.progress)%" + (goal.lastNote.map { ", last note: \($0)" } ?? "") + ".\n\n"
        s += "When a message asks you to check on the goal: find out where it stands right now with your tools "
        s += "(shell, browser, MCP servers, memory) and take the next small step if it is safe and reversible. "
        s += "Never pay, send messages or delete anything without asking. Then write the user a short update in "
        s += "their language (at most six lines) and end with EXACTLY ONE fenced code block tagged `nanomuse-goal-update` "
        s += "containing {\"goal_id\": \"\(goal.id)\", \"progress\": <0-100>, \"status\": \"on_track|attention|done\", \"note\": \"one line\"}. "
        s += "In ordinary conversation here, answer normally and add that block only when the goal's progress actually changed."
        return s
    }

    @MainActor
    static func setScheduledChecks(_ goal: NanoMuseGoal, _ enabled: Bool) {
        guard var g = NanoMuseGoalStore.shared.goal(id: goal.id), g.status == .active else { return }
        let scheduler = NanoMuseScheduler.shared
        let existing = scheduler.forGoal(g.id)
        g.scheduledChecks = enabled
        if enabled && existing.isEmpty { g.routineId = nil }
        NanoMuseGoalStore.shared.upsert(g)
        if enabled && existing.isEmpty {
            Task { @MainActor [g] in await setUp(g, firstCheck: "") }
        } else {
            for routine in existing { scheduler.setEnabled(routine.id, enabled) }
            if enabled { scheduler.requestNotificationPermission() }
        }
    }

    @MainActor
    static func setPaused(_ goal: NanoMuseGoal, _ paused: Bool) {
        guard var g = NanoMuseGoalStore.shared.goal(id: goal.id) else { return }
        if paused { g.scheduledChecks = g.hasActiveChecks(in: NanoMuseScheduler.shared.checkedGoalIDs) }
        g.status = paused ? .paused : .active
        NanoMuseGoalStore.shared.upsert(g)
        if let rid = g.routineId { NanoMuseScheduler.shared.setEnabled(rid, !paused && g.hasScheduledChecks) }
    }

    @MainActor
    static func markDone(_ goal: NanoMuseGoal, _ done: Bool) {
        guard var g = NanoMuseGoalStore.shared.goal(id: goal.id) else { return }
        if done && g.status == .active { g.scheduledChecks = g.hasActiveChecks(in: NanoMuseScheduler.shared.checkedGoalIDs) }
        g.status = done ? .done : .active
        if done { g.progress = 100 }
        NanoMuseGoalStore.shared.upsert(g)
        if let rid = g.routineId { NanoMuseScheduler.shared.setEnabled(rid, !done && g.hasScheduledChecks) }
        if done, goal.status != .done { NanoMuseStar.shared.goalDone() } // C1: a goal reached is a moment to ask for a star
    }

    /// The goal and its check go; its conversation stays (it is the person's history).
    @MainActor
    static func delete(_ goal: NanoMuseGoal) {
        if let rid = goal.routineId { NanoMuseScheduler.shared.delete(rid) }
        NanoMuseGoalStore.shared.delete(goal.id)
    }

    @MainActor
    static func checkNow(_ goal: NanoMuseGoal) {
        guard let rid = goal.routineId else { return }
        Task { @MainActor in await NanoMuseScheduler.shared.run(rid, trigger: "manual") }
    }

    /// "Checks every 2 hours · next 09:51"
    @MainActor
    static func cadenceLabel(_ goal: NanoMuseGoal) -> String {
        let base = goal.cadence
        guard let rid = goal.routineId, let routine = NanoMuseScheduler.shared.routine(id: rid), let next = routine.nextDue(after: Date()) else { return base }
        if next <= Date() { return String(format: AppLocalized("%@ · due now, runs when the app is open"), base) }
        let when = Calendar.current.isDateInToday(next)
            ? next.formatted(date: .omitted, time: .shortened)
            : next.formatted(date: .abbreviated, time: .shortened)
        return String(format: AppLocalized("%@ · next %@"), base, when)
    }
}

// MARK: - Goals room

struct NanoMuseGoalsRoom: View {
    var chrome: NanoMuseRoomChrome
    var onStartGoal: (NanoMuseGoalCategory) -> Void
    var onOpenSession: (String) -> Void

    @ObservedObject private var store = NanoMuseGoalStore.shared
    @ObservedObject private var scheduler = NanoMuseScheduler.shared
    @State private var pickedCategory: NanoMuseGoalCategory?
    @State private var deleting: NanoMuseGoal?
    @State private var editingRoutine: NanoMuseRoutine?
    @State private var editingDeadline: NanoMuseGoal?

    var body: some View {
        VStack(spacing: 0) {
            // Android: the Goals room's ••• menu — all routines, then the shared rows.
            NanoMuseRoomHeader(chrome: chrome) {
                NanoMuseRoomMenu(chrome: chrome) {
                    Button { chrome.open("routines") } label: { Label(AppLocalized("All routines"), systemImage: "clock") }
                }
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    trackingSection
                    routinesSection
                    createSection
                }
                .padding(16)
            }
        }
        // The chat's canvas (white, black in dark), as Android's GoalsTab and docs/design.md; the
        // grey page is the Feed's alone. The cards keep a hairline so they read on it.
        .background(ChatColors.background.ignoresSafeArea())
        .sheet(item: $pickedCategory) { category in
            NanoMuseGoalCategorySheet(category: category) {
                pickedCategory = nil
                onStartGoal(category)
            }
            .presentationDetents([.medium])
        }
        .sheet(item: $editingDeadline) { goal in
            NanoMuseDeadlineEditor(goal: goal)
                .presentationDetents([.medium])
        }
        .sheet(item: $editingRoutine) { routine in
            NanoMuseRoutineEditor(routine: routine)
        }
        .confirmationDialog(AppLocalized("Delete this goal? Its conversation stays in your chats."), isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } }), titleVisibility: .visible) {
            Button(AppLocalized("Delete goal"), role: .destructive) {
                if let g = deleting { NanoMuseGoalFlow.delete(g) }
                deleting = nil
            }
            Button(AppLocalized("Cancel"), role: .cancel) { deleting = nil }
        }
    }

    // MARK: Tracking

    private var trackingSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Circle().fill(Color.green).frame(width: 8, height: 8)
                Text(AppLocalized("Tracking")).font(.headline)
                Spacer()
                Button { pickedCategory = .other } label: { Image(systemName: "plus").font(.body.weight(.semibold)) }
                    .buttonStyle(.plain)
                    .accessibilityLabel(Text(AppLocalized("Create a goal")))
            }
            if store.tracking.isEmpty && store.finished.isEmpty {
                card { Text(AppLocalized("Nothing tracked yet")).font(.subheadline).foregroundStyle(.secondary) }
            } else {
                card {
                    VStack(spacing: 0) {
                        ForEach(store.tracking) { goal in
                            goalRow(goal)
                            if goal.id != store.tracking.last?.id || !store.finished.isEmpty { Divider().padding(.leading, 44) }
                        }
                        ForEach(store.finished) { goal in
                            goalRow(goal)
                            if goal.id != store.finished.last?.id { Divider().padding(.leading, 44) }
                        }
                    }
                }
            }
        }
    }

    private func goalRow(_ goal: NanoMuseGoal) -> some View {
        HStack(alignment: .top, spacing: 12) {
            Button {
                NanoMuseGoalFlow.markDone(goal, goal.status != .done)
            } label: {
                Image(systemName: goal.status == .done ? "checkmark.circle.fill" : "circle")
                    .font(.system(size: 22))
                    .foregroundStyle(goal.status == .done ? Color.green : Color.secondary)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(Text(goal.status == .done ? AppLocalized("Done") : AppLocalized("Mark as done")))
            VStack(alignment: .leading, spacing: 3) {
                Text(goal.title)
                    .font(.body.weight(.semibold))
                    .strikethrough(goal.status == .done)
                    .foregroundStyle(goal.status == .done ? .secondary : .primary)
                if let due = NanoMuseGoalDeadline.date(goal.due) {
                    Text(String(format: AppLocalized("Due %@"), due.formatted(date: .abbreviated, time: .omitted)))
                        .font(.footnote).foregroundStyle(.secondary)
                }
                if !goal.why.isEmpty {
                    Text(goal.why).font(.footnote).foregroundStyle(.secondary).lineLimit(2)
                }
                HStack(spacing: 6) {
                    Text(statusLine(goal)).font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Text("\(goal.progress)%").font(.caption.weight(.semibold)).foregroundStyle(NanoMuseTones.action)
                }
                ProgressView(value: Double(goal.progress) / 100).tint(NanoMuseTones.action)
                if let note = goal.lastNote, !note.isEmpty {
                    Text(note).font(.caption).foregroundStyle(.secondary).lineLimit(2)
                }
            }
            Menu {
                if let sid = goal.sessionId {
                    Button { onOpenSession(sid) } label: { Label(AppLocalized("Open conversation"), systemImage: "bubble.left") }
                }
                if goal.status == .active {
                    Toggle(AppLocalized("Scheduled check-ins"), isOn: Binding(
                        get: { goal.hasActiveChecks(in: scheduler.checkedGoalIDs) }, set: { NanoMuseGoalFlow.setScheduledChecks(goal, $0) }
                    ))
                }
                if goal.status != .done {
                    Button { editingDeadline = goal } label: { Label(AppLocalized("Due date"), systemImage: "calendar") }
                    Button { NanoMuseGoalFlow.checkNow(goal) } label: { Label(AppLocalized("Check now"), systemImage: "arrow.clockwise") }
                    Button { NanoMuseGoalFlow.setPaused(goal, goal.status != .paused) } label: {
                        Label(goal.status == .paused ? AppLocalized("Resume checks") : AppLocalized("Pause checks"), systemImage: goal.status == .paused ? "play" : "pause")
                    }
                }
                Button(role: .destructive) { deleting = goal } label: { Label(AppLocalized("Delete goal"), systemImage: "trash") }
            } label: {
                Image(systemName: "ellipsis")
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .frame(width: 28, height: 28)
                    .contentShape(Rectangle())
            }
            .accessibilityLabel(Text(AppLocalized("More")))
        }
        .padding(.vertical, 10)
        .contentShape(Rectangle())
        .onTapGesture { if let sid = goal.sessionId { onOpenSession(sid) } }
    }

    private func statusLine(_ goal: NanoMuseGoal) -> String {
        switch goal.status {
        case .paused: return AppLocalized("Paused")
        case .done: return AppLocalized("Done")
        case .active:
            if !goal.hasActiveChecks(in: scheduler.checkedGoalIDs) { return AppLocalized("Scheduled check-ins are off") }
            if goal.lastCheckedAt == nil, goal.routineId != nil { return AppLocalized("First check in about a minute") }
            return NanoMuseGoalFlow.cadenceLabel(goal)
        }
    }

    // MARK: Routines

    private var routinesSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(AppLocalized("Routines")).font(.headline)
                Spacer()
                Button { editingRoutine = NanoMuseRoutine(label: "", prompt: "", hour: 9, minute: 0) } label: { Image(systemName: "plus").font(.body.weight(.semibold)) }
                    .buttonStyle(.plain)
                    .accessibilityLabel(Text(AppLocalized("New routine")))
            }
            let visible = scheduler.visible
            if visible.isEmpty {
                card {
                    Text(AppLocalized("Nothing scheduled yet. A routine is something I do for you at a set time, every day or on weekdays. On the iPhone it runs when the app is open; at the set time the phone reminds you to open it."))
                        .font(.subheadline).foregroundStyle(.secondary)
                }
            } else {
                card {
                    VStack(spacing: 0) {
                        ForEach(visible) { routine in
                            routineRow(routine)
                            if routine.id != visible.last?.id { Divider().padding(.leading, 44) }
                        }
                    }
                }
            }
        }
    }

    private func routineRow(_ routine: NanoMuseRoutine) -> some View {
        HStack(spacing: 12) {
            Image(systemName: "clock")
                .font(.system(size: 20))
                .foregroundStyle(routine.enabled ? NanoMuseTones.action : Color.secondary)
                .frame(width: 24)
            VStack(alignment: .leading, spacing: 3) {
                Text(routine.label.isEmpty ? AppLocalized("Routine") : routine.label)
                    .font(.body.weight(.semibold))
                    .foregroundStyle(routine.enabled ? .primary : .secondary)
                Text(routine.enabled ? routine.cadence : AppLocalized("Off"))
                    .font(.caption).foregroundStyle(.secondary)
                if let last = routine.runs.first {
                    Text(String(format: last.ok ? AppLocalized("last run %@") : AppLocalized("last run %@, failed"), NanoMuseDay.relative(last.at)))
                        .font(.caption2).foregroundStyle(.tertiary)
                }
            }
            Spacer()
            if scheduler.running.contains(routine.id) {
                ProgressView()
            } else {
                Toggle("", isOn: Binding(get: { routine.enabled }, set: { scheduler.setEnabled(routine.id, $0) }))
                    .labelsHidden()
                    .tint(NanoMuseTones.action)
                    .accessibilityLabel(Text(routine.label.isEmpty ? AppLocalized("Routine") : routine.label))
            }
            Menu {
                Button { editingRoutine = routine } label: { Label(AppLocalized("Edit"), systemImage: "pencil") }
                Button { Task { @MainActor in await scheduler.run(routine.id) } } label: { Label(AppLocalized("Run now"), systemImage: "play") }
                if let sid = routine.sessionId {
                    Button { onOpenSession(sid) } label: { Label(AppLocalized("Open conversation"), systemImage: "bubble.left") }
                }
                Button(role: .destructive) { scheduler.delete(routine.id) } label: { Label(AppLocalized("Delete"), systemImage: "trash") }
            } label: {
                Image(systemName: "ellipsis")
                    .font(.body)
                    .foregroundStyle(.secondary)
                    .frame(width: 28, height: 28)
                    .contentShape(Rectangle())
            }
            .accessibilityLabel(Text(AppLocalized("More")))
        }
        .padding(.vertical, 10)
    }

    // MARK: Create

    private var createSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(AppLocalized("Create a goal")).font(.headline)
            Text(AppLocalized("Pick a category and tell me the goal you have in mind. I'll shape a plan with you and keep improving it as you go."))
                .font(.subheadline)
                .foregroundStyle(.secondary)
            card {
                VStack(spacing: 0) {
                    ForEach(NanoMuseGoalCategory.allCases) { category in
                        Button { pickedCategory = category } label: {
                            HStack(spacing: 12) {
                                Image(systemName: category.symbol)
                                    .font(.system(size: 18))
                                    .foregroundStyle(NanoMuseTones.action)
                                    .frame(width: 24)
                                Text(category.label).font(.body).foregroundStyle(.primary)
                                Spacer()
                                Image(systemName: "chevron.right").font(.footnote).foregroundStyle(.tertiary)
                            }
                            .padding(.vertical, 12)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        if category != NanoMuseGoalCategory.allCases.last { Divider().padding(.leading, 36) }
                    }
                }
            }
        }
    }

    private func card<Content: View>(@ViewBuilder _ content: () -> Content) -> some View {
        content()
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 14)
            .padding(.vertical, 4)
            .background(NanoMuseTones.surface, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(NanoMuseTones.hairline))
    }
}

/// "Create a Health goal" — what happens next, and the button that starts it.
struct NanoMuseGoalCategorySheet: View {
    var category: NanoMuseGoalCategory
    var onGo: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 12) {
                Image(systemName: category.symbol).font(.system(size: 28)).foregroundStyle(NanoMuseTones.action)
                Text(String(format: AppLocalized("Create a %@ goal"), category.label)).font(.title3.weight(.bold))
            }
            Text(AppLocalized("First, we'll shape the goal together in the chat. I'll ask a few questions so I understand exactly what you're after."))
                .font(.body)
            Text(AppLocalized("Once it's set, I'll track your progress here. The check-ins run when the app is open; at check time the phone reminds you to open it."))
                .font(.body).foregroundStyle(.secondary)
            Spacer(minLength: 8)
            Button(action: onGo) {
                Text(AppLocalized("Start"))
                    .font(.body.weight(.semibold))
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 12)
            }
            .buttonStyle(.borderedProminent)
            .tint(NanoMuseTones.action)
        }
        .padding(22)
    }
}

// MARK: - Routine editor

struct NanoMuseRoutineEditor: View {
    @State var routine: NanoMuseRoutine
    @Environment(\.dismiss) private var dismiss
    @State private var time: Date = Date()

    private var isNew: Bool { NanoMuseScheduler.shared.routine(id: routine.id) == nil }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField(AppLocalized("Name"), text: $routine.label)
                    DatePicker(AppLocalized("Time"), selection: $time, displayedComponents: .hourAndMinute)
                    Picker(AppLocalized("Repeat"), selection: $routine.repeatMode) {
                        Text(AppLocalized("Every day")).tag(NanoMuseRoutine.Repeat.daily)
                        Text(AppLocalized("Weekdays")).tag(NanoMuseRoutine.Repeat.weekdays)
                        Text(AppLocalized("Once")).tag(NanoMuseRoutine.Repeat.once)
                    }
                    Toggle(AppLocalized("On"), isOn: $routine.enabled).tint(NanoMuseTones.action)
                }
                Section {
                    TextEditor(text: $routine.prompt)
                        .frame(minHeight: 120)
                } header: {
                    Text(AppLocalized("What to do"))
                } footer: {
                    Text(AppLocalized("Sent to the agent as a message at the set time, in its own conversation. On the iPhone the run happens when the app is open; at the set time you get a reminder to open it. Nothing runs while the app is asleep."))
                }
                if !routine.runs.isEmpty {
                    Section(AppLocalized("Run records")) {
                        ForEach(Array(routine.runs.enumerated()), id: \.offset) { _, run in
                            HStack {
                                Image(systemName: run.ok ? "checkmark.circle" : "exclamationmark.circle")
                                    .foregroundStyle(run.ok ? Color.green : Color.orange)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(run.at.formatted(date: .abbreviated, time: .shortened)).font(.subheadline)
                                    if let note = run.note, !note.isEmpty { Text(note).font(.caption).foregroundStyle(.secondary) }
                                }
                            }
                        }
                    }
                }
            }
            .navigationTitle(isNew ? AppLocalized("New routine") : AppLocalized("Edit routine"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button(AppLocalized("Cancel")) { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button(AppLocalized("Save")) { save() }
                        .disabled(routine.prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
            .onAppear {
                var c = DateComponents()
                c.hour = routine.hour
                c.minute = routine.minute
                time = Calendar.current.date(from: c) ?? Date()
            }
        }
    }

    private func save() {
        let c = Calendar.current.dateComponents([.hour, .minute], from: time)
        var r = routine
        r.hour = c.hour ?? 9
        r.minute = c.minute ?? 0
        if r.label.trimmingCharacters(in: .whitespaces).isEmpty { r.label = String(r.prompt.prefix(40)) }
        if isNew { NanoMuseScheduler.shared.create(r) } else { NanoMuseScheduler.shared.update(r) }
        NanoMuseScheduler.shared.requestNotificationPermission()
        dismiss()
    }
}
