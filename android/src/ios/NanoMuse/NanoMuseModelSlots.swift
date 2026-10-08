//
//  NanoMuseModelSlots.swift
//  nanoMuse
//
//  0.1.41 "Choice": the four things a model does for the person — chat, operating the screen,
//  making pictures, making clips — as four slots, each holding one `<provider> · <model>`.
//  Settings › Models shows them (NanoMuseModelsView); the "Use it for" card after a key is
//  saved fills them; and when the person has not chosen, the order of `resolve` decides
//  (the contract's section 3): an explicit choice, then the chat provider's own default for
//  the same capability, then nanoMuse Cloud, then the first provider on the phone that can.
//  Cloud never jumps ahead of a provider the person chose.
//
//  The relay's menu (`/v1/models` with `nanomuse.for` / `nanomuse.kind`) is kept on the phone
//  so the Cloud group of each picker can be listed without a round trip; the pure parts are
//  tested in MinisTests/NanoMuseModelSlotsTests.swift. Android: ui/models/ModelsScreen.kt,
//  hands/Hands.kt (screenModel), media/MediaModels.kt. Desktop: cloud.ts (handsChoice,
//  imageEndpoint, videoEndpoint).
//

import Foundation

// MARK: - The slots

/// One of the four things a model does for the person.
enum NanoMuseSlot: String, CaseIterable, Identifiable, Sendable {
    case chat, hands, image, video
    var id: String { rawValue }

    /// The catalogue capability a provider needs for the slot (`providers.json` → `capabilities`).
    var capability: String {
        switch self {
        case .chat: return "chat"
        case .hands: return "vision"
        case .image: return "image"
        case .video: return "video"
        }
    }

    /// The key of the provider's default for the slot (`providers.json` → `defaults`).
    var defaultsKey: String { rawValue }

    var title: String {
        switch self {
        // its own key: the slot is 对话 in Chinese, while the chat tab's "Chat" key stays 闲聊
        case .chat: return AppLocalized("models.slot.chat")
        case .hands: return AppLocalized("Operating the screen")
        case .image: return AppLocalized("Making pictures")
        case .video: return AppLocalized("Making clips")
        }
    }

    var subtitle: String {
        switch self {
        case .chat: return AppLocalized("The model that talks with you.")
        // iPhones cannot operate their own screen: the row is there, disabled, and says where the setting lives.
        case .hands: return AppLocalized("Your computer uses its own setting.")
        case .image: return AppLocalized("Portraits of your Muse and the pictures you ask for.")
        case .video: return AppLocalized("Short clips of your Muse.")
        }
    }

    var symbol: String {
        switch self {
        case .chat: return "bubble.left"
        case .hands: return "hand.tap"
        case .image: return "photo"
        case .video: return "film"
        }
    }
}

// MARK: - Resolution (pure, tested)

/// What a picker and the resolver know about one provider: nanoMuse Cloud or a provider of
/// the person's own, with the models the app can actually use for each slot.
struct NanoMuseSlotProvider: Equatable, Sendable {
    /// The provider instance's id (the relay's instance for Cloud).
    var id: String
    var label: String
    var isCloud: Bool
    /// `chat`, `vision`, `image`, `video`: what the provider covers and the app can drive.
    var capabilities: Set<String>
    /// The provider's default model per slot (`defaults.chat` …; for Cloud the relay's recommended ones).
    var defaults: [String: String]
    /// The models the app can list for each slot, the recommended one first.
    var models: [NanoMuseSlot: [String]]
    /// A model's display name where the provider gave one that differs from the id; the
    /// picker's search matches on both.
    var names: [String: String] = [:]

    func models(for slot: NanoMuseSlot) -> [String] { models[slot] ?? [] }

    /// True when the provider can serve the slot: it has the capability and at least one model
    /// for it. nanoMuse Cloud needs only the capability: the relay picks the model itself when
    /// the phone has no copy of its menu yet.
    func has(_ slot: NanoMuseSlot) -> Bool {
        capabilities.contains(slot.capability) && (isCloud || !models(for: slot).isEmpty)
    }

    /// The model the provider would use for the slot: its default when that is in the list
    /// (a bare id or one with a vendor prefix, `deepseek/deepseek-v4.1-flash`), else the first
    /// with the capability; nil when it has none. For Cloud without a menu on the phone, the
    /// empty string: the relay's own first choice.
    func defaultModel(for slot: NanoMuseSlot) -> String? {
        let list = models(for: slot)
        if let wanted = defaults[slot.defaultsKey], !wanted.isEmpty {
            if list.contains(wanted) { return wanted }
            if let prefixed = list.first(where: { $0.hasSuffix("/" + wanted) }) { return prefixed }
        }
        if let first = list.first { return first }
        return isCloud && capabilities.contains(slot.capability) ? "" : nil
    }
}

