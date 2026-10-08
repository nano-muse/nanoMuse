import XCTest
@testable import Minis

/// The pure parts of the nanoMuse iPhone layer, pinned so they cannot drift from Android:
/// the fences the model writes, the words that change the avatar, the goal and feed blocks,
/// the scheduler's arithmetic, the region rule, the model menu and the first-run gating.
/// Android: AvatarFlowTest, GoalFlowTest, FencesTest, FirstRunSetupTest, SharedConnectorsTest.
@MainActor
final class NanoMuseLogicTests: XCTestCase {

    // MARK: - Fences

    func testFencesFindTheLastBlockAndStripIt() {
        let text = """
        Here you go.
        ```nanomuse-goal
        {"title": "Run twice a week", "check_every_hours": 72}
        ```
        And an update later:
        ```nanomuse-goal
        {"title": "Run three times a week"}
        ```
        Done.
        """
        XCTAssertTrue(NanoMuseFences.contains(text))
        XCTAssertTrue(NanoMuseFences.contains(text, kind: "goal"))
        XCTAssertFalse(NanoMuseFences.contains(text, kind: "feed"))
        XCTAssertEqual(NanoMuseFences.blocks("goal", in: text).count, 2)
        XCTAssertEqual(NanoMuseFences.lastObject("goal", in: text)?["title"] as? String, "Run three times a week")
        let stripped = NanoMuseFences.strip(text)
        XCTAssertFalse(stripped.contains("nanomuse-goal"))
        XCTAssertTrue(stripped.contains("Here you go."))
        XCTAssertTrue(stripped.contains("Done."))
    }

    func testFencesSplitIntoPieces() {
        let text = "Before\n```nanomuse-feed\n{\"title\":\"A\",\"body\":\"B\"}\n```\nAfter"
        let pieces = NanoMuseFences.pieces(text)
        XCTAssertEqual(pieces.count, 3)
        XCTAssertEqual(pieces.first, .prose("Before"))
        if case .block(let kind, let json) = pieces[1] {
            XCTAssertEqual(kind, "feed")
            XCTAssertTrue(json.contains("\"title\""))
        } else {
            XCTFail("second piece should be the block")
        }
        XCTAssertEqual(pieces.last, .prose("After"))
    }

    func testFenceRoundTrip() {
        let fence = NanoMuseFences.fence("goal-update", ["goal_id": "g1", "progress": 40])
        XCTAssertTrue(fence.hasPrefix("```nanomuse-goal-update\n"))
        XCTAssertEqual(NanoMuseFences.lastObject("goal-update", in: fence)?["goal_id"] as? String, "g1")
    }

    // MARK: - Day

    func testParseClock() {
        XCTAssertEqual(NanoMuseDay.parseClock("09:30")?.hour, 9)
        XCTAssertEqual(NanoMuseDay.parseClock("09:30")?.minute, 30)
        XCTAssertEqual(NanoMuseDay.parseClock("7:05")?.hour, 7)
        XCTAssertNil(NanoMuseDay.parseClock("25:00"))
        XCTAssertNil(NanoMuseDay.parseClock("noon"))
        XCTAssertNil(NanoMuseDay.parseClock(nil))
    }

    // MARK: - Avatar words

    func testAvatarRequestsEnglish() {
        XCTAssertEqual(NanoMuseAvatarIntent.parseRequest("Change your avatar to a red panda"), "red panda")
        XCTAssertEqual(NanoMuseAvatarIntent.parseRequest("please switch your look into a small robot."), "small robot")
        XCTAssertEqual(NanoMuseAvatarIntent.parseRequest("new avatar: cyberpunk fox"), "cyberpunk fox")
        XCTAssertEqual(NanoMuseAvatarIntent.parseRequest("become a dragon"), "dragon")
        // "become better" is not a face.
        XCTAssertNil(NanoMuseAvatarIntent.parseRequest("become better at math"))
        XCTAssertNil(NanoMuseAvatarIntent.parseRequest("be quiet"))
        XCTAssertNil(NanoMuseAvatarIntent.parseRequest("What is the weather like?"))
    }

    func testAvatarRequestsChinese() {
        XCTAssertEqual(NanoMuseAvatarIntent.parseRequest("把你的形象换成一只橘猫"), "一只橘猫")
        XCTAssertEqual(NanoMuseAvatarIntent.parseRequest("换个头像：赛博朋克狐狸"), "赛博朋克狐狸")
        XCTAssertEqual(NanoMuseAvatarIntent.parseRequest("变成一条小龙吧"), "一条小龙")
        XCTAssertNil(NanoMuseAvatarIntent.parseRequest("今天天气怎么样"))
    }

    func testAvatarChoices() {
        XCTAssertEqual(NanoMuseAvatarIntent.parseChoice("2"), .index(1))
        XCTAssertEqual(NanoMuseAvatarIntent.parseChoice("the third one"), .index(2))
        XCTAssertEqual(NanoMuseAvatarIntent.parseChoice("I'll take the first"), .index(0))
        XCTAssertEqual(NanoMuseAvatarIntent.parseChoice("第二个"), .index(1))
        XCTAssertEqual(NanoMuseAvatarIntent.parseChoice("就第四个吧"), .index(3))
        XCTAssertEqual(NanoMuseAvatarIntent.parseChoice("右下"), .index(3))
        XCTAssertEqual(NanoMuseAvatarIntent.parseChoice("regenerate"), .regenerate)
        XCTAssertEqual(NanoMuseAvatarIntent.parseChoice("都不喜欢"), .regenerate)
        XCTAssertNil(NanoMuseAvatarIntent.parseChoice("tell me more about option two"))
    }

    // MARK: - Goals

    func testGoalFromBlock() throws {
        let block: [String: Any] = [
            "title": " Learn 20 Spanish words a week ",
            "why": "trip in June",
            "category": "interests",
            "check_every_hours": 48,
            "check_time": "at 18:30",
            "steps": ["Pick a list", "", "Review on Sunday"],
            "first_check": "How did the first list go?",
        ]
        let parsed = try XCTUnwrap(NanoMuseGoal.from(block: block))
        XCTAssertEqual(parsed.goal.title, "Learn 20 Spanish words a week")
        XCTAssertEqual(parsed.goal.category, .interests)
        XCTAssertEqual(parsed.goal.checkEveryHours, 48)
        XCTAssertEqual(parsed.goal.checkHour, 18)
        XCTAssertEqual(parsed.goal.checkMinute, 30)
        XCTAssertEqual(parsed.goal.steps.map(\.text), ["Pick a list", "Review on Sunday"])
        XCTAssertEqual(parsed.firstCheck, "How did the first list go?")
        XCTAssertNil(NanoMuseGoal.from(block: ["title": "  "]))
    }

