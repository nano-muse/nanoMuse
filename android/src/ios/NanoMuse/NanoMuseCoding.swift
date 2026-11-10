//
//  NanoMuseCoding.swift
//  nanoMuse
//
//  The coding agents on another computer of the account, over the hub:
//  the `coding.*` actions the runtime there answers (docs/coding-agents.md).
//  Their sessions, their last reply, and a message to any of them — from
//  the phone. Nothing of theirs is copied here.
//  Android: coding/CodingBridge.kt, ui/coding/CodingScreen.kt.
//

import SwiftUI

// MARK: - Bridge

enum NanoMuseCodingBridge {
    static let log = AppLogger(category: "NanoMuseCoding")
    /// A coding agent as the computer reports it.
    struct Agent: Identifiable, Equatable {
        var id: String
        var name: String
        var installed: Bool
        var version: String
        var running: Int
        var richHistory = false
    }

    /// One of the agent's sessions on that computer; `id` is empty for one not started yet.
    struct Session: Identifiable, Equatable {
        var agent: String
        var id: String
        var title: String
        var workspace: String
        var updatedAt: Date?
        var messages: Int
        var status: String
        var lastUser: String
        var lastAssistant: String
        var resumable: Bool
        var scope = "projects"
        var projectId = ""
        var firstMessage = ""

        /// A list key that survives an empty id (a fresh session).
        var key: String { agent + "|" + (id.isEmpty ? workspace : id) }
    }

    struct Message: Identifiable, Equatable {
        var id = UUID()
        var role: String
        var text: String
    }

    /// A message in flight: what was sent and what has come back so far.
    struct LiveRun: Equatable {
        var text: String
        var id = ""
        var sessionId = ""
        var status = "running"
        /// Finished paragraphs.
        var output = ""
        /// The paragraph being written (Cursor streams deltas, then sends the whole message).
        var current = ""
        var lastTool = ""
        var tools = 0
        var error = ""
        var items: [NanoMuseCodingItem] = []
        var resumeConflict: ResumeConflict?
        var isActive: Bool { ["starting", "authorizing", "running"].contains(status) }
    }

    struct ResumeConflict: Equatable {
        var process: String
        var continuation: String
    }

    static let listTimeout: TimeInterval = 30
    static let sendTimeout: TimeInterval = 180

