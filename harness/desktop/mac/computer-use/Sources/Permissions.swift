// The two TCC grants, as this process sees them — which is the point: the grant is ours,
// not the Electron app's.

import AppKit
import ApplicationServices
import CoreGraphics
import Foundation

enum Permissions {
    enum ScreenState: String {
        case granted
        case denied
        case unknown
    }

    /// The capture layer's verdict is kept this long: `/status` is read every two seconds
    /// and a ScreenCaptureKit listing is a round trip to the window server.
    private static let probeKeep: TimeInterval = 3
    private static var probedAt: Date = .distantPast
    private static var probed: (ScreenState, String) = (.unknown, "")
    private static let lock = NSLock()

    /// Screen Recording, truthfully: `CGPreflightScreenCaptureAccess` first (TCC's own
    /// answer, no prompt) — a `false` is `denied`. A `true` is confirmed with the capture
    /// layer on macOS 14 and later (ScreenCapture.probe: `SCShareableContent` throwing
    /// `userDeclined` means the grant is not there, whatever the preflight said), so
    /// `granted` means a screenshot will come back; an SCK error that is not a refusal is
    /// `unknown`, with the reason in `screenDetail`.
    static func screenState() -> ScreenState {
        screenStateAndDetail().0
    }

    /// The last reason behind an `unknown` or an SCK `denied` ("" when granted outright).
    static func screenDetail() -> String {
        screenStateAndDetail().1
    }

    private static func screenStateAndDetail() -> (ScreenState, String) {
        guard CGPreflightScreenCaptureAccess() else { return (.denied, "") }
        lock.lock()
        defer { lock.unlock() }
        if Date().timeIntervalSince(probedAt) < probeKeep {
            return probed
        }
        switch ScreenCapture.probe() {
        case .granted:
            probed = (.granted, "")
        case .denied(let text):
            probed = (.denied, text)
        case .unknown(let text):
            probed = (.unknown, text)
        }
        probedAt = Date()
        return probed
    }

    /// Forget the cached verdict (after a `/request`, so the next `/status` reads it afresh).
    static func forgetProbe() {
        lock.lock()
        probedAt = .distantPast
        lock.unlock()
    }

    static func accessibilityGranted() -> Bool {
        AXIsProcessTrusted() && CGPreflightPostEventAccess()
    }

    /// The system's own request: its dialog the first time, and this app on the pane's list.
    /// Both calls return at once; the dialog is tccd's. On the main thread, where UI belongs.
    static func request(_ what: String) {
        DispatchQueue.main.sync {
            if what == "screen" {
                // Active first: tccd has been seen to show the Screen Recording dialog for a
                // request from a backgrounded process and still leave the process off the
                // pane's list (Omi's PERM-02). This app is started with `open -g`, so it is in
                // the background until it asks; an accessory app is active without a window.
                NSApp.activate(ignoringOtherApps: true)
                // the result is the current grant, which /status reports — the call is for the prompt
                _ = CGRequestScreenCaptureAccess()
            } else {
                let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
                if AXIsProcessTrustedWithOptions(options) && !CGPreflightPostEventAccess() {
                    _ = CGRequestPostEventAccess()
                }
            }
        }
        forgetProbe()
    }

    /// System Settings → Privacy & Security, at the pane where the switch is.
    static func openPane(_ what: String) {
        let pane = what == "screen" ? "Privacy_ScreenCapture" : "Privacy_Accessibility"
        guard let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?\(pane)") else { return }
        DispatchQueue.main.async {
            _ = NSWorkspace.shared.open(url)
        }
    }
}
