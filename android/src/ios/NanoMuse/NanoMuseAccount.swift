import Combine // nanoMuse: NanoMuseStar publishes its pending ask
import Foundation
import UIKit

/// The account as the phone's account page reads it — `GET /v1/me` in full (relay 0.14+: the pool
/// in yuan, usage by kind and by model, the invite), the devices holding a key, the account's own
/// timeline, the password, and the ways out. Every field is optional on the wire: an older relay
/// sends fewer, and the page shows what it got. Mirror of the Android `CloudAccountScreen` data
/// and the desktop `AccountPage`.
struct NanoMuseSheet: Sendable {
    struct Spend: Sendable {
        var total: Double
        var grant: Double?
        var left: Double?
        var unlimited: Bool
        var warn: Bool
        var usdCny: Double?
        var inviteBonusCny: Double?
        var inviteeBonusCny: Double?
        var ownKeyDocs: String?
        /// Relay 0.21 (contract C11): the ways on for the person's region, as the relay lists them; nil from an older relay.
        var guidance: NanoMuseGuidance?

        /// What is left, from the relay or from the grant and the total.
        var remaining: Double? {
            if let left { return left }
            guard let grant else { return nil }
            return max(grant - total, 0)
        }
        var exhausted: Bool { !unlimited && grant != nil && (remaining ?? 1) <= 0 }
        var low: Bool { !unlimited && (warn || exhausted || ((grant ?? 0) > 0 && total / (grant ?? 1) >= 0.8)) }
    }

    struct UsageRow: Identifiable, Sendable {
        var id: String { model ?? kind }
        var kind: String
        var model: String?
        var requests: Int
        var promptTokens: Int64
        var completionTokens: Int64
        var costCny: Double
    }

    struct Invite: Sendable {
        var code: String
        var url: String
        var invites: Int
        var bonusCny: Double
        var earnedCny: Double
    }

    var hint: String
    var channel: String
    var member: Bool
    var hasPassword: Bool
    var sessions: Int
    var spend: Spend?
    var today: [UsageRow]
    var total: [UsageRow]
    var byModel: [UsageRow]
    var invite: Invite?

    static func parse(_ reply: [String: Any]) -> NanoMuseSheet {
        let account = reply["account"] as? [String: Any] ?? [:]
        func num(_ v: Any?) -> Double? {
            if let n = v as? NSNumber { return n.doubleValue }
            if let s = v as? String { return Double(s) }
            return nil
        }
        func rows(_ v: Any?) -> [UsageRow] {
            (v as? [[String: Any]] ?? []).map { r in
                UsageRow(
                    kind: r["kind"] as? String ?? "",
                    model: r["model"] as? String,
                    requests: Int(num(r["requests"]) ?? 0),
                    promptTokens: Int64(num(r["prompt_tokens"]) ?? 0),
                    completionTokens: Int64(num(r["completion_tokens"]) ?? 0),
                    costCny: num(r["cost_cny"]) ?? 0
                )
            }
        }
        var spend: Spend?
        if let s = reply["spend"] as? [String: Any] {
            spend = Spend(
                total: num(s["total"]) ?? 0,
                grant: num(s["grant"]),
                left: s["left"] is NSNull ? nil : num(s["left"]),
                unlimited: (s["unlimited"] as? Bool) ?? ((s["unlimited"] as? NSNumber)?.boolValue ?? false),
                warn: (s["warn"] as? Bool) ?? ((s["warn"] as? NSNumber)?.boolValue ?? false),
                usdCny: num(s["usd_cny"]),
                inviteBonusCny: num(s["invite_bonus_cny"]),
                inviteeBonusCny: num(s["invitee_bonus_cny"]),
                ownKeyDocs: (s["own_key_docs"] as? String).flatMap { $0.isEmpty ? nil : $0 },
                guidance: NanoMuseGuidance.parse(s["guidance"] as? [String: Any])
            )
        }
        var invite: Invite?
        if let i = reply["invite"] as? [String: Any], let code = i["code"] as? String, !code.isEmpty {
            invite = Invite(
                code: code,
                url: i["url"] as? String ?? "",
                invites: Int(num(i["invites"]) ?? 0),
                bonusCny: num(i["bonus_cny"]) ?? 5,
                earnedCny: num(i["earned_cny"]) ?? 0
            )
        }
        let usage = reply["usage"] as? [String: Any] ?? [:]
        let todayBlock = usage["today"] as? [String: Any] ?? [:]
        let totalBlock = usage["total"] as? [String: Any] ?? [:]
        return NanoMuseSheet(
            hint: account["hint"] as? String ?? "",
            channel: account["channel"] as? String ?? "",
            member: (account["member"] as? Bool) ?? ((account["member"] as? NSNumber)?.boolValue ?? false),
            hasPassword: (account["has_password"] as? Bool) ?? ((account["has_password"] as? NSNumber)?.boolValue ?? false),
            sessions: Int(num(account["sessions"]) ?? 0),
            spend: spend,
            today: rows(todayBlock["by_kind"]),
            total: rows(totalBlock["by_kind"]),
            byModel: rows(totalBlock["by_model"]),
            invite: invite
        )
    }
}

