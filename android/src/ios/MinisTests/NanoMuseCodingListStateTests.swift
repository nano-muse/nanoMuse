import XCTest
@testable import Minis

final class NanoMuseCodingListStateTests: XCTestCase {
    private func session(_ id: String) -> NanoMuseCodingBridge.Session {
        NanoMuseCodingBridge.session(["agent": "codex", "id": id, "workspace": "/project"])
    }

    func testSwitchingDevicesDropsOldProjectsAndIgnoresTheOldFailure() {
        var list = NanoMuseCodingListState()
        let first = list.begin(device: "A", more: false)
        list.complete(first, selectedDevice: "A", agents: [], sessions: [session("a")], cursor: "a-page")
        let old = list.begin(device: "A", more: true)
        let current = list.begin(device: "B", more: false)
        XCTAssertTrue(list.sessions.isEmpty)
        XCTAssertNil(list.cursor)
        XCTAssertFalse(list.fail(old, selectedDevice: "B", message: "A failed"))
        XCTAssertNil(list.error)
        XCTAssertEqual(list.request, current)
        XCTAssertTrue(list.complete(current, selectedDevice: "B", agents: [], sessions: [session("b")], cursor: nil))
        XCTAssertEqual(list.sessions.map(\.id), ["b"])
    }

    func testReturningToADeviceDoesNotAcceptItsEarlierResponse() {
        var list = NanoMuseCodingListState()
        let earlierA = list.begin(device: "A", more: false)
        _ = list.begin(device: "B", more: false)
        let latestA = list.begin(device: "A", more: false)
        list.complete(latestA, selectedDevice: "A", agents: [], sessions: [session("new-a")], cursor: nil)
        XCTAssertFalse(list.complete(earlierA, selectedDevice: "A", agents: [], sessions: [session("old-a")], cursor: "old"))
        XCTAssertEqual(list.sessions.map(\.id), ["new-a"])
        XCTAssertNil(list.cursor)
        XCTAssertNil(list.request)
    }

    func testASelectionChangeRejectsRepliesBeforeTheNextRequestBegins() {
        var list = NanoMuseCodingListState()
        let request = list.begin(device: "A", more: false)
        XCTAssertFalse(list.complete(request, selectedDevice: "B", agents: [], sessions: [session("a")], cursor: nil))
        XCTAssertFalse(list.fail(request, selectedDevice: nil, message: "offline"))
        XCTAssertTrue(list.sessions.isEmpty)
        XCTAssertNil(list.error)
    }

    func testInvalidPagesOnlyResetForCursorErrors() {
        XCTAssertTrue(NanoMuseCodingBridge.invalidPage(HubError(code: "stale_cursor", message: "changed")))
        XCTAssertTrue(NanoMuseCodingBridge.invalidPage(HubError(code: "invalid_cursor", message: "invalid")))
        XCTAssertFalse(NanoMuseCodingBridge.invalidPage(HubError(code: "disconnected", message: "offline")))
    }

    func testPaginationCapturesItsCursorAndRefreshReplacesTheOldVersion() {
        var list = NanoMuseCodingListState()
        let first = list.begin(device: "A", more: false)
        list.complete(first, selectedDevice: "A", agents: [], sessions: [session("one")], cursor: "version-1")
        let more = list.begin(device: "A", more: true)
        XCTAssertEqual(more.cursor, "version-1")
        list.complete(more, selectedDevice: "A", agents: [], sessions: [session("one"), session("two")], cursor: "version-1-next")
        XCTAssertEqual(list.sessions.map(\.id), ["one", "two"])
        let stale = list.begin(device: "A", more: true)
        list.fail(stale, selectedDevice: "A", message: "changed", invalidCursor: true)
        XCTAssertNil(list.cursor)
        XCTAssertEqual(list.sessions.map(\.id), ["one", "two"])
        let refresh = list.begin(device: "A", more: false)
        XCTAssertNil(refresh.cursor)
        XCTAssertFalse(refresh.more)
        list.complete(refresh, selectedDevice: "A", agents: [], sessions: [session("new-version")], cursor: nil)
        XCTAssertEqual(list.sessions.map(\.id), ["new-version"])
        XCTAssertNil(list.error)
    }
}