    func testGoalUpdateBlock() {
        let update = NanoMuseGoal.Update(block: ["goal_id": "g1", "progress": 140, "status": "attention", "note": "slipping"])
        XCTAssertEqual(update?.goalId, "g1")
        XCTAssertEqual(update?.progress, 100)
        XCTAssertEqual(update?.status, .active)
        XCTAssertEqual(update?.note, "slipping")
        XCTAssertEqual(NanoMuseGoal.Update(block: ["status": "done"])?.status, .done)
        XCTAssertNil(NanoMuseGoal.Update(block: ["note": "   "]))
    }

    func testGoalCategoryFallsBackToOther() {
        XCTAssertEqual(NanoMuseGoalCategory.from("HEALTH"), .health)
        XCTAssertEqual(NanoMuseGoalCategory.from("whatever"), .other)
        XCTAssertEqual(NanoMuseGoalCategory.from(nil), .other)
    }

    // MARK: - Feed

    func testFeedDraftFromBlock() {
        let draft = NanoMusePost.Draft(block: ["title": "Rain later", "body": "Take the umbrella.", "type": "REMINDER", "emoji": "☔️", "source": "weather; calendar"])
        XCTAssertEqual(draft?.type, "reminder")
        XCTAssertEqual(draft?.source, ["weather", "calendar"])
        XCTAssertEqual(NanoMusePost.Draft(block: ["title": "x", "body": "y", "type": "nonsense"])?.type, "note")
        XCTAssertNil(NanoMusePost.Draft(block: ["title": "x"]))
    }

    func testFrontMatterSplit() {
        let (meta, body) = NanoMusePost.splitFrontMatter("---\ntitle: Hello\ntype: brief\n---\nThe body\nmore")
        XCTAssertEqual(meta["title"], "Hello")
        XCTAssertEqual(meta["type"], "brief")
        XCTAssertEqual(body, "The body\nmore")
        let (none, plain) = NanoMusePost.splitFrontMatter("just text")
        XCTAssertTrue(none.isEmpty)
        XCTAssertEqual(plain, "just text")
    }

    // MARK: - Scheduler arithmetic

    private func date(_ y: Int, _ mo: Int, _ d: Int, _ h: Int, _ mi: Int, _ cal: Calendar) -> Date {
        cal.date(from: DateComponents(year: y, month: mo, day: d, hour: h, minute: mi))!
    }

    func testDailyRoutineNextDue() {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone(identifier: "UTC")!
        var routine = NanoMuseRoutine(label: "Brief", prompt: "x", hour: 8, minute: 0)
        routine.createdAt = date(2026, 10, 1, 7, 0, cal)
        // created before 08:00 → due the same day
        XCTAssertEqual(routine.nextDue(after: date(2026, 10, 1, 7, 30, cal), calendar: cal), date(2026, 10, 1, 8, 0, cal))
        // already fired this slot → tomorrow
        routine.lastFiredAt = date(2026, 10, 1, 8, 1, cal)
        XCTAssertEqual(routine.nextDue(after: date(2026, 10, 1, 9, 0, cal), calendar: cal), date(2026, 10, 2, 8, 0, cal))
    }

    func testRoutineCreatedAfterSlotWaitsForTomorrow() {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone(identifier: "UTC")!
        var routine = NanoMuseRoutine(label: "Brief", prompt: "x", hour: 8, minute: 0)
        routine.createdAt = date(2026, 10, 1, 9, 0, cal)
        XCTAssertEqual(routine.nextDue(after: date(2026, 10, 1, 9, 5, cal), calendar: cal), date(2026, 10, 2, 8, 0, cal))
    }

    func testWeekdaysRoutineSkipsTheWeekend() {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone(identifier: "UTC")!
        var routine = NanoMuseRoutine(label: "Standup", prompt: "x", hour: 9, minute: 0, repeatMode: .weekdays)
        routine.createdAt = date(2026, 10, 1, 0, 0, cal)
        // 2026-10-03 is a Saturday
        XCTAssertEqual(routine.nextDue(after: date(2026, 10, 3, 10, 0, cal), calendar: cal), date(2026, 10, 5, 9, 0, cal))
    }

    func testOnceRoutineCreatedAfterItsTimeRunsTomorrow() {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone(identifier: "UTC")!
        var routine = NanoMuseRoutine(label: "Call", prompt: "x", hour: 18, minute: 0, repeatMode: .once)
        routine.createdAt = date(2026, 10, 1, 19, 0, cal)
        // made at 19:00 for 18:00 → tomorrow at 18:00, not never
        XCTAssertEqual(routine.nextDue(after: date(2026, 10, 1, 19, 5, cal), calendar: cal), date(2026, 10, 2, 18, 0, cal))
        // made before its time → today; once run → spent
        routine.createdAt = date(2026, 10, 1, 15, 0, cal)
        XCTAssertEqual(routine.nextDue(after: date(2026, 10, 1, 15, 5, cal), calendar: cal), date(2026, 10, 1, 18, 0, cal))
        routine.lastFiredAt = date(2026, 10, 1, 18, 0, cal)
        XCTAssertNil(routine.nextDue(after: date(2026, 10, 1, 18, 5, cal), calendar: cal))
    }

    func testIntervalRoutineCountsFromTheLastRun() {
        let cal = Calendar(identifier: .gregorian)
        var routine = NanoMuseRoutine(label: "Check-in", prompt: "x", hour: 9, minute: 0)
        routine.intervalHours = 6
        let fired = Date(timeIntervalSince1970: 1_800_000_000)
        routine.lastFiredAt = fired
        XCTAssertEqual(routine.nextDue(after: fired.addingTimeInterval(60), calendar: cal), fired.addingTimeInterval(6 * 3600))
    }

