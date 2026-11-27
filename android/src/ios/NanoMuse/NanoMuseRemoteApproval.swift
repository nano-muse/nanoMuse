//
//  NanoMuseRemoteApproval.swift
//  nanoMuse
//
//  A task sent to another device of the account ("@Mac tidy the downloads") runs on that
//  device's Muse. When a step there needs a yes, the question comes back over the hub as an
//  `event {stage:"approval"}` and is answered where the task was typed (docs/hub.md,
//  docs/every-device.md); the answer goes back as `approve {approval_id, allow}`. Up to 1.0.3
//  the phone declined every such question. This is the card: the four answers of the Android
//  phone's own card (RiskGate), the "for this chat" grants in memory, the "always" grants on
//  this phone under the device's id, listed under Approvals on the agent's page with Revoke.
//  A payment gets neither. A question nobody answers in time is a no, as on Android; one the
//  person at the other device answered first (`approval_result`) leaves without an answer
//  from here.
//
//  The same card answers a computer's own question (a pushed `approval` event, docs/hub.md): a step of a
//  scheduled task there, asked here because nobody may be at that computer. Its answers are
//  Allow once, Always in this task (kept on the computer, not here) and Deny; the computer's
//  `approval_result` takes the card away once it was decided there or on another phone.
//

import Foundation
import SwiftUI

/// The fields of one `approval` event, read where the frame lands so the hub's dictionary
/// never crosses into the card's work.
struct NanoMuseRemoteQuestion: Sendable {
    /// The `approval_id`.
    let id: String
    let preview: String
    let risk: String
    let reason: String
    /// What a remembered answer covers. A legacy event without this complete structure can
    /// still be allowed once, but can never select or create a remembered answer.
    let grantTarget: NanoMuseApprovalGrantTarget?
    /// Seconds the other side waits before it takes silence as a no; 0 when it did not say.
    let timeout: Int

