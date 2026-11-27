//
//  NanoMuseAvatarMotion.swift
//  nanoMuse
//
//  The face in motion: one short looping clip per mood, drawn from that
//  mood's pose by the video model — Muse's fixed set: a head shake and a
//  sway at rest, the crystal ball while waiting, the five-pointed star when
//  pleased, headphones and a laptop while working. Clips live next to the
//  pictures (`avatar/motion/<mood>.mp4`) and the face view plays whichever
//  exists for the current mood, falling back to the still. Clips are made
//  one after another (each takes a few minutes and costs the person per
//  second) and only when a video model is set and the animation is on. A clip
//  drawn here goes to the account's other devices through the profile's `clips`
//  (relay 0.29, NanoMuseProfileSync), and theirs land here, so a face is
//  animated once per account, not once per device. Android: avatar/AvatarMotion.kt.
//

import Foundation
import SwiftUI
import UIKit

@MainActor
final class NanoMuseAvatarMotion: ObservableObject {
    static let shared = NanoMuseAvatarMotion()

    /// Clip length, seconds. Wan 2.2 Flash has a fixed length; the others take this.
    nonisolated static let seconds = 4
    /// The moods that get a clip, in the order they are drawn: the one seen most first. Not `error`.
    nonisolated static let animated: [NanoMuseMood] = [.idle, .working, .waiting, .happy]

    struct Progress: Equatable {
        var done: Int
        var total: Int
        var failed: [NanoMuseMood]
        var running: Bool
        var current: NanoMuseMood?
        var stage: NanoMuseVideoGen.Progress?
        var error: String?
    }

    @Published private(set) var progress: Progress?
    /// The clips on disk, by mood.
    @Published private(set) var clips: [NanoMuseMood: URL] = [:]
    /// Bumped whenever a clip file is written or removed, so a player on the same path is rebuilt.
    @Published private(set) var clipVersion = 0

    private var job: Task<Void, Never>?

    private init() {
        rescan()
    }

    // MARK: Paths

    nonisolated static var directory: URL {
        NanoMuseFaceStore.directory.appendingPathComponent("motion", isDirectory: true)
    }

    nonisolated static func clipFile(_ mood: NanoMuseMood) -> URL {
        directory.appendingPathComponent("\(mood.rawValue).mp4")
    }

    /// The bundled dragon's clip for a mood (`dragon-<mood>.mp4`), when the bundle has it.
    nonisolated static func dragonClip(_ mood: NanoMuseMood) -> URL? {
        Bundle.main.url(forResource: "dragon-\(mood.rawValue)", withExtension: "mp4")
    }

    func rescan() {
        var found: [NanoMuseMood: URL] = [:]
        for mood in NanoMuseMood.allCases {
            let url = Self.clipFile(mood)
            if let size = (try? FileManager.default.attributesOfItem(atPath: url.path))?[.size] as? NSNumber, size.intValue > 0 {
                found[mood] = url
            }
        }
        clips = found
    }

    // MARK: State

    /// "Animating 2/4…" while clips are drawn; nil otherwise.
    var statusLine: String? {
        guard let p = progress, p.running else { return nil }
        return String(format: AppLocalized("Animating %d/%d…"), min(p.done + 1, p.total), p.total)
    }

    /// True when a video model is set and the person has not turned the animation off.
    var enabled: Bool { NanoMuseMediaModels.animateAvatar && NanoMuseMediaModels.videoEndpoint().map { $0.studioURL == nil } == true }

    /// A new face, or none: the old clips belonged to the old face.
    func clear() {
        job?.cancel()
        job = nil
        progress = nil
        try? FileManager.default.removeItem(at: Self.directory)
        clipVersion += 1
        rescan()
    }

    func cancel() {
        job?.cancel()
        job = nil
        if var p = progress { p.running = false; progress = p }
    }

    func clearProgress() {
        if progress?.running == false { progress = nil }
    }

    /// A clip another device drew arrived as a file (NanoMuseProfileSync): the players rebuild.
    func clipLanded() {
        clipVersion += 1
        rescan()
    }

    /// After a face was adopted or arrived from the profile: the clips, in the background, when enabled.
    func animateIfEnabled() {
        guard enabled else { return }
        Task { @MainActor [self] in await animateAll() }
    }

    /// Draws the missing clips (all of them with `force`), one after another. No-op without a
    /// custom face or a video model. Returns when the run is over; partial sets are fine.
    @discardableResult
    func animateAll(force: Bool = false) async -> Bool {
        guard let ep = NanoMuseMediaModels.videoEndpoint(), ep.studioURL == nil else { return false }
        let store = NanoMuseFaceStore.shared
        guard store.hasCustomFace else { return false }
        if progress?.running == true { return false }
        let todo = Self.animated.filter { force || clips[$0] == nil }
        if todo.isEmpty { return false }
        job?.cancel()
        progress = Progress(done: 0, total: todo.count, failed: [], running: true)
        let run = Task { @MainActor [self] in
            var failed: [NanoMuseMood] = []
            var lastError: String?
            for (i, mood) in todo.enumerated() {
                if Task.isCancelled { break }
                progress = Progress(done: i, total: todo.count, failed: failed, running: true, current: mood)
                guard let frame = store.custom[mood] ?? store.custom[.idle] else {
                    failed.append(mood)
                    continue
                }
                do {
                    let bytes = try await NanoMuseVideoGen.imageToVideo(ep, image: frame, prompt: Self.motionPrompt(mood), seconds: Self.seconds) { stage in
                        Task { @MainActor in
                            guard var p = self.progress, p.running else { return }
                            p.stage = stage
                            self.progress = p
                        }
                    }
                    if Task.isCancelled { break }
                    try FileManager.default.createDirectory(at: Self.directory, withIntermediateDirectories: true)
                    try bytes.write(to: Self.clipFile(mood), options: .atomic)
                    clipVersion += 1
                    rescan()
                    // the account's other devices get the clip instead of drawing their own (relay 0.29)
                    NanoMuseProfileSync.shared.shareClip(mood, bytes: bytes)
                } catch is CancellationError {
                    break
                } catch {
                    failed.append(mood)
                    lastError = error.localizedDescription
                }
            }
            progress = Progress(done: todo.count, total: todo.count, failed: failed, running: false, error: lastError)
        }
        job = run
        await run.value
        return true
    }

    // MARK: Prompts

    /// Muse's fixed motions, one per mood, on top of the pose picture. The same words as Android.
    nonisolated static func motionPrompt(_ mood: NanoMuseMood) -> String {
        let action: String
        switch mood {
        case .idle:
            action = "The character stays in place and gently shakes its head left and right while its round body sways very slightly, calm and friendly, like the idle animation of a mascot."
        case .waiting:
            action = "The character holds a small glowing crystal ball in its hands and plays with it, turning it slowly and peeking into it with curiosity."
        case .happy:
            action = "The character plays happily with a small golden five-pointed star, tossing it up a little and catching it, bouncing gently with joy."
        case .working:
            action = "The character wears headphones and types busily on the small laptop in front of it, nodding slightly to the rhythm, focused and content."
        case .error:
            action = "The character looks a little flustered, a sweat drop on its brow, then takes a breath and settles."
        }
        return "\(action) Plain white background, static camera, no zoom, no cuts, soft even studio lighting, the same 3D toy look as the picture throughout, "
            + "nothing else appears in the frame, and the motion loops naturally with the character back in its starting pose at the end."
    }
}
