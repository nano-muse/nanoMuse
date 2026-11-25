import XCTest
@testable import Minis

/// Where a model call sits, as the phone tells the relay (relay 0.31): the run kind armed for a
/// session until its turn ends, the turn and step counted per call, the headers and the fields an
/// own-key turn repeats, and the shape the events are kept to before they travel. The Android
/// twins are ProvenanceTest and ClientEventsTest.
final class NanoMuseProvenanceTests: XCTestCase {

    override func setUp() {
        super.setUp()
        NanoMuseProvenance.reset()
        NanoMuseClientEvents.reset()
    }

    private func user(_ text: String) -> AgentMessage { AgentMessage(role: .user, parts: [.text(text)]) }
    private func assistant(_ text: String) -> AgentMessage { AgentMessage(role: .assistant, parts: [.text(text)]) }
    private func toolResult() -> AgentMessage { AgentMessage(role: .user, parts: [.toolResult(id: "c1", name: "bash", content: "ok", isError: false)]) }

    func testTurnAndStepAreCountedFromTheRequestWithoutASession() {
        let messages = [user("hi"), assistant("call"), toolResult(), assistant("again"), toolResult()]
        XCTAssertEqual(NanoMuseProvenance.turnOf(messages), 1, "a tool result is not a turn of the person's")
        XCTAssertEqual(NanoMuseProvenance.stepOf(messages), 3)
        let f = NanoMuseProvenance.fields(session: nil, turns: 0, conversation: "minis-x", messages: messages)
        XCTAssertEqual(f, NanoMuseProvenance.Fields(run: "person", turn: 1, step: 3))
        XCTAssertEqual(f.headers, ["X-NanoMuse-Run": "person", "X-NanoMuse-Turn": "1", "X-NanoMuse-Step": "3", "X-NanoMuse-Platform": "ios"])
    }

    func testASessionCountsItsOwnStepsAndTheChatsTurnWins() {
        let m = [user("hi")]
        let a = NanoMuseProvenance.fields(session: "s1", turns: 7, conversation: "minis-c", messages: m)
        let b = NanoMuseProvenance.fields(session: "s1", turns: 7, conversation: "minis-c", messages: m)
        XCTAssertEqual(a.turn, 7, "the chat's count, not the request's (older rows may be compacted away)")
        XCTAssertEqual(a.step, 1)
        XCTAssertEqual(b.step, 2)
        // the next turn starts counting from one again
        let c = NanoMuseProvenance.fields(session: "s1", turns: 8, conversation: "minis-c", messages: m)
        XCTAssertEqual(c.turn, 8)
        XCTAssertEqual(c.step, 1)
        XCTAssertEqual(NanoMuseProvenance.turnNo(session: "s1"), 8)
        XCTAssertEqual(NanoMuseProvenance.conversationOf(session: "s1"), "minis-c")
        XCTAssertEqual(NanoMuseProvenance.sessionOf(conversation: "minis-c"), "s1")
    }

    func testTheArmedRunLastsUntilTheTurnEnds() {
        NanoMuseProvenance.arm(session: "s2", run: NanoMuseProvenance.runSchedule)
        XCTAssertEqual(NanoMuseProvenance.runOf(session: "s2"), "schedule")
        let f = NanoMuseProvenance.fields(session: "s2", turns: 1, conversation: "minis-d", messages: [user("x")])
        XCTAssertEqual(f.run, "schedule")
        NanoMuseProvenance.turnEnded(session: "s2")
        XCTAssertEqual(NanoMuseProvenance.runOf(session: "s2"), "person")
        XCTAssertEqual(NanoMuseProvenance.fields(session: "s2", turns: 2, conversation: "minis-d", messages: [user("x")]).step, 1)
        // a word the relay would not take is not armed
        NanoMuseProvenance.arm(session: "s2", run: "Not A Run")
        XCTAssertEqual(NanoMuseProvenance.runOf(session: "s2"), "person")
    }

    func testTheRelaysIdAndAnOwnTurnsIdNameTheTurn() {
        _ = NanoMuseProvenance.fields(session: "s3", turns: 1, conversation: "minis-e", messages: [user("x")])
        NanoMuseProvenance.noteResponse(conversation: "minis-e", requestId: " req-12:ab ")
        XCTAssertEqual(NanoMuseProvenance.turnRef(session: "s3"), NanoMuseProvenance.TurnRef(id: "req-12:ab", own: false))
        NanoMuseProvenance.noteResponse(conversation: "minis-e", requestId: "has space") // not an id
        XCTAssertEqual(NanoMuseProvenance.turnRef(session: "s3")?.id, "req-12:ab")
        NanoMuseProvenance.noteOwnTurn(session: "s3", id: "own-1")
        XCTAssertEqual(NanoMuseProvenance.turnRef(session: "s3"), NanoMuseProvenance.TurnRef(id: "own-1", own: true))
    }

    func testTheFieldsGoIntoAnOwnTurn() {
        var turn: [String: Any] = ["id": "t"]
        NanoMuseProvenance.Fields(run: "feed", turn: 3, step: 2).into(&turn)
        XCTAssertEqual(turn["run"] as? String, "feed")
        XCTAssertEqual(turn["turn"] as? Int, 3)
        XCTAssertEqual(turn["step"] as? Int, 2)
        XCTAssertEqual(turn["platform"] as? String, "ios")
        var bare: [String: Any] = [:]
        NanoMuseProvenance.Fields(run: "person", turn: 0, step: 0).into(&bare)
        XCTAssertNil(bare["turn"])
        XCTAssertNil(bare["step"])
    }

    // MARK: Events

