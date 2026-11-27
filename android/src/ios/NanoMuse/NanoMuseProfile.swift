//
//  NanoMuseProfile.swift
//  nanoMuse
//
//  The relay side of the agent's look: pictures drawn through nanoMuse
//  Cloud (/v1/images/*), what a new face would cost (/v1/estimate), and
//  the profile the account's devices share (/v1/me/profile). Android:
//  cloud/ProfileSync.kt, cloud/FaceCost.kt, avatar/ImageGen.kt.
//

import Foundation
import UIKit

// MARK: - Relay media calls

/// Raw relay requests that `NanoMuseCloud.call` (JSON in, JSON out, 30 s)
/// does not cover: picture generation takes a minute and edits are
/// multipart.
enum NanoMuseRelayMedia {
    struct Estimate: Equatable {
        var cny: Double
        var leftCny: Double?
        var unlimited: Bool
        var affordable: Bool
        var inviteBonusCny: Double?
    }

    private static let session: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 180
        config.timeoutIntervalForResource = 300
        return URLSession(configuration: config)
    }()

    @MainActor
    private static func authorized(_ method: String, _ path: String) throws -> URLRequest {
        guard let key = NanoMuseCloud.apiKey else {
            throw NanoMuseCloudError(code: "signed_out", message: AppLocalized("Sign in to nanoMuse Cloud first."), status: 401)
        }
        guard let url = URL(string: NanoMuseCloud.baseURL + path) else {
            throw NanoMuseCloudError(code: "bad_base", message: "Bad relay address", status: 0)
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0"
        request.setValue("nanoMuse-iOS/\(version)", forHTTPHeaderField: "User-Agent")
        return request
    }

    private static func perform(_ request: URLRequest) async throws -> [String: Any] {
        let result: (Data, URLResponse)
        do {
            result = try await session.data(for: request)
        } catch {
            throw NanoMuseCloudError(code: "unreachable", message: error.localizedDescription, status: 0)
        }
        let (data, response) = result
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
        if (200..<300).contains(status) { return object ?? [:] }
        let err = object?["error"] as? [String: Any]
        let code = (err?["code"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? "http_\(status)"
        let message = (err?["message"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? "HTTP \(status)"
        throw NanoMuseCloudError(code: code, message: message, status: status)
    }

    /// The relay's image model: the first the menu lists with image output.
    @MainActor
    static func imageModel() async throws -> String {
        let request = try authorized("GET", "/v1/models")
        let reply = try await perform(request)
        let models = reply["data"] as? [[String: Any]] ?? []
        for model in models {
            let arch = model["architecture"] as? [String: Any]
            let outputs = arch?["output_modalities"] as? [String] ?? []
            let kind = (model["nanomuse"] as? [String: Any])?["kind"] as? String
            if outputs.contains("image") || kind == "image", let id = model["id"] as? String, !id.isEmpty, NanoMuseRelayMenu.allows(.image, at: NanoMuseCloud.baseURL, model: id) {
                return id
            }
        }
        throw NanoMuseCloudError(code: "model_not_offered", message: AppLocalized("nanoMuse Cloud offers no image model right now."), status: 404)
    }

    @MainActor
    static func estimate(images: Int, clips: Int = 0) async throws -> Estimate {
        let request = try authorized("GET", "/v1/estimate?images=\(images)&clips=\(clips)")
        let reply = try await perform(request)
        func num(_ key: String) -> Double? {
            if let d = reply[key] as? Double { return d }
            if let i = reply[key] as? Int { return Double(i) }
            if let s = reply[key] as? String { return Double(s) }
            return nil
        }
        let unlimited = (reply["unlimited"] as? Bool) ?? false
        return Estimate(
            cny: num("cny") ?? 0,
            leftCny: unlimited ? nil : num("left_cny"),
            unlimited: unlimited,
            affordable: (reply["affordable"] as? Bool) ?? true,
            inviteBonusCny: num("invite_bonus_cny")
        )
    }

    /// One picture from a prompt, as the decoded image.
    @MainActor
    static func generate(prompt: String, model: String, size: String = "1024*1024") async throws -> UIImage {
        var request = try authorized("POST", "/v1/images/generations")
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: [
            "model": model, "prompt": prompt, "n": 1, "size": size,
        ])
        return try await decodeImage(try await perform(request))
    }

    /// The picture posed again (a new mood of the same face).
    @MainActor
    static func edit(_ image: UIImage, prompt: String, model: String, size: String = "1024*1024") async throws -> UIImage {
        var request = try authorized("POST", "/v1/images/edits")
        let boundary = "nanomuse-" + UUID().uuidString
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        guard let png = NanoMuseFaceStore.square(image, side: 768).pngData() else {
            throw NanoMuseCloudError(code: "bad_image", message: "The picture could not be encoded", status: 0)
        }
        var body = Data()
        func field(_ name: String, _ value: String) {
            body.append("--\(boundary)\r\n".data(using: .utf8)!)
            body.append("Content-Disposition: form-data; name=\"\(name)\"\r\n\r\n".data(using: .utf8)!)
            body.append(value.data(using: .utf8)!)
            body.append("\r\n".data(using: .utf8)!)
        }
        field("model", model)
        field("prompt", prompt)
        field("n", "1")
        field("size", size)
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"image\"; filename=\"face.png\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: image/png\r\n\r\n".data(using: .utf8)!)
        body.append(png)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
        request.httpBody = body
        return try await decodeImage(try await perform(request))
    }

    private static func decodeImage(_ reply: [String: Any]) async throws -> UIImage {
        let data = reply["data"] as? [[String: Any]] ?? []
        guard let first = data.first else {
            throw NanoMuseCloudError(code: "bad_reply", message: "The relay sent no picture", status: 0)
        }
        if let b64 = first["b64_json"] as? String, let bytes = Data(base64Encoded: b64), let image = UIImage(data: bytes) {
            return image
        }
        if let urlString = first["url"] as? String, let url = URL(string: urlString) {
            let (bytes, _) = try await session.data(from: url)
            if let image = UIImage(data: bytes) { return image }
        }
        throw NanoMuseCloudError(code: "bad_reply", message: "The relay sent a picture that could not be read", status: 0)
    }

    // MARK: Profile

    struct Profile {
        var rev: Int
        var name: String
        var avatar: String
        /// The emoji look's glyph and `#rrggbb` (#435); empty unless `avatar` is `emoji`.
        var emoji: String
        var color: String
        var style: String
        var description: String
        var faceId: String
        var hasFace: Bool
        var face: [String: String]?
        /// Contract C3: which device of the account connected what (raw entries).
        var connectors: [[String: Any]]
        /// The face's short clips as the relay holds them (relay 0.29): mood -> `{sha256, mime, bytes}`.
        var clips: [String: [String: Any]] = [:]
    }

    @MainActor
    static func profile(withFace: Bool) async throws -> Profile {
        let request = try authorized("GET", "/v1/me/profile?face=\(withFace ? "true" : "false")")
        let reply = try await perform(request)
        return Profile(
            rev: (reply["rev"] as? Int) ?? Int((reply["rev"] as? Double) ?? 0),
            name: reply["name"] as? String ?? "",
            avatar: reply["avatar"] as? String ?? "",
            emoji: reply["emoji"] as? String ?? "",
            color: reply["color"] as? String ?? "",
            style: reply["style"] as? String ?? "",
            description: reply["description"] as? String ?? "",
            faceId: reply["face_id"] as? String ?? "",
            hasFace: (reply["has_face"] as? Bool) ?? (reply["face"] != nil && !(reply["face"] is NSNull)),
            face: reply["face"] as? [String: String],
            connectors: reply["connectors"] as? [[String: Any]] ?? [],
            clips: reply["clips"] as? [String: [String: Any]] ?? [:]
        )
    }

    /// Writes the look. `face` nil keeps the pictures the relay has; an
    /// empty map is not allowed, so a reset sends `avatar: "dragon"` with
    /// `face: NSNull()`.
    @MainActor
    @discardableResult
    static func putProfile(_ body: [String: Any]) async throws -> Int {
        var request = try authorized("PUT", "/v1/me/profile")
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        var payload = body
        // the writing device's id, as the hub's hello says it (contract C3): the relay replaces
        // only the connectors whose `device_id` is this one, and refuses entries naming another
        payload["device"] = NanoMuseHub.shared.deviceId
        request.httpBody = try JSONSerialization.data(withJSONObject: payload)
        let reply = try await perform(request)
        // the reply is the merged profile: the other devices' connections, fresh
        NanoMuseSharedConnectors.shared.absorb(reply)
        return (reply["rev"] as? Int) ?? Int((reply["rev"] as? Double) ?? 0)
    }

    // MARK: Data controls

    struct Contribute: Equatable {
        var on: Bool
        var samples: Int
        var defaultOn: Bool
        var privacyURL: String
        /// The account's record on this relay (relay 0.29); nil from an older relay.
        var record: Record?
    }

    /// `contribute.record` of `/v1/me`: what the relay keeps of the account's turns in full
    /// (Android: `NanoMuseCloud.Record`).
    struct Record: Equatable {
        var on: Bool
        var turns: Int
        /// Turns answered on the person's own key and added by the app.
        var own: Int
        var files: Int
        var mediaBytes: Int64
        /// 0: kept until deleted.
        var keepDays: Int
    }

    /// What `DELETE /v1/me/samples` removed: the training turns, the record's turns, the files.
    struct Deleted: Equatable {
        var samples: Int
        var turns: Int
        var files: Int
    }

    @MainActor
    static func setContribute(_ on: Bool) async throws -> Contribute {
        var request = try authorized("POST", "/v1/me/contribute")
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: ["on": on])
        return parseContribute(try await perform(request))
    }

    @MainActor
    static func contribute() async throws -> Contribute {
        let request = try authorized("GET", "/v1/me")
        let reply = try await perform(request)
        let block = reply["contribute"] as? [String: Any] ?? [:]
        return parseContribute(block)
    }

    @MainActor
    static func deleteSamples() async throws -> Deleted {
        let request = try authorized("DELETE", "/v1/me/samples")
        let reply = try await perform(request)
        return Deleted(samples: int(reply["deleted"]), turns: int(reply["turns"]), files: int(reply["files"]))
    }

    private static func int(_ value: Any?) -> Int {
        if let n = value as? NSNumber { return n.intValue }
        if let s = value as? String { return Int(s) ?? 0 }
        return 0
    }

    private static func parseContribute(_ d: [String: Any]) -> Contribute {
        var record: Record?
        if let r = d["record"] as? [String: Any] {
            record = Record(
                on: (r["on"] as? Bool) ?? false,
                turns: int(r["turns"]), own: int(r["own"]), files: int(r["files"]),
                mediaBytes: (r["media_bytes"] as? NSNumber)?.int64Value ?? 0,
                keepDays: int(r["keep_days"])
            )
        }
        return Contribute(
            on: (d["on"] as? Bool) ?? false,
            samples: int(d["samples"]),
            defaultOn: (d["default_on"] as? Bool) ?? false,
            privacyURL: d["privacy_url"] as? String ?? "",
            record: record
        )
    }

    // MARK: The record (relay 0.29): files by hash, turns answered on the person's own key

    /// Whether the relay already has the file (`HEAD /v1/blobs/<sha256>`).
    @MainActor
    static func hasBlob(_ sha256: String) async throws -> Bool {
        let request = try authorized("HEAD", "/v1/blobs/\(sha256)")
        let (_, response) = try await raw(request, accept: [200, 404])
        return response.statusCode == 200
    }

    /// Puts the file; the relay checks the hash. Idempotent.
    @MainActor
    static func putBlob(_ sha256: String, mime: String, data: Data) async throws {
        var request = try authorized("PUT", "/v1/blobs/\(sha256)")
        request.setValue(mime, forHTTPHeaderField: "Content-Type")
        request.httpBody = data
        _ = try await perform(request)
    }

    /// The file back, with its type; nil when the relay has no such file for this account.
    @MainActor
    static func getBlob(_ sha256: String) async throws -> (mime: String, data: Data)? {
        let request = try authorized("GET", "/v1/blobs/\(sha256)")
        let (data, response) = try await raw(request, accept: [200, 404])
        guard response.statusCode == 200 else { return nil }
        return (response.value(forHTTPHeaderField: "Content-Type") ?? "application/octet-stream", data)
    }

    /// One finished turn answered on the person's own key, into the account's record
    /// (`POST /v1/turns`; docs/cloud.md "The record"). Files it names must be put first.
    @MainActor
    static func postTurn(_ turn: [String: Any]) async throws {
        var request = try authorized("POST", "/v1/turns")
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.setValue(NanoMuseHub.shared.deviceId, forHTTPHeaderField: NanoMuseCloudHeaders.device)
        request.setValue(NanoMuseProvenance.platform, forHTTPHeaderField: NanoMuseProvenance.platformHeader)
        request.httpBody = try JSONSerialization.data(withJSONObject: turn)
        _ = try await perform(request)
    }

    /// A batch of client events, codes about turns (`POST /v1/events`; docs/cloud.md "Client
    /// events"): a hundred at most, the device and the platform in the headers.
    @MainActor
    static func postEvents(_ events: [[String: Any]]) async throws {
        var request = try authorized("POST", "/v1/events")
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.setValue(NanoMuseHub.shared.deviceId, forHTTPHeaderField: NanoMuseCloudHeaders.device)
        request.setValue(NanoMuseProvenance.platform, forHTTPHeaderField: NanoMuseProvenance.platformHeader)
        request.httpBody = try JSONSerialization.data(withJSONObject: ["events": events])
        _ = try await perform(request)
    }

    /// A request whose answer is bytes, not JSON; statuses outside `accept` are relay errors.
    private static func raw(_ request: URLRequest, accept: Set<Int>) async throws -> (Data, HTTPURLResponse) {
        let result: (Data, URLResponse)
        do {
            result = try await session.data(for: request)
        } catch {
            throw NanoMuseCloudError(code: "unreachable", message: error.localizedDescription, status: 0)
        }
        guard let response = result.1 as? HTTPURLResponse else {
            throw NanoMuseCloudError(code: "bad_reply", message: "No HTTP response", status: 0)
        }
        if accept.contains(response.statusCode) { return (result.0, response) }
        let object = (try? JSONSerialization.jsonObject(with: result.0)) as? [String: Any]
        let err = object?["error"] as? [String: Any]
        let code = (err?["code"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? "http_\(response.statusCode)"
        let message = (err?["message"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? "HTTP \(response.statusCode)"
        throw NanoMuseCloudError(code: code, message: message, status: response.statusCode)
    }
}

// MARK: - Profile sync

/// Keeps the face — and, contract C8, the name — this phone wears in step
/// with the account: pulls the profile when the app starts or the hub says
/// another device wrote it, pushes after the studio adopted or reset a face
/// and a moment after the name changed (Settings, the naming card, the model
/// through minis-config — every write goes through `SoulStore.save`).
@MainActor
final class NanoMuseProfileSync: ObservableObject {
    static let shared = NanoMuseProfileSync()

    private enum Keys {
        static let rev = "nanomuse.profile.rev"
        static let pushedConnectors = "nanomuse.profile.pushed_connectors"
        /// The name the relay last heard from or gave this phone (Android: `KEY_PUSHED_NAME`).
        /// A local name that differs from it is a rename not yet pushed, and a pull must not undo it.
        static let pushedName = "nanomuse.profile.pushed_name"
        /// The face's clips as the relay has them, mood -> {sha256, mime, bytes} (relay 0.29), so a
        /// clip shared from here is added to the others', not sent in their place.
        static let clips = "nanomuse.profile.clips"
    }

    /// Android's `PUSH_DELAY_MS`: a rename is pushed once the typing has settled.
    private static let nameDelay: UInt64 = 2_000_000_000

    @Published private(set) var syncing = false
    @Published private(set) var lastError: String?

    private var pulling = false
    /// The account the pull or push in flight is for (`NanoMuseAccountData.current`). A reply that
    /// lands after the phone moved to another account, or signed out, is dropped: it would write
    /// account A's name, face and connections over B's (Android: `ProfileSync.accountOf`).
    private var who: String { NanoMuseAccountData.shared.current }
    /// True while a pulled name is being written to SOUL.md, so the write does not push itself back.
    private var applying = false
    private var namePush: Task<Void, Never>?
    private var soulObserver: NSObjectProtocol?
    private var foregroundObserver: NSObjectProtocol?

    private init() {}

    /// Called once from the app root.
    func start() {
        NanoMuseSharedConnectors.shared.watch()
        if soulObserver == nil {
            soulObserver = NotificationCenter.default.addObserver(forName: .soulMdChanged, object: nil, queue: .main) { [weak self] _ in
                Task { @MainActor in self?.nameChanged() }
            }
        }
        if foregroundObserver == nil {
            // The hub's `profile` frame is missed while the app is in the background; a pull on
            // the way back to the front picks up a name or a face the other device wrote
            // meanwhile, instead of waiting for the next cold start (Android does the same).
            foregroundObserver = NotificationCenter.default.addObserver(forName: UIApplication.didBecomeActiveNotification, object: nil, queue: .main) { [weak self] _ in
                Task { @MainActor in self?.pull() }
            }
        }
        pull()
    }

    /// The name SOUL.md carries, or nothing for the default.
    private static var localName: String {
        let name = SoulStore.cachedMetadata.name.trimmingCharacters(in: .whitespacesAndNewlines)
        return name == SoulMetadata.default.name ? "" : name
    }

    private static var pushedName: String? {
        get { UserDefaults.standard.string(forKey: Keys.pushedName) }
        set { UserDefaults.standard.set(newValue, forKey: Keys.pushedName) }
    }

    /// A relay name lands in SOUL.md (C8: the name follows the account). Skipped when this
    /// phone renamed after its last push — that rename is about to go up and wins.
    private func apply(remoteName: String) {
        let remote = remoteName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !remote.isEmpty, remote.count <= 60 else { return }
        let local = Self.localName
        if remote == local {
            Self.pushedName = remote
            return
        }
        if let pushed = Self.pushedName, !local.isEmpty, local != pushed {
            // renamed here since the last push: ours is newer than what the relay shows
            return
        }
        applying = true
        defer { applying = false }
        var file = SoulStore.load() ?? SoulMDParser.parse(SoulStore.defaultContent)
        file.metadata.name = remote
        try? SoulStore.save(file)
        Self.pushedName = remote
    }

    /// The hub heard `{"type":"profile","rev":N}` from another device.
    func onHubFrame(_ frame: [String: Any]) {
        let rev = (frame["rev"] as? Int) ?? Int((frame["rev"] as? Double) ?? 0)
        if rev > UserDefaults.standard.integer(forKey: Keys.rev) {
            pull()
        }
    }

    func pull() {
        guard NanoMuseCloud.isSignedIn, !pulling else { return }
        pulling = true
        let forAccount = who
        Task { @MainActor [self] in
            defer { pulling = false }
            do {
                let head = try await NanoMuseRelayMedia.profile(withFace: false)
                guard forAccount == who else { return }
                let known = UserDefaults.standard.integer(forKey: Keys.rev)
                // the other devices' connections come with every read, whatever the rev
                NanoMuseSharedConnectors.shared.absorb(["connectors": head.connectors])
                if head.rev <= known, head.rev > 0 || known > 0 {
                    // the look is current; this phone's connections — or a rename — may still be unsaid
                    if NanoMuseSharedConnectors.shared.stamp() != UserDefaults.standard.string(forKey: Keys.pushedConnectors) {
                        connectorsChanged()
                    } else {
                        nameChanged()
                    }
                    return
                }
                if head.rev == 0, known == 0 {
                    // the relay has nothing for this account yet: the face this phone wears, its
                    // connections and its name (when it has one) seed it, as Android does
                    if NanoMuseFaceStore.shared.hasCustomFace {
                        faceChanged()
                    } else if !NanoMuseSharedConnectors.shared.mine().isEmpty {
                        connectorsChanged()
                    } else if !Self.localName.isEmpty {
                        nameChanged(now: true)
                    }
                }
                // C8: the account's name, before the pictures — a rename elsewhere is often all that moved
                if head.rev > 0 { apply(remoteName: head.name) }
                let store = NanoMuseFaceStore.shared
                if head.avatar == "emoji" {
                    // An emoji on a colour, set on the desktop or in the web console (#435):
                    // worn in place of a drawn face, as a remote dragon takes one off.
                    store.wear(emoji: NanoMuseEmojiLook(emoji: head.emoji, color: head.color))
                } else if head.hasFace {
                    if head.faceId == store.meta.faceId && store.hasCustomFace {
                        UserDefaults.standard.set(head.rev, forKey: Keys.rev)
                        // the same face; another device may have drawn a clip of it since
                        remember(clips: head.clips)
                        await adoptClips(head.clips, forAccount: forAccount)
                        return
                    }
                    let full = try await NanoMuseRelayMedia.profile(withFace: true)
                    guard forAccount == who else { return }
                    var stills: [NanoMuseMood: UIImage] = [:]
                    for (key, b64) in full.face ?? [:] {
                        if let mood = NanoMuseMood(rawValue: key), let bytes = Data(base64Encoded: b64), let img = UIImage(data: bytes) {
                            stills[mood] = img
                        }
                    }
                    if stills[.idle] != nil {
                        store.wear(remote: stills, faceId: full.faceId, description: full.description, style: full.style)
                        // the clips travel with the face (relay 0.29): the ones another device drew come
                        // down as files; whatever mood is still missing is drawn here when enabled
                        remember(clips: full.clips)
                        await adoptClips(full.clips, forAccount: forAccount)
                        NanoMuseAvatarMotion.shared.animateIfEnabled()
                    }
                } else if head.rev > 0, store.source != .dragon {
                    // Another device went back to the dragon: the drawn face or the emoji look goes.
                    store.reset(sync: false)
                    remember(clips: [:])
                } else {
                    remember(clips: [:])
                }
                UserDefaults.standard.set(head.rev, forKey: Keys.rev)
                lastError = nil
            } catch {
                guard forAccount == who else { return }
                lastError = NanoMuseCloud.describe(error)
            }
        }
    }

    /// The face on this phone changed: push it.
    func faceChanged() {
        guard NanoMuseCloud.isSignedIn else { return }
        syncing = true
        let forAccount = who
        Task { @MainActor [self] in
            defer { syncing = false }
            do {
                let store = NanoMuseFaceStore.shared
                var body: [String: Any] = [:]
                if store.hasCustomFace {
                    var face: [String: String] = [:]
                    for mood in NanoMuseMood.allCases {
                        if let img = store.custom[mood], let bytes = NanoMuseFaceStore.encodeStill(img) {
                            face[mood.rawValue] = bytes.base64EncodedString()
                        }
                    }
                    body["avatar"] = "face"
                    body["face"] = face
                    body["description"] = store.meta.description
                    body["style"] = store.meta.style
                } else if let look = store.emojiLook {
                    // An emoji look is another device's choice (#435): this phone says it
                    // back as it is, never the dragon over it.
                    body["avatar"] = "emoji"
                    body["emoji"] = look.emoji
                    body["color"] = look.color
                    body["face"] = NSNull()
                } else {
                    body["avatar"] = "dragon"
                    body["face"] = NSNull()
                }
                let name = Self.localName
                if !name.isEmpty { body["name"] = String(name.prefix(60)) }
                let mine = NanoMuseSharedConnectors.shared.mine()
                body["connectors"] = mine
                let rev = try await NanoMuseRelayMedia.putProfile(body)
                guard forAccount == who else { return }
                UserDefaults.standard.set(rev, forKey: Keys.rev)
                UserDefaults.standard.set(NanoMuseSharedConnectors.stamp(mine), forKey: Keys.pushedConnectors)
                if !name.isEmpty { Self.pushedName = name }
                // the relay dropped the old face's clips with the face; the ones here are the new face's
                remember(clips: [:])
                if store.hasCustomFace {
                    for (mood, url) in NanoMuseAvatarMotion.shared.clips {
                        if let bytes = try? Data(contentsOf: url) { shareClip(mood, bytes: bytes) }
                    }
                }
                lastError = nil
            } catch {
                guard forAccount == who else { return }
                lastError = NanoMuseCloud.describe(error)
            }
        }
    }

    // MARK: Clips (relay 0.29): the face's short videos travel with it as files

    private func remember(clips: [String: [String: Any]]) {
        if clips.isEmpty {
            UserDefaults.standard.removeObject(forKey: Keys.clips)
        } else if let data = try? JSONSerialization.data(withJSONObject: clips) {
            UserDefaults.standard.set(data, forKey: Keys.clips)
        }
    }

    private func rememberedClips() -> [String: [String: Any]] {
        guard let data = UserDefaults.standard.data(forKey: Keys.clips),
              let map = (try? JSONSerialization.jsonObject(with: data)) as? [String: [String: Any]] else { return [:] }
        return map
    }

    private static let sha256Pattern = try? NSRegularExpression(pattern: "^[0-9a-f]{64}$")

    /// The clips the profile names, down to this phone's motion folder: a mood whose file is
    /// already here is left alone; a file whose hash is not the one named is dropped.
    private func adoptClips(_ clips: [String: [String: Any]], forAccount: String) async {
        let motion = NanoMuseAvatarMotion.shared
        var landed = false
        for (key, ref) in clips {
            guard let mood = NanoMuseMood(rawValue: key), NanoMuseAvatarMotion.animated.contains(mood),
                  let sha = ref["sha256"] as? String,
                  Self.sha256Pattern?.firstMatch(in: sha, range: NSRange(sha.startIndex..., in: sha)) != nil else { continue }
            if motion.clips[mood] != nil { continue }
            guard let got = try? await NanoMuseRelayMedia.getBlob(sha), forAccount == who else { continue }
            guard got.mime.hasPrefix("video/") || (ref["mime"] as? String) == got.mime, NanoMuseOwnTurns.sha256(got.data) == sha else { continue }
            let fm = FileManager.default
            try? fm.createDirectory(at: NanoMuseAvatarMotion.directory, withIntermediateDirectories: true)
            let tmp = NanoMuseAvatarMotion.directory.appendingPathComponent("\(mood.rawValue).part")
            do {
                try got.data.write(to: tmp, options: .atomic)
                let dst = NanoMuseAvatarMotion.clipFile(mood)
                try? fm.removeItem(at: dst)
                try fm.moveItem(at: tmp, to: dst)
                landed = true
            } catch {
                try? fm.removeItem(at: tmp)
            }
        }
        if landed { motion.clipLanded() }
    }

    /// A clip this phone drew (or had before signing in) goes up for the account's other
    /// devices: the file first, then the profile's `clips`, this one added to the others'.
    /// Only while signed in, wearing the face, on a relay that keeps the account's files.
    func shareClip(_ mood: NanoMuseMood, bytes: Data) {
        guard NanoMuseCloud.isSignedIn, NanoMuseCloud.account?.recordOn == true,
              NanoMuseFaceStore.shared.hasCustomFace, NanoMuseAvatarMotion.animated.contains(mood) else { return }
        let forAccount = who
        let faceId = NanoMuseFaceStore.shared.meta.faceId
        let sha = NanoMuseOwnTurns.sha256(bytes)
        Task { @MainActor [self] in
            do {
                if !(try await NanoMuseRelayMedia.hasBlob(sha)) {
                    try await NanoMuseRelayMedia.putBlob(sha, mime: "video/mp4", data: bytes)
                }
                // the face changed hands or changed while the file went up: the clip is not its
                guard forAccount == who, NanoMuseFaceStore.shared.meta.faceId == faceId else { return }
                var clips = rememberedClips()
                clips[mood.rawValue] = ["sha256": sha, "mime": "video/mp4", "bytes": bytes.count]
                let rev = try await NanoMuseRelayMedia.putProfile(["avatar": "face", "clips": clips])
                guard forAccount == who else { return }
                UserDefaults.standard.set(rev, forKey: Keys.rev)
                remember(clips: clips)
            } catch {
                guard forAccount == who else { return }
                lastError = NanoMuseCloud.describe(error)
            }
        }
    }

    /// The agent's name changed on this phone (C8): the account hears it a moment later, with
    /// the face as "keep what you have" and this phone's connectors, like `connectorsChanged`.
    /// A no-op when the relay already has this name; `now` skips the wait (the seeding pull).
    func nameChanged(now: Bool = false) {
        guard NanoMuseCloud.isSignedIn, !applying else { return }
        let name = Self.localName
        guard !name.isEmpty, name != Self.pushedName else { return }
        namePush?.cancel()
        namePush = Task { @MainActor [weak self] in
            if !now {
                try? await Task.sleep(nanoseconds: NanoMuseProfileSync.nameDelay)
                guard !Task.isCancelled else { return }
            }
            await self?.pushKeepingFace()
        }
    }

    /// What this phone connected changed (contract C3): tell the account. The face
    /// is sent as "keep what you have" — `avatar: "face"` without pictures.
    func connectorsChanged() {
        guard NanoMuseCloud.isSignedIn else { return }
        let mine = NanoMuseSharedConnectors.shared.mine()
        let stamp = NanoMuseSharedConnectors.stamp(mine)
        guard stamp != UserDefaults.standard.string(forKey: Keys.pushedConnectors) || UserDefaults.standard.string(forKey: Keys.pushedConnectors) == nil else { return }
        Task { @MainActor [self] in
            await pushKeepingFace()
        }
    }

    /// One PUT with the name and the connectors, the face left as the relay has it.
    private func pushKeepingFace() async {
        guard NanoMuseCloud.isSignedIn else { return }
        let forAccount = who
        let mine = NanoMuseSharedConnectors.shared.mine()
        let stamp = NanoMuseSharedConnectors.stamp(mine)
        let name = Self.localName
        do {
            let store = NanoMuseFaceStore.shared
            var body: [String: Any] = ["connectors": mine]
            if store.hasCustomFace {
                body["avatar"] = "face"
                body["description"] = store.meta.description
                body["style"] = store.meta.style
            }
            // Without a face of its own this phone says nothing about the look: the relay keeps
            // what it has (relay 0.25), an emoji look another device set included (#435). Sending
            // the dragon here took the account's face off every other device whenever a phone
            // renamed the muse before its first pull had landed.
            if !name.isEmpty { body["name"] = String(name.prefix(60)) }
            let rev = try await NanoMuseRelayMedia.putProfile(body)
            guard forAccount == who else { return }
            UserDefaults.standard.set(rev, forKey: Keys.rev)
            UserDefaults.standard.set(stamp, forKey: Keys.pushedConnectors)
            if !name.isEmpty { Self.pushedName = name }
            lastError = nil
        } catch {
            guard forAccount == who else { return }
            lastError = NanoMuseCloud.describe(error)
        }
    }

    /// Signed out, or another account signed in: the cursors (`rev`, what was pushed) were the
    /// account's that left, and another account's devices are not ours to list. Without this a
    /// second account's first pull compared the relay's `rev` with the first account's and
    /// skipped its name and face.
    func forget() {
        NanoMuseSharedConnectors.shared.forget()
        namePush?.cancel()
        UserDefaults.standard.removeObject(forKey: Keys.rev)
        UserDefaults.standard.removeObject(forKey: Keys.pushedConnectors)
        UserDefaults.standard.removeObject(forKey: Keys.pushedName)
        UserDefaults.standard.removeObject(forKey: Keys.clips)
    }
}