    // MARK: - Region (contract C5)

    func testMainlandRule() {
        XCTAssertTrue(NanoMuseRegion.isMainland(languageCode: "zh", scriptCode: "Hans", regionCode: nil, signedInWithPhone: false, relayRegion: nil))
        XCTAssertTrue(NanoMuseRegion.isMainland(languageCode: "zh", scriptCode: nil, regionCode: "CN", signedInWithPhone: false, relayRegion: nil))
        XCTAssertTrue(NanoMuseRegion.isMainland(languageCode: "zh", scriptCode: nil, regionCode: nil, signedInWithPhone: false, relayRegion: nil))
        XCTAssertFalse(NanoMuseRegion.isMainland(languageCode: "zh", scriptCode: "Hant", regionCode: "TW", signedInWithPhone: false, relayRegion: nil))
        XCTAssertFalse(NanoMuseRegion.isMainland(languageCode: "en", scriptCode: nil, regionCode: "US", signedInWithPhone: false, relayRegion: nil))
        XCTAssertTrue(NanoMuseRegion.isMainland(languageCode: "en", scriptCode: nil, regionCode: "US", signedInWithPhone: true, relayRegion: nil))
        XCTAssertTrue(NanoMuseRegion.isMainland(languageCode: "en", scriptCode: nil, regionCode: "US", signedInWithPhone: false, relayRegion: "CN"))
    }

    // MARK: - Models (contract C4)

    func testRecommendedChatPrefersTheMarkedModelThenTheDefault() {
        let marked: [[String: Any]] = [
            ["id": "qwen3.8-flash", "for": ["chat"]],
            ["id": "qwen3.8-27b", "for": ["chat", "gui"], "nanomuse": ["recommended": true]],
        ]
        XCTAssertEqual(NanoMuseModelMenu.recommendedChat(marked)?["id"] as? String, "qwen3.8-27b")
        let plain: [[String: Any]] = [
            ["id": "qwen3.8-27b", "for": ["gui"]],
            ["id": "deepseek-v4.1-flash", "for": ["chat"]],
        ]
        XCTAssertEqual(NanoMuseModelMenu.recommendedChat(plain)?["id"] as? String, NanoMuseModelMenu.defaultChatModel)
        let drawsOnly: [[String: Any]] = [["id": "qwen3.8-27b", "for": ["gui"]]]
        XCTAssertNil(NanoMuseModelMenu.recommendedChat(drawsOnly))
        XCTAssertEqual(NanoMuseModelMenu.guiModel(plain), "qwen3.8-27b")
        // the relay 0.17 shape: the lanes live under `nanomuse`, next to its other flags
        let relay: [[String: Any]] = [
            ["id": "qwen3.8-27b", "nanomuse": ["for": ["gui", "chat"], "recommended": true, "recommended_for": ["gui"]]],
            ["id": "deepseek-v4.1-flash", "nanomuse": ["for": ["chat"], "recommended": true, "recommended_for": ["chat"]]],
            ["id": "qwen3.8-flash", "nanomuse": ["for": ["chat"], "recommended": false]],
        ]
        XCTAssertEqual(NanoMuseModelMenu.recommendedChat(relay)?["id"] as? String, "deepseek-v4.1-flash")
        XCTAssertEqual(NanoMuseModelMenu.guiModel(relay), "qwen3.8-27b")
        XCTAssertEqual(NanoMuseModelMenu.lanes(relay[0]), ["gui", "chat"])
    }

    func testDeepSeekVisionRule() {
        XCTAssertEqual(NanoMuseVision.deepSeekSees("deepseek-v4.1-flash"), true)
        XCTAssertEqual(NanoMuseVision.deepSeekSees("deepseek/deepseek-v4.1-flash"), true)
        XCTAssertEqual(NanoMuseVision.deepSeekSees("deepseek-v4-pro"), false)
        XCTAssertEqual(NanoMuseVision.deepSeekSees("deepseek-chat"), false)
        XCTAssertEqual(NanoMuseVision.deepSeekSees("deepseek-r1"), false)
        XCTAssertEqual(NanoMuseVision.deepSeekSees("deepseek-ocr"), true)
        XCTAssertEqual(NanoMuseVision.deepSeekSees("deepseek-vl2"), false)
        XCTAssertNil(NanoMuseVision.deepSeekSees("qwen3.8-27b"))
        XCTAssertEqual(NanoMuseVision.guess(id: "deepseek-chat"), .textOnly)
        XCTAssertEqual(NanoMuseVision.guess(id: "deepseek-v4.1-flash"), .vision)
        XCTAssertEqual(NanoMuseVision.guess(id: "qwen3.8-27b"), .vision)
        XCTAssertNil(NanoMuseVision.guess(id: "some-unknown-model"))
    }

    func testOwnKeyPresets() {
        XCTAssertEqual(NanoMuseOwnKeyPreset.bailian.chatModel, "deepseek-v4.1-flash")
        XCTAssertEqual(NanoMuseOwnKeyPreset.bailian.guiModel, "qwen3.8-27b")
        XCTAssertEqual(NanoMuseOwnKeyPreset.openrouter.chatModel, "deepseek/deepseek-v4.1-flash")
        XCTAssertEqual(NanoMuseOwnKeyPreset.openrouter.guiModel, "qwen/qwen3.8-27b")
    }

    // MARK: - First run

    func testFirstRunNeeded() {
        // Neither a sign-in nor a key of one's own: nothing could answer, the setup comes back.
        XCTAssertTrue(NanoMuseFirstRun.needed(signedIn: false, hasProviders: false, hasSessions: true, done: true))
        // Signed out with a key of one's own, the chat stays; so does a signed-in phone whose Cloud models are off.
        XCTAssertFalse(NanoMuseFirstRun.needed(signedIn: false, hasProviders: true, hasSessions: true, done: true))
        XCTAssertFalse(NanoMuseFirstRun.needed(signedIn: true, hasProviders: false, hasSessions: true, done: true))
        XCTAssertTrue(NanoMuseFirstRun.needed(signedIn: true, hasProviders: true, hasSessions: false, done: false))
        XCTAssertFalse(NanoMuseFirstRun.needed(signedIn: true, hasProviders: true, hasSessions: false, done: true))
        XCTAssertFalse(NanoMuseFirstRun.needed(signedIn: true, hasProviders: true, hasSessions: true, done: false))
    }

