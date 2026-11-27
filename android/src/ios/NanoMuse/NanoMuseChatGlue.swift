//
//  NanoMuseChatGlue.swift
//  nanoMuse
//
//  The few places the upstream chat pipeline hands control to nanoMuse —
//  one `// nanoMuse:` line each in AIChatViewModel: before a send, after a
//  turn, while the system prompt is assembled. Everything else lives here.
//  Android: the same hooks in ChatViewModel for AvatarFlow, GoalFlow,
//  FeedFlow, FirstConversation and SessionAddenda.
//

import Foundation

// MARK: - The Muse header's menu → the chat

extension Notification.Name {
    /// `object` is the chat's session key (`nmSessionKey`); `userInfo["action"]` a
    /// `NanoMuseChatAction` raw value. AIChatView acts on it for its own chat.
    static let nanoMuseChatAction = Notification.Name("nanoMuse.chatAction")
}

/// What the Muse header's ••• menu can ask of the chat under it (the entries
/// Android's ChatScreen menu has; the shell's own rows stay in the shell).
enum NanoMuseChatAction: String {
    case newChat, model, thinking, clearChat, terminal, browser, files, tokenUsage

    static func post(_ action: NanoMuseChatAction, session: String) {
        NotificationCenter.default.post(name: .nanoMuseChatAction, object: session, userInfo: ["action": action.rawValue])
    }

    /// The action a notification carries, when it is for the given chat.
    static func from(_ note: Notification, for session: String) -> NanoMuseChatAction? {
        guard (note.object as? String) == session, let raw = note.userInfo?["action"] as? String else { return nil }
        return NanoMuseChatAction(rawValue: raw)
    }
}

@MainActor
extension AIChatViewModel {
    /// What addenda, flows and cards key on: the real session, or the draft until it is created.
    var nmSessionKey: String { sessionId ?? draftId ?? "draft" }

    // MARK: Hooks

    /// Before the model sees a message. True when nanoMuse handled the text itself (the
    /// composer is cleared, nothing is sent); false to carry on as usual.
    func nmInterceptSend(_ text: String) -> Bool {
        guard !text.isEmpty else { return false }
        if NanoMuseAvatarFlow.shared.handle(text, in: self) { return true }
        if NanoMuseFirstConversation.shared.handle(text, in: self) { return true }
        // C7: "@Pixel 8 open the calendar" — the task runs on that device, its answer comes back here.
        if NanoMuseDeviceMention.handle(text, in: self) { return true }
        return false
    }

    /// After a turn ended: goals, the feed, the naming flow read the reply; addenda tick; sync pushes.
    func nmAfterTurn() {
        let key = nmSessionKey
        let reply = nmLastAssistantText()
        // the record hears a turn that ended in an error (a Stop was told at the Stop); the next turn is the person's again
        NanoMuseFeedback.shared.turnEnded(session: key, errored: messages.last.map { $0.role == .assistant && !($0.error ?? "").isEmpty } ?? false)
        NanoMuseGoalFlow.afterTurn(session: key, assistantText: reply)
        NanoMuseFeedFlow.afterTurn(session: key, assistantText: reply)
        NanoMuseFirstConversation.shared.afterTurn(session: key, assistantText: reply, vm: self)
        NanoMuseSessionAddenda.onTurnFinished(session: key)
        NanoMuseSync.shared.turnFinished(session: key)
        // "Use nanoMuse Cloud this time" covered this one turn; where the turn ran decides whether the next failure offers it
        NanoMuseCloudOnce.turnEnded(onCloud: resolveCurrentEntry()?.providerInstanceId == NanoMuseCloud.instance?.id)
    }