/// One device holding a key for the account.
struct NanoMuseSession: Identifiable, Sendable {
    var id: String { prefix }
    var prefix: String
    var device: String
    var via: String
    var createdAt: Date
    var lastUsedAt: Date?
    var current: Bool
}

/// A line of the account's own timeline: sign-ins, settings, refusals — never message content.
struct NanoMuseEvent: Identifiable, Sendable {
    var id: String
    var at: Date
    var kind: String
    var detail: String
}

/// `GET /v1/config` (relay 0.15): what a client prints before anyone signs in.
struct NanoMuseConfig: Sendable {
    var allowanceCny: Double?
    var inviteBonusCny: Double?
    var inviteeBonusCny: Double?
    var signupOpen: Bool?
}

extension NanoMuseCloud {
    private static var configCache: (at: Date, config: NanoMuseConfig)?

    /// The relay's public figures, cached for ten minutes; empty when the relay is older.
    static func config() async -> NanoMuseConfig {
        if let configCache, Date().timeIntervalSince(configCache.at) < 600 { return configCache.config }
        func num(_ v: Any?) -> Double? { (v as? NSNumber)?.doubleValue }
        let reply = (try? await call("GET", "/v1/config", body: nil, token: nil)) ?? [:]
        let config = NanoMuseConfig(
            allowanceCny: num(reply["allowance_cny"]),
            inviteBonusCny: num(reply["invite_bonus_cny"]),
            inviteeBonusCny: num(reply["invitee_bonus_cny"]),
            signupOpen: reply["signup_open"] as? Bool
        )
        configCache = (Date(), config)
        return config
    }

    private static func key() throws -> String {
        guard let key = apiKey else { throw CloudError(code: "signed_out", message: "Sign in first", status: 401) }
        return key
    }

    /// The whole of `/v1/me`.
    static func sheet() async throws -> NanoMuseSheet {
        let reply = try await call("GET", "/v1/me", body: nil, token: key())
        account = parseAccount(reply)
        NanoMuseAllowance.shared.absorb(me: reply) // the 80 % heads-up, the region's guidance (contract C11)
        return NanoMuseSheet.parse(reply)
    }

    /// Every device holding a key, this one marked.
    static func sessions() async throws -> [NanoMuseSession] {
        let reply = try await call("GET", "/v1/me/sessions", body: nil, token: key())
        return (reply["sessions"] as? [[String: Any]] ?? []).compactMap { s in
            guard let prefix = s["prefix"] as? String else { return nil }
            let created = (s["created_at"] as? NSNumber)?.doubleValue ?? 0
            let used = (s["last_used_at"] as? NSNumber)?.doubleValue
            return NanoMuseSession(
                prefix: prefix,
                device: s["device"] as? String ?? "",
                via: s["via"] as? String ?? "code",
                createdAt: Date(timeIntervalSince1970: created),
                lastUsedAt: used.map { Date(timeIntervalSince1970: $0) },
                current: (s["current"] as? Bool) ?? ((s["current"] as? NSNumber)?.boolValue ?? false)
            )
        }
    }

    /// Retire one device's key.
    static func revokeSession(prefix: String) async throws {
        let safe = prefix.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? prefix
        _ = try await call("DELETE", "/v1/me/sessions/\(safe)", body: nil, token: key())
    }

