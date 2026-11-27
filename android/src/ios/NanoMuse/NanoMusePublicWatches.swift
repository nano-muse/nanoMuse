import Combine
import Foundation
import JavaScriptCore
import UIKit

/// Only the bundled engine is executable. External data enters it as JSON strings.
final class NanoMuseWatchScript {
    private let context: JSContext?
    init() {
        guard let url = Bundle.main.url(forResource: "public-watches", withExtension: "js"),
              let source = try? String(contentsOf: url, encoding: .utf8), let context = JSContext() else {
            self.context = nil
            return
        }
        context.evaluateScript(source)
        self.context = context.exception == nil ? context : nil
    }
    func call(_ function: String, _ input: [String: Any]) -> [String: Any]? {
        guard let context, JSONSerialization.isValidJSONObject(input),
              let bytes = try? JSONSerialization.data(withJSONObject: input),
              let json = String(data: bytes, encoding: .utf8),
              let fn = context.objectForKeyedSubscript(function), !fn.isUndefined else { return nil }
        context.exception = nil
        guard let out = fn.call(withArguments: [json])?.toString(), context.exception == nil,
              let parsed = try? JSONSerialization.jsonObject(with: Data(out.utf8)) as? [String: Any] else { return nil }
        return parsed
    }
}

struct NanoMuseWatchRow: Decodable, Identifiable {
    let id, kind, target, label, status: String
    let origin: String?
    let lastChecked: Double?
    let unavailable: Bool
}
private struct NanoMuseWatchDue: Decodable { let id, kind, target: String }
private struct NanoMuseWatchView: Decodable {
    let enabled: Bool
    let revision: Int
    let watches: [NanoMuseWatchRow]
    let due: [NanoMuseWatchDue]
    let pending: [NanoMuseWatchItem]
}

private actor NanoMuseWatchReader {
    static let shared = NanoMuseWatchReader()
    private let script = NanoMuseWatchScript()
    struct Sample: Decodable {
        let items: [[String: String]]
        let source: String?
    }
    /// One bounded native request at a time. The host validates ownership between every request.
    func step(kind: String, target: String, now: Date, responses: [[String: String]]) -> (url: String?, sample: Sample?) {
        let input: [String: Any] = ["kind": kind, "target": target, "now": Int(now.timeIntervalSince1970 * 1000), "responses": responses]
        guard let result = script.call("NanoMusePublicRead", input), result["error"] == nil else { return (nil, nil) }
        if let request = result["request"] as? [String: String] { return (request["url"], nil) }
        guard let data = try? JSONSerialization.data(withJSONObject: result) else { return (nil, nil) }
        return (nil, try? JSONDecoder().decode(Sample.self, from: data))
    }
    func get(kind: String, target: String, url: String) -> [String: String]? {
        let k = strdup(kind), t = strdup(target), u = strdup(url)
        defer { free(k); free(t); free(u) }
        guard let k, let t, let u, !Task.isCancelled, let result = NanoMusePublicGET(k, t, u) else { return nil }
        defer { MinisRcloneFreeString(result) }
        guard let value = try? JSONDecoder().decode([String: String].self, from: Data(String(cString: result).utf8)),
              let body = value["body"], let finalURL = value["finalUrl"] else { return nil }
        return ["body": body, "url": url, "finalUrl": finalURL]
    }
}

@MainActor
final class NanoMusePublicWatches: ObservableObject {
    static let shared = NanoMusePublicWatches()
    // The account lifecycle puts aside and restores nanomuse.feed.* preferences.
    private let storage = "nanomuse.feed.publicWatches"
    private let reviewAfter = "nanomuse.feed.publicWatches.reviewAfter"
    private lazy var script = NanoMuseWatchScript()
    private var view: NanoMuseWatchView?
    private var switching = false
    private var generation = UUID()
    private var running: Task<Void, Never>?
    private var nextCheck = Date.distantPast
    @Published private(set) var rows: [NanoMuseWatchRow] = []
    @Published private(set) var enabled = true
    @Published private(set) var available = false
    private(set) var revision = 0
    private init() {}