/// A provider and a model for one slot.
struct NanoMuseSlotChoice: Equatable, Sendable {
    var providerId: String
    var model: String
}

enum NanoMuseSlotResolver {
    /// The slot's value (the contract's section 3). `chosen` is what the person picked, kept
    /// when its provider is still there and still covers the slot (a typed model name is kept
    /// as typed; an empty one becomes the provider's default). Without a choice: for chat,
    /// Cloud when signed in, else the first provider that chats; for the other slots the chat
    /// provider's own default when it is a provider of the person's own with the capability,
    /// then Cloud, then the first provider that can. Nil when nothing on the phone can.
    static func resolve(slot: NanoMuseSlot, chosen: NanoMuseSlotChoice?, chatProviderId: String?, providers: [NanoMuseSlotProvider]) -> NanoMuseSlotChoice? {
        if let chosen, let p = providers.first(where: { $0.id == chosen.providerId }), p.has(slot) {
            if !chosen.model.isEmpty { return chosen }
            if let model = p.defaultModel(for: slot) { return NanoMuseSlotChoice(providerId: p.id, model: model) }
        }
        let cloud = providers.first { $0.isCloud && $0.has(slot) }
        let own = providers.filter { !$0.isCloud && $0.has(slot) }
        func choice(_ p: NanoMuseSlotProvider?) -> NanoMuseSlotChoice? {
            guard let p, let model = p.defaultModel(for: slot) else { return nil }
            return NanoMuseSlotChoice(providerId: p.id, model: model)
        }
        if slot != .chat, let chatId = chatProviderId, let chatProvider = own.first(where: { $0.id == chatId }) {
            return choice(chatProvider)
        }
        return choice(cloud) ?? choice(own.first)
    }

    /// What the slot follows when no choice is stored: the same order, without a choice.
    static func automatic(slot: NanoMuseSlot, chatProviderId: String?, providers: [NanoMuseSlotProvider]) -> NanoMuseSlotChoice? {
        resolve(slot: slot, chosen: nil, chatProviderId: chatProviderId, providers: providers)
    }

    /// Where the chat slot goes when the provider `leaving` is switched off while new chats
    /// answered through it: the first other provider in `providers` (the order they were added)
    /// that chats, on its default chat model (the catalogue's default for that provider, else
    /// its first chat model). Nil when nothing else could answer; the switch is then refused.
    /// Android: `ModelSlots.nextChat`.
    static func nextChat(leaving: String, providers: [NanoMuseSlotProvider]) -> NanoMuseSlotChoice? {
        for p in providers where p.id != leaving && p.has(.chat) {
            if let model = p.defaultModel(for: .chat) { return NanoMuseSlotChoice(providerId: p.id, model: model) }
        }
        return nil
    }
}

// MARK: - The picker's groups (pure, tested)

/// How a picker lays out one provider's models so a key with hundreds of them does not
/// become an endless list (the same contract on Android, the desktop and the web): a group
/// shows at most `fold` rows until its *Show n more* row is tapped, the provider's default
/// for the slot first, then the chosen model, then the rest as the list came; a search field
/// appears once the groups together hold more than `fold` rows and filters every group by a
/// case-insensitive substring of the model id or its display name, with no cap while a query
/// is present.
enum NanoMusePickerList {
    /// The most rows a group shows before it is expanded.
    static let fold = 8

    /// A group's rows in the picker's order: `preferred` (the provider's default for the
    /// slot; the relay's recommended one for Cloud) first when it is in the list, then
    /// `chosen` when it is in the list and not already placed, then the rest in the order
    /// they came. Nothing is added that was not in `models`.
    static func ordered(_ models: [String], preferred: String?, chosen: String?) -> [String] {
        var out: [String] = []
        for top in [preferred, chosen] {
            if let top, models.contains(top), !out.contains(top) { out.append(top) }
        }
        return out + models.filter { !out.contains($0) }
    }

    /// The rows a collapsed group shows: the first `fold` of `ordered`, or all of them when
    /// `expanded`. `hidden` is how many the *Show n more* row stands for; 0 means no such row.
    static func collapsed(_ ordered: [String], expanded: Bool) -> (shown: [String], hidden: Int) {
        if expanded || ordered.count <= fold { return (ordered, 0) }
        return (Array(ordered.prefix(fold)), ordered.count - fold)
    }