    func testFirstRunStages() {
        XCTAssertEqual(NanoMuseFirstRun.stage(signedIn: false, hasGroups: false, sourceChosen: false, modelsSkipped: false, fresh: false, passwordAnswered: false), .welcome)
        // Signed out with a key of one's own: past the welcome, and the account's pages (password, source) are skipped.
        XCTAssertEqual(NanoMuseFirstRun.stage(signedIn: false, hasProviders: true, hasGroups: false, sourceChosen: false, modelsSkipped: false, fresh: false, passwordAnswered: false), .models)
        XCTAssertEqual(NanoMuseFirstRun.stage(signedIn: false, hasProviders: true, hasGroups: true, sourceChosen: false, modelsSkipped: false, fresh: false, passwordAnswered: false), .meet)
        XCTAssertEqual(NanoMuseFirstRun.stage(signedIn: true, hasGroups: false, sourceChosen: false, modelsSkipped: false, fresh: true, passwordAnswered: false), .password)
        XCTAssertEqual(NanoMuseFirstRun.stage(signedIn: true, hasGroups: false, sourceChosen: false, modelsSkipped: false, fresh: true, passwordAnswered: true), .source)
        XCTAssertEqual(NanoMuseFirstRun.stage(signedIn: true, hasGroups: false, sourceChosen: true, modelsSkipped: false, fresh: false, passwordAnswered: false), .models)
        XCTAssertEqual(NanoMuseFirstRun.stage(signedIn: true, hasGroups: true, sourceChosen: true, modelsSkipped: false, fresh: false, passwordAnswered: false), .meet)
        XCTAssertEqual(NanoMuseFirstRun.stage(signedIn: true, hasGroups: false, sourceChosen: true, modelsSkipped: true, fresh: false, passwordAnswered: false), .meet)
        // The phone page (notifications) sits between the model pages and Meet, as Android's Hands page does.
        XCTAssertEqual(NanoMuseFirstRun.stage(signedIn: true, hasGroups: true, sourceChosen: true, modelsSkipped: false, fresh: false, passwordAnswered: false, notificationsSeen: false), .notifications)
        XCTAssertEqual(NanoMuseFirstRun.stage(signedIn: true, hasGroups: false, sourceChosen: true, modelsSkipped: false, fresh: false, passwordAnswered: false, notificationsSeen: false), .models)
        // Three dots: account · phone · meet.
        XCTAssertEqual(NanoMuseFirstRun.dot(.welcome), 0)
        XCTAssertEqual(NanoMuseFirstRun.dot(.password), 0)
        XCTAssertEqual(NanoMuseFirstRun.dot(.source), 0)
        XCTAssertEqual(NanoMuseFirstRun.dot(.models), 0)
        XCTAssertEqual(NanoMuseFirstRun.dot(.notifications), 1)
        XCTAssertEqual(NanoMuseFirstRun.dot(.meet), 2)
    }

    // MARK: - Header status line (Android §2.2 order)

    func testStatusLinePriority() {
        XCTAssertEqual(NanoMuseStatus.line(waiting: true, needsApproval: true, processing: true, toolName: "shell", toolTitle: "Running ls", request: "hi", studio: "Drawing", motion: "Animating 1/4…"), AppLocalized("Needs approval"))
        XCTAssertEqual(NanoMuseStatus.line(waiting: true, processing: true, toolName: "shell", toolTitle: "Running ls", request: "hi", studio: "Drawing"), AppLocalized("Waiting for you"))
        XCTAssertEqual(NanoMuseStatus.line(waiting: false, processing: true, toolName: "shell", toolTitle: "Running ls", request: "hi", studio: "Drawing"), "Drawing")
        XCTAssertEqual(NanoMuseStatus.line(waiting: false, processing: true, toolName: "shell", toolTitle: "Running ls", request: "hi", studio: nil), "Running ls")
        XCTAssertEqual(NanoMuseStatus.line(waiting: false, processing: true, toolName: "text", toolTitle: "", request: "hi", studio: nil), AppLocalized("Writing the reply"))
        XCTAssertEqual(NanoMuseStatus.line(waiting: false, processing: true, toolName: "", toolTitle: "", request: "Plan my week", studio: nil), String(format: AppLocalized("On it: %@"), "Plan my week"))
        XCTAssertEqual(NanoMuseStatus.line(waiting: false, processing: true, toolName: "", toolTitle: "", request: nil, studio: nil), AppLocalized("On it"))
        XCTAssertEqual(NanoMuseStatus.line(waiting: false, processing: false, toolName: "", toolTitle: "", request: "hi", studio: nil, motion: "Animating 2/4…"), "Animating 2/4…")
        XCTAssertNil(NanoMuseStatus.line(waiting: false, processing: false, toolName: "", toolTitle: "", request: "hi", studio: nil))
    }

    // MARK: - Appearance

    func testAvatarSizes() {
        XCTAssertEqual(NanoMuseAvatarSize.small.points, 44)
        XCTAssertEqual(NanoMuseAvatarSize.medium.points, 56)
        XCTAssertEqual(NanoMuseAvatarSize.large.points, 66)
        XCTAssertEqual(NanoMuseAvatarSize.extraLarge.points, 76)
        XCTAssertNil(NanoMuseAvatarSize.hidden.points)
        XCTAssertEqual(NanoMuseAvatarSize.stored(nil), .extraLarge)
        XCTAssertEqual(NanoMuseAvatarSize.stored("junk"), .extraLarge)
        XCTAssertEqual(NanoMuseAvatarSize.stored("small"), .small)
    }

    // MARK: - Transcript

    func testAssistantBubbleStaysBareForCodeAndTables() {
        XCTAssertFalse(NanoMuseAssistantBubble.isBare("Here is the plan."))
        XCTAssertTrue(NanoMuseAssistantBubble.isBare("```swift\nlet a = 1\n```"))
        XCTAssertTrue(NanoMuseAssistantBubble.isBare("| a | b |\n|---|---|\n| 1 | 2 |"))
        XCTAssertTrue(NanoMuseAssistantBubble.isBare("<table><tr><td>1</td></tr></table>"))
    }

