//
//  NanoMuseAccountData.swift
//  nanoMuse — contract C12 (0.1.40): what of this phone is the signed-in account's, and what
//  happens to it when the account leaves. The table is in docs/sync.md.
//
//  - Chats are rows in upstream's store; each has an owner here (`nanomuse-owners.json`): the
//    key of the account that was signed in when the session was first seen, or "" for one made
//    while nobody was. The lists, the search, the Chat tab and the sync engine show the current
//    owner's and no others (`shows`). Pre-0.1.40 sessions are claimed the same way the first
//    time the updated app runs.
//  - The agent's memory of the person (SOUL.md, USER.md, GLOBAL.md), the feed, the goals, the
//    routines, the face, the shared workspace and the account's few UserDefaults keys sit at
//    their fixed paths while the account is signed in, so upstream reads them where it always
//    did. When the account leaves they are put aside under `nanomuse/accounts/<hash>/` (*Keep
//    this account's chats on this device*) or deleted; the next account's come back from its own
//    folder or start empty. Signed out, the phone's own set (`_local`) is in place.
//  - Settings (providers and their keys, appearance, the hub's device identity) are the
//    phone's and never move. The relay's key is saved on this device only (not iCloud Keychain).
//

import CryptoKit
import Foundation
import Security

@MainActor
final class NanoMuseAccountData {
    static let shared = NanoMuseAccountData()

    /// The owner of what was made with nobody signed in.
    nonisolated static let local = ""

    private struct Owners: Codable {
        var owners: [String: String] = [:]
    }

    private enum Keys {
        /// Set on the first launch of 0.1.40 or later; its absence with no data is a fresh install.
        static let installed = "nanomuse.installed"
    }

    /// The UserDefaults keys that are the account's rather than the phone's, by prefix: the
    /// main chat and first-conversation state, the feed's, the per-session addenda and routine
    /// wakes (keyed by the account's session and row ids), and the hub's conversation → session
    /// map (a conversation id such as `main` recurs from account to account; left in place it
    /// sent another account's hub task into this one's chat).
    nonisolated static let prefPrefixes = [
        "nanomuse.main_chat.", "nanomuse.first_conversation.", "nanomuse.feed.",
        "nanomuse.addenda", "nanomuse.routine_wakes", "hub.session.",
    ]

    /// The relay's error code for a key whose account no longer exists (relay 0.1.40).
    nonisolated static let accountDeleted = "account_deleted"

    /// What becomes of the account's data when the relay refuses its key — a 401 nobody on
    /// this phone asked for (signed out from another device, a relay reset, a relay bug).
    /// Kept: put aside as *Keep this account's chats on this device* would, for the next
    /// sign-in with the same account. Only when the relay says the account itself is gone
    /// (`accountDeleted`) is there nothing to come back to, and the data goes as *Delete the
    /// account* would.
    nonisolated static func keepOnRefusedKey(code: String?) -> Bool {
        code != accountDeleted
    }

    private var owners: [String: String] = [:]
    private var loaded = false
    private var started = false

    private init() {}

    // MARK: - The key

    /// The key the signed-in account's data is filed under — the same the sync tables use
    /// (`NanoMuseSync.accountKey`): the relay's opaque `account.id`; "" while signed out.
    var current: String {
        NanoMuseSync.accountKey(id: NanoMuseCloud.account?.id, hint: NanoMuseCloud.account?.hint, apiKey: NanoMuseCloud.apiKey)
    }

    /// The folder an account's put-aside files live under: a hash, so neither the id nor a
    /// hint (which may be the address) is ever a directory name.
    nonisolated static func dirName(_ account: String) -> String {
        if account.isEmpty { return "_local" }
        let digest = SHA256.hash(data: Data(account.utf8))
        return String(digest.map { String(format: "%02x", $0) }.joined().prefix(16))
    }

    // MARK: - Lifecycle

    /// Once, from the app root: the reinstall sweep, the relay key kept on this device, and every
    /// session given an owner.
    func start() {
        guard !started else { return }
        started = true
        Task { @MainActor [self] in
            await sweepIfFreshInstall()
            Self.keepRelayKeyOnThisDevice()
            await reconcile()
        }
    }

    // MARK: - Whose chat

    func owner(of sessionId: String) -> String? {
        load()
        return owners[sessionId]
    }

    /// Whether the lists show this session right now: the current owner's, or one not claimed yet.
    func shows(_ sessionId: String) -> Bool {
        let owner = owner(of: sessionId)
        return owner == nil || owner == current
    }

