import Foundation

/// A list response belongs to one device and one request, including after an A-B-A switch.
struct NanoMuseCodingListState {
    struct Request: Equatable {
        let id = UUID()
        let device: String
        let more: Bool
        let cursor: String?
    }

    private(set) var device = ""
    private(set) var agents: [NanoMuseCodingBridge.Agent] = []
    private(set) var sessions: [NanoMuseCodingBridge.Session] = []
    private(set) var cursor: String?
    private(set) var error: String?
    private(set) var request: Request?

    mutating func begin(device: String, more: Bool) -> Request {
        let append = more && self.device == device && cursor != nil
        let next = Request(device: device, more: append, cursor: append ? cursor : nil)
        if self.device != device {
            agents = []
            sessions = []
            cursor = nil
        }
        self.device = device
        error = nil
        request = next
        return next
    }

    @discardableResult
    mutating func complete(_ sent: Request, selectedDevice: String?,
                           agents: [NanoMuseCodingBridge.Agent],
                           sessions: [NanoMuseCodingBridge.Session], cursor: String?) -> Bool {
        guard request == sent, selectedDevice == sent.device else { return false }
        self.agents = agents
        self.sessions = sent.more
            ? self.sessions + sessions.filter { item in !self.sessions.contains { $0.key == item.key } }
            : sessions
        self.cursor = cursor
        error = nil
        request = nil
        return true
    }

    @discardableResult
    mutating func fail(_ sent: Request, selectedDevice: String?, message: String,
                       invalidCursor: Bool = false) -> Bool {
        guard request == sent, selectedDevice == sent.device else { return false }
        error = message
        if invalidCursor { cursor = nil }
        request = nil
        return true
    }
}
