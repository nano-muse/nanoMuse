import Foundation
#if canImport(Darwin)
import Darwin
#else
import Glibc
#endif

/// The helper owns this lock until input has stopped. An independent --release or a second
/// helper cannot release a button in the middle of the owner's gesture.
final class MouseButtons {
    enum Failure: Error {
        case markerInUse, eventUnavailable, pendingRelease, stopping
    }

    let queue = DispatchQueue(label: "io.github.nanomuse.desktop.computer-use.http")
    private var stopping = false
    private let marker: URL
    private let owner: Int32
    private var held: [UInt32] = []
    private var inherited: Set<UInt32> = []

    init(marker: URL) throws {
        self.marker = marker
        let fd = open(marker.appendingPathExtension("lock").path, O_CREAT | O_RDWR | O_CLOEXEC | O_NOFOLLOW, 0o600)
        guard fd >= 0 else { throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO) }
        guard flock(fd, LOCK_EX | LOCK_NB) == 0 else {
            let error = errno
            close(fd)
            if error == EWOULDBLOCK { throw Failure.markerInUse }
            throw POSIXError(POSIXErrorCode(rawValue: error) ?? .EIO)
        }
        owner = fd
        let existing = open(marker.path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK)
        guard existing >= 0 else {
            if errno == ENOENT { return }
            throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO)
        }
        let handle = FileHandle(fileDescriptor: existing, closeOnDealloc: true)
        let text = String(decoding: try handle.readToEnd() ?? Data(), as: UTF8.self)
        for field in text.split(separator: ",") {
            if let raw = UInt32(field.trimmingCharacters(in: .whitespacesAndNewlines)),
               raw <= 2, inherited.insert(raw).inserted {
                held.append(raw)
            }
        }
    }

    deinit { close(owner) }

    private func save(_ buttons: [UInt32]) throws {
        if buttons.isEmpty {
            if unlink(marker.path) != 0 && errno != ENOENT {
                throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO)
            }
        } else {
            let line = buttons.map(String.init).joined(separator: ",") + "\n"
            try Data(line.utf8).write(to: marker, options: .atomic)
        }
    }

    func checkCanPerform() throws {
        dispatchPrecondition(condition: .onQueue(queue))
        guard !stopping else { throw Failure.stopping }
    }

    func press(_ button: UInt32, post: () -> Bool) throws {
        try checkCanPerform()
        guard held.isEmpty else { throw Failure.pendingRelease }
        // Persist the intent before posting down. Recovery checks the actual OS
        // button state if a crash happened between these two operations.
        try save([button])
        held.append(button)
        if !post() {
            try forget(button)
            throw Failure.eventUnavailable
        }
    }

    private func forget(_ button: UInt32) throws {
        held.removeAll { $0 == button }
        inherited.remove(button)
        try save(held)
    }

    func release(_ button: UInt32, post: () -> Bool) throws {
        dispatchPrecondition(condition: .onQueue(queue))
        guard held.contains(button) else { return }
        guard post() else { throw Failure.eventUnavailable }
        // Even if unlink fails, the in-process owner has already posted this up.
        // A later process checks the OS before replaying the stale file.
        try forget(button)
    }

    func recover(isDown: (UInt32) -> Bool?, postUp: (UInt32) -> Bool) throws {
        dispatchPrecondition(condition: .onQueue(queue))
        var firstError: Error?
        for button in held.reversed() {
            do {
                if inherited.contains(button) {
                    guard let down = isDown(button) else { throw Failure.eventUnavailable }
                    if !down {
                        try forget(button)
                        continue
                    }
                }
                try release(button) { postUp(button) }
            } catch {
                if firstError == nil { firstError = error }
            }
        }
        if let firstError = firstError { throw firstError }
    }

    func stop(release: () -> Void) {
        dispatchPrecondition(condition: .onQueue(queue))
        guard !stopping else { return }
        stopping = true
        release()
        // A replacement may launch as soon as /quit returns. The old process
        // can still send its JSON response, but can no longer touch input.
        flock(owner, LOCK_UN)
    }
}
