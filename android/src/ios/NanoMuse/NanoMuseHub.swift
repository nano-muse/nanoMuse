// nanoMuse: this iPhone on the hub — one outbound WebSocket to the relay the account is signed
// in to, so the user's other devices (computers running nanoMuse Desktop, Android phones, the
// web console) reach it from any network, and it can ask them for things.
//
// The protocol is docs/hub.md. What this phone does for others is decided here: `info`, `open`,
// `notify`, `task` and `stop` work (the task runs on this phone's Muse, NanoMuseHubTasks);
// `screen` is refused with `no_screen`, and `shell`, `files` and `approve` are not offered on
// iOS (the sandbox has no entry point for other devices), so a caller asking for them gets a
// clear `not_supported` rather than a hang. Mirrors io.github.nanomuse.hub on Android.

import Foundation
import UIKit
import UserNotifications

// MARK: - Types

struct HubDevice: Identifiable, Equatable {
    let id: String
    let name: String
    let kind: String   // phone | computer | web
    let os: String
    let version: String
    let online: Bool
    let lastSeen: Date?
    /// The hub actions the device answers (`coding.sessions`, `shell`, …); empty when it did not say.
    let actions: [String]

    var isPhone: Bool { kind == "phone" }
    var isComputer: Bool { kind == "computer" }

    init?(_ json: [String: Any]) {
        guard let id = json["id"] as? String, !id.isEmpty else { return nil }
        self.id = id
        name = (json["name"] as? String) ?? id
        kind = (json["kind"] as? String) ?? "computer"
        os = (json["os"] as? String) ?? ""
        version = (json["version"] as? String) ?? ""
        online = (json["online"] as? Bool) ?? false
        actions = (json["actions"] as? [String]) ?? []
        if let t = json["last_seen"] as? Double, t > 0 { lastSeen = Date(timeIntervalSince1970: t) } else { lastSeen = nil }
    }
}

struct HubError: LocalizedError {
    let code: String
    let message: String
    var errorDescription: String? { message }
}

// MARK: - The hub

@MainActor
final class NanoMuseHub: ObservableObject {
    static let shared = NanoMuseHub()

    static let actions = ["info", "open", "notify", "task", "stop"]
    static let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0"

    /// Where the connection stands, for the Devices page; `connected` is the short form.
    enum State: Equatable {
        case idle
        case connecting
        case connected
        /// Dropped; trying again after a backoff.
        case reconnecting
        /// The operator paused the hub (`hub_paused`, docs/hub.md); trying again in a while.
        case paused
        /// Close 4003: a newer connection of this device id took the seat; trying again later.
        case replaced
        /// Close 4001 / 4002: the relay refused the key or the device; a new sign-in starts over.
        case refused
        /// The relay sent an `error` frame without a call id; its own sentence.
        case error(String)
    }

    @Published private(set) var connected = false
    @Published private(set) var devices: [HubDevice] = []
    @Published private(set) var state: State = .idle

    private enum Keys {
        static let enabled = "nanomuse.hub.enabled"
        static let deviceId = "nanomuse.hub.device_id"
        static let name = "nanomuse.hub.name"
        static let remoteControl = "nanomuse.hub.remote_control"
    }

    // Settings -------------------------------------------------------------------------

    var enabled: Bool {
        get { UserDefaults.standard.object(forKey: Keys.enabled) as? Bool ?? true }
        set {
            UserDefaults.standard.set(newValue, forKey: Keys.enabled)
            if newValue { autoStart() } else { stop() }
        }
    }

    var remoteControl: Bool {
        get { UserDefaults.standard.object(forKey: Keys.remoteControl) as? Bool ?? true }
        set { UserDefaults.standard.set(newValue, forKey: Keys.remoteControl) }
    }

    var deviceId: String {
        if let id = UserDefaults.standard.string(forKey: Keys.deviceId), !id.isEmpty { return id }
        let id = "phone-" + UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased().prefix(12)
        UserDefaults.standard.set(String(id), forKey: Keys.deviceId)
        return String(id)
    }

