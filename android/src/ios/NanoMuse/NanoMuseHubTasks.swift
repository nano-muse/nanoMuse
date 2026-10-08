//
//  NanoMuseHubTasks.swift
//  nanoMuse
//
//  The iPhone as a target of other devices' `task` calls: "@iPhone …" said on
//  the Android phone or a computer reaches this phone's Muse through the hub,
//  runs here headless and the answer goes back. One local session per remote
//  conversation, remembered in UserDefaults; the person is not looking at
//  this phone, so a step that needs permission is declined while the app is
//  in the background. `stop {call}` or `stop {conversation}` from the device
//  that asked ends the run and the task answers `cancelled`. Android:
//  HubActions.task / HubTasks; runtime: nanomuse/hub/service.py _task. Works
//  while nanoMuse is open, that is the hub connection itself.
//

import Combine
import Foundation
import UIKit

@MainActor
enum NanoMuseHubTasks {
    /// What goes back through the hub: a result body, or an error code with its message.
    enum Outcome {
        case result([String: Any])
        case failure(code: String, message: String)
    }

    static let timeout: TimeInterval = 10 * 60
    static let source = "nanomuse-hub"

    /// Remote conversation → local session, as Android's `hub.session.<conversation>`.
    private static func key(_ conversation: String) -> String { "hub.session.\(conversation)" }

    /// A task under way here: who asked, in which conversation, and whether a `stop` ended it.
    struct Run {
        let senderId: String
        let conversation: String
        var stopped = false
    }

    /// The runs under way, by the id of their `task` frame (docs/hub.md: `stop {call}` names it).
    static var running: [String: Run] = [:]

