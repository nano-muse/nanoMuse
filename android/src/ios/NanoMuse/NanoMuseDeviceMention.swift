//
//  NanoMuseDeviceMention.swift
//  nanoMuse
//
//  Contract C7, rule 8: a message that starts with "@<device name>" is work
//  for that device. The iOS agent has no `delegate` tool of its own, so the
//  task goes straight to the device's Muse over the hub (`task`), with the
//  mention removed, and its answer is shown here as the reply. A step that
//  Muse must ask about comes back as an `approval` event and is answered
//  here, on the card (NanoMuseRemoteApproval.swift). Device names come from
//  the hub's list; the match is a case-insensitive prefix, the longest name
//  first.
//

import Foundation

enum NanoMuseDeviceMention {
    /// Allow the desktop/runtime target's full task budget before abandoning the call.
    private static let taskTimeout: TimeInterval = 15 * 60

    struct Hit {
        let device: HubDevice
        /// The message without the mention; empty when the mention was all there was.
        let task: String
    }

    /// "@Pixel 8 open the calendar" → Pixel 8, "open the calendar".
    @MainActor
    static func parse(_ text: String) -> Hit? {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.hasPrefix("@") else { return nil }
        let rest = String(trimmed.dropFirst())
        guard !rest.isEmpty else { return nil }
        let devices = NanoMuseHub.shared.others
            .filter { !$0.name.trimmingCharacters(in: .whitespaces).isEmpty }
            .sorted { $0.name.count > $1.name.count }
        for device in devices {
            guard let range = rest.range(of: device.name, options: [.caseInsensitive, .anchored]) else { continue }
            // "@Mac" must not take "@Macbook …": the name ends at a word boundary.
            if range.upperBound < rest.endIndex, rest[range.upperBound].isLetter || rest[range.upperBound].isNumber { continue }
            var task = String(rest[range.upperBound...])
            while let first = task.first, first == ":" || first == "," || first == "，" || first == "：" || first.isWhitespace {
                task.removeFirst()
            }
            return Hit(device: device, task: task.trimmingCharacters(in: .whitespacesAndNewlines))
        }
        return nil
    }

    /// The online devices the `@` menu offers, above the files: only when the `@` opens the
    /// message (that is the only place `parse` looks), name starting with what was typed after it,
    /// or containing it. Picking one writes "@<name> ", which `parse` then reads at send.
    @MainActor
    static func menuEntries(text: String, anchor: Int, filter: String) -> [FileMentionEntry] {
        let nsText = text as NSString
        guard anchor >= 0, anchor <= nsText.length,
              nsText.substring(to: anchor).trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        else { return [] }
        let query = filter.lowercased()
        let devices = NanoMuseHub.shared.others.filter { d in
            let name = d.name.trimmingCharacters(in: .whitespaces)
            return d.online && !name.isEmpty && (query.isEmpty || name.lowercased().contains(query))
        }
        let ranked = devices.sorted { a, b in
            let pa = a.name.lowercased().hasPrefix(query), pb = b.name.lowercased().hasPrefix(query)
            if pa != pb { return pa }
            return a.name.localizedCaseInsensitiveCompare(b.name) == .orderedAscending
        }
        return ranked.map { d in
            FileMentionEntry(
                linuxPath: d.name, scope: .mount, mountName: AppLocalized("device"),
                modifiedAt: d.lastSeen ?? Date(), isDirectory: false,
                nmDevice: NanoMuseMentionDevice(
                    symbol: d.isPhone ? "iphone" : "desktopcomputer",
                    detail: [d.os, AppLocalized("online")].filter { !$0.isEmpty }.joined(separator: " · ")
                )
            )
        }
    }

