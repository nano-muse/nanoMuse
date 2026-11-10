import XCTest
@testable import Minis

final class NanoMuseCodingTimelineTests: XCTestCase {
    func testToolsGroupAboveAllRepliesWithoutMovingUserMessages() {
        let items = [
            NanoMuseCodingItem(["id": "u1", "turn_id": "t1", "kind": "message", "role": "user"]),
            NanoMuseCodingItem(["id": "a1", "turn_id": "t1", "kind": "message", "role": "assistant"]),
            NanoMuseCodingItem(["id": "c1", "turn_id": "t1", "kind": "command"]),
            NanoMuseCodingItem(["id": "p1", "turn_id": "t1", "kind": "file_change"]),
            NanoMuseCodingItem(["id": "a2", "turn_id": "t1", "kind": "message", "role": "assistant"]),
            NanoMuseCodingItem(["id": "u2", "turn_id": "t2", "kind": "message", "role": "user"]),
            NanoMuseCodingItem(["id": "c2", "turn_id": "t2", "kind": "tool"]),
            NanoMuseCodingItem(["id": "a3", "turn_id": "t2", "kind": "message", "role": "assistant"]),
        ]
        let groups = NanoMuseCodingTurn.group(items)
        XCTAssertEqual(groups.count, 4)
        XCTAssertEqual(groups[0].messages.map(\.id), ["u1"])
        XCTAssertTrue(groups[0].tools.isEmpty)
        XCTAssertEqual(groups[1].messages.map(\.id), ["a1", "a2"])
        XCTAssertEqual(groups[1].tools.map(\.id), ["c1", "p1"])
        XCTAssertEqual(groups[2].messages.map(\.id), ["u2"])
        XCTAssertEqual(groups[3].tools.map(\.id), ["c2"])
    }

    func testToolGroupKeepsIdentityDuringStreamingAndHandlesMissingTurnIds() {
        let command = NanoMuseCodingItem(["id": "c1", "kind": "command", "status": "running"])
        let reply = NanoMuseCodingItem(["id": "a1", "kind": "message", "role": "assistant"])
        let user = NanoMuseCodingItem(["id": "u2", "kind": "message", "role": "user"])
        let second = NanoMuseCodingItem(["id": "c2", "turn_id": "t2", "kind": "tool"])
        let third = NanoMuseCodingItem(["id": "c3", "turn_id": "t3", "kind": "tool"])
        XCTAssertEqual(NanoMuseCodingTurn.group([command])[0].id,
                       NanoMuseCodingTurn.group([command, reply])[0].id)
        let groups = NanoMuseCodingTurn.group([command, reply, user, second, third])
        XCTAssertEqual(groups.map(\.id), ["c1", "u2", "c2", "c3"])
        XCTAssertTrue(NanoMuseCodingTurn.group([]).isEmpty)
    }

    func testFileDetailTargetKeepsItsOwnReferenceAndRun() {
        let file = NanoMuseCodingFile(path: "a.swift", reference: "p1:0", additions: 2, deletions: 1)
        let target = NanoMuseCodingDetailTarget.file(file, runId: "r1")
        guard case let .file(selected, runId) = target else {
            return XCTFail("A file opens a diff, not execution details")
        }
        XCTAssertEqual(selected.reference, "p1:0")
        XCTAssertEqual(runId, "r1")
        XCTAssertEqual(target.id, "file|r1|p1:0")
    }

    func testContinuationTextMatchesHistoryWithoutAnExtraUserMessage() {
        let text = "Continuing an earlier chat titled 'test'.\n\nLast exchange:\nassistant: context\n\nNow: how many?"
        let run = NanoMuseCodingBridge.LiveRun(text: text, status: "done")
        let items = [
            NanoMuseCodingItem(["id": "u", "sequence": 1, "role": "user", "text": text]),
            NanoMuseCodingItem(["id": "a", "sequence": 2, "role": "assistant", "text": "19"]),
        ]
        XCTAssertTrue(NanoMuseCodingBridge.hasRecordedReply(run, in: items, before: []))
        XCTAssertFalse(NanoMuseCodingBridge.hasRecordedReply(run, in: items, before: ["u"]))
        XCTAssertFalse(NanoMuseCodingBridge.hasRecordedReply(
            NanoMuseCodingBridge.LiveRun(text: "how many?", status: "done"), in: items, before: []))
        XCTAssertFalse(NanoMuseCodingBridge.hasRecordedReply(
            NanoMuseCodingBridge.LiveRun(text: text), in: items, before: []))
    }

    func testResumeConflictArrivesThroughOwnedRunSnapshot() {
        let run = NanoMuseCodingBridge.LiveRun(text: "how many?", id: "r1")
        let failed = NanoMuseCodingBridge.snapshot(run, reply: ["runs": [
            ["id": "r1", "status": "failed", "resume_conflict": [
                "process": "codex (PID 123)", "continuation": "context\nNow: how many?",
            ]],
        ]])
        XCTAssertEqual(failed.resumeConflict?.process, "codex (PID 123)")
        XCTAssertEqual(failed.resumeConflict?.continuation, "context\nNow: how many?")
        XCTAssertFalse(failed.isActive)
    }
    func testStableItemRevisionsReplace() {
        let started = NanoMuseCodingItem(["id": "c1", "revision": 1, "status": "running"])
        let ended = NanoMuseCodingItem(["id": "c1", "revision": 2, "status": "completed"])
        let merged = NanoMuseCodingItem.merge([started], [ended, started])
        XCTAssertEqual(merged.count, 1)
        XCTAssertEqual(merged[0].status, "completed")
    }

