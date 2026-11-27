//
//  NanoMuseAvatarStudio.swift
//  nanoMuse
//
//  Describe a face → four candidates → pick one → the moods are posed
//  from it → saved on this phone and in the account's profile. Pictures
//  are drawn with a provider key on this phone, or through a self-hosted
//  relay that explicitly advertises an image model (NanoMuseImageGen).
//  The chat-driven flow (NanoMuseAvatarFlow) drives this same model.
//  Android: avatar/AvatarStudio.kt, ui/avatar/AvatarStudioScreen.kt.
//

import Combine // nanoMuse: the header follows the motion clips' progress through this model
import SwiftUI
import UIKit

// MARK: - Styles and prompts

enum NanoMuseAvatarStyle: String, CaseIterable, Identifiable {
    case muse, flat, clay, watercolor, pixel, line, sticker
    var id: String { rawValue }

    var label: String {
        switch self {
        case .muse: return AppLocalized("3D toy (Muse)")
        case .flat: return AppLocalized("Flat")
        case .clay: return AppLocalized("3D clay")
        case .watercolor: return AppLocalized("Watercolour")
        case .pixel: return AppLocalized("Pixel")
        case .line: return AppLocalized("Line")
        case .sticker: return AppLocalized("Sticker")
        }
    }

    var phrase: String {
        switch self {
        case .muse: return "cute 3D character render in the style of a collectible vinyl toy, soft matte materials with subtle sheen, rounded simplified forms, big friendly eyes, soft studio lighting with gentle shadows, pastel accents"
        case .flat: return "flat vector illustration, soft pastel colours, clean simple shapes, subtle shading"
        case .clay: return "3D clay render, soft studio lighting, matte rounded forms, gentle colours"
        case .watercolor: return "gentle watercolour painting, soft edges, light paper texture"
        case .pixel: return "crisp pixel art, limited palette, clean silhouette"
        case .line: return "minimal line drawing with two accent colours on cream, confident strokes"
        case .sticker: return "glossy sticker style, thick white outline, bold saturated colours"
        }
    }
}

private struct NanoMuseAvatarPreset: Identifiable {
    let id: String
    let nameKey: String.LocalizationValue
    let descriptionKey: String.LocalizationValue
    let style: NanoMuseAvatarStyle

    var name: String { AppLocalized(nameKey) }
    var description: String { AppLocalized(descriptionKey) }

    static let all = [
        NanoMuseAvatarPreset(id: "moss-courier", nameKey: "Moss Courier", descriptionKey: "a tiny moss-covered courier with leaf ears and an unmarked canvas satchel", style: .muse),
        NanoMuseAvatarPreset(id: "tide-tinker", nameKey: "Tide Tinker", descriptionKey: "a seafoam axolotl tinkerer with coral frills and a plain tool pouch", style: .clay),
        NanoMuseAvatarPreset(id: "dusk-moth", nameKey: "Dusk Moth", descriptionKey: "a thoughtful indigo moth with peach wing spots, a cream collar and round glasses", style: .watercolor),
        NanoMuseAvatarPreset(id: "copper-acorn", nameKey: "Copper Acorn", descriptionKey: "a small acorn-shaped copper automaton with sage panels and a muted-blue scarf", style: .line),
    ]
}

enum NanoMuseAvatarPrompts {
    static let candidates = 4
    static let posedMoods: [NanoMuseMood] = [.working, .waiting, .happy, .error]

    static func candidate(description: String, style: NanoMuseAvatarStyle, index: Int) -> String {
        let variations = [
            "variation 1: the most typical, classic colouring",
            "variation 2: a different breed or colour pattern, lighter tones",
            "variation 3: a different breed or colour pattern, darker or warmer tones, a small accessory such as a scarf or glasses",
            "variation 4: a playful take, unusual colouring or a tiny outfit, slight head tilt",
        ]
        var subject = description.trimmingCharacters(in: .whitespacesAndNewlines)
        while let last = subject.last, ".。!！,，".contains(last) { subject.removeLast() }
        return "A cute character based on: \(subject). \(style.phrase). Full body, standing, facing the viewer, "
            + "centred, whole figure visible with margin on all sides, big head and small body, friendly expression, "
            + "pure white background, soft ground shadow only. \(variations[index % 4]). "
            + "Square composition. No text, no watermark, no border, no props other than what is described, one character only."
    }

