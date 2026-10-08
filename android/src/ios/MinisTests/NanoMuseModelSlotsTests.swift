import XCTest
@testable import Minis

/// The pure parts of Settings › Models (0.1.41 "Choice"): how a slot resolves when the
/// person did and did not choose, how a provider's default is matched, and how the relay's
/// menu is read for each slot. Android: ModelSlotsTest; desktop: cloud.test.ts (slots).
final class NanoMuseModelSlotsTests: XCTestCase {

    private let cloudId = "relay"

    private var cloud: NanoMuseSlotProvider {
        NanoMuseSlotProvider(
            id: cloudId, label: "nanoMuse Cloud", isCloud: true,
            capabilities: ["chat", "vision", "image", "video"],
            defaults: ["chat": "deepseek-v4.1-flash", "image": "qwen-image-3.0", "video": "wan2.2-i2v-flash"],
            models: [.chat: ["deepseek-v4.1-flash", "qwen3.8-27b"], .hands: ["qwen3.8-27b"], .image: ["qwen-image-3.0"], .video: ["wan2.2-i2v-flash"]]
        )
    }

    private var bailian: NanoMuseSlotProvider {
        NanoMuseSlotProvider(
            id: "bailian-1", label: "Alibaba Cloud Bailian", isCloud: false,
            capabilities: ["chat", "vision", "image", "video"],
            defaults: ["chat": "deepseek-v4.1-flash", "image": "qwen-image-3.0", "video": "wan2.2-i2v-flash"],
            models: [.chat: ["qwen-plus", "deepseek-v4.1-flash"], .image: ["qwen-image-3.0", "wan2.6-image"], .video: ["wan2.2-i2v-flash", "wan2.6-i2v"]]
        )
    }

    private var openrouter: NanoMuseSlotProvider {
        NanoMuseSlotProvider(
            id: "openrouter-1", label: "OpenRouter", isCloud: false,
            capabilities: ["chat", "vision", "image"],
            defaults: ["chat": "deepseek-v4.1-flash"],
            models: [.chat: ["anthropic/claude-sonnet-4.5", "deepseek/deepseek-v4.1-flash"]]
        )
    }

    // MARK: - A provider's default

    func testDefaultModelMatchesBareAndPrefixedIds() {
        XCTAssertEqual(bailian.defaultModel(for: .chat), "deepseek-v4.1-flash")
        XCTAssertEqual(openrouter.defaultModel(for: .chat), "deepseek/deepseek-v4.1-flash", "a vendor prefix still matches the catalogue's bare id")
        XCTAssertEqual(bailian.defaultModel(for: .image), "qwen-image-3.0")
        XCTAssertNil(openrouter.defaultModel(for: .image), "the capability is claimed, but iPhone draws only through Model Studio: no models, no slot")
        XCTAssertFalse(openrouter.has(.image))
        XCTAssertFalse(openrouter.has(.video))
    }

    func testDefaultModelFallsBackToTheFirstListed() {
        var p = bailian
        p.defaults["chat"] = "something-the-key-does-not-have"
        XCTAssertEqual(p.defaultModel(for: .chat), "qwen-plus")
    }

    func testCloudWithoutAMenuStillHoldsEverySlot() {
        var bare = cloud
        bare.models = [:]
        bare.defaults = [:]
        for slot in NanoMuseSlot.allCases {
            XCTAssertTrue(bare.has(slot), "\(slot) on Cloud needs only the capability")
            XCTAssertEqual(bare.defaultModel(for: slot), "", "the relay picks the model itself")
        }
    }

    // MARK: - Resolution order (the contract's section 3)

    func testAnExplicitChoiceWinsOverEverything() {
        let chosen = NanoMuseSlotChoice(providerId: "bailian-1", model: "wan2.6-image")
        let got = NanoMuseSlotResolver.resolve(slot: .image, chosen: chosen, chatProviderId: cloudId, providers: [cloud, bailian])
        XCTAssertEqual(got, chosen)
    }

