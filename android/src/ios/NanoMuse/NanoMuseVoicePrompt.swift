//
//  NanoMuseVoicePrompt.swift
//  nanoMuse
//
//  Carries one "start voice input" request from `VoicePromptIntent` (the Action Button, Back
//  Tap, a Shortcut) to the chat that should listen, and starts the listening there.
//
//  The intent runs before the window exists on a cold start and SwiftUI owns the voice
//  panel, so it leaves a request here and the chat consumes it once it is on screen: the
//  pattern `NotificationNavigationStore` uses for notification taps. A request names a
//  session, or nothing; a request for nothing is for the chat that is open. In the Muse
//  shell that is the main chat: the shell aims the request at it (`NanoMuseHomeView`) so
//  that the main chat, and not a side chat that happens to be pushed over it, takes it.
//  In upstream's layout the chat that is mounted takes it.
//
//  Honouring a request is the mic button's path, nothing else: the composer switches to the
//  inline voice panel the way a tap on the mic does, and once the panel is up its mic is
//  pressed, through the same permission flow (`VoiceInputViewModel.handleMainButtonTap`
//  asks for the microphone and for speech recognition when they were never granted, and
//  shows the panel's refusal when they were denied). The transcript reaches the composer the
//  way it always does (the panel mirrors it into `inputText`); nothing is sent.
//

import Combine
import Foundation

/// One press: "listen in this chat".
struct NanoMuseVoicePromptRequest: Equatable {
    /// The session it is for, or nil for the chat that is open.
    var session: String?
    /// Two presses are two requests, even for the same chat.
    let token = UUID()
}

@MainActor
final class NanoMuseVoicePrompt: ObservableObject {
    static let shared = NanoMuseVoicePrompt()

    /// Non-nil while a request waits for its chat.
    @Published private(set) var pending: NanoMuseVoicePromptRequest?
    private var requestedAt: Date?

    /// A request older than this is dropped unanswered: the app took too long to come up, or
    /// the chat it named never did. Long enough for a cold start on an old phone.
    static let staleAfter: TimeInterval = 30

    private init() {}

    /// Called from `VoicePromptIntent.perform()`.
    func request(session: String?) {
        requestedAt = Date()
        pending = NanoMuseVoicePromptRequest(session: session)
    }

    /// The shell names the chat a request without one is for (its main chat).
    func aim(at session: String) {
        guard var request = pending, request.session == nil else { return }
        request.session = session
        pending = request
    }

    /// The chat `key` takes the request meant for it, once; `unaddressed` says whether a
    /// request that names no chat is for this one.
    func take(for key: String, unaddressed: Bool) -> Bool {
        guard let request = pending else { return false }
        if let at = requestedAt, Date().timeIntervalSince(at) > Self.staleAfter {
            pending = nil
            return false
        }
        guard request.session == key || (request.session == nil && unaddressed) else { return false }
        pending = nil
        return true
    }

    /// Listening in the chat that took a request: into voice mode the way the mic button goes
    /// (`enterVoice` is the chat's switch), then the panel's own mic once the panel is up.
    /// `InlineVoiceInputView.onAppear` prepares the model (the provider, the permission state)
    /// on the render that shows it, so the press waits for that render; a panel that is
    /// already listening is left alone.
    static func listen(with voice: VoiceInputViewModel, enterVoice: () -> Void) {
        let mode = VoiceModePreference.shared
        if !mode.isVoiceActive { enterVoice() }
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: 500_000_000)
            guard mode.isVoiceActive, !mode.isCapturing else { return }
            voice.handleMainButtonTap()
        }
    }
}
