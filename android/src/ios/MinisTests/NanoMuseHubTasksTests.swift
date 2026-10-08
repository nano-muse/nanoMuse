import XCTest
@testable import Minis

/// The bookkeeping behind `stop {call | conversation}` on the iPhone (docs/hub.md): the run a
/// `stop` ends is the one the task frame opened, or the sender's run in the named conversation,
/// and never another device's. The Android twin is HubTasksTest.
@MainActor
final class NanoMuseHubTasksTests: XCTestCase {

    override func setUp() {
        super.setUp()
        NanoMuseHubTasks.running = [:]
    }

    override func tearDown() {
        NanoMuseHubTasks.running = [:]
        super.tearDown()
    }

    func testPromptCarriesTheAskingDevicesLanguage() {
        // A device's Muse gets the context and, with `language`, the language to answer in.
        let fromPhone = NanoMuseHubTasks.prompt(text: "weather tomorrow", senderName: "Pixel", senderKind: "phone", language: "zh-Hans")
        XCTAssertTrue(fromPhone.contains("Pixel"))
        XCTAssertTrue(fromPhone.contains("tagged zh-Hans"))
        XCTAssertTrue(fromPhone.hasSuffix("\n\nweather tomorrow"))
        // Without the tag the model goes by the text; nothing is said about a language tag.
        let untagged = NanoMuseHubTasks.prompt(text: "weather tomorrow", senderName: "Pixel", senderKind: "computer", language: nil)
        XCTAssertFalse(untagged.contains("tagged"))
        XCTAssertEqual(NanoMuseHubTasks.prompt(text: "weather tomorrow", senderName: "Pixel", senderKind: "computer", language: "  "), untagged, "blank counts as absent")
        // A web console speaks for the person: no context line, the tag still counts.
        let fromWeb = NanoMuseHubTasks.prompt(text: "weather tomorrow", senderName: "web", senderKind: "web", language: "fr")
        XCTAssertEqual(fromWeb, "Answer in the language tagged fr; the device that asked shows its screens in it.\n\nweather tomorrow")
        XCTAssertEqual(NanoMuseHubTasks.prompt(text: "weather tomorrow", senderName: "web", senderKind: "web", language: nil), "weather tomorrow")
        // An overlong tag is cut, so a stray value cannot pad the prompt.
        XCTAssertTrue(NanoMuseHubTasks.prompt(text: "x", senderName: "web", senderKind: "web", language: String(repeating: "a", count: 80)).contains("tagged " + String(repeating: "a", count: 20) + ";"))
    }

    func testConversationKeyIsTheNamedOneOrOnePerDevice() {
        XCTAssertEqual(NanoMuseHubTasks.conversationKey(senderId: "mac", conversation: nil), "from-mac")
        XCTAssertEqual(NanoMuseHubTasks.conversationKey(senderId: "mac", conversation: "  "), "from-mac")
        XCTAssertEqual(NanoMuseHubTasks.conversationKey(senderId: "", conversation: nil), "from-unknown")
        XCTAssertEqual(NanoMuseHubTasks.conversationKey(senderId: "mac", conversation: "t-1"), "t-1")
    }

    func testStopByCallFindsTheRunTheFrameOpened() {
        NanoMuseHubTasks.running["c1"] = .init(senderId: "mac", conversation: "from-mac")
        XCTAssertEqual(NanoMuseHubTasks.find(senderId: "mac", callId: "c1", conversation: nil), "c1")
        XCTAssertNil(NanoMuseHubTasks.find(senderId: "mac", callId: "c9", conversation: "elsewhere"))
    }

    func testStopByConversationDefaultsToTheSendersOwn() {
        NanoMuseHubTasks.running["c1"] = .init(senderId: "mac", conversation: "from-mac")
        NanoMuseHubTasks.running["c2"] = .init(senderId: "mac", conversation: "t-1")
        XCTAssertEqual(NanoMuseHubTasks.find(senderId: "mac", callId: nil, conversation: nil), "c1")
        XCTAssertEqual(NanoMuseHubTasks.find(senderId: "mac", callId: "", conversation: "t-1"), "c2")
        XCTAssertNil(NanoMuseHubTasks.find(senderId: "mac", callId: nil, conversation: "t-2"))
    }

    func testAnotherDeviceCannotStopIt() {
        NanoMuseHubTasks.running["c1"] = .init(senderId: "mac", conversation: "t-1")
        XCTAssertNil(NanoMuseHubTasks.find(senderId: "pc", callId: "c1", conversation: nil))
        XCTAssertNil(NanoMuseHubTasks.find(senderId: "pc", callId: nil, conversation: "t-1"))
        XCTAssertFalse(NanoMuseHubTasks.stop(args: ["call": "c1"], from: ["id": "pc"]))
        XCTAssertEqual(NanoMuseHubTasks.running["c1"]?.stopped, false)
    }

    func testStopMarksTheRunSoTheTaskAnswersCancelled() {
        NanoMuseHubTasks.running["c1"] = .init(senderId: "mac", conversation: "from-mac")
        XCTAssertTrue(NanoMuseHubTasks.stop(args: [:], from: ["id": "mac"]))
        XCTAssertEqual(NanoMuseHubTasks.running["c1"]?.stopped, true)
        XCTAssertFalse(NanoMuseHubTasks.stop(args: ["conversation": "none"], from: ["id": "mac"]))
    }
}