    func testAChoiceOfCloudIsKeptEvenWithAKeyThatDraws() {
        let chosen = NanoMuseSlotChoice(providerId: cloudId, model: "")
        let got = NanoMuseSlotResolver.resolve(slot: .image, chosen: chosen, chatProviderId: "bailian-1", providers: [cloud, bailian])
        XCTAssertEqual(got?.providerId, cloudId, "Cloud chosen on purpose is never passed over for a Bailian key")
        XCTAssertEqual(got?.model, "qwen-image-3.0", "an empty model means the provider's default")
    }

    func testAChoiceWhoseProviderIsGoneFallsThrough() {
        let chosen = NanoMuseSlotChoice(providerId: "deleted", model: "x")
        let got = NanoMuseSlotResolver.resolve(slot: .image, chosen: chosen, chatProviderId: cloudId, providers: [cloud, bailian])
        XCTAssertEqual(got?.providerId, cloudId)
    }

    func testWithoutAChoiceTheChatProvidersOwnDefaultComesFirst() {
        let got = NanoMuseSlotResolver.resolve(slot: .image, chosen: nil, chatProviderId: "bailian-1", providers: [cloud, bailian])
        XCTAssertEqual(got, NanoMuseSlotChoice(providerId: "bailian-1", model: "qwen-image-3.0"))
        let clips = NanoMuseSlotResolver.resolve(slot: .video, chosen: nil, chatProviderId: "bailian-1", providers: [cloud, bailian])
        XCTAssertEqual(clips, NanoMuseSlotChoice(providerId: "bailian-1", model: "wan2.2-i2v-flash"))
    }

    func testWithoutAChoiceCloudComesBeforeAKeyThatIsNotTheChatProvider() {
        let got = NanoMuseSlotResolver.resolve(slot: .image, chosen: nil, chatProviderId: cloudId, providers: [cloud, bailian])
        XCTAssertEqual(got?.providerId, cloudId, "Cloud chats, so Cloud draws; the Bailian key waits to be chosen")
        let viaOpenRouter = NanoMuseSlotResolver.resolve(slot: .image, chosen: nil, chatProviderId: "openrouter-1", providers: [cloud, openrouter, bailian])
        XCTAssertEqual(viaOpenRouter?.providerId, cloudId, "the chat provider cannot draw on iPhone, so Cloud is next")
    }

    func testWithoutCloudTheFirstKeyThatCanTakesTheSlot() {
        let got = NanoMuseSlotResolver.resolve(slot: .image, chosen: nil, chatProviderId: "openrouter-1", providers: [openrouter, bailian])
        XCTAssertEqual(got?.providerId, "bailian-1")
        XCTAssertNil(NanoMuseSlotResolver.resolve(slot: .video, chosen: nil, chatProviderId: "openrouter-1", providers: [openrouter]))
    }

    func testClearingTheChoiceReturnsTheSlotToTheOrder() {
        let providers = [cloud, bailian]
        let chosen = NanoMuseSlotChoice(providerId: "bailian-1", model: "wan2.6-image")
        XCTAssertEqual(NanoMuseSlotResolver.resolve(slot: .image, chosen: chosen, chatProviderId: cloudId, providers: providers), chosen, "a stored choice is kept")
        // the Automatic entry: no choice stored, the order again: the chat provider cannot draw here, so Cloud
        let automatic = NanoMuseSlotResolver.automatic(slot: .image, chatProviderId: cloudId, providers: providers)
        XCTAssertEqual(automatic, NanoMuseSlotChoice(providerId: cloudId, model: "qwen-image-3.0"))
        XCTAssertEqual(automatic, NanoMuseSlotResolver.resolve(slot: .image, chosen: nil, chatProviderId: cloudId, providers: providers))
        // and when the chat runs on the Bailian key, automatic follows it
        XCTAssertEqual(NanoMuseSlotResolver.automatic(slot: .video, chatProviderId: "bailian-1", providers: providers), NanoMuseSlotChoice(providerId: "bailian-1", model: "wan2.2-i2v-flash"))
        XCTAssertNil(NanoMuseSlotResolver.automatic(slot: .video, chatProviderId: "openrouter-1", providers: [openrouter]), "nothing can: the entry says so instead of a model")
    }