    /// The query as the filter reads it: trimmed and lowercased; empty means no query.
    static func normalized(_ query: String) -> String {
        query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }

    /// Whether a model stays in view for `query` (already normalized): the id or the display
    /// name contains it, case-insensitively. An empty query keeps everything.
    static func matches(_ model: String, name: String?, query: String) -> Bool {
        if query.isEmpty { return true }
        if model.lowercased().contains(query) { return true }
        if let name, name.lowercased().contains(query) { return true }
        return false
    }

    /// The matches of a group for `query` (normalized), all of them, in `ordered`'s order.
    static func filtered(_ ordered: [String], names: [String: String], query: String) -> [String] {
        ordered.filter { matches($0, name: names[$0], query: query) }
    }

    /// Whether the picker shows its search field: the groups together hold more than `fold` rows.
    static func offersSearch(total: Int) -> Bool { total > fold }
}

// MARK: - The relay's menu, kept on the phone (pure parts tested)

/// The relay's `/v1/models` as the pickers read it: which lane a model is for (`nanomuse.for`:
/// `chat`, `gui`), which kind it is (`nanomuse.kind`: `chat`, `image`, `video`), which one the
/// relay recommends. Stored at sign-in and refreshed when the Models page opens, so the Cloud
/// group lists without a round trip; empty on a phone that signed in before this build until
/// the next refresh (the Cloud instance's own model list stands in meanwhile).
enum NanoMuseRelayMenu {
    private static let key = "nanomuse.cloud.menu"

    static func store(_ models: [[String: Any]]) {
        guard !models.isEmpty, JSONSerialization.isValidJSONObject(models),
              let data = try? JSONSerialization.data(withJSONObject: models) else { return }
        UserDefaults.standard.set(data, forKey: key)
    }

    static var cached: [[String: Any]] {
        guard let data = UserDefaults.standard.data(forKey: key),
              let list = (try? JSONSerialization.jsonObject(with: data)) as? [[String: Any]] else { return [] }
        return list
    }

    static func forget() { UserDefaults.standard.removeObject(forKey: key) }

    /// Ask the relay for its menu and keep it. Nil when the phone is not signed in or the relay did not answer.
    @MainActor
    @discardableResult
    static func refresh() async -> [[String: Any]]? {
        guard let token = NanoMuseCloud.apiKey else { return nil }
        guard let reply = try? await NanoMuseCloud.call("GET", "/v1/models", body: nil, token: token),
              let models = reply["data"] as? [[String: Any]] else { return nil }
        store(models)
        return models
    }

    /// `nanomuse.kind`: `chat`, `image`, `video`; nil from a relay before 0.17.
    static func kind(_ model: [String: Any]) -> String? {
        (model["nanomuse"] as? [String: Any])?["kind"] as? String
    }

    private static func outputs(_ model: [String: Any]) -> [String] {
        ((model["architecture"] as? [String: Any])?["output_modalities"] as? [String]) ?? []
    }

    /// Whether a menu entry belongs in the slot's picker.
    static func serves(_ slot: NanoMuseSlot, _ model: [String: Any]) -> Bool {
        let kind = kind(model)
        switch slot {
        case .chat:
            return (kind == nil || kind == "chat") && !NanoMuseModelMenu.drawsOnly(model) && !outputs(model).contains("video") && NanoMuseModelMenu.forChat(model)
        case .hands:
            return (kind == nil || kind == "chat") && NanoMuseModelMenu.lanes(model)?.contains("gui") == true
        case .image:
            return kind == "image" || (kind == nil && NanoMuseModelMenu.drawsOnly(model))
        case .video:
            return kind == "video" || (kind == nil && outputs(model).contains("video"))
        }
    }

    /// The relay's recommended model for the slot: `recommended_for` the lane for chat and the
    /// screen, the entry marked `recommended` (else the first) for pictures and clips.
    static func recommended(for slot: NanoMuseSlot, in menu: [[String: Any]]) -> String? {
        switch slot {
        case .chat: return NanoMuseModelMenu.recommendedChat(menu)?["id"] as? String
        case .hands: return NanoMuseModelMenu.guiModel(menu)
        case .image, .video:
            let list = menu.filter { serves(slot, $0) }
            return (list.first { NanoMuseModelMenu.isRecommended($0) } ?? list.first)?["id"] as? String
        }
    }

