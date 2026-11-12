import CryptoKit
import SwiftUI

/// Caller-side conversations for the Hub's persistent task protocol (docs/hub.md).
@MainActor
final class NanoMuseDeviceConversations: ObservableObject {
    static let shared = NanoMuseDeviceConversations()
    nonisolated static var fileURL: URL { NanoMuseDirs.root.appendingPathComponent("device-chats.json") }

    enum State: String, Codable {
        case unknown, accepted, completed, failed, cancelled, interrupted

        var pending: Bool { self == .unknown || self == .accepted }
    }

    struct Destination: Codable {
        let id: String
        let name: String
        let phone: Bool

        init(_ device: HubDevice) {
            id = device.id
            name = device.name
            phone = device.isPhone
        }

        var symbol: String { phone ? "iphone" : "desktopcomputer" }
    }

    struct Turn: Identifiable, Codable {
        var id = UUID().uuidString.lowercased()
        let prompt: String
        var alternate: Destination?
        var state: State = .unknown
        var answer: String?
        var error: String?
        var rejected = false

        func arguments(chat: Chat) -> [String: Any] {
            ["conversation": alternate == nil ? chat.id : id, "turn_id": id]
        }
    }

    struct Chat: Identifiable, Codable {
        var id = UUID().uuidString.lowercased()
        let destination: Destination
        var draft = ""
        var turns: [Turn] = []

        var pending: Turn? { turns.last(where: { $0.state.pending }) }
        var contextLost: Bool { turns.contains { $0.alternate == nil && $0.error == "context_lost" } }
        var title: String { turns.first?.prompt.components(separatedBy: .newlines).first ?? destination.name }
    }

    private struct Archive: Codable {
        let owner: String
        let chats: [Chat]
    }

    enum Route {
        case bound
        case alternate(NanoMuseDeviceMention.Hit)
        case ambiguous
    }

    static func route(_ text: String, devices: [HubDevice]) -> Route {
        let matches = NanoMuseDeviceMention.matches(text, devices: devices)
        guard let first = matches.first else { return .bound }
        let candidates = matches.prefix { $0.device.name.count == first.device.name.count }
        if first.task.hasPrefix("["), let end = first.task.firstIndex(of: "]") {
            let id = first.task[first.task.index(after: first.task.startIndex)..<end]
            if let selected = candidates.first(where: { $0.device.id == id }) {
                let task = NanoMuseDeviceMention.taskText(String(first.task[first.task.index(after: end)...]))
                return .alternate(.init(device: selected.device, task: task))
            }
            return .ambiguous
        }
        return candidates.count == 1 ? .alternate(first) : .ambiguous
    }

    struct Live {
        var text = ""
        var step = ""
        var approvals: [Approval] = []
    }

    struct Approval: Identifiable {
        let id: String
        let preview: String
        let reason: String
        let expires: Date
    }

    @Published private(set) var chats: [Chat] = []
    @Published private(set) var sending: Set<String> = []
    @Published private(set) var live: [String: Live] = [:]
    @Published private(set) var storageError = false
    private var account: String?
    private var revision = UUID()
    private var statusRequests: [String: UUID] = [:]
    private let hub = NanoMuseHub.shared

    private var currentAccount: String? {
        guard NanoMuseCloud.isSignedIn, let id = NanoMuseCloud.account?.id, !id.isEmpty else { return nil }
        return NanoMuseCloud.baseURL + "|" + id
    }

    private var leavingAccount = false

    func suspendForAccountChange() {
        leavingAccount = true
        clear()
    }

    func resumeAfterAccountChange() {
        leavingAccount = false
        load()
    }

    private func clear() {
        revision = UUID()
        account = nil
        chats = []
        live = [:]
        sending = []
        statusRequests = [:]
        storageError = false
    }