    var name: String {
        get {
            if let n = UserDefaults.standard.string(forKey: Keys.name)?.trimmingCharacters(in: .whitespaces), !n.isEmpty { return n }
            return UIDevice.current.name.isEmpty ? "iPhone" : UIDevice.current.name
        }
        set {
            UserDefaults.standard.set(String(newValue.trimmingCharacters(in: .whitespaces).prefix(60)), forKey: Keys.name)
            send(["type": "rename", "name": name])
        }
    }

    var webConsoleURL: String { NanoMuseCloud.baseURL + "/app/" }

    /// The other devices of the account: never this phone, never a browser tab.
    var others: [HubDevice] { devices.filter { $0.id != deviceId && $0.kind != "web" } }

    // Connection -----------------------------------------------------------------------

    private var task: URLSessionWebSocketTask?
    /// Bumped on every connect; callbacks from an older socket compare against it and step aside.
    private var generation = 0
    private var backoff: TimeInterval = 1
    private var stopping = false
    /// Close 4001 / 4002: the relay would say the same next time, so `autoStart` waits for a
    /// new sign-in or key (`restart`) instead of knocking again.
    private var refused = false
    private var reconnectTask: Task<Void, Never>?
    private var pending: [String: (Result<[String: Any], HubError>) -> Void] = [:]
    private var eventHandlers: [String: ([String: Any]) -> Void] = [:]

    /// Joins the hub when the account is signed in and the switch is on; a no-op otherwise.
    func autoStart() {
        guard enabled, NanoMuseCloud.isSignedIn, task == nil, !refused else { return }
        start()
    }

    func start() {
        guard task == nil, let inst = NanoMuseCloud.instance,
              let key = ProviderKeychainHelper.loadAPIKey(instanceId: inst.id), !key.isEmpty else { return }
        var base = NanoMuseCloud.baseURL
        if base.hasPrefix("https://") { base = "wss://" + base.dropFirst(8) } else if base.hasPrefix("http://") { base = "ws://" + base.dropFirst(7) }
        guard let url = URL(string: base + "/v1/hub") else { return }
        stopping = false
        refused = false
        reconnectTask?.cancel()
        reconnectTask = nil
        var request = URLRequest(url: url)
        request.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization")
        request.setValue("nanoMuse-iOS/\(Self.version)", forHTTPHeaderField: "User-Agent")
        let task = URLSession.shared.webSocketTask(with: request)
        task.maximumMessageSize = 16 * 1024 * 1024
        generation += 1
        self.task = task
        state = .connecting
        task.resume()
        send(hello())
        receive(generation)
        schedulePing(generation)
    }

    func stop() {
        stopping = true
        refused = false // a deliberate stop (sign-out, a new key through `restart`) starts afresh
        reconnectTask?.cancel()
        reconnectTask = nil
        task?.cancel(with: .normalClosure, reason: nil)
        task = nil
        generation += 1
        connected = false
        devices = []
        state = .idle
        failAll(HubError(code: "disconnected", message: "left the hub"))
    }

    /// Sign-in or a key change: leave, then join again if it still makes sense.
    func restart() {
        stop()
        autoStart()
    }

    private func hello() -> [String: Any] {
        [
            "type": "hello",
            "device": [
                "id": deviceId,
                "name": name,
                "kind": "phone",
                "os": "iOS \(UIDevice.current.systemVersion)",
                "version": Self.version,
                "actions": Self.actions,
            ],
        ]
    }

