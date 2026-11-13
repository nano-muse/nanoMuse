import Foundation

// Compile this with the production NanoMuseDeviceConversations.swift. Only its app services
// are replaced here. The real state machine, JSON archive and atomic writes run unchanged.
struct HubDevice {
    let id: String
    let name: String
    let isPhone = false
    let online = true
    let actions = ["task", "task.status", "approve", "stop"]
}

struct HubError: Error {
    let code: String
    let message: String
}

enum NanoMuseDirs {
    static var root = FileManager.default.temporaryDirectory
}

enum NanoMuseLocale { static let tag = "en" }

@MainActor
enum NanoMuseCloud {
    struct Account { let id: String }
    static var baseURL = "https://relay.invalid"
    static var isSignedIn = true
    static var account: Account? = Account(id: "account-a")
}

enum NanoMuseDeviceMention {
    struct Hit { let device: HubDevice; let task: String }
    // Mention parsing belongs to the app adapter, not the lifecycle under test.
    static func matches(_ text: String, devices: [HubDevice]) -> [Hit] { [] }
    static func taskText(_ text: String) -> String { text.trimmingCharacters(in: .whitespacesAndNewlines) }
}

struct NanoMuseRemoteQuestion {
    let id: String
    let preview: String
    let reason: String
    let timeout = 180
    init?(body: [String: Any]) {
        guard let id = body["approval_id"] as? String else { return nil }
        self.id = id
        preview = body["preview"] as? String ?? ""
        reason = body["reason"] as? String ?? ""
    }
}

@MainActor
final class NanoMuseHub {
    struct Call {
        let target: String
        let action: String
        let args: [String: Any]
        let event: (([String: Any]) -> Void)?
    }
    static let shared = NanoMuseHub()
    var connected = true
    var others: [HubDevice] = []
    var calls: [Call] = []
    var handler: (@MainActor (Call) async throws -> [String: Any])?

    func call(to: String, action: String, args: [String: Any], timeout: TimeInterval,
              onEvent: (([String: Any]) -> Void)? = nil) async throws -> [String: Any] {
        let call = Call(target: to, action: action, args: args, event: onEvent)
        calls.append(call)
        guard let handler else { preconditionFailure("Unexpected Hub call") }
        return try await handler(call)
    }
}

@MainActor
final class ReplyGate {
    private var pending: CheckedContinuation<[String: Any], Error>?
    private var waiters: [CheckedContinuation<Void, Never>] = []
    func receive() async throws -> [String: Any] {
        try await withCheckedThrowingContinuation { continuation in
            pending = continuation
            for waiter in waiters { waiter.resume() }
            waiters = []
        }
    }
    func started() async {
        if pending != nil { return }
        await withCheckedContinuation { waiters.append($0) }
    }
    func finish(_ reply: [String: Any]) {
        let continuation = pending
        pending = nil
        continuation?.resume(returning: reply)
    }
}

@main
@MainActor
struct DeviceConversationsChecks {
    @MainActor
    struct Fixture {
        let model: NanoMuseDeviceConversations
        let device: HubDevice
        let root: URL
        init() {
            root = FileManager.default.temporaryDirectory.appendingPathComponent("nanomuse-device-check-\(UUID())")
            NanoMuseDirs.root = root
            NanoMuseCloud.account = .init(id: "account-a")
            NanoMuseCloud.isSignedIn = true
            let hub = NanoMuseHub.shared
            hub.connected = true
            device = HubDevice(id: "device-a", name: "Computer")
            hub.others = [device, HubDevice(id: "device-b", name: "Other computer")]
            hub.calls = []
            hub.handler = nil
            model = NanoMuseDeviceConversations()
            model.load()
        }
        func cleanup() { try? FileManager.default.removeItem(at: root) }
    }

    static func chat(_ model: NanoMuseDeviceConversations, _ id: String) -> NanoMuseDeviceConversations.Chat {
        guard let saved = model.chats.first(where: { $0.id == id }) else { preconditionFailure("Chat missing") }
        return saved
    }

