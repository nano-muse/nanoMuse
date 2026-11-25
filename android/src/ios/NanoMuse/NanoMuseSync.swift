//
//  NanoMuseSync.swift
//  nanoMuse
//
//  Contract C7, display rules C8: the account's conversations are the same
//  on every device. This is the client: a side table that gives each local
//  session a `cid` (upstream's schema is not touched), a push of the
//  person's line when it is sent and of the final assistant text when the
//  turn ends, a pull on launch, foreground, the hub's `sync` frame and every
//  minute, and the one-main-chat rule. The whole eligible history goes up
//  on sign-in (oldest first, 200 a POST, the first conversation included);
//  what comes down is inserted into the chat by time, deduplicated by `mid`,
//  and shown as the other device's bubble with a "From {device}" caption.
//  Pulled side conversations are ordinary chats here. Files and images stay
//  where they were made; only their names and sizes travel.
//  C9 (0.1.38): side chats are per device — "Also sync side chats", default
//  off: only the main goes up, the pull asks `scope=main`, side rows that
//  still arrive are ignored. Switching it on pulls everything once
//  (`since=0&scope=all&tail=300`, idempotent) and the side chats go up with
//  the next push. The first pull of a table is `since=0&tail=300`: the last
//  300 texts per conversation, not the whole history. Presence — "{device}
//  is working…" — is NanoMusePresence; this file tells it when a turn's
//  user line has been pushed and when the turn's end has.
//  C10 (0.1.39): a conversation belongs to the account that first pushed or
//  pulled it — the table that maps it is that account's, and every account
//  that ever synced on this phone keeps its table (`Tables`). Signed in as B,
//  the lists show B's and the unowned conversations, the push takes the same
//  (an unowned one becomes B's with its first push), and A's stay on the
//  phone, hidden, until A is back. A different account than last time starts
//  its table's cursor over (a `tail` pull) and clears presence. Signed out,
//  everything on the phone shows and nothing moves. Accounts are told apart
//  by the relay's opaque `account.id`, never by the identifier.
//  Relay: GET/PUT /v1/sync/state, GET/POST /v1/sync/changes,
//  DELETE /v1/sync/conversations/{cid}, DELETE /v1/sync/changes.
//

import Foundation
import SwiftUI
import UIKit

extension Notification.Name {
    /// A main conversation arrived from another device while this phone's main chat was still a
    /// draft; the object is the local session id the shell should show as the main chat.
    static let nanoMuseMainChatAdopt = Notification.Name("nanoMuseMainChatAdopt")
    /// C10: the signed-in account is not the one the tables were open for; the object is the
    /// new account's key. The lists re-read, the main chat re-resolves.
    static let nanoMuseAccountSwitched = Notification.Name("nanoMuseAccountSwitched")
}

@MainActor
final class NanoMuseSync: ObservableObject {
    static let shared = NanoMuseSync()

    // MARK: - Side table

    /// One local session's place in the account's store.
    struct Entry: Codable {
        var cid: String
        /// `main` or `side`, fixed when the session is first mapped.
        var kind: String
        /// The hub device the conversation came from; nil when it started on this phone.
        var fromDevice: String?
        var fromDeviceName: String?
        /// What the relay last heard about the conversation itself.
        var pushedTitle: String?
        var pushedUpdatedAt: Int?
        /// Message ids (lowercase) the relay already has, pushed or pulled.
        var knownMids: Set<String> = []
    }

    /// A pulled text that could not be written yet (its chat was running a turn here).
    struct Pending: Codable {
        var mid: String
        var cid: String
        var role: String
        var text: String
        var createdAt: Int
        var deviceName: String
    }

    private struct Store: Codable {
        /// The account the table belongs to; another account starts from an empty one.
        var account = ""
        var cursor = 0
        /// Local session id → entry.
        var entries: [String: Entry] = [:]
        /// The cid every device's main chat shares, once known.
        var mainCid: String?
        /// Conversations deleted locally whose tombstone has not reached the relay yet.
        var pendingDeletes: [String] = []
        /// Whether this table has pulled at least once: a push waits for that (C8 — a device that
        /// has never pulled pulls first, so its main joins the account's instead of racing it).
        var pulled = false
        /// Message id (lowercase) → the name of the device it was written on, for the texts
        /// that came down from elsewhere (the bubble's "From {device}").
        var remoteMids: [String: String] = [:]
        /// Pulled texts waiting for their chat to finish a turn here.
        var deferred: [Pending] = []
        /// C10: the local session the Chat tab showed when this account was last signed in, so
        /// the same chat is the main one again when it comes back.
        var mainSession: String?

        init(account: String = "") {
            self.account = account
        }