    func accountChanged(_ leaving: Bool) {
        generation = UUID()
        running?.cancel()
        switching = leaving
        nextCheck = .distantPast
        view = nil
        rows = []
        available = false
        if !leaving { reload() }
    }

    private var canAccess: Bool {
        !switching && UIApplication.shared.isProtectedDataAvailable && !SessionLockStore.shared.appIsLocked
            && !(UserDefaults.standard.string(forKey: NanoMuseMainChat.key).map { SessionLockStore.shared.isLocked($0) } ?? false)
    }

    @discardableResult
    private func apply(_ op: String, _ arguments: [String: Any] = [:]) -> Bool {
        guard canAccess else { return false }
        let defaults = UserDefaults.standard
        var input = arguments
        if let data = defaults.data(forKey: storage) {
            guard let saved = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return false }
            input["state"] = saved
        } else { input["state"] = [String: Any]() }
        input["op"] = op
        input["now"] = Int(Date().timeIntervalSince1970 * 1000)
        guard let out = script.call("NanoMuseWatch", input), out["error"] == nil, let state = out["state"] as? [String: Any],
              let bytes = try? JSONSerialization.data(withJSONObject: out),
              let latest = try? JSONDecoder().decode(NanoMuseWatchView.self, from: bytes) else { return false }
        if op != "view" {
            guard let encoded = try? JSONSerialization.data(withJSONObject: state, options: [.sortedKeys]),
                  encoded.count <= 2_000_000 else { return false }
            if defaults.data(forKey: storage) != encoded { defaults.set(encoded, forKey: storage) }
        }
        view = latest
        enabled = latest.enabled
        rows = latest.watches
        revision = latest.revision
        available = true
        return true
    }

    func reload() {
        if !apply("view") { available = false; view = nil; rows = [] }
    }
    /// Every click carries the account and choices revision that the person actually saw.
    func edit(_ fields: [String: Any], owner: String, revision: Int) -> Bool {
        guard canAccess, owner == NanoMuseAccountData.shared.current else { return false }
        var args = fields
        args["revision"] = revision
        guard apply("edit", args) else { reload(); return false }
        generation = UUID()
        NanoMuseChatOutreach.shared.revokePublicWork()
        running?.cancel()
        nextCheck = .distantPast
        if enabled {
            NanoMuseScheduler.shared.scheduleBackgroundRefresh()
            if fields["kind"] != nil || fields["action"] as? String == "confirm" {
                NanoMuseScheduler.shared.requestNotificationPermission()
            }
            Task { await check(background: false) }
        }
        return true
    }

    struct CaptureTicket {
        let token: UUID
        let source: NanoMuseFeedChatIndex.Ticket
    }

    func captureTicket(session: String?, memory: Bool) -> CaptureTicket? {
        guard canAccess, enabled, NanoMuseFeedChatIndex.allowsChatCheckIn(), let source = NanoMuseFeedChatIndex.ticket(session: session, memory: memory),
              session == nil || session == UserDefaults.standard.string(forKey: NanoMuseMainChat.key) else { return nil }
        return CaptureTicket(token: generation, source: source)
    }

    func observe(_ ticket: CaptureTicket, session: String, id: String, text: String, memory: Bool) {
        guard ticket.token == generation, !text.contains("{{vault:"), !text.contains("<system"), !text.contains("```"),
              ticket.source.owner == NanoMuseAccountData.shared.current, ticket.source.generation == NanoMuseFeedChatIndex.epoch,
              UserDefaults.standard.string(forKey: NanoMuseMainChat.key) == session,
              captureTicket(session: session, memory: memory) != nil else { return }
        let before = revision
        let turn: [String: Any] = ["id": id, "at": Int(Date().timeIntervalSince1970 * 1000), "text": text, "personal": true]
        if apply("observe", ["turns": [turn]]), revision != before {
            nextCheck = .distantPast
            NanoMuseScheduler.shared.scheduleBackgroundRefresh()
        }
    }

    func nextRefresh(after now: Date) -> Date? {
        guard canAccess, UserDefaults.standard.object(forKey: "nanomuse.shell.enabled") as? Bool ?? true else { return nil }
        if view == nil { reload() }
        guard enabled, rows.contains(where: { $0.status == "active" }) else { return nil }
        let backlog = !(view?.due.isEmpty ?? true)
        return now.addingTimeInterval(backlog ? 15 * 60 : 60 * 60)
    }

    func check(background: Bool) async {
        guard running == nil, canAccess, !Task.isCancelled, Date() >= nextCheck,
              let session = UserDefaults.standard.string(forKey: NanoMuseMainChat.key),
              !session.hasPrefix(NanoMuseMainChat.draftPrefix) else { return }
        let outreach = NanoMuseChatOutreach.shared
        let owner = NanoMuseAccountData.shared.current
        guard let ticket = outreach.publicTicket(owner: owner, session: session),
              apply("view"), enabled else { return }
        nextCheck = Date().addingTimeInterval(5 * 60)
        let token = generation
        let work = Task { await scan(owner: owner, session: session, token: token, ticket: ticket, background: background) }
        running = work
        let timeout = Task {
            try? await Task.sleep(nanoseconds: background ? 21_000_000_000 : 55_000_000_000)
            if !Task.isCancelled { work.cancel() }
        }
        await withTaskCancellationHandler { await work.value } onCancel: { work.cancel() }
        timeout.cancel()
        running = nil
    }

    private func valid(_ owner: String, _ session: String, _ token: UUID, _ ticket: UInt) -> Bool {
        !Task.isCancelled && token == generation && enabled && canAccess
            && NanoMuseChatOutreach.shared.publicTicket(owner: owner, session: session) == ticket
    }

    private func scan(owner: String, session: String, token: UUID, ticket: UInt, background: Bool) async {
        let startedAt = ProcessInfo.processInfo.systemUptime
        func valid() -> Bool { self.valid(owner, session, token, ticket) }
        guard valid() else { return }
        let refs = NanoMuseFeedChatIndex.references(now: Date(), forMainChat: session)
        if !refs.isEmpty {
            let turns = await ChatStore.shared.nmFeedTurns(refs)
            guard valid(), refs == NanoMuseFeedChatIndex.references(now: Date(), forMainChat: session) else { return }
            let input: [[String: Any]] = turns.map {
                ["id": $0.ref.message, "text": $0.text, "at": Int($0.ref.at.timeIntervalSince1970 * 1000), "personal": true]
            }
            guard apply("observe", ["turns": input]) else { return }
        }
        let choiceRevision = revision
        for due in view?.due.prefix(3) ?? [] {
            // Leave time for delivery and BGTask completion. Reschedule a remaining backlog
            // at the next available 15-minute window instead of waiting another hour.
            if ProcessInfo.processInfo.systemUptime - startedAt > (background ? 5 : 25) { break }
            if background, !(view?.pending.isEmpty ?? true),
               NanoMuseChatOutreach.shared.canReviewPublic(owner: owner, now: Date()),
               UserDefaults.standard.double(forKey: reviewAfter) <= Date().timeIntervalSince1970 { break }
            let reader = NanoMuseWatchReader.shared
            let started = Date()
            var replies = [[String: String]]()
            var sample: NanoMuseWatchReader.Sample?
            while replies.count <= 6 {
                let step = await reader.step(kind: due.kind, target: due.target, now: started, responses: replies)
                guard valid() else { return }
                if let complete = step.sample { sample = complete; break }
                guard let url = step.url, replies.count < 6, !replies.contains(where: { $0["url"] == url }),
                      let received = await reader.get(kind: due.kind, target: due.target, url: url) else { break }
                guard valid() else { return }
                replies.append(received)
            }
            guard valid(), choiceRevision == revision else { return }
            var args: [String: Any] = ["id": due.id]
            if let sample { args["items"] = sample.items; args["source"] = sample.source }
            else { args["failed"] = true }
            guard apply("sample", args) else { return }
        }
        let outreach = NanoMuseChatOutreach.shared
        guard valid(), choiceRevision == revision, outreach.canReviewPublic(owner: owner, now: Date()), let pending = view?.pending, !pending.isEmpty else { return }
        var offered = [NanoMuseWatchItem]()
        var known = [String]()
        for item in pending.prefix(5) {
            let matches = await ChatStore.shared.nmMatchingPublicNotices(session: session, item: item)
            guard valid() else { return }
            if matches.contains(where: { NanoMuseSync.shared.fromDevice(mid: $0) != nil }) { known.append(item.key) }
            else { offered.append(item) }
        }
        if !known.isEmpty { guard apply("consume", ["keys": known]) else { return } }
        guard !offered.isEmpty else { return }
        // No dialogue, credentials, subscriber identity or private context goes into the review.
        let defaults = UserDefaults.standard
        guard defaults.double(forKey: reviewAfter) <= Date().timeIntervalSince1970,
              await ChatStore.shared.nmPublicReviewReady(owner: NanoMuseAccountData.dirName(owner), day: NanoMuseGoalDeadline.key(Date()), session: session),
              valid(), let storedModel = await ChatStore.shared.getSession(session)?.modelId,
              valid(), let entry = reviewModel(session: session, model: storedModel) else { return }
        let modelRevision = ProviderConfigStore.shared.configRevision
        let authRevision = ProviderConfigStore.shared.authRevision
        func reviewAllowed() -> Bool {
            valid() && choiceRevision == revision && modelRevision == ProviderConfigStore.shared.configRevision
                && authRevision == ProviderConfigStore.shared.authRevision && reviewModel(session: session, model: storedModel)?.id == entry.id
        }
        let provider = await AIChatViewModel.makeBareAgentProvider(for: entry)
        guard reviewAllowed(), let prompt = NanoMusePublicReview.prompt(offered) else { return }
        defaults.set(Date().addingTimeInterval(60 * 60).timeIntervalSince1970, forKey: reviewAfter)
        guard let text = try? await NanoMuseFeedWriter.complete(prompt: prompt, provider: provider, session: session,
                                                                instructions: NanoMusePublicReview.instructions),
              reviewAllowed(), (await ChatStore.shared.getSession(session))?.modelId == storedModel,
              reviewAllowed(), outreach.canReviewPublic(owner: owner, now: Date()),
              let choice = NanoMusePublicReview.choice(text, count: offered.count) else { return }
        if choice == 0 { apply("consume", ["keys": offered.map(\.key)]); return }
        let item = offered[choice - 1]
        guard let message = NanoMusePublicReview.message(item) else { return }
        guard await outreach.deliverPublic(.init(text: message, goalID: nil, publicReceipt: item.key), owner: owner, session: session, ticket: ticket),
              valid() else { return }
        apply("consume", ["keys": [item.key]])
    }
    /// Select a credentialed model without opening/restoring the conversation or consuming a one-turn override.
    private func reviewModel(session: String, model: String) -> ModelEntry? {
        let store = ProviderConfigStore.shared
        func usable(_ entry: ModelEntry) -> Bool {
            guard !entry.isHidden, let instance = store.instance(for: entry.providerInstanceId),
                  instance.isEnabled, instance.hasAnyCredential else { return false }
            return AIChatViewModel.isTextOutputModel(entry.model)
        }
        if let binding = store.binding(for: session) {
            let selected: String
            switch binding.primarySource {
            case .directEntry(let id, _): selected = id
            case .group(_, let id): selected = id
            }
            if let entry = store.entry(for: selected), usable(entry) { return entry }
        }
        if let match = store.modelEntries.first(where: { $0.model.id == model && usable($0) }) { return match }
        guard let group = store.defaultPrimaryGroupId.flatMap({ store.group(for: $0) }),
              let id = ModelGroupRouter.resolve(group: group, sessionId: session, store: store) else { return nil }
        guard let entry = store.entry(for: id), usable(entry) else { return nil }
        return entry
    }

}
