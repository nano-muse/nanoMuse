import XCTest
@testable import Minis

final class NanoMuseRemoteApprovalTests: XCTestCase {
    func testCompleteTargetUsesTheWholeResourceAndAction() throws {
        let prefix = String(repeating: "x", count: 60)
        let one = try XCTUnwrap(target(resource: prefix + "one", digest: "a"))
        let two = try XCTUnwrap(target(resource: prefix + "two", digest: "b"))

        XCTAssertNotEqual(one.identity, two.identity)
        XCTAssertTrue(one.identity.contains(prefix + "one"))
    }

    func testLegacyAndMalformedEventsCanOnlyBeAllowedOnce() {
        let legacy = NanoMuseRemoteQuestion(body: [
            "approval_id": "legacy",
            "preview": String(repeating: "same", count: 30),
            "grant_key": "old:string:key",
        ])
        XCTAssertNil(legacy?.grantTarget)

        let request = NanoMuseRemoteApprovals.Request(
            id: "legacy", deviceId: "device", deviceName: "Desk", sessionId: "chat",
            risk: .delete, wireRisk: "destructive",
            preview: "same visible prefix", reason: "",
            grantTarget: legacy?.grantTarget, timeout: 180
        )
        XCTAssertFalse(request.canSession)
        XCTAssertFalse(request.canAlways)
        XCTAssertNil(request.target)
        XCTAssertNil(target(resource: "resource", digest: "not-hex"))
        XCTAssertNil(NanoMuseApprovalGrantTarget(wire: [
            "version": 1, "tool": "shell", "resource": "x",
            "action": "sha256:" + String(repeating: "١", count: 64),
        ]))
    }

    func testSessionGrantsAreIsolatedAndResetByChat() {
        var grants = NanoMuseApprovalSessionGrants()
        let base = NanoMuseApprovalSessionGrants.Key(
            sessionId: "chat-one", deviceId: "device-one",
            risk: "delete", target: "target"
        )
        grants.insert(base)
        XCTAssertTrue(grants.allows(base))
        XCTAssertFalse(grants.allows(.init(
            sessionId: "chat-two", deviceId: base.deviceId,
            risk: base.risk, target: base.target
        )))
        XCTAssertFalse(grants.allows(.init(
            sessionId: base.sessionId, deviceId: "device-two",
            risk: base.risk, target: base.target
        )))
        XCTAssertFalse(grants.allows(.init(
            sessionId: base.sessionId, deviceId: base.deviceId,
            risk: "send", target: base.target
        )))

        let other = NanoMuseApprovalSessionGrants.Key(
            sessionId: "chat-two", deviceId: base.deviceId,
            risk: base.risk, target: base.target
        )
        grants.insert(other)
        grants.reset(for: base.sessionId)
        XCTAssertFalse(grants.allows(base))
        XCTAssertTrue(grants.allows(other))
        grants.resetAll()
        XCTAssertFalse(grants.allows(other))
    }

    private func target(resource: String, digest: String) -> NanoMuseApprovalGrantTarget? {
        NanoMuseApprovalGrantTarget(wire: [
            "version": 1,
            "tool": "shell",
            "resource": resource,
            "action": digest == "not-hex"
                ? "sha256:\(String(repeating: digest, count: 8))"
                : "sha256:\(String(repeating: digest, count: 64))",
        ])
    }
}