    @MainActor
    static func agents(device: String) async throws -> [Agent] {
        let reply = try await NanoMuseHub.shared.call(to: device, action: "coding.agents", args: [:], timeout: listTimeout)
        return ((reply["agents"] as? [[String: Any]]) ?? []).map { o in
            let id = o["id"] as? String ?? ""
            let name = (o["name"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? id
            return Agent(id: id, name: name, installed: (o["installed"] as? Bool) ?? false, version: o["version"] as? String ?? "", running: (o["running"] as? NSNumber)?.intValue ?? 0, richHistory: (o["capabilities"] as? [String: Any])?["timeline"] as? Bool ?? false)
        }
    }

    @MainActor
    static func sessions(device: String, agent: String?, limit: Int = 40) async throws -> [Session] {
        var args: [String: Any] = ["limit": limit]
        if let agent, !agent.isEmpty { args["agent"] = agent }
        let reply = try await NanoMuseHub.shared.call(to: device, action: "coding.sessions", args: args, timeout: listTimeout)
        return ((reply["sessions"] as? [[String: Any]]) ?? []).map(session)
    }

    static func session(_ o: [String: Any]) -> Session {
        let updated = (o["updated_at"] as? NSNumber)?.doubleValue ?? 0
        return Session(
            agent: o["agent"] as? String ?? "",
            id: o["id"] as? String ?? "",
            title: o["title"] as? String ?? "",
            workspace: o["workspace"] as? String ?? "",
            updatedAt: updated > 0 ? Date(timeIntervalSince1970: updated) : nil,
            messages: (o["messages"] as? NSNumber)?.intValue ?? 0,
            status: (o["status"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? "idle",
            lastUser: o["last_user"] as? String ?? "",
            lastAssistant: o["last_assistant"] as? String ?? "",
            resumable: (o["resumable"] as? Bool) ?? true,
            scope: o["scope"] as? String ?? ((o["workspace"] as? String ?? "").isEmpty ? "chats" : "projects"),
            projectId: o["project_id"] as? String ?? o["workspace"] as? String ?? ""
        )
    }

    @MainActor
    static func transcript(device: String, agent: String, sessionId: String) async throws -> [Message] {
        let reply = try await NanoMuseHub.shared.call(to: device, action: "coding.session", args: ["agent": agent, "session_id": sessionId], timeout: listTimeout)
        return ((reply["transcript"] as? [[String: Any]]) ?? [])
            .map { Message(role: $0["role"] as? String ?? "", text: $0["text"] as? String ?? "") }
            .filter { !$0.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    }

    /// Confirm the start, then follow the owned run through short snapshot requests.
    @MainActor
    static func send(device: String, agent: String, text: String, sessionId: String, workspace: String, scope: String = "", requestId: String = UUID().uuidString, onUpdate: @escaping (LiveRun) -> Void) async throws -> LiveRun {
        var run = LiveRun(text: text, sessionId: sessionId)
        let args: [String: Any] = ["agent": agent, "text": text, "session_id": sessionId, "workspace": workspace, "scope": scope, "request_id": requestId, "protocol_version": 2, "wait": false]
        let final = try await NanoMuseHub.shared.call(to: device, action: "coding.send", args: args, timeout: sendTimeout) { ev in
            run = step(run, event: ev)
            onUpdate(run)
        }
        log.info("coding-resume-v2 send_reply request=\(requestId) run=\(final["id"] as? String ?? "") asked=\(sessionId) result=\(final["session_id"] as? String ?? "") status=\(final["status"] as? String ?? "") resumed=\(final["resumed"] as? Bool ?? false) conflict=\(final["resume_conflict"] != nil)")
        return finish(run, reply: final)
    }

    /// A snapshot cannot replace a newer send or another run in the same session.
    static func snapshot(_ run: LiveRun, reply: [String: Any]) -> LiveRun {
        let runs = reply["runs"] as? [[String: Any]] ?? []
        guard !run.id.isEmpty, let current = runs.first(where: { $0["id"] as? String == run.id }) else { return run }
        return finish(run, reply: current)
    }

    static func hasRecordedReply(_ run: LiveRun, in items: [NanoMuseCodingItem], before ids: Set<String>) -> Bool {
        guard !run.isActive,
              let user = items.last(where: { $0.role == "user" && $0.text == run.text && !ids.contains($0.id) })
        else { return false }
        return items.contains { $0.role == "assistant" && $0.sequence > user.sequence }
    }

    static func failure(_ error: Error) -> String {
        guard let hub = error as? HubError else { return error.localizedDescription }
        let description = hub.code == "not_allowed"
            ? AppLocalized("The computer did not authorize this request.")
            : NanoMuseHubErrors.describe(error)
        guard !hub.message.isEmpty else { return description }
        return description + "\n" + String(hub.message.prefix(2000))
    }

    static func invalidPage(_ error: Error) -> Bool {
        guard let code = (error as? HubError)?.code else { return false }
        return code == "stale_cursor" || code == "invalid_cursor"
    }

    /// One `coding.send` event folded into the run (pure, tested).
    static func step(_ run: LiveRun, event ev: [String: Any]) -> LiveRun {
        var r = run
        switch ev["kind"] as? String ?? "" {
        case "authorization":
            r.status = "authorizing"
        case "item":
            if let value = ev["item"] as? [String: Any] {
                r.items = NanoMuseCodingItem.merge(r.items, [NanoMuseCodingItem(value)])
            }
        case "started":
            r.status = "running"
            r.id = ev["run"] as? String ?? r.id
            if let sid = ev["session_id"] as? String, !sid.isEmpty { r.sessionId = sid }
        case "text":
            let t = ev["text"] as? String ?? ""
            if (ev["partial"] as? Bool) == true {
                r.current += t
            } else {
                r.output = [r.output, t].filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }.joined(separator: "\n")
                r.current = ""
            }
        case "tool":
            r.tools += 1
            r.lastTool = ev["text"] as? String ?? ""
        default:
            break
        }
        return r
    }

    /// The final reply folded into the run (pure, tested).
    static func finish(_ run: LiveRun, reply final: [String: Any]) -> LiveRun {
        var r = run
        r.id = final["id"] as? String ?? run.id
        if let sid = final["session_id"] as? String, !sid.isEmpty { r.sessionId = sid }
        r.status = (final["status"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? "done"
        let output = final["output"] as? String ?? ""
        r.output = output.trimmingCharacters(in: .whitespaces).isEmpty
            ? [run.output, run.current].filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }.joined(separator: "\n")
            : output
        r.current = ""
        r.tools = (final["tools"] as? NSNumber)?.intValue ?? run.tools
        r.error = final["error"] as? String ?? ""
        if let conflict = final["resume_conflict"] as? [String: Any],
           let continuation = conflict["continuation"] as? String {
            r.resumeConflict = ResumeConflict(process: conflict["process"] as? String ?? "", continuation: continuation)
        }
        if let items = final["timeline"] as? [[String: Any]] {
            r.items = NanoMuseCodingItem.merge(r.items, items.map(NanoMuseCodingItem.init))
        }
        return r
    }

    @MainActor
    static func stop(device: String, runId: String) async throws -> Bool {
        let reply = try await NanoMuseHub.shared.call(to: device, action: "coding.stop", args: ["run": runId], timeout: listTimeout)
        return (reply["stopped"] as? Bool) ?? false
    }
}

// MARK: - Screen

struct NanoMuseCodingView: View {
    @ObservedObject private var hub = NanoMuseHub.shared
    @State private var chosenId: String?
    @State private var listing = NanoMuseCodingListState()
    @State private var filter: String?
    @State private var open: NanoMuseCodingBridge.Session?
    @State private var openComputer: HubDevice?
    @State private var newWith: NanoMuseCodingBridge.Agent?
    @State private var newComputer: HubDevice?
    @State private var scope = "projects"
    @State private var search = ""

    private var computers: [HubDevice] {
        hub.others.filter { $0.online && $0.isComputer && ($0.actions.isEmpty || $0.actions.contains("coding.sessions")) }
    }
    private var computer: HubDevice? { computers.first { $0.id == chosenId } ?? computers.first }
    private var current: Bool { listing.device == computer?.id }
    private var agents: [NanoMuseCodingBridge.Agent] { current ? listing.agents : [] }
    private var sessions: [NanoMuseCodingBridge.Session] { current ? listing.sessions : [] }
    private var cursor: String? { current ? listing.cursor : nil }
    private var error: String? { current ? listing.error : nil }
    private var loading: Bool { current && listing.request != nil }

    private func show(_ session: NanoMuseCodingBridge.Session, on computer: HubDevice) {
        openComputer = computer
        open = session
    }

    var body: some View {
        List {
            Section {
                if computer == nil {
                    Text(AppLocalized("No computer with a coding agent is online. Run nanoMuse on the computer where Cursor, Codex or Claude Code is installed, signed in with this account."))
                        .font(.subheadline)
                    if let hint = NanoMuseCloud.account?.hint, !hint.isEmpty {
                        Text(String(format: AppLocalized("This phone is signed in as %@; the computer must use the same account."), hint))
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                }
                NavigationLink {
                    Form {
                        NanoMuseDevicesSection()
                        NanoMuseReachSection()
                    }
                    .navigationTitle(AppLocalized("Devices"))
                    .navigationBarTitleDisplayMode(.inline)
                } label: {
                    Label(AppLocalized("Devices"), systemImage: "desktopcomputer")
                }
            }
            if let computer {
                if computers.count > 1 {
                    Section {
                        Picker(AppLocalized("Computer"), selection: Binding(get: { computer.id }, set: { chosenId = $0 })) {
                            ForEach(computers) { c in Text(c.name).tag(c.id) }
                        }
                    }
                }
                if !agents.isEmpty {
                    Section {
                        ScrollView(.horizontal, showsIndicators: false) {
                            HStack(spacing: 8) {
                                chip(AppLocalized("All"), selected: filter == nil, running: 0, installed: true) { filter = nil }
                                ForEach(agents) { a in
                                    chip(a.name, selected: filter == a.id, running: a.running, installed: a.installed) { filter = a.id }
                                }
                            }
                            .padding(.vertical, 2)
                        }
                        .listRowInsets(EdgeInsets(top: 8, leading: 16, bottom: 8, trailing: 16))
                    }
                    Section(AppLocalized("Start something new")) {
                        ForEach(agents.filter { $0.installed && (filter == nil || filter == $0.id) }) { a in
                            Button {
                                if scope == "chats", a.richHistory {
                                    show(NanoMuseCodingBridge.Session(agent: a.id, id: "", title: "", workspace: "", updatedAt: nil, messages: 0, status: "idle", lastUser: "", lastAssistant: "", resumable: true, scope: "chats"), on: computer)
                                } else { newComputer = computer; newWith = a }
                            } label: {
                                Label(String(format: AppLocalized("New conversation with %@"), a.name), systemImage: "plus.bubble")
                            }
                        }
                    }
                }
                Section {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 8) {
                            chip(AppLocalized("Projects"), selected: scope == "projects", running: 0, installed: true) { scope = "projects" }
                            chip(AppLocalized("Chats"), selected: scope == "chats", running: 0, installed: true) { scope = "chats" }
                        }
                        .padding(.vertical, 2)
                    }
                    .listRowInsets(EdgeInsets(top: 8, leading: 16, bottom: 8, trailing: 16))
                }
                Section {
                    let shown = sessions.filter {
                        (filter == nil || $0.agent == filter) && $0.scope == scope &&
                        (search.isEmpty || ($0.title + " " + $0.workspace + " " + $0.lastUser).localizedCaseInsensitiveContains(search))
                    }
                    if shown.isEmpty {
                        Text(loading ? AppLocalized("Refreshing…") : AppLocalized("No sessions on this computer yet."))
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                    if scope == "projects" {
                        let workspaces = shown.reduce(into: [String]()) { paths, session in
                            if !paths.contains(session.workspace) { paths.append(session.workspace) }
                        }
                        ForEach(workspaces, id: \.self) { workspace in
                            DisclosureGroup {
                                Menu {
                                    ForEach(agents.filter(\.installed)) { agent in
                                        Button(agent.name) {
                                            show(NanoMuseCodingBridge.Session(agent: agent.id, id: "", title: "", workspace: workspace, updatedAt: nil, messages: 0, status: "idle", lastUser: "", lastAssistant: "", resumable: true), on: computer)
                                        }
                                    }
                                } label: { Label(AppLocalized("Start something new"), systemImage: "plus.bubble") }
                                ForEach(shown.filter { $0.workspace == workspace }, id: \.key) { s in
                                    Button { show(s, on: computer) } label: { sessionRow(s) }.buttonStyle(.plain)
                                }
                            } label: {
                                Label((workspace as NSString).lastPathComponent, systemImage: "folder")
                                    .font(.body.weight(.medium)).lineLimit(1)
                            }
                        }
                    } else {
                        ForEach(shown, id: \.key) { s in
                            Button { show(s, on: computer) } label: { sessionRow(s) }.buttonStyle(.plain)
                        }
                    }
                    if cursor != nil { Button(AppLocalized("Load more")) { load(more: true) }.disabled(loading) }
                } header: {
                    Text(AppLocalized("Recent sessions"))
                } footer: {
                    if let error { Text(error).foregroundStyle(.red) }
                }
            }
        }
        .navigationTitle(AppLocalized("Coding agents"))
        .navigationBarTitleDisplayMode(.inline)
        .tint(NanoMuseTones.action)
        .searchable(text: $search, prompt: AppLocalized("Search"))
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    load()
                } label: {
                    if loading { ProgressView() } else { Image(systemName: "arrow.clockwise") }
                }
                .disabled(loading || computer == nil)
                .accessibilityLabel(AppLocalized("Refresh"))
            }
        }
        .task(id: computer?.id) {
            if computer != nil { load() } else { listing = NanoMuseCodingListState() }
        }
        .fullScreenCover(item: $open, onDismiss: { load() }) { s in
            if let computer = openComputer {
                NavigationStack {
                    NanoMuseCodingSessionView(computer: computer, session: s, agentName: agents.first { $0.id == s.agent }?.name ?? s.agent,
                                             onNewSession: { open = $0 })
                        .id(computer.id + "|" + s.key)
                        .toolbar {
                            ToolbarItem(placement: .cancellationAction) { Button(AppLocalized("Done")) { open = nil } }
                        }
                }
            }
        }
        .sheet(item: $newWith) { a in
            NanoMuseCodingNewSheet(agent: a, device: newComputer?.id ?? "", scope: a.richHistory ? scope : "projects", workspaces: Array(Set((listing.device == newComputer?.id ? listing.sessions : []).filter { $0.scope == "projects" }.map(\.workspace).filter { !$0.isEmpty })).sorted()) { workspace in
                newWith = nil
                if let computer = newComputer {
                    show(NanoMuseCodingBridge.Session(agent: a.id, id: "", title: "", workspace: workspace, updatedAt: nil, messages: 0, status: "idle", lastUser: "", lastAssistant: "", resumable: true, scope: a.richHistory ? scope : "projects"), on: computer)
                }
            }
            .presentationDetents([.medium])
        }
    }

    private func load(more: Bool = false) {
        guard let dev = computer else { return }
        let request = listing.begin(device: dev.id, more: more)
        Task { @MainActor in
            do {
                let found = try await NanoMuseCodingBridge.agents(device: dev.id)
                let page = try await NanoMuseCodingBridge.sessionPage(device: dev.id, cursor: request.cursor)
                listing.complete(request, selectedDevice: computer?.id,
                                 agents: found, sessions: page.sessions, cursor: page.cursor)
            } catch {
                listing.fail(request, selectedDevice: computer?.id,
                             message: NanoMuseHubErrors.describe(error),
                             invalidCursor: NanoMuseCodingBridge.invalidPage(error))
            }
        }
    }

    private func chip(_ label: String, selected: Bool, running: Int, installed: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 6) {
                Text(label).font(.subheadline.weight(.medium))
                if running > 0 {
                    Text("\(running)").font(.caption2.weight(.semibold))
                        .padding(.horizontal, 5).padding(.vertical, 1)
                        .background(NanoMuseTones.action.opacity(0.18), in: Capsule())
                }
            }
            .foregroundStyle(installed ? Color.primary : Color.secondary)
            .padding(.horizontal, 12)
            .padding(.vertical, 7)
            .background(selected ? NanoMuseTones.action.opacity(0.15) : NanoMuseTones.fill, in: Capsule())
            .overlay(Capsule().stroke(selected ? NanoMuseTones.action : Color.clear, lineWidth: 1))
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }

    private func sessionRow(_ s: NanoMuseCodingBridge.Session) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack {
                Text(s.title.isEmpty ? (s.lastUser.isEmpty ? AppLocalized("Untitled") : s.lastUser) : s.title)
                    .font(.body.weight(.medium)).lineLimit(1)
                Spacer()
                Text(s.status == "running" ? AppLocalized("running") : (s.updatedAt.map { NanoMuseDrawer.when($0) } ?? ""))
                    .font(.caption).foregroundStyle(s.status == "running" ? NanoMuseTones.action : Color.secondary)
            }
            HStack(spacing: 6) {
                Text(agents.first { $0.id == s.agent }?.name ?? s.agent).font(.caption.weight(.medium)).foregroundStyle(.secondary)
                if !s.workspace.isEmpty {
                    Text((s.workspace as NSString).lastPathComponent).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                }
            }
            if !s.lastAssistant.isEmpty {
                Text(s.lastAssistant).font(.footnote).foregroundStyle(.secondary).lineLimit(2)
            }
        }
        .contentShape(Rectangle())
    }
}

