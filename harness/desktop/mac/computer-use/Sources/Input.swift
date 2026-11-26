// The hands: CGEvent mouse and keyboard events posted at the HID level, in the operator's
// vocabulary (src/operator.ts). Coordinates are points of the main display, top-left origin —
// what CGEvent wants and what the operator's screen space is on a Mac.

import CoreGraphics
import Foundation

enum Input {
    enum Failure: Error {
        case message(String)
    }

    static func perform(_ body: [String: Any]) throws {
        let kind = body["action"] as? String ?? ""
        let start = point(body, "x", "y")
        let end = point(body, "x2", "y2")
        func needsPoint() throws -> CGPoint {
            guard let start = start else { throw Failure.message("\(kind) needs x and y") }
            return start
        }
        switch kind {
        case "move", "hover":
            let at = try needsPoint()
            Mouse.move(to: at)
        case "click", "left_click":
            let at = try needsPoint()
            Mouse.click(at: at, button: .left)
        case "double_click", "left_double":
            let at = try needsPoint()
            Mouse.click(at: at, button: .left, count: 2)
        case "right_click", "right_single":
            let at = try needsPoint()
            Mouse.click(at: at, button: .right)
        case "middle_click":
            let at = try needsPoint()
            Mouse.click(at: at, button: .center)
        case "drag", "left_click_drag":
            let from = try needsPoint()
            guard let to = end else { throw Failure.message("drag needs x2 and y2") }
            Mouse.drag(from: from, to: to)
        case "scroll":
            // `dy` in points, positive = down (the runtime's dialect)
            let dy = Service.number(body["dy"]) ?? 300
            if let start = start {
                Mouse.move(to: start)
            }
            Mouse.scroll(dy: dy)
        case "type":
            let raw = body["text"] as? String ?? ""
            guard !raw.isEmpty else { throw Failure.message("type needs text") }
            let submit = body["submit"] as? Bool == true || raw.hasSuffix("\n") || raw.hasSuffix("\\n")
            var text = raw
            if text.hasSuffix("\\n") {
                text = String(text.dropLast(2))
            } else if text.hasSuffix("\n") {
                text = String(text.dropLast())
            }
            if body["clear"] as? Bool == true {
                try Keyboard.hotkey(["cmd", "a"])
                pause(ms: 50)
            }
            Keyboard.type(text)
            if submit {
                Keyboard.tap(Keys.returnKey)
            }
        case "key", "hotkey":
            let names = (body["keys"] as? [Any] ?? []).map { "\($0)" }
            guard !names.isEmpty else { throw Failure.message("key needs keys") }
            try Keyboard.hotkey(names)
        case "press", "release":
            // UI-TARS's hold: keys down across the actions that follow (shift-click, a game)
            let names = (body["keys"] as? [Any] ?? []).map { "\($0)" }
            guard !names.isEmpty else { throw Failure.message("\(kind) needs keys") }
            if kind == "press" {
                try Keyboard.press(names)
            } else {
                try Keyboard.release(names)
            }
        case "wait":
            let seconds = min(10, max(0.2, Service.number(body["seconds"]) ?? 1))
            pause(ms: Int(seconds * 1000))
        default:
            throw Failure.message("unknown action '\(kind)'")
        }
    }

    /// Both coordinates present and finite → a point clamped to the main display; else nil.
    private static func point(_ body: [String: Any], _ kx: String, _ ky: String) -> CGPoint? {
        guard let x = Service.number(body[kx]), let y = Service.number(body[ky]), x.isFinite, y.isFinite else { return nil }
        let bounds = CGDisplayBounds(CGMainDisplayID())
        return CGPoint(
            x: min(max(x, Double(bounds.minX)), Double(bounds.maxX) - 1),
            y: min(max(y, Double(bounds.minY)), Double(bounds.maxY) - 1)
        )
    }
}

func pause(ms: Int) {
    Thread.sleep(forTimeInterval: Double(ms) / 1000)
}

enum Mouse {
    /// Where a `down` parks the fact that a button is still down (the shell's computer-use
    /// directory), so a helper that never gets to post the `up` — killed, its shell gone —
    /// leaves a note the next one can clear. Input.swift has no file paths of its own.
    static var marker: URL?

    /// The buttons this process put down and has not lifted yet.
    private static var held: [CGMouseButton] = []

    /// The marker says one line of button numbers: `0` left, `1` right, `2` center.
    private static func note(_ button: CGMouseButton, down: Bool) {
        if down {
            if !held.contains(where: { $0.rawValue == button.rawValue }) {
                held.append(button)
            }
        } else {
            held.removeAll { $0.rawValue == button.rawValue }
        }
        guard let marker = marker else { return }
        do {
            if held.isEmpty {
                try? FileManager.default.removeItem(at: marker)
            } else {
                let line = held.map { "\($0.rawValue)" }.joined(separator: ",") + "\n"
                try Data(line.utf8).write(to: marker, options: .atomic)
            }
        } catch {
            // the note is a courtesy; a click never fails because a file could not be written
        }
    }

