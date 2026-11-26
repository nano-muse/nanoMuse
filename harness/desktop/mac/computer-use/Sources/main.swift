// nanoMuse Computer Use — the small macOS app that holds the hands' two permissions.
//
// macOS grants Screen Recording and Accessibility to the *responsible process*: whatever
// LaunchServices started. A child process the desktop app spawns is attributed to the app;
// this bundle, started through `open`, is responsible for itself, so the panes list
// "nanoMuse Computer Use" and the app itself never holds either grant. (Qt's write-up "The
// Curious Case of the Responsible Process" explains the attribution; the same arrangement
// is what Codex's "Codex Computer Use.app" does.)
//
// What it does: a loopback HTTP server the Electron shell talks to (src/mac-helper.ts), with
// a token read from a file the shell writes, the bound port written back to a file:
//
//   GET  /status       → { screen: "granted"|"denied"|"unknown", screen_detail, capture, accessibility: bool,
//                          pid, version, display } — `capture` is "ScreenCaptureKit" (macOS 14+) or "CoreGraphics"
//   POST /request      { what: "screen"|"accessibility", pane?: bool } → the system's dialog, the pane
//   POST /screenshot   { width?, height?, max_pixels?, format?: "png"|"jpeg", quality? }
//                      → { base64, mime, width, height, screen: { width, height }, scale, capture }
//   GET  /windows      → { windows: [{ id, pid, app, bundle_id, title, bounds: [x, y, w, h], layer, on_screen }] }
//                      the windows on screen, front to back — the runtime's window mode lists them here
//   POST /window       { id, max_pixels?, format?: "png"|"jpeg", quality? }
//                      → { base64, mime, width, height, window: { id, x, y, width, height }, scale, capture }
//                      one window's own pixels (no shadow) and its frame in points; 404 when it is gone
//   POST /execute      { action, x?, y?, x2?, y2?, dy?, text?, submit?, clear?, keys?, seconds? }
//                      → { ok: true, note } — the operator's vocabulary, coordinates in points;
//                      `press` holds keys down across the actions that follow, `release` lets go
//   POST /quit         → { ok: true }, then the process ends
//
// Errors are 4xx/5xx with { error, message }: 403 `screen_denied` / `accessibility_denied`
// when a grant is missing, 500 `screenshot_failed` with the capture layer's own words
// (ScreenCapture.swift) when the picture could not be taken. The process ends by itself when
// the parent (--parent-pid) is gone, so a crashed shell leaves nothing behind.
//
// Arguments: --token-file <path>  --port-file <path>  --parent-pid <pid>  [--version]
// Built by build.sh with plain swiftc: Foundation, Network, CoreGraphics, AppKit,
// ScreenCaptureKit; no packages.

import AppKit
import Foundation

let arguments = CommandLine.arguments

func argument(_ name: String) -> String? {
    guard let index = arguments.firstIndex(of: name), index + 1 < arguments.count else { return nil }
    return arguments[index + 1]
}

let bundleVersion = (Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String) ?? "0"

if arguments.contains("--version") {
    print(bundleVersion)
    exit(0)
}

// The note a `down` leaves next to the shell's token file, so the button it never lifted can
// be lifted by the helper that comes after it (Input.swift, `Mouse.releaseStuck`).
func markerPath() -> URL? {
    guard let tokenFile = argument("--token-file") else { return nil }
    return URL(fileURLWithPath: tokenFile).deletingLastPathComponent().appendingPathComponent("mouse-held")
}
Mouse.marker = markerPath()

// `--release`: lift a button a killed helper left down, then leave. The shell calls this when
// the helper it had is gone; it needs no token and no listener.
if arguments.contains("--release") {
    Mouse.releaseStuck()
    exit(0)
}

// Buttons and keys a previous helper left down go up before this one starts serving.
Mouse.releaseStuck()

var token = ""
if let tokenFile = argument("--token-file"), let text = try? String(contentsOfFile: tokenFile, encoding: .utf8) {
    token = text.trimmingCharacters(in: .whitespacesAndNewlines)
}
if token.isEmpty {
    FileHandle.standardError.write(Data("nanoMuse Computer Use: --token-file <path> with a non-empty token is required\n".utf8))
    exit(2)
}

let service = Service(token: token, version: bundleVersion)
let queue = DispatchQueue(label: "io.github.nanomuse.desktop.computer-use.http")
func makeServer() -> HTTPServer {
    do {
        return try HTTPServer(queue: queue) { request in service.handle(request) }
    } catch {
        FileHandle.standardError.write(Data("nanoMuse Computer Use: no listener: \(error)\n".utf8))
        exit(1)
    }
}
let server = makeServer()

server.onReady = { port in
    let line = "{\"port\":\(port),\"pid\":\(getpid()),\"version\":\"\(bundleVersion)\"}"
    if let portFile = argument("--port-file") {
        do {
            // atomic, so the shell never reads a half-written file
            try Data((line + "\n").utf8).write(to: URL(fileURLWithPath: portFile), options: .atomic)
        } catch {
            FileHandle.standardError.write(Data("nanoMuse Computer Use: could not write \(portFile): \(error)\n".utf8))
        }
    }
    print(line)
    fflush(stdout)
}
server.onFailure = { message in
    FileHandle.standardError.write(Data("nanoMuse Computer Use: \(message)\n".utf8))
    exit(1)
}
server.start()

// The shell that started us: when it is gone, so are we (a crashed shell, a force quit).
// Kept in a global so the timer lives as long as the process.
let parentWatch: DispatchSourceTimer? = {
    guard let text = argument("--parent-pid"), let parent = Int32(text), parent > 1 else { return nil }
    let timer = DispatchSource.makeTimerSource(queue: DispatchQueue.global(qos: .utility))
    timer.schedule(deadline: .now() + 2, repeating: 2)
    timer.setEventHandler {
        if kill(parent, 0) != 0 && errno == ESRCH {
            // nothing of ours stays down when we go: the system would hold it for every app
            Mouse.releaseAll()
            Keyboard.releaseAll()
            exit(0)
        }
    }
    timer.resume()
    return timer
}()

// Being asked to stop (a restart in the shell, a `kill`) is still not a reason to leave a
// button down: SIGTERM, SIGINT and SIGHUP lift what this process put down, then leave.
// Held in a global: a source that goes away stops delivering.
let signalSources: [DispatchSourceSignal] = [SIGTERM, SIGINT, SIGHUP].map { number in
    signal(number, SIG_IGN)
    let source = DispatchSource.makeSignalSource(signal: number, queue: DispatchQueue.global(qos: .utility))
    source.setEventHandler {
        Mouse.releaseAll()
        Keyboard.releaseAll()
        exit(0)
    }
    source.resume()
    return source
}

// LSUIElement in Info.plist keeps us out of the Dock; the run loop is for the permission
// dialogs and NSWorkspace. Everything else happens on the server's queue.
let application = NSApplication.shared
_ = application.setActivationPolicy(.accessory)
application.run()
