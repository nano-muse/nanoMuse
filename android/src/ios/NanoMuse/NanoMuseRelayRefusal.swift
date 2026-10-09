//
//  NanoMuseRelayRefusal.swift
//  nanoMuse
//
//  The relay's refusals as the chat shows them (docs/parity.md, item 35): one kind per code,
//  read off the HTTP status and the body of a refused model call, so the chat can show one
//  plain sentence and the right button instead of upstream's "Rate limited" / "[429] {…}".
//  The kinds, the codes and the sentences' meaning are the desktop's
//  (`harness/dsh-nanomuse/src/refusals.ts`) and the runtime's (`nanomuse/server/failures.py`);
//  the words are the phone's own, in every language (`NanoMuseCloud.describe`). The Android
//  twin is io.github.nanomuse.cloud.RelayRefusal; the canonical line is the same on both.
//
//  Two halves. `NanoMuseRelayRefusal` is pure: classify, parse, the stored line. The
//  `NanoMuseRelaySignal` keeps the last refusal for a few seconds between `mapHTTPError`
//  (where the body is still whole) and `friendlyErrorMessage` (where the chat stores the
//  failed turn's error), the way NanoMuseReachSignal does for a provider's 401/403/429.
//

import Foundation

enum NanoMuseRelayRefusal {
    /// What the relay said, in the words the cards are keyed by.
    enum Kind: String, Sendable {
        /// 429 `allowance_exhausted`, 402 `out_of_tokens`: the pool is spent — the ways-on card.
        case exhausted
        /// 429 `allowance_exhausted` with `paused: true` (relay 0.22): paused by the operator, not spent — the same card, another lead.
        case allowancePaused = "allowance_paused"
        /// 429 `daily_cap`: today's share is spent — the same card, the day's heading.
        case dailyCap = "daily_cap"
        /// 413 (the relay's `too_large`, or a proxy's plain page): shorten it or start a new chat.
        case tooLarge = "too_large"
        /// 400 `content_rejected`: the provider's content check declined the words (the relay's code, or a
        /// provider's own `DataInspectionFailed` on a key of one's own). Final: the same words come back
        /// refused, so nothing retries it; change them or start a new chat.
        case contentRejected = "content_rejected"
        /// 401: the key was retired elsewhere (`bad_key`), or the account was deleted (`account_deleted`).
        case signedOut = "signed_out"
        /// 403: the account is disabled, or this relay does not take it (`not_invited`, `signup_closed`).
        case disabled
        /// 429 otherwise: `rate_limited`, `too_many_in_flight`, `provider_busy` (with `retry_after`), `locked`.
        case busy
        /// 404 `model_not_offered`: the chosen model left the menu.
        case model
        /// 503 `service_paused` (relay 0.22): the operator paused the relay; nothing is lost.
        case servicePaused = "service_paused"
        /// 503 `sync_paused` (relay 0.22): conversation sync is off for now.
        case syncPaused = "sync_paused"
        /// 503 `hub_paused` (relay 0.22): the device hub is off for now.
        case hubPaused = "hub_paused"
        /// 5xx: the relay, or the provider behind it, did not answer.
        case relayDown = "relay_down"
        /// Any other refusal: the relay's own sentence is shown.
        case other
    }

    /// One refusal, as the chat keeps it.
    struct Refusal: Equatable, Sendable {
        var kind: Kind
        /// The HTTP status; 0 when none.
        var status: Int
        /// The relay's `code`; `http_<status>` without one.
        var code: String
        /// The relay's own sentence, English; empty when it sent none.
        var message: String = ""
        /// `retry_after` in seconds, when the relay said when to come back.
        var retryAfterS: Int? = nil
        /// Relay 0.22: one of the operator's switches, not use (`paused: true`).
        var paused: Bool = false

        /// The allowance card is the answer (the pool spent, paused, or today's share spent).
        var isAllowance: Bool { kind == .exhausted || kind == .allowancePaused || kind == .dailyCap }

        /// The error `NanoMuseCloud.describe` turns into the sentence.
        var cloudError: NanoMuseCloudError {
            NanoMuseCloudError(code: code, message: message, status: status, retryAfterS: retryAfterS, paused: paused)
        }
    }

    /// What a `429 allowance_exhausted` carries beside the code (relay 0.17+): the figures the
    /// card prints, the invite, the docs, the guidance for the region (relay 0.21).
    struct AllowanceFacts: Equatable, Sendable {
        var leftCny: Double?
        var grantCny: Double?
        var inviteURL: String = ""
        var inviteBonusCny: Double?
        var inviteeBonusCny: Double?
        var ownKeyDocs: String = ""
        var guidance: NanoMuseGuidance?
    }