    private func receive(_ gen: Int) {
        guard let task else { return }
        task.receive { [weak self] result in
            // Only plain values cross into the main actor: the text of the frame, or why it ended.
            var text: String?
            var failure: String?
            switch result {
            case .success(let message):
                if case .string(let s) = message { text = s }
            case .failure(let error):
                failure = error.localizedDescription
            }
            Task { @MainActor [text, failure] in
                guard let self, self.generation == gen else { return }
                if let failure { self.dropped(failure); return }
                if let text, let data = text.data(using: .utf8),
                   let frame = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                    self.handle(frame)
                }
                self.receive(gen)
            }
        }
    }

    /// The socket ended. The relay's close code says what to do next (docs/hub.md): 4001 and
    /// 4002 are final until a new sign-in; 4003 means another connection of this device took
    /// the seat, so wait a while; `hub_paused` means the operator switched the hub off, so
    /// wait longer; anything else is the network, and the backoff doubles up to 30 s.
    private func dropped(_ why: String) {
        let code = task?.closeCode.rawValue ?? 0
        let reason = task?.closeReason.flatMap { String(data: $0, encoding: .utf8) } ?? ""
        connected = false
        task = nil
        generation += 1
        failAll(HubError(code: "disconnected", message: why))
        guard !stopping else { return }
        if code == 4001 || code == 4002 {
            refused = true
            state = .refused
            return
        }
        var delay = backoff
        backoff = min(backoff * 2, 30)
        if reason == "hub_paused" {
            state = .paused
            delay = 120
        } else if code == 4003 {
            state = .replaced
            delay = 30
        } else {
            state = .reconnecting
        }
        reconnectTask?.cancel()
        reconnectTask = Task { @MainActor [weak self] in
            try? await Task.sleep(nanoseconds: UInt64(delay * 1_000_000_000))
            guard !Task.isCancelled else { return }
            self?.autoStart()
        }
    }

    private func schedulePing(_ gen: Int) {
        Task { @MainActor [weak self] in
            try? await Task.sleep(nanoseconds: 25_000_000_000)
            guard let self, self.generation == gen, let task = self.task else { return }
            task.sendPing { [weak self] error in
                let failure = error?.localizedDescription
                Task { @MainActor in
                    guard let self, self.generation == gen else { return }
                    if let failure { self.dropped(failure) } else { self.schedulePing(gen) }
                }
            }
        }
    }

    private func send(_ frame: [String: Any]) {
        guard let task, let data = try? JSONSerialization.data(withJSONObject: frame), let text = String(data: data, encoding: .utf8) else { return }
        let gen = generation
        task.send(.string(text)) { [weak self] error in
            guard let failure = error?.localizedDescription else { return }
            Task { @MainActor in
                guard let self, self.generation == gen else { return }
                self.dropped(failure)
            }
        }
    }

    private func handle(_ frame: [String: Any]) {
        switch frame["type"] as? String {
        case "welcome":
            connected = true
            backoff = 1
            state = .connected
            devices = (frame["devices"] as? [[String: Any]] ?? []).compactMap(HubDevice.init)
            // C9: what the relay remembers of who is working on what (frames missed while away).
            NanoMusePresence.shared.refresh()
        case "devices":
            devices = (frame["devices"] as? [[String: Any]] ?? []).compactMap(HubDevice.init)
        case "ping":
            send(["type": "pong"])
        case "call":
            incoming(frame)
        case "result":
            guard let id = frame["id"] as? String, let done = pending.removeValue(forKey: id) else { return }
            eventHandlers.removeValue(forKey: id)
            if (frame["ok"] as? Bool) ?? false {
                done(.success(frame["body"] as? [String: Any] ?? [:]))
            } else {
                done(.failure(HubError(code: frame["error"] as? String ?? "failed", message: frame["message"] as? String ?? "failed")))
            }
        case "event":
            if let id = frame["id"] as? String, let body = frame["body"] as? [String: Any] { eventHandlers[id]?(body) }
        case "profile":
            // Another device of the account wrote the agent's look.
            NanoMuseProfileSync.shared.onHubFrame(frame)
        case "sync":
            // C7: another device pushed conversations; pull from our cursor.
            NanoMuseSync.shared.onHubFrame(frame)
        case "working":
            // C9: another device started or ended a turn on a synced conversation.
            NanoMusePresence.shared.onHubFrame(frame)
        case "error":
            if let id = frame["id"] as? String, let done = pending.removeValue(forKey: id) {
                eventHandlers.removeValue(forKey: id)
                done(.failure(HubError(code: frame["code"] as? String ?? "error", message: frame["message"] as? String ?? "error")))
            } else if connected {
                // `too_large`, `rate_limited`, `bad_frame`: a word about one frame while the
                // socket stays open (docs/hub.md); the Devices row keeps saying Connected.
                AppLogger(category: "NanoMuseHub").info("relay error frame: \(frame["code"] as? String ?? "error")")
            } else {
                // `bad_key` / `bad_device` ahead of the close: the row says so until 4001/4002 lands
                state = .error(frame["message"] as? String ?? "")
            }
        default:
            break
        }
    }

    private func failAll(_ error: HubError) {
        let waiting = pending
        pending = [:]
        eventHandlers = [:]
        waiting.values.forEach { $0(.failure(error)) }
    }

    // Calls out --------------------------------------------------------------------------

    /// Asks another device for something; resolves with its `result` body. Progress arrives on `onEvent`.
    func call(to: String, action: String, args: [String: Any] = [:], timeout: TimeInterval = 120, onEvent: (([String: Any]) -> Void)? = nil) async throws -> [String: Any] {
        guard connected else { throw HubError(code: "disconnected", message: "this iPhone is not on the hub; sign in to nanoMuse Cloud and turn on Devices") }
        let id = String(UUID().uuidString.lowercased().prefix(12))
        return try await withCheckedThrowingContinuation { cont in
            var finished = false
            var timer: Task<Void, Never>?
            pending[id] = { result in
                guard !finished else { return }
                finished = true
                timer?.cancel()
                cont.resume(with: result.mapError { $0 as Error })
            }
            if let onEvent { eventHandlers[id] = onEvent }
            send(["type": "call", "id": id, "to": to, "action": action, "args": args])
            // The timer ends with the answer, so a long timeout does not keep the hub alive for nothing.
            timer = Task { @MainActor [weak self] in
                try? await Task.sleep(nanoseconds: UInt64(timeout * 1_000_000_000))
                guard !Task.isCancelled, let self, let done = self.pending.removeValue(forKey: id) else { return }
                self.eventHandlers.removeValue(forKey: id)
                done(.failure(HubError(code: "timeout", message: "\(to) did not answer in time")))
            }
        }
    }

    /// Drops an offline device from the account's list; the hub refuses while it is connected.
    func forget(_ deviceId: String) { send(["type": "forget", "device_id": deviceId]) }

    /// By name (case-insensitive), by id, by a unique substring, or by kind words.
    func find(_ query: String?) -> HubDevice? {
        let all = others
        let q = (query ?? "").trimmingCharacters(in: .whitespaces).lowercased()
        if q.isEmpty { let online = all.filter(\.online); return online.count == 1 ? online[0] : nil }
        if let exact = all.first(where: { $0.name.lowercased() == q || $0.id == query }) { return exact }
        let partial = all.filter { $0.name.lowercased().contains(q) }
        if partial.count == 1 { return partial[0] }
        let kind: String? = ["pc", "computer", "desktop", "电脑", "mac", "windows"].contains(q) ? "computer" : (["phone", "手机"].contains(q) ? "phone" : nil)
        if let kind { let same = all.filter { $0.online && $0.kind == kind }; return same.count == 1 ? same[0] : nil }
        return nil
    }

    // Calls in -----------------------------------------------------------------------------

    private func incoming(_ frame: [String: Any]) {
        guard let id = frame["id"] as? String else { return }
        let action = frame["action"] as? String ?? ""
        let args = frame["args"] as? [String: Any] ?? [:]
        let from = (frame["from"] as? [String: Any])?["name"] as? String ?? "another device"

        if action == "info" { reply(id, body: info()); return }
        guard remoteControl else { refuse(id, "not_allowed", "\(name) is set not to be operated from other devices"); return }
        switch action {
        case "open":
            guard let raw = (args["url"] as? String)?.trimmingCharacters(in: .whitespaces), let url = URL(string: raw) else { refuse(id, "usage", "a URL is required"); return }
            // Web pages only: another device must not dial numbers, start FaceTime or drive
            // other apps' URL schemes on this phone through the hub.
            guard let scheme = url.scheme?.lowercased(), scheme == "http" || scheme == "https" else {
                refuse(id, "usage", "only http and https links are opened on this iPhone")
                return
            }
            UIApplication.shared.open(url) { ok in
                Task { @MainActor in
                    if ok {
                        self.reply(id, body: ["ok": true, "url": raw])
                    } else {
                        self.refuse(id, "not_opened", "this iPhone did not open \(raw): nothing handles it, or nanoMuse is not in the foreground")
                    }
                }
            }
        case "notify":
            guard let text = args["text"] as? String, !text.isEmpty else { refuse(id, "usage", "text is required"); return }
            let title = (args["title"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? "nanoMuse"
            notify(title: title, text: text, from: from) { ok in
                Task { @MainActor in self.reply(id, body: ["ok": ok, "shown": ok]) }
            }
        case "screen":
            refuse(id, "no_screen", "this iPhone cannot be screenshotted from another device")
        case "task":
            // "@iPhone …" from another device: this phone's Muse does it (NanoMuseHubTasks).
            let sender = frame["from"] as? [String: Any] ?? [:]
            Task { @MainActor [weak self] in
                let outcome = await NanoMuseHubTasks.run(callId: id, args: args, from: sender) { [weak self] body in
                    self?.event(id, body: body)
                }
                switch outcome {
                case .result(let body): self?.reply(id, body: body)
                case .failure(let code, let message): self?.refuse(id, code, message)
                }
            }
        case "stop":
            let sender = frame["from"] as? [String: Any] ?? [:]
            reply(id, body: ["stopped": NanoMuseHubTasks.stop(args: args, from: sender)])
        case "shell", "files", "file.get", "file.put", "approve":
            refuse(id, "not_supported", "nanoMuse on iOS does not do '\(action)' for other devices yet; ask on the phone itself")
        default:
            refuse(id, "unknown_action", "this iPhone does not do '\(action)'")
        }
    }

    private func reply(_ id: String, body: [String: Any]) {
        send(["type": "result", "id": id, "ok": true, "body": body])
    }

    private func refuse(_ id: String, _ code: String, _ message: String) {
        send(["type": "result", "id": id, "ok": false, "error": code, "message": message])
    }

    /// Progress on a call still running (`{"type":"event","id","body"}`, docs/hub.md).
    private func event(_ id: String, body: [String: Any]) {
        send(["type": "event", "id": id, "body": body])
    }

    private func info() -> [String: Any] {
        [
            "name": name,
            "os": "iOS \(UIDevice.current.systemVersion)",
            "model": UIDevice.current.model,
            "app": "nanoMuse \(Self.version)",
            "actions": Self.actions,
            "note": "iOS answers info, open, notify and task (its Muse runs the task while nanoMuse is open); no shell, files or screen",
        ]
    }

    private func notify(title: String, text: String, from: String, done: @escaping @Sendable (Bool) -> Void) {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { granted, _ in
            guard granted else { done(false); return }
            let content = UNMutableNotificationContent()
            content.title = title
            content.body = text
            content.subtitle = from
            content.sound = .default
            let request = UNNotificationRequest(identifier: "nanomuse.hub.\(UUID().uuidString)", content: content, trigger: nil)
            UNUserNotificationCenter.current().add(request) { error in done(error == nil) }
        }
    }
}