    // MARK: - First conversation (naming)

    func testNamingBlockParsing() {
        let text = "What should I call you?\n```nanomuse-naming\n{\"user_address\": \"“Li”\", \"suggest\": [\"Pip\", \"Pip\", \"'Wren'\", \"Sol\", \"Fig\"]}\n```"
        let block = NanoMuseFirstConversation.parseBlock(text)
        XCTAssertEqual(block?.userAddress, "Li")
        XCTAssertTrue(block?.addressGiven ?? false)
        XCTAssertEqual(block?.suggestions, ["Pip", "Wren", "Sol"])
        XCTAssertNil(block?.agentName)
        XCTAssertNil(NanoMuseFirstConversation.parseBlock("no block here"))
        XCTAssertNil(NanoMuseFirstConversation.parseBlock(nil))
    }

    func testCleanName() {
        XCTAssertEqual(NanoMuseFirstConversation.cleanName("「小满」。"), "小满")
        XCTAssertEqual(NanoMuseFirstConversation.cleanName("  Juno!  "), "Juno")
        XCTAssertNil(NanoMuseFirstConversation.cleanName("a name that is far too long to use"))
        XCTAssertNil(NanoMuseFirstConversation.cleanName("two\nlines"))
        XCTAssertNil(NanoMuseFirstConversation.cleanName(""))
        XCTAssertNil(NanoMuseFirstConversation.cleanName(nil))
    }

    func testWithAddressWritesAndReplacesTheLine() {
        let fresh = NanoMuseFirstConversation.withAddress("Li", in: "")
        XCTAssertEqual(fresh, "## About the user\n- Call them: Li\n")
        let appended = NanoMuseFirstConversation.withAddress("Li", in: "# GLOBAL\nSome notes.\n\n")
        XCTAssertTrue(appended.hasSuffix("## About the user\n- Call them: Li\n"))
        XCTAssertTrue(appended.hasPrefix("# GLOBAL\nSome notes."))
        let replaced = NanoMuseFirstConversation.withAddress("Wei", in: appended)
        XCTAssertTrue(replaced.contains("- Call them: Wei"))
        XCTAssertFalse(replaced.contains("- Call them: Li"))
        XCTAssertEqual(replaced.components(separatedBy: "- Call them:").count, 2)
    }

    func testPoolPickIsStableAndDistinct() {
        let a = NanoMuseFirstConversation.poolPick(seed: "session-1", chinese: false)
        let b = NanoMuseFirstConversation.poolPick(seed: "session-1", chinese: false)
        XCTAssertEqual(a, b)
        XCTAssertEqual(a.count, 2)
        XCTAssertNotEqual(a[0], a[1])
        let zh = NanoMuseFirstConversation.poolPick(seed: "x", chinese: true)
        XCTAssertTrue(NanoMuseFirstConversation.namePoolZH.contains(zh[0]))
    }

    func testRealSessionKeys() {
        XCTAssertTrue(NanoMuseFirstConversation.isRealSession("3F2504E0-4F89-11D3-9A0C-0305E82C3301"))
        XCTAssertFalse(NanoMuseFirstConversation.isRealSession("__new__3F2504E0-4F89-11D3-9A0C-0305E82C3301"))
        XCTAssertFalse(NanoMuseFirstConversation.isRealSession("draft"))
    }

    // MARK: - Coding bridge

    func testCodingRunFoldsEvents() {
        var run = NanoMuseCodingBridge.LiveRun(text: "fix the test")
        run = NanoMuseCodingBridge.step(run, event: ["kind": "started", "run": "r1", "session_id": "s1"])
        XCTAssertEqual(run.id, "r1")
        XCTAssertEqual(run.sessionId, "s1")
        run = NanoMuseCodingBridge.step(run, event: ["kind": "text", "text": "Looking", "partial": true])
        run = NanoMuseCodingBridge.step(run, event: ["kind": "text", "text": " at it", "partial": true])
        XCTAssertEqual(run.current, "Looking at it")
        run = NanoMuseCodingBridge.step(run, event: ["kind": "text", "text": "Looking at it."])
        XCTAssertEqual(run.output, "Looking at it.")
        XCTAssertEqual(run.current, "")
        run = NanoMuseCodingBridge.step(run, event: ["kind": "tool", "text": "read_file"])
        XCTAssertEqual(run.tools, 1)
        XCTAssertEqual(run.lastTool, "read_file")
        let done = NanoMuseCodingBridge.finish(run, reply: ["id": "r1", "status": "done", "output": "", "tools": 3])
        XCTAssertEqual(done.output, "Looking at it.")
        XCTAssertEqual(done.status, "done")
        XCTAssertEqual(done.tools, 3)
        let withOutput = NanoMuseCodingBridge.finish(run, reply: ["output": "Final answer", "error": "boom"])
        XCTAssertEqual(withOutput.output, "Final answer")
        XCTAssertEqual(withOutput.error, "boom")
    }

    // MARK: - Shared connectors (contract C3)

    func testSharedConnectorEntriesCarryNoSecrets() {
        let now = Date().timeIntervalSince1970
        let servers = [
            MCPServerConfig(id: "github", note: nil, enabled: true, createdAt: now, updatedAt: now,
                            url: "https://api.githubcopilot.com/mcp/", headers: ["Authorization": "Bearer SECRET"], oauth: nil,
                            command: nil, args: nil, env: nil, startupTimeoutSeconds: nil),
            MCPServerConfig(id: "maps", note: "Maps", enabled: false, createdAt: now - 10, updatedAt: now,
                            url: "https://example.invalid/mcp?key=SECRET", headers: nil, oauth: nil,
                            command: nil, args: nil, env: nil, startupTimeoutSeconds: nil),
            MCPServerConfig(id: "local", note: nil, enabled: true, createdAt: now - 20, updatedAt: now,
                            url: nil, headers: nil, oauth: nil,
                            command: "npx", args: ["thing"], env: nil, startupTimeoutSeconds: nil),
        ]
        let mine = NanoMuseSharedConnectors.mine(servers: servers, catalogue: [], device: "Li's iPhone", deviceId: "phone-abc")
        XCTAssertEqual(mine.count, 2, "a stdio command is not a service anyone else can sign in to")
        XCTAssertEqual(mine[0]["id"] as? String, "github")
        XCTAssertEqual(mine[0]["auth"] as? String, "key")
        XCTAssertEqual(mine[1]["url"] as? String, "https://example.invalid/mcp")
        XCTAssertEqual(mine[1]["auth"] as? String, "key")
        XCTAssertEqual(mine[1]["label"] as? String, "Maps")
        XCTAssertEqual(mine[1]["enabled"] as? Bool, false)
        for entry in mine {
            let keys = Set(entry.keys)
            XCTAssertEqual(keys, ["id", "label", "url", "auth", "device", "device_id", "enabled", "at"])
            for (_, value) in entry {
                XCTAssertFalse("\(value)".contains("SECRET"))
            }
        }
    }

