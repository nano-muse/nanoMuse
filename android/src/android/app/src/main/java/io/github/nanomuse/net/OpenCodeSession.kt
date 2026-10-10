package io.github.nanomuse.net

import java.net.URI
import java.util.Locale

/**
 * OpenCode Go asks every client to name itself with its own user agent and to send one stable
 * id per conversation in `x-opencode-session` (opencode.ai/docs/go, "Where can I use it?"); the
 * catalogue says so in the entry's `session_header`. The user agent is already the app's own
 * (`MinisUserAgent.DEFAULT`, `nanoMuse/<version> (Android …)`); this names the header and the
 * endpoints that get it. `OpenAIProvider.buildRequest` adds it to chat and Responses requests,
 * with the conversation's `prompt_cache_key` (a hash of its first user message, stable across
 * turns) as the value.
 *
 * Every endpoint on OpenCode's host gets it, Zen included: OpenCode's own clients send it to
 * both, and Zen ignores it. `ProviderCatalogueTest` checks that every catalogue entry with a
 * `session_header` is on a host this matches, so the two cannot drift apart. The iOS twin is
 * NanoMuseOpenCodeSession.swift.
 */
object OpenCodeSession {
    const val HEADER = "x-opencode-session"
    private const val HOST = "opencode.ai"

    /** Whether requests to this base URL carry [HEADER]. */
    fun wants(baseUrl: String?): Boolean {
        val raw = baseUrl?.trim() ?: return false
        val host = runCatching { URI(raw).host }.getOrNull()?.lowercase(Locale.ROOT) ?: return false
        return host == HOST || host.endsWith(".$HOST")
    }
}