    /// The error type the relay stamps on every refusal (`docs/cloud.md` → Protocol).
    static let relayType = "nanomuse_cloud"

    /// The codes the relay sends today; a body with one of these is the relay's even without the type.
    static let relayCodes: Set<String> = [
        "allowance_exhausted", "out_of_tokens", "daily_cap", "too_large", "content_rejected", "bad_key",
        "account_deleted", "account_disabled", "not_invited", "signup_closed", "rate_limited",
        "too_many_in_flight", "provider_busy", "locked", "model_not_offered", "service_paused", "sync_paused",
        "hub_paused", "upstream",
    ]

    /// How a provider's content check says no, in its own body or in the relay's sentence: the relay's
    /// code, the relay's own words, and Bailian's `DataInspectionFailed` / `data_inspection_failed` with
    /// its "inappropriate content" line (the relay keeps the same marks in `CONTENT_CHECK_MARKS`).
    /// Matched case-insensitively; a miss means the error is treated like any other provider error.
    private static let contentCheckMarks = [
        "content_rejected", "content check declined", "data_inspection_failed", "datainspectionfailed",
        "inappropriate content", "green net",
    ]

    /// True when `text` (an error body, or an error's own line) is a content check saying no.
    static func contentCheck(_ text: String?) -> Bool {
        guard let lower = text?.lowercased() else { return false }
        return contentCheckMarks.contains { lower.contains($0) }
    }

    private static let canonicalPrefix = "nm_relay:"

    /// The kind for a status, a code and the relay's flags — the desktop's `classifyRefusal`.
    static func classify(status: Int, code: String, paused: Bool = false) -> Kind {
        switch code {
        case "allowance_exhausted": return paused ? .allowancePaused : .exhausted
        case "out_of_tokens": return .exhausted
        case "daily_cap": return .dailyCap
        case "content_rejected": return .contentRejected
        case "service_paused": return .servicePaused
        case "sync_paused": return .syncPaused
        case "hub_paused": return .hubPaused
        default: break
        }
        if status == 413 || code == "too_large" { return .tooLarge }
        if status == 401 { return .signedOut }
        if status == 403 { return .disabled }
        if status == 429 { return .busy }
        if status == 404 && code == "model_not_offered" { return .model }
        if status >= 500 { return .relayDown }
        return .other
    }

    /// The relay's error object out of a body: `{error: {...}}` (OpenAI's shape) or the inner
    /// object itself; nil for anything else (a plain-text 413 from a proxy, HTML).
    static func errorObject(_ body: String?) -> [String: Any]? {
        guard let body else { return nil }
        let text = body.trimmingCharacters(in: .whitespacesAndNewlines)
        guard text.hasPrefix("{"), let data = text.data(using: .utf8),
              let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else { return nil }
        return json["error"] as? [String: Any] ?? json
    }