    func testSharedConnectorParseAndStamp() {
        let raw: [[String: Any]] = [
            ["id": "slack", "label": "", "device": "Mac", "device_id": "mac-1", "enabled": true, "at": "2026-10-01T08:00:00Z"],
            ["id": "  ", "device_id": "mac-1"],
            ["id": "notion", "label": "Notion", "auth": "oauth", "device_id": "mac-2"],
        ]
        let parsed = NanoMuseSharedConnectors.parse(raw)
        XCTAssertEqual(parsed.map(\.id), ["slack", "notion"])
        XCTAssertEqual(parsed[0].label, "slack")
        XCTAssertEqual(parsed[0].auth, "open")
        XCTAssertEqual(parsed[1].auth, "oauth")
        XCTAssertTrue(parsed[1].enabled)
        let again = NanoMuseSharedConnectors.parse(NanoMuseSharedConnectors.serialize(parsed))
        XCTAssertEqual(again, parsed)
        let a = NanoMuseSharedConnectors.stamp([["id": "a", "enabled": true, "at": "1"], ["id": "b", "enabled": true, "at": "2"]])
        let b = NanoMuseSharedConnectors.stamp([["id": "b", "enabled": true, "at": "9"], ["id": "a", "enabled": true, "at": "8"]])
        XCTAssertEqual(a, b, "order and timestamps do not count as a change")
        let c = NanoMuseSharedConnectors.stamp([["id": "a", "enabled": false], ["id": "b", "enabled": true]])
        XCTAssertNotEqual(a, c)
    }

    // MARK: - Video generation (pure parts)

    func testVideoGenModelSiblingsAndParameters() {
        XCTAssertEqual(NanoMuseVideoGen.model(for: "wan2.2-i2v-flash", fromImage: true), "wan2.2-i2v-flash")
        XCTAssertEqual(NanoMuseVideoGen.model(for: "wan2.2-i2v-flash", fromImage: false), "wan2.2-t2v-plus", "Wan 2.2 has no text-to-video Flash")
        XCTAssertEqual(NanoMuseVideoGen.model(for: "wan2.6-t2v", fromImage: true), "wan2.6-i2v")
        XCTAssertEqual(NanoMuseVideoGen.model(for: "wan2.6-i2v", fromImage: false), "wan2.6-t2v")
        XCTAssertEqual(NanoMuseVideoGen.model(for: "MiniMax/MiniMax-H3", fromImage: false), "MiniMax/MiniMax-H3")

        XCTAssertEqual(NanoMuseVideoGen.wanResolution("wan2.2-i2v-flash"), "480P")
        XCTAssertEqual(NanoMuseVideoGen.wanResolution("wan2.6-i2v"), "720P")

        XCTAssertNil(NanoMuseVideoGen.duration(for: "wan2.2-i2v-flash", seconds: 4), "Wan 2.2 has a fixed length")
        XCTAssertEqual(NanoMuseVideoGen.duration(for: "wan2.5-i2v-preview", seconds: 4), 5)
        XCTAssertEqual(NanoMuseVideoGen.duration(for: "wan2.5-i2v-preview", seconds: 8), 10)
        XCTAssertEqual(NanoMuseVideoGen.duration(for: "wan2.6-i2v", seconds: 1), 2)
        XCTAssertEqual(NanoMuseVideoGen.duration(for: "wan2.6-i2v", seconds: 40), 15)
        XCTAssertEqual(NanoMuseVideoGen.duration(for: "MiniMax/MiniMax-H3", seconds: 2), 4)

        XCTAssertEqual(NanoMuseVideoGen.wanSize("16:9"), "1280*720")
        XCTAssertEqual(NanoMuseVideoGen.wanSize("9:16"), "720*1280")
        XCTAssertEqual(NanoMuseVideoGen.wanSize("1:1"), "960*960")
    }

    func testVideoGenHostsAndMessages() {
        XCTAssertEqual(NanoMuseVideoGen.host(of: "https://dashscope.aliyuncs.com/compatible-mode/v1"), "https://dashscope.aliyuncs.com")
        XCTAssertEqual(NanoMuseVideoGen.host(of: "https://dashscope.aliyuncs.com/api/v1/"), "https://dashscope.aliyuncs.com")
        XCTAssertEqual(NanoMuseVideoGen.host(of: "https://relay.example/v1"), "https://relay.example")
        XCTAssertEqual(NanoMuseVideoGen.host(of: "https://relay.example/"), "https://relay.example")
        XCTAssertTrue(NanoMuseVideoGen.speaksDashScope("https://dashscope-intl.aliyuncs.com/compatible-mode/v1"))
        XCTAssertFalse(NanoMuseVideoGen.speaksDashScope("https://api.openai.com/v1"))
        XCTAssertTrue(NanoMuseVideoGen.looksLikeVideoModel("wan2.6-t2v"))
        XCTAssertTrue(NanoMuseVideoGen.looksLikeVideoModel("MiniMax/MiniMax-H3"))
        XCTAssertFalse(NanoMuseVideoGen.looksLikeVideoModel("qwen-image-3.0"))
        XCTAssertEqual(NanoMuseVideoGen.knownDashScopeModels.first, "wan2.2-i2v-flash")

        XCTAssertTrue(NanoMuseVideoGen.failureMessage(["code": "Arrearage", "message": "Model not activated for this account"]).contains("activate"))
        XCTAssertEqual(NanoMuseVideoGen.failureMessage(["code": "InvalidParameter", "message": "bad size"]), "InvalidParameter: bad size")
        XCTAssertTrue(NanoMuseVideoGen.failureMessage(["task_status": "CANCELED"]).contains("CANCELED"))
        XCTAssertTrue(NanoMuseVideoGen.failureMessage([:]).contains("FAILED"))
        XCTAssertEqual(NanoMuseVideoGen.apiMessage(Data("{\"message\":\"nope\"}".utf8)), "nope")
        XCTAssertEqual(NanoMuseVideoGen.apiMessage(Data("{\"error\":{\"message\":\"clips used up\"}}".utf8)), "clips used up")
        XCTAssertEqual(NanoMuseVideoGen.apiMessage(Data("not json".utf8)), "")
        let refused = NanoMuseMediaWords.refused(status: 401, vendorMessage: "Invalid API-key provided.")
        XCTAssertTrue(refused.contains("401") && refused.contains("Invalid API-key provided."))
        XCTAssertFalse(NanoMuseMediaWords.refused(status: 503, vendorMessage: "").contains(":"))

        XCTAssertNil(NanoMuseVideoGen.frameScale(width: 768, height: 768))
        XCTAssertEqual(NanoMuseVideoGen.frameScale(width: 2048, height: 2048), 0.5)
        XCTAssertEqual(NanoMuseVideoGen.frameScale(width: 128, height: 128), 2)
    }