    /// A chat made now belongs to whoever is signed in now (the hook in `ChatStore.createSession`).
    func claim(_ sessionId: String) {
        load()
        guard owners[sessionId] == nil else { return }
        owners[sessionId] = current
        save()
    }

    /// The sessions owned by `account`.
    func sessions(of account: String) -> [String] {
        load()
        return owners.filter { $0.value == account }.map(\.key)
    }

    /// Every session has an owner after this: one with no row goes to the account whose sync
    /// table maps it (the C10 rule), else to `account`; rows of sessions that no longer exist go.
    @discardableResult
    func reconcile(as account: String? = nil) async -> Bool {
        load()
        let current = account ?? self.current
        let sessions = await ChatStore.shared.listSessions()
        var changed = false
        let live = Set(sessions.map(\.id))
        for session in sessions where owners[session.id] == nil {
            owners[session.id] = NanoMuseSync.shared.owner(of: session.id) ?? current
            changed = true
        }
        for id in owners.keys.filter({ !live.contains($0) }) {
            owners.removeValue(forKey: id)
            changed = true
        }
        if changed {
            save()
            NotificationCenter.default.post(name: .sessionDidUpdate, object: nil)
        }
        return changed
    }

    // MARK: - Leaving and entering

    /// The account filed under `account` leaves this phone — a sign-out, a switch, *Delete
    /// account*, or a key the relay refused. With `keep` its chats stay in the store (hidden by
    /// their owner rows until it is back) and its files and keys are put aside; without, every
    /// one of them is deleted, its sync table included (so a later sign-in never reads the
    /// gap as deletions and tombstones the account's chats on its other devices).
    func leave(account: String, keep: Bool) async {
        NanoMuseDeviceConversations.shared.suspendForAccountChange()
        await reconcile(as: account)
        if !keep { await deleteChats(of: account) }
        let fm = FileManager.default
        let stash = Self.stash(for: account)
        if keep {
            try? fm.createDirectory(at: stash, withIntermediateDirectories: true)
        } else {
            try? fm.removeItem(at: stash)
        }
        for (name, url) in Self.accountPaths where fm.fileExists(atPath: url.path) {
            if keep {
                Self.move(url, to: stash.appendingPathComponent(name))
            } else {
                try? fm.removeItem(at: url)
            }
        }
        let defaults = UserDefaults.standard
        let mine = defaults.dictionaryRepresentation().filter { key, _ in Self.isAccountPref(key) }
        if keep, !mine.isEmpty, let data = try? PropertyListSerialization.data(fromPropertyList: mine, format: .binary, options: 0) {
            try? data.write(to: stash.appendingPathComponent("defaults.plist"), options: .atomic)
        }
        for key in mine.keys { defaults.removeObject(forKey: key) }
        NanoMuseScheduler.shared.reload() // the routines file moved: alarms and notifications follow
        reloadStores()
    }

    /// The account filed under `account` is the signed-in one from now on: what was put aside
    /// for it comes back to the fixed paths (nothing, for a first sign-in), the stores re-read,
    /// the lists and the Chat tab resolve again.
    func enter(account: String) async {
        let fm = FileManager.default
        let stash = Self.stash(for: account)
        if fm.fileExists(atPath: stash.path) {
            for (name, url) in Self.accountPaths {
                let src = stash.appendingPathComponent(name)
                guard fm.fileExists(atPath: src.path) else { continue }
                try? fm.removeItem(at: url)
                Self.move(src, to: url)
            }
            let plist = stash.appendingPathComponent("defaults.plist")
            if let data = try? Data(contentsOf: plist),
               let saved = (try? PropertyListSerialization.propertyList(from: data, options: [], format: nil)) as? [String: Any] {
                for (key, value) in saved where Self.isAccountPref(key) { UserDefaults.standard.set(value, forKey: key) }
            }
            try? fm.removeItem(at: stash)
        }
        await reconcile(as: account)
        NanoMuseScheduler.shared.reload()
        reloadStores()
        NanoMuseDeviceConversations.shared.resumeAfterAccountChange()
        NotificationCenter.default.post(name: .nanoMuseAccountSwitched, object: account)
        NotificationCenter.default.post(name: .sessionDidUpdate, object: nil)
        // the feed's routine and conversation are this account's now; made again when missing
        Task { @MainActor in await NanoMuseFeedFlow.ensureRoutine() }
    }