    init?(body: [String: Any]) {
        guard let id = body["approval_id"] as? String, !id.isEmpty else { return nil }
        self.id = id
        preview = ((body["preview"] as? String) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        risk = (body["risk"] as? String) ?? ""
        reason = ((body["reason"] as? String) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        grantTarget = NanoMuseApprovalGrantTarget(wire: body["grant_target"])
        timeout = (body["timeout"] as? Int) ?? (body["timeout"] as? Double).map { Int($0) } ?? 0
    }
}

/// A computer's pushed `approval` event: a step of one of its scheduled tasks.
struct NanoMuseScheduledQuestion: Sendable {
    let id: String
    let preview: String
    let reason: String
    let app: String
    let taskTitle: String
    /// The computer offers *Always in this task* (a hands step in one task).
    let canTask: Bool
    let timeout: Int

    init?(args: [String: Any]) {
        guard let id = args["approval_id"] as? String, !id.isEmpty else { return nil }
        self.id = id
        let chinese = Locale.preferredLanguages.first?.hasPrefix("zh") == true
        let zh = chinese ? ((args["preview_zh"] as? String) ?? "").trimmingCharacters(in: .whitespacesAndNewlines) : ""
        let en = ((args["preview"] as? String) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        reason = ((args["reason"] as? String) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        preview = zh.isEmpty ? (en.isEmpty ? reason : en) : zh
        app = ((args["app"] as? String) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        taskTitle = (((args["task"] as? [String: Any])?["title"] as? String) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        canTask = ((args["scopes"] as? [String]) ?? []).contains("schedule")
        let seconds = (args["timeout"] as? Int) ?? (args["timeout"] as? Double).map { Int($0) } ?? 0
        timeout = seconds > 0 ? min(max(seconds, 30), 600) : 180
    }
}

@MainActor
final class NanoMuseRemoteApprovals: ObservableObject {
    static let shared = NanoMuseRemoteApprovals()

    /// What the step does, from the `risk` word on the wire: the Android class names
    /// (destructive, outbound, money) and anything else, the runtime's levels included.
    enum Risk: String {
        case delete, send, pay, other

        init(wire: String) {
            switch wire.lowercased() {
            case "destructive", "delete": self = .delete
            case "outbound", "send", "network": self = .send
            case "money", "payment": self = .pay
            default: self = .other
            }
        }
    }

    /// The question as the other device's Muse put it.
    struct Request: Identifiable, Equatable {
        /// The `approval_id`.
        let id: String
        let deviceId: String
        let deviceName: String
        /// The chat the task was typed in; "for this chat" grants live under it.
        let sessionId: String
        let risk: Risk
        /// The exact wire class. Aliases never share a remembered capability.
        let wireRisk: String
        let preview: String
        let reason: String
        /// The sender's complete name for what an answer covers; nil from an older sender.
        let grantTarget: NanoMuseApprovalGrantTarget?
        /// Seconds the other side waits before it takes silence as a no.
        let timeout: Int
        /// For a computer's own question: the scheduled task asking, and the app it acts in.
        var schedule: Schedule? = nil

        struct Schedule: Equatable {
            let taskTitle: String
            let app: String
            let canTask: Bool
        }

        /// A payment is answered one at a time, as on Android; a scheduled task's step has its own answers.
        var canSession: Bool {
            nanoMuseCanRememberApproval(
                target: grantTarget, wireRisk: wireRisk, scheduled: schedule != nil
            )
        }
        var canAlways: Bool { canSession }
        /// The complete step identity. It is never reconstructed from display text.
        var target: String? { grantTarget.map { "task:\($0.identity)" } }
    }

    /// One standing answer: the same step on one device runs without a card.
    struct Grant: Codable, Identifiable, Equatable {
        var id: String { Self.key(deviceId: deviceId, risk: risk, target: target) }
        let deviceId: String
        let deviceName: String
        let risk: String
        let target: String
        let preview: String
        let grantedAt: Date

        static func key(deviceId: String, risk: String, target: String) -> String {
            [deviceId, risk, target].map { "\($0.utf8.count):\($0)" }.joined(separator: "|")
        }
    }

    enum Decision {
        case once, session, always, task, deny, timeout, elsewhere
    }

    /// What a computer's question ends with: the answer to send back, or none.
    enum ScheduledOutcome {
        /// `once`, `schedule` or `deny`.
        case answer(String)
        case expired
        case withdrawn
    }

    /// What `decide` hands back to the task: the answer to send, or nothing to send.
    enum Outcome {
        /// `standing` when a remembered answer decided, with no card.
        case allowed(standing: Bool)
        case denied
        case settledElsewhere

        var allow: Bool? {
            switch self {
            case .allowed: return true
            case .denied: return false
            case .settledElsewhere: return nil
            }
        }
    }

    /// The questions waiting, first in front.
    @Published private(set) var queue: [Request] = []
    /// The "always" answers, oldest first.
    @Published private(set) var grants: [Grant]

    var current: Request? { queue.first }

    private var waiters: [String: CheckedContinuation<Decision, Never>] = [:]
    private var timers: [String: Task<Void, Never>] = [:]
    /// Answers that hold until their chat is cleared or deleted, or the account is left.
    private var sessionGrants = NanoMuseApprovalSessionGrants()

    private static let grantsKey = "nanomuse.remote_approvals.always"
    /// Android's RiskGate waits this long when the other side names no timeout.
    static let defaultTimeout = 180

    private init() {
        grants = Self.loadGrants()
    }

    // MARK: - The question

    /// Answers one `approval` event from `device` about a task typed in `sessionId`: a
    /// remembered answer at once, otherwise the card, otherwise the timeout.
    func decide(_ question: NanoMuseRemoteQuestion, from device: HubDevice, sessionId: String) async -> Outcome {
        let id = question.id
        let preview = question.preview
        let request = Request(
            id: id,
            deviceId: device.id,
            deviceName: device.name,
            sessionId: sessionId,
            risk: Risk(wire: question.risk),
            wireRisk: question.risk.lowercased(),
            preview: preview,
            reason: question.reason,
            grantTarget: question.grantTarget,
            timeout: question.timeout > 0 ? min(max(question.timeout, 30), 600) : Self.defaultTimeout
        )
        let sessionGrant = request.target.map {
            NanoMuseApprovalSessionGrants.Key(
                sessionId: sessionId, deviceId: device.id,
                risk: request.wireRisk, target: $0
            )
        }
        let key = request.target.map {
            Grant.key(deviceId: device.id, risk: request.wireRisk, target: $0)
        }
        if request.canAlways, let key, grants.contains(where: { $0.id == key }) {
            return .allowed(standing: true)
        }
        if request.canSession, let sessionGrant, sessionGrants.allows(sessionGrant) {
            return .allowed(standing: true)
        }

        queue.append(request)
        timers[id] = Task { @MainActor [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(request.timeout) * 1_000_000_000)
            guard !Task.isCancelled else { return }
            self?.resolve(id, .timeout)
        }
        let decision = await withCheckedContinuation { (cont: CheckedContinuation<Decision, Never>) in
            waiters[id] = cont
        }
        queue.removeAll { $0.id == id }
        switch decision {
        case .once, .task:
            return .allowed(standing: false)
        case .session:
            if request.canSession, let sessionGrant { sessionGrants.insert(sessionGrant) }
            return .allowed(standing: false)
        case .always:
            if request.canAlways, let key, let target = request.target {
                grants.removeAll { $0.id == key }
                grants.append(Grant(deviceId: device.id, deviceName: device.name,
                                    risk: request.wireRisk, target: target,
                                    preview: preview, grantedAt: Date()))
                saveGrants()
            }
            return .allowed(standing: false)
        case .deny, .timeout:
            return .denied
        case .elsewhere:
            return .settledElsewhere
        }
    }

    /// A computer's pushed card from `device`: the card, then the answer. Nothing is
    /// remembered here; *Always in this task* is kept on the computer.
    func ask(_ question: NanoMuseScheduledQuestion, from device: (id: String, name: String)) async -> ScheduledOutcome {
        let id = Self.scheduledId(deviceId: device.id, approvalId: question.id)
        guard waiters[id] == nil else { return .withdrawn }
        let request = Request(
            id: id,
            deviceId: device.id,
            deviceName: device.name,
            sessionId: "",
            risk: .other,
            wireRisk: "scheduled",
            preview: question.preview,
            reason: question.reason,
            grantTarget: nil,
            timeout: question.timeout,
            schedule: Request.Schedule(taskTitle: question.taskTitle, app: question.app, canTask: question.canTask)
        )
        queue.append(request)
        timers[id] = Task { @MainActor [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(request.timeout) * 1_000_000_000)
            guard !Task.isCancelled else { return }
            self?.resolve(id, .timeout)
        }
        let decision = await withCheckedContinuation { (cont: CheckedContinuation<Decision, Never>) in
            waiters[id] = cont
        }
        queue.removeAll { $0.id == id }
        switch decision {
        case .once, .session, .always: return .answer("once")
        case .task: return .answer(question.canTask ? "schedule" : "once")
        case .deny: return .answer("deny")
        case .timeout: return .expired
        case .elsewhere: return .withdrawn
        }
    }

    /// The computer's `approval_result`: decided there or on another phone. False when this phone was not asking.
    func close(deviceId: String, approvalId: String) -> Bool {
        let id = Self.scheduledId(deviceId: deviceId, approvalId: approvalId)
        guard waiters[id] != nil else { return false }
        resolve(id, .elsewhere)
        return true
    }

    private static func scheduledId(deviceId: String, approvalId: String) -> String {
        "ask|\(deviceId)|\(approvalId)"
    }

    /// The card's answer.
    func answer(_ id: String, _ decision: Decision) {
        resolve(id, decision)
    }

    /// The other side's `approval_result`: decided there, or expired; the card goes without an answer from here.
    func settled(_ id: String) {
        resolve(id, .elsewhere)
    }

    /// A chat no longer exists or has been cleared, so none of its in-memory answers survive.
    func resetSessionGrants(for sessionId: String) {
        sessionGrants.reset(for: sessionId)
    }

    /// Leaving or replacing an account invalidates every chat-scoped answer.
    func resetAllSessionGrants() {
        sessionGrants.resetAll()
    }

    /// Takes one "always" back.
    func revoke(_ grantId: String) {
        grants.removeAll { $0.id == grantId }
        saveGrants()
    }

    private func resolve(_ id: String, _ decision: Decision) {
        timers.removeValue(forKey: id)?.cancel()
        guard let cont = waiters.removeValue(forKey: id) else { return }
        cont.resume(returning: decision)
    }

    // MARK: - The grants on disk

    private static func loadGrants() -> [Grant] {
        guard let data = UserDefaults.standard.data(forKey: grantsKey) else { return [] }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return (try? decoder.decode([Grant].self, from: data)) ?? []
    }

    private func saveGrants() {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        if let data = try? encoder.encode(grants) {
            UserDefaults.standard.set(data, forKey: Self.grantsKey)
        } else {
            UserDefaults.standard.removeObject(forKey: Self.grantsKey)
        }
    }
}

// MARK: - The card

/// Shows the question in front, as a sheet over whatever is on screen; the next one follows.
struct NanoMuseRemoteApprovalPresenter: ViewModifier {
    @ObservedObject private var approvals = NanoMuseRemoteApprovals.shared

    func body(content: Content) -> some View {
        content
            .sheet(item: Binding(get: { approvals.current }, set: { _ in })) { request in
                NanoMuseRemoteApprovalSheet(request: request)
            }
    }
}

extension View {
    /// The remote approval card, once, at the root.
    func nanoMuseRemoteApprovalPresenter() -> some View {
        modifier(NanoMuseRemoteApprovalPresenter())
    }
}

struct NanoMuseRemoteApprovalSheet: View {
    let request: NanoMuseRemoteApprovals.Request
    @ObservedObject private var approvals = NanoMuseRemoteApprovals.shared

    private var agentName: String { NanoMuseHomeView.currentAgentName() }

    /// Android's titles for the three classes; a plain one for the rest.
    private var title: String {
        if request.schedule != nil {
            return String(format: AppLocalized("Allow %@ to take this step on %@?"), agentName, request.deviceName)
        }
        switch request.risk {
        case .delete: return String(format: AppLocalized("Allow %@ to delete this?"), agentName)
        case .send: return String(format: AppLocalized("Allow %@ to send this?"), agentName)
        case .pay: return String(format: AppLocalized("Allow %@ to make a payment?"), agentName)
        case .other: return String(format: AppLocalized("Allow %@ to take this step?"), agentName)
        }
    }

    private var waiting: Int { max(0, approvals.queue.count - 1) }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text(lead)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    if !request.reason.isEmpty {
                        Text(request.reason)
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                    if waiting > 0 {
                        Text(String(format: AppLocalized("%d more waiting"), waiting))
                            .font(.footnote)
                            .foregroundStyle(.tertiary)
                    }
                }
                Section {
                    Text(request.preview.isEmpty ? AppLocalized("No details were given.") : request.preview)
                        .font(.callout)
                        .textSelection(.enabled)
                } header: {
                    Text(AppLocalized("The step"))
                }
                Section {
                    Button(AppLocalized("Allow once")) { approvals.answer(request.id, .once) }
                    if request.schedule?.canTask == true {
                        Button(AppLocalized("Always in this task")) { approvals.answer(request.id, .task) }
                    }
                    if request.canSession {
                        Button(AppLocalized("Allow for this chat")) { approvals.answer(request.id, .session) }
                    }
                    if request.canAlways {
                        Button(String(format: AppLocalized("Always allow this on %@"), request.deviceName)) { approvals.answer(request.id, .always) }
                    }
                    Button(AppLocalized("Deny"), role: .destructive) { approvals.answer(request.id, .deny) }
                } footer: {
                    Text(footer)
                }
            }
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
        }
        .presentationDetents([.medium, .large])
        .interactiveDismissDisabled()
    }

    /// Where the step runs: for a scheduled task, which task and which app.
    private var lead: String {
        guard let schedule = request.schedule else {
            return String(format: AppLocalized("The step runs on %@, not on this phone."), request.deviceName)
        }
        if schedule.app.isEmpty {
            return String(format: AppLocalized("The scheduled task “%@” is running on %@ and waits for your answer. The step runs there, not on this phone."), schedule.taskTitle, request.deviceName)
        }
        return String(format: AppLocalized("The scheduled task “%@” is running on %@ and wants to act in %@. It waits for your answer; the step runs there, not on this phone."), schedule.taskTitle, request.deviceName, schedule.app)
    }

    private var footer: String {
        if let schedule = request.schedule {
            var lines = [String(format: AppLocalized("No answer in %d seconds leaves the question waiting on %@."), request.timeout, request.deviceName)]
            if schedule.canTask {
                lines.append(String(format: AppLocalized("Always in this task is kept on %@: this task stops asking there. Revoke it under Settings → Permissions on that computer."), request.deviceName))
            }
            return lines.joined(separator: " ")
        }
        var lines = [String(format: AppLocalized("No answer in %d seconds counts as a no."), request.timeout)]
        if request.canAlways {
            lines.append(String(format: AppLocalized("Always allow lets this same step run on %@ without asking; Approvals on the agent's page lists it and can take it back."), request.deviceName))
        } else if request.risk == .pay {
            lines.append(AppLocalized("A payment is answered one at a time."))
        }
        return lines.joined(separator: " ")
    }
}
