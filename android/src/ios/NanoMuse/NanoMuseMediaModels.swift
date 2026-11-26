//
//  NanoMuseMediaModels.swift
//  nanoMuse
//
//  The three models nanoMuse runs on. Muse ships with all of them built in;
//  here each is one of the person's own providers, chosen in Settings →
//  Image & video models:
//
//   - the chat model — OpenMinis' default model group, unchanged;
//   - the image model — the avatar's four candidates and poses
//     (NanoMuseImageGen: a Bailian key on this phone, or a relay whose live
//     menu explicitly advertises an image model);
//   - the video model — the animated avatar (NanoMuseVideoGen: Model
//     Studio's asynchronous video API, directly or through a relay that
//     explicitly advertises a video model).
//
//  Unset, the video model follows the image provider — an eligible relay
//  when the face is drawn through it, a Bailian key when that draws — so a
//  moving avatar needs no visit here; it can be switched off or moved to
//  another Model Studio provider. Android: media/MediaModels.kt,
//  ui/media/MediaModelsScreen.kt.
//

import SwiftUI

// MARK: - Store

enum NanoMuseMediaModels {
    /// The video model a Model Studio key starts on: the catalogue's `defaults.video` for
    /// Bailian (`providers.json`), the known Wan 2.2 Flash only if the catalogue is missing.
    static var defaultVideoModel: String {
        NanoMuseCatalogue.bundled.first { $0.id == NanoMuseCatalogue.bailian }?.defaults["video"] ?? NanoMuseVideoGen.knownDashScopeModels[0]
    }
    /// Posted after a save here, so the face view and the studio re-read what is set.
    static let changed = Notification.Name("nanoMuse.mediaModelsChanged")

    private enum Keys {
        static let videoInstance = "nanomuse.media.video.instance"
        static let videoModel = "nanomuse.media.video.model"
        static let animate = "nanomuse.media.animate_avatar"
        static let availablePrefix = "nanomuse.media.video.available."
        static let checkedPrefix = "nanomuse.media.video.checked."
    }

    /// Stored instance id meaning "the person switched the video model off".
    private static let videoOff = ""
    private static let checkTTL: TimeInterval = 24 * 60 * 60

    // MARK: Video

    /// Providers whose host speaks Model Studio's asynchronous video API and hold a key: Model
    /// Studio itself, and a relay only when its live menu advertises video generation.
    @MainActor
    static func eligibleVideoInstances() -> [ProviderInstance] {
        let cloud = NanoMuseModelSlots.cloudProvider()
        let cloudId = cloud?.has(.video) == true ? cloud?.id : nil
        return ProviderConfigStore.shared.instances.filter { inst in
            guard inst.isEnabled, inst.credentialType == .apiKey else { return false }
            guard inst.id == cloudId || NanoMuseVideoGen.speaksDashScope(inst.customBaseURL ?? "") else { return false }
            return !(ProviderKeychainHelper.loadAPIKey(instanceId: inst.id) ?? "").isEmpty
        }
    }

    /// What the person set for clips: nothing yet, switched off, or a provider and a model.
    enum VideoChoice: Equatable {
        case unset
        case off
        case chosen(NanoMuseSlotChoice)
    }

    static func videoChoice() -> VideoChoice {
        guard let saved = UserDefaults.standard.string(forKey: Keys.videoInstance) else { return .unset }
        if saved == videoOff { return .off }
        let model = UserDefaults.standard.string(forKey: Keys.videoModel)?.trimmingCharacters(in: .whitespaces) ?? ""
        return .chosen(NanoMuseSlotChoice(providerId: saved, model: model))
    }

    /// The instance the video model is on, or nil (0.1.41, the contract's section 3): the
    /// saved one; without a choice, the chat provider's when it is a Model Studio key of the
    /// person's own, else a relay that advertises video, else the first key that can.
    @MainActor
    static func videoInstance() -> ProviderInstance? {
        guard let value = NanoMuseModelSlots.videoValue() else { return nil }
        return eligibleVideoInstances().first { $0.id == value.providerId }
    }

    /// The video model in use: the one chosen or the provider's default; the recommended one when nothing is set.
    @MainActor
    static var videoModel: String {
        if let value = NanoMuseModelSlots.videoValue(), !value.model.isEmpty { return value.model }
        let saved = UserDefaults.standard.string(forKey: Keys.videoModel)?.trimmingCharacters(in: .whitespaces) ?? ""
        return saved.isEmpty ? defaultVideoModel : saved
    }