    // MARK: - Nudges policy and the star gate (contract C1)

    func testNudgePolicyParsesAndKeepsDefaults() {
        let d = NanoMuseNudgePolicy.defaults
        XCTAssertTrue(d.enabled)
        XCTAssertEqual(d.tasks, [3, 10, 30])
        XCTAssertEqual(d.daysUsed, [7, 30])
        XCTAssertEqual(d.cooldownDays, 7)
        XCTAssertEqual(d.maxAsks, 4)
        XCTAssertEqual(NanoMuseNudgePolicy.parse([:]), d, "an empty reply is the defaults")
        XCTAssertEqual(NanoMuseNudgePolicy.parse(d.json), d, "round trip")

        let p = NanoMuseNudgePolicy.parse([
            "version": 1,
            "star": [
                "enabled": false,
                "url": "javascript:alert(1)",
                "moments": ["tasks": [10, 3, 3, "x"], "days_used": [], "goal_done": false],
                "cooldown_days": -2,
                "max_asks": "2",
            ] as [String: Any],
        ])
        XCTAssertFalse(p.enabled)
        XCTAssertEqual(p.url, d.url, "only https links are taken")
        XCTAssertEqual(p.tasks, [3, 10])
        XCTAssertEqual(p.daysUsed, [])
        XCTAssertFalse(p.goalDone)
        XCTAssertTrue(p.signedIn, "a missing moment keeps its default")
        XCTAssertEqual(p.cooldownDays, 0)
        XCTAssertEqual(p.maxAsks, 2)
    }

    func testNudgePolicyReadsTheOperatorsSentence() {
        let d = NanoMuseNudgePolicy.defaults
        XCTAssertEqual(d.text, "")
        XCTAssertEqual(d.textZh, "")
        XCTAssertNil(d.sentence(chinese: false), "without a sentence the app's own line stays")
        XCTAssertNil(d.sentence(chinese: true))

        // A cached copy from before the fields: neither key, both empty, the same policy.
        var old: [String: Any] = d.json
        var star: [String: Any] = old["star"] as? [String: Any] ?? [:]
        star.removeValue(forKey: "text")
        star.removeValue(forKey: "text_zh")
        old["star"] = star
        XCTAssertEqual(NanoMuseNudgePolicy.parse(old), d)

        let p = NanoMuseNudgePolicy.parse([
            "star": ["text": "  Stars help.  ", "text_zh": "\n点个 star。\t"] as [String: Any],
        ])
        XCTAssertEqual(p.text, "Stars help.", "trimmed")
        XCTAssertEqual(p.textZh, "点个 star。")
        XCTAssertEqual(NanoMuseNudgePolicy.parse(p.json), p, "round trip through the cache")

        let odd = NanoMuseNudgePolicy.parse(["star": ["text": 42, "text_zh": ["x"]] as [String: Any]])
        XCTAssertEqual(odd.text, "", "not a string: empty, never a crash")
        XCTAssertEqual(odd.textZh, "")
    }

    func testNudgePolicyDropsASentenceOver200Characters() {
        let ok = String(repeating: "a", count: 200)
        let tooLong = String(repeating: "a", count: 201)
        let p = NanoMuseNudgePolicy.parse(["star": ["text": ok, "text_zh": tooLong] as [String: Any]])
        XCTAssertEqual(p.text, ok)
        XCTAssertEqual(p.textZh, "")
        let padded = String(repeating: " ", count: 10) + ok + String(repeating: " ", count: 10)
        XCTAssertEqual(NanoMuseNudgePolicy.parse(["star": ["text": padded] as [String: Any]]).text, ok, "the limit applies after trimming")
    }

    func testNudgePolicySentenceFallsBackInOrder() {
        var both = NanoMuseNudgePolicy.defaults
        both.text = "English line"
        both.textZh = "中文句子"
        XCTAssertEqual(both.sentence(chinese: true), "中文句子")
        XCTAssertEqual(both.sentence(chinese: false), "English line")

        var englishOnly = NanoMuseNudgePolicy.defaults
        englishOnly.text = "English line"
        XCTAssertEqual(englishOnly.sentence(chinese: true), "English line", "Chinese without text_zh takes text")
        XCTAssertEqual(englishOnly.sentence(chinese: false), "English line")

        var chineseOnly = NanoMuseNudgePolicy.defaults
        chineseOnly.textZh = "中文句子"
        XCTAssertEqual(chineseOnly.sentence(chinese: true), "中文句子")
        XCTAssertNil(chineseOnly.sentence(chinese: false), "another language never takes text_zh")
    }