    /// Every button this process put down goes up, at the pointer's own place — called before
    /// the process ends, so a crash or a force quit cannot leave the system holding a button.
    static func releaseAll() {
        guard !held.isEmpty else { return }
        let at = CGEvent(source: nil)?.location ?? .zero
        for button in held.reversed() {
            post(upType(button), at: at, button: button)
            pause(ms: 20)
        }
        held.removeAll()
        if let marker = marker {
            try? FileManager.default.removeItem(at: marker)
        }
    }

    /// The note a previous helper left: those buttons go up now, and the note goes away.
    /// A helper that was killed mid-drag would otherwise leave the system holding the button —
    /// every drag and every hover in every app stops working until someone presses ESC.
    static func releaseStuck() {
        guard let marker = marker, let text = try? String(contentsOf: marker, encoding: .utf8) else { return }
        let at = CGEvent(source: nil)?.location ?? .zero
        for field in text.split(separator: ",", omittingEmptySubsequences: true) {
            guard let raw = UInt32(field.trimmingCharacters(in: .whitespacesAndNewlines)),
                  raw <= 2, let button = CGMouseButton(rawValue: raw) else { continue }
            post(upType(button), at: at, button: button)
            pause(ms: 20)
        }
        try? FileManager.default.removeItem(at: marker)
    }

    private static func upType(_ button: CGMouseButton) -> CGEventType {
        switch button {
        case .left: return .leftMouseUp
        case .right: return .rightMouseUp
        default: return .otherMouseUp
        }
    }

    private static func post(_ type: CGEventType, at point: CGPoint, button: CGMouseButton, clicks: Int64 = 1) {
        guard let event = CGEvent(mouseEventSource: nil, mouseType: type, mouseCursorPosition: point, mouseButton: button) else { return }
        if type != .mouseMoved {
            // a double click is two clicks whose events say so; apps count by this field
            event.setIntegerValueField(.mouseEventClickState, value: clicks)
        }
        // a modifier held by `press` rides on the clicks in between (shift-click, cmd-click)
        if !Keyboard.heldFlags.isEmpty {
            event.flags = Keyboard.heldFlags
        }
        event.post(tap: .cghidEventTap)
    }

    static func move(to point: CGPoint) {
        post(.mouseMoved, at: point, button: .left)
        pause(ms: 30)
    }

    static func click(at point: CGPoint, button: CGMouseButton, count: Int = 1) {
        move(to: point)
        pause(ms: 100)
        let down: CGEventType
        let up: CGEventType
        switch button {
        case .left:
            down = .leftMouseDown
            up = .leftMouseUp
        case .right:
            down = .rightMouseDown
            up = .rightMouseUp
        default:
            down = .otherMouseDown
            up = .otherMouseUp
        }
        for index in 1...max(1, count) {
            post(down, at: point, button: button, clicks: Int64(index))
            note(button, down: true)
            pause(ms: 40)
            post(up, at: point, button: button, clicks: Int64(index))
            note(button, down: false)
            pause(ms: index < count ? 80 : 40)
        }
    }

    static func drag(from: CGPoint, to: CGPoint) {
        move(to: from)
        pause(ms: 100)
        post(.leftMouseDown, at: from, button: .left)
        note(.left, down: true)
        pause(ms: 60)
        let steps = 12
        for index in 1...steps {
            let t = Double(index) / Double(steps)
            let p = CGPoint(x: from.x + (to.x - from.x) * t, y: from.y + (to.y - from.y) * t)
            post(.leftMouseDragged, at: p, button: .left)
            pause(ms: 15)
        }
        post(.leftMouseUp, at: to, button: .left)
        note(.left, down: false)
        pause(ms: 40)
    }

    /// `dy` points, positive = down; CGEvent's wheel1 is positive for up. In chunks, so the
    /// receiving app sees a wheel turning rather than one jump.
    static func scroll(dy: Double) {
        var remaining = Int32(max(-3000, min(3000, -dy)))
        while remaining != 0 {
            let step = max(-120, min(120, remaining))
            guard let event = CGEvent(scrollWheelEvent2Source: nil, units: .pixel, wheelCount: 1, wheel1: step, wheel2: 0, wheel3: 0) else { return }
            if !Keyboard.heldFlags.isEmpty {
                event.flags = Keyboard.heldFlags
            }
            event.post(tap: .cghidEventTap)
            pause(ms: 10)
            remaining -= step
        }
    }
}