    static func main() async throws {
        try await durableBeforeDispatchAndNewerDraft()
        try await failedWriteDoesNotDispatch()
        try await unknownDeliveryNeverResends()
        try await accountSwitchDiscardsOldResponse()
        try await newestStatusWins()
        try await alternateTurnKeepsControlTarget()
        print("Persistent device conversation checks passed (6 lifecycle scenarios)")
    }

    static func durableBeforeDispatchAndNewerDraft() async throws {
        let f = Fixture(); defer { f.cleanup() }
        let id = try f.model.create(f.device)
        try f.model.draft("First prompt", in: id)
        let gate = ReplyGate()
        NanoMuseHub.shared.handler = { call in
            let bytes = try Data(contentsOf: NanoMuseDeviceConversations.fileURL)
            let saved = try JSONSerialization.jsonObject(with: bytes) as! [String: Any]
            let archivedChat = (saved["chats"] as! [[String: Any]]).first!
            let turn = (archivedChat["turns"] as! [[String: Any]]).last!
            precondition(turn["id"] as? String == call.args["turn_id"] as? String)
            precondition(turn["state"] as? String == "unknown")
            precondition(archivedChat["draft"] as? String == "")
            return try await gate.receive()
        }
        let sent = chat(f.model, id)
        let task = Task { try await f.model.send(sent, prompt: sent.draft, to: nil) }
        await gate.started()
        try f.model.draft("Newer input", in: id)
        gate.finish(["state": "completed", "text": "First answer"])
        try await task.value
        precondition(chat(f.model, id).draft == "Newer input")
        let reopened = NanoMuseDeviceConversations(); reopened.load()
        precondition(chat(reopened, id).turns.last?.answer == "First answer")
        precondition(chat(reopened, id).draft == "Newer input")
    }

    static func failedWriteDoesNotDispatch() async throws {
        let f = Fixture(); defer { f.cleanup() }
        let id = try f.model.create(f.device)
        try f.model.draft("Keep this prompt", in: id)
        let originalURL = NanoMuseDeviceConversations.fileURL
        let original = try Data(contentsOf: originalURL)
        let blocker = f.root.appendingPathComponent("not-a-directory")
        try Data("fixture".utf8).write(to: blocker)
        NanoMuseDirs.root = blocker
        let sent = chat(f.model, id)
        do {
            try await f.model.send(sent, prompt: sent.draft, to: nil)
            preconditionFailure("A failed archive write must throw")
        } catch { /* The original archive and in-memory draft must survive. */ }
        precondition(NanoMuseHub.shared.calls.isEmpty)
        precondition(chat(f.model, id).turns.isEmpty)
        precondition(chat(f.model, id).draft == "Keep this prompt")
        let remaining = try Data(contentsOf: originalURL)
        precondition(remaining == original)
    }

    static func unknownDeliveryNeverResends() async throws {
        let f = Fixture(); defer { f.cleanup() }
        let id = try f.model.create(f.device)
        try f.model.draft("Uncertain prompt", in: id)
        NanoMuseHub.shared.handler = { _ in throw HubError(code: "disconnected", message: "fixture") }
        let sent = chat(f.model, id)
        try await f.model.send(sent, prompt: sent.draft, to: nil)
        let pending = chat(f.model, id).pending!
        precondition(pending.state == .unknown)
        precondition(NanoMuseHub.shared.calls.count == 1)
        NanoMuseHub.shared.handler = { call in
            precondition(call.action == "task.status")
            precondition(call.args["conversation"] as? String == id)
            precondition(call.args["turn_id"] as? String == pending.id)
            return ["state": "unknown"]
        }
        try await f.model.refresh(chat(f.model, id), turn: pending)
        try f.model.draft("Do not replay", in: id)
        try await f.model.send(chat(f.model, id), prompt: "Do not replay", to: nil)
        precondition(NanoMuseHub.shared.calls.map(\.action) == ["task", "task.status"])
        precondition(chat(f.model, id).pending?.id == pending.id)
        precondition(chat(f.model, id).draft == "Do not replay")
    }

