//
//  NanoMuseOpenCodeSession.swift
//  nanoMuse
//
//  OpenCode Go asks every client to name itself with its own user agent and to send one stable
//  id per conversation in `x-opencode-session` (opencode.ai/docs/go, "Where can I use it?"); the
//  catalogue says so in the entry's `session_header`. The user agent is already the app's own
//  (`MinisUserAgent.default`, `nanoMuse/<version> (iOS …)`); this names the header and the
//  endpoints that get it. `OpenAIAgentProvider` passes the conversation's prompt cache key (a
//  hash of its first user message, stable across turns) to `OpenAIProvider.streamRaw`, which
//  sets the header on chat and Responses requests.
//
//  Every endpoint on OpenCode's host gets it, Zen included: OpenCode's own clients send it to
//  both, and Zen ignores it. The Android twin is io.github.nanomuse.net.OpenCodeSession.
//

import Foundation

enum NanoMuseOpenCodeSession {
    static let header = "x-opencode-session"
    private static let host = "opencode.ai"

    /// Whether requests to this base URL carry `header`.
    static func wants(_ baseURL: String?) -> Bool {
        guard let raw = baseURL?.trimmingCharacters(in: .whitespacesAndNewlines),
              let h = URLComponents(string: raw)?.host?.lowercased() else { return false }
        return h == host || h.hasSuffix("." + host)
    }
}
