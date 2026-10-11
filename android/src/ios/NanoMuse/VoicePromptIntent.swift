//
//  VoicePromptIntent.swift
//  nanoMuse
//
//  The Action Button's way in (#296): a Shortcut that opens the app and starts voice input,
//  so a prompt can be spoken instead of typed. Bound once in Shortcuts, it sits on the Action
//  Button, on Back Tap or on a widget; one press and the composer is listening, and what is
//  said lands in the composer. Sending stays a tap: a sentence the recogniser misheard must
//  not start the agent on a pause.
//
//  Why the app opens: iOS gives an App Intent no way to take free-form speech (the phrase a
//  Shortcut is called by is fixed), and a microphone running with nothing on screen would
//  read as a fault. `SendPromptIntent` and `AskMinisIntent` take a typed prompt; this one
//  takes none and hands the chat the job of listening.
//
//  The intent cannot drive the voice panel itself: it runs before the window exists on a
//  cold start, and SwiftUI owns the panel. It leaves a request in `NanoMuseVoicePrompt`;
//  the chat on screen picks it up (`NanoMuseChatHooks`) and presses the composer's own mic,
//  so there is one recording path and one transcription stack. Registered in Shortcuts by
//  `MinisShortcutsProvider`, with its phrases in the `AppShortcuts.strings` tables.
//

import AppIntents
import Foundation

private let logger = AppLogger(category: "VoicePromptIntent")

/// Opens nanoMuse and starts voice input in a chat.
struct VoicePromptIntent: AppIntent {
    static var title: LocalizedStringResource = "Voice Prompt"
    static var description = IntentDescription(
        "Opens nanoMuse and starts listening. What you say lands in the composer; you send it with a tap."
    )

    /// Listening needs the panel on screen (see the file header).
    static var openAppWhenRun = true

    @Parameter(
        title: "Session",
        description: "Existing session to continue. Leave empty for the chat that is open."
    )
    var session: SessionEntity?

    static var parameterSummary: some ParameterSummary {
        Summary("Voice prompt to nanoMuse") {
            \.$session
        }
    }

    @MainActor
    func perform() async throws -> some IntentResult {
        let target = session?.id
        NanoMuseVoicePrompt.shared.request(session: target)
        if let sid = target, !sid.isEmpty {
            // The route a notification tap and "Ask nanoMuse" already take: the buffer for a
            // cold launch, the event for an app that is running (ContentView and the Muse shell
            // both listen). The chat that comes up then finds the request addressed to it.
            NotificationNavigationStore.shared.setPending(sid)
            NotificationCenter.default.post(
                name: .openSessionFromIntent,
                object: nil,
                userInfo: ["sessionId": sid]
            )
        }
        logger.info("voice prompt requested session=\(target?.prefix(8) ?? "open chat")")
        return .result()
    }
}