    func testChatResolvesToCloudThenTheFirstKey() {
        XCTAssertEqual(NanoMuseSlotResolver.resolve(slot: .chat, chosen: nil, chatProviderId: nil, providers: [bailian, cloud])?.providerId, cloudId)
        XCTAssertEqual(NanoMuseSlotResolver.resolve(slot: .chat, chosen: nil, chatProviderId: nil, providers: [openrouter, bailian]), NanoMuseSlotChoice(providerId: "openrouter-1", model: "deepseek/deepseek-v4.1-flash"))
    }

    // MARK: - nanoMuse Cloud switched off while the chat was the account's (Android: ChatLeavesTest)

    func testChatLeavesCloudForTheFirstOwnProvidersDefault() {
        // The first own provider in the order they were added, on the catalogue's default for it.
        XCTAssertEqual(NanoMuseSlotResolver.nextChat(leaving: cloudId, providers: [cloud, bailian, openrouter]), NanoMuseSlotChoice(providerId: "bailian-1", model: "deepseek-v4.1-flash"))
        XCTAssertEqual(NanoMuseSlotResolver.nextChat(leaving: cloudId, providers: [cloud, openrouter, bailian]), NanoMuseSlotChoice(providerId: "openrouter-1", model: "deepseek/deepseek-v4.1-flash"))
        // Cloud already gone from the list (the switch was written first): the same answer.
        XCTAssertEqual(NanoMuseSlotResolver.nextChat(leaving: cloudId, providers: [bailian])?.providerId, "bailian-1")
    }

    func testChatLeavesIsRefusedWhenNothingElseChats() {
        XCTAssertNil(NanoMuseSlotResolver.nextChat(leaving: cloudId, providers: [cloud]), "only the account: the switch stays on")
        XCTAssertNil(NanoMuseSlotResolver.nextChat(leaving: cloudId, providers: []))
        // A key that only draws is no chat model.
        let drawsOnly = NanoMuseSlotProvider(id: "dashscope-img", label: "Model Studio", isCloud: false, capabilities: ["image"], defaults: [:], models: [.image: ["qwen-image-3.0"]])
        XCTAssertNil(NanoMuseSlotResolver.nextChat(leaving: cloudId, providers: [cloud, drawsOnly]))
        // A provider of one's own leaving hands the chat to the next own one, never back to itself.
        XCTAssertEqual(NanoMuseSlotResolver.nextChat(leaving: "bailian-1", providers: [bailian, openrouter])?.providerId, "openrouter-1")
        XCTAssertNil(NanoMuseSlotResolver.nextChat(leaving: "bailian-1", providers: [bailian]))
    }

    // MARK: - The relay's menu

    private let menu: [[String: Any]] = [
        ["id": "deepseek-v4.1-flash", "nanomuse": ["for": ["chat"], "kind": "chat", "recommended": true, "recommended_for": ["chat"]]],
        ["id": "qwen3.8-27b", "nanomuse": ["for": ["chat", "gui"], "kind": "chat", "recommended_for": ["gui"]]],
        ["id": "qwen-image-3.0", "nanomuse": ["kind": "image", "recommended": true]],
        ["id": "wan-image", "nanomuse": ["kind": "image"]],
        ["id": "wan2.2-i2v-flash", "nanomuse": ["kind": "video", "recommended": true]],
        ["id": "wan2.2-t2v-plus", "nanomuse": ["kind": "video"]],
    ]