    static func mood(_ mood: NanoMuseMood) -> String {
        let keep = "Keep this exact character: same face, colours, outfit, art style, proportions, framing, "
            + "camera angle and pure white background. Change only the pose and props described. "
        switch mood {
        case .working:
            return keep + "It now wears over-ear headphones and sits typing on a small open laptop in front of it, focused and content, a faint glow from the screen on its face."
        case .waiting:
            return keep + "It now holds a small glowing crystal ball in both hands at chest height and gazes into it with wide curious eyes, waiting for an answer."
        case .happy:
            return keep + "It is now celebrating, hugging a big glowing yellow five-pointed star, eyes closed with a wide smile. Same white background; no confetti, no night sky, no extra decoration."
        case .error:
            return keep + "It now looks sheepish and apologetic, a small sweat drop beside its head, one hand behind its head, shoulders slightly raised."
        case .idle:
            return keep + "No change."
        }
    }
}

// MARK: - Model

@MainActor
final class NanoMuseAvatarStudioModel: ObservableObject {
    static let shared = NanoMuseAvatarStudioModel()

    struct Candidate: Identifiable, Equatable {
        let id = UUID()
        var image: UIImage?
        var error: String?
        var drawing = true
        /// Where the picture is kept, so a persisted options card can show it again.
        var file: URL?
    }

    enum Phase: Equatable {
        case describe
        case drawing
        case pick
        case posing(done: Int, total: Int)
        case finished(drawn: Int, total: Int)
    }

    @Published var description: String = ""
    @Published var style: NanoMuseAvatarStyle = .muse
    @Published private(set) var phase: Phase = .describe
    @Published private(set) var candidates: [Candidate] = []
    @Published var selected: Int?
    @Published private(set) var estimate: NanoMuseRelayMedia.Estimate?
    @Published private(set) var estimateError: String?
    @Published private(set) var estimating = false
    @Published private(set) var lastError: String?
    /// Which round of candidates is up; files are named after it.
    private var round = 0
    /// nanoMuse: `headerStatus` reads the motion clips' progress, so their changes are this model's too.
    private var motionWatch: AnyCancellable?

    private init() {
        description = AppLocalized("A chubby pale-yellow baby dragon with tiny orange horns and small folded wings")
        motionWatch = NanoMuseAvatarMotion.shared.objectWillChange.sink { [weak self] _ in
            self?.objectWillChange.send()
        }
    }

    var isBusy: Bool {
        switch phase {
        case .drawing, .posing: return true
        default: return false
        }
    }

    /// What the header says while the studio works in the background — and, once the poses are
    /// done, while the clips are drawn (contract C3: "Animating 2/4…").
    var headerStatus: String? {
        switch phase {
        case .drawing: return AppLocalized("Generating options")
        case .posing: return AppLocalized("Finalizing avatar")
        default: return NanoMuseAvatarMotion.shared.statusLine // nanoMuse: motion clips
        }
    }

    var picturesPerFace: Int { NanoMuseAvatarPrompts.candidates + NanoMuseAvatarPrompts.posedMoods.count }

    /// Clips a new face costs from the allowance: one per animated mood when the video model is
    /// nanoMuse Cloud and animation is on; 0 when they would come from a key of your own, or not at all.
    var clipsPerFace: Int {
        NanoMuseMediaModels.videoOnCloud && NanoMuseAvatarMotion.shared.enabled ? NanoMuseAvatarMotion.animated.count : 0
    }