    /// The slot's models in the menu, the recommended one first, in the relay's order otherwise.
    static func models(for slot: NanoMuseSlot, in menu: [[String: Any]]) -> [String] {
        var ids = menu.filter { serves(slot, $0) }.compactMap { $0["id"] as? String }.filter { !$0.isEmpty }
        if let top = recommended(for: slot, in: menu), let i = ids.firstIndex(of: top), i > 0 {
            ids.remove(at: i)
            ids.insert(top, at: 0)
        }
        return ids
    }
}

// MARK: - The phone's providers as slot providers

@MainActor
enum NanoMuseModelSlots {
    /// Posted after a slot changed here, so the rows and the face re-read what is set.
    static let changed = Notification.Name("nanoMuse.modelSlotsChanged")

    /// Whether a model of a provider of one's own can hold a conversation: it writes text and
    /// is not one of the picture or video models the same key lists.
    static func chats(_ entry: ModelEntry) -> Bool {
        let modalities = entry.model.modalityOverride ?? entry.model.capabilities.supportedModalities
        if !modalities.contains(.textOutput) && (modalities.contains(.imageOutput) || modalities.contains(.videoOutput)) { return false }
        if NanoMuseImageGen.drawsNatively(entry.model.id) || NanoMuseVideoGen.looksLikeVideoModel(entry.model.id) { return false }
        let id = entry.model.id.lowercased()
        return !["embed", "whisper", "tts", "rerank", "moderation"].contains { id.contains($0) }
    }

    /// Whether a chat model also sees pictures (the provider said so, or its name says so).
    static func sees(_ entry: ModelEntry) -> Bool {
        let modalities = entry.model.modalityOverride ?? entry.model.capabilities.supportedModalities
        return modalities.contains(.imageInput) || NanoMuseVision.looksLikeItSees(id: entry.model.id, displayName: entry.model.displayName)
    }

    /// nanoMuse Cloud as a slot provider, from the kept menu (or, until one is kept, from the
    /// relay instance's own model list); nil when the phone is not signed in or *Use nanoMuse
    /// Cloud models* is off.
    static func cloudProvider() -> NanoMuseSlotProvider? {
        guard NanoMuseCloud.modelsOn, let inst = NanoMuseCloud.instance else { return nil }
        let menu = NanoMuseRelayMenu.cached
        var models: [NanoMuseSlot: [String]] = [:]
        var defaults: [String: String] = [:]
        var names: [String: String] = [:]
        if !menu.isEmpty {
            for slot in NanoMuseSlot.allCases {
                models[slot] = NanoMuseRelayMenu.models(for: slot, in: menu)
                if let top = NanoMuseRelayMenu.recommended(for: slot, in: menu) { defaults[slot.defaultsKey] = top }
            }
            for m in menu {
                if let id = m["id"] as? String, let name = m["name"] as? String, !name.isEmpty, name != id { names[id] = name }
            }
        } else {
            let entries = ProviderConfigStore.shared.visibleEntries(for: inst.id)
            let chat = entries.filter(chats)
            models[.chat] = chat.map(\.model.id)
            models[.hands] = chat.filter(sees).map(\.model.id)
            models[.image] = entries.filter { NanoMuseImageGen.drawsNatively($0.model.id) || ($0.model.modalityOverride ?? $0.model.capabilities.supportedModalities) == [.textInput, .imageOutput] }.map(\.model.id)
            models[.video] = entries.filter { NanoMuseVideoGen.looksLikeVideoModel($0.model.id) }.map(\.model.id)
            names = displayNames(entries)
        }
        // the relay chats, sees, draws and makes clips for every account; the menu only names the models
        let capabilities = Set(NanoMuseSlot.allCases.map(\.capability))
        return NanoMuseSlotProvider(id: inst.id, label: NanoMuseCloud.label, isCloud: true, capabilities: capabilities, defaults: defaults, models: models, names: names)
    }

    /// The display names the entries carry where they differ from the id, for the picker's search.
    private static func displayNames(_ entries: [ModelEntry]) -> [String: String] {
        entries.reduce(into: [String: String]()) { out, e in
            let name = e.model.displayName
            if !name.isEmpty, name != e.model.id { out[e.model.id] = name }
        }
    }