    /// The video models a Model Studio key may have before it was asked: the catalogue's
    /// default for the vendor first, then the known Wan and MiniMax ids, then anything on the
    /// key's own list that is named like a video model.
    @MainActor
    static func candidateVideoModels(for inst: ProviderInstance) -> [String] {
        let listed = ProviderConfigStore.shared.entries(for: inst.id)
            .filter { !$0.isHidden && NanoMuseVideoGen.looksLikeVideoModel($0.model.id) }
            .map(\.model.id)
        var out: [String] = []
        let first = NanoMuseCatalogue.vendor(for: inst)?.defaults["video"] ?? defaultVideoModel
        for id in [first] + NanoMuseVideoGen.knownDashScopeModels + listed where !id.isEmpty && !out.contains(id) { out.append(id) }
        return out
    }

    /// The video model, or nil when there is none.
    @MainActor
    static func videoEndpoint() -> NanoMuseVideoGen.Endpoint? {
        guard let value = NanoMuseModelSlots.videoValue(),
              let inst = eligibleVideoInstances().first(where: { $0.id == value.providerId }),
              let key = ProviderKeychainHelper.loadAPIKey(instanceId: inst.id), !key.isEmpty else { return nil }
        let model = value.model.isEmpty ? defaultVideoModel : value.model
        return NanoMuseVideoGen.Endpoint(instanceId: inst.id, label: inst.label, host: host(of: inst), apiKey: key, model: model)
    }

    /// The Cloud instance's base is the relay's; a Bailian instance's is the compatible-mode URL.
    @MainActor
    static func host(of inst: ProviderInstance) -> String {
        if inst.id == NanoMuseCloud.instance?.id { return NanoMuseCloud.baseURL }
        return NanoMuseVideoGen.host(of: inst.customBaseURL ?? "")
    }

    /// `instanceId` nil switches the video model off; it is remembered, unlike "never chosen".
    @MainActor
    static func saveVideo(instanceId: String?, model: String) {
        UserDefaults.standard.set(instanceId ?? videoOff, forKey: Keys.videoInstance)
        UserDefaults.standard.set(model.trimmingCharacters(in: .whitespaces), forKey: Keys.videoModel)
        NotificationCenter.default.post(name: changed, object: nil)
    }

    /// Back to the automatic order for clips (the *Automatic* entry of the picker): the
    /// stored choice, on or off, is forgotten, nothing else changes.
    @MainActor
    static func clearVideoChoice() {
        UserDefaults.standard.removeObject(forKey: Keys.videoInstance)
        UserDefaults.standard.removeObject(forKey: Keys.videoModel)
        NotificationCenter.default.post(name: changed, object: nil)
    }

    /// The video model is the relay's: a self-hosted relay may account for it.
    @MainActor
    static var videoOnCloud: Bool {
        guard let cloud = NanoMuseCloud.instance else { return false }
        return videoInstance()?.id == cloud.id
    }

    // MARK: Which video models the key can use

    /// The video models of `inst` that answered the last check, recommended first; nil when it has
    /// never been checked. Model Studio does not list video models on `/models`, so this is what
    /// "which models does this key have" means for video: the known candidates, each probed once.
    @MainActor
    static func availableVideoModels(for inst: ProviderInstance) -> [String]? {
        if let models = hostedVideoModels(for: inst) { return models }
        guard let raw = UserDefaults.standard.string(forKey: Keys.availablePrefix + inst.id),
              let data = raw.data(using: .utf8),
              let list = (try? JSONSerialization.jsonObject(with: data)) as? [String] else { return nil }
        return list.filter { !$0.isEmpty }
    }

    @MainActor
    private static func hostedVideoModels(for inst: ProviderInstance) -> [String]? {
        guard inst.id == NanoMuseCloud.instance?.id, !NanoMuseRelayMenu.allows(.video, at: NanoMuseCloud.baseURL) else { return nil }
        return NanoMuseRelayMenu.models(for: .video, in: NanoMuseRelayMenu.cached).filter { NanoMuseRelayMenu.allows(.video, at: NanoMuseCloud.baseURL, model: $0) }
    }

    @MainActor
    static func videoCheckIsFresh(for inst: ProviderInstance) -> Bool {
        if hostedVideoModels(for: inst) != nil { return true }
        return Date().timeIntervalSince1970 - UserDefaults.standard.double(forKey: Keys.checkedPrefix + inst.id) < checkTTL
    }

