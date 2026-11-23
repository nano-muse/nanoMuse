import CryptoKit
import EventKit
import Foundation
import SwiftUI

/// EventKit objects stay on this actor; only selected calendars' timing metadata leaves it.
actor NanoMuseCalendarReader {
    static let shared = NanoMuseCalendarReader()
    private lazy var store = EKEventStore()

    nonisolated static var readable: Bool {
        let status = EKEventStore.authorizationStatus(for: .event)
        if #available(iOS 17, *) { return status == .fullAccess }
        return status == .authorized
    }

    nonisolated private static func hash(_ input: String) -> String {
        SHA256.hash(data: Data(input.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    struct Choice: Identifiable, Sendable {
        let id: String
        let name: String
    }

    func choices(request: Bool) async -> [Choice] {
        if request && !Self.readable {
            if #available(iOS 17, *) { _ = try? await store.requestFullAccessToEvents() }
            else { _ = try? await store.requestAccess(to: .event) }
        }
        guard Self.readable else { return [] }
        return store.calendars(for: .event).map { Choice(id: Self.hash($0.calendarIdentifier), name: $0.title) }
            .sorted { $0.name.localizedStandardCompare($1.name) == .orderedAscending }
    }

    func snapshot(_ selected: Set<String>, at now: Date) -> NanoMuseCalendarChanges.Snapshot? {
        guard !Task.isCancelled, Self.readable, !selected.isEmpty else { return nil }
        let calendars = store.calendars(for: .event).filter { selected.contains(Self.hash($0.calendarIdentifier)) }
        // Partial reads while a source is offline cannot establish a new baseline.
        guard calendars.count == selected.count else { return nil }
        let end = now.addingTimeInterval(48 * 3600)
        let query = store.predicateForEvents(withStart: now, end: end, calendars: calendars)
        let events = store.events(matching: query)
        var slots: [NanoMuseCalendarChanges.Slot] = []
        var keys = Set<String>()
        for event in events {
            guard !Task.isCancelled else { return nil }
            guard !event.isAllDay, event.status != .canceled, event.status != .tentative,
                  event.availability == .busy || event.availability == .unavailable,
                  let start = event.startDate, let stop = event.endDate, stop > start, stop > now,
                  let id = event.eventIdentifier, let calendar = event.calendar else { continue }
            var identity = calendar.calendarIdentifier + "/" + id
            if event.hasRecurrenceRules || event.isDetached {
                guard let anchor = event.occurrenceDate else { continue }
                identity += "/" + String(anchor.timeIntervalSince1970)
            }
            let key = Self.hash(identity)
            guard keys.insert(key).inserted, slots.count < 256 else { return nil }
            slots.append(.init(key: key, start: start, end: stop))
        }
        return Self.readable ? .init(read: now, through: end, slots: slots) : nil
    }
}

enum NanoMuseCalendarWatch {
    static let selection = "nanomuse.feed.calendarSelection"
    static let baseline = "nanomuse.feed.calendarSnapshot"

    static var selected: Set<String> { Set(UserDefaults.standard.stringArray(forKey: selection) ?? []) }

    static func compare(_ snapshot: NanoMuseCalendarChanges.Snapshot) -> NanoMuseOutreachJournal.Candidate? {
        let previous = UserDefaults.standard.data(forKey: baseline).flatMap { try? JSONDecoder().decode(NanoMuseCalendarChanges.Snapshot.self, from: $0) }
        guard let change = NanoMuseCalendarChanges.next(previous: previous, current: snapshot) else { return nil }
        let format = DateIntervalFormatter()
        format.dateStyle = .short
        format.timeStyle = .short
        let slots = change.slots
        let a = format.string(from: slots[0].start, to: slots[0].end)
        let b = format.string(from: slots[1].start, to: slots[1].end)
        let template: String
        let kind: String
        switch change {
        case .moved:
            template = AppLocalized("Calendar shows a time change from %1$@ to %2$@. Shall we review what else needs to move?")
            kind = "move"
        case .conflict:
            template = AppLocalized("Calendar shows a new overlap between %1$@ and %2$@. Would you like help adjusting your plans?")
            kind = "conflict"
        }
        let signature = [kind] + slots.map { "\($0.key)/\($0.start.timeIntervalSince1970)/\($0.end.timeIntervalSince1970)" }
        let receipt = SHA256.hash(data: Data(signature.joined(separator: "|").utf8)).map { String(format: "%02x", $0) }.joined()
        return .init(text: String(format: template, a, b), goalID: nil, calendarReceipt: receipt)
    }

    static func save(_ snapshot: NanoMuseCalendarChanges.Snapshot) {
        if let data = try? JSONEncoder().encode(snapshot) { UserDefaults.standard.set(data, forKey: baseline) }
    }
}

struct NanoMuseCalendarWatchSettings: View {
    @Environment(\.openURL) private var openURL
    @State private var calendars: [NanoMuseCalendarReader.Choice] = []
    @State private var selected = NanoMuseCalendarWatch.selected
    @State private var checkedPermission = false
    @State private var displayedOwner: String?
    @State private var allowed = NanoMuseCalendarReader.readable
    @State private var loadID: UUID?

    var body: some View {
        Form {
            Section {
                if allowed {
                    ForEach(calendars) { choice in
                        Toggle(choice.name, isOn: Binding(get: { selected.contains(choice.id) }, set: { on in
                            guard let owner = displayedOwner else { return }
                            if on { selected.insert(choice.id) } else { selected.remove(choice.id) }
                            NanoMuseChatOutreach.shared.setCalendars(selected, owner: owner)
                        })).tint(NanoMuseTones.action)
                    }
                    if calendars.isEmpty && loadID == nil { Text(AppLocalized("No calendars available.")) }
                } else if checkedPermission {
                    Button(AppLocalized("Open Settings")) {
                        if let url = URL(string: UIApplication.openSettingsURLString) { openURL(url) }
                    }
                } else {
                    Button(AppLocalized("Choose calendars")) { Task { await load(request: true) } }.disabled(loadID != nil)
                }
                if !selected.isEmpty {
                    Button(AppLocalized("Stop watching calendars")) {
                        guard let owner = displayedOwner else { return }
                        selected = []
                        NanoMuseChatOutreach.shared.setCalendars([], owner: owner)
                    }
                }
            } footer: {
                Text(AppLocalized("Choose which calendars nanoMuse can check on this iPhone. It compares busy times locally and can message your main chat about a new overlap or a time change."))
            }
        }
        .navigationTitle(AppLocalized("Calendar changes in chat"))
        .task { await load(request: false) }
        .onReceive(NotificationCenter.default.publisher(for: .nanoMuseAccountSwitched)) { _ in
            displayedOwner = nil
            selected = []
            Task { await load(request: false) }
        }
        .onReceive(NotificationCenter.default.publisher(for: UIApplication.willEnterForegroundNotification)) { _ in Task { await load(request: false) } }
    }

    @MainActor private func load(request: Bool) async {
        let id = UUID()
        loadID = id
        defer { if loadID == id { loadID = nil } }
        let account = NanoMuseAccountData.shared.current
        let choices = await NanoMuseCalendarReader.shared.choices(request: request)
        guard !Task.isCancelled, loadID == id, account == NanoMuseAccountData.shared.current else { return }
        displayedOwner = account
        calendars = choices
        allowed = NanoMuseCalendarReader.readable
        selected = NanoMuseCalendarWatch.selected
        checkedPermission = !allowed && EKEventStore.authorizationStatus(for: .event) != .notDetermined
    }
}