/// "New conversation with Cursor": the project folder on the computer, then Start.
struct NanoMuseCodingNewSheet: View {
    var agent: NanoMuseCodingBridge.Agent
    var device = ""
    var scope = "projects"
    var workspaces: [String]
    var onStart: (String) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var workspace = ""
    @State private var validating = false
    @State private var error: String?

    var body: some View {
        NavigationStack {
            Form {
                if scope == "projects" { Section {
                    TextField(AppLocalized("Project folder on the computer"), text: $workspace)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    if !workspaces.isEmpty {
                        ForEach(workspaces, id: \.self) { w in
                            Button(w) { workspace = w }.font(.footnote).lineLimit(1)
                        }
                    }
                } footer: {
                    Text(AppLocalized("The agent works inside this folder. Leave it empty for the computer's default."))
                } }
                if let error { Text(error).font(.footnote).foregroundStyle(.red) }
                if validating { ProgressView() }
            }
            .navigationTitle(String(format: AppLocalized("New conversation with %@"), agent.name))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button(AppLocalized("Cancel")) { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button(AppLocalized("Start")) { start() }.disabled(validating)
                }
            }
        }
    }

    private func start() {
        let path = workspace.trimmingCharacters(in: .whitespacesAndNewlines)
        guard agent.richHistory, !path.isEmpty, !device.isEmpty else { onStart(path); return }
        validating = true
        error = nil
        Task { @MainActor in
            defer { validating = false }
            do {
                let reply = try await NanoMuseHub.shared.call(to: device, action: "coding.project.validate", args: ["workspace": path], timeout: NanoMuseCodingBridge.listTimeout)
                onStart(reply["workspace"] as? String ?? path)
            } catch { self.error = NanoMuseHubErrors.describe(error) }
        }
    }
}