    func testStarGate() {
        let policy = NanoMuseNudgePolicy.defaults
        var ledger = NanoMuseStarLedger()
        let now = Date(timeIntervalSince1970: 1_800_000_000)

        XCTAssertTrue(NanoMuseStarGate.due(.signedIn, ledger: ledger, policy: policy, now: now))
        XCTAssertFalse(NanoMuseStarGate.due(.tasks(2), ledger: ledger, policy: policy, now: now), "2 is not a threshold")
        XCTAssertTrue(NanoMuseStarGate.due(.tasks(3), ledger: ledger, policy: policy, now: now))

        ledger = NanoMuseStarGate.marked(.tasks(3), in: ledger, now: now)
        XCTAssertEqual(ledger.asks, 1)
        XCTAssertFalse(NanoMuseStarGate.due(.tasks(3), ledger: ledger, policy: policy, now: now), "once per threshold")
        XCTAssertFalse(NanoMuseStarGate.due(.newLook, ledger: ledger, policy: policy, now: now.addingTimeInterval(86_400)), "cooldown")
        XCTAssertTrue(NanoMuseStarGate.due(.newLook, ledger: ledger, policy: policy, now: now.addingTimeInterval(8 * 86_400)))
        XCTAssertTrue(NanoMuseStarGate.due(.tasks(10), ledger: ledger, policy: policy, now: now.addingTimeInterval(8 * 86_400)), "the next threshold is its own moment")

        var capped = ledger
        capped.asks = policy.maxAsks
        XCTAssertFalse(NanoMuseStarGate.due(.goalDone, ledger: capped, policy: policy, now: now.addingTimeInterval(30 * 86_400)), "lifetime cap")

        var starred = ledger
        starred.starred = true
        XCTAssertFalse(NanoMuseStarGate.due(.exhausted, ledger: starred, policy: policy, now: now.addingTimeInterval(30 * 86_400)))

        // "I already starred" on the first card: nothing shown, no cooldown, every ask left, still nothing
        var done = NanoMuseStarLedger()
        done.starred = true
        var generous = policy
        generous.cooldownDays = 0
        generous.maxAsks = 99
        let later = now.addingTimeInterval(365 * 86_400)
        for moment: NanoMuseStarMoment in [.signedIn, .tasks(3), .newLook, .exhausted, .daysUsed(7), .goalDone] {
            XCTAssertFalse(NanoMuseStarGate.due(moment, ledger: done, policy: generous, now: later), "\(moment.key) after I already starred")
        }

        var off = policy
        off.enabled = false
        XCTAssertFalse(NanoMuseStarGate.due(.signedIn, ledger: NanoMuseStarLedger(), policy: off, now: now))

        let day1 = NanoMuseStarGate.dayOpened(NanoMuseStarLedger(), dayKey: "2026-10-05")
        XCTAssertEqual(day1.days, 1)
        XCTAssertEqual(NanoMuseStarGate.dayOpened(day1, dayKey: "2026-10-05").days, 1, "the same day counts once")
        XCTAssertEqual(NanoMuseStarGate.dayOpened(day1, dayKey: "2026-10-06").days, 2)
        XCTAssertEqual(NanoMuseStarMoment.daysUsed(7).key, "days_used.7")
        XCTAssertEqual(NanoMuseStarMoment.tasks(30).key, "tasks.30")
    }

    // MARK: - Update check (contract C2)

    func testVersionCompare() {
        XCTAssertEqual(NanoMuseUpdateCheck.compareVersions("1.4.0", "1.4.0"), 0)
        XCTAssertEqual(NanoMuseUpdateCheck.compareVersions("v1.4.0", "1.4"), 0, "a missing part is 0; a leading v is ignored")
        XCTAssertEqual(NanoMuseUpdateCheck.compareVersions("1.10.0", "1.9.9"), 1, "numbers, not strings")
        XCTAssertEqual(NanoMuseUpdateCheck.compareVersions("1.4.0", "1.4.1"), -1)
        XCTAssertEqual(NanoMuseUpdateCheck.compareVersions("1.4.0", "1.4.0-beta.1"), 1, "a release beats its pre-release")
        XCTAssertEqual(NanoMuseUpdateCheck.compareVersions("1.4.0-beta.1", "1.4.0-beta.2"), -1)
        XCTAssertEqual(NanoMuseUpdateCheck.compareVersions("1.4.0+7", "1.4.0+9"), 0, "build metadata does not count")
        XCTAssertEqual(NanoMuseUpdateCheck.normalize(" v2.0.1\n"), "2.0.1")
    }

    func testUpdateIndexReadsTheReleasesList() {
        // The index as nanomuse.cn/dl/index.json is written: releases newest first, each with a tag.
        let index: [String: Any] = [
            "repo": "nano-muse/nanoMuse",
            "releases": [["tag": "v1.0.0", "name": "nanoMuse 1.0.0", "assets": [String]()], ["tag": "v0.1.41"]],
        ]
        let found = NanoMuseUpdateCheck.parseIndex(index)
        XCTAssertEqual(found?.version, "v1.0.0", "the newest release's tag, as Android reads it")
        XCTAssertEqual(found?.page, NanoMuseUpdateCheck.downloadPage, "a tap leads to the download page")
        XCTAssertEqual(NanoMuseUpdateCheck.parseIndex(["releases": [["tag": ""], ["tag": "v0.9.0"]]])?.version, "v0.9.0", "an empty tag is skipped")
        XCTAssertNil(NanoMuseUpdateCheck.parseIndex(["repo": "nano-muse/nanoMuse"]), "no releases, no answer")
        XCTAssertNil(NanoMuseUpdateCheck.parseIndex(["releases": [[String: Any]]()]))
        // The older shapes still read.
        XCTAssertEqual(NanoMuseUpdateCheck.parseIndex(["ios": ["version": "1.2.0", "page": "https://example.invalid/r"]]), NanoMuseUpdateCheck.Found(version: "1.2.0", page: "https://example.invalid/r"))
        XCTAssertEqual(NanoMuseUpdateCheck.parseIndex(["latest": "1.1.0"])?.page, NanoMuseUpdateCheck.downloadPage)
        // GitHub's release object.
        XCTAssertEqual(NanoMuseUpdateCheck.parseGitHubLatest(["tag_name": "v1.0.0", "html_url": "https://example.invalid/tag"]), NanoMuseUpdateCheck.Found(version: "v1.0.0", page: "https://example.invalid/tag"))
        XCTAssertNil(NanoMuseUpdateCheck.parseGitHubLatest(["message": "Not Found"]))
    }
}
