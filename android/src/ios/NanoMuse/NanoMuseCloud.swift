import Foundation
import UIKit

/// nanoMuse Cloud: the "start now" path. A phone number or an e-mail address, a code, and the
/// app has a provider with a starter allowance — no key of one's own needed. The server is the
/// relay in `cloud/` of the repository; anyone can run one, and a debug build can be pointed at
/// a different one.
///
/// To the rest of the app the relay is an ordinary OpenAI-compatible provider: an API-key
/// `ProviderInstance` on the relay's base URL, whose key is the `nm_…` token the relay issued.
/// Chat and model listing go through the paths that already exist for any custom base URL.
/// What this type adds is the sign-in itself, the provisioning of that instance (models
/// fetched, a default group) and the account meta the settings page shows (how much is left).
///
/// What the relay keeps about a person is the hashed identifier and token counts; message
/// content is forwarded to the model, not stored. See `docs/cloud.md`.
///
/// Mirror of `io.github.nanomuse.cloud.NanoMuseCloud` on Android; the wire format is the same.
/// What the settings page shows. Cached from the last `/v1/me` (or the sign-in itself).
struct NanoMuseCloudAccount: Codable, Equatable, Sendable {
    var channel: String
    var hint: String
    var granted: Int64
    var used: Int64
    var usedToday: Int64
    var dailyCap: Int64
    var checkedAt: Date
    /// The relay runs without a ceiling: usage is shown, nothing is refused for lack of tokens.
    var unlimited: Bool = false

    var remaining: Int64 { max(granted - used, 0) }
    /// 0..1 of the grant still unspent.
    var fraction: Double {
        guard granted > 0 else { return 0 }
        return min(max(Double(remaining) / Double(granted), 0), 1)
    }

    init(channel: String, hint: String, granted: Int64, used: Int64, usedToday: Int64, dailyCap: Int64, checkedAt: Date, unlimited: Bool = false) {
        self.channel = channel
        self.hint = hint
        self.granted = granted
        self.used = used
        self.usedToday = usedToday
        self.dailyCap = dailyCap
        self.checkedAt = checkedAt
        self.unlimited = unlimited
    }

    // `unlimited` came later; an account cached by an earlier build decodes without it.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        channel = try c.decode(String.self, forKey: .channel)
        hint = try c.decode(String.self, forKey: .hint)
        granted = try c.decode(Int64.self, forKey: .granted)
        used = try c.decode(Int64.self, forKey: .used)
        usedToday = try c.decode(Int64.self, forKey: .usedToday)
        dailyCap = try c.decode(Int64.self, forKey: .dailyCap)
        checkedAt = try c.decode(Date.self, forKey: .checkedAt)
        unlimited = try c.decodeIfPresent(Bool.self, forKey: .unlimited) ?? false
    }
}

/// The relay's stable error codes (`docs/cloud.md`), or `unreachable` / `http_<status>`.
struct NanoMuseCloudError: LocalizedError, Sendable {
    let code: String
    let message: String
    let status: Int

    var errorDescription: String? { NanoMuseCloud.describe(self) }
}

@MainActor
enum NanoMuseCloud {
    static let defaultBase = "https://cloud.nanomuse.cn"
    static let label = "nanoMuse Cloud"

    private enum Keys {
        static let base = "nanomuse.cloud.base"
        static let instance = "nanomuse.cloud.instance_id"
        static let account = "nanomuse.cloud.account"
    }

    typealias Account = NanoMuseCloudAccount
    typealias CloudError = NanoMuseCloudError

    // MARK: - State

    /// The person may point the app at another relay (a self-hosted one, or a
    /// laptop on the same Wi-Fi); the default stays the hosted one when unset.
    static var canOverrideBase: Bool { true }

    /// The relay this build talks to.
    static var baseURL: String {
        if let custom = UserDefaults.standard.string(forKey: Keys.base)?.trimmingCharacters(in: .whitespacesAndNewlines),
           !custom.isEmpty {
            return trimSlash(custom)
        }
        return defaultBase
    }

    static func setBaseURL(_ url: String?) {
        let trimmed = url?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if trimmed.isEmpty {
            UserDefaults.standard.removeObject(forKey: Keys.base)
        } else {
            UserDefaults.standard.set(trimSlash(trimmed), forKey: Keys.base)
        }
    }

    /// The provider instance the relay is signed in as, if it still exists.
    static var instance: ProviderInstance? {
        guard let id = UserDefaults.standard.string(forKey: Keys.instance) else { return nil }
        return ProviderConfigStore.shared.instance(for: id)
    }

    static var isSignedIn: Bool {
        guard let inst = instance else { return false }
        return !(ProviderKeychainHelper.loadAPIKey(instanceId: inst.id) ?? "").isEmpty
    }

