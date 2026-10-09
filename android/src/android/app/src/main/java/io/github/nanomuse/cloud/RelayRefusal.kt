package io.github.nanomuse.cloud

import org.json.JSONObject

/**
 * The relay's refusals as the chat shows them (docs/parity.md, item 35): one kind per code,
 * read off the HTTP status and the body of a refused model call, so the chat can show one
 * plain sentence and the right button instead of upstream's "Rate limited" / "[429] {…}".
 * The kinds, the codes and the sentences' meaning are the desktop's
 * (`harness/dsh-nanomuse/src/refusals.ts`) and the runtime's (`nanomuse/server/failures.py`);
 * the words are the phone's own, in every locale (`nm_cloud_err_*`).
 *
 * Pure Kotlin: the unit tests run it without Android. The sentence itself is
 * [NanoMuseCloud.describe] of [toException], which has the strings.
 */
object RelayRefusal {
    /** What the relay said, in the words the cards are keyed by. */
    enum class Kind(val wire: String) {
        /** 429 `allowance_exhausted`, 402 `out_of_tokens`: the pool is spent — the ways-on card. */
        EXHAUSTED("exhausted"),

        /** 429 `allowance_exhausted` with `paused: true` (relay 0.22): the allowance paused by the operator, not spent — the same card, another lead. */
        ALLOWANCE_PAUSED("allowance_paused"),

        /** 429 `daily_cap`: today's share is spent (a relay that sets one) — the same card, the day's heading. */
        DAILY_CAP("daily_cap"),

        /** 413 (the relay's `too_large`, or the proxy's plain `Request too large`): shorten it or start a new chat. */
        TOO_LARGE("too_large"),

        /**
         * 400 `content_rejected`: the provider's content check declined the words (the relay's
         * code, or a provider's own `DataInspectionFailed` on a key of one's own). Final: the
         * same words come back refused, so nothing retries it; change them or start a new chat.
         */
        CONTENT_REJECTED("content_rejected"),

        /** 401: the key was retired elsewhere (`bad_key`), or the account was deleted (`account_deleted`); sign in again. */
        SIGNED_OUT("signed_out"),

        /** 403: the account is disabled, or this relay does not take it (`not_invited`, `signup_closed`). */
        DISABLED("disabled"),

        /** 429 otherwise: `rate_limited`, `too_many_in_flight`, `provider_busy` (with `retry_after`), `locked`. */
        BUSY("busy"),

        /** 404 `model_not_offered`: the chosen model left the menu. */
        MODEL("model"),

        /** 503 `service_paused` (relay 0.22): the operator paused the relay; nothing is lost. */
        SERVICE_PAUSED("service_paused"),

        /** 503 `sync_paused` (relay 0.22): conversation sync is off for now. */
        SYNC_PAUSED("sync_paused"),

        /** 503 `hub_paused` (relay 0.22): the device hub is off for now. */
        HUB_PAUSED("hub_paused"),

        /** 5xx: the relay, or the provider behind it, did not answer. */
        RELAY_DOWN("relay_down"),

        /** Any other refusal: the relay's own sentence is shown. */
        OTHER("other"),
        ;

        companion object {
            fun of(wire: String): Kind? = entries.firstOrNull { it.wire == wire }
        }
    }

    /** One refusal, as the chat keeps it. */
    data class Refusal(
        val kind: Kind,
        /** The HTTP status; 0 when none. */
        val status: Int,
        /** The relay's `code` (`allowance_exhausted`, `too_large`, …); `http_<status>` without one. */
        val code: String,
        /** The relay's own sentence, English; empty when it sent none. */
        val message: String = "",
        /** `retry_after` in seconds, when the relay said when to come back. */
        val retryAfterS: Int? = null,
        /** Relay 0.22: the refusal comes from one of the operator's switches, not from use (`paused: true`). */
        val paused: Boolean = false,
    ) {
        /** The allowance card is the answer (the pool spent, paused, or today's share spent). */
        val isAllowance: Boolean get() = kind == Kind.EXHAUSTED || kind == Kind.ALLOWANCE_PAUSED || kind == Kind.DAILY_CAP

        /** The [NanoMuseCloud.CloudException] [NanoMuseCloud.describe] turns into the sentence. */
        fun toException(): NanoMuseCloud.CloudException =
            NanoMuseCloud.CloudException(code, message, status, retryAfterS = retryAfterS, paused = paused)
    }

    /** The error type the relay stamps on every refusal (`docs/cloud.md` → Protocol). */
    const val RELAY_TYPE = "nanomuse_cloud"

    /** The codes the relay sends today; a body with one of these is the relay's even without the type. */
    val RELAY_CODES: Set<String> = setOf(
        "allowance_exhausted", "out_of_tokens", "daily_cap", "too_large", "content_rejected", "bad_key",
        "account_deleted", "account_disabled", "not_invited", "signup_closed", "rate_limited",
        "too_many_in_flight", "provider_busy", "locked", "model_not_offered", "service_paused", "sync_paused",
        "hub_paused", "upstream",
    )

    /**
     * How a provider's content check says no, in its own body or in the relay's sentence: the
     * relay's code, the relay's own words, and Bailian's `DataInspectionFailed` /
     * `data_inspection_failed` with its "inappropriate content" line (the relay keeps the same
     * marks in `CONTENT_CHECK_MARKS`). Matched case-insensitively; a miss means the error is
     * treated like any other provider error, as before.
     */
    private val CONTENT_CHECK_MARKS = listOf(
        "content_rejected", "content check declined", "data_inspection_failed", "datainspectionfailed",
        "inappropriate content", "green net",
    )