    /// The refusal in a failed HTTP reply of a model call, or nil when the reply is not the
    /// relay's: the body carries `type: nanomuse_cloud` or one of the relay's codes, or the
    /// call went to the relay's host and the status is a 413, a 401 or a 5xx (a proxy's plain
    /// `Request too large` on the way, the relay fallen over). Without `fromRelay` only a body
    /// that says so counts, so another provider's 429 keeps upstream's card. One exception for
    /// every host: a 400 whose body is a content check saying no (`contentCheck`) is
    /// `.contentRejected` whoever sent it, so a key of one's own gets the same sentence and the
    /// same end to retrying.
    static func parse(status: Int, body: String?, fromRelay: Bool = false) -> Refusal? {
        let err = errorObject(body)
        let code = (err?["code"] as? String).flatMap { $0.isEmpty ? nil : $0 }
        let relays = (err?["type"] as? String) == relayType || (code.map { relayCodes.contains($0) } ?? false)
        let isContentCheck = status == 400 && contentCheck(body)
        if !relays && !isContentCheck && !(fromRelay && (status == 413 || status >= 500 || status == 401)) { return nil }
        let paused = (err?["paused"] as? Bool) ?? ((err?["paused"] as? NSNumber)?.boolValue ?? false)
        let retry = (err?["retry_after"] as? NSNumber).map { $0.doubleValue }.flatMap { $0 > 0 ? Int(ceil($0)) : nil }
        var message = (err?["message"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? ""
        if message.isEmpty, let body {
            let t = body.trimmingCharacters(in: .whitespacesAndNewlines)
            if !t.isEmpty, !t.hasPrefix("{"), !t.hasPrefix("<") { message = String(t.prefix(200)) }
        }
        if isContentCheck { return Refusal(kind: .contentRejected, status: status, code: "content_rejected", message: message) }
        let relayCode = code ?? "http_\(status)"
        return Refusal(kind: classify(status: status, code: relayCode, paused: paused), status: status, code: relayCode, message: message, retryAfterS: retry, paused: paused)
    }

    /// The figures beside a `429 allowance_exhausted` (or `daily_cap`), when the relay sent them.
    static func facts(_ body: String?) -> AllowanceFacts {
        let err = errorObject(body) ?? [:]
        func num(_ v: Any?) -> Double? {
            if let n = v as? NSNumber { return n.doubleValue }
            if let s = v as? String { return Double(s) }
            return nil
        }
        return AllowanceFacts(
            leftCny: num(err["left"]),
            grantCny: num(err["grant"]),
            inviteURL: err["invite_url"] as? String ?? "",
            inviteBonusCny: num(err["invite_bonus_cny"]),
            inviteeBonusCny: num(err["invitee_bonus_cny"]),
            ownKeyDocs: err["own_key_docs"] as? String ?? "",
            guidance: NanoMuseGuidance.parse(err["guidance"] as? [String: Any])
        )
    }

    /// `nm_relay:<kind>:<status>:<code>:<retry_after>:<paused>|<message>` — what the view model
    /// stores as the failed turn's error so the card survives a reload (the same line as Android).
    static func canonical(_ r: Refusal) -> String {
        let retry = r.retryAfterS.map(String.init) ?? ""
        return canonicalPrefix + r.kind.rawValue + ":" + String(r.status) + ":" + r.code + ":" + retry + ":" +
            (r.paused ? "1" : "0") + "|" + r.message.replacingOccurrences(of: "\n", with: " ")
    }

    /// The refusal behind a stored error line, or nil when it is not one of ours.
    static func fromCanonical(_ text: String) -> Refusal? {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard t.hasPrefix(canonicalPrefix) else { return nil }
        let rest = t.dropFirst(canonicalPrefix.count)
        let head: Substring
        let message: String
        if let bar = rest.firstIndex(of: "|") {
            head = rest[rest.startIndex..<bar]
            message = String(rest[rest.index(after: bar)...])
        } else {
            head = rest
            message = ""
        }
        let parts = head.split(separator: ":", omittingEmptySubsequences: false).map(String.init)
        guard parts.count >= 5, let kind = Kind(rawValue: parts[0]) else { return nil }
        return Refusal(kind: kind, status: Int(parts[1]) ?? 0, code: parts[2], message: message, retryAfterS: Int(parts[3]), paused: parts[4] == "1")
    }

    /// True when the stored error line is one of ours.
    static func isCanonical(_ text: String) -> Bool {
        text.trimmingCharacters(in: .whitespacesAndNewlines).hasPrefix(canonicalPrefix)
    }
}

/// The relay's refusals kept for the chat for a few seconds: noted in `mapHTTPError` (through
/// NanoMuseReachSignal, which sees every non-2xx answer of an OpenAI-shaped provider) before
/// upstream flattens the body; consumed by `lineForError` when the failed turn's error is
/// about to be stored. An allowance refusal also raises the pinned card (NanoMuseAllowance).
final class NanoMuseRelaySignal: @unchecked Sendable {
    static let shared = NanoMuseRelaySignal()

    private let lock = NSLock()
    private var last: (refusal: NanoMuseRelayRefusal.Refusal, facts: NanoMuseRelayRefusal.AllowanceFacts?, at: Date)?

    /// Call for every non-2xx answer of a model request. Returns true when it was the relay's
    /// and has been kept, so the caller leaves it to this card.
    @discardableResult
    func noteHTTPError(status: Int, body: String?, host: String) -> Bool {
        let fromRelay = NanoMuseProxy.isRelayHost(host)
        guard let refusal = NanoMuseRelayRefusal.parse(status: status, body: body, fromRelay: fromRelay) else { return false }
        let facts = refusal.isAllowance ? NanoMuseRelayRefusal.facts(body) : nil
        lock.lock()
        last = (refusal, facts, Date())
        lock.unlock()
        return true
    }

    /// The refusal behind the error the chat is about to show, if there is a fresh one; consumed.
    func takeFresh(maxAge: TimeInterval = 30) -> (refusal: NanoMuseRelayRefusal.Refusal, facts: NanoMuseRelayRefusal.AllowanceFacts?)? {
        lock.lock(); defer { lock.unlock() }
        guard let n = last else { return nil }
        last = nil
        return Date().timeIntervalSince(n.at) <= maxAge ? (n.refusal, n.facts) : nil
    }

    func clear() {
        lock.lock(); defer { lock.unlock() }
        last = nil
    }
}