enum Keyboard {
    /// What `press` holds down until `release` (or the end of the process): the modifiers as
    /// flags for every event in between, and the keys themselves, so each goes up once.
    private(set) static var heldFlags: CGEventFlags = []
    private static var heldCodes: [CGKeyCode] = []

    private static func post(_ code: CGKeyCode, down: Bool, flags: CGEventFlags) {
        guard let event = CGEvent(keyboardEventSource: nil, virtualKey: code, keyDown: down) else { return }
        event.flags = flags.union(heldFlags)
        event.post(tap: .cghidEventTap)
    }

    /// One key down and up, with the modifier flags on both events.
    static func tap(_ code: CGKeyCode, flags: CGEventFlags = []) {
        post(code, down: true, flags: flags)
        pause(ms: 8)
        post(code, down: false, flags: flags)
        pause(ms: 8)
    }

    /// The names as flags (the modifiers) and codes (the other keys), or the unknown one.
    private static func parse(_ names: [String]) throws -> (CGEventFlags, [CGKeyCode]) {
        var flags: CGEventFlags = []
        var codes: [CGKeyCode] = []
        for name in names {
            let key: Key
            do {
                key = try Keys.lookup(name)
            } catch {
                throw Input.Failure.message("unknown key '\(name)'")
            }
            if let modifier = key.modifier {
                flags.insert(modifier)
            } else {
                codes.append(key.code)
            }
        }
        return (flags, codes)
    }

    /// Keys down and kept down: the modifiers first (as keys of their own, so apps that watch
    /// them see them), then the others. A key already held is not pressed twice.
    static func press(_ names: [String]) throws {
        let (flags, codes) = try parse(names)
        heldFlags.formUnion(flags)
        for code in Keys.modifierCodes(flags) + codes where !heldCodes.contains(code) {
            heldCodes.append(code)
            post(code, down: true, flags: [])
            pause(ms: 8)
        }
    }

    /// The held keys named go up, in the reverse order; their modifier flags stop riding along.
    static func release(_ names: [String]) throws {
        let (flags, codes) = try parse(names)
        heldFlags.subtract(flags)
        for code in (Keys.modifierCodes(flags) + codes).reversed() where heldCodes.contains(code) {
            heldCodes.removeAll { $0 == code }
            post(code, down: false, flags: [])
            pause(ms: 8)
        }
    }

    /// Everything `press` left down goes up (before the process ends).
    static func releaseAll() {
        for code in heldCodes.reversed() {
            heldFlags = []
            post(code, down: false, flags: [])
            pause(ms: 8)
        }
        heldCodes.removeAll()
        heldFlags = []
    }

    /// `["cmd", "shift", "s"]`: the modifiers go down as keys of their own (apps that watch
    /// them see them), the other keys are tapped with the flags set, the modifiers come up.
    static func hotkey(_ names: [String]) throws {
        let (flags, codes) = try parse(names)
        let held = Keys.modifierCodes(flags)
        for code in held {
            post(code, down: true, flags: flags)
            pause(ms: 8)
        }
        for code in codes {
            tap(code, flags: flags)
        }
        for code in held.reversed() {
            post(code, down: false, flags: [])
            pause(ms: 8)
        }
    }

    /// Text of any script: keyboard events carrying the characters themselves
    /// (`CGEventKeyboardSetUnicodeString`), a few at a time, never split inside a character.
    /// Newlines and tabs are the Return and Tab keys.
    static func type(_ text: String) {
        var chunk: [UniChar] = []
        func flush() {
            guard !chunk.isEmpty else { return }
            guard let down = CGEvent(keyboardEventSource: nil, virtualKey: 0, keyDown: true),
                  let up = CGEvent(keyboardEventSource: nil, virtualKey: 0, keyDown: false) else { return }
            chunk.withUnsafeBufferPointer { units in
                down.keyboardSetUnicodeString(stringLength: units.count, unicodeString: units.baseAddress)
                up.keyboardSetUnicodeString(stringLength: units.count, unicodeString: units.baseAddress)
            }
            down.post(tap: .cghidEventTap)
            pause(ms: 4)
            up.post(tap: .cghidEventTap)
            pause(ms: 8)
            chunk.removeAll()
        }
        for character in text {
            if character == "\n" || character == "\r\n" {
                flush()
                tap(Keys.returnKey)
            } else if character == "\t" {
                flush()
                tap(Keys.tab)
            } else {
                let units = Array(String(character).utf16)
                if chunk.count + units.count > 16 {
                    flush()
                }
                chunk.append(contentsOf: units)
            }
        }
        flush()
    }
}