    static func accountSwitchDiscardsOldResponse() async throws {
        let f = Fixture(); defer { f.cleanup() }
        let id = try f.model.create(f.device)
        try f.model.draft("Account A prompt", in: id)
        let gate = ReplyGate()
        NanoMuseHub.shared.handler = { _ in try await gate.receive() }
        let sent = chat(f.model, id)
        let task = Task { try await f.model.send(sent, prompt: sent.draft, to: nil) }
        await gate.started()
        f.model.suspendForAccountChange()
        NanoMuseCloud.account = .init(id: "account-b")
        f.model.resumeAfterAccountChange()
        precondition(f.model.storageError && !f.model.available && f.model.chats.isEmpty)
        let aArchive = f.root.appendingPathComponent("account-a.json")
        try FileManager.default.moveItem(at: NanoMuseDeviceConversations.fileURL, to: aArchive)
        f.model.resumeAfterAccountChange()
        let b = try f.model.create(f.device)
        try f.model.draft("Account B draft", in: b)
        gate.finish(["state": "completed", "text": "Private account A answer"])
        try await task.value
        precondition(f.model.chats.count == 1 && chat(f.model, b).draft == "Account B draft")
        precondition(chat(f.model, b).turns.isEmpty)
        f.model.suspendForAccountChange()
        NanoMuseCloud.account = .init(id: "account-a")
        try FileManager.default.removeItem(at: NanoMuseDeviceConversations.fileURL)
        try FileManager.default.moveItem(at: aArchive, to: NanoMuseDeviceConversations.fileURL)
        f.model.resumeAfterAccountChange()
        precondition(chat(f.model, id).pending?.state == .unknown)
        precondition(chat(f.model, id).turns.last?.answer == nil)
    }

    static func newestStatusWins() async throws {
        let f = Fixture(); defer { f.cleanup() }
        let id = try f.model.create(f.device)
        try f.model.draft("Status prompt", in: id)
        NanoMuseHub.shared.handler = { _ in throw HubError(code: "disconnected", message: "fixture") }
        try await f.model.send(chat(f.model, id), prompt: "Status prompt", to: nil)
        let pending = chat(f.model, id).pending!
        let old = ReplyGate()
        NanoMuseHub.shared.handler = { _ in try await old.receive() }
        let first = Task { try await f.model.refresh(chat(f.model, id), turn: pending) }
        await old.started()
        NanoMuseHub.shared.handler = { _ in ["state": "completed", "text": "Recovered result"] }
        try await f.model.refresh(chat(f.model, id), turn: pending)
        old.finish(["state": "accepted"])
        try await first.value
        precondition(chat(f.model, id).turns.last?.state == .completed)
        precondition(chat(f.model, id).turns.last?.answer == "Recovered result")
    }

    static func alternateTurnKeepsControlTarget() async throws {
        let f = Fixture(); defer { f.cleanup() }
        let id = try f.model.create(f.device)
        try f.model.draft("@Other computer ask", in: id)
        let other = NanoMuseHub.shared.others[1]
        NanoMuseHub.shared.handler = { call in
            precondition(call.target == other.id && call.action == "task")
            precondition(call.args["conversation"] as? String == call.args["turn_id"] as? String)
            call.event?(["stage": "approval", "approval_id": "fixture-approval", "preview": "Fixture step"])
            return ["state": "accepted"]
        }
        try await f.model.send(chat(f.model, id), prompt: "ask", to: other)
        let saved = chat(f.model, id), pending = saved.pending!
        NanoMuseHub.shared.handler = { call in
            precondition(call.target == other.id)
            if call.action == "stop" {
                precondition(call.args["conversation"] as? String == pending.id)
                precondition(call.args["turn_id"] as? String == pending.id)
            } else {
                precondition(call.action == "approve" && call.args["allow"] as? Bool == true)
            }
            return [:]
        }
        try await f.model.approve(f.model.live[id]!.approvals.first!, allow: true, chat: saved, turn: pending)
        try await f.model.stop(saved, turn: pending)
        precondition(chat(f.model, id).pending?.state == .accepted, "Stop acknowledgement is not a terminal outcome")
    }
}