/// One session: the transcript so far, the run in flight, a composer.
struct NanoMuseCodingSessionView: View {
    var computer: HubDevice
    var session: NanoMuseCodingBridge.Session
    var agentName: String
    var onNewSession: ((NanoMuseCodingBridge.Session) -> Void)?
    @Environment(\.scenePhase) private var scenePhase

    @State private var sessionId: String
    @State private var transcript: [NanoMuseCodingItem] = []
    @State private var live: NanoMuseCodingBridge.LiveRun?
    @State private var draft = ""
    @State private var loading = false
    @State private var error: String?
    @State private var cursor: String?
    @State private var version = ""
    @State private var rich = false
    @State private var detail: NanoMuseCodingDetailTarget?
    @State private var watchingRun = ""
    @State private var loadedSession = ""
    @State private var preSendIds: Set<String> = []
    @State private var initialScrollToken = 0
    @State private var firstMessageSent = false
    @State private var showResumeConflict = false

    init(computer: HubDevice, session: NanoMuseCodingBridge.Session, agentName: String,
         onNewSession: ((NanoMuseCodingBridge.Session) -> Void)? = nil) {
        self.computer = computer
        self.session = session
        self.agentName = agentName
        self.onNewSession = onNewSession
        _sessionId = State(initialValue: session.id)
    }

