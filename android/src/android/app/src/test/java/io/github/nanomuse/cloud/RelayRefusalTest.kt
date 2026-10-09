package io.github.nanomuse.cloud

import com.openminis.app.data.model.LLMError
import com.openminis.app.ui.chat.ChatViewModel.Companion.shouldSplitOnError
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * docs/parity.md, item 35: every code the relay sends today lands on one kind — the one the
 * chat turns into a plain sentence and the right button — and the stored line round-trips.
 */
class RelayRefusalTest {
    private fun relay(status: Int, code: String, message: String = "refused", extra: String = "") =
        RelayRefusal.parse(status, """{"error":{"message":"$message","type":"nanomuse_cloud","code":"$code"$extra}}""")!!

    @Test fun `every code the relay sends today has a kind`() {
        val expected = mapOf(
            Triple(429, "allowance_exhausted", "") to RelayRefusal.Kind.EXHAUSTED,
            Triple(429, "allowance_exhausted", ""","paused":true,"reason":"allowance_paused"""") to RelayRefusal.Kind.ALLOWANCE_PAUSED,
            Triple(402, "out_of_tokens", "") to RelayRefusal.Kind.EXHAUSTED,
            Triple(429, "daily_cap", "") to RelayRefusal.Kind.DAILY_CAP,
            Triple(413, "too_large", "") to RelayRefusal.Kind.TOO_LARGE,
            Triple(400, "content_rejected", "") to RelayRefusal.Kind.CONTENT_REJECTED,
            Triple(401, "bad_key", "") to RelayRefusal.Kind.SIGNED_OUT,
            Triple(401, "account_deleted", "") to RelayRefusal.Kind.SIGNED_OUT,
            Triple(403, "account_disabled", "") to RelayRefusal.Kind.DISABLED,
            Triple(403, "not_invited", "") to RelayRefusal.Kind.DISABLED,
            Triple(403, "signup_closed", "") to RelayRefusal.Kind.DISABLED,
            Triple(429, "rate_limited", "") to RelayRefusal.Kind.BUSY,
            Triple(429, "too_many_in_flight", "") to RelayRefusal.Kind.BUSY,
            Triple(429, "provider_busy", ""","retry_after":2.5""") to RelayRefusal.Kind.BUSY,
            Triple(429, "locked", "") to RelayRefusal.Kind.BUSY,
            Triple(404, "model_not_offered", "") to RelayRefusal.Kind.MODEL,
            Triple(503, "service_paused", "") to RelayRefusal.Kind.SERVICE_PAUSED,
            Triple(503, "sync_paused", "") to RelayRefusal.Kind.SYNC_PAUSED,
            Triple(503, "hub_paused", "") to RelayRefusal.Kind.HUB_PAUSED,
            Triple(502, "upstream", "") to RelayRefusal.Kind.RELAY_DOWN,
        )
        for ((key, kind) in expected) {
            val (status, code, extra) = key
            val r = relay(status, code, extra = extra)
            assertEquals(code, kind, r.kind)
            assertEquals(code, r.code)
            assertEquals(status, r.status)
            assertEquals("refused", r.message)
        }
        // every code in the relay's list is covered by the table above
        assertEquals(RelayRefusal.RELAY_CODES, expected.keys.map { it.second }.toSet())
    }

    @Test fun `the flags - paused and retry_after - come through, and the allowance kinds are one card`() {
        val paused = relay(429, "allowance_exhausted", extra = ""","paused":true,"left":1.5,"grant":5""")
        assertTrue(paused.paused)
        assertTrue(paused.isAllowance)
        val busy = relay(429, "provider_busy", extra = ""","retry_after":2.5""")
        assertEquals(3, busy.retryAfterS) // rounded up to whole seconds
        assertFalse(busy.isAllowance)
        assertNull(relay(429, "rate_limited").retryAfterS)
        assertTrue(relay(429, "daily_cap").isAllowance)
        assertTrue(relay(402, "out_of_tokens").isAllowance)
        assertFalse(relay(413, "too_large").isAllowance)
        // the exception describe() reads carries the same
        val e = busy.toException()
        assertEquals("provider_busy", e.code)
        assertEquals(429, e.status)
        assertEquals(3, e.retryAfterS)
    }

    @Test fun `a plain 413 from a proxy on the way to the relay is too large, another provider's 429 is not ours`() {
        // nginx's page, no JSON — the call went to the relay's host
        val r = RelayRefusal.parse(413, "<html><head><title>413 Request Entity Too Large</title></head></html>", fromRelay = true)!!
        assertEquals(RelayRefusal.Kind.TOO_LARGE, r.kind)
        assertEquals("http_413", r.code)
        assertEquals("", r.message) // HTML is not a sentence
        // a plain-text body is kept as the relay's words
        assertEquals("Request too large", RelayRefusal.parse(413, "Request too large", fromRelay = true)!!.message)
        // the relay fell over: a bare 502 from the host is RELAY_DOWN
        assertEquals(RelayRefusal.Kind.RELAY_DOWN, RelayRefusal.parse(502, "Bad Gateway", fromRelay = true)!!.kind)
        // OpenAI's own 429 — not the relay's host, not the relay's shape — keeps upstream's card
        assertNull(RelayRefusal.parse(429, """{"error":{"message":"Rate limit reached","type":"tokens","code":"rate_limit_exceeded"}}"""))
        assertNull(RelayRefusal.parse(429, """{"error":{"message":"Rate limit reached","type":"tokens","code":"rate_limit_exceeded"}}""", fromRelay = true))
        assertNull(RelayRefusal.parse(413, "Request too large")) // a 413 from a provider of one's own
        assertNull(RelayRefusal.parse(500, null))
        // the relay's code without the type still counts (an older relay)
        assertEquals(RelayRefusal.Kind.TOO_LARGE, RelayRefusal.parse(413, """{"error":{"message":"too big","code":"too_large"}}""")!!.kind)
    }

    @Test fun `a content check saying no is one kind, from the relay or from a key of one's own, and nothing splits it`() {
        // the relay's 400: `content_rejected`, the provider's line under `upstream`
        val relayBody = """{"error":{"message":"The model provider's content check declined this request; try different words","type":"upstream","code":"content_rejected","upstream":"<400> InternalError.Algo.DataInspectionFailed: Input data may contain inappropriate content."}}"""
        val fromRelay = RelayRefusal.parse(400, relayBody, fromRelay = true)!!
        assertEquals(RelayRefusal.Kind.CONTENT_REJECTED, fromRelay.kind)
        assertEquals("content_rejected", fromRelay.code)
        assertEquals("The model provider's content check declined this request; try different words", fromRelay.message)
        assertFalse(fromRelay.isAllowance)
        // the same inside a stream: the relay answers 200 and puts the error in a data: line, so the
        // client maps it with status 0; the code alone says what it is
        assertEquals(RelayRefusal.Kind.CONTENT_REJECTED, RelayRefusal.parse(0, relayBody)!!.kind)
        // Bailian's own 400 on a key of one's own: not the relay's shape, the same kind and code
        val bailian = """{"error":{"message":"<400> InternalError.Algo.DataInspectionFailed: Input data may contain inappropriate content.","type":"invalid_request_error","code":"data_inspection_failed"}}"""
        val own = RelayRefusal.parse(400, bailian)!!
        assertEquals(RelayRefusal.Kind.CONTENT_REJECTED, own.kind)
        assertEquals("content_rejected", own.code)
        assertTrue(own.message.startsWith("<400> InternalError.Algo.DataInspectionFailed"))
        // an older relay passing the provider's words through as upstream_400 lands on the same kind
        assertEquals(
            RelayRefusal.Kind.CONTENT_REJECTED,
            RelayRefusal.parse(400, """{"error":{"message":"<400> InternalError.Algo.DataInspectionFailed: Input data may contain inappropriate content.","type":"upstream","code":"upstream_400"}}""")!!.kind,
        )
        // another provider's 400 is still not ours
        assertNull(RelayRefusal.parse(400, """{"error":{"message":"Invalid value for 'temperature'","type":"invalid_request_error","code":"invalid_value"}}"""))
        assertNull(RelayRefusal.parse(400, """{"error":{"message":"Invalid value for 'temperature'","type":"invalid_request_error","code":"invalid_value"}}""", fromRelay = true))
        // the stored line survives a reload
        assertEquals(own, RelayRefusal.fromCanonical(RelayRefusal.canonical(own)))
        // the compaction's split-retry leaves a content check alone: the words are the matter, not the size.
        // The HTTP path's "[400] …", the stream's "[0] …", and the provider's own line all count
        assertFalse(shouldSplitOnError(LLMError.ProviderError("[400] The model provider's content check declined this request; try different words")))
        assertFalse(shouldSplitOnError(LLMError.ProviderError("[0] The model provider's content check declined this request; try different words")))
        assertFalse(shouldSplitOnError(LLMError.ProviderError("[400] <400> InternalError.Algo.DataInspectionFailed: Input data may contain inappropriate content.")))
        // an over-length refusal still splits, as upstream's test expects
        assertTrue(shouldSplitOnError(LLMError.ProviderError("[400] Your input exceeds the context window of this model")))
        assertTrue(RelayRefusal.contentCheck("content_rejected"))
        assertFalse(RelayRefusal.contentCheck(null))
        assertFalse(RelayRefusal.contentCheck("Model not exist."))
    }

    @Test fun `the stored line round-trips, with the message and the flags`() {
        val r = RelayRefusal.Refusal(RelayRefusal.Kind.BUSY, 429, "provider_busy", "Busy: try later", retryAfterS = 7)
        val line = RelayRefusal.canonical(r)
        assertTrue(line.startsWith("nm_relay:busy:429:provider_busy:7:0|"))
        assertEquals(r, RelayRefusal.fromCanonical(line))
        val paused = RelayRefusal.Refusal(RelayRefusal.Kind.ALLOWANCE_PAUSED, 429, "allowance_exhausted", "", paused = true)
        assertEquals(paused, RelayRefusal.fromCanonical(RelayRefusal.canonical(paused)))
        // a message with a pipe or a newline survives
        val odd = RelayRefusal.Refusal(RelayRefusal.Kind.OTHER, 418, "teapot", "a | b\nc")
        assertEquals("a | b c", RelayRefusal.fromCanonical(RelayRefusal.canonical(odd))!!.message)
        // not ours
        assertNull(RelayRefusal.fromCanonical("nm_reach:unreachable|…"))
        assertNull(RelayRefusal.fromCanonical("Rate limited"))
        assertNull(RelayRefusal.fromCanonical("nm_relay:nonsense:1:2:3:0|x"))
    }
}