    func load() {
        let key = currentAccount
        guard !leavingAccount, key != account || storageError else { return }
        clear()
        account = key
        guard let key else { return }
        do {
            let url = Self.fileURL
            if FileManager.default.fileExists(atPath: url.path) {
                let archive = try JSONDecoder().decode(Archive.self, from: Data(contentsOf: url))
                guard archive.owner == Self.owner(key) else {
                    storageError = true
                    return
                }
                chats = archive.chats
            }
        } catch {
            storageError = true
        }
    }

    var available: Bool { account != nil && account == currentAccount && !storageError }

    private static func owner(_ key: String) -> String {
        SHA256.hash(data: Data(key.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    private func save(_ next: [Chat]) throws {
        guard available, let account else { throw HubError(code: "bad_key", message: "") }
        let url = Self.fileURL
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        let archive = Archive(owner: Self.owner(account), chats: next)
        try JSONEncoder().encode(archive).write(to: url, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
        chats = next
    }

    private func update(_ id: String, _ change: (inout Chat) -> Void) throws {
        guard let index = chats.firstIndex(where: { $0.id == id }) else { return }
        var next = chats
        change(&next[index])
        try save(next)
    }

    func create(_ device: HubDevice) throws -> String {
        guard hub.others.contains(where: { $0.id == device.id }) else {
            throw HubError(code: "no_device", message: "")
        }
        let chat = Chat(destination: Destination(device))
        try save([chat] + chats)
        return chat.id
    }

    func draft(_ text: String, in id: String) throws {
        guard chats.first(where: { $0.id == id })?.draft != text else { return }
        try update(id) { $0.draft = text }
    }

    func remove(_ chat: Chat) throws {
        guard let saved = chats.first(where: { $0.id == chat.id }), saved.pending?.state != .accepted,
              !sending.contains(chat.id) else { return }
        try save(chats.filter { $0.id != chat.id })
    }

    func device(for destination: Destination) -> HubDevice? {
        hub.others.first { $0.id == destination.id }
    }

    func canSend(to destination: Destination) -> Bool {
        guard available, hub.connected, let device = device(for: destination), device.online else { return false }
        return device.actions.contains("task.status")
    }

    func send(_ chat: Chat, prompt: String, to alternate: HubDevice?) async throws {
        let text = chat.draft.trimmingCharacters(in: .whitespacesAndNewlines)
        let turn = Turn(prompt: text, alternate: alternate.map(Destination.init))
        let target = turn.alternate ?? chat.destination
        guard !prompt.isEmpty, canSend(to: target), !sending.contains(chat.id),
              let saved = chats.first(where: { $0.id == chat.id }), saved.pending == nil,
              turn.alternate != nil || !saved.contextLost else { return }

        let first = turn.alternate != nil || saved.turns.allSatisfy { $0.alternate != nil || $0.rejected }
        try update(chat.id) {
            $0.turns.append(turn)
            if $0.draft == chat.draft { $0.draft = "" }
        }
        let revision = self.revision
        sending.insert(chat.id)
        live[chat.id] = Live()
        defer {
            if self.revision == revision { sending.remove(chat.id) }
        }
        var args = turn.arguments(chat: chat)
        args["text"] = prompt
        args["stream"] = true
        args["new_conversation"] = first
        args["language"] = NanoMuseLocale.tag
        var accepted = false
        let reply: [String: Any]
        do {
            reply = try await hub.call(to: target.id, action: "task", args: args, timeout: 15 * 60) { body in
                guard self.available, self.revision == revision else { return }
                if (body["stage"] as? String) == "accepted", (body["turn_id"] as? String) == turn.id {
                    accepted = true
                }
                self.event(body, in: chat.id)
            }
        } catch {
            guard available, self.revision == revision else { return }
            // A transport failure leaves delivery uncertain. Status is the only recovery call.
            if !accepted, let failure = error as? HubError,
               ["not_allowed", "denied", "usage", "no_model", "not_ready", "context_lost", "busy"].contains(failure.code) {
                try reconcile(chat.id, turn: turn.id, reply: ["state": "failed", "error": failure.code], rejected: true)
            }
            return
        }
        guard available, self.revision == revision else { return }
        try reconcile(chat.id, turn: turn.id, reply: reply)
    }

    func refresh(_ chat: Chat, turn: Turn) async throws {
        guard !Task.isCancelled, !sending.contains(chat.id), canSend(to: turn.alternate ?? chat.destination) else { return }
        let request = UUID()
        statusRequests[chat.id] = request
        defer {
            if statusRequests[chat.id] == request { statusRequests[chat.id] = nil }
        }
        let reply = try await control("task.status", chat: chat, turn: turn, args: turn.arguments(chat: chat))
        guard !Task.isCancelled, available, statusRequests[chat.id] == request,
              chats.first(where: { $0.id == chat.id })?.pending?.id == turn.id else { return }
        try reconcile(chat.id, turn: turn.id, reply: reply)
        if let state = reply["state"] as? String, state == State.accepted.rawValue || state == State.unknown.rawValue {
            live[chat.id] = Live()
            for body in (reply["events"] as? [[String: Any]] ?? []) { event(body, in: chat.id) }
        }
    }

    func stop(_ chat: Chat, turn: Turn) async throws {
        _ = try await control("stop", chat: chat, turn: turn, args: turn.arguments(chat: chat))
    }

    func approve(_ approval: Approval, allow: Bool, chat: Chat, turn: Turn) async throws {
        guard approval.expires > Date(), live[chat.id]?.approvals.contains(where: { $0.id == approval.id }) == true else { return }
        let revision = self.revision
        _ = try await control("approve", chat: chat, turn: turn, args: ["approval_id": approval.id, "allow": allow])
        if self.revision == revision { live[chat.id]?.approvals.removeAll { $0.id == approval.id } }
    }

    private func control(_ action: String, chat: Chat, turn: Turn, args: [String: Any]) async throws -> [String: Any] {
        let target = turn.alternate ?? chat.destination
        guard canSend(to: target), chats.first(where: { $0.id == chat.id })?.pending?.id == turn.id else {
            throw HubError(code: "device_offline", message: "")
        }
        return try await hub.call(to: target.id, action: action, args: args, timeout: 10)
    }

    private func reconcile(_ chat: String, turn: String, reply: [String: Any], rejected: Bool = false) throws {
        guard let raw = reply["state"] as? String, let state = State(rawValue: raw) else { return }
        try update(chat) {
            guard let index = $0.turns.firstIndex(where: { $0.id == turn && $0.state.pending }) else { return }
            $0.turns[index].state = state
            $0.turns[index].answer = reply["text"] as? String
            $0.turns[index].error = reply["error"] as? String
            $0.turns[index].rejected = rejected
        }
        if !state.pending { live[chat] = nil }
    }

    private func event(_ body: [String: Any], in chat: String) {
        var snapshot = live[chat] ?? Live()
        switch body["stage"] as? String {
        case "accepted":
            // The record was already durable before dispatch; the executor is now known to have it.
            if let id = body["turn_id"] as? String {
                try? reconcile(chat, turn: id, reply: ["state": "accepted"])
            }
        case "text": snapshot.text = body["text"] as? String ?? ""
        case "tool": snapshot.step = (body["summary"] as? String) ?? (body["name"] as? String) ?? ""
        case "tool_result": snapshot.step = ""
        case "approval":
            if let question = NanoMuseRemoteQuestion(body: body) {
                let seconds = question.timeout > 0 ? question.timeout : 180
                snapshot.approvals.removeAll { $0.id == question.id }
                snapshot.approvals.append(Approval(id: question.id, preview: question.preview, reason: question.reason,
                                                   expires: Date().addingTimeInterval(TimeInterval(seconds))))
            }
        case "approval_result":
            if let id = body["approval_id"] as? String { snapshot.approvals.removeAll { $0.id == id } }
        default: return
        }
        live[chat] = snapshot
    }
}