        /// The 0.1.36 table has none of the C8 fields; they default rather than fail the decode
        /// (a failed decode would mean a fresh table — and every conversation pushed again under new cids).
        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            account = try c.decodeIfPresent(String.self, forKey: .account) ?? ""
            cursor = try c.decodeIfPresent(Int.self, forKey: .cursor) ?? 0
            entries = try c.decodeIfPresent([String: Entry].self, forKey: .entries) ?? [:]
            mainCid = try c.decodeIfPresent(String.self, forKey: .mainCid)
            pendingDeletes = try c.decodeIfPresent([String].self, forKey: .pendingDeletes) ?? []
            pulled = try c.decodeIfPresent(Bool.self, forKey: .pulled) ?? (cursor > 0)
            remoteMids = try c.decodeIfPresent([String: String].self, forKey: .remoteMids) ?? [:]
            deferred = try c.decodeIfPresent([Pending].self, forKey: .deferred) ?? []
            mainSession = try c.decodeIfPresent(String.self, forKey: .mainSession)
        }
    }

    /// C10: every account's table, by account key. The one signed in is `store` (and its copy
    /// here is refreshed on every save); the others wait, and say which sessions are theirs.
    private struct Tables: Codable {
        var stores: [String: Store] = [:]
        /// The key of the account the tables were last open for ("" before the first sign-in).
        var current = ""
    }

    private enum Keys {
        /// The local switch (Data controls). Default on, as the contract says.
        static let enabled = "nanomuse.sync.enabled"
        /// C9: "Also sync side chats", per device. Default off.
        static let sideChats = "nanomuse.sync.sidechats"
    }

    static let pushLimit = 200
    /// C9: how many texts per conversation a first (or switch-on) pull asks for.
    static let tail = 300

    // MARK: - Observable state

    @Published private(set) var syncing = false
    @Published private(set) var lastError: String?
    /// What the relay says about the account's switch; nil until asked.
    @Published private(set) var serverEnabled: Bool?
    @Published private(set) var conversationCount = 0
    @Published private(set) var messageCount = 0
    /// Bumped when the side table changes, so the drawer's badges re-read.
    @Published private(set) var revision = 0

    private var store = Store()
    /// C10: the other accounts' tables (and the current one's last saved copy).
    private var tables = Tables()
    private var loaded = false
    private var started = false
    private var inForeground = false
    private var pulling = false
    private var pushing = false
    private var pullAgain = false
    private var pushAgain = false
    private var pushDebounce: Task<Void, Never>?
    private var pullTimer: Timer?
    /// 401: nothing more until the account changes.
    private var haltedAccount: String?
    private var observers: [NSObjectProtocol] = []
    /// C9: the presence this phone owes the relay once the next push has gone through —
    /// session id → working. `true` after the user line, `false` after the turn's end.
    private var workingToSend: [String: Bool] = [:]
    /// A pull that starts at 0 whatever the cursor says (the side-chat switch turned on).
    private var fullPullWanted = false

    private init() {}

    // MARK: - Switch

    /// The local switch; the relay's own is `serverEnabled`.
    var enabled: Bool {
        get { UserDefaults.standard.object(forKey: Keys.enabled) == nil ? true : UserDefaults.standard.bool(forKey: Keys.enabled) }
        set { UserDefaults.standard.set(newValue, forKey: Keys.enabled) }
    }

    /// C9: whether this device's side chats travel too. Default off: they stay on this phone and
    /// the other devices' side chats do not come here.
    var sideChats: Bool {
        get { UserDefaults.standard.bool(forKey: Keys.sideChats) }
        set { UserDefaults.standard.set(newValue, forKey: Keys.sideChats) }
    }

    /// The side-chat switch: on → one pull of everything (idempotent — what is here already is
    /// known by mid), then this phone's side chats go up with the next push. Off → the pushes
    /// and pulls narrow to the main; what came down stays, as ordinary chats.
    func setSideChats(_ on: Bool) {
        guard on != sideChats else { return }
        sideChats = on
        revision += 1
        guard on, active else { return }
        fullPullWanted = true
        pull()
    }

    /// The query a pull makes. `tail` is asked on a table's first pull (cursor 0) and on the
    /// switch-on pull; otherwise the pull is incremental.
    nonisolated static func pullPath(since: Int, sideChats: Bool, tail: Int? = nil) -> String {
        var path = "/v1/sync/changes?since=\(since)&limit=500&scope=\(sideChats ? "all" : "main")"
        if let tail { path += "&tail=\(tail)" }
        return path
    }

    /// The cid of a mapped session, for presence; nil for a draft or an unmapped chat.
    func cid(for sessionId: String) -> String? {
        if !loaded { load() }
        return store.entries[sessionId]?.cid
    }

    /// Whether a conversation of `kind` is this device's business under the switch.
    nonisolated static func takes(kind: String, sideChats: Bool) -> Bool {
        kind == "main" || sideChats
    }

    private var active: Bool {
        NanoMuseCloud.isSignedIn && enabled && haltedAccount != accountKey
    }

    /// C10: the key a table is filed under — the relay's opaque `account.id`; the 0.1.38 key
    /// (the hint, or the key's tail) only for a relay that sends no id. "" when signed out.
    private var accountKey: String {
        Self.accountKey(id: NanoMuseCloud.account?.id, hint: NanoMuseCloud.account?.hint, apiKey: NanoMuseCloud.apiKey)
    }

    /// What 0.1.38 filed the one table under, to find it again the first time after the update.
    private var legacyAccountKey: String {
        Self.accountKey(id: nil, hint: NanoMuseCloud.account?.hint, apiKey: NanoMuseCloud.apiKey)
    }

    /// The table's key for an account: its id when the relay gave one, else the hint, else the
    /// key's last eight characters; "" for none of the three (signed out).
    nonisolated static func accountKey(id: String?, hint: String?, apiKey: String?) -> String {
        if let id, !id.isEmpty { return id }
        if let hint, !hint.isEmpty { return hint }
        if let apiKey, !apiKey.isEmpty { return String(apiKey.suffix(8)) }
        return ""
    }

    /// C10, rule 2: whether a session is shown and pushed under the signed-in account — one no
    /// account has synced yet, or one of the current account's. Signed out, everything shows.
    nonisolated static func visible(owner: String?, current: String) -> Bool {
        current.isEmpty || owner == nil || owner == current
    }

    // MARK: - C10: whose conversation

    /// The account a session belongs to — the one whose table maps it (it was pushed to or
    /// pulled from that account); nil for a session no account has synced.
    func owner(of sessionId: String) -> String? {
        if !loaded { load() }
        if store.entries[sessionId] != nil { return store.account }
        for (key, table) in tables.stores where key != store.account && table.entries[sessionId] != nil { return key }
        return nil
    }

    /// Whether the lists show this session right now: C10 (`visible(owner:current:)` over the
    /// sync tables) and C12 (the owner row, `NanoMuseAccountData.shows`) both agree, and it is
    /// not the feed's working conversation, which is the agent's and no chat of the person's.
    func shows(_ sessionId: String) -> Bool {
        !NanoMuseFeedFlow.isFeedSession(sessionId)
            && Self.visible(owner: owner(of: sessionId), current: accountKey) && NanoMuseAccountData.shared.shows(sessionId)
    }

    /// C12: the account's table goes with its chats (a sign-out without *Keep*, *Delete
    /// account*): a later sign-in starts a fresh table rather than reading the missing
    /// sessions as deletions and tombstoning them on the account's other devices.
    func dropTable(for account: String) {
        load()
        guard loaded, !account.isEmpty else { return }
        tables.stores.removeValue(forKey: account)
        if store.account == account {
            store = Store(account: account)
            workingToSend = [:]
            pushDebounce?.cancel()
        }
        guard let data = try? JSONEncoder().encode(tables) else { return }
        try? data.write(to: Self.tablesURL, options: .atomic)
        revision += 1
    }

    /// The sessions the lists show: `shows` over a list.
    func visible(_ sessions: [ChatSession]) -> [ChatSession] {
        sessions.filter { shows($0.id) }
    }

    /// The local session the Chat tab showed when the current account was last signed in, if
    /// it is remembered (set when the account was switched away from).
    var rememberedMainSession: String? {
        if !loaded { load() }
        return store.mainSession
    }

    /// NanoMuseCloud signed an account in or out: the tables are re-filed now rather than at
    /// the next push, so the lists and the main chat follow at once. Signed in, the account's
    /// chats come down now (Android's `ConversationSync.signedIn`): before, nothing pulled
    /// until the app was sent to the background and back or a session changed, so a fresh
    /// sign-in sat on an empty draft while the other device's main chat waited on the relay.
    func accountChanged() {
        load()
        if accountKey.isEmpty {
            // signed out: what the relay said about the account's conversations is forgotten and
            // the lists show everything on the phone again; the table waits for an account
            workingToSend = [:]
            NanoMusePresence.shared.reset()
            revision += 1
            NotificationCenter.default.post(name: .sessionDidUpdate, object: nil)
            return
        }
        signedIn()
    }

    /// A new key for the signed-in account: the stop after a 401 is over, whatever account the
    /// key is for (signing in again as the same account used to stay halted until the app was
    /// killed), the tail comes down, the minute pull starts, and this phone's own history
    /// follows (the pull schedules the push).
    private func signedIn() {
        haltedAccount = nil
        guard started, active else { return }
        pull()
        if inForeground { startPullTimer() }
    }

    /// The signed-in account is not the one `store` is for: file the current table, take the
    /// account's own (re-keyed from the 0.1.38 key when that is how it was filed) or a fresh
    /// one, start its cursor over (rule 4), clear presence, tell the lists and the main chat.
    private func activate(_ key: String) {
        let previous = tables.current
        if !previous.isEmpty {
            store.mainSession = Self.localMainSessionId()
            tables.stores[previous] = store
        }
        let legacyKey = legacyAccountKey
        var next: Store
        if let own = tables.stores[key] {
            next = own
        } else if !legacyKey.isEmpty, legacyKey != key, let legacy = tables.stores.removeValue(forKey: legacyKey) {
            next = legacy
        } else {
            next = Store(account: key)
        }
        next.account = key
        // the cursor over: the next pull is the tail pull, and the push waits for it
        next.cursor = 0
        next.pulled = false
        store = next
        tables.current = key
        tables.stores[key] = next
        save()
        workingToSend = [:]
        fullPullWanted = false
        if haltedAccount != key { haltedAccount = nil }
        NanoMusePresence.shared.reset()
        // the lists and the Chat tab: off the view update that may have asked for the table
        Task { @MainActor [self] in
            revision += 1
            NotificationCenter.default.post(name: .nanoMuseAccountSwitched, object: key)
            NotificationCenter.default.post(name: .sessionDidUpdate, object: nil)
        }
    }

    // MARK: - Lifecycle

    /// Called once from the app root: load the table, watch the app's life, pull.
    func start() {
        guard !started else { return }
        started = true
        load()
        let center = NotificationCenter.default
        observers.append(center.addObserver(forName: UIApplication.didBecomeActiveNotification, object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor in self?.foregrounded() }
        })
        observers.append(center.addObserver(forName: UIApplication.didEnterBackgroundNotification, object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor in self?.backgrounded() }
        })
        observers.append(center.addObserver(forName: .sessionDidUpdate, object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor in self?.schedulePush() }
        })
        foregrounded()
    }

    private func foregrounded() {
        inForeground = true
        guard active else { return }
        pull()
        startPullTimer()
    }

    /// The minute pull while the app is in front (contract C7: at launch, on the hub's `sync` frame, and once a minute).
    private func startPullTimer() {
        pullTimer?.invalidate()
        pullTimer = Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.pull() }
        }
    }

    private func backgrounded() {
        inForeground = false
        pullTimer?.invalidate()
        pullTimer = nil
        pushDebounce?.cancel()
        pushDebounce = nil
        guard active else { return }
        push()
    }

    /// The hub heard `{"type":"sync","what":"conversations","cursor":N,"from":id}`.
    func onHubFrame(_ frame: [String: Any]) {
        guard (frame["what"] as? String ?? "conversations") == "conversations" else { return }
        if let from = frame["from"] as? String, from == NanoMuseHub.shared.deviceId { return }
        let cursor = (frame["cursor"] as? Int) ?? Int((frame["cursor"] as? Double) ?? 0)
        if cursor > store.cursor { pull() }
    }

    // MARK: - Hooks from the chat

    /// A turn finished in `session` (the real id, or a draft id that is not a session yet).
    func turnFinished(session: String) {
        guard !session.hasPrefix(NanoMuseMainChat.draftPrefix) else { return }
        if active { workingToSend[session] = false } // C9: "working: false" follows the turn's last push
        schedulePush()
        // Texts that arrived while this chat was busy go in once the activity tracker has let go.
        if !store.deferred.isEmpty {
            Task { @MainActor in
                try? await Task.sleep(nanoseconds: 1_500_000_000)
                await self.flushDeferred()
            }
        }
    }

    /// C8: the person's line goes up when it is sent, not when the turn ends. Called by the view
    /// model right after the user row is written; the turn's assistant text follows at the end.
    func userMessageSent(session: String) {
        guard active, !session.hasPrefix(NanoMuseMainChat.draftPrefix) else { return }
        workingToSend[session] = true // C9: "working: true" follows the push of this line
        pushDebounce?.cancel()
        pushDebounce = nil
        push()
    }

    /// C9: the presence owed after a push that went through — one POST per session, never retried.
    private func sendWorking() {
        let owed = workingToSend
        workingToSend = [:]
        for (session, on) in owed {
            guard let entry = store.entries[session], Self.takes(kind: entry.kind, sideChats: sideChats) else { continue }
            NanoMusePresence.shared.send(cid: entry.cid, working: on)
        }
    }

    /// The device a pulled text was written on — the bubble's "From {device}" — or nil for this
    /// phone's own. Cheap: a dictionary lookup, read for every row the chat lays out.
    func fromDevice(mid: String) -> String? {
        if !loaded { load() }
        guard let name = store.remoteMids[mid.lowercased()] else { return nil }
        return name.isEmpty ? AppLocalized("A device") : name
    }

    /// The chat was renamed (or otherwise changed) — push soon.
    func conversationChanged(_ sessionId: String) {
        schedulePush()
    }

    /// The chat is about to be deleted locally: remember its cid for the tombstone.
    func conversationWillBeDeleted(_ sessionId: String) {
        load()
        guard let entry = store.entries.removeValue(forKey: sessionId) else { return }
        store.pendingDeletes.append(entry.cid)
        save()
        schedulePush()
    }

    /// The device a synced chat came from, for the drawer's "From Pixel 8"; nil for this phone's own.
    func originDeviceName(for sessionId: String) -> String? {
        _ = revision
        load()
        guard let entry = store.entries[sessionId], let id = entry.fromDevice, id != NanoMuseHub.shared.deviceId else { return nil }
        if let live = NanoMuseHub.shared.others.first(where: { $0.id == id }) { return live.name }
        return entry.fromDeviceName
    }

    // MARK: - Data controls

    /// Reads the relay's switch and counts.
    func refreshState() async {
        guard NanoMuseCloud.isSignedIn, let token = NanoMuseCloud.apiKey else { return }
        do {
            let reply = try await NanoMuseCloud.call("GET", "/v1/sync/state", body: nil, token: token)
            apply(state: reply)
            lastError = nil
        } catch {
            note(error)
        }
    }

    /// The switch: off → the relay deletes everything and this phone stops; on → an empty store,
    /// this phone's conversations go up again.
    func setEnabled(_ on: Bool) async {
        enabled = on
        guard NanoMuseCloud.isSignedIn, let token = NanoMuseCloud.apiKey else { return }
        do {
            let reply = try await NanoMuseCloud.call("PUT", "/v1/sync/state", body: ["enabled": on], token: token)
            apply(state: reply)
            lastError = nil
            if on {
                load()
                for key in store.entries.keys { store.entries[key]?.knownMids = []; store.entries[key]?.pushedTitle = nil }
                // The relay's store is empty again: pull first (the cursor keeps counting), then
                // everything this phone has goes up — the full backfill, oldest first.
                store.pulled = false
                save()
                foregrounded()
            } else {
                pullTimer?.invalidate()
                pullTimer = nil
            }
        } catch {
            note(error)
        }
    }

    /// "Delete synced conversations": the store is wiped, the switch stays.
    func deleteSynced() async {
        guard NanoMuseCloud.isSignedIn, let token = NanoMuseCloud.apiKey else { return }
        do {
            _ = try await NanoMuseCloud.call("DELETE", "/v1/sync/changes", body: nil, token: token)
            conversationCount = 0
            messageCount = 0
            lastError = nil
            // What this phone has is still its own; the relay simply has nothing of it now.
            load()
            for key in store.entries.keys { store.entries[key]?.knownMids = []; store.entries[key]?.pushedTitle = nil }
            save()
        } catch {
            note(error)
        }
    }

    private func apply(state reply: [String: Any]) {
        if let on = reply["enabled"] as? Bool {
            serverEnabled = on
            if !on { enabled = false }
        }
        if let counts = reply["counts"] as? [String: Any] {
            conversationCount = (counts["conversations"] as? Int) ?? 0
            messageCount = (counts["messages"] as? Int) ?? 0
        }
        // C9: who is at work on what, as the relay remembers it (unexpired only).
        if let working = reply["working"] as? [[String: Any]] { NanoMusePresence.shared.apply(list: working) }
    }

    // MARK: - Push

    private func schedulePush() {
        guard active else { return }
        // Signed in since the last foreground: the minute pull starts now.
        if inForeground, pullTimer == nil { foregrounded() }
        pushDebounce?.cancel()
        pushDebounce = Task { @MainActor [weak self] in
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            guard !Task.isCancelled else { return }
            self?.push()
        }
    }

    /// Everything the relay does not have yet: new or changed conversations, new texts, tombstones.
    func push() {
        guard active, let token = NanoMuseCloud.apiKey else { return }
        load()
        // A table that never pulled pulls first: the account's main may already exist, and our
        // main must join it rather than race it. The pull schedules this push when it is done.
        guard store.pulled else { pull(); return }
        if pushing { pushAgain = true; return }
        pushing = true
        syncing = true
        Task { @MainActor [self] in
            defer {
                pushing = false
                syncing = pulling
                if pushAgain { pushAgain = false; schedulePush() }
            }
            load()
            do {
                try await pushTombstones(token: token)
                try await pushChanges(token: token)
                lastError = nil
                sendWorking()
            } catch {
                note(error)
            }
        }
    }

    private func pushTombstones(token: String) async throws {
        guard !store.pendingDeletes.isEmpty else { return }
        for cid in store.pendingDeletes {
            do {
                _ = try await NanoMuseCloud.call("DELETE", "/v1/sync/conversations/\(cid)", body: nil, token: token)
            } catch let error as NanoMuseCloudError where error.status == 404 {
                // already gone
            }
            store.pendingDeletes.removeAll { $0 == cid }
            save()
        }
    }

    private func pushChanges(token: String) async throws {
        // Oldest first (C8): a sign-in backfills the whole history in the order it happened, the
        // first conversation at the head.
        let every = await eligibleSessions().sorted { $0.createdAt < $1.createdAt }
        let mainId = ownMainSessionId()
        let alive = Set(every.map(\.id))
        // C9: with the side-chat switch off only the main chat goes up — the one mapped as main,
        // or the shell's main when it has no entry yet. The side chats stay this phone's.
        // C10, rule 3: another account's conversations never go up under this one — only the
        // current account's and the unowned (which become this account's with this push).
        // C12: nor the chats another account, or nobody, owns on this phone.
        let sideChats = sideChats
        let sessions = every.filter { session in
            guard Self.visible(owner: owner(of: session.id), current: store.account), NanoMuseAccountData.shared.shows(session.id) else { return false }
            return sideChats || session.id == mainId || store.entries[session.id]?.kind == "main"
        }

        // Sessions that vanished without passing through the drawer's delete (Clear-all, upstream list).
        for (id, entry) in store.entries where !alive.contains(id) {
            store.entries.removeValue(forKey: id)
            store.pendingDeletes.append(entry.cid)
        }
        if !store.pendingDeletes.isEmpty {
            save()
            try await pushTombstones(token: token)
        }

        var conversations: [[String: Any]] = []
        var messages: [[String: Any]] = []
        // What each message record came from, to mark it known once accepted.
        var pending: [(session: String, mid: String)] = []

        for session in sessions {
            let entry = ensureEntry(for: session, isMain: session.id == mainId)
            // The shell's main can map as side when another local session already holds the shared cid.
            guard Self.takes(kind: entry.kind, sideChats: sideChats) else { continue }
            let updated = Int(session.updatedAt.timeIntervalSince1970)
            if entry.pushedTitle != (session.title ?? "") || entry.pushedUpdatedAt != updated {
                var record: [String: Any] = [
                    "cid": entry.cid,
                    "kind": entry.kind,
                    "created_at": Int(session.createdAt.timeIntervalSince1970),
                    "updated_at": updated,
                ]
                if let title = session.title, !title.isEmpty { record["title"] = title }
                conversations.append(record)
            }

            // Only a session that changed since its last push is read; the rest is known.
            guard entry.knownMids.isEmpty || entry.pushedUpdatedAt != updated else { continue }
            let local = await ChatStore.shared.loadMessages(sessionId: session.id)
            let present = Set(local.map { $0.id.lowercased() })
            // The first conversation's opening (what the app said on the agent's behalf) is virtual
            // here — in the message list, never in the database — so the other devices get it
            // from this table, under stable ids, dated just before the person's first line.
            let intro = Self.introRecords(for: session, cid: entry.cid)
            let introMids = Set(intro.compactMap { $0["mid"] as? String })
            // Texts that were deleted here since the relay got them.
            for mid in entry.knownMids where !present.contains(mid) && !introMids.contains(mid) {
                messages.append(["mid": mid, "cid": entry.cid, "role": "user", "text": "", "created_at": Int(Date().timeIntervalSince1970), "deleted": true])
                pending.append((session.id, mid))
            }
            for record in intro {
                guard let mid = record["mid"] as? String, !entry.knownMids.contains(mid) else { continue }
                messages.append(record)
                pending.append((session.id, mid))
            }
            for message in local.sorted(by: { $0.createdAt < $1.createdAt }) {
                let mid = message.id.lowercased()
                // What came down from another device is theirs to push, not ours.
                guard !entry.knownMids.contains(mid), store.remoteMids[mid] == nil, let record = Self.record(message, cid: entry.cid) else { continue }
                messages.append(record)
                pending.append((session.id, mid))
            }
        }

        guard !conversations.isEmpty || !messages.isEmpty else { return }

        // Conversations first, then the texts, 200 a POST.
        var first = true
        var offset = 0
        repeat {
            let slice = Array(messages[offset..<min(offset + Self.pushLimit, messages.count)])
            let body: [String: Any] = [
                "device": NanoMuseHub.shared.deviceId,
                "conversations": first ? conversations : [],
                "messages": slice,
            ]
            let reply = try await NanoMuseCloud.call("POST", "/v1/sync/changes", body: body, token: token)
            let rejected = reply["rejected"] as? [[String: Any]] ?? []
            let rejectedMids = Set(rejected.compactMap { $0["mid"] as? String })
            for (session, mid) in pending[offset..<min(offset + Self.pushLimit, pending.count)] where !rejectedMids.contains(mid) {
                store.entries[session]?.knownMids.insert(mid)
            }
            if first {
                for session in sessions {
                    guard store.entries[session.id] != nil else { continue }
                    store.entries[session.id]?.pushedTitle = session.title ?? ""
                    store.entries[session.id]?.pushedUpdatedAt = Int(session.updatedAt.timeIntervalSince1970)
                }
                if let mainId, let entry = store.entries[mainId], entry.kind == "main", store.mainCid == nil { store.mainCid = entry.cid }
            }
            save()
            // Another device's main chat was there first: ours joins it.
            if let clash = rejected.first(where: { ($0["reason"] as? String) == "main_exists" }),
               let cidMain = clash["cid_main"] as? String,
               let rejectedCid = clash["cid"] as? String {
                adoptMain(cidMain, rejectedCid: rejectedCid)
                return
            }
            first = false
            offset += Self.pushLimit
        } while offset < messages.count
    }

    /// The relay keeps one main conversation; the session we pushed as `rejectedCid` re-posts under it.
    private func adoptMain(_ cidMain: String, rejectedCid: String) {
        store.mainCid = cidMain
        guard let sessionId = store.entries.first(where: { $0.value.cid == rejectedCid })?.key else { save(); return }
        if store.entries.contains(where: { $0.value.cid == cidMain }) {
            // Another local session already is the shared main; this one stays a side chat.
            store.entries[sessionId]?.kind = "side"
            store.entries[sessionId]?.knownMids = []
            store.entries[sessionId]?.pushedTitle = nil
        } else {
            store.entries[sessionId]?.cid = cidMain
            store.entries[sessionId]?.knownMids = []
            store.entries[sessionId]?.pushedTitle = nil
        }
        save()
        revision += 1
        pushAgain = true
    }

    /// The first conversation's scripted opening as relay records, when `session` is where it
    /// happened: three assistant lines under ids derived from the session (so every push names
    /// the same ones), dated just before the session began. Empty for any other chat.
    private static func introRecords(for session: ChatSession, cid: String) -> [[String: Any]] {
        let flow = NanoMuseFirstConversation.shared
        guard flow.isBound(to: session.id) else { return [] }
        let base = Int(session.createdAt.timeIntervalSince1970) - 3
        return flow.intro().enumerated().map { index, text in
            [
                "mid": "intro-\(session.id.lowercased())-\(index)",
                "cid": cid,
                "role": "assistant",
                "text": text,
                "created_at": base + index,
            ]
        }
    }

    /// The record for a text the relay should have, or nil for what is not synced (tool steps, empties).
    private static func record(_ message: RawMessage, cid: String) -> [String: Any]? {
        if message.isToolResultOnly || message.isInternalBridge || message.id.hasPrefix(NanoMuseOutreachJournal.localPublicPrefix) { return nil }
        var text = ""
        var attachments: [[String: Any]] = []
        for part in message.parts {
            switch part {
            case .text(let s):
                text += text.isEmpty ? s : "\n" + s
            case .mediaRef(let ref):
                var a: [String: Any] = ["name": ref.originalFileName ?? (ref.relativePath as NSString).lastPathComponent, "mime": ref.mimeType]
                let path = ChatStore.shared.minisBaseURL.appendingPathComponent(ref.relativePath).path
                if let size = (try? FileManager.default.attributesOfItem(atPath: path))?[.size] as? Int {
                    a["size"] = size
                }
                attachments.append(a)
            case .toolUse:
                // An assistant step that calls a tool is not the final answer of the turn.
                if message.role == .assistant { return nil }
            case .toolResult:
                return nil
            }
        }
        // The model's `<system-reminder>` notes ride inside the person's text here and are
        // hidden by every screen; the other devices store the record as is, so they go before
        // the push (Android's Transcript does the same). A turn that was only a reminder, such
        // as the stop-and-continue nudge, is not a message at all.
        let trimmed = RawMessage.stripSystemReminders(text).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty || !attachments.isEmpty else { return nil }
        var record: [String: Any] = [
            "mid": message.id.lowercased(),
            "cid": cid,
            "role": message.role.rawValue,
            "text": trimmed,
            "created_at": Int(message.createdAt.timeIntervalSince1970),
        ]
        if !attachments.isEmpty { record["attachments"] = attachments }
        return record
    }

    // MARK: - Pull

    /// What the other devices wrote since our cursor, applied in `seq` order.
    func pull() {
        guard active, let token = NanoMuseCloud.apiKey else { return }
        if pulling { pullAgain = true; return }
        pulling = true
        syncing = true
        Task { @MainActor [self] in
            defer {
                pulling = false
                syncing = pushing
                if pullAgain { pullAgain = false; pull() }
            }
            load()
            do {
                var more = true
                var touched = false
                // C9: a table's first pull and the switch-on pull start at 0 and ask for the last
                // `tail` texts per conversation; the switch-on pull leaves the cursor where it is
                // (only ever raised) so nothing is pulled twice later.
                let full = fullPullWanted || store.cursor == 0
                fullPullWanted = false
                var since = full ? 0 : store.cursor
                while more {
                    let path = Self.pullPath(since: since, sideChats: sideChats, tail: full ? Self.tail : nil)
                    let reply = try await NanoMuseCloud.call("GET", path, body: nil, token: token)
                    let changed = await apply(changes: reply)
                    touched = touched || changed
                    let cursor = (reply["cursor"] as? Int) ?? Int((reply["cursor"] as? Double) ?? 0)
                    if cursor > store.cursor { store.cursor = cursor }
                    save()
                    more = (reply["more"] as? Bool) ?? false
                    if cursor <= since { more = false }
                    since = cursor
                }
                if !store.pulled {
                    store.pulled = true
                    save()
                }
                lastError = nil
                if touched {
                    revision += 1
                    NotificationCenter.default.post(name: .cloudSyncDidFetchChanges, object: nil)
                    NotificationCenter.default.post(name: .sessionDidUpdate, object: nil)
                }
                // Our own texts the relay does not have yet (first pull after sign-in, a new main cid).
                schedulePush()
            } catch {
                note(error)
            }
        }
    }

    /// One page. Returns true when something changed locally.
    private func apply(changes reply: [String: Any]) async -> Bool {
        var changed = false
        let me = NanoMuseHub.shared.deviceId
        // C10: the account's main joins the shell's main chat only when that chat is this
        // account's business — never another account's conversation still pinned to the tab
        let mainId = ownMainSessionId()
        let sideChats = sideChats

        for record in reply["conversations"] as? [[String: Any]] ?? [] {
            guard let cid = record["cid"] as? String else { continue }
            let deleted = (record["deleted"] as? Bool) ?? false
            let kind = (record["kind"] as? String) ?? "side"
            let title = (record["title"] as? String).flatMap { $0.isEmpty ? nil : $0 }
            let device = record["device"] as? String
            let deviceName = record["device_name"] as? String
            let local = store.entries.first(where: { $0.value.cid == cid })
            // C9: with the switch off a side conversation this phone does not know is not its business.
            if !Self.takes(kind: kind, sideChats: sideChats), local == nil { continue }

            if deleted {
                if let local {
                    store.entries.removeValue(forKey: local.key)
                    await ChatStore.shared.deleteSession(local.key)
                    changed = true
                }
                if store.mainCid == cid { store.mainCid = nil }
                continue
            }

            if kind == "main" {
                store.mainCid = cid
                if let local {
                    let sessionId = local.key
                    if let title, title != local.value.pushedTitle, await ChatStore.shared.getSession(sessionId)?.title != title {
                        await ChatStore.shared.updateSessionTitle(sessionId, title: title, category: nil)
                        store.entries[sessionId]?.pushedTitle = title
                        changed = true
                    }
                } else if let mainId, store.entries[mainId]?.kind != "side" {
                    // Our main chat joins the account's: its texts go up under the shared cid.
                    let own = store.entries[mainId]
                    store.entries[mainId] = Entry(cid: cid, kind: "main", fromDevice: own?.fromDevice, fromDeviceName: own?.fromDeviceName, pushedTitle: title, pushedUpdatedAt: nil, knownMids: [])
                    if let title, await ChatStore.shared.getSession(mainId)?.title == nil {
                        await ChatStore.shared.updateSessionTitle(mainId, title: title, category: nil)
                    }
                    changed = true
                } else {
                    // No main chat here yet (a draft): the account's main becomes a session the shell adopts.
                    let session = await ChatStore.shared.createSession(modelId: Self.defaultModelId(), title: title, source: "nanomuse-sync")
                    store.entries[session.id] = Entry(cid: cid, kind: "main", fromDevice: device, fromDeviceName: deviceName, pushedTitle: title, pushedUpdatedAt: nil, knownMids: [])
                    NotificationCenter.default.post(name: .nanoMuseMainChatAdopt, object: session.id)
                    changed = true
                }
                continue
            }

            if let local {
                let sessionId = local.key
                if let title, title != local.value.pushedTitle, await ChatStore.shared.getSession(sessionId)?.title != title {
                    await ChatStore.shared.updateSessionTitle(sessionId, title: title, category: nil)
                    store.entries[sessionId]?.pushedTitle = title
                    changed = true
                }
            } else {
                let session = await ChatStore.shared.createSession(modelId: Self.defaultModelId(), title: title, source: "nanomuse-sync")
                store.entries[session.id] = Entry(cid: cid, kind: "side", fromDevice: device, fromDeviceName: deviceName, pushedTitle: title, pushedUpdatedAt: Int(session.updatedAt.timeIntervalSince1970), knownMids: [])
                changed = true
            }
        }

        // Texts, grouped by conversation so each session's ids are read once.
        var presentBySession: [String: Set<String>] = [:]
        for record in reply["messages"] as? [[String: Any]] ?? [] {
            guard let mid = (record["mid"] as? String)?.lowercased(), let cid = record["cid"] as? String,
                  let entry = store.entries.first(where: { $0.value.cid == cid }) else { continue }
            let sessionId = entry.key
            // C9: a side chat's texts stay where they were written while the switch is off.
            guard Self.takes(kind: entry.value.kind, sideChats: sideChats) else { continue }
            let deleted = (record["deleted"] as? Bool) ?? false
            if deleted {
                await ChatStore.shared.deleteLocalMessage(messageId: mid)
                await ChatStore.shared.deleteLocalMessage(messageId: mid.uppercased())
                store.entries[sessionId]?.knownMids.remove(mid)
                store.remoteMids.removeValue(forKey: mid)
                store.deferred.removeAll { $0.mid == mid }
                changed = true
                continue
            }
            // Our own texts are here already (or were deleted here, which the push says): the echo.
            if (record["device"] as? String) == me { store.entries[sessionId]?.knownMids.insert(mid); continue }
            if store.entries[sessionId]?.knownMids.contains(mid) == true || store.deferred.contains(where: { $0.mid == mid }) { continue }
            if presentBySession[sessionId] == nil {
                presentBySession[sessionId] = Set(await ChatStore.shared.loadMessages(sessionId: sessionId).map { $0.id.lowercased() })
            }
            if presentBySession[sessionId]?.contains(mid) == true { store.entries[sessionId]?.knownMids.insert(mid); continue }
            guard let roleName = record["role"] as? String, MessageRole(rawValue: roleName) != nil else { continue }
            var text = (record["text"] as? String) ?? ""
            if let attachments = record["attachments"] as? [[String: Any]], !attachments.isEmpty {
                let names = attachments.compactMap { $0["name"] as? String }.filter { !$0.isEmpty }
                if !names.isEmpty {
                    let line = String(format: AppLocalized("Files on the other device: %@"), names.joined(separator: ", "))
                    text = text.isEmpty ? line : text + "\n\n" + line
                }
            }
            guard !text.isEmpty else { store.entries[sessionId]?.knownMids.insert(mid); continue }
            let created = (record["created_at"] as? Int) ?? Int((record["created_at"] as? Double) ?? Date().timeIntervalSince1970)
            let pending = Pending(mid: mid, cid: cid, role: roleName, text: text, createdAt: created, deviceName: (record["device_name"] as? String) ?? "")
            if await insert(pending, into: sessionId) {
                presentBySession[sessionId]?.insert(mid)
                changed = true
            }
        }
        if !store.deferred.isEmpty, await writeDeferred() { changed = true }
        return changed
    }

    /// One pulled text into its chat, by time (C8: a late row goes where it happened, not at the
    /// end). While that chat runs a turn here the store refuses — the row waits in `deferred` and
    /// `turnFinished` / the next pull write it. Returns true when the row is in the database.
    private func insert(_ pending: Pending, into sessionId: String) async -> Bool {
        if SessionActivityTracker.isActiveThreadSafe(sessionId) {
            if !store.deferred.contains(where: { $0.mid == pending.mid }) { store.deferred.append(pending) }
            return false
        }
        guard let data = try? JSONEncoder().encode([ContentPart.text(pending.text)]), let partsJSON = String(data: data, encoding: .utf8) else { return false }
        await ChatStore.shared.mergeRemoteMessage(
            id: pending.mid, sessionId: sessionId, role: pending.role, partsJson: partsJSON,
            createdAt: Date(timeIntervalSince1970: TimeInterval(pending.createdAt)), tokenUsageJson: nil, sortOrder: 0,
            reasoningContent: nil, streamInterruptCount: 0
        )
        await ChatStore.shared.nmTouchSession(sessionId)
        store.entries[sessionId]?.knownMids.insert(pending.mid)
        store.remoteMids[pending.mid] = pending.deviceName
        store.deferred.removeAll { $0.mid == pending.mid }
        return true
    }

    /// The texts that waited for a running chat, tried again. True when any went in.
    private func writeDeferred() async -> Bool {
        var wrote = false
        for pending in store.deferred {
            guard let sessionId = store.entries.first(where: { $0.value.cid == pending.cid })?.key else {
                store.deferred.removeAll { $0.mid == pending.mid }
                continue
            }
            if await insert(pending, into: sessionId) { wrote = true }
        }
        return wrote
    }

    /// After a turn: the waiting texts go in and the open chat is told.
    private func flushDeferred() async {
        load()
        let wrote = await writeDeferred()
        save()
        guard wrote else { return }
        revision += 1
        NotificationCenter.default.post(name: .cloudSyncDidFetchChanges, object: nil)
        NotificationCenter.default.post(name: .sessionDidUpdate, object: nil)
    }

    // MARK: - Sessions

    /// This phone's own conversations, as Android picks them: not iCloud copies of another device's,
    /// not the feed's, not a routine's or a goal's working session, not a session another device
    /// opened here through the hub (`task` calls, source "nanomuse-hub").
    private func eligibleSessions() async -> [ChatSession] {
        let all = await ChatStore.shared.listSessions()
        let routineSessions = Set(NanoMuseScheduler.shared.routines.compactMap(\.sessionId))
        let hiddenSources: Set<String> = ["nanomuse-routine", "nanomuse-goal", "nanomuse-hub"]
        return all.filter { session in
            if session.isRemote { return false }
            if NanoMuseFeedFlow.isFeedSession(session.id) { return false }
            if routineSessions.contains(session.id) { return false }
            if let source = session.source, hiddenSources.contains(source) { return false }
            return true
        }
    }

    /// The session the Chat tab shows, when it is a real session.
    private static func localMainSessionId() -> String? {
        guard let id = UserDefaults.standard.string(forKey: NanoMuseMainChat.key), !id.hasPrefix(NanoMuseMainChat.draftPrefix) else { return nil }
        return id
    }

    /// C10: the Chat tab's session when it may be this account's main — unowned, or already the
    /// current account's; nil while another account's conversation is still pinned there.
    private func ownMainSessionId() -> String? {
        guard let id = Self.localMainSessionId() else { return nil }
        return Self.visible(owner: owner(of: id), current: store.account) && NanoMuseAccountData.shared.shows(id) ? id : nil
    }

    private static func defaultModelId() -> String {
        ProviderConfigStore.shared.defaultPrimaryGroupId ?? LLMModel.claudeHaiku45.id
    }

    @discardableResult
    private func ensureEntry(for session: ChatSession, isMain: Bool) -> Entry {
        if let entry = store.entries[session.id] { return entry }
        var kind = "side"
        if isMain {
            // One main per account: ours is main while no other local session already holds the shared cid.
            if let mainCid = store.mainCid, store.entries.contains(where: { $0.value.cid == mainCid }) {
                kind = "side"
            } else {
                kind = "main"
            }
        }
        let cid: String
        if kind == "main", let mainCid = store.mainCid {
            cid = mainCid
        } else {
            cid = UUID().uuidString.lowercased()
        }
        let entry = Entry(cid: cid, kind: kind, fromDevice: nil, fromDeviceName: nil, pushedTitle: nil, pushedUpdatedAt: nil, knownMids: [])
        store.entries[session.id] = entry
        revision += 1
        return entry
    }

    // MARK: - Errors

    private func note(_ error: Error) {
        if let cloud = error as? NanoMuseCloudError {
            if cloud.status == 401 {
                haltedAccount = accountKey
                lastError = AppLocalized("Sign in to sync")
                return
            }
            if cloud.status == 409 || cloud.code == "sync_off" {
                enabled = false
                serverEnabled = false
                lastError = nil
                return
            }
            if cloud.code == "unreachable" { return }
        }
        lastError = NanoMuseCloud.describe(error)
    }

    // MARK: - Persistence

    private static var supportDirectory: URL {
        (try? FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true))
            ?? FileManager.default.temporaryDirectory
    }

    /// The one table of 0.1.36–0.1.38 (read once, to become the first entry of `tablesURL`).
    private static var fileURL: URL { supportDirectory.appendingPathComponent("nanomuse-sync.json") }
    /// C10: every account's table.
    private static var tablesURL: URL { supportDirectory.appendingPathComponent("nanomuse-sync-accounts.json") }

    private func load() {
        let account = accountKey
        if !loaded {
            if let data = try? Data(contentsOf: Self.tablesURL) {
                tables = (try? JSONDecoder().decode(Tables.self, from: data)) ?? Tables()
            } else if FileManager.default.fileExists(atPath: Self.tablesURL.path) {
                // There but unreadable (the phone is locked, the app woke in the background):
                // keep the file and read again on the next call; `save` stays off until then,
                // so an empty table is never written over every account's history.
                return
            } else if let data = try? Data(contentsOf: Self.fileURL), let saved = try? JSONDecoder().decode(Store.self, from: data), !saved.account.isEmpty {
                // the 0.1.38 table, filed under the key it carried (the hint); `activate` re-keys
                // it to the account's id the first time that account is seen signed in
                tables = Tables(stores: [saved.account: saved], current: saved.account)
            } else {
                tables = Tables()
            }
            loaded = true
            store = tables.stores[tables.current] ?? Store(account: tables.current)
        }
        // Signed out: the tables wait for an account; what is on the phone is the person's to see.
        guard !account.isEmpty else { return }
        if tables.current != account {
            activate(account)
        }
        if haltedAccount != nil, haltedAccount != account { haltedAccount = nil }
    }

    private func save() {
        guard loaded else { return }
        if !store.account.isEmpty { tables.stores[store.account] = store }
        if tables.current.isEmpty { tables.current = store.account }
        guard let data = try? JSONEncoder().encode(tables) else { return }
        try? data.write(to: Self.tablesURL, options: .atomic)
    }
}
