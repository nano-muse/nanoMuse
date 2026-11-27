import XCTest
@testable import Minis

final class NanoMuseFeedPreparationTests: XCTestCase {
    typealias Plan = NanoMuseFeedPreparation

    private func goal(_ recent: Bool = true) -> Plan.Signal {
        .init(id: "g1", version: "ga", label: "Goal · Atlas talk", text: "Rehearse the Atlas talk", timely: recent, role: .goal)
    }

    private func note(_ text: String, recent: Bool = true, version: String = "v1") -> Plan.Signal {
        .init(id: "diary", version: version, label: "Diary", text: text, timely: recent)
    }

    func testOnlyRelatedTimelyIndependentEvidenceIsEligible() {
        let info = note("The Atlas audience wants a concrete example", recent: false)
        XCTAssertTrue(Plan.candidates(primaries: [goal(false)], notes: [info], seen: []).isEmpty)
        XCTAssertTrue(Plan.candidates(primaries: [goal()], notes: [note("Plan next week"), note("- Rehearse the Atlas talk")], seen: []).isEmpty)
        let matches = Plan.candidates(primaries: [goal()], notes: [info], seen: [])
        XCTAssertEqual(matches.count, 1)
        XCTAssertTrue(Plan.candidates(primaries: [goal()], notes: [info], seen: [matches[0].key]).isEmpty)
        XCTAssertEqual(Plan.candidates(primaries: [goal()], notes: [note("The Atlas talk now has five minutes", version: "v2")], seen: [matches[0].key]).count, 1)
    }

    func testChineseSubjectsMatchWithoutSpaces() {
        let chinese = Plan.Signal(id: "g2", version: "g2v", label: "目标", text: "准备预算汇报", timely: true, role: .goal)
        XCTAssertTrue(Plan.candidates(primaries: [chinese], notes: [note("准备午饭食材")], seen: []).isEmpty)
        XCTAssertEqual(Plan.candidates(primaries: [chinese], notes: [note("预算审议先讲差额")], seen: []).count, 1)
    }