    /// The account's timeline, newest first.
    static func events(limit: Int = 40) async throws -> [NanoMuseEvent] {
        let reply = try await call("GET", "/v1/me/events?limit=\(limit)", body: nil, token: key())
        return (reply["events"] as? [[String: Any]] ?? []).enumerated().map { index, e in
            let ts = (e["ts"] as? NSNumber)?.doubleValue ?? 0
            let id = (e["id"] as? NSNumber).map { "\($0)" } ?? "\(ts)-\(index)"
            return NanoMuseEvent(id: id, at: Date(timeIntervalSince1970: ts), kind: e["kind"] as? String ?? "", detail: e["detail"] as? String ?? "")
        }
    }

    /// Set or change the password; an empty `password` with `current` removes it.
    static func setPassword(_ password: String, current: String?) async throws {
        var body: [String: Any] = ["password": password]
        if let current, !current.isEmpty { body["current"] = current }
        _ = try await call("POST", "/v1/auth/password", body: body, token: key())
    }

    /// Every device's key, this phone's included; then the provider leaves the app, and this
    /// phone's copy of the account's data stays only with `keep` (contract C12).
    static func signOutEverywhere(keep: Bool = false) async throws {
        _ = try await call("POST", "/v1/auth/sign-out-all", body: ["all": true], token: key())
        await forgetLocally(keep: keep)
    }

    /// The account, its keys, ledger, devices and synced conversations — gone for good at the
    /// relay; and everything of it on this phone — chats, memory, feed, goals, face, the key —
    /// goes too (contract C12). The next sign-in with the same address is a new account.
    static func deleteAccount() async throws {
        _ = try await call("POST", "/v1/auth/delete", body: nil, token: key())
        await forgetLocally(keep: false)
    }
}

/// One ask for a star, ready for the shell to show: the moment and its words.
struct NanoMuseStarAsk: Equatable, Identifiable {
    var moment: NanoMuseStarMoment
    var text: String
    var id: String { moment.key }
}

/// The ask for a star at the moments it is fair to (contract C1): the first sign-in, the 3rd /
/// 10th / 30th task that ran to its end, a face just drawn, the allowance used up, the 7th and
/// 30th day with the app, a goal reached — as the relay's policy says (NanoMuseNudges), with a
/// cooldown between asks and a lifetime cap. Remembered on the phone under `nm.star.*`;
/// "Star on GitHub" or "I already starred" ends every ask for good. Never a dialog: `pending` is a card where the
/// shell puts it, `signedIn()` a row on the account page. Android: community/StarPrompt.kt.
@MainActor
final class NanoMuseStar: ObservableObject {
    static let shared = NanoMuseStar()
    static let repoURL = URL(string: "https://github.com/nano-muse/nanoMuse")!

    /// The moments by name, as the shell's card API has known them. `firstTask` / `tenthTask`
    /// are the names from before the policy; they read as `tasks` with that count.
    enum Moment: String {
        case signedIn = "signed_in", firstTask = "first_task", tenthTask = "tenth_task", newLook = "new_look", exhausted
        case tasks, daysUsed = "days_used", goalDone = "goal_done"
    }

    private enum Keys {
        static let tasks = "nm.star.tasks"
        static let asks = "nm.star.asks"
        static let lastAsk = "nm.star.last_ask"
        static let days = "nm.star.days"
        static let lastDay = "nm.star.last_day"
        static let starred = "nm.star.starred"
        static let shown = "nm.star.shown"
        static let migrated = "nm.star.migrated"
    }

    /// The ask the shell should show now; nil when there is none. Dismissed by `dismiss()` or `open()`.
    @Published private(set) var pending: NanoMuseStarAsk?
    @Published private(set) var ledger: NanoMuseStarLedger

    private init() {
        Self.migrate()
        ledger = Self.load()
    }

    var policy: NanoMuseNudgePolicy { NanoMuseNudges.shared.policy }
    var starred: Bool { ledger.starred }

    // MARK: The gate

    /// Still worth asking at this moment: on in the policy, not spent, not starred, under the cap, cooldown over.
    func due(_ moment: NanoMuseStarMoment) -> Bool {
        NanoMuseStarGate.due(moment, ledger: ledger, policy: policy)
    }