    /// The conversation a task from `senderId` lands in: the one it names, else one per device.
    static func conversationKey(senderId: String, conversation: String?) -> String {
        let named = (conversation ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return named.isEmpty ? "from-\(senderId.isEmpty ? "unknown" : senderId)" : named
    }

    /// The run a `stop` from `senderId` would end: the one opened by `callId`, else the sender's
    /// run in `conversation` (its own per-device conversation when none is named). Only the device
    /// that asked for a task may stop it; nil when there is nothing of theirs to stop.
    static func find(senderId: String, callId: String?, conversation: String?) -> String? {
        if let callId, !callId.isEmpty, let run = running[callId] {
            return run.senderId == senderId ? callId : nil
        }
        let wanted = conversationKey(senderId: senderId, conversation: conversation)
        return running.first { $0.value.conversation == wanted && $0.value.senderId == senderId }?.key
    }

    // MARK: - task

    /// What this phone's Muse is told. A web console speaks for the person directly; a device's
    /// Muse gets the context (who asked, from where). `language` is the asking device's screen
    /// language (`task.language`, docs/hub.md, a BCP-47 tag): when it is there the answer is
    /// asked for in it, so the person reads the result in the language of the device they used;
    /// without it the model goes by the text.
    static func prompt(text: String, senderName: String, senderKind: String, language: String?) -> String {
        let tag = (language ?? "").trimmingCharacters(in: .whitespacesAndNewlines).prefix(20)
        var lines: [String] = []
        if senderKind != "web" {
            lines.append(String(format: AppLocalized("The following was asked from %@, one of the user's other devices. Do it on this phone and answer in the user's language."), senderName))
        }
        if !tag.isEmpty {
            // For the model, in English: the device that asked shows its screens in this language.
            lines.append("Answer in the language tagged \(tag); the device that asked shows its screens in it.")
        }
        lines.append(text)
        return lines.joined(separator: "\n\n")
    }

    /// Runs `args.text` on this phone's Muse for the device in `from`; `event` carries progress.
    /// `callId` is the task frame's id, what a `stop {call}` from the same device names.
    static func run(callId: String, args: [String: Any], from: [String: Any], event: @escaping ([String: Any]) -> Void) async -> Outcome {
        let text = (args["text"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return .failure(code: "usage", message: "text is required") }
        guard RootfsManager.shared.isInstalled else {
            return .failure(code: "not_ready", message: "nanoMuse on the iPhone is still starting")
        }
        let store = ProviderConfigStore.shared
        guard store.defaultPrimaryGroupId != nil || !store.modelEntries.isEmpty else {
            return .failure(code: "no_model", message: "this iPhone has no model to think with; sign in to nanoMuse Cloud there")
        }

        let senderId = (from["id"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? "unknown"
        let senderName = (from["name"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? "another device"
        let senderKind = from["kind"] as? String ?? "computer"
        let conversation = conversationKey(senderId: senderId, conversation: args["conversation"] as? String)
        guard !running.values.contains(where: { $0.conversation == conversation }) else {
            return .failure(code: "busy", message: "this conversation is already busy on the iPhone")
        }

        // The session for this conversation, when it still exists; NanoMuseHeadless creates one otherwise
        // (a new one is only known once the run ends, so the event names the session when there is one).
        var sessionId = UserDefaults.standard.string(forKey: key(conversation))
        if let sid = sessionId, !(await ChatStore.shared.sessionExists(id: sid)) { sessionId = nil }
        var thinking: [String: Any] = ["stage": "thinking"]
        if let sessionId { thinking["session"] = sessionId }
        event(thinking)

        let prompt = Self.prompt(text: text, senderName: senderName, senderKind: senderKind, language: args["language"] as? String)

        running[callId] = Run(senderId: senderId, conversation: conversation)
        defer { running[callId] = nil }
        let watch = PermissionWatch()
        let started = Date()
        let outcome = await NanoMuseHeadless.run(
            prompt: prompt,
            sessionId: sessionId,
            title: String(format: AppLocalized("From %@"), senderName),
            source: source,
            timeout: timeout
        )
        let declined = watch.stop()
        if let sid = outcome.sessionId { UserDefaults.standard.set(sid, forKey: key(conversation)) }

        var answer = outcome.text.trimmingCharacters(in: .whitespacesAndNewlines)
        // a `stop` ended it: the task answers `cancelled`, as docs/hub.md says and Android does
        if running[callId]?.stopped == true {
            return .failure(code: "cancelled", message: "stopped from \(senderName)")
        }
        let timedOut = !outcome.ok && Date().timeIntervalSince(started) >= timeout - 1
        if timedOut {
            if let sid = outcome.sessionId { ViewModelCache.shared.get(for: sid)?.cancel() }
            return .failure(code: "timeout", message: "the iPhone's agent did not finish within ten minutes")
        }
        if !outcome.ok, answer.isEmpty {
            return .failure(code: "failed", message: outcome.note.flatMap { $0.isEmpty ? nil : "the iPhone's agent could not run this: \($0)" } ?? "the iPhone's agent could not run this")
        }
        if declined > 0 {
            let note = AppLocalized("A step needed permission on this iPhone and was declined: nobody was there to approve it.")
            answer = answer.isEmpty ? note : answer + "\n\n" + note
        }
        return .result([
            "text": answer.isEmpty ? "(no answer)" : answer,
            "conversation": conversation,
            "session": outcome.sessionId ?? "",
            "device": NanoMuseHub.shared.name,
            "status": outcome.ok ? "Done" : "Error",
        ])
    }

    // MARK: - stop

    /// Cancels the sender's run named by `args.call` (the task frame's id) or `args.conversation`
    /// (default: the sender's own), when one is under way here; false when there is none of theirs.
    static func stop(args: [String: Any], from: [String: Any]) -> Bool {
        let senderId = (from["id"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? "unknown"
        guard let callId = find(senderId: senderId, callId: args["call"] as? String, conversation: args["conversation"] as? String),
              let run = running[callId] else { return false }
        running[callId]?.stopped = true
        guard let sid = UserDefaults.standard.string(forKey: key(run.conversation)),
              let vm = ViewModelCache.shared.get(for: sid), vm.isProcessing else {
            // the run has not reached its session yet (or the session is gone): the flag alone
            // makes the task answer `cancelled` when it returns
            return true
        }
        vm.cancel()
        return true
    }

    // MARK: - Permissions while nobody looks

    /// Declines "Ask Once" prompts that come up during the run while the app is not on screen;
    /// with the app in front, the person answers the card as usual (or the 30 s timeout does).
    @MainActor private final class PermissionWatch {
        private var cancellable: AnyCancellable?
        private(set) var declined = 0

        init() {
            cancellable = OffloadPermissionManager.shared.$pendingRequest
                .receive(on: RunLoop.main)
                .sink { [weak self] request in
                    guard let request else { return }
                    let id = request.id
                    Task { @MainActor [weak self] in
                        guard let self, UIApplication.shared.applicationState != .active else { return }
                        self.declined += 1
                        OffloadPermissionManager.shared.respond(to: id, allowed: false)
                    }
                }
        }

        func stop() -> Int {
            cancellable?.cancel()
            cancellable = nil
            return declined
        }
    }
}