    func testLiveEventUsesSameIdentity() {
        let event: [String: Any] = ["kind": "item", "item": ["id": "c1", "revision": 1, "kind": "command"]]
        var run = NanoMuseCodingBridge.LiveRun(text: "test")
        run = NanoMuseCodingBridge.step(run, event: event)
        run = NanoMuseCodingBridge.step(run, event: event)
        XCTAssertEqual(run.items.count, 1)
    }

    func testAuthorizationAndSnapshotFollowOnlyTheSentRun() {
        var run = NanoMuseCodingBridge.LiveRun(text: "test", status: "starting")
        XCTAssertTrue(run.isActive)
        run = NanoMuseCodingBridge.step(run, event: ["kind": "authorization"])
        XCTAssertEqual(run.status, "authorizing")
        run = NanoMuseCodingBridge.finish(run, reply: ["id": "r1", "status": "running"])
        let other: [String: Any] = ["runs": [["id": "r2", "status": "done", "output": "other"]]]
        XCTAssertEqual(NanoMuseCodingBridge.snapshot(run, reply: other), run)
        run = NanoMuseCodingBridge.snapshot(run, reply: ["runs": [
            ["id": "r1", "session_id": "new-session", "status": "done", "output": "finished"],
        ]])
        XCTAssertFalse(run.isActive)
        XCTAssertEqual(run.sessionId, "new-session")
        XCTAssertEqual(run.output, "finished")
    }

    func testSnapshotReportsFailureAndStopWithoutWaitingForSend() {
        let run = NanoMuseCodingBridge.LiveRun(text: "test", id: "r1")
        let failed = NanoMuseCodingBridge.snapshot(run, reply: ["runs": [
            ["id": "r1", "status": "failed", "error": "quota"],
        ]])
        XCTAssertFalse(failed.isActive)
        XCTAssertEqual(failed.error, "quota")
        let stopped = NanoMuseCodingBridge.snapshot(run, reply: ["runs": [["id": "r1", "status": "stopped"]]])
        XCTAssertFalse(stopped.isActive)
        XCTAssertEqual(stopped.status, "stopped")
    }

    func testFileChangesAppearUnderOnlyTheLastReplyOfTheirTurn() {
        let earlier = NanoMuseCodingItem(["id": "a1", "turn_id": "t1", "role": "assistant", "kind": "message"])
        let final = NanoMuseCodingItem(["id": "a2", "turn_id": "t1", "role": "assistant", "kind": "message"])
        let patch = NanoMuseCodingItem(["id": "p1", "turn_id": "t1", "kind": "file_change",
                                       "files": [["path": "a.swift", "diff_reference": "p1:0"]]])
        let other = NanoMuseCodingItem(["id": "p2", "turn_id": "t2", "kind": "file_change",
                                       "files": [["path": "b.swift"]]])
        let failed = NanoMuseCodingItem(["id": "p3", "turn_id": "t1", "kind": "file_change",
                                        "status": "failed", "files": [["path": "c.swift"]]])
        let items = [earlier, patch, final, other, failed]
        XCTAssertTrue(NanoMuseCodingItem.changes(after: earlier, in: items).isEmpty)
        XCTAssertEqual(NanoMuseCodingItem.changes(after: final, in: items).map(\.id), ["p1"])
    }

    func testDiffHasOnlyRecordedLineNumbers() {
        let raw = NanoMuseCodingDiffLine.parse("@@\n-old\n+new")
        XCTAssertNil(raw[1].old)
        XCTAssertNil(raw[2].new)
        let unified = NanoMuseCodingDiffLine.parse("@@ -3,2 +7,2 @@\n-old\n+new\n context")
        XCTAssertEqual(unified[1].old, 3)
        XCTAssertEqual(unified[2].new, 7)
        XCTAssertEqual(unified[3].old, 4)
        XCTAssertEqual(unified[3].new, 8)
    }

    func testDiffGutterOnlyReservesSpaceForRecordedNumbers() {
        let raw = NanoMuseCodingDiffLine.parse("@@\n-old\n+new")
        XCTAssertEqual(NanoMuseCodingDiffLine.numberWidth(in: raw), 0)
        let numbered = NanoMuseCodingDiffLine.parse("@@ -3,2 +7,2 @@\n-old\n+new")
        XCTAssertEqual(NanoMuseCodingDiffLine.numberWidth(in: numbered), 20)
        let large = NanoMuseCodingDiffLine.parse("@@ -12345,1 +12345,1 @@\n context")
        XCTAssertEqual(NanoMuseCodingDiffLine.numberWidth(in: large), 44)
        XCTAssertFalse(NanoMuseCodingDiffLine.parse("--- a.swift")[0].isDeletion)
        XCTAssertFalse(NanoMuseCodingDiffLine.parse("+++ a.swift")[0].isAddition)
        XCTAssertTrue(raw[1].isDeletion)
        XCTAssertTrue(raw[2].isAddition)
    }
}