    /// A provider of the person's own as a slot provider: its catalogue entry's capabilities
    /// and defaults where the catalogue knows it, and only the models the app can drive —
    /// pictures and clips go through Model Studio's native endpoints, so only a DashScope host
    /// is listed for those. Nil for a disabled instance or one without a credential.
    static func ownProvider(_ inst: ProviderInstance) -> NanoMuseSlotProvider? {
        guard inst.isEnabled, inst.hasAnyCredential, inst.id != NanoMuseCloud.instance?.id else { return nil }
        let store = ProviderConfigStore.shared
        let vendor = NanoMuseCatalogue.vendor(for: inst)
        let entries = store.visibleEntries(for: inst.id)
        let chat = entries.filter(chats)
        var models: [NanoMuseSlot: [String]] = [:]
        models[.chat] = chat.map(\.model.id)
        models[.hands] = chat.filter(sees).map(\.model.id)
        if NanoMuseImageGen.speaksDashScope(inst.customBaseURL ?? "") {
            models[.image] = NanoMuseImageGen.availableModels(for: inst)
            models[.video] = NanoMuseMediaModels.availableVideoModels(for: inst) ?? NanoMuseMediaModels.candidateVideoModels(for: inst)
        }
        var capabilities = Set(NanoMuseSlot.allCases.filter { !(models[$0] ?? []).isEmpty }.map(\.capability))
        // the catalogue's word on what the key covers, where it has one (a `custom` vendor leaves it to the models)
        if let vendor, !vendor.userCapabilities, vendor.id != NanoMuseCatalogue.custom {
            let known = inst.credentialType == .oauth ? vendor.capabilitiesFor(vendor.signIn) : vendor.capabilities
            capabilities = capabilities.intersection(known)
        }
        return NanoMuseSlotProvider(id: inst.id, label: inst.label, isCloud: false, capabilities: capabilities, defaults: vendor?.defaults ?? [:], models: models, names: displayNames(entries))
    }

    /// Every provider the pickers list: nanoMuse Cloud first when signed in, then the person's own in the order they were added.
    static func providers() -> [NanoMuseSlotProvider] {
        var out: [NanoMuseSlotProvider] = []
        if let cloud = cloudProvider() { out.append(cloud) }
        for inst in ProviderConfigStore.shared.instances.sorted(by: { $0.createdAt < $1.createdAt }) {
            if let p = ownProvider(inst) { out.append(p) }
        }
        return out
    }

    /// The person's own providers that could serve `slot` by the catalogue's word (or that
    /// leave it open, as a `custom` endpoint does) but that this app cannot drive for it:
    /// pictures and clips go through Model Studio's native endpoints only, so an OpenRouter
    /// or OpenAI key that draws on the desktop is not listed here. Their labels, in the order
    /// the providers were added, for the sentence under the picker that says so; empty for
    /// chat and hands, which every endpoint serves.
    static func notDriven(for slot: NanoMuseSlot) -> [String] {
        guard slot == .image || slot == .video else { return [] }
        let cloudId = NanoMuseCloud.instance?.id
        return ProviderConfigStore.shared.instances.sorted(by: { $0.createdAt < $1.createdAt }).compactMap { inst in
            guard inst.isEnabled, inst.hasAnyCredential, inst.id != cloudId,
                  !NanoMuseImageGen.speaksDashScope(inst.customBaseURL ?? ""),
                  let vendor = NanoMuseCatalogue.vendor(for: inst) else { return nil }
            let open = vendor.userCapabilities || vendor.id == NanoMuseCatalogue.custom
            return open || vendor.capabilities.contains(slot.capability) ? inst.label : nil
        }
    }

    // MARK: Chat

    /// The entry new chats start on: the default group's first member that can answer.
    static func chatEntry() -> ModelEntry? {
        let store = ProviderConfigStore.shared
        guard let gid = store.defaultPrimaryGroupId, let group = store.group(for: gid) else { return nil }
        let usable = group.memberEntryIds.lazy.compactMap { id -> ModelEntry? in
            guard let e = store.entry(for: id), !e.isHidden, let inst = store.instance(for: e.providerInstanceId), inst.isEnabled, inst.hasAnyCredential else { return nil }
            return e
        }.first
        return usable ?? group.memberEntryIds.lazy.compactMap { store.entry(for: $0) }.first
    }

    /// The instance new chats start on, if any.
    static func chatProviderId() -> String? { chatEntry()?.providerInstanceId }

    /// Whether the chat slot could leave `instanceId` (nanoMuse Cloud, when its switch goes
    /// off): new chats do not run on it, or a provider of one's own could take them
    /// (`NanoMuseSlotResolver.nextChat`). False is the refusal the switch shows as one sentence.
    static func canLeave(_ instanceId: String) -> Bool {
        chatProviderId() != instanceId || NanoMuseSlotResolver.nextChat(leaving: instanceId, providers: providers()) != nil
    }