    /// The card or row was shown (or waved away): the moment is spent and the cooldown starts.
    func markShown(_ moment: NanoMuseStarMoment) {
        ledger = NanoMuseStarGate.marked(moment, in: ledger)
        save()
    }

    /// Show the moment if it is due: marks it and sets `pending`.
    private func raise(_ moment: NanoMuseStarMoment) {
        guard due(moment) else { return }
        markShown(moment)
        pending = NanoMuseStarAsk(moment: moment, text: Self.words(for: moment))
    }

    func dismiss() { pending = nil }

    // MARK: Moments

    /// A model turn the person started ended with a reply. Turns of the first conversation (the
    /// naming, until the agent has its name) and background runs are not tasks; callers only
    /// report turns a person started. Returns the count so far on this phone.
    @discardableResult
    func taskFinished() -> Int {
        switch NanoMuseFirstConversation.shared.phase {
        case .askUserName, .askAgentName: return ledger.tasks
        case .none, .named, .done: break
        }
        ledger.tasks += 1
        save()
        raise(.tasks(ledger.tasks))
        return ledger.tasks
    }

    /// The app came to the front: one more distinct day, and the policy refreshed when stale.
    func dayOpened() {
        NanoMuseNudges.shared.fetchIfStale()
        let next = NanoMuseStarGate.dayOpened(ledger, dayKey: NanoMuseDay.key())
        guard next != ledger else { return }
        ledger = next
        save()
        raise(.daysUsed(ledger.days))
    }

    /// A goal was marked achieved.
    func goalDone() { raise(.goalDone) }

    /// A new face's poses finished.
    func newLook() { raise(.newLook) }

    /// The account page, seen signed in: true once, for the row (never a popup).
    func signedIn() -> Bool {
        guard due(.signedIn) else { return false }
        markShown(.signedIn)
        return true
    }

    /// The star is done: the person went to GitHub from any "Star on GitHub" or said "I already
    /// starred". No ask comes back on this phone, whatever the cooldown and the asks left.
    func markStarred() {
        ledger.starred = true
        pending = nil
        save()
    }

    /// Off to GitHub, and no more asking anywhere.
    func open() {
        markStarred()
        UIApplication.shared.open(URL(string: policy.url) ?? Self.repoURL)
    }

    // MARK: Words

    /// The card's sentence for a moment: the one the operator set in the relay's console
    /// (`star.text_zh` first when the UI is Chinese, then `star.text`), else the app's own line.
    /// The title and the buttons are always the app's.
    static func words(for moment: NanoMuseStarMoment) -> String {
        NanoMuseNudges.shared.policy.sentence(chinese: NanoMuseLocale.isChinese) ?? builtInWords(for: moment)
    }

    /// The app's own line for a moment (the same meaning as every other client).
    static func builtInWords(for moment: NanoMuseStarMoment) -> String {
        switch moment {
        case .signedIn:
            return AppLocalized("Welcome. nanoMuse is free, open source and non-profit, a personal agent for anyone who runs it. If that is worth something to you, a star on GitHub is how the next person finds it.")
        case .tasks(let n) where n == 1:
            return AppLocalized("One task done. If nanoMuse helped, a star on GitHub tells the people building it that it did.")
        case .tasks(let n):
            return String(format: AppLocalized("%d tasks done. If nanoMuse is useful, a star on GitHub helps the next person find it."), n)
        case .newLook:
            return AppLocalized("A new face, drawn for you. If you like where nanoMuse is going, a star on GitHub helps more people find it.")
        case .exhausted:
            return AppLocalized("The free allowance is used up. Thank you for coming this far. If nanoMuse has earned it, a star on GitHub keeps the project in view for the next person.")
        case .daysUsed(let n) where n == 1:
            return AppLocalized("A day with nanoMuse. If it helped, a star on GitHub helps the next person find it.")
        case .daysUsed(let n) where n == 7:
            return AppLocalized("A week with nanoMuse. If it has earned a place in your day, a star on GitHub helps the next person find it.")
        case .daysUsed(let n) where n == 30:
            return AppLocalized("A month with nanoMuse. If it has become part of your routine, a star on GitHub tells others it is worth a try.")
        case .daysUsed(let n):
            return String(format: AppLocalized("%d days with nanoMuse. If it has earned a place in your day, a star on GitHub helps the next person find it."), n)
        case .goalDone:
            return AppLocalized("Goal reached. If nanoMuse helped you get there, a star on GitHub tells the people building it.")
        }
    }

