import Foundation

private func wire(_ resource: String, _ digit: String) -> [String: Any] {
    [
        "version": 1,
        "tool": "shell",
        "resource": resource,
        "action": "sha256:" + String(repeating: digit, count: 64),
    ]
}

@main
private enum ApprovalGrantChecks {
    static func main() {
        let prefix = String(repeating: "x", count: 60)
        let one = NanoMuseApprovalGrantTarget(wire: wire(prefix + "one", "a"))
        let two = NanoMuseApprovalGrantTarget(wire: wire(prefix + "two", "b"))
        precondition(one != nil && two != nil && one?.identity != two?.identity)
        precondition(NanoMuseApprovalGrantTarget(wire: nil) == nil)
        precondition(
            nanoMuseCanRememberApproval(target: one, wireRisk: "destructive", scheduled: false)
        )
        precondition(
            !nanoMuseCanRememberApproval(target: nil, wireRisk: "destructive", scheduled: false)
        )
        precondition(
            !nanoMuseCanRememberApproval(target: one, wireRisk: "payment", scheduled: false)
        )
        precondition(
            !nanoMuseCanRememberApproval(target: one, wireRisk: "outbound", scheduled: true)
        )
        precondition(NanoMuseApprovalGrantTarget(wire: [
            "version": 1, "tool": "shell", "resource": "x", "action": "not-a-digest",
        ]) == nil)
        precondition(NanoMuseApprovalGrantTarget(wire: [
            "version": 1, "tool": "shell", "resource": "x",
            "action": "sha256:" + String(repeating: "١", count: 64),
        ]) == nil)

        var grants = NanoMuseApprovalSessionGrants()
        let first = NanoMuseApprovalSessionGrants.Key(
            sessionId: "chat-one",
            deviceId: "device-one",
            risk: "delete",
            target: one!.identity
        )
        let otherChat = NanoMuseApprovalSessionGrants.Key(
            sessionId: "chat-two",
            deviceId: first.deviceId,
            risk: first.risk,
            target: first.target
        )
        grants.insert(first)
        grants.insert(otherChat)
        precondition(grants.allows(first))
        precondition(!grants.allows(.init(
            sessionId: first.sessionId,
            deviceId: "device-two",
            risk: first.risk,
            target: first.target
        )))
        precondition(!grants.allows(.init(
            sessionId: first.sessionId,
            deviceId: first.deviceId,
            risk: "send",
            target: first.target
        )))
        grants.reset(for: first.sessionId)
        precondition(!grants.allows(first) && grants.allows(otherChat))
        grants.resetAll()
        precondition(!grants.allows(otherChat))

        print("approval grant checks passed")
    }
}