    /// Whether something was put aside for `account`.
    nonisolated static func hasKept(_ account: String) -> Bool {
        FileManager.default.fileExists(atPath: stash(for: account).path)
    }

    nonisolated static func isAccountPref(_ key: String) -> Bool {
        prefPrefixes.contains { key.hasPrefix($0) }
    }

    // MARK: - Reinstall

    /// A reinstall keeps the Keychain: the items of ours that are this device's only (the
    /// relay's key, OAuth tokens, environment variables) would outlive the data that used them.
    /// On a launch with no marker and nothing on the phone — no provider, no chat — they go.
    /// Items shared through iCloud Keychain are the person's other devices' and are left alone.
    private func sweepIfFreshInstall() async {
        let defaults = UserDefaults.standard
        defer { defaults.set(true, forKey: Keys.installed) }
        guard !defaults.bool(forKey: Keys.installed) else { return }
        let hasProviders = !ProviderConfigStore.shared.instances.isEmpty
        let hasSessions = !(await ChatStore.shared.listSessions()).isEmpty
        guard !hasProviders, !hasSessions, NanoMuseCloud.instance == nil else { return }
        Self.sweepDeviceKeychain()
    }

    nonisolated private static func sweepDeviceKeychain() {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecMatchLimit as String: kSecMatchLimitAll,
            kSecReturnAttributes as String: true,
        ]
        var result: AnyObject?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess, let items = result as? [[String: Any]] else { return }
        var removed = 0
        for item in items {
            guard let service = item[kSecAttrService as String] as? String, service.hasPrefix("io.github.nanomuse.app."),
                  service != "io.github.nanomuse.app.device" else { continue }
            var delete: [String: Any] = [
                kSecClass as String: kSecClassGenericPassword,
                kSecAttrService as String: service,
            ]
            if let account = item[kSecAttrAccount as String] as? String { delete[kSecAttrAccount as String] = account }
            if SecItemDelete(delete as CFDictionary) == errSecSuccess { removed += 1 }
        }
        AppLogger(category: "NanoMuseAccountData").info("fresh install: \(removed) device keychain item(s) of a previous install removed")
    }

    /// The relay's key is this phone's alone: saved without iCloud Keychain, unlocked after the
    /// first unlock, on this device only. `ProviderKeychainHelper.loadAPIKey` reads it as the
    /// legacy entry. Called after every sign-in and once at start (the 0.1.39 entry moves).
    static func keepRelayKeyOnThisDevice() {
        guard let inst = NanoMuseCloud.instance else { return }
        let service = "io.github.nanomuse.app.provider.\(inst.id)"
        let syncQuery: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: "api-key",
            kSecAttrSynchronizable as String: true,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: AnyObject?
        guard SecItemCopyMatching(syncQuery as CFDictionary, &result) == errSecSuccess, let data = result as? Data,
              let key = String(data: data, encoding: .utf8), !key.isEmpty else { return }
        saveRelayKey(key, instanceId: inst.id)
    }

    nonisolated static func saveRelayKey(_ key: String, instanceId: String) {
        let service = "io.github.nanomuse.app.provider.\(instanceId)"
        let base: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: "api-key",
        ]
        _ = SecItemDelete(base as CFDictionary)
        var syncDelete = base
        syncDelete[kSecAttrSynchronizable as String] = kSecAttrSynchronizableAny
        _ = SecItemDelete(syncDelete as CFDictionary)
        var add = base
        add[kSecValueData as String] = Data(key.utf8)
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        add[kSecAttrSynchronizable as String] = false
        let status = SecItemAdd(add as CFDictionary, nil)
        ProviderKeychainHelper.stampAPIKeySavedAt(Date(), instanceId: instanceId)
        AppLogger(category: "NanoMuseAccountData").info("relay key saved on this device only, status=\(status)")
    }

    // MARK: - Internals

    /// What belongs to the account, by the name it is filed under when put aside.
    nonisolated private static var accountPaths: [(String, URL)] {
        [
            ("memory", NanoMuseDirs.memory),
            ("shared", AIChatViewModel.minisSharedPersistentDir),
            ("feed", NanoMuseDirs.root.appendingPathComponent("feed", isDirectory: true)),
            ("feed-preferences.md", NanoMuseDirs.root.appendingPathComponent("feed-preferences.md")),
            ("goals.json", NanoMuseDirs.root.appendingPathComponent("goals.json")),
            ("routines.json", NanoMuseDirs.root.appendingPathComponent("routines.json")),
            ("device-chats.json", NanoMuseDeviceConversations.fileURL),
            ("avatar", NanoMuseFaceStore.directory),
            ("avatar-options", NanoMuseDirs.root.appendingPathComponent("avatar-options", isDirectory: true)),
        ]
    }

    nonisolated private static func stash(for account: String) -> URL {
        NanoMuseDirs.root.appendingPathComponent("accounts", isDirectory: true).appendingPathComponent(dirName(account), isDirectory: true)
    }

    nonisolated private static func move(_ src: URL, to dst: URL) {
        let fm = FileManager.default
        try? fm.createDirectory(at: dst.deletingLastPathComponent(), withIntermediateDirectories: true)
        try? fm.removeItem(at: dst)
        do {
            try fm.moveItem(at: src, to: dst)
        } catch {
            // across containers (the app group and Application Support): copy, then delete,
            // and only once the copy is whole. A copy that failed half way (no space, a
            // file busy) left a torn stash and then deleted the only good one.
            do {
                try fm.copyItem(at: src, to: dst)
                guard sameShape(src, dst) else {
                    try? fm.removeItem(at: dst)
                    return
                }
                try? fm.removeItem(at: src)
            } catch {
                try? fm.removeItem(at: dst)
            }
        }
    }

    /// The copy has every file of the original, at the same size: the whole tree is compared
    /// by relative path and byte count (contents are not re-read; the copy was just written).
    nonisolated private static func sameShape(_ a: URL, _ b: URL) -> Bool {
        func shape(_ root: URL) -> [String: Int]? {
            let fm = FileManager.default
            var isDir: ObjCBool = false
            guard fm.fileExists(atPath: root.path, isDirectory: &isDir) else { return nil }
            var out: [String: Int] = [:]
            if !isDir.boolValue {
                out[""] = (try? fm.attributesOfItem(atPath: root.path)[.size] as? Int) ?? -1
                return out
            }
            guard let walk = fm.enumerator(at: root, includingPropertiesForKeys: [.isRegularFileKey, .fileSizeKey], options: [.skipsHiddenFiles]) else { return nil }
            let prefix = root.standardizedFileURL.path
            for case let url as URL in walk {
                let values = try? url.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey])
                guard values?.isRegularFile == true else { continue }
                let rel = String(url.standardizedFileURL.path.dropFirst(prefix.count))
                out[rel] = values?.fileSize ?? -1
            }
            return out
        }
        guard let one = shape(a), let two = shape(b) else { return false }
        return one == two
    }

    private func deleteChats(of account: String) async {
        let ids = sessions(of: account)
        // the account's sync table first: a push later must never read these as deletions
        NanoMuseSync.shared.dropTable(for: account)
        for id in ids {
            await ChatStore.shared.deleteSession(id)
            owners.removeValue(forKey: id)
        }
        save()
        if !ids.isEmpty {
            AppLogger(category: "NanoMuseAccountData").info("removed \(ids.count) chat(s) of the account that left")
            NotificationCenter.default.post(name: .sessionDidUpdate, object: nil)
        }
    }

    private func reloadStores() {
        NanoMuseFeedStore.shared.reload()
        NanoMuseGoalStore.shared.reload()
        NanoMuseFaceStore.shared.reload()
        NanoMuseOwnClip.shared.rescan()
        NanoMuseRoutineWakes.shared.reload() // its map is in the defaults that just changed hands
        SoulStore.refreshCache()
    }

    // MARK: - Persistence

    private static var fileURL: URL {
        let dir = (try? FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true))
            ?? FileManager.default.temporaryDirectory
        return dir.appendingPathComponent("nanomuse-owners.json")
    }

    private func load() {
        guard !loaded else { return }
        let url = Self.fileURL
        if let data = try? Data(contentsOf: url) {
            if let saved = try? JSONDecoder().decode(Owners.self, from: data) { owners = saved.owners }
        } else if FileManager.default.fileExists(atPath: url.path) {
            // The file is there but could not be read (the phone is locked, the app woke in the
            // background): keep it, and read again on the next call rather than start empty and
            // write that over it.
            return
        }
        loaded = true
    }

    private func save() {
        guard loaded, let data = try? JSONEncoder().encode(Owners(owners: owners)) else { return }
        try? data.write(to: Self.fileURL, options: .atomic)
    }
}
