// The routes: the bearer token first, then status, request, screenshot, windows, window,
// execute, quit.

import CoreGraphics
import Foundation

final class Service {
    private let token: String
    private let version: String

    init(token: String, version: String) {
        self.token = token
        self.version = version
    }

    func handle(_ request: HTTPRequest) -> HTTPResponse {
        guard request.headers["authorization"] == "Bearer \(token)" else {
            return Service.failure(401, "unauthorized", "a bearer token is required")
        }
        let body: [String: Any]
        if request.body.isEmpty {
            body = [:]
        } else if let parsed = (try? JSONSerialization.jsonObject(with: request.body, options: [])) as? [String: Any] {
            body = parsed
        } else {
            return Service.failure(400, "bad_request", "the body must be a JSON object")
        }
        switch (request.method, request.path) {
        case ("GET", "/status"):
            return HTTPResponse(status: 200, body: status())
        case ("POST", "/request"):
            let what = body["what"] as? String ?? ""
            guard what == "screen" || what == "accessibility" else {
                return Service.failure(400, "bad_request", "`what` must be \"screen\" or \"accessibility\"")
            }
            Permissions.request(what)
            if body["pane"] as? Bool == true {
                Permissions.openPane(what)
            }
            return HTTPResponse(status: 200, body: status())
        case ("POST", "/screenshot"):
            return screenshot(body)
        case ("GET", "/windows"):
            return windows()
        case ("POST", "/window"):
            return window(body)
        case ("POST", "/execute"):
            return execute(body)
        case ("POST", "/quit"):
            // the answer goes out first; then the run loop ends — with nothing left held down
            Keyboard.releaseAll()
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
                exit(0)
            }
            return HTTPResponse(status: 200, body: ["ok": true])
        default:
            return Service.failure(404, "not_found", "no route \(request.method) \(request.path)")
        }
    }

    private func status() -> [String: Any] {
        let mainDisplay = CGMainDisplayID()
        let bounds = CGDisplayBounds(mainDisplay)
        // the mode's pixel width is the physical one; CGDisplayPixelsWide is in points on a
        // Retina display (1728 for a 3456-pixel panel), which read as a scale of 1 in 0.1.38
        let pixelsWide = CGDisplayCopyDisplayMode(mainDisplay)?.pixelWidth ?? CGDisplayPixelsWide(mainDisplay)
        let scale = bounds.width > 0 ? Double(pixelsWide) / Double(bounds.width) : 1
        let display: [String: Any] = ["width": Int(bounds.width), "height": Int(bounds.height), "scale": scale]
        return [
            // granted / denied / unknown — the capture layer's word on macOS 14+, not the preflight's alone
            "screen": Permissions.screenState().rawValue,
            "screen_detail": Permissions.screenDetail(),
            "capture": ScreenCapture.source,
            "accessibility": Permissions.accessibilityGranted(),
            "pid": Int(getpid()),
            "version": version,
            "display": display,
        ]
    }

    /// The refusal for a missing Screen Recording grant, with the capture layer's reason when it had one.
    private static func screenDenied(_ detail: String) -> HTTPResponse {
        let base = "Screen Recording is off for nanoMuse Computer Use"
        return Service.failure(403, "screen_denied", detail.isEmpty ? base : "\(base) (\(detail))")
    }

    /// A JSON number as a whole number within bounds (nil when absent or not a number).
    private static func integer(_ value: Any?, min lower: Double, max upper: Double) -> Int? {
        guard let number = Service.number(value), number.isFinite else { return nil }
        return Int(Swift.min(upper, Swift.max(lower, number)))
    }

    private func screenshot(_ body: [String: Any]) -> HTTPResponse {
        // `denied` is refused here; `unknown` (an SCK error that is not a refusal) lets the
        // capture try and report the real error, rather than guessing at the permission
        if Permissions.screenState() == .denied {
            return Service.screenDenied(Permissions.screenDetail())
        }
        let format = body["format"] as? String == "png" ? "png" : "jpeg"
        let quality = min(1, max(0.3, (Service.number(body["quality"]) ?? 80) / 100))
        let maxPixels = Service.integer(body["max_pixels"], min: 10_000, max: 50_000_000) ?? 2_000_000
        let width = Service.integer(body["width"], min: 0, max: 20_000)
        let height = Service.integer(body["height"], min: 0, max: 20_000)
        do {
            let shot = try Screenshot.take(width: width, height: height, maxPixels: maxPixels, format: format, quality: quality)
            let screen: [String: Any] = ["width": shot.screenWidth, "height": shot.screenHeight]
            return HTTPResponse(status: 200, body: [
                "base64": shot.data.base64EncodedString(),
                "mime": shot.mime,
                "width": shot.width,
                "height": shot.height,
                "screen": screen,
                "scale": shot.scale,
                "capture": ScreenCapture.source,
            ])
        } catch Screenshot.Failure.black {
            return Service.failure(403, "screen_denied", "the picture is black — Screen Recording is off for nanoMuse Computer Use")
        } catch {
            return Service.captureFailure(error)
        }
    }

    /// `GET /windows`: the windows on screen, for the runtime's window mode (front to back).
    private func windows() -> HTTPResponse {
        if Permissions.screenState() == .denied {
            return Service.screenDenied(Permissions.screenDetail())
        }
        do {
            let list = try ScreenCapture.windows()
            return HTTPResponse(status: 200, body: ["windows": list.map { $0.json }, "capture": ScreenCapture.source])
        } catch {
            return Service.captureFailure(error)
        }
    }

    /// `POST /window { id, max_pixels?, format?, quality? }`: one window's own pixels and its frame.
    private func window(_ body: [String: Any]) -> HTTPResponse {
        guard let id = Service.integer(body["id"], min: 1, max: Double(UInt32.max)) else {
            return Service.failure(400, "bad_request", "`id` must be a window id from /windows")
        }
        if Permissions.screenState() == .denied {
            return Service.screenDenied(Permissions.screenDetail())
        }
        let format = body["format"] as? String == "jpeg" ? "jpeg" : "png"
        let quality = min(1, max(0.3, (Service.number(body["quality"]) ?? 80) / 100))
        let maxPixels = Service.integer(body["max_pixels"], min: 0, max: 50_000_000) ?? 0
        do {
            let shot = try Screenshot.window(id: UInt32(id), maxPixels: maxPixels, format: format, quality: quality)
            let frame: [String: Any] = ["id": id, "x": shot.originX, "y": shot.originY, "width": shot.screenWidth, "height": shot.screenHeight]
            return HTTPResponse(status: 200, body: [
                "base64": shot.data.base64EncodedString(),
                "mime": shot.mime,
                "width": shot.width,
                "height": shot.height,
                "window": frame,
                "scale": shot.scale,
                "capture": ScreenCapture.source,
            ])
        } catch Screenshot.Failure.noWindow(let missing) {
            return Service.failure(404, "no_window", "no window with id \(missing) is on screen")
        } catch {
            return Service.captureFailure(error)
        }
    }

    /// A capture that failed: a refusal from the capture layer is 403 with its words; anything
    /// else is 500 with the error named (`ScreenCaptureKit userDeclined (-3801): …`, `no image
    /// came back from the capture`), which the shell's log and the runtime's error carry on.
    static func captureFailure(_ error: Error) -> HTTPResponse {
        if ScreenCapture.isDenied(error) {
            Permissions.forgetProbe()
            return Service.screenDenied(ScreenCapture.describe(error))
        }
        return Service.failure(500, "screenshot_failed", "no screenshot: \(ScreenCapture.describe(error))")
    }

    private func execute(_ body: [String: Any]) -> HTTPResponse {
        guard Permissions.accessibilityGranted() else {
            return Service.failure(403, "accessibility_denied", "macOS has not granted nanoMuse Computer Use permission to send input. Check Accessibility for the helper in System Settings.")
        }
        do {
            try Input.perform(body)
            return HTTPResponse(status: 200, body: ["ok": true, "note": ""])
        } catch Input.Failure.message(let text) {
            return Service.failure(400, "bad_action", text)
        } catch {
            return Service.failure(500, "action_failed", "\(error)")
        }
    }

    static func failure(_ status: Int, _ error: String, _ message: String) -> HTTPResponse {
        HTTPResponse(status: status, body: ["error": error, "message": message])
    }

    /// A JSON number (or a numeric string) as Double; nil for anything else.
    static func number(_ value: Any?) -> Double? {
        if let number = value as? NSNumber {
            return number.doubleValue
        }
        if let text = value as? String {
            return Double(text)
        }
        return nil
    }
}