    static var account: Account? {
        get {
            guard let data = UserDefaults.standard.data(forKey: Keys.account) else { return nil }
            return try? JSONDecoder().decode(Account.self, from: data)
        }
        set {
            if let newValue, let data = try? JSONEncoder().encode(newValue) {
                UserDefaults.standard.set(data, forKey: Keys.account)
            } else {
                UserDefaults.standard.removeObject(forKey: Keys.account)
            }
        }
    }

    // MARK: - Calls

    /// Ask the relay to send a code. Throws `CloudError` with the relay's `code`.
    static func requestCode(identifier: String) async throws {
        _ = try await call("POST", "/v1/auth/code", body: ["identifier": trimmed(identifier)], token: nil)
    }

    /// Exchange the code for a key and make the relay a usable provider: instance, key, models
    /// and a default group with the recommended chat model (only if the user has none yet).
    /// Returns the account as the relay sees it.
    static func verify(identifier: String, code: String) async throws -> Account {
        let device = UIDevice.current
        let reply = try await call(
            "POST", "/v1/auth/verify",
            body: [
                "identifier": trimmed(identifier),
                "code": trimmed(code),
                "device": String("\(device.model) iOS \(device.systemVersion)".prefix(80)),
            ],
            token: nil
        )
        guard let apiKey = reply["api_key"] as? String, !apiKey.isEmpty else {
            throw CloudError(code: "bad_reply", message: "The relay sent no key", status: 0)
        }
        // The host the code was sent to is the host the key is for; the relay's own idea of
        // its public address (`base_url`) is informational.
        let base = baseURL
        let store = ProviderConfigStore.shared

        // One instance per relay: signing in again on the same phone refreshes the key and
        // keeps the entries and groups that already point at it.
        let inst: ProviderInstance
        if var existing = instance {
            if existing.customBaseURL != base {
                existing.customBaseURL = base
                store.updateInstance(existing)
            }
            ProviderKeychainHelper.saveAPIKey(apiKey, instanceId: existing.id)
            inst = existing
        } else {
            let fresh = ProviderInstance(
                label: label,
                providerType: .openAI,
                credentialType: .apiKey,
                customBaseURL: base,
                appendV1Suffix: true
            )
            // Key first: addInstance fetches the model list on its own right away.
            ProviderKeychainHelper.saveAPIKey(apiKey, instanceId: fresh.id)
            store.addInstance(fresh)
            inst = fresh
        }
        UserDefaults.standard.set(inst.id, forKey: Keys.instance)

        // The models the relay serves — the same `/v1/models` call every provider gets; the
        // relay includes modalities so a picture model is recognised as one.
        await store.refreshModels(for: inst)
        provisionDefaults(store: store, instance: inst, models: reply["models"] as? [[String: Any]] ?? [])

        let parsed = parseAccount(reply)
        account = parsed
        await MainActor.run { NanoMuseHub.shared.restart() } // the new key joins the hub
        return parsed
    }

    /// Re-read the balance. Returns nil (and forgets the account) when the key is gone.
    static func refresh() async throws -> Account? {
        guard let inst = instance, let key = ProviderKeychainHelper.loadAPIKey(instanceId: inst.id), !key.isEmpty else {
            return nil
        }
        do {
            let me = try await call("GET", "/v1/me", body: nil, token: key)
            let parsed = parseAccount(me)
            account = parsed
            return parsed
        } catch let error as CloudError where error.status == 401 {
            // Revoked elsewhere, or the relay was reset: the provider cannot answer any more.
            ProviderConfigStore.shared.removeInstance(inst.id)
            clear()
            return nil
        }
    }

    /// Revoke this phone's key at the relay and take the provider out of the app.
    static func signOut() async {
        await MainActor.run { NanoMuseHub.shared.stop() }
        let store = ProviderConfigStore.shared
        if let inst = instance {
            if let key = ProviderKeychainHelper.loadAPIKey(instanceId: inst.id), !key.isEmpty {
                _ = try? await call("POST", "/v1/auth/sign-out", body: nil, token: key)
            }
            store.removeInstance(inst.id)
        }
        clear()
    }