    // MARK: Ledger on disk

    private static func load() -> NanoMuseStarLedger {
        let d = UserDefaults.standard
        var ledger = NanoMuseStarLedger()
        ledger.tasks = d.integer(forKey: Keys.tasks)
        ledger.asks = d.integer(forKey: Keys.asks)
        let last = d.double(forKey: Keys.lastAsk)
        ledger.lastAsk = last > 0 ? Date(timeIntervalSince1970: last) : nil
        ledger.days = d.integer(forKey: Keys.days)
        ledger.lastDay = d.string(forKey: Keys.lastDay) ?? ""
        ledger.starred = d.bool(forKey: Keys.starred)
        ledger.shown = Set(d.stringArray(forKey: Keys.shown) ?? [])
        return ledger
    }

    private func save() {
        let d = UserDefaults.standard
        d.set(ledger.tasks, forKey: Keys.tasks)
        d.set(ledger.asks, forKey: Keys.asks)
        d.set(ledger.lastAsk?.timeIntervalSince1970 ?? 0, forKey: Keys.lastAsk)
        d.set(ledger.days, forKey: Keys.days)
        d.set(ledger.lastDay, forKey: Keys.lastDay)
        d.set(ledger.starred, forKey: Keys.starred)
        d.set(Array(ledger.shown).sorted(), forKey: Keys.shown)
    }

    /// The keys from before the policy (`nanomuse.star.*`) move over once: the counter, the
    /// flag per moment (the first and tenth task become `tasks.1` / `tasks.10`), "starred".
    private static func migrate() {
        let d = UserDefaults.standard
        guard !d.bool(forKey: Keys.migrated) else { return }
        d.set(true, forKey: Keys.migrated)
        guard d.object(forKey: Keys.tasks) == nil else { return }
        var ledger = NanoMuseStarLedger()
        ledger.tasks = d.integer(forKey: "nanomuse.star.tasks")
        ledger.starred = d.bool(forKey: "nanomuse.star.starred")
        let moved: [(String, String)] = [
            ("signed_in", "signed_in"), ("first_task", "tasks.1"), ("tenth_task", "tasks.10"),
            ("new_look", "new_look"), ("exhausted", "exhausted"),
        ]
        for (old, new) in moved where d.bool(forKey: "nanomuse.star.\(old)") {
            ledger.shown.insert(new)
        }
        ledger.asks = ledger.shown.count
        d.set(ledger.tasks, forKey: Keys.tasks)
        d.set(ledger.asks, forKey: Keys.asks)
        d.set(ledger.starred, forKey: Keys.starred)
        d.set(Array(ledger.shown).sorted(), forKey: Keys.shown)
    }

    // MARK: The pre-policy static API, kept for the shell

    /// Maps a named moment onto the gate's; the counted ones read the ledger.
    private static func convert(_ moment: Moment) -> NanoMuseStarMoment {
        switch moment {
        case .signedIn: return .signedIn
        case .firstTask: return .tasks(1)
        case .tenthTask: return .tasks(10)
        case .tasks: return .tasks(shared.ledger.tasks)
        case .newLook: return .newLook
        case .exhausted: return .exhausted
        case .daysUsed: return .daysUsed(shared.ledger.days)
        case .goalDone: return .goalDone
        }
    }

    static var starred: Bool { shared.starred }

    /// A task ended with a reply: counts per the policy and raises `shared.pending` when due.
    static func countTask() -> Int { shared.taskFinished() }

    /// The policy decides which counts ask, and `taskFinished()` already raised the card: nothing here.
    static func moment(forTask n: Int) -> Moment? { nil }

    static func text(_ moment: Moment) -> String { words(for: convert(moment)) }
    static func due(_ moment: Moment) -> Bool { shared.due(convert(moment)) }
    static func shown(_ moment: Moment) { shared.markShown(convert(moment)) }
    static func open() { shared.open() }
    static func markStarred() { shared.markStarred() }
}