    /// `instanceId` was switched off: when new chats answered through it, the chat slot and the
    /// main chat move to the next provider that chats (`useForChat`), so the Models page names
    /// what answers and no chat stops at the switch. Nothing moves when the slot was elsewhere
    /// or nothing is left; call after the instance was written off. Returns what it moved to.
    @discardableResult
    static func chatLeaves(_ instanceId: String) -> NanoMuseSlotChoice? {
        guard chatProviderId() == instanceId,
              let next = NanoMuseSlotResolver.nextChat(leaving: instanceId, providers: providers()),
              useForChat(instanceId: next.providerId, model: next.model) else { return nil }
        return next
    }

    /// The chat slot as a choice, or nil when no group can answer.
    static func chatChoice() -> NanoMuseSlotChoice? {
        guard let e = chatEntry() else { return nil }
        return NanoMuseSlotChoice(providerId: e.providerInstanceId, model: e.model.id)
    }

    /// Make `entry` the model new chats start on: a group of ours for its provider — every
    /// member on that instance; the one holding the entry first, else the one named after the
    /// instance, else a new one — with the entry moved to the front, and that group the
    /// default. A group the person made with members from several providers is never touched.
    /// The current chat keeps its own binding; the note under the row says so.
    static func useForChat(_ entry: ModelEntry) {
        let store = ProviderConfigStore.shared
        guard let inst = store.instance(for: entry.providerInstanceId) else { return }
        let ours = store.modelGroups.filter { g in
            !g.memberEntryIds.isEmpty && g.memberEntryIds.allSatisfy { store.entry(for: $0)?.providerInstanceId == inst.id }
        }
        let groupId: String
        if var g = ours.first(where: { $0.memberEntryIds.contains(entry.id) }) ?? ours.first(where: { $0.name == inst.label }) {
            if g.memberEntryIds.first != entry.id {
                g.memberEntryIds = [entry.id] + g.memberEntryIds.filter { $0 != entry.id }
                store.updateGroup(g)
            }
            groupId = g.id
        } else {
            let g = ModelGroup(name: inst.label, memberEntryIds: [entry.id])
            store.addGroup(g)
            groupId = g.id
        }
        if store.defaultPrimaryGroupId != groupId { store.defaultPrimaryGroupId = groupId }
        mainChatFollows(groupId: groupId, entry: entry)
        NotificationCenter.default.post(name: changed, object: nil)
    }

    /// The main chat follows the chat slot. Every chat keeps the binding it was made with,
    /// and the chat slot is the default for new ones; but the main chat is the one
    /// conversation the Chat tab always shows and is never new, so on 0.1.41 the Models page
    /// could not move it off the provider it started on: a tester who saved a key of their own
    /// saw their side chats answer through it while the main chat kept reading nanoMuse Cloud
    /// under the face. Now the main chat's binding moves with the slot (the same write as a
    /// pick in the chat's own picker, SessionModelPicker); side chats are left as they are.
    /// Nothing is written when the binding already says so, which also keeps the
    /// `sessionModelBindingChanged` → `followPick` → `useForChat` round from going on.
    /// The group's default thinking level comes along, as it does when a group is picked in
    /// the chat's own picker and when a new chat is made (`applyGroupSessionDefaults`): a
    /// group the person set to think hard was followed with the main chat still on `off`.
    static func mainChatFollows(groupId: String, entry: ModelEntry) {
        guard let sid = UserDefaults.standard.string(forKey: NanoMuseMainChat.key), !sid.hasPrefix(NanoMuseMainChat.draftPrefix) else { return }
        let store = ProviderConfigStore.shared
        let source = SessionModelSource.group(groupId: groupId, resolvedEntryId: entry.id)
        let existing = store.binding(for: sid)
        if existing?.primarySource == source { return }
        store.setBinding(SessionModelBinding(sessionId: sid, primarySource: source, subModelSource: existing?.subModelSource), for: sid)
        if let level = store.group(for: groupId)?.defaultThinkingLevel {
            var cfg = store.inferenceConfig(for: sid) ?? SessionInferenceConfig()
            cfg.thinkingLevel = level
            store.setInferenceConfig(cfg, for: sid)
        }
        NotificationCenter.default.post(name: .sessionModelBindingChanged, object: nil, userInfo: ["groupId": groupId, "sessionId": sid])
        let model = entry.model.id
        Task { await ChatStore.shared.updateSessionModelId(sid, modelId: model) }
    }

    /// The same, by provider instance and model id.
    @discardableResult
    static func useForChat(instanceId: String, model: String) -> Bool {
        guard let entry = ProviderConfigStore.shared.entries(for: instanceId).first(where: { $0.model.id == model }) else { return false }
        useForChat(entry)
        return true
    }

