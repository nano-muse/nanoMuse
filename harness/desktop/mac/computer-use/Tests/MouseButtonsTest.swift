// Deterministic tests for the helper's button ownership. The event callbacks are
// fakes; this executable never links CoreGraphics or posts a system input event.
import Foundation

private func markerText(_ marker: URL) -> String? {
    try? String(contentsOf: marker, encoding: .utf8)
}

private func expectFailure(_ expected: MouseButtons.Failure, _ action: () throws -> Void) throws {
    do {
        try action()
        fatalError("expected \(expected)")
    } catch let failure as MouseButtons.Failure {
        precondition(failure == expected)
    }
}

private func noPost(_ button: UInt32) -> Bool {
    fatalError("unexpected up for \(button)")
}

private func retryAfterFailedUp(_ marker: URL) throws {
    let buttons = try MouseButtons(marker: marker)
    try buttons.queue.sync {
        var posts = 0
        try expectFailure(.eventUnavailable) {
            try buttons.press(1) {
                precondition(markerText(marker) == "1\n")
                return false
            }
        }
        precondition(markerText(marker) == nil)
        try buttons.recover(isDown: { _ in nil }, postUp: noPost)

        try buttons.press(1) { markerText(marker) == "1\n" }
        try expectFailure(.eventUnavailable) { try buttons.release(1) { false } }
        precondition(markerText(marker) == "1\n")
        try expectFailure(.pendingRelease) { try buttons.press(0) { fatalError("unexpected down") } }
        try buttons.recover(isDown: { _ in fatalError("the live owner knows it pressed this button") },
                            postUp: { raw in posts += 1; return raw == 1 })
        try buttons.release(1) { fatalError("already released") }
        try buttons.recover(isDown: { _ in nil }, postUp: noPost)
        precondition(posts == 1 && markerText(marker) == nil)
    }
}

private func recoverAcrossOwners(_ marker: URL) throws {
    // The old helper's marker may contain multiple or duplicate entries.
    try "0,1,1,2\n".write(to: marker, atomically: true, encoding: .utf8)
    do {
        let buttons = try MouseButtons(marker: marker)
        try buttons.queue.sync {
            try expectFailure(.markerInUse) { _ = try MouseButtons(marker: marker) }
            var posted: [UInt32] = []
            try expectFailure(.eventUnavailable) {
                try buttons.recover(isDown: { $0 != 1 }, postUp: { raw in
                    posted.append(raw)
                    return raw == 0
                })
            }
            // 2 failed, 1 was already up and 0 was still released.
            precondition(posted == [2, 0] && markerText(marker) == "2\n")
        }
    }
    let next = try MouseButtons(marker: marker)
    try next.queue.sync {
        try expectFailure(.eventUnavailable) {
            try next.recover(isDown: { _ in nil }, postUp: noPost)
        }
        precondition(markerText(marker) == "2\n")
        // The previous owner, or the user, already released the remaining
        // button. An uncertain recording never justifies another mouse-up.
        try next.recover(isDown: { _ in false }, postUp: noPost)
        precondition(markerText(marker) == nil)
    }
}

private func recoverAfterProcessExit(_ marker: URL) throws {
    let child = Process()
    child.executableURL = URL(fileURLWithPath: CommandLine.arguments[0])
    child.arguments = ["--fake-down", marker.path]
    let ready = Pipe()
    child.standardOutput = ready
    try child.run()
    defer {
        if child.isRunning { child.terminate() }
        child.waitUntilExit()
    }
    precondition(ready.fileHandleForReading.readData(ofLength: 1) == Data([1]))
    try expectFailure(.markerInUse) { _ = try MouseButtons(marker: marker) }
    child.terminate()
    child.waitUntilExit()

    let next = try MouseButtons(marker: marker)
    try next.queue.sync {
        var ups: [UInt32] = []
        try next.recover(isDown: { $0 == 2 }, postUp: { ups.append($0); return true })
        try next.recover(isDown: { _ in nil }, postUp: noPost)
        precondition(ups == [2] && markerText(marker) == nil)
    }
}

private final class EventLog {
    // Accessed only on the helper's serial input queue.
    var events: [String] = []
}

private func finishGestureBeforeShutdown(_ marker: URL) throws {
    let buttons = try MouseButtons(marker: marker)
    let started = DispatchSemaphore(value: 0)
    let finish = DispatchSemaphore(value: 0)
    let log = EventLog()
    buttons.queue.async {
        try! buttons.checkCanPerform()
        log.events.append("move")
        try! buttons.press(0) { log.events.append("down"); return true }
        started.signal()
        precondition(finish.wait(timeout: .now() + 5) == .success)
        log.events.append("drag")
        try! buttons.release(0) { log.events.append("up"); return true }
    }
    precondition(started.wait(timeout: .now() + 5) == .success)
    buttons.queue.async {
        buttons.stop {
            try! buttons.recover(isDown: { _ in nil }, postUp: noPost)
            log.events.append("quit")
        }
    }
    finish.signal()
    try buttons.queue.sync {
        try expectFailure(.stopping) { try buttons.checkCanPerform() }
        try expectFailure(.stopping) { try buttons.press(1) { fatalError("post after quit") } }
        precondition(log.events == ["move", "down", "drag", "up", "quit"])
        let replacement = try MouseButtons(marker: marker)
        try replacement.queue.sync {
            try replacement.press(2) { true }
        }
        buttons.stop { fatalError("old process touched a replacement's input") }
        precondition(markerText(marker) == "2\n")
        try replacement.queue.sync {
            try replacement.release(2) { true }
        }
    }
}

@main
enum MouseButtonsTest {
    static func main() throws {
        if CommandLine.arguments.count == 3, CommandLine.arguments[1] == "--fake-down" {
            let owner = try MouseButtons(marker: URL(fileURLWithPath: CommandLine.arguments[2]))
            try owner.queue.sync {
                try owner.press(2) { true }
                FileHandle.standardOutput.write(Data([1]))
                // The parent terminates this test process without a release.
                Thread.sleep(forTimeInterval: 10)
            }
            return
        }
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        let marker = dir.appendingPathComponent("mouse-held")
        try retryAfterFailedUp(marker)
        try recoverAcrossOwners(marker)
        try recoverAfterProcessExit(marker)
        try finishGestureBeforeShutdown(marker)
    }
}