    /// "A new face is 8 pictures" / "… and 4 short clips" — the cost sheet's first line (Android `nm_face_cost_what`).
    var costWhat: String {
        clipsPerFace > 0
            ? String(format: AppLocalized("A new face is %d pictures and %d short clips"), picturesPerFace, clipsPerFace)
            : String(format: AppLocalized("A new face is %d pictures"), picturesPerFace)
    }

    /// Whether a Bailian key on this phone draws the face.
    var usesOwnKey: Bool { NanoMuseImageGen.usesOwnKey }

    /// Whether a picture can be drawn at all right now; the reason when not.
    var cannotDrawReason: String? {
        if case .unavailable = NanoMuseImageGen.route() {
            return AppLocalized("No image model found on this provider. Type one below, or check again once the key is in.")
        }
        return nil
    }

    /// Files of the candidates on screen, in order ("" where one failed).
    var candidateFiles: [String] { candidates.map { $0.file?.path ?? "" } }

    static var optionsDirectory: URL {
        let dir = NanoMuseDirs.root.appendingPathComponent("avatar-options", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    /// Candidates older than the last two rounds go, so options do not pile up.
    private func pruneOptionFiles(keepingRound current: Int) {
        let dir = Self.optionsDirectory
        guard let names = try? FileManager.default.contentsOfDirectory(atPath: dir.path) else { return }
        for name in names {
            guard let dash = name.firstIndex(of: "-"), let r = Int(name[..<dash]), r < current - 1 else { continue }
            try? FileManager.default.removeItem(at: dir.appendingPathComponent(name))
        }
    }

    private func store(_ image: UIImage, round: Int, index: Int) -> URL? {
        let url = Self.optionsDirectory.appendingPathComponent("\(round)-\(index).png")
        guard let data = NanoMuseFaceStore.square(image, side: 768).pngData() else { return nil }
        do {
            try data.write(to: url, options: .atomic)
            return url
        } catch {
            return nil
        }
    }

    // MARK: Cost

    func refreshEstimate() {
        guard case .relay = NanoMuseImageGen.route() else { return }
        estimating = true
        estimateError = nil
        Task { @MainActor [self] in
            defer { estimating = false }
            do {
                estimate = try await NanoMuseRelayMedia.estimate(images: picturesPerFace, clips: clipsPerFace)
            } catch {
                estimate = nil
                estimateError = NanoMuseCloud.describe(error)
            }
        }
    }

    // MARK: Drawing

    func draw() {
        let desc = description.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !desc.isEmpty, !isBusy else { return }
        lastError = nil
        selected = nil
        candidates = Array(repeating: Candidate(), count: NanoMuseAvatarPrompts.candidates)
        phase = .drawing
        round += 1
        let thisRound = round
        pruneOptionFiles(keepingRound: thisRound)
        Task { @MainActor [self] in
            await withTaskGroup(of: (Int, Result<UIImage, Error>).self) { group in
                for i in 0..<NanoMuseAvatarPrompts.candidates {
                    let prompt = NanoMuseAvatarPrompts.candidate(description: desc, style: self.style, index: i)
                    group.addTask { @MainActor in
                        do {
                            let image = try await NanoMuseImageGen.generate(prompt: prompt)
                            return (i, .success(image))
                        } catch {
                            return (i, .failure(error))
                        }
                    }
                }
                for await (i, result) in group {
                    guard i < self.candidates.count, thisRound == self.round else { continue }
                    switch result {
                    case .success(let image):
                        self.candidates[i] = Candidate(image: image, error: nil, drawing: false, file: self.store(image, round: thisRound, index: i))
                    case .failure(let error):
                        self.candidates[i] = Candidate(image: nil, error: NanoMuseCloud.describe(error), drawing: false)
                    }
                }
            }
            guard thisRound == self.round else { return }
            if self.candidates.allSatisfy({ $0.image == nil }) {
                self.lastError = self.candidates.first?.error ?? AppLocalized("The pictures did not come through. Try again in a minute.")
                self.phase = .describe
            } else {
                self.phase = .pick
            }
        }
    }

    /// The chat flow: description and house style in, four candidates drawn. False with the reason when nothing can be drawn.
    func start(description desc: String, style: NanoMuseAvatarStyle = .muse) -> Bool {
        if let reason = cannotDrawReason {
            lastError = reason
            return false
        }
        guard !isBusy else { return false }
        description = desc
        self.style = style
        draw()
        return phase == .drawing
    }

    func retry(_ index: Int) {
        guard phase == .pick, index < candidates.count else { return }
        let desc = description.trimmingCharacters(in: .whitespacesAndNewlines)
        let thisRound = round
        candidates[index] = Candidate()
        Task { @MainActor [self] in
            do {
                let image = try await NanoMuseImageGen.generate(prompt: NanoMuseAvatarPrompts.candidate(description: desc, style: style, index: index))
                if index < candidates.count, thisRound == round {
                    candidates[index] = Candidate(image: image, error: nil, drawing: false, file: store(image, round: thisRound, index: index))
                }
            } catch {
                if index < candidates.count { candidates[index] = Candidate(image: nil, error: NanoMuseCloud.describe(error), drawing: false) }
            }
        }
    }

    /// The chat flow picked one by tap or by words.
    @discardableResult
    func adopt(index: Int) -> Bool {
        guard phase == .pick, index < candidates.count, candidates[index].image != nil else { return false }
        selected = index
        adopt()
        return true
    }

    /// Wear the chosen picture now and pose the other moods from it.
    func adopt() {
        guard let i = selected, i < candidates.count, let base = candidates[i].image, !isBusy else { return }
        let desc = description.trimmingCharacters(in: .whitespacesAndNewlines)
        NanoMuseFaceStore.shared.adopt([.idle: base], description: desc, style: style.rawValue)
        candidates = []
        selected = nil
        poseMoods(from: base)
    }

    /// Draw the four poses again for the face that is worn.
    func redrawMoods() {
        guard !isBusy, let base = NanoMuseFaceStore.shared.custom[.idle] else { return }
        poseMoods(from: base)
    }

    func reset() {
        guard !isBusy else { return }
        NanoMuseFaceStore.shared.reset()
        phase = .describe
    }

    func backToDescribe() {
        guard !isBusy else { return }
        candidates = []
        selected = nil
        phase = .describe
    }

    private func poseMoods(from base: UIImage) {
        let moods = NanoMuseAvatarPrompts.posedMoods
        phase = .posing(done: 0, total: moods.count)
        Task { @MainActor [self] in
            var done = 0
            var drawn = 0
            for mood in moods {
                do {
                    let image = try await NanoMuseImageGen.edit(base, prompt: NanoMuseAvatarPrompts.mood(mood))
                    NanoMuseFaceStore.shared.put(mood, image: image)
                    drawn += 1
                } catch {
                    self.lastError = NanoMuseCloud.describe(error)
                }
                done += 1
                self.phase = .posing(done: done, total: moods.count)
            }
            NanoMuseProfileSync.shared.faceChanged()
            self.phase = .finished(drawn: drawn, total: moods.count)
            // nanoMuse: the clips, in the background, once the poses are in (contract C3)
            NanoMuseAvatarMotion.shared.animateIfEnabled()
            // nanoMuse: the star ask goes through the policy's gate (contract C1)
            NanoMuseStar.shared.newLook()
        }
    }
}

// MARK: - View

struct NanoMuseAvatarStudioView: View {
    /// True when pushed inside another navigation stack (no own stack, no Done).
    var embedded: Bool = false

    @ObservedObject private var studio = NanoMuseAvatarStudioModel.shared
    @ObservedObject private var faces = NanoMuseFaceStore.shared
    @ObservedObject private var motion = NanoMuseAvatarMotion.shared // nanoMuse: clips
    @ObservedObject private var own = NanoMuseOwnClip.shared
    @StateObject private var clipPicker = NanoMuseOwnClipPicker()
    @Environment(\.dismiss) private var dismiss
    @State private var askCost = false
    @State private var confirmReset = false

    private var sourceNote: String {
        switch NanoMuseImageGen.route() {
        case .ownKey:
            return AppLocalized("Pictures are drawn with your Bailian key and kept on this phone; the face is shared with your other devices through your account. Each new face is eight pictures: four to choose from and four moods.")
        case .relay:
            return AppLocalized("Pictures are drawn through nanoMuse Cloud and kept on this phone; the face is shared with your other devices through your account. Each new face is eight pictures: four to choose from and four moods.")
        case .unavailable:
            return AppLocalized("Until one is set, the avatar cannot be changed and no pictures can be drawn. The agent will say so if you ask.")
        }
    }

    var body: some View {
        if embedded {
            content
        } else {
            NavigationStack {
                content
                    .toolbar {
                        ToolbarItem(placement: .topBarTrailing) {
                            Button(AppLocalized("Done")) { dismiss() }
                        }
                    }
            }
        }
    }

    private var content: some View {
            Form {
                currentSection
                ownClipSection
                switch studio.phase {
                case .describe:
                    describeSection
                case .drawing, .pick:
                    pickSection
                case .posing(let done, let total):
                    Section {
                        HStack(spacing: 12) {
                            ProgressView()
                            Text(String(format: AppLocalized("Posing the moods… %d/%d"), done, total))
                        }
                    }
                case .finished(let drawn, let total):
                    Section {
                        Label(
                            drawn == total
                                ? AppLocalized("All five moods are drawn.")
                                : String(format: AppLocalized("%d of %d moods drawn; the rest use the main picture."), drawn, total),
                            systemImage: drawn == total ? "checkmark.circle" : "exclamationmark.circle"
                        )
                        if drawn < total {
                            Button(AppLocalized("Retry")) { studio.redrawMoods() }
                        }
                        Button(AppLocalized("Describe a new face")) { studio.backToDescribe() }
                    }
                }
                if let error = studio.lastError {
                    Section {
                        Text(error).foregroundStyle(.red).font(.footnote)
                    }
                }
                Section {
                    Text(sourceNote)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                    Text(NanoMuseImageGen.providerLine())
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                    if studio.usesOwnKey {
                        NavigationLink(AppLocalized("Image model")) { NanoMuseImageModelPicker() }
                    }
                }
            }
            .navigationTitle(AppLocalized("Avatar"))
            .navigationBarTitleDisplayMode(.inline)
            .sheet(isPresented: $askCost) {
                NanoMuseFaceCostSheet(studio: studio) {
                    askCost = false
                    studio.draw()
                }
                .presentationDetents([.medium])
            }
            .confirmationDialog(AppLocalized("Back to the built-in face"), isPresented: $confirmReset, titleVisibility: .visible) {
                Button(AppLocalized("Back to the built-in face"), role: .destructive) { studio.reset() }
                Button(AppLocalized("Cancel"), role: .cancel) {}
            }
            .nanoMuseOwnClipHost(clipPicker)
    }

    /// A clip of the person's own as the face (#324): choose, replace, or back to the default.
    private var ownClipSection: some View {
        Section {
            Button(own.clip == nil ? AppLocalized("Choose a clip") : AppLocalized("Replace the clip")) {
                clipPicker.choose()
            }
            if own.clip != nil {
                Button(AppLocalized("Default face")) { own.clear() }
            }
            ForEach(NanoMuseMood.allCases, id: \.self) { mood in
                HStack {
                    Text({
                        switch mood {
                        case .idle: return AppLocalized("Idle")
                        case .working: return AppLocalized("Working")
                        case .waiting: return AppLocalized("Waiting")
                        case .happy: return AppLocalized("Done")
                        case .error: return AppLocalized("Error")
                        }
                    }())
                    Spacer()
                    Button(own.moods[mood] == nil ? AppLocalized("Choose a clip") : AppLocalized("Replace the clip")) {
                        clipPicker.choose(mood: mood)
                    }
                    if own.moods[mood] != nil {
                        Button(AppLocalized("Remove")) { own.clear(mood: mood) }
                    }
                }
            }
        } header: {
            Text(AppLocalized("Your own clip"))
        } footer: {
            VStack(alignment: .leading, spacing: 6) {
                Text(own.clip != nil
                     ? AppLocalized("Your clip is on and plays for every mood; the drawn stills still show where a still is used. Default face removes it.")
                     : AppLocalized("A short video of yours plays as the face at rest, and the other moods fall back to it. MP4 or MOV with H.264 or HEVC video, up to 15 seconds and 30 MB; it plays muted in a loop."))
                Text(AppLocalized("The clip stays on this phone. It is not uploaded to nanoMuse Cloud or synced to your other devices."))
            }
        }
    }

    /// The line beside the current face: the drawn face's description, else what an emoji
    /// look is (#435), else the dragon.
    private var currentTitle: String {
        switch faces.source {
        case .drawn: return faces.meta.description
        case .emoji: return AppLocalized("An emoji set on another device")
        case .dragon: return AppLocalized("The built-in dragon")
        }
    }

    private var currentSection: some View {
        Section {
            HStack(spacing: 16) {
                NanoMuseFaceView(mood: .idle, size: 72)
                VStack(alignment: .leading, spacing: 4) {
                    Text(currentTitle)
                        .font(.body.weight(.semibold))
                        .lineLimit(2)
                    if faces.hasCustomFace {
                        Text(NanoMuseAvatarStyle(rawValue: faces.meta.style)?.label ?? faces.meta.style)
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                }
                Spacer()
            }
            .padding(.vertical, 4)
            // nanoMuse: the clips being drawn, or the last failure, one line (contract C3)
            if let line = motion.statusLine {
                HStack(spacing: 10) {
                    ProgressView()
                    Text(line).font(.footnote).foregroundStyle(.secondary)
                }
            } else if let note = motion.progress?.error {
                Text(note).font(.footnote).foregroundStyle(.secondary)
            }
            if faces.hasCustomFace, !studio.isBusy {
                HStack(spacing: 10) {
                    ForEach(NanoMuseMood.allCases, id: \.self) { mood in
                        NanoMuseFaceView(mood: mood, size: 40, showsRing: false)
                            .opacity(faces.custom[mood] == nil ? 0.4 : 1)
                    }
                }
                Button(AppLocalized("Redraw the moods")) { studio.redrawMoods() }
                    .disabled(studio.cannotDrawReason != nil)
                if motion.progress == nil, NanoMuseMediaModels.videoEndpoint() != nil {
                    Button(motion.clips.isEmpty ? AppLocalized("Animate the moods") : AppLocalized("Redo the clips")) {
                        Task { await motion.animateAll(force: true) }
                    }
                }
                Button(AppLocalized("Back to the built-in face"), role: .destructive) { confirmReset = true }
            }
        }
    }

    private var describeSection: some View {
        Section {
            Text(AppLocalized("AI-generated inspiration"))
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.secondary)
                .textCase(.uppercase)
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 10) {
                    ForEach(NanoMuseAvatarPreset.all) { preset in
                        Button {
                            studio.description = preset.description
                            studio.style = preset.style
                        } label: {
                            VStack(alignment: .leading, spacing: 3) {
                                if let image = UIImage(named: "preset-\(preset.id)") {
                                    Image(uiImage: image)
                                        .resizable()
                                        .scaledToFill()
                                        .frame(width: 112, height: 112)
                                        .clipShape(RoundedRectangle(cornerRadius: 18))
                                        .overlay {
                                            if studio.description == preset.description {
                                                RoundedRectangle(cornerRadius: 18)
                                                    .stroke(NanoMuseTones.action, lineWidth: 3)
                                            }
                                        }
                                }
                                Text(preset.name).font(.caption.weight(.semibold)).lineLimit(1)
                                Text(preset.style.label).font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                            }
                            .frame(width: 112, alignment: .leading)
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("\(preset.name), \(preset.style.label)")
                    }
                }
                .padding(.vertical, 2)
            }
            TextField(AppLocalized("Describe a new face"), text: $studio.description, axis: .vertical)
                .lineLimit(2...5)
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(NanoMuseAvatarStyle.allCases) { style in
                        Button {
                            studio.style = style
                        } label: {
                            Text(style.label)
                                .font(.footnote.weight(.medium))
                                .padding(.horizontal, 12)
                                .padding(.vertical, 7)
                                .background(studio.style == style ? NanoMuseTones.action : NanoMuseTones.fill, in: Capsule())
                                .foregroundStyle(studio.style == style ? Color.white : Color.primary)
                        }
                        .buttonStyle(.plain)
                    }
                }
                .padding(.vertical, 2)
            }
            if let reason = studio.cannotDrawReason {
                Text(reason)
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            } else {
                Button {
                    if studio.usesOwnKey {
                        studio.draw()
                    } else {
                        studio.refreshEstimate()
                        askCost = true
                    }
                } label: {
                    Label(AppLocalized("Draw four"), systemImage: "paintbrush")
                }
                .disabled(studio.description.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        } header: {
            Text(AppLocalized("Describe a new face"))
        } footer: {
            Text(AppLocalized("One sentence is enough: what it is, what it wears, what it feels like. Pick a style, and four takes are drawn for you to choose from."))
        }
    }

    private var pickSection: some View {
        Section {
            if studio.phase == .drawing {
                HStack(spacing: 12) {
                    ProgressView()
                    Text(String(format: AppLocalized("Drawing four takes on \"%@\"…"), NanoMuseStatus.requestBrief(studio.description) ?? ""))
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            LazyVGrid(columns: [GridItem(.flexible(), spacing: 12), GridItem(.flexible(), spacing: 12)], spacing: 12) {
                ForEach(Array(studio.candidates.enumerated()), id: \.element.id) { index, candidate in
                    Button {
                        if candidate.image != nil { studio.selected = index }
                    } label: {
                        ZStack {
                            RoundedRectangle(cornerRadius: 16, style: .continuous)
                                .fill(NanoMuseTones.fill)
                            if let image = candidate.image {
                                Image(uiImage: image)
                                    .resizable()
                                    .scaledToFill()
                                    .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                            } else if candidate.drawing {
                                ProgressView()
                            } else {
                                VStack(spacing: 6) {
                                    Image(systemName: "exclamationmark.triangle").foregroundStyle(.secondary)
                                    Button(AppLocalized("Retry")) { studio.retry(index) }
                                        .font(.footnote)
                                }
                            }
                        }
                        .aspectRatio(1, contentMode: .fit)
                        .overlay {
                            RoundedRectangle(cornerRadius: 16, style: .continuous)
                                .strokeBorder(studio.selected == index ? NanoMuseTones.action : Color.clear, lineWidth: 3)
                        }
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(Text(String(format: AppLocalized("Option %d"), index + 1)))
                }
            }
            .padding(.vertical, 4)
            if studio.phase == .pick {
                Button {
                    studio.adopt()
                } label: {
                    Label(AppLocalized("Use this one"), systemImage: "checkmark")
                }
                .disabled(studio.selected == nil)
                Button(AppLocalized("Draw four more")) {
                    if studio.usesOwnKey {
                        studio.draw()
                    } else {
                        studio.refreshEstimate()
                        askCost = true
                    }
                }
                Button(AppLocalized("Keep current"), role: .cancel) { studio.backToDescribe() }
            }
        } header: {
            Text(AppLocalized("Pick one"))
        } footer: {
            Text(AppLocalized("The moods are drawn from the one you pick, in the background: working, waiting, done, oops."))
        }
    }
}

// MARK: - Cost sheet

struct NanoMuseFaceCostSheet: View {
    @ObservedObject var studio: NanoMuseAvatarStudioModel
    var onDraw: () -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(AppLocalized("Before drawing")).font(.title3.weight(.semibold))
            let what = studio.costWhat
            if studio.estimating {
                HStack(spacing: 10) {
                    ProgressView()
                    Text(AppLocalized("Checking today's allowance…")).foregroundStyle(.secondary)
                }
            } else if let e = studio.estimate {
                if e.unlimited {
                    Text(what + ".")
                } else {
                    Text(String(format: AppLocalized("%@: about ¥%@ from your allowance."), what, Self.money(e.cny)))
                    if let left = e.leftCny {
                        Text(String(format: AppLocalized("You have ¥%@ of the allowance left."), Self.money(left)))
                            .foregroundStyle(.secondary)
                    }
                    if !e.affordable {
                        Text(AppLocalized("That is more than what is left. Invite a friend for more allowance, or wait for tomorrow's share."))
                            .foregroundStyle(.red)
                            .font(.footnote)
                    }
                }
            } else {
                Text(String(format: AppLocalized("%@. Today's allowance could not be checked right now."), what))
                if let err = studio.estimateError {
                    Text(err).font(.footnote).foregroundStyle(.secondary)
                }
            }
            Spacer(minLength: 0)
            Button {
                onDraw()
            } label: {
                Text(studio.estimate?.affordable == false ? AppLocalized("Try anyway") : AppLocalized("Draw it"))
                    .font(.body.weight(.semibold))
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 12)
            }
            .buttonStyle(.borderedProminent)
            .tint(NanoMuseTones.action)
            .disabled(studio.estimating)
            Button(AppLocalized("Not now")) { dismiss() }
                .frame(maxWidth: .infinity)
        }
        .padding(22)
    }

    static func money(_ v: Double) -> String {
        if v == v.rounded() { return String(format: "%.0f", v) }
        return String(format: "%.2f", v)
    }
}

// MARK: - Image model (own key)

/// Which Bailian instance and model draw the face, when a key is on this phone.
struct NanoMuseImageModelPicker: View {
    @State private var instances: [ProviderInstance] = []
    @State private var instanceId: String = ""
    @State private var model: String = ""