    /// The Cloud model a chat falls back to for one turn (NanoMuseCloudOnce): the relay's
    /// recommended chat model as an entry, else the Cloud group's first member, else the first
    /// Cloud model that chats. Asks for the sign-in alone, not the switch: the button that leads
    /// here is the consent, so it works while *Use nanoMuse Cloud models* is off.
    static func cloudChatEntry() -> ModelEntry? {
        guard NanoMuseCloud.isSignedIn, let inst = NanoMuseCloud.instance else { return nil }
        let store = ProviderConfigStore.shared
        let entries = store.visibleEntries(for: inst.id)
        if let top = NanoMuseRelayMenu.recommended(for: .chat, in: NanoMuseRelayMenu.cached), let e = entries.first(where: { $0.model.id == top }) { return e }
        if let group = store.modelGroups.first(where: { $0.name == NanoMuseCloud.label }),
           let e = group.memberEntryIds.lazy.compactMap({ store.entry(for: $0) }).first(where: { $0.providerInstanceId == inst.id }) { return e }
        return entries.first(where: chats)
    }

    // MARK: Image and video

    /// The image slot as the person set it (nil when nothing was chosen): nanoMuse Cloud when
    /// they picked it, else the key they picked while it is still on the phone.
    static func imageChoice() -> NanoMuseSlotChoice? {
        if NanoMuseImageGen.preferRelay, let cloud = NanoMuseCloud.instance, NanoMuseCloud.modelsOn {
            return NanoMuseSlotChoice(providerId: cloud.id, model: NanoMuseImageGen.relayModel ?? "")
        }
        guard let saved = UserDefaults.standard.string(forKey: NanoMuseImageGen.defaultsInstanceKey), !saved.isEmpty else { return nil }
        let model = UserDefaults.standard.string(forKey: NanoMuseImageGen.defaultsModelKey)?.trimmingCharacters(in: .whitespaces) ?? ""
        return NanoMuseSlotChoice(providerId: saved, model: model)
    }

    /// The image slot's value, chosen or resolved.
    static func imageValue(providers: [NanoMuseSlotProvider]? = nil) -> NanoMuseSlotChoice? {
        NanoMuseSlotResolver.resolve(slot: .image, chosen: imageChoice(), chatProviderId: chatProviderId(), providers: providers ?? self.providers())
    }

    /// The video slot's value, chosen or resolved; nil when switched off or nothing can.
    static func videoValue(providers: [NanoMuseSlotProvider]? = nil) -> NanoMuseSlotChoice? {
        switch NanoMuseMediaModels.videoChoice() {
        case .off: return nil
        case .chosen(let c): return NanoMuseSlotResolver.resolve(slot: .video, chosen: c, chatProviderId: chatProviderId(), providers: providers ?? self.providers())
        case .unset: return NanoMuseSlotResolver.resolve(slot: .video, chosen: nil, chatProviderId: chatProviderId(), providers: providers ?? self.providers())
        }
    }

    /// True when the person stored a choice for the slot (pictures or clips, on or off);
    /// false when the slot follows the automatic order. Chat is the anchor and always counts
    /// as chosen; the screen is not on iPhone.
    static func hasChoice(_ slot: NanoMuseSlot) -> Bool {
        switch slot {
        case .chat: return true
        case .hands: return false
        case .image: return imageChoice() != nil
        case .video: return NanoMuseMediaModels.videoChoice() != .unset
        }
    }

    /// What the slot would follow with no choice stored, as `<provider> · <model>`; nil when nothing can.
    static func automaticLine(_ slot: NanoMuseSlot, providers: [NanoMuseSlotProvider]? = nil) -> String? {
        let list = providers ?? self.providers()
        guard let choice = NanoMuseSlotResolver.automatic(slot: slot, chatProviderId: chatProviderId(), providers: list) else { return nil }
        return line(for: choice, in: list)
    }

    /// Forget the stored choice for pictures or clips, so the slot follows the automatic
    /// order again (the *Automatic* entry of the picker). Nothing else changes.
    static func clear(_ slot: NanoMuseSlot) {
        switch slot {
        case .chat, .hands: return
        case .image:
            NanoMuseImageGen.clearChoice()
            NotificationCenter.default.post(name: NanoMuseMediaModels.changed, object: nil)
        case .video:
            NanoMuseMediaModels.clearVideoChoice()
        }
        NotificationCenter.default.post(name: changed, object: nil)
    }

