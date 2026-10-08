//
//  NanoMuseDeviceMention.swift
//  nanoMuse
//
//  Contract C7, rule 8: a message that starts with "@<device name>" is work
//  for that device. The iOS agent has no `delegate` tool of its own, so the
//  task goes straight to the device's Muse over the hub (`task`), with the
//  mention removed, and its answer is shown here as the reply. Device names
//  come from the hub's list; the match is a case-insensitive prefix, the
//  longest name first.
//

import Foundation

enum NanoMuseDeviceMention {
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

    /// Runs the mention when there is one: the person's line goes into the chat, the device's
    /// answer follows when it comes. Returns false when the text does not address a device.
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
        let declined = Counter()
        Task { @MainActor in
            do {
                let reply = try await NanoMuseHub.shared.call(
                    to: device.id,
                    action: "task",
                    // `language` (runtime 1.0.0, docs/hub.md): the Muse over there answers in
                    // this phone's language instead of guessing from the text; older runtimes ignore it.
                    args: ["text": task, "from": NanoMuseHub.shared.name, "language": NanoMuseLocale.tag],
                    timeout: 600
                ) { body in
                    // That Muse asks whether it may do something risky. Nobody is there to say yes
                    // on this side of the hub, so the step is declined and the person is told.
                    guard (body["stage"] as? String) == "approval", let id = body["approval_id"] as? String else { return }
                    declined.count += 1
                    Task { @MainActor in
                        _ = try? await NanoMuseHub.shared.call(to: device.id, action: "approve", args: ["approval_id": id, "allow": false], timeout: 30)
                    }
                }
                var answer = (reply["text"] as? String) ?? (reply["answer"] as? String) ?? ""
                if answer.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { answer = AppLocalized("Done") }
                if declined.count > 0 {
                    answer += "\n\n" + String(format: AppLocalized("%@ asked for permission for a step and did not get it from here; approve such steps on that device."), device.name)
                }
                vm.nmLocalTurn(assistant: String(format: AppLocalized("%@ answered:"), device.name) + "\n\n" + answer)
            } catch {
                let reason = (error as? HubError)?.message ?? error.localizedDescription
                vm.nmLocalTurn(assistant: String(format: AppLocalized("%@ did not answer: %@"), device.name, reason))
            }
        }
        return true
    }

    /// A box for the count the event closure bumps.
    private final class Counter {
        var count = 0
    }
}