    func testMenuSortsEachSlotWithTheRecommendedFirst() {
        XCTAssertEqual(NanoMuseRelayMenu.models(for: .chat, in: menu), ["deepseek-v4.1-flash", "qwen3.8-27b"])
        XCTAssertEqual(NanoMuseRelayMenu.models(for: .hands, in: menu), ["qwen3.8-27b"])
        XCTAssertEqual(NanoMuseRelayMenu.models(for: .image, in: menu), ["qwen-image-3.0", "wan-image"])
        XCTAssertEqual(NanoMuseRelayMenu.models(for: .video, in: menu), ["wan2.2-i2v-flash", "wan2.2-t2v-plus"])
        XCTAssertEqual(NanoMuseRelayMenu.recommended(for: .chat, in: menu), "deepseek-v4.1-flash")
        XCTAssertEqual(NanoMuseRelayMenu.recommended(for: .hands, in: menu), "qwen3.8-27b")
        XCTAssertEqual(NanoMuseRelayMenu.recommended(for: .image, in: menu), "qwen-image-3.0")
        XCTAssertEqual(NanoMuseRelayMenu.recommended(for: .video, in: menu), "wan2.2-i2v-flash")
    }

    func testMenuFromAnOlderRelayFallsBackToModalities() {
        let old: [[String: Any]] = [
            ["id": "deepseek-v4.1-flash", "nanomuse": ["for": ["chat"]]],
            ["id": "qwen-image-3.0", "architecture": ["input_modalities": ["text"], "output_modalities": ["image"]]],
            ["id": "wan2.2-i2v-flash", "architecture": ["input_modalities": ["text", "image"], "output_modalities": ["video"]]],
        ]
        XCTAssertEqual(NanoMuseRelayMenu.models(for: .chat, in: old), ["deepseek-v4.1-flash"])
        XCTAssertEqual(NanoMuseRelayMenu.models(for: .image, in: old), ["qwen-image-3.0"])
        XCTAssertEqual(NanoMuseRelayMenu.models(for: .video, in: old), ["wan2.2-i2v-flash"])
    }

    func testMenuRoundTripsThroughDefaults() {
        let key = "nanomuse.cloud.menu"
        let before = UserDefaults.standard.data(forKey: key)
        defer {
            if let before { UserDefaults.standard.set(before, forKey: key) } else { UserDefaults.standard.removeObject(forKey: key) }
        }
        NanoMuseRelayMenu.store(menu)
        XCTAssertEqual(NanoMuseRelayMenu.cached.compactMap { $0["id"] as? String }, menu.compactMap { $0["id"] as? String })
        NanoMuseRelayMenu.forget()
        XCTAssertTrue(NanoMuseRelayMenu.cached.isEmpty)
    }

    // MARK: - The picker's groups: order, fold, search

    /// Twenty chat models as a key with many of them lists them, `m01` … `m20`.
    private let many: [String] = (1...20).map { $0 < 10 ? "m0\($0)" : "m\($0)" }

    func testGroupPutsTheDefaultThenTheChoiceFirstAndKeepsTheRestInOrder() {
        let got = NanoMusePickerList.ordered(many, preferred: "m07", chosen: "m15")
        XCTAssertEqual(Array(got.prefix(3)), ["m07", "m15", "m01"])
        XCTAssertEqual(got.count, many.count, "nothing is added, nothing is lost")
        XCTAssertEqual(Set(got), Set(many))
        XCTAssertEqual(got.filter { $0 != "m07" && $0 != "m15" }, many.filter { $0 != "m07" && $0 != "m15" }, "the rest keep the list's order")
    }

    func testGroupDoesNotRepeatAChoiceThatIsTheDefaultNorInventOneThatIsMissing() {
        XCTAssertEqual(Array(NanoMusePickerList.ordered(many, preferred: "m03", chosen: "m03").prefix(2)), ["m03", "m01"])
        XCTAssertEqual(NanoMusePickerList.ordered(many, preferred: "not-here", chosen: "neither"), many, "a default the key does not list changes nothing")
        XCTAssertEqual(NanoMusePickerList.ordered(many, preferred: nil, chosen: nil), many)
        XCTAssertEqual(NanoMusePickerList.ordered([], preferred: "m01", chosen: "m02"), [])
    }