    /// A sentence for the person, from the relay's stable error codes.
    nonisolated static func describe(_ error: Error) -> String {
        guard let cloud = error as? CloudError else {
            if (error as NSError).domain == NSURLErrorDomain {
                return AppLocalized("Could not reach nanoMuse Cloud. Check the connection and try again.")
            }
            return error.localizedDescription
        }
        switch cloud.code {
        case "bad_identifier":
            return AppLocalized("Enter a phone number or an e-mail address.")
        case "code_wrong":
            return AppLocalized("That code is not right.")
        case "code_expired":
            return AppLocalized("That code has expired. Ask for a new one.")
        case "code_too_often":
            return AppLocalized("A code was sent a moment ago. Wait a little before asking again.")
        case "send_failed":
            return AppLocalized("The code could not be sent. Try again in a minute.")
        case "account_disabled":
            return AppLocalized("This account has been disabled.")
        case "bad_key":
            return AppLocalized("This sign-in is no longer valid. Sign in again.")
        case "out_of_tokens":
            return AppLocalized("The starter allowance is used up. Add a provider of your own to keep going.")
        case "daily_cap":
            return AppLocalized("Today's allowance is used up. It resets tomorrow.")
        case "rate_limited":
            return AppLocalized("Too many requests at once. Try again shortly.")
        case "unreachable":
            return AppLocalized("Could not reach nanoMuse Cloud. Check the connection and try again.")
        default:
            return cloud.message.isEmpty ? AppLocalized("nanoMuse Cloud could not complete the request.") : cloud.message
        }
    }

    // MARK: - Internals

    /// After the key: a default group if the user has none. Nothing of the user's own is
    /// replaced — someone who already has a key and a group keeps them and gets the relay as
    /// one more provider.
    private static func provisionDefaults(store: ProviderConfigStore, instance: ProviderInstance, models: [[String: Any]]) {
        let recommended = models.first(where: { model in
            let meta = model["nanomuse"] as? [String: Any]
            return (meta?["recommended"] as? Bool) == true && !drawsOnly(model)
        }) ?? models.first(where: { !drawsOnly($0) })
        let recommendedChat = recommended?["id"] as? String
        let pictureIds = Set(models.filter { drawsOnly($0) }.compactMap { $0["id"] as? String })

        let entries = store.entries(for: instance.id).filter { !$0.isHidden }
        let chatEntry = entries.first(where: { $0.model.id == recommendedChat })
            ?? entries.first(where: { !pictureIds.contains($0.model.id) })
        guard let chatEntry else { return }
        let already = store.modelGroups.contains { $0.memberEntryIds.contains(chatEntry.id) }
        guard !already else { return }
        let group = ModelGroup(name: label, memberEntryIds: [chatEntry.id])
        store.addGroup(group)
        if store.defaultPrimaryGroupId == nil {
            store.defaultPrimaryGroupId = group.id
        }
    }

    private static func drawsOnly(_ model: [String: Any]) -> Bool {
        let arch = model["architecture"] as? [String: Any]
        let outputs = arch?["output_modalities"] as? [String] ?? []
        return outputs.contains("image") && !outputs.contains("text")
    }

    private static func parseAccount(_ reply: [String: Any]) -> Account {
        let account = reply["account"] as? [String: Any] ?? [:]
        let tokens = reply["tokens"] as? [String: Any] ?? [:]
        func int64(_ value: Any?) -> Int64 {
            if let n = value as? NSNumber { return n.int64Value }
            if let s = value as? String { return Int64(s) ?? 0 }
            return 0
        }
        return Account(
            channel: account["channel"] as? String ?? "",
            hint: account["hint"] as? String ?? "",
            granted: int64(tokens["granted"]),
            used: int64(tokens["used"]),
            usedToday: int64(tokens["used_today"]),
            dailyCap: int64(tokens["daily_cap"]),
            checkedAt: Date(),
            unlimited: (tokens["unlimited"] as? Bool) ?? ((tokens["unlimited"] as? NSNumber)?.boolValue ?? false)
        )
    }

    private static func clear() {
        UserDefaults.standard.removeObject(forKey: Keys.instance)
        UserDefaults.standard.removeObject(forKey: Keys.account)
    }

    private static func trimmed(_ s: String) -> String {
        s.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func trimSlash(_ s: String) -> String {
        var out = s
        while out.hasSuffix("/") { out.removeLast() }
        return out
    }

    private static var userAgent: String {
        let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0"
        return "nanoMuse-iOS/\(version)"
    }

    private static let session: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 30
        config.timeoutIntervalForResource = 60
        return URLSession(configuration: config)
    }()

    private static func call(_ method: String, _ path: String, body: [String: Any]?, token: String?) async throws -> [String: Any] {
        guard let url = URL(string: baseURL + path) else {
            throw CloudError(code: "bad_base", message: "Bad relay address", status: 0)
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue(userAgent, forHTTPHeaderField: "User-Agent")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let token {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        if method != "GET" {
            request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: body ?? [:])
        }
        let result: (Data, URLResponse)
        do {
            result = try await session.data(for: request)
        } catch {
            throw CloudError(code: "unreachable", message: error.localizedDescription, status: 0)
        }
        let (data, response) = result
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
        if (200..<300).contains(status) {
            return object ?? [:]
        }
        let err = object?["error"] as? [String: Any]
        let code = (err?["code"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? "http_\(status)"
        let message = (err?["message"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? "HTTP \(status)"
        throw CloudError(code: code, message: message, status: status)
    }
}
