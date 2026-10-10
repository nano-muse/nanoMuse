// nanoMuse: new file — iOS voice-input shortcut entry point.
//
// Adds a Shortcuts / Action-Button / Back-Tap trigger that opens the app and
// drops straight into voice capture, so a prompt can be spoken instead of
// typed. This is the missing half of #296: `SendPromptIntent` already carries
// a prompt to the agent, but its `prompt` parameter is a plain `String` — in
// the Action-Button flow the user has to type it, and Siri's
// `requestValueDialog` follow-up is a poor fit for Chinese.
//
// Shape of the flow:
//
//   Action Button / Back Tap / Shortcuts
//     → VoicePromptIntent (openAppWhenRun = true)
//     → opens the app and asks the chat surface to enter voice input
//     → the user speaks; the existing VAD panel transcribes
//     → the transcript lands in the composer; sending stays a deliberate tap
//
// Why the app opens rather than running headless: iOS gives an App Intent no
// way to capture free-form speech, and a headless intent that opened the mic
// without a visible speaking surface would be indistinguishable from a bug.
// Opening the app also means the user sees and can correct the transcript
// before it is sent — the same "asks first" discipline the rest of the app
// follows. No new send pipeline is introduced: the transcript goes into
// `AIChatViewModel.inputText` through the same voice panel path the composer's
// mic button uses.

import AppIntents
import Foundation

private let logger = AppLogger(category: "VoicePromptIntent")

/// Opens nanoMuse and enters voice input for a new (or existing) session.
///
/// Intended for the iOS Action Button, Back Tap, and Shortcuts widgets: one
/// press starts listening, and the spoken prompt lands in the composer.
struct VoicePromptIntent: AppIntent {
    static var title: LocalizedStringResource = "Voice Prompt"
    static var description = IntentDescription(
        "Opens nanoMuse and starts voice input. Speak your prompt; it lands in the composer ready to send."
    )

    // Voice capture needs the app on screen — see the file header.
    static var openAppWhenRun = true

    @Parameter(
        title: "Session",
        description: "Existing session to continue. Leave empty to start a new session."
    )
    var session: SessionEntity?

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        // Same eager keep-alive discipline as AskMinisIntent / SendPromptIntent:
        // arm before any await so an intent-woken process is not suspended
        // before the chat surface takes over. No-op unless
        // enhancedBackgroundEffective is on.
        BackgroundKeepAliveManager.shared.setup()

        let targetSid = session?.id

        // Hand the request to the chat surface. The app is opening anyway
        // (openAppWhenRun), so the marker is read by whichever session view
        // comes up — cold launch included, via the pending-request store.
        VoicePromptRequestStore.shared.request(sessionId: targetSid)

        logger.info("VoicePrompt requested sid=\(targetSid?.prefix(8) ?? "new")")

        return .result(
            dialog: targetSid == nil
                ? IntentDialog(stringLiteral: AppLocalized("Listening — speak your prompt."))
                : IntentDialog(stringLiteral: AppLocalized("Listening — continue the conversation."))
        )
    }

    // As with SendPromptIntent, the summary is what makes the action card
    // render with an inline editor instead of a bare title. Voice capture
    // needs no prompt field, so `session` is the only thing surfaced.
    static var parameterSummary: some ParameterSummary {
        Summary("Voice prompt to nanoMuse") {
            \.$session
        }
    }
}