    private var continuesAsNew: Bool { !session.id.isEmpty && !session.resumable }

    var body: some View {
        VStack(spacing: 0) {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 10) {
                        if transcript.isEmpty && live == nil {
                            Text(loading ? AppLocalized("Refreshing…")
                                 : sessionId.isEmpty ? String(format: AppLocalized("A new conversation with %@. Your first message starts it on the computer."), agentName)
                                 : AppLocalized("Nothing readable in this session yet."))
                                .font(.subheadline).foregroundStyle(.secondary)
                                .frame(maxWidth: .infinity, alignment: .center)
                                .padding(.top, 40)
                        }
                        if cursor != nil {
                            Button(AppLocalized("Load more")) { reload(more: true) }.disabled(loading)
                                .padding(.horizontal, 12)
                        }
                        ForEach(NanoMuseCodingTurn.group(transcript)) { turn in
                            NanoMuseCodingTurnView(turn: turn,
                                onDetail: { detail = .item($0, runId: "") },
                                onFile: { detail = .file($0, runId: "") })
                                .padding(.horizontal, 12)
                        }
                        if let live {
                            if !transcript.contains(where: { $0.role == "user" && $0.text == live.text && !preSendIds.contains($0.id) }) {
                                bubble(role: "user", text: live.text)
                            }
                            if live.items.isEmpty { liveBlock(live).id("live") }
                            else {
                                ForEach(NanoMuseCodingTurn.group(live.items)) { turn in
                                    NanoMuseCodingTurnView(turn: turn,
                                        onDetail: { detail = .item($0, runId: live.id) },
                                        onFile: { detail = .file($0, runId: live.id) })
                                        .padding(.horizontal, 12)
                                }
                                if !live.current.isEmpty {
                                    NanoMuseInlineMarkdown(text: live.current).font(.callout).padding(.horizontal, 12)
                                }
                                if live.isActive { ProgressView().padding(.horizontal, 12) }
                                if live.status == "stopped" { Text(AppLocalized("Stopped.")).font(.caption).foregroundStyle(.secondary).padding(.horizontal, 12) }
                                if !live.error.isEmpty { Text(live.error).font(.footnote).foregroundStyle(.red).padding(.horizontal, 12) }
                            }
                        }
                        if let error {
                            Text(error).font(.footnote).foregroundStyle(.red).padding(.horizontal, 14)
                        }
                        Color.clear.frame(height: 1).id("bottom")
                    }
                    .padding(.vertical, 12)
                }
                .overlay(alignment: .bottomTrailing) {
                    Button { proxy.scrollTo("bottom", anchor: .bottom) } label: {
                        Image(systemName: "arrow.down").padding(10)
                            .background(NanoMuseTones.surface, in: Circle())
                    }
                    .accessibilityLabel(AppLocalized("Latest message"))
                    .padding(12)
                }
                .nmOnChange(of: initialScrollToken) { _ in proxy.scrollTo("bottom", anchor: .bottom) }
            }
            Divider()
            HStack(alignment: .bottom, spacing: 8) {
                TextField(continuesAsNew ? AppLocalized("Made in the IDE: continues as a new chat in the same workspace…") : String(format: AppLocalized("Message %@…"), agentName), text: $draft, axis: .vertical)
                    .lineLimit(1...5)
                    .textFieldStyle(.roundedBorder)
                if live?.isActive == true || !watchingRun.isEmpty {
                    Button {
                        Task { await stop() }
                    } label: {
                        Image(systemName: "stop.circle.fill").font(.system(size: 28))
                    }
                    .accessibilityLabel(AppLocalized("Stop"))
                    .disabled(live?.id.isEmpty != false && watchingRun.isEmpty)
                } else {
                    Button {
                        send()
                    } label: {
                        Image(systemName: "arrow.up.circle.fill").font(.system(size: 28))
                    }
                    .disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    .accessibilityLabel(AppLocalized("Send"))
                }
            }
            .padding(10)
        }
        .background(NanoMuseTones.canvas.ignoresSafeArea())
        .navigationTitle(session.title.isEmpty ? String(format: AppLocalized("New conversation with %@"), agentName) : session.title)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button { reload() } label: { Image(systemName: "arrow.clockwise") }
                    .disabled(loading)
                    .accessibilityLabel(AppLocalized("Refresh"))
            }
        }
        .sheet(item: $detail) { target in
            switch target {
            case let .item(item, runId):
                NanoMuseCodingItemDetail(computer: computer, agent: session.agent, sessionId: sessionId, runId: runId, item: item)
            case let .file(file, runId):
                NavigationStack {
                    NanoMuseCodingDiffView(computer: computer, agent: session.agent, sessionId: sessionId, runId: runId, file: file)
                        .toolbar {
                            ToolbarItem(placement: .cancellationAction) {
                                Button(AppLocalized("Done")) { detail = nil }
                            }
                        }
                }.tint(NanoMuseTones.action)
            }
        }
        .nmOnChange(of: live?.resumeConflict) { conflict in
            if conflict != nil {
                NanoMuseCodingBridge.log.info("conflict_alert run=\(live?.id ?? "") session=\(sessionId)")
                showResumeConflict = true
            }
        }
        .alert(AppLocalized("Conversation in use"), isPresented: $showResumeConflict) {
            Button(AppLocalized("Cancel"), role: .cancel) {
                NanoMuseCodingBridge.log.info("conflict_cancel run=\(live?.id ?? "")")
                draft = live?.text ?? ""
                live = nil
            }
            Button(AppLocalized("Create conversation")) {
                guard let conflict = live?.resumeConflict else { return }
                var next = session
                next.id = ""
                next.title = ""
                next.firstMessage = conflict.continuation
                // A continuation belongs in the original workspace, not the standalone Chats root.
                next.scope = "projects"
                NanoMuseCodingBridge.log.info("conflict_create run=\(live?.id ?? "") prompt_chars=\(next.firstMessage.count) callback=\(onNewSession != nil)")
                onNewSession?(next)
            }
        } message: {
            Text(String(format: AppLocalized("This conversation is occupied by %@ and cannot be continued. Create a new conversation with the previous conversation's recent context?"),
                        live?.resumeConflict?.process.isEmpty == false ? live?.resumeConflict?.process ?? "" : AppLocalized("another process")))
        }
        .task(id: sessionId) {
            NanoMuseCodingBridge.log.info("coding-resume-v2 page_task session=\(sessionId) first_chars=\(session.firstMessage.count) first_sent=\(firstMessageSent)")
            if !firstMessageSent, !session.firstMessage.isEmpty {
                firstMessageSent = true
                send(session.firstMessage)
            }
            if !sessionId.isEmpty, live?.isActive != true { await fetch(more: false) }
            while !Task.isCancelled {
                do { try await Task.sleep(nanoseconds: 3_000_000_000) } catch { return }
                guard scenePhase == .active, !loading else { continue }
                let requested = sessionId
                let owned = live
                guard !requested.isEmpty || owned?.id.isEmpty == false else { continue }
                do {
                    let reply = try await NanoMuseHub.shared.call(to: computer.id, action: rich ? "coding.watch" : "coding.runs",
                        args: ["agent": session.agent, "session_id": requested, "version": version,
                               "run_id": owned?.id ?? "", "limit": 50],
                        timeout: NanoMuseCodingBridge.listTimeout)
                    guard !Task.isCancelled, sessionId == requested else { continue }
                    let runs = reply["runs"] as? [[String: Any]] ?? []
                    if let current = live, current.id == owned?.id, !current.id.isEmpty {
                        let updated = NanoMuseCodingBridge.snapshot(current, reply: reply)
                        if updated.status != current.status || updated.sessionId != current.sessionId || updated.resumeConflict != current.resumeConflict {
                            NanoMuseCodingBridge.log.info("watch_update run=\(updated.id) status=\(updated.status) result=\(updated.sessionId) conflict=\(updated.resumeConflict != nil)")
                        }
                        live = updated
                        if !updated.sessionId.isEmpty, updated.sessionId != requested {
                            sessionId = updated.sessionId
                            continue
                        }
                    }
                    watchingRun = runs.first {
                        $0["status"] as? String == "running" && $0["agent"] as? String == session.agent &&
                        $0["session_id"] as? String == requested
                    }?["id"] as? String ?? ""
                    error = nil
                    let ended = owned?.isActive == true && live?.isActive == false
                    if ended || (live?.isActive != true && reply["changed"] as? Bool == true && transcript.count <= 100) {
                        await fetch(more: false)
                    }
                } catch { self.error = NanoMuseHubErrors.describe(error) }
            }
        }
    }

    private func reload(more: Bool = false) {
        Task { @MainActor in await fetch(more: more) }
    }

    private func fetch(more: Bool) async {
        guard !sessionId.isEmpty, live?.isActive != true else { return }
        let requested = sessionId
        guard !loading || loadedSession != requested else { return }
        loading = true
        defer { if sessionId == requested { loading = false } }
        let initial = loadedSession != requested
        if loadedSession != requested {
            transcript = []
            cursor = nil
            loadedSession = requested
        }
        do {
            let page = try await NanoMuseCodingBridge.history(device: computer.id, agent: session.agent, sessionId: requested, cursor: more ? cursor : nil)
            guard sessionId == requested, !Task.isCancelled else { return }
            let combined = more ? NanoMuseCodingItem.merge(page.items, transcript) : page.items
            if let live {
                let recorded = NanoMuseCodingBridge.hasRecordedReply(live, in: combined, before: preSendIds)
                let users = combined.filter { $0.role == "user" && !preSendIds.contains($0.id) }
                NanoMuseCodingBridge.log.info("history_match run=\(live.id) session=\(requested) status=\(live.status) items=\(combined.count) new_users=\(users.count) user_chars=\(users.map { String($0.text.count) }.joined(separator: ",")) live_chars=\(live.text.count) exact=\(users.contains { $0.text == live.text }) clear_live=\(recorded)")
                if recorded { self.live = nil }
            }
            transcript = combined
            if initial { initialScrollToken += 1 }
            cursor = page.cursor
            version = page.version
            rich = page.rich
            watchingRun = page.runs.first { $0["status"] as? String == "running" }?["id"] as? String ?? ""
            error = nil
        } catch {
            guard sessionId == requested, !Task.isCancelled else { return }
            if NanoMuseCodingBridge.invalidPage(error) { cursor = nil }
            self.error = NanoMuseHubErrors.describe(error)
        }
    }

    private func send(_ firstMessage: String? = nil) {
        let text = (firstMessage ?? draft).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, live?.isActive != true, watchingRun.isEmpty else { return }
        draft = ""
        preSendIds = Set(transcript.map(\.id))
        error = nil
        live = NanoMuseCodingBridge.LiveRun(text: text, status: "starting")
        NanoMuseCodingBridge.log.info("send_start session=\(sessionId) text_chars=\(text.count) first_message=\(firstMessage != nil) history_items=\(transcript.count)")
        Task { @MainActor in
            do {
                let final = try await NanoMuseCodingBridge.send(device: computer.id, agent: session.agent, text: text, sessionId: sessionId, workspace: session.workspace, scope: session.scope) { updated in
                    live = updated
                }
                live = final
                if !final.sessionId.isEmpty, final.sessionId != sessionId {
                    sessionId = final.sessionId
                } else if !final.isActive {
                    reload()
                }
            } catch {
                NanoMuseCodingBridge.log.warning("send_failed session=\(sessionId) code=\((error as? HubError)?.code ?? "transport")")
                live?.status = "failed"
                live?.error = NanoMuseCodingBridge.failure(error)
            }
        }
    }

    private func stop() async {
        let id = live?.id.isEmpty == false ? live?.id ?? "" : watchingRun
        guard !id.isEmpty else { return }
        do { _ = try await NanoMuseCodingBridge.stop(device: computer.id, runId: id) }
        catch { self.error = NanoMuseHubErrors.describe(error) }
    }

    private func bubble(role: String, text: String) -> some View {
        let user = role == "user"
        return HStack {
            if user { Spacer(minLength: 40) }
            Text(text)
                .font(.callout)
                .textSelection(.enabled)
                .padding(.horizontal, 12).padding(.vertical, 8)
                .background(user ? NanoMuseTones.action.opacity(0.15) : NanoMuseTones.surface, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            if !user { Spacer(minLength: 40) }
        }
        .padding(.horizontal, 12)
    }

    private func liveBlock(_ run: NanoMuseCodingBridge.LiveRun) -> some View {
        let body = [run.output, run.current].filter { !$0.isEmpty }.joined(separator: "\n")
        let status: String? = {
            switch run.status {
            case "authorizing": return AppLocalized("Waiting for authorization…")
            case "starting": return AppLocalized("Working…")
            case "running": return body.isEmpty && run.lastTool.isEmpty ? AppLocalized("Working…") : nil
            case "failed": return String(format: AppLocalized("Failed: %@"), run.error.isEmpty ? "?" : run.error)
            case "stopped": return AppLocalized("Stopped.")
            default: return run.tools > 0 ? String(format: AppLocalized("%d tool calls"), run.tools) : nil
            }
        }()
        return HStack {
            VStack(alignment: .leading, spacing: 6) {
                if !body.isEmpty { Text(body).font(.callout).textSelection(.enabled) }
                if run.isActive, !run.lastTool.isEmpty {
                    Label(run.lastTool, systemImage: "wrench").font(.caption).foregroundStyle(.secondary).lineLimit(1)
                }
                if let status {
                    HStack(spacing: 6) {
                        if run.isActive { ProgressView().controlSize(.small) }
                        Text(status).font(.caption).foregroundStyle(run.status == "failed" ? Color.red : Color.secondary)
                    }
                }
            }
            .padding(.horizontal, 12).padding(.vertical, 8)
            .background(NanoMuseTones.surface, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            Spacer(minLength: 40)
        }
        .padding(.horizontal, 12)
    }
}
