// nanoMuse: new file — carries a "start voice input" request from the
// VoicePromptIntent (Shortcuts / Action Button) to the chat surface.
//
// The intent cannot drive the voice panel itself: it runs before the window
// exists, and SwiftUI owns the panel's lifecycle. So it leaves a marker here
// and the chat surface consumes it once it is on screen — the same pattern
// `NotificationNavigationStore` uses for notification taps and deep links.
//
// A pending request is also what makes the cold-launch path work: the intent
// may be what launched the app, so nothing is on screen yet when `perform()`
// writes the marker.

import Foundation
import Combine

/// One pending "open voice input" request, optionally bound to a session.
struct VoicePromptRequest: Equatable {
    /// Session to continue, or nil for a new one.
    var sessionId: String?
    /// Monotonic token so a repeat request within the same session still
    /// notifies observers (Equatable alone would swallow an identical second
    /// request — pressing the Action Button twice must start listening twice).
    var token: UUID
}

@MainActor
final class VoicePromptRequestStore: ObservableObject {
    static let shared = VoicePromptRequestStore()

    /// Non-nil while a voice request is waiting to be picked up.
    ///
    /// Published so a session view already on screen reacts immediately;
    /// a view that appears later reads the same value on `onAppear`.
    @Published private(set) var pending: VoicePromptRequest?

    private init() {}

    /// Records a request. Called from `VoicePromptIntent.perform()`.
    func request(sessionId: String?) {
        pending = VoicePromptRequest(sessionId: sessionId, token: UUID())
    }

    /// Returns the pending request and clears it, so a single request drives
    /// exactly one listening session. Called by the chat surface when it is
    /// ready to act on it.
    func consume() -> VoicePromptRequest? {
        defer { pending = nil }
        return pending
    }

    /// Drops a request that can no longer be honoured (e.g. the target session
    /// was deleted while the app was opening) without entering voice input.
    func discard() {
        pending = nil
    }
}