    func testAnEventKeepsCodesAndDropsProse() throws {
        let e = try XCTUnwrap(NanoMuseClientEvents.event(
            kind: "turn.feedback",
            data: ["vote": "down", "reason": "wrong", "turn_no": 4, "ok": true, "note": "this is prose, with a comma", "Bad-Key": "x", "nothing": nil],
            turn: NanoMuseProvenance.TurnRef(id: "own-9", own: true),
            conversation: "minis-f",
            now: Date(timeIntervalSince1970: 1_700_000_000)
        ))
        XCTAssertEqual(e["kind"] as? String, "turn.feedback")
        XCTAssertEqual(e["ts"] as? Int, 1_700_000_000)
        XCTAssertEqual(e["turn"] as? String, "own-9")
        XCTAssertEqual(e["source"] as? String, "own")
        XCTAssertEqual(e["conversation"] as? String, "minis-f")
        let data = try XCTUnwrap(e["data"] as? [String: Any])
        XCTAssertEqual(data["vote"] as? String, "down")
        XCTAssertEqual(data["turn_no"] as? Int, 4)
        XCTAssertEqual(data["ok"] as? Bool, true)
        XCTAssertNil(data["note"], "prose is left out, never cut")
        XCTAssertNil(data["Bad-Key"])
        XCTAssertNil(data["nothing"])
        XCTAssertNil(NanoMuseClientEvents.event(kind: "Turn.Feedback", data: [:]), "a kind the relay would drop is not sent at all")
        XCTAssertNil(NanoMuseClientEvents.event(kind: "a.b.c.d.e", data: [:]))
        XCTAssertNotNil(NanoMuseClientEvents.event(kind: "hands.step", data: [:]))
    }

    func testBatchesGoToTheSenderWhenEnabled() async {
        final class Box: @unchecked Sendable { var batches: [[[String: Any]]] = [] }
        let box = Box()
        NanoMuseClientEvents.enabled = { true }
        NanoMuseClientEvents.sender = { events in box.batches.append(events) }
        for i in 0..<(NanoMuseClientEvents.batch + 5) {
            NanoMuseClientEvents.add(kind: "turn.ended", data: ["ended": "aborted", "turn_no": i])
        }
        XCTAssertEqual(NanoMuseClientEvents.pending, NanoMuseClientEvents.batch + 5)
        await NanoMuseClientEvents.drainNow()
        XCTAssertEqual(box.batches.count, 2, "a hundred at most per request")
        XCTAssertEqual(box.batches[0].count, NanoMuseClientEvents.batch)
        XCTAssertEqual(box.batches[1].count, 5)
        XCTAssertEqual(NanoMuseClientEvents.pending, 0)
        XCTAssertEqual(NanoMuseClientEvents.sent, 2)
    }

    func testNothingGoesWithoutAnAccount() async {
        final class Box: @unchecked Sendable { var sent = 0 }
        let box = Box()
        NanoMuseClientEvents.enabled = { false }
        NanoMuseClientEvents.sender = { _ in box.sent += 1 }
        NanoMuseClientEvents.add(kind: "turn.ended", data: ["ended": "error"])
        await NanoMuseClientEvents.drainNow()
        XCTAssertEqual(box.sent, 0)
        XCTAssertEqual(NanoMuseClientEvents.pending, 0, "dropped, not hoarded")
        XCTAssertEqual(NanoMuseClientEvents.dropped, 1)
    }

    @MainActor
    func testTheGatesTwoEventsFollowTheSetting() async {
        // the record hears what upstream's permission check decided, as codes; never the command's arguments
        let bypass = await NanoMuseGateEvents.events(command: "apple-healthkit", level: .bypass, asked: false, allowed: true, waited: 0)
        XCTAssertEqual(bypass.count, 1)
        XCTAssertEqual(bypass[0].kind, "sentinel.decision")
        XCTAssertEqual(bypass[0].data["decision"] as? String, "allow")
        XCTAssertEqual(bypass[0].data["by"] as? String, "policy")
        XCTAssertEqual(bypass[0].data["class"] as? String, "privacy")
        XCTAssertEqual(bypass[0].data["risk"] as? String, "sensitive")
        let denied = await NanoMuseGateEvents.events(command: "apple-speak", level: .notAllowed, asked: false, allowed: false, waited: 0)
        XCTAssertEqual(denied[0].data["decision"] as? String, "deny")
        XCTAssertEqual(denied[0].data["risk"] as? String, "moderate")
        let granted = await NanoMuseGateEvents.events(command: "apple-photos", level: .askOnce, asked: false, allowed: true, waited: 0)
        XCTAssertEqual(granted.count, 1)
        XCTAssertEqual(granted[0].data["by"] as? String, "grant")
        let asked = await NanoMuseGateEvents.events(command: "apple-photos", level: .askOnce, asked: true, allowed: true, waited: 4.2)
        XCTAssertEqual(asked.count, 2)
        XCTAssertEqual(asked[0].data["decision"] as? String, "ask")
        XCTAssertEqual(asked[1].kind, "approval.result")
        XCTAssertEqual(asked[1].data["allow"] as? Bool, true)
        XCTAssertEqual(asked[1].data["by"] as? String, "person")
        XCTAssertEqual(asked[1].data["scope"] as? String, "conversation")
        XCTAssertEqual(asked[1].data["waited_s"] as? Int, 4)
        let timedOut = await NanoMuseGateEvents.events(command: "apple-photos", level: .askOnce, asked: true, allowed: false, waited: 30)
        XCTAssertEqual(timedOut[1].data["by"] as? String, "timeout")
        XCTAssertNil(timedOut[1].data["scope"] ?? nil)
    }
}
