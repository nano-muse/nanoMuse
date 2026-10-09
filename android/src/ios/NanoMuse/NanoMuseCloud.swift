import Foundation
import UIKit

/// nanoMuse Cloud: the "start now" path. A phone number or an e-mail address, a code, and the
/// app has a provider with a starter allowance — no key of one's own needed. The server is the
/// relay in `cloud/` of the repository; anyone can run one, and the app can be pointed at it
/// ("Use a different server" on the sign-in page, `NanoMuseRelayPicker`).
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
    /// C10: the relay's opaque id of the account (`account.id` of `/v1/me`) — what the local
    /// conversations are keyed to, never the identifier. Empty from a relay that sends none.
    var id: String = ""

    var remaining: Int64 { max(granted - used, 0) }
    /// 0..1 of the grant still unspent.
    var fraction: Double {
        guard granted > 0 else { return 0 }
        return min(max(Double(remaining) / Double(granted), 0), 1)
    }

    init(channel: String, hint: String, granted: Int64, used: Int64, usedToday: Int64, dailyCap: Int64, checkedAt: Date, unlimited: Bool = false, id: String = "") {
        self.channel = channel
        self.hint = hint
        self.granted = granted
        self.used = used
        self.usedToday = usedToday
        self.dailyCap = dailyCap
        self.checkedAt = checkedAt
        self.unlimited = unlimited
        self.id = id
    }

    // `unlimited` and `id` came later; an account cached by an earlier build decodes without them.
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
        id = try c.decodeIfPresent(String.self, forKey: .id) ?? ""
    }
}

