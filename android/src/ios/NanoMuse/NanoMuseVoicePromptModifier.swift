// nanoMuse: new file — the chat surface's consumer for VoicePromptRequestStore.
//
// `VoicePromptIntent` leaves a request; this turns it into a live voice-input
// session by driving the SAME `VoiceInputViewModel` the composer's mic button
// uses. No second recording path, no second transcription stack: the panel is
// still the single voice entry point (see the note on `MicButton` in
// AIChatView.swift), this only presses its button for the user.
//
// Attach to the session view:
//
//   .nanoMuseVoicePrompt(onTranscript: { vm.inputText = $0 })
//
// The transcript is delivered through the panel's existing `onTranscript`
// callback and written into `AIChatViewModel.inputText`. Sending stays a
// deliberate tap: a spoken prompt that fires the agent the instant the VAD
// hears a pause would be a destructive-by-default surprise, and the app's
// standing rule is to ask before anything the user cannot undo.

import SwiftUI

extension View {
    /// Wires the VoicePromptIntent request into the chat surface's voice panel.
    ///
    /// - Parameters:
    ///   - viewModel: the chat model the transcript is written into.
    ///   - isEnabled: false when the session cannot accept voice input (for
    ///     example while the agent is mid-run). The request is dropped rather
    ///     than queued, so an action-button press never lands in the wrong turn.
    func nanoMuseVoicePrompt(
        viewModel: AIChatViewModel,
        isEnabled: Bool = true
    ) -> some View {
        modifier(NanoMuseVoicePromptModifier(viewModel: viewModel, isEnabled: isEnabled))
    }
}

private struct NanoMuseVoicePromptModifier: ViewModifier {
    @ObservedObject var viewModel: AIChatViewModel
    @ObservedObject private var store = VoicePromptRequestStore.shared
    let isEnabled: Bool

    /// The panel's view model. Owned here rather than by the composer because
    /// the shortcut may start a listening session the user never opened the
    /// panel for; the composer adopts this instance when the panel is shown.
    @StateObject private var voicePanel = VoiceInputViewModel()

    /// Set once a request has been honoured, so the same request cannot start
    /// listening twice (both the `onChange` and `onAppear` paths can fire).
    @State private var honouredToken: UUID?

    func body(content: Content) -> some View {
        content
            .onAppear { consumeIfPending() }
            .onChange(of: store.pending) { _, _ in consumeIfPending() }
    }

    private func consumeIfPending() {
        guard let request = store.pending else { return }
        guard request.token != honouredToken else { return }
        guard isEnabled else {
            // Cannot honour it here (mid-run, or wrong session). Drop it so it
            // does not fire later against an unrelated conversation.
            store.discard()
            return
        }

        honouredToken = request.token
        _ = store.consume()

        // Same callback the mic button's panel installs. The panel writes the
        // final transcript; we land it in the composer and leave sending to the
        // user.
        voicePanel.onTranscript = { text in
            let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty else { return }
            viewModel.inputText = trimmed
            // Remember that this composition was spoken, matching the mic
            // button's behaviour so the composer's mode preference stays honest.
            SpeechRecognitionManager.saveInputModePreference("voice")
        }

        voicePanel.prepare()
        voicePanel.handleMainButtonTap()
    }
}