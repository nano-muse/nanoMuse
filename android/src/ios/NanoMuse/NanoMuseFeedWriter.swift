// A scheduled Feed preparation has its own tool-free model call. Only the supplied
// excerpts enter the request, regardless of what the Feed conversation contains.
import CryptoKit
import Foundation

@MainActor
enum NanoMuseFeedWriter {
    private typealias Signal = NanoMuseFeedPreparation.Signal
    private static var generation = UUID()
    private static var switching = false
    private static var pending: Task<Bool, Error>?

    static func accountChanging(_ changing: Bool) {
        switching = changing
        NanoMuseFeedChatIndex.invalidate()
        generation = UUID()
        pending?.cancel()
        pending = nil
    }

    private static func digest(_ value: String) -> String {
        let canonical = value.precomposedStringWithCanonicalMapping.lowercased().split(whereSeparator: \.isWhitespace).joined(separator: " ")
        return SHA256.hash(data: Data(canonical.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    /// Read only the bounded part used by the prompt, under the existing private memory folder.
    private static func notes(day: Date) -> [Signal] {
        var signals: [Signal] = []
        var contents = Set<String>()
        func add(_ filename: String, limit: Int, daysAgo: Int?) {
            let file = NanoMuseDirs.memory.appendingPathComponent(filename)
            guard let values = try? file.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey]),
                  values.isRegularFile == true, values.isSymbolicLink != true,
                  let handle = try? FileHandle(forReadingFrom: file) else { return }
            defer { try? handle.close() }
            // memory_write prepends a timestamp comment and the newest entry. Read from the
            // beginning and discard a truncated final line instead of treating it as evidence.
            let byteLimit = 12_288
            guard let data = try? handle.read(upToCount: byteLimit + 1) else { return }
            var lines = String(decoding: data.prefix(byteLimit), as: UTF8.self).components(separatedBy: .newlines)
            if data.count > byteLimit { lines.removeLast() }
            var count = 0
            for line in lines {
                let text = String(line.trimmingCharacters(in: .whitespaces).prefix(400))
                guard (6...400).contains(text.count), !text.hasPrefix("#"), !text.hasPrefix("<!--"),
                      !text.hasPrefix("```"), !text.contains("{{vault:") else { continue }
                // Keep later corrections even beyond the normal excerpt limit.
                let correction = daysAgo != nil && NanoMuseFeedPreparation.isClosed(text)
                guard count < limit || correction else { continue }
                let version = digest(text.trimmingCharacters(in: CharacterSet(charactersIn: "-*• ")))
                guard contents.insert(version).inserted else { continue }
                signals.append(Signal(id: filename, version: version, label: filename, text: text, timely: daysAgo != nil, daysAgo: daysAgo))
                if !correction { count += 1 }
            }
        }
        for offset in 0..<7 {
            if let date = Calendar.current.date(byAdding: .day, value: -offset, to: day) {
                add(NanoMuseDay.key(date) + ".md", limit: 4, daysAgo: offset)
            }
        }
        add("USER.md", limit: 6, daysAgo: nil)
        add("GLOBAL.md", limit: 6, daysAgo: nil)
        return signals
    }

    private static func chatSignals(at now: Date) async -> [Signal] {
        let epoch = NanoMuseFeedChatIndex.epoch
        let refs = NanoMuseFeedChatIndex.references(now: now)
        guard !switching, !refs.isEmpty else { return [] }
        let turns = await ChatStore.shared.nmFeedTurns(refs)
        guard !switching, epoch == NanoMuseFeedChatIndex.epoch else { return [] }
        guard refs == NanoMuseFeedChatIndex.references(now: now) else { return [] }
        return NanoMuseFeedChatContext.outstanding(turns, now: now).map { item in
            let due = NanoMuseDay.key(item.due)
            let text = [item.request, item.update].compactMap { $0 }.joined(separator: "\n")
            return Signal(id: item.ref.session, version: digest([item.ref.session, item.ref.message, item.revision, due, text].joined(separator: "\n")),
                          label: AppLocalized("Chat"), text: text, timely: true, role: .chat, eventDay: due)
        }
    }

    static func liveChatKeys() async -> Set<String> {
        guard !switching, let sid = NanoMuseFeedFlow.sessionId, !SessionLockStore.shared.isLocked(sid),
              await ChatStore.shared.getMemoryEnabled(sessionId: sid) else { return [] }
        let now = Date()
        let chats = await chatSignals(at: now)
        guard !chats.isEmpty, !switching, NanoMuseFeedFlow.sessionId == sid, !SessionLockStore.shared.isLocked(sid) else { return [] }
        let pairs = NanoMuseFeedPreparation.candidates(primaries: chats, notes: notes(day: now), seen: [], limit: Int.max)
        return Set(pairs.map(\.key))
    }

    private static func pairs(at now: Date) async -> [NanoMuseFeedPreparation.Pair] {
        let chats = await chatSignals(at: now)
        return candidates(chats: chats, now: now)
    }

    private static func candidates(chats: [Signal], now: Date) -> [NanoMuseFeedPreparation.Pair] {
        let locks = SessionLockStore.shared.lockedSessionIds
        let day = NanoMuseDay.key(now)
        let cal = Calendar.current
        let goals = NanoMuseGoalStore.shared.goals.filter { goal in
            goal.status == .active && !goal.usesProtectedSession(in: locks)
                && (goal.deadlineSnoozedUntil.map { $0 <= day } ?? true)
        }.sorted { $0.updatedAt > $1.updatedAt }
        let signals = goals.prefix(16).compactMap { g -> Signal? in
            guard g.steps.isEmpty || g.steps.contains(where: { !$0.done }),
                  g.due == nil || g.dismissedDeadline != g.due else { return nil }
            let parts: [String?] = [g.title, g.why, g.steps.first(where: { !$0.done })?.text, g.lastNote, g.due]
            let text = parts.compactMap { part -> String? in
                guard let part, !part.isEmpty else { return nil }
                return String(part.prefix(220))
            }.joined(separator: "\n")
            guard !text.isEmpty, !text.contains("{{vault:") else { return nil }
            let daysToDue = NanoMuseGoalDeadline.date(g.due).flatMap {
                cal.dateComponents([.day], from: cal.startOfDay(for: now), to: cal.startOfDay(for: $0)).day
            }
            let age = now.timeIntervalSince(g.updatedAt)
            return Signal(id: g.id, version: digest(g.id + "\n" + text), label: AppLocalized("Goal") + " · " + g.title,
                          text: text, timely: daysToDue.map { (-7...7).contains($0) } == true || (0...7*86_400).contains(age), role: .goal)
        }
        let notes = notes(day: now)
        let days = (0...7).compactMap { cal.date(byAdding: .day, value: $0, to: now) }.map { NanoMuseDay.key($0) }
        let primaries = chats + signals + NanoMuseFeedPreparation.commitments(notes: notes, upcomingDays: days)
        guard !primaries.isEmpty else { return [] }
        return NanoMuseFeedPreparation.candidates(primaries: primaries, notes: notes, seen: NanoMuseFeedStore.shared.seenPreparations)
    }

    @MainActor
    private struct Run {
        let routine: NanoMuseRoutine
        let manual: Bool
        let epoch: UUID
        let owner: String
        let preferences: String

        var allowed: Bool {
            guard !switching, generation == epoch, owner == NanoMuseAccountData.shared.current,
                  let session = routine.sessionId, NanoMuseFeedFlow.isFeedSession(session), NanoMuseAccountData.shared.shows(session),
                  !SessionLockStore.shared.isLocked(session), !SessionLockStore.shared.appIsLocked,
                  let current = NanoMuseFeedFlow.routine, current.id == routine.id,
                  current.sessionId == session, (manual || current.enabled), NanoMuseFeedStore.shared.preferences == preferences else { return false }
            return !Task.isCancelled
        }

        func outcome(_ ok: Bool = true, _ note: String? = nil) -> NanoMuseHeadless.Outcome {
            .init(ok: ok, sessionId: routine.sessionId, text: "", note: note)
        }
    }

    /// Read the Feed session's configured model. This automatic computation makes no chat
    /// turn, including in the optional own-key chat transcript recorder.
    static func run(_ routine: NanoMuseRoutine, manual: Bool) async -> NanoMuseHeadless.Outcome {
        let run = Run(routine: routine, manual: manual, epoch: generation,
                      owner: NanoMuseAccountData.shared.current, preferences: NanoMuseFeedStore.shared.preferences)
        guard run.allowed, let session = routine.sessionId,
              await ChatStore.shared.getMemoryEnabled(sessionId: session), run.allowed,
              !(await pairs(at: Date())).isEmpty, run.allowed else { return run.outcome() }
        let cached = ViewModelCache.shared.getOrCreate(for: session)
        if cached.isNew { await cached.vm.loadSession() }
        guard run.allowed, cached.vm.memoryEnabled else { return run.outcome() }
        guard let entry = cached.vm.resolveCurrentEntry() else { return run.outcome(false, AppLocalized("Add a model first; routines are run by your agent.")) }
        let provider = await AIChatViewModel.makeBareAgentProvider(for: entry)
        guard run.allowed, cached.vm.memoryEnabled else { return run.outcome() }
        do {
            let call = Task { @MainActor in
                guard run.allowed, cached.vm.memoryEnabled else { return true }
                let chatEpoch = NanoMuseFeedChatIndex.epoch
                let candidates = await pairs(at: Date())
                guard run.allowed, cached.vm.memoryEnabled, !candidates.isEmpty,
                      candidates.allSatisfy({ $0.primary.role != .chat || NanoMuseFeedChatIndex.allows($0.primary.id) }) else { return true }
                let recent = NanoMuseFeedStore.shared.recentVisibleTitles(limit: 10)
                let language = AppBundle.current.preferredLocalizations.first ?? Locale.preferredLanguages.first ?? "en"
                let prompt = NanoMuseFeedPreparation.prompt(pairs: candidates, preferences: run.preferences, today: NanoMuseDay.key(),
                                                            recent: recent, language: language)
                let text = try await complete(prompt: prompt, provider: provider, session: session)
                guard run.allowed, cached.vm.memoryEnabled, let choice = NanoMuseFeedPreparation.verify(text, pairs: candidates),
                      (await pairs(at: Date())).contains(where: { $0.key == choice.pair.key }),
                      choice.pair.primary.role != .chat || (NanoMuseFeedChatIndex.epoch == chatEpoch && NanoMuseFeedChatIndex.allows(choice.pair.primary.id)),
                      run.allowed, cached.vm.memoryEnabled else { return true }
                return save(choice)
            }
            return run.outcome(try await wait(call, epoch: run.epoch))
        } catch {
            return run.outcome(false)
        }
    }

    private static func save(_ choice: NanoMuseFeedPreparation.Result) -> Bool {
        let store = NanoMuseFeedStore.shared
        if store.posts.contains(where: { $0.body.caseInsensitiveCompare(choice.body) == .orderedSame }) {
            store.remember(choice.pair.key)
            return true
        }
        let block: [String: Any] = ["title": choice.title, "body": choice.body, "type": "brief", "source": choice.citations.map(\.display)]
        guard var draft = NanoMusePost.Draft(block: block) else { return false }
        draft.citations = choice.citations
        draft.preparationGoal = choice.pair.primary.role == .goal ? choice.pair.primary.id : nil
        draft.preparationKey = choice.pair.key
        draft.preparationChat = choice.pair.primary.role == .chat ? choice.pair.primary.id : nil
        return !store.append([draft]).isEmpty
    }

    private static func complete(prompt: String, provider: AgentProvider, session: String) async throws -> String {
        let messages = [AgentMessage(role: .user, parts: [.text(prompt)])]
        let provenance = NanoMuseProvenance.Current(sessionId: session, conversation: NanoMuseOwnTurns.conversationKey(messages),
                                                    fields: .init(run: NanoMuseProvenance.runFeed, turn: 0, step: 1))
        return try await NanoMuseProvenance.$current.withValue(provenance) {
            try Task.checkCancellation()
            let stream = try await provider.streamAgentMessage(messages: messages, systemPrompt: NanoMuseFeedPreparation.instructions,
                                                               tools: [], maxTokens: 1200, thinkingLevel: .off)
            var text = ""
            var ended = false
            for try await event in stream {
                try Task.checkCancellation()
                switch event {
                case .textDelta(let delta):
                    text += delta
                    if text.utf8.count > 24_000 { return "" }
                case .done(stopReason: .endTurn): ended = true
                case .done, .toolCallComplete, .toolInputDelta, .contentBlockStart(.toolUse): return ""
                default: break
                }
            }
            return ended ? text : ""
        }
    }

    private static func wait(_ call: Task<Bool, Error>, epoch: UUID) async throws -> Bool {
        pending = call
        let timeout = Task {
            try await Task.sleep(nanoseconds: 120_000_000_000)
            call.cancel()
        }
        defer {
            timeout.cancel()
            if generation == epoch { pending = nil }
        }
        return try await withTaskCancellationHandler(operation: { try await call.value }, onCancel: { call.cancel() })
    }
}