    /** True when [text] (an error body, or an error's own line) is a content check saying no. */
    fun contentCheck(text: String?): Boolean {
        val lower = text?.lowercase() ?: return false
        return CONTENT_CHECK_MARKS.any { it in lower }
    }

    private val PAUSED_CODES = mapOf(
        "service_paused" to Kind.SERVICE_PAUSED,
        "sync_paused" to Kind.SYNC_PAUSED,
        "hub_paused" to Kind.HUB_PAUSED,
    )

    private const val CANONICAL_PREFIX = "nm_relay:"

    /** The kind for a status, a code and the relay's flags — the desktop's `classifyRefusal`. */
    fun classify(status: Int, code: String, paused: Boolean = false): Kind = when {
        code == "allowance_exhausted" && paused -> Kind.ALLOWANCE_PAUSED
        code == "allowance_exhausted" || code == "out_of_tokens" -> Kind.EXHAUSTED
        code == "daily_cap" -> Kind.DAILY_CAP
        code == "content_rejected" -> Kind.CONTENT_REJECTED
        PAUSED_CODES[code] != null -> PAUSED_CODES.getValue(code)
        status == 413 || code == "too_large" -> Kind.TOO_LARGE
        status == 401 -> Kind.SIGNED_OUT
        status == 403 -> Kind.DISABLED
        status == 429 -> Kind.BUSY
        status == 404 && code == "model_not_offered" -> Kind.MODEL
        status >= 500 -> Kind.RELAY_DOWN
        else -> Kind.OTHER
    }

    /**
     * The relay's error object out of a body: `{error: {...}}` (OpenAI's shape) or the inner
     * object itself; null for anything else (a plain-text 413 from a proxy, HTML).
     */
    fun errorObject(body: String?): JSONObject? {
        val text = body?.trim()?.takeIf { it.startsWith("{") } ?: return null
        val json = runCatching { JSONObject(text) }.getOrNull() ?: return null
        return json.optJSONObject("error") ?: json
    }

    /**
     * The refusal in a failed HTTP reply of a model call, or null when the reply is not the
     * relay's: the body carries `type: nanomuse_cloud` or one of the relay's codes, or the
     * status is a 413 (a proxy's plain `Request too large` on the way to the relay).
     * [fromRelay] says the call went to the relay's host; without it only a body that says
     * so counts, so another provider's 429 keeps upstream's card. One exception for every
     * host: a 400 whose body is a content check saying no ([contentCheck]) is
     * [Kind.CONTENT_REJECTED] whoever sent it, so a key of one's own gets the same sentence
     * and the same end to retrying.
     */
    fun parse(status: Int, body: String?, fromRelay: Boolean = false): Refusal? {
        val err = errorObject(body)
        val code = err?.optString("code")?.takeIf { it.isNotBlank() }
        val relays = err?.optString("type") == RELAY_TYPE || (code != null && code in RELAY_CODES)
        val contentCheck = status == 400 && contentCheck(body)
        if (!relays && !contentCheck && !(fromRelay && (status == 413 || status >= 500 || status == 401))) return null
        val paused = err?.optBoolean("paused", false) == true
        val retry = err?.optDouble("retry_after", 0.0)?.takeIf { it > 0 }?.let { kotlin.math.ceil(it).toInt() }
        val message = err?.optString("message")?.takeIf { it.isNotBlank() }
            ?: body?.trim()?.takeIf { it.isNotBlank() && !it.startsWith("{") && !it.startsWith("<") }?.take(200)
            ?: ""
        if (contentCheck) return Refusal(Kind.CONTENT_REJECTED, status, "content_rejected", message)
        val relayCode = code ?: "http_$status"
        return Refusal(classify(status, relayCode, paused), status, relayCode, message, retry, paused)
    }

    /**
     * `nm_relay:<kind>:<status>:<code>:<retry_after>:<paused>|<message>` — what the view model
     * stores as the failed turn's error so the card survives a reload, and what the chat reads
     * back with [fromCanonical].
     */
    fun canonical(r: Refusal): String =
        CANONICAL_PREFIX + r.kind.wire + ":" + r.status + ":" + r.code + ":" + (r.retryAfterS?.toString() ?: "") + ":" +
            (if (r.paused) "1" else "0") + "|" + r.message.replace('\n', ' ')

    /** The refusal behind a stored error line, or null when it is not one of ours. */
    fun fromCanonical(text: String): Refusal? {
        val t = text.trim()
        if (!t.startsWith(CANONICAL_PREFIX)) return null
        val rest = t.removePrefix(CANONICAL_PREFIX)
        val head = rest.substringBefore('|')
        val message = if ('|' in rest) rest.substringAfter('|') else ""
        val parts = head.split(':')
        if (parts.size < 5) return null
        val kind = Kind.of(parts[0]) ?: return null
        return Refusal(
            kind = kind,
            status = parts[1].toIntOrNull() ?: 0,
            code = parts[2],
            message = message,
            retryAfterS = parts[3].toIntOrNull(),
            paused = parts[4] == "1",
        )
    }
}