    func testCloudGroupKeepsTheRecommendedFirst() {
        // the relay's list already leads with the recommended one, and the provider's default names it
        let got = NanoMusePickerList.ordered(cloud.models(for: .chat), preferred: cloud.defaultModel(for: .chat), chosen: "qwen3.8-27b")
        XCTAssertEqual(got, ["deepseek-v4.1-flash", "qwen3.8-27b"])
        let prefixed = NanoMusePickerList.ordered(openrouter.models(for: .chat), preferred: openrouter.defaultModel(for: .chat), chosen: nil)
        XCTAssertEqual(prefixed.first, "deepseek/deepseek-v4.1-flash", "the catalogue's bare default finds its prefixed id")
    }

    func testGroupFoldsToEightRowsUntilExpanded() {
        XCTAssertEqual(NanoMusePickerList.fold, 8)
        let folded = NanoMusePickerList.collapsed(many, expanded: false)
        XCTAssertEqual(folded.shown, Array(many.prefix(8)))
        XCTAssertEqual(folded.hidden, 12, "the Show n more row counts what is behind it")
        let open = NanoMusePickerList.collapsed(many, expanded: true)
        XCTAssertEqual(open.shown, many)
        XCTAssertEqual(open.hidden, 0)
    }

    func testAGroupOfEightOrFewerHasNoMoreRow() {
        let eight = Array(many.prefix(8))
        let got = NanoMusePickerList.collapsed(eight, expanded: false)
        XCTAssertEqual(got.shown, eight)
        XCTAssertEqual(got.hidden, 0)
        let nine = Array(many.prefix(9))
        XCTAssertEqual(NanoMusePickerList.collapsed(nine, expanded: false).hidden, 1)
    }

    func testSearchAppearsOnlyAboveEightRowsAcrossAllGroups() {
        XCTAssertFalse(NanoMusePickerList.offersSearch(total: 0))
        XCTAssertFalse(NanoMusePickerList.offersSearch(total: 8))
        XCTAssertTrue(NanoMusePickerList.offersSearch(total: 9))
    }

    func testSearchMatchesIdAndDisplayNameWithoutCaseAndWithoutACap() {
        let names = ["m02": "Claude Sonnet", "m19": "GPT Mini"]
        XCTAssertEqual(NanoMusePickerList.normalized("  SoNNet \n"), "sonnet")
        XCTAssertEqual(NanoMusePickerList.filtered(many, names: names, query: "sonnet"), ["m02"], "the display name counts")
        XCTAssertEqual(NanoMusePickerList.filtered(many, names: names, query: "M1"), [], "the query is normalized by the caller; a raw upper-case one matches nothing here")
        XCTAssertEqual(NanoMusePickerList.filtered(many, names: names, query: "m1"), (10...19).map { "m\($0)" }, "every match shows, more than a fold of them")
        XCTAssertEqual(NanoMusePickerList.filtered(many, names: names, query: "nothing"), [])
        XCTAssertEqual(NanoMusePickerList.filtered(many, names: names, query: ""), many, "no query keeps everything")
        XCTAssertTrue(NanoMusePickerList.matches("deepseek/deepseek-v4.1-flash", name: nil, query: "v4.1"))
        XCTAssertFalse(NanoMusePickerList.matches("qwen-plus", name: "Qwen Plus", query: "max"))
    }

    // MARK: - The slots' words

    func testEverySlotNamesItsCapability() {
        XCTAssertEqual(NanoMuseSlot.chat.capability, "chat")
        XCTAssertEqual(NanoMuseSlot.hands.capability, "vision")
        XCTAssertEqual(NanoMuseSlot.image.capability, "image")
        XCTAssertEqual(NanoMuseSlot.video.capability, "video")
        XCTAssertEqual(NanoMuseSlot.allCases.map(\.defaultsKey), ["chat", "hands", "image", "video"])
    }
}