    /// Set one slot to a provider and a model (the pickers and the "Use it for" card).
    static func use(_ slot: NanoMuseSlot, providerId: String, model: String) {
        let isCloud = providerId == NanoMuseCloud.instance?.id
        switch slot {
        case .chat:
            useForChat(instanceId: providerId, model: model)
        case .hands:
            break // not on iPhone
        case .image:
            if isCloud {
                NanoMuseImageGen.useRelay(model: model)
            } else {
                NanoMuseImageGen.save(instanceId: providerId, model: model)
            }
            NotificationCenter.default.post(name: NanoMuseMediaModels.changed, object: nil)
        case .video:
            NanoMuseMediaModels.saveVideo(instanceId: providerId, model: model)
        }
        NotificationCenter.default.post(name: changed, object: nil)
    }

    /// The value line of a slot: `<provider> · <model>`, or nil when the slot has nothing.
    static func line(_ slot: NanoMuseSlot, providers: [NanoMuseSlotProvider]? = nil) -> String? {
        let list = providers ?? self.providers()
        let choice: NanoMuseSlotChoice?
        switch slot {
        case .chat: choice = chatChoice()
        case .hands: return nil
        case .image: choice = imageValue(providers: list)
        case .video: choice = videoValue(providers: list)
        }
        guard let choice else { return nil }
        return line(for: choice, in: list)
    }

    private static func line(for choice: NanoMuseSlotChoice, in list: [NanoMuseSlotProvider]) -> String {
        let label = list.first { $0.id == choice.providerId }?.label ?? ProviderConfigStore.shared.instance(for: choice.providerId)?.label ?? ""
        return label.isEmpty ? choice.model : "\(label) · \(choice.model)"
    }
}

// MARK: - "Use nanoMuse Cloud this time"

/// A turn on a key of one's own failed and the person asked for nanoMuse Cloud once: while
/// armed, the chat resolves its model to the relay's chat model (one `// nanoMuse:` line at the
/// top of `resolveCurrentEntry`), and nothing in the slots changes. Disarmed when the turn
/// ends (`nmAfterTurn`), or after ten minutes if no turn ran.
@MainActor
enum NanoMuseCloudOnce {
    private static var armedAt: Date?
    private static let maxAge: TimeInterval = 10 * 60

    /// The button shows only when the relay can take the turn.
    static var available: Bool { NanoMuseModelSlots.cloudChatEntry() != nil }

    /// Whether the turn that ended last ran on the relay (`turnEnded`), so upstream's plain
    /// inline error, which knows no provider, does not offer Cloud for Cloud's own failure.
    private(set) static var lastTurnWasCloud = false

    static func arm() { armedAt = Date() }
    static func disarm() { armedAt = nil }

    /// A turn ended (nmAfterTurn): remember where it ran, and a one-turn fallback is spent.
    static func turnEnded(onCloud: Bool) {
        lastTurnWasCloud = onCloud
        disarm()
    }

    static var isArmed: Bool {
        guard let at = armedAt else { return false }
        if Date().timeIntervalSince(at) > maxAge { armedAt = nil; return false }
        return true
    }

    /// The relay's chat entry while armed; nil otherwise (the chat resolves as usual).
    static func entry() -> ModelEntry? {
        guard isArmed else { return nil }
        return NanoMuseModelSlots.cloudChatEntry()
    }
}

// MARK: - The catalogue entry of an instance

extension NanoMuseCatalogue {
    /// The vendor an instance was made from: by the endpoint's host for an OpenAI-shaped one
    /// (`dashscope.aliyuncs.com` → Bailian), by the protocol for upstream's own types
    /// (OpenRouter, Anthropic, Gemini, xAI, Kimi); nil for the relay and for a host the
    /// catalogue does not list.
    @MainActor
    static func vendor(for inst: ProviderInstance) -> NanoMuseVendor? {
        if inst.id == NanoMuseCloud.instance?.id { return nil }
        let list = bundled + (NanoMuseAllowance.storedGuidance().map { $0.providers + $0.local } ?? [])
        switch inst.providerType {
        case .openRouter: return list.first { $0.id == openrouter }
        case .anthropic: return list.first { $0.protocolName == "anthropic" }
        case .gemini: return list.first { $0.protocolName == "gemini" }
        case .xAI: return list.first { $0.protocolName == "xai" }
        case .kimiCode: return list.first { $0.auth.contains(authKimi) }
        default: break
        }
        guard let host = NanoMuseProxy.hostOf(inst.customBaseURL ?? "") else { return nil }
        return list.first { v in
            [v.baseURL, v.baseURLGlobal ?? ""].compactMap(NanoMuseProxy.hostOf).contains(host)
        }
    }
}