    /// Asks the host which of the known video models exist for this key — plus anything on the
    /// provider's own list that is named like a video model — and remembers the answer. The
    /// models found, or nil when the host could not be reached at all.
    @MainActor
    static func checkVideoModels(for inst: ProviderInstance) async -> [String]? {
        if let models = hostedVideoModels(for: inst) { return models }
        guard let key = ProviderKeychainHelper.loadAPIKey(instanceId: inst.id), !key.isEmpty else { return nil }
        let host = host(of: inst)
        let listed = ProviderConfigStore.shared.entries(for: inst.id)
            .filter { !$0.isHidden && NanoMuseVideoGen.looksLikeVideoModel($0.model.id) }
            .map(\.model.id)
        var candidates: [String] = []
        for id in NanoMuseVideoGen.knownDashScopeModels + listed where !candidates.contains(id) { candidates.append(id) }
        var reached = false
        var found: [String] = []
        for model in candidates {
            let ok = await NanoMuseVideoGen.probe(host: host, apiKey: key, model: model)
            if ok != nil { reached = true }
            if ok == true { found.append(model) }
        }
        guard reached else { return nil }
        if let data = try? JSONSerialization.data(withJSONObject: found), let raw = String(data: data, encoding: .utf8) {
            UserDefaults.standard.set(raw, forKey: Keys.availablePrefix + inst.id)
        }
        UserDefaults.standard.set(Date().timeIntervalSince1970, forKey: Keys.checkedPrefix + inst.id)
        return found
    }

    // MARK: Animate

    /// Whether a new face is animated after its poses (four short clips through the video model). On by default.
    static var animateAvatar: Bool {
        get { UserDefaults.standard.object(forKey: Keys.animate) as? Bool ?? true }
        set {
            UserDefaults.standard.set(newValue, forKey: Keys.animate)
            NotificationCenter.default.post(name: changed, object: nil)
        }
    }

    // MARK: Lines

    /// "qwen-image-3.0 · Bailian" / "nanoMuse Cloud" / "Not set".
    @MainActor
    static func imageLine() -> String {
        switch NanoMuseImageGen.route() {
        case .ownKey(let k): return "\(k.model) · \(k.label)"
        case .relay: return NanoMuseCloud.modelsOn ? NanoMuseCloud.label : AppLocalized("Not set")
        case .unavailable: return AppLocalized("Not set")
        }
    }

    @MainActor
    static func videoLine() -> String {
        guard let ep = videoEndpoint() else { return AppLocalized("Not set") }
        return "\(ep.model) · \(ep.label)"
    }
}

// MARK: - Screen

/// Settings → Image & video models. The one place that says what Muse never has to: nanoMuse
/// runs on three of the person's own models. The chat model is OpenMinis' default group (a row
/// to its picker); the image and video models are chosen here — a provider, then one of the
/// models the key turns out to have — and each section says plainly what stops working
/// without one. Android: MediaModelsScreen.
struct NanoMuseMediaModelsView: View {
    @ObservedObject private var store = ProviderConfigStore.shared
    @ObservedObject private var motion = NanoMuseAvatarMotion.shared
    @ObservedObject private var faces = NanoMuseFaceStore.shared

    // Image: a Bailian key on this phone, or an eligible relay (NanoMuseImageGen).
    @State private var imageInstances: [ProviderInstance] = []
    @State private var imageInstanceId: String?
    @State private var imageModel = ""
    @State private var imageChecking = false

    // Video: the saved choice, or the image provider's when it speaks the video API.
    @State private var videoInstances: [ProviderInstance] = []
    @State private var videoInstanceId: String?
    @State private var videoModel = NanoMuseMediaModels.defaultVideoModel
    @State private var videoModels: [String]?
    @State private var videoChecking = false
    @State private var animate = NanoMuseMediaModels.animateAvatar