    func testReferencesCheckedAgainstThisPairAndSourceLabelsComeFromDevice() throws {
        let pairs = Plan.candidates(primaries: [goal()], notes: [note("The Atlas audience wants a concrete example")], seen: [])
        let answer = #"{"pair":1,"kind":"checklist","title":"Atlas rehearsal","body":"1. Pick an opening example.\n2. Practice the transition.","source":["unknown.pdf"]}"#
        let card = try XCTUnwrap(Plan.verify("```json\n" + answer + "\n```", pairs: pairs))
        XCTAssertEqual(card.citations.map(\.display), ["Goal · Atlas talk · Rehearse the Atlas talk", "Diary · The Atlas audience wants a concrete example"])
        XCTAssertNil(Plan.verify(answer.replacingOccurrences(of: "opening example", with: "demo for 25 attendees"), pairs: pairs))
        XCTAssertNil(Plan.verify(answer.replacingOccurrences(of: "opening example", with: "opening example in Room C"), pairs: pairs))
        XCTAssertNil(Plan.verify(answer.replacingOccurrences(of: #""pair":1"#, with: #""pair":0"#), pairs: pairs))
        XCTAssertNil(Plan.verify("null", pairs: pairs))
    }

    func testDatedCommitmentAndIndependentPreferenceWithoutAGoal() throws {
        let days = ["2026-01-02", "2026-01-03"]
        let event = Plan.Signal(id: "diary-1", version: "ev", label: "Diary", text: "Tomorrow: Atlas presentation", timely: true, daysAgo: 1)
        let preference = Plan.Signal(id: "USER.md", version: "pref", label: "USER.md", text: "For Atlas I prefer a visual demo", timely: false)
        let primary = try XCTUnwrap(Plan.commitments(notes: [event, preference], upcomingDays: days).first)
        XCTAssertTrue(primary.version.hasSuffix(days[0]))
        let pairs = Plan.candidates(primaries: [primary], notes: [event, preference], seen: [])
        XCTAssertEqual(pairs.count, 1)
        let answer = #"{"pair":1,"kind":"draft","title":"Opening","body":"Start the Atlas presentation with a visual demo of the result."}"#
        XCTAssertNotNil(Plan.verify(answer, pairs: pairs))
        XCTAssertNil(Plan.verify(answer.replacingOccurrences(of: "Start the Atlas presentation with a visual demo of the result.", with: "Please prepare a visual opening for your Atlas presentation."), pairs: pairs))
        XCTAssertNil(Plan.verify(answer.replacingOccurrences(of: "a visual demo", with: "a visual demo for three people"), pairs: pairs))
        XCTAssertNil(Plan.verify(answer.replacingOccurrences(of: "Start the Atlas presentation with a visual demo of the result.", with: "Take care and have a good day."), pairs: pairs))
        XCTAssertTrue(Plan.candidates(primaries: [primary], notes: [note("Buy groceries for Saturday")], seen: []).isEmpty)

        let correction = Plan.Signal(id: "diary-2", version: "correction", label: "Diary", text: "Atlas presentation was cancelled", timely: true, daysAgo: 0)
        XCTAssertTrue(Plan.commitments(notes: [event, correction, preference], upcomingDays: days).isEmpty)
        let nearby = note("I like the coffee shop near Atlas for its window seats")
        XCTAssertTrue(Plan.candidates(primaries: [primary], notes: [nearby], seen: []).isEmpty)
        let header = answer.replacingOccurrences(of: "Start the Atlas presentation with a visual demo of the result.", with: "Next step: Write an Atlas opening about a visual demo.")
        XCTAssertNil(Plan.verify(header, pairs: pairs))
        XCTAssertNil(Plan.verify(answer.replacingOccurrences(of: "Start the Atlas presentation", with: "Dear investors, start the Atlas presentation"), pairs: pairs))
        let past = Plan.Signal(id: "diary-older", version: "old", label: "Diary", text: event.text, timely: true, daysAgo: 2)
        XCTAssertTrue(Plan.commitments(notes: [past], upcomingDays: days).isEmpty)
        let undated = Plan.Signal(id: "diary", version: "idea", label: "Diary", text: "Maybe an Atlas presentation", timely: true, daysAgo: 0)
        XCTAssertTrue(Plan.commitments(notes: [undated], upcomingDays: days).isEmpty)
    }

    func testOmitUnsupportedClockPreambleAndResolvePlaceholderTitle() throws {
        let event = Plan.Signal(id: "diary", version: "a", label: "Diary", text: "明天参加海桥项目设计评审", timely: true, role: .commitment)
        let pref = Plan.Signal(id: "USER.md", version: "b", label: "USER.md", text: "海桥项目的设计评审先看原型，再谈取舍", timely: false)
        let pairs = Plan.candidates(primaries: [event], notes: [pref], seen: [])
        let actual = #"{"pair":1,"kind":"draft","title":"...","body":"明天早上9点，我们先看海桥项目的原型设计，然后再讨论需要保留和调整的部分。"}"#
        let draft = try XCTUnwrap(Plan.verify(actual, pairs: pairs))
        XCTAssertEqual(draft.title, event.text)
        XCTAssertEqual(draft.body, "我们先看海桥项目的原型设计，然后再讨论需要保留和调整的部分。")
        XCTAssertNil(Plan.verify(actual.replacingOccurrences(of: "明天早上9点，", with: "务必9点到。"), pairs: pairs))
        XCTAssertNil(Plan.verify(actual.replacingOccurrences(of: "原型设计", with: "原型设计，现场有30人"), pairs: pairs))
    }

    func testBodyAliasOnlyForAnExplicitDraftAndWithFullValidation() throws {
        let event = Plan.Signal(id: "diary", version: "a", label: "Diary", text: "明天参加海桥项目设计评审，需要开场。", timely: true, role: .commitment)
        let pref = Plan.Signal(id: "USER.md", version: "b", label: "USER.md", text: "海桥项目的设计评审先看原型，再谈取舍。", timely: false)
        let pairs = Plan.candidates(primaries: [event], notes: [pref], seen: [])
        let response = #"{"pair":1,"kind":"body","title":"设计评审开场","body":"大家好，我们今天的海桥项目设计评审先看原型，再讨论取舍。"}"#
        XCTAssertNotNil(Plan.verify(response, pairs: pairs))
        XCTAssertNil(Plan.verify(response.replacingOccurrences(of: "大家好，我们", with: "尊敬的各位专家，我们"), pairs: pairs))
        XCTAssertNil(Plan.verify(response.replacingOccurrences(of: "大家好，我们", with: "现场有20人，我们"), pairs: pairs))
        XCTAssertNil(Plan.verify(response.replacingOccurrences(of: "大家好，我们", with: "下一步：我们"), pairs: pairs))
        let withoutOpening = Plan.Signal(id: "diary", version: "c", label: "Diary", text: "明天参加海桥项目设计评审。", timely: true, role: .commitment)
        XCTAssertNil(Plan.verify(response, pairs: Plan.candidates(primaries: [withoutOpening], notes: [pref], seen: [])))
    }

    func testCompatiblePostMetadataRoundTrip() throws {
        let file = URL(fileURLWithPath: "/sample.md")
        func parse(_ text: String) throws -> NanoMusePost {
            try XCTUnwrap(NanoMusePost.parse(text: text, day: "2026-01-02", index: 1, file: file, modified: Date()))
        }
        var post = try parse("---\ntitle: Rehearsal\n---\n\nPractice the opening.")
        XCTAssertNil(post.preparationKey)
        post.preparationKey = "source.version"
        post.preparationGoal = "g1"
        post.citations = [.init(label: "Goal · Atlas talk", excerpt: "Atlas; rehearsal"), .init(label: "Diary", excerpt: "Atlas · audience; one demo")]
        post.source = try XCTUnwrap(post.citations).map(\.display)
        let read = try parse(post.serialize())
        XCTAssertEqual(read.preparationKey, post.preparationKey)
        XCTAssertEqual(read.preparationGoal, post.preparationGoal)
        XCTAssertEqual(read.source, post.source)
        XCTAssertEqual(read.citations, post.citations)
    }
}