    /// Appended to the system prompt of this session (empty when there is nothing to add).
    func nmSystemPromptAddenda() -> String {
        // A draft became a session: carry what was registered under the draft's id.
        if let draft = draftId, let real = sessionId, draft != real { nmRebind(from: draft, to: real) }
        let key = nmSessionKey
        var parts: [String] = []
        if let user = NanoMuseSystemFiles.userPromptFragment() { parts.append(user) }
        if let goal = NanoMuseGoalFlow.systemAddendum(session: key) { parts.append(goal) }
        if let feed = NanoMuseFeedFlow.systemAddendum(session: key, memoryEnabled: memoryEnabled) { parts.append(feed) }
        if let addenda = NanoMuseSessionAddenda.forPrompt(session: key) { parts.append(addenda) }
        if let naming = NanoMuseFirstConversation.shared.systemAddendum(session: key) { parts.append(naming) }
        guard !parts.isEmpty else { return "" }
        return "\n\n" + parts.joined(separator: "\n\n")
    }

    /// A draft became a session: everything keyed on the draft follows it.
    func nmRebind(from draft: String, to real: String) {
        NanoMuseSessionAddenda.rebind(from: draft, to: real)
        NanoMuseFirstConversation.shared.rebind(from: draft, to: real)
        NanoMuseAvatarFlow.shared.rebind(from: draft, to: real)
    }

    // MARK: Helpers

    /// The last assistant reply's text, fences included.
    func nmLastAssistantText() -> String? {
        guard let msg = messages.last(where: { $0.role == .assistant }) else { return nil }
        let text = msg.blocks.filter { $0.kind == .text }.map(\.content).joined(separator: "\n")
        if !text.isEmpty { return text }
        return msg.content.isEmpty ? nil : msg.content
    }

    /// A line from the person and a line from the agent, in the chat and in the store, with no
    /// model call: what the avatar flow and the naming flow say for themselves.
    func nmLocalTurn(user: String? = nil, assistant: String? = nil) {
        var agentMessages: [AgentMessage] = []
        if let user, !user.isEmpty {
            messages.append(ChatMessage(role: .user, content: user))
            agentMessages.append(AgentMessage(role: .user, parts: [.text(user)]))
        }
        if let assistant, !assistant.isEmpty {
            let msg = ChatMessage(role: .assistant, content: assistant, blocks: [AssistantBlock(kind: .text, content: assistant)])
            messages.append(msg)
            agentMessages.append(AgentMessage(role: .assistant, parts: [.text(assistant)]))
        }
        guard !agentMessages.isEmpty else { return }
        inputText = ""
        scrollToBottomSignal.send()
        Task { @MainActor [weak self] in await self?.nmRecord(agentMessages) }
    }

    /// Into the history and the store, after the session exists: rows the chat already shows.
    func nmRecord(_ agentMessages: [AgentMessage]) async {
        let before = nmSessionKey
        await ensureSession()
        if before != nmSessionKey { nmRebind(from: before, to: nmSessionKey) }
        for var m in agentMessages {
            let idx = agentHistory.count
            agentHistory.append(m)
            if let id = await persistAgentMessage(m), idx < agentHistory.count {
                m.dbMessageId = id
                agentHistory[idx].dbMessageId = id
            }
        }
    }

    /// Put words in the composer without sending ("Change your avatar to ").
    func nmPrefill(_ text: String) {
        inputText = text
    }

    /// Send a message on the person's behalf (an idea's "Try it", a goal's "Start").
    func nmSendNow(_ text: String) {
        inputText = text
        send()
    }

    // MARK: C9 presence

    /// Put "{device} is working…" under the last message when it is another device's user line
    /// and presence says that device is at work on this conversation — with the run's step or
    /// "waiting for you" when the frame said so (relay 0.31); take it off otherwise (the reply
    /// arrived, presence said done, or ten minutes passed). Cheap: the last row only.
    func nmApplyPresence() {
        let key = nmSessionKey
        let last = messages.last
        let remote = last.map { $0.role == .user && $0.nmFromDevice != nil } ?? false
        var entry: NanoMusePresence.Working?
        if remote, let sid = sessionId, let cid = NanoMuseSync.shared.cid(for: sid) {
            entry = NanoMusePresence.shared.working(for: cid)
        }
        let device = NanoMusePresence.line(lastIsRemoteUser: remote, lastFromDevice: last?.nmFromDevice, entry: entry, me: NanoMuseHub.shared.deviceId)
        NanoMusePresence.shared.show(device.map { NanoMusePresence.sentence(device: $0, entry: entry) }, on: last, session: key)
    }
}