    var body: some View {
        Form {
            Section {
                Text(AppLocalized("Three models, each chosen on its own: the chat model you talk to, an image model for the avatar and pictures, a video model that makes the avatar move. One Alibaba Cloud Model Studio key covers all three."))
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            chatSection
            imageSection
            videoSection
        }
        .navigationTitle(AppLocalized("Image & video models"))
        .navigationBarTitleDisplayMode(.inline)
        .onAppear { reload() }
        .nmOnChange(of: store.instances) { _ in reload() }
    }

    // MARK: Chat

    private var defaultGroup: ModelGroup? {
        store.modelGroups.first { $0.id == store.defaultPrimaryGroupId } ?? store.modelGroups.first
    }

    private var chatSection: some View {
        let entry = defaultGroup?.memberEntryIds.lazy.compactMap { store.entry(for: $0) }.first
        let instance = entry.flatMap { store.instance(for: $0.providerInstanceId) }
        let subtitle = [instance?.label, entry?.model.displayName].compactMap { $0 }.joined(separator: " · ")
        return Section {
            NavigationLink {
                ModelGroupsView()
            } label: {
                HStack(spacing: 12) {
                    Image(systemName: "bubble.left").foregroundStyle(.primary).frame(width: 24)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(defaultGroup?.name ?? AppLocalized("No model yet"))
                        Text(subtitle.isEmpty ? AppLocalized("Sign in to nanoMuse Cloud or add a provider") : subtitle)
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
        } header: {
            Text(AppLocalized("Chat model"))
        } footer: {
            Text(AppLocalized("The default model group. Every conversation, the feed and the daily routines run on it."))
        }
    }

    // MARK: Image

    private var imageInstance: ProviderInstance? { imageInstances.first { $0.id == imageInstanceId } }
    private var relayImageAvailable: Bool { NanoMuseModelSlots.cloudProvider()?.has(.image) == true }

    @ViewBuilder
    private var imageSection: some View {
        Section {
            let ready = imageInstance != nil || relayImageAvailable
            statusRow(
                icon: "photo",
                ready: ready,
                line: imageInstance != nil ? "\(imageModel) · \(imageInstance?.label ?? "")" : (relayImageAvailable ? NanoMuseCloud.label : AppLocalized("Not set")),
                offLine: AppLocalized("Until one is set, the avatar cannot be changed and no pictures can be drawn. The agent will say so if you ask.")
            )
            if relayImageAvailable {
                choiceRow(title: NanoMuseCloud.label, selected: imageInstanceId == nil) {
                    imageInstanceId = nil
                    imageModel = ""
                    NanoMuseImageGen.useRelay()
                    NotificationCenter.default.post(name: NanoMuseMediaModels.changed, object: nil)
                }
            }
            ForEach(imageInstances) { inst in
                choiceRow(title: inst.label, selected: imageInstanceId == inst.id) {
                    imageInstanceId = inst.id
                    imageModel = NanoMuseImageGen.suggestedModel(for: inst)
                    NanoMuseImageGen.preferRelay = false
                    NanoMuseImageGen.save(instanceId: inst.id, model: imageModel)
                }
            }
            if let inst = imageInstance {
                modelList(
                    header: String(format: AppLocalized("Models on %@"), inst.label),
                    models: NanoMuseImageGen.availableModels(for: inst),
                    recommended: NanoMuseImageGen.recommendedBailianModel,
                    selected: imageModel,
                    checking: imageChecking,
                    empty: AppLocalized("No image model found on this provider. Type one below, or check again once the key is in."),
                    onSelect: { imageModel = $0; NanoMuseImageGen.save(instanceId: inst.id, model: $0) },
                    onCheck: { checkImageModels(inst) }
                )
                TextField(AppLocalized("Other model name"), text: $imageModel, prompt: Text("qwen-image-3.0 · …"))
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .onSubmit { NanoMuseImageGen.save(instanceId: inst.id, model: imageModel) }
            }
            if imageInstances.isEmpty && !relayImageAvailable {
                NavigationLink(AppLocalized("Add a provider")) { ProviderInstancesView() }
            }
        } header: {
            Text(AppLocalized("Image model"))
        } footer: {
            Text(imageInstances.isEmpty
                 ? AppLocalized("Add a provider")
                 : AppLocalized("Image model"))
        }
    }

    private func checkImageModels(_ inst: ProviderInstance) {
        guard !imageChecking else { return }
        imageChecking = true
        Task { @MainActor in
            await store.refreshModels(for: inst)
            imageChecking = false
        }
    }

    // MARK: Video

    private var videoInstance: ProviderInstance? { videoInstances.first { $0.id == videoInstanceId } }

    @ViewBuilder
    private var videoSection: some View {
        Section {
            statusRow(
                icon: "film",
                ready: videoInstance != nil && !videoModel.isEmpty,
                line: videoInstance != nil ? (videoModel.isEmpty ? AppLocalized("Type a model name below") : "\(videoModel) · \(videoInstance?.label ?? "")") : AppLocalized("Not set"),
                offLine: AppLocalized("Optional. Without one, the avatar stays still and no clips can be made.")
            )
            choiceRow(title: AppLocalized("No video model"), selected: videoInstanceId == nil) {
                videoInstanceId = nil
                NanoMuseMediaModels.saveVideo(instanceId: nil, model: videoModel)
            }
            ForEach(videoInstances) { inst in
                choiceRow(title: inst.label, selected: videoInstanceId == inst.id) {
                    videoInstanceId = inst.id
                    if videoModel.isEmpty { videoModel = NanoMuseMediaModels.defaultVideoModel }
                    NanoMuseMediaModels.saveVideo(instanceId: inst.id, model: videoModel)
                    loadVideoModels(for: inst)
                }
            }
            if let url = NanoMuseMediaModels.videoEndpoint()?.studioURL {
                Link(NanoMuseRelayMenu.hostedVideo, destination: url)
            } else if let inst = videoInstance {
                modelList(
                    header: String(format: AppLocalized("Models on %@"), inst.label),
                    models: videoModels ?? [],
                    recommended: NanoMuseMediaModels.defaultVideoModel,
                    selected: videoModel,
                    checking: videoChecking,
                    empty: AppLocalized("No video model answered for this key. Type one below, or check again."),
                    onSelect: { videoModel = $0; NanoMuseMediaModels.saveVideo(instanceId: inst.id, model: $0) },
                    onCheck: { checkVideoModels(inst) }
                )
                TextField(AppLocalized("Other model name"), text: $videoModel, prompt: Text(NanoMuseMediaModels.defaultVideoModel))
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .onSubmit { NanoMuseMediaModels.saveVideo(instanceId: inst.id, model: videoModel) }
                Toggle(isOn: $animate) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(AppLocalized("Animate the avatar after a change"))
                        Text(String(format: AppLocalized("%d clips of %d s, one per state, drawn in the background once the poses are done"), NanoMuseAvatarMotion.animated.count, NanoMuseAvatarMotion.seconds))
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
                .nmOnChange(of: animate) { on in NanoMuseMediaModels.animateAvatar = on }
                if faces.hasCustomFace {
                    clipsRow
                    ForEach(NanoMuseAvatarMotion.animated, id: \.self) { mood in clipLine(mood) }
                }
            }
        } header: {
            Text(AppLocalized("Video model"))
        } footer: {
            Text(videoInstances.isEmpty
                 ? AppLocalized("Add a provider")
                 : AppLocalized("Makes the avatar move: a short looping clip for each state. Alibaba Cloud Model Studio: wan2.2-i2v-flash (recommended, ¥0.10 a second at 480P), another Wan model or MiniMax/MiniMax-H3; the list shows the ones this key can use, each activated once on the model's card in the Model Studio console. Billed per second of video; an avatar takes four clips of a few seconds."))
        }
    }

    /// The clips of the current face: how many exist, what is running, Make / Redo.
    private var clipsRow: some View {
        let running = motion.progress?.running == true
        let total = NanoMuseAvatarMotion.animated.count
        return HStack(spacing: 12) {
            Image(systemName: "play.circle").foregroundStyle(.primary).frame(width: 24)
            VStack(alignment: .leading, spacing: 2) {
                Text(String(format: AppLocalized("Clips for the current face: %d of %d"), motion.clips.count, total))
                Text(motion.statusLine ?? motion.progress?.error ?? AppLocalized("Head shake at rest, crystal ball while waiting, star when pleased, laptop while working"))
                    .font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            if running {
                Text(AppLocalized("Drawing…")).font(.subheadline).foregroundStyle(.secondary)
            } else {
                Button(motion.clips.isEmpty ? AppLocalized("Make") : AppLocalized("Redo")) {
                    let force = motion.clips.count >= total
                    Task { @MainActor in await NanoMuseAvatarMotion.shared.animateAll(force: force) }
                }
                .font(.subheadline.weight(.medium))
                .tint(NanoMuseTones.action)
            }
        }
    }

    /// One clip: the face in that mood, the mood's word, the file's size — or a dash while it is missing.
    private func clipLine(_ mood: NanoMuseMood) -> some View {
        HStack(spacing: 12) {
            NanoMuseFaceView(mood: mood, size: 28, showsRing: false)
            Text(Self.moodWord(mood))
            Spacer()
            Text(motion.clips[mood].flatMap(Self.fileSize) ?? "…")
                .font(.caption).foregroundStyle(.secondary)
        }
    }

    private static func moodWord(_ mood: NanoMuseMood) -> String {
        switch mood {
        case .idle: return AppLocalized("At rest")
        case .working: return AppLocalized("Working")
        case .waiting: return AppLocalized("Waiting")
        case .happy: return AppLocalized("Pleased")
        case .error: return AppLocalized("Oops")
        }
    }

    private static func fileSize(_ url: URL) -> String? {
        guard let n = (try? FileManager.default.attributesOfItem(atPath: url.path))?[.size] as? NSNumber else { return nil }
        return ByteCountFormatter.string(fromByteCount: n.int64Value, countStyle: .file)
    }

    private func loadVideoModels(for inst: ProviderInstance) {
        videoModels = NanoMuseMediaModels.availableVideoModels(for: inst)
        if videoModels == nil || !NanoMuseMediaModels.videoCheckIsFresh(for: inst) { checkVideoModels(inst) }
    }

    private func checkVideoModels(_ inst: ProviderInstance) {
        guard !videoChecking else { return }
        videoChecking = true
        Task { @MainActor in
            if let found = await NanoMuseMediaModels.checkVideoModels(for: inst) { videoModels = found }
            videoChecking = false
        }
    }

    // MARK: Pieces

    private func reload() {
        imageInstances = NanoMuseImageGen.bailianInstances()
        switch NanoMuseImageGen.route() {
        case .ownKey(let k):
            imageInstanceId = k.instanceId
            imageModel = k.model
        case .relay:
            imageInstanceId = nil
            imageModel = ""
        case .unavailable:
            imageInstanceId = nil
            imageModel = ""
        }
        videoInstances = NanoMuseMediaModels.eligibleVideoInstances()
        videoInstanceId = NanoMuseMediaModels.videoInstance()?.id
        videoModel = NanoMuseMediaModels.videoModel
        if let inst = videoInstance { loadVideoModels(for: inst) } else { videoModels = nil }
    }

    /// Ready / not set, with the one line of consequence when it is not.
    private func statusRow(icon: String, ready: Bool, line: String, offLine: String) -> some View {
        HStack(spacing: 12) {
            Image(systemName: icon)
                .foregroundStyle(ready ? NanoMuseTones.action : Color.secondary)
                .frame(width: 24)
            VStack(alignment: .leading, spacing: 2) {
                Text(line)
                Text(ready ? AppLocalized("Ready") : offLine)
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    private func choiceRow(title: String, selected: Bool, onSelect: @escaping () -> Void) -> some View {
        Button(action: onSelect) {
            HStack {
                Text(title).foregroundStyle(.primary)
                Spacer()
                if selected { Image(systemName: "checkmark").foregroundStyle(NanoMuseTones.action) }
            }
        }
    }

    /// The models the key can use, one row each, the recommended one marked; a "checking…" line
    /// while the provider is asked, and a row to ask again.
    @ViewBuilder
    private func modelList(
        header: String,
        models: [String],
        recommended: String,
        selected: String,
        checking: Bool,
        empty: String,
        onSelect: @escaping (String) -> Void,
        onCheck: @escaping () -> Void
    ) -> some View {
        Text(header).font(.footnote.weight(.medium)).foregroundStyle(.secondary)
        ForEach(models, id: \.self) { id in
            Button { onSelect(id) } label: {
                HStack {
                    if id == recommended {
                        Text(AppLocalized("Recommended")).font(.caption2.weight(.medium)).foregroundStyle(NanoMuseTones.action)
                    }
                    Text(id).foregroundStyle(.primary)
                    Spacer()
                    if selected == id { Image(systemName: "checkmark").foregroundStyle(NanoMuseTones.action) }
                }
            }
        }
        if checking {
            HStack(spacing: 10) {
                ProgressView().controlSize(.small)
                Text(AppLocalized("Checking which models this key can use…")).foregroundStyle(.secondary)
            }
        } else if models.isEmpty {
            Button(action: onCheck) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(empty).foregroundStyle(.secondary)
                    Text(AppLocalized("Check again")).font(.caption).foregroundStyle(NanoMuseTones.action)
                }
            }
        } else {
            Button(AppLocalized("Check again"), action: onCheck).foregroundStyle(NanoMuseTones.action)
        }
    }
}