    /// Runs the mention when there is one: the person's line goes into the chat, then the device's
    /// reply, drawn while that device works (NanoMuseDeviceReply). Returns false when the text
    /// does not address a device.
    @MainActor
    static func handle(_ text: String, in vm: AIChatViewModel) -> Bool {
        guard let hit = parse(text) else { return false }
        let device = hit.device
        let task = hit.task.isEmpty ? text : hit.task
        vm.nmLocalTurn(user: text)
        guard device.online else {
            vm.nmLocalTurn(assistant: String(format: AppLocalized("%@ is not online right now."), device.name))
            return true
        }
        let notes = Notes()
        let sessionId = vm.sessionId ?? vm.draftId ?? "draft"
        let live = NanoMuseDeviceReply(device: device, vm: vm)
        Task { @MainActor in
            do {
                let reply = try await NanoMuseHub.shared.call(
                    to: device.id,
                    action: "task",
                    // `language` (runtime 1.0.0, docs/hub.md): the Muse over there answers in
                    // this phone's language instead of guessing from the text; older runtimes ignore it.
                    // `stream`: the reply draws a `text` in place (NanoMuseDeviceReply), so the
                    // computer may send a message's text while its model writes it; others ignore it.
                    args: ["text": task, "from": NanoMuseHub.shared.name, "language": NanoMuseLocale.tag, "stream": true],
                    timeout: taskTimeout,
                    id: live.callId
                ) { body in
                    guard let stage = body["stage"] as? String else { return }
                    switch stage {
                    case "approval":
                        // That Muse asks whether it may do something risky. The question is answered
                        // here, where the task was typed (docs/hub.md): the card, or a remembered answer.
                        guard let id = body["approval_id"] as? String, let question = NanoMuseRemoteQuestion(body: body) else { return }
                        Task { @MainActor in
                            let outcome = await NanoMuseRemoteApprovals.shared.decide(question, from: device, sessionId: sessionId)
                            switch outcome {
                            case .allowed(let standing): if standing { notes.standing += 1 }
                            case .denied: notes.declined += 1
                            case .settledElsewhere: break
                            }
                            guard let allow = outcome.allow else { return }
                            _ = try? await NanoMuseHub.shared.call(to: device.id, action: "approve", args: ["approval_id": id, "allow": allow], timeout: 30)
                        }
                    case "approval_result":
                        // Decided at the other device, or expired there: the card here goes.
                        guard let id = body["approval_id"] as? String else { return }
                        Task { @MainActor in NanoMuseRemoteApprovals.shared.settled(id) }
                    default:
                        // A step starting or done, what that Muse says along the way: drawn as it comes.
                        Task { @MainActor in live.apply(body) }
                    }
                }
                var answer = ((reply["text"] as? String) ?? (reply["answer"] as? String) ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                // Nothing came back: a task that did not run (a chat that refused the step, #718),
                // or one whose Muse ended it without a word. "Done" here read as work that had
                // happened; the steps above say what did happen, and this line says the answer did not come.
                if answer.isEmpty {
                    let reason = String(format: AppLocalized("%@ finished without an answer."), device.name)
                    await live.finish(header: nil, answer: reason, replacing: false, completion: .failed(reason))
                    return
                }
                if notes.declined > 0 {
                    answer += "\n\n" + String(format: AppLocalized("%@ asked for permission for a step and did not get it from here."), device.name)
                }
                if notes.standing > 0 {
                    answer += "\n\n" + AppLocalized("A step ran on a standing approval given on this phone; Approvals on the agent's page lists it.")
                }
                await live.finish(header: String(format: AppLocalized("%@ answered:"), device.name), answer: answer, replacing: true, completion: .answered)
            } catch {
                if let failure = error as? HubError, failure.code == "timeout" {
                    // A caller deadline or relay timeout does not stop the target by itself.
                    // Keep the original error if the bounded stop cannot reach that device.
                    _ = try? await NanoMuseHub.shared.call(to: device.id, action: "stop", args: ["call": live.callId], timeout: 15)
                }
                if live.stopped {
                    await live.finish(header: nil, answer: AppLocalized("Stopped."), replacing: false, completion: .stopped)
                } else {
                    // A failed call can have completed earlier steps. Describe the failure without
                    // claiming the task never started; an empty answer must not read as "Done".
                    let reason = NanoMuseHubErrors.describe(error)
                    await live.finish(header: nil, answer: String(format: AppLocalized("%@ did not answer: %@"), device.name, reason), replacing: false, completion: .failed(reason))
                }
            }
        }
        return true
    }

    /// What the approvals of one task came to, for the lines under the answer.
    @MainActor
    private final class Notes {
        var declined = 0
        var standing = 0
    }
}

/// What a row of the `@` menu needs to show a device instead of a file (`FileMentionEntry.nmDevice`).
struct NanoMuseMentionDevice: Hashable {
    /// The SF Symbol: a phone or a computer.
    let symbol: String
    /// "Darwin 25.5.0 · online", the line under the name.
    let detail: String
}