    var body: some View {
        Form {
            Section {
                Picker(AppLocalized("Provider"), selection: $instanceId) {
                    ForEach(instances) { inst in Text(inst.label).tag(inst.id) }
                }
                .nmOnChange(of: instanceId) { _ in
                    if let inst = instances.first(where: { $0.id == instanceId }) { model = NanoMuseImageGen.suggestedModel(for: inst) }
                }
                if let inst = instances.first(where: { $0.id == instanceId }) {
                    Picker(AppLocalized("Image model"), selection: $model) {
                        ForEach(NanoMuseImageGen.availableModels(for: inst), id: \.self) { Text($0).tag($0) }
                    }
                }
            } footer: {
                Text(AppLocalized("Drawn through Model Studio's native image endpoint with the same key. qwen-image-3.0 is about ¥0.18 a picture."))
            }
        }
        .navigationTitle(AppLocalized("Image model"))
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            instances = NanoMuseImageGen.bailianInstances()
            if case .ownKey(let k) = NanoMuseImageGen.route() {
                instanceId = k.instanceId
                model = k.model
            } else if let first = instances.first {
                instanceId = first.id
                model = NanoMuseImageGen.suggestedModel(for: first)
            }
        }
        .onDisappear {
            guard !instanceId.isEmpty, !model.isEmpty else { return }
            NanoMuseImageGen.save(instanceId: instanceId, model: model)
        }
    }
}