/// The relay's stable error codes (`docs/cloud.md`), or `unreachable` / `http_<status>`.
struct NanoMuseCloudError: LocalizedError, Sendable {
    let code: String
    let message: String
    let status: Int
    /// `retry_after` in seconds, when the relay said when to come back (`provider_busy`).
    var retryAfterS: Int? = nil
    /// Relay 0.22: the refusal is one of the operator's switches, not use (`paused: true` beside `allowance_exhausted`).
    var paused: Bool = false

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
        static let fresh = "nanomuse.cloud.fresh_account"
        /// The relay refused the key and the account's data was kept aside (C12); the sign-in page says so until the next sign-in.
        static let ended = "nanomuse.cloud.sign_in_ended"
    }

    /// True after a sign-in that created the account, until the first run's password page was answered.
    static var freshAccount: Bool { UserDefaults.standard.bool(forKey: Keys.fresh) }

    /// True after the relay refused the phone's key and the account's data was put aside (C12)
    /// — the sign-in page tells the person so — until the next sign-in.
    static var signInEnded: Bool { UserDefaults.standard.bool(forKey: Keys.ended) }
    static func clearFreshAccount() { UserDefaults.standard.removeObject(forKey: Keys.fresh) }

    typealias Account = NanoMuseCloudAccount
    typealias CloudError = NanoMuseCloudError

    // MARK: - State

    /// Any build may talk to another relay (0.1.38: "Use a different server" on the sign-in
    /// sheet, NanoMuseRelayPicker). The address must pass `relayProblem` first.
    static var canOverrideBase: Bool { true }

    /// The relay this build talks to.
    static var baseURL: String {
        if canOverrideBase,
           let custom = UserDefaults.standard.string(forKey: Keys.base)?.trimmingCharacters(in: .whitespacesAndNewlines),
           !custom.isEmpty {
            return trimSlash(custom)
        }
        return defaultBase
    }

    /// Whether the relay is one of the person's own rather than the default.
    static var usesOwnRelay: Bool { baseURL != defaultBase }

    /// The host of the relay in use, for "Server: …" rows.
    static var relayHost: String { URL(string: baseURL)?.host ?? baseURL }

    static func setBaseURL(_ url: String?) {
        let trimmed = url?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if trimmed.isEmpty {
            UserDefaults.standard.removeObject(forKey: Keys.base)
        } else {
            UserDefaults.standard.set(trimSlash(trimmed), forKey: Keys.base)
        }
    }

    // MARK: - Own relay

    /// What a person typed, as the base URL it means: a scheme added when none was given
    /// (https), trailing slashes gone. Nil when it is not a URL with a host.
    nonisolated static func normalizedRelay(_ raw: String) -> String? {
        var text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return nil }
        if !text.contains("://") { text = "https://" + text }
        guard let url = URL(string: text), let host = url.host, !host.isEmpty, url.scheme != nil else { return nil }
        var out = text
        while out.hasSuffix("/") { out.removeLast() }
        return out
    }

    /// A host on one's own network, where plain http is allowed. The rule is
    /// `NanoMuseProxy.isLocal`, the one the proxy's bypass applies too (and Android's `LanOnly`):
    /// parsed addresses rather than string prefixes, the private, carrier-grade, loopback,
    /// link-local and ULA ranges, `localhost`, a name without a dot, and the local suffixes
    /// with Tailscale's `.ts.net` among them.
    nonisolated static func isPrivateHost(_ host: String) -> Bool {
        NanoMuseProxy.isLocal(host)
    }

    /// Why an address cannot be used as the relay, as a sentence; nil when it can.
    nonisolated static func relayProblem(_ raw: String) -> String? {
        guard let base = normalizedRelay(raw), let url = URL(string: base), let host = url.host else {
            return AppLocalized("Enter the server's address, for example https://relay.example.org.")
        }
        let scheme = url.scheme?.lowercased() ?? ""
        if scheme == "https" { return nil }
        if scheme == "http" {
            return isPrivateHost(host) ? nil : AppLocalized("Use https unless the server is on your own network.")
        }
        return AppLocalized("Enter the server's address, for example https://relay.example.org.")
    }

    /// Whether `base` answers as a relay: `GET /healthz` with a 2xx. Throws the cloud error otherwise.
    static func checkRelay(_ base: String) async throws {
        guard let url = URL(string: base + "/healthz") else {
            throw CloudError(code: "bad_base", message: "Bad relay address", status: 0)
        }
        var request = URLRequest(url: url)
        request.setValue(userAgent, forHTTPHeaderField: "User-Agent")
        request.timeoutInterval = 10
        let response: URLResponse
        do {
            (_, response) = try await session.data(for: request)
        } catch {
            throw CloudError(code: "unreachable", message: error.localizedDescription, status: 0)
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            throw CloudError(code: "http_\(status)", message: "HTTP \(status)", status: status)
        }
    }

    // MARK: - Phone numbers

    /// Whether a phone number cannot get a text-message code before the relay is asked: a
    /// number with a country code other than China's (+86). Bare digits are left to the relay
    /// (its `phone_region` says the same sentence); an e-mail address never qualifies.
    nonisolated static func needsEmailInstead(identifier raw: String) -> Bool {
        let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.isEmpty || text.contains("@") { return false }
        let compact = text.filter { !" -()".contains($0) }
        guard compact.allSatisfy({ $0.isNumber || $0 == "+" }) else { return false }
        if compact.hasPrefix("+") { return !compact.hasPrefix("+86") }
        if compact.hasPrefix("00") { return !compact.hasPrefix("0086") }
        return false
    }

    /// The sentence for a number that cannot get a code (also `describe("phone_region")`).
    nonisolated static var phoneRegionSentence: String {
        AppLocalized("Text-message codes reach mainland-China numbers only. Use an e-mail address instead.")
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

    /// *Use nanoMuse Cloud models*: the account's models as a source. Signed in and the Cloud
    /// instance switched on. Off, the account leaves the pickers and the automatic order of
    /// every slot while the sign-in stays for sync and the hub; the one thing that may still run
    /// on it is the explicit *Use nanoMuse Cloud this time* (NanoMuseCloudOnce). The one decision
    /// point: every slot, picker and side call asks this, not `isSignedIn`.
    static var modelsOn: Bool {
        guard let inst = instance, inst.isEnabled else { return false }
        return isSignedIn
    }

    /// Flip the switch. Upstream's `isEnabled` on the Cloud instance is the stored bit, so a
    /// chat pinned to a Cloud entry stops at it the same way as for any disabled provider.
    /// Off while new chats answer through the account: the chat slot and the main chat move to
    /// the first provider of one's own that chats (`NanoMuseModelSlots.chatLeaves`); with none,
    /// the switch is refused and stays on, which is the `false` the page shows as one sentence.
    /// The same rule on every client (Android `NanoMuseCloud.setModelsOn`, the desktop's
    /// `setCloudModels`, the runtime's `409 chat_on_cloud`).
    @discardableResult
    static func setModelsOn(_ on: Bool) -> Bool {
        guard var inst = instance, inst.isEnabled != on else { return true }
        if !on, !NanoMuseModelSlots.canLeave(inst.id) { return false }
        inst.isEnabled = on
        ProviderConfigStore.shared.updateInstance(inst)
        if !on { NanoMuseModelSlots.chatLeaves(inst.id) }
        return true
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
    static func verify(identifier: String, code: String, invite: String = "") async throws -> Account {
        var body: [String: Any] = [
            "identifier": trimmed(identifier),
            "code": trimmed(code),
            "device": deviceName,
        ]
        // A friend's code: both get credit on a first sign-in (relay 0.12+); older relays ignore it.
        if !trimmed(invite).isEmpty { body["invite"] = trimmed(invite).uppercased() }
        let reply = try await call("POST", "/v1/auth/verify", body: body, token: nil)
        return try await adopt(reply)
    }

    /// The other way in: the account's password instead of a code (relay 0.12+).
    static func login(identifier: String, password: String) async throws -> Account {
        let reply = try await call(
            "POST", "/v1/auth/login",
            body: ["identifier": trimmed(identifier), "password": password, "device": deviceName],
            token: nil
        )
        return try await adopt(reply)
    }

    /// "iPhone iOS 18.1", what the relay lists under signed-in devices.
    static var deviceName: String {
        let device = UIDevice.current
        return String("\(device.model) iOS \(device.systemVersion)".prefix(80))
    }

    /// The key this phone holds, if it is signed in.
    static var apiKey: String? {
        guard let inst = instance, let key = ProviderKeychainHelper.loadAPIKey(instanceId: inst.id), !key.isEmpty else { return nil }
        return key
    }

    /// A sign-in reply → the provider instance, its models, a default group, the cached account.
    private static func adopt(_ reply: [String: Any]) async throws -> Account {
        guard let apiKey = reply["api_key"] as? String, !apiKey.isEmpty else {
            throw CloudError(code: "bad_reply", message: "The relay sent no key", status: 0)
        }
        // The host the code was sent to is the host the key is for; the relay's own idea of
        // its public address (`base_url`) is informational.
        let base = baseURL
        let store = ProviderConfigStore.shared
        // C12: who was here before the key is written — the phone's own set (signed out), or
        // an account a sign-in reached without a sign-out (nothing of it is deleted without
        // the sheet's question: it is put aside, as *Keep* would)
        let before = NanoMuseAccountData.shared.current

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
        UserDefaults.standard.removeObject(forKey: Keys.ended) // a sign-in answers the sentence (C12)
        // A sign-in that created the account owes the first run a password page (NanoMuseFirstRun).
        if (reply["created"] as? Bool) == true { UserDefaults.standard.set(true, forKey: Keys.fresh) }
        if let region = reply["region"] as? String, !region.isEmpty { UserDefaults.standard.set(region, forKey: "nanomuse.relay.region") }

        // The models the relay serves — the same `/v1/models` call every provider gets; the
        // relay includes modalities so a picture model is recognised as one.
        await store.refreshModels(for: inst)
        let menu = reply["models"] as? [[String: Any]] ?? []
        NanoMuseRelayMenu.store(menu) // the pickers' Cloud group (Settings › Models) reads it without a round trip
        provisionDefaults(store: store, instance: inst, models: menu)

        let parsed = parseAccount(reply)
        account = parsed
        // C12: the relay's key is this phone's alone — never in iCloud Keychain
        NanoMuseAccountData.saveRelayKey(apiKey, instanceId: inst.id)
        NanoMuseNudges.shared.absorb(me: reply) // nanoMuse: contract C1 — the star policy rides along
        // C12: whoever was here is put aside, and this account's own set comes back (or starts empty)
        let after = NanoMuseAccountData.shared.current
        if after != before {
            await NanoMuseAccountData.shared.leave(account: before, keep: true)
            await NanoMuseAccountData.shared.enter(account: after)
        }
        await MainActor.run { NanoMuseHub.shared.restart() } // the new key joins the hub
        NanoMuseSync.shared.accountChanged() // C10: another account's conversations are not this one's to show or push
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
            NanoMuseNudges.shared.absorb(me: me) // nanoMuse: contract C1
            NanoMuseAllowance.shared.absorb(me: me) // the 80 % heads-up, the region's guidance (contract C11)
            return parsed
        } catch let error as CloudError where error.status == 401 {
            // Revoked elsewhere, or the relay was reset: the provider cannot answer any more.
            // Nobody on this phone asked, so the account's data is put aside as *Keep* would
            // and comes back with the next sign-in as the same account (C12). Only
            // `account_deleted` — the account itself is gone at the relay — leaves nothing to
            // come back to, and the data goes.
            let keep = NanoMuseAccountData.keepOnRefusedKey(code: error.code)
            await forgetLocally(keep: keep)
            if keep { UserDefaults.standard.set(true, forKey: Keys.ended) }
            return nil
        }
    }

    /// Revoke this phone's key at the relay and take the provider out of the app. The account's
    /// chats, memory, feed, goals and face stay on the phone — put aside for its return — only
    /// with `keep` (the sign-out sheet's switch, off by default; contract C12).
    static func signOut(keep: Bool = false) async {
        NanoMuseHub.shared.stop()
        if let inst = instance, let key = ProviderKeychainHelper.loadAPIKey(instanceId: inst.id), !key.isEmpty {
            _ = try? await call("POST", "/v1/auth/sign-out", body: nil, token: key)
        }
        await forgetLocally(keep: keep)
    }

    /// The phone forgets the account: the account's data leaves the fixed paths (C12,
    /// `NanoMuseAccountData.leave` — put aside with `keep`, deleted without), the provider and
    /// the key go, and the phone's own set comes back. The account's data moves while the
    /// account is still the signed-in key; the phone's set returns only once the key is gone,
    /// so nothing made in the gap is filed under the account that left.
    static func forgetLocally(keep: Bool) async {
        NanoMuseHub.shared.stop()
        let account = NanoMuseAccountData.shared.current
        if !account.isEmpty { await NanoMuseAccountData.shared.leave(account: account, keep: keep) }
        if let inst = instance { ProviderConfigStore.shared.removeInstance(inst.id) }
        clear()
        if !account.isEmpty { await NanoMuseAccountData.shared.enter(account: NanoMuseAccountData.local) }
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
        case "phone_region":
            return phoneRegionSentence
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
        case "not_invited":
            return AppLocalized("This relay is private; that address is not on its list.")
        case "bad_key":
            return AppLocalized("This sign-in is no longer valid. Sign in again.")
        case "account_deleted":
            return AppLocalized("This account was deleted. Sign in again to start a new one.")
        case "out_of_tokens":
            return AppLocalized("The starter allowance is used up. Add a provider of your own to keep going.")
        case "allowance_exhausted" where cloud.paused:
            // relay 0.22: the operator's switch, not use — the same card, another lead
            return AppLocalized("The free allowance is paused on this relay for now. It is not used up. Add a key of your own or sign in with a plan you already pay for, under Settings → nanoMuse Cloud. Your sign-in, your devices and what is left stay as they are.")
        case "allowance_exhausted":
            return AppLocalized("The free allowance is used up. Use a key of your own, or invite a friend; both are under nanoMuse Cloud in Settings.")
        case "too_large":
            return AppLocalized("That message is too large for the model. Shorten it, leave out some attachments, or start a new chat.")
        case "content_rejected":
            return AppLocalized("The model provider's content check declined this request. Try different words, or start a new chat if it keeps happening: the words it objects to can be earlier in the conversation.")
        case "too_many_in_flight":
            return AppLocalized("Too many requests at once. Try again shortly.")
        case "provider_busy":
            if let s = cloud.retryAfterS, s > 0 {
                return String(format: AppLocalized("The model provider is busy right now. Try again in %@."), NanoMuseProviderReach.duration(s))
            }
            return AppLocalized("The model provider is busy right now. Try again in a moment.")
        case "locked":
            return AppLocalized("Too many requests at once. Try again shortly.")
        case "model_not_offered":
            return AppLocalized("nanoMuse Cloud no longer offers that model. Pick another under Settings → nanoMuse Cloud.")
        case "service_paused":
            return AppLocalized("nanoMuse Cloud is paused by its operator for now; your sign-in and your data are kept. Try again later.")
        case "sync_paused":
            return AppLocalized("Conversation sync is paused on this relay for now; what is stored is kept, and your devices keep working on their own.")
        case "hub_paused":
            return AppLocalized("The device hub is paused on this relay for now; each device keeps working on its own.")
        case "upstream":
            return AppLocalized("nanoMuse Cloud did not answer. Try again in a moment.")
        case "password_wrong":
            return AppLocalized("That password is not right.")
        case "password_required", "no_password":
            return AppLocalized("This account has no password yet. Sign in with a code and set one under nanoMuse Cloud.")
        case "password_weak":
            return AppLocalized("Use eight characters or more.")
        case "invite_bad":
            return AppLocalized("That invite code is not one we know. Check it, or leave it empty.")
        case "signup_closed":
            return AppLocalized("Sign-ups are paused on this relay for now. An account that already exists can still sign in.")
        case "daily_cap":
            return AppLocalized("Today's allowance is used up. It resets tomorrow.")
        case "rate_limited":
            return AppLocalized("Too many requests at once. Try again shortly.")
        case "unreachable":
            return AppLocalized("Could not reach nanoMuse Cloud. Check the connection and try again.")
        default:
            // a code we do not know: the status says what kind of thing it was
            switch cloud.status {
            case 413: return AppLocalized("That message is too large for the model. Shorten it, leave out some attachments, or start a new chat.")
            case 401: return AppLocalized("This sign-in is no longer valid. Sign in again.")
            case 500...: return AppLocalized("nanoMuse Cloud did not answer. Try again in a moment.")
            default: break
            }
            let bare = cloud.message.isEmpty || cloud.message.hasPrefix("HTTP ")
            return bare ? AppLocalized("nanoMuse Cloud could not complete the request.") : cloud.message
        }
    }

    // MARK: - Internals

    /// After the key: a default group if the user has none. Nothing of the user's own is
    /// replaced — someone who already has a key and a group keeps them and gets the relay as
    /// one more provider.
    private static func provisionDefaults(store: ProviderConfigStore, instance: ProviderInstance, models: [[String: Any]]) {
        // Contract C4: the chat opens on the model the relay recommends *for chat*
        // (`for: ["chat"]`, deepseek-v4.1-flash), never on a hands-only one.
        let recommendedChat = NanoMuseModelMenu.recommendedChat(models)?["id"] as? String
        let pictureIds = Set(models.filter { drawsOnly($0) }.compactMap { $0["id"] as? String })

        let entries = store.entries(for: instance.id).filter { !$0.isHidden }
        let chatEntry = entries.first(where: { $0.model.id == recommendedChat })
            ?? entries.first(where: { !pictureIds.contains($0.model.id) })
        guard let chatEntry else { return }
        // Ours already, with the recommended model or with the person's own choice (a member
        // who swapped the recommended model for another must not get a second group with the
        // old one back on signing in again).
        let already = store.modelGroups.contains { $0.memberEntryIds.contains(chatEntry.id) || ($0.name == label && !$0.memberEntryIds.isEmpty) }
        if !already {
            let group = ModelGroup(name: label, memberEntryIds: [chatEntry.id])
            store.addGroup(group)
            if store.defaultPrimaryGroupId == nil {
                store.defaultPrimaryGroupId = group.id
            }
        }
        // The default group must be one that can answer.
        let def = store.modelGroups.first { $0.id == store.defaultPrimaryGroupId }
        if def == nil || def?.memberEntryIds.isEmpty == true {
            store.defaultPrimaryGroupId = (store.modelGroups.first { $0.memberEntryIds.contains(chatEntry.id) }
                ?? store.modelGroups.first { $0.name == label && !$0.memberEntryIds.isEmpty })?.id
        }
    }

    private static func drawsOnly(_ model: [String: Any]) -> Bool {
        let arch = model["architecture"] as? [String: Any]
        let outputs = arch?["output_modalities"] as? [String] ?? []
        return outputs.contains("image") && !outputs.contains("text")
    }

    static func parseAccount(_ reply: [String: Any]) -> Account {
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
            unlimited: (tokens["unlimited"] as? Bool) ?? ((tokens["unlimited"] as? NSNumber)?.boolValue ?? false),
            id: account["id"] as? String ?? ""
        )
    }

    static func clear() {
        UserDefaults.standard.removeObject(forKey: Keys.instance)
        UserDefaults.standard.removeObject(forKey: Keys.account)
        UserDefaults.standard.removeObject(forKey: Keys.fresh)
        NanoMuseRelayMenu.forget()
        NanoMuseAllowance.shared.forget() // the pinned card, the heads-up and the guidance were this account's
        // another account's devices and their connections are not ours to list
        NanoMuseProfileSync.shared.forget()
        NanoMuseSync.shared.accountChanged() // C10: signed out — the presence of the account that left goes too
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

    static func call(_ method: String, _ path: String, body: [String: Any]?, token: String?) async throws -> [String: Any] {
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
        if method != "GET" && method != "DELETE" {
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
        let retry = (err?["retry_after"] as? NSNumber).map { $0.doubleValue }.flatMap { $0 > 0 ? Int(ceil($0)) : nil }
        let paused = (err?["paused"] as? Bool) ?? ((err?["paused"] as? NSNumber)?.boolValue ?? false)
        throw CloudError(code: code, message: message, status: status, retryAfterS: retry, paused: paused)
    }
}
