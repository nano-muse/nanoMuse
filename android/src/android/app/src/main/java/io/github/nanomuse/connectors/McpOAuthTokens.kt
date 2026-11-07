package io.github.nanomuse.connectors

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject

/** Token responses are JSON by negotiation. Only fixed error codes may reach logs or UI. */
object McpOAuthTokens {
    data class Tokens(val accessToken: String, val refreshToken: String?, val expiresIn: Long)
    class Failure(val code: String) : Exception(code)

    private val errorCodes = setOf(
        "invalid_request", "invalid_client", "invalid_grant", "unauthorized_client",
        "unsupported_grant_type", "invalid_scope", "access_denied", "server_error",
        "temporarily_unavailable", "incorrect_client_credentials", "redirect_uri_mismatch",
        "bad_verification_code", "unverified_user_email",
    )

    fun request(endpoint: String, form: String): Request = try {
        Request.Builder()
            .url(endpoint)
            .header("Accept", "application/json")
            .post(form.toRequestBody("application/x-www-form-urlencoded".toMediaType()))
            .build()
    } catch (_: IllegalArgumentException) {
        throw Failure("invalid_token_endpoint")
    }

    fun parse(status: Int, body: String): Tokens {
        val json = try { JSONObject(body) } catch (_: Exception) { null }
        if (json?.has("error") == true) {
            val code = json.opt("error") as? String
            throw Failure(code?.takeIf { it in errorCodes } ?: "oauth_error")
        }
        if (status !in 200..299) throw Failure("HTTP $status")
        val response = json ?: throw Failure("invalid_token_response")
        val access = (response.opt("access_token") as? String)?.takeIf { it.isNotBlank() }
            ?: throw Failure("invalid_token_response")
        val refresh = (response.opt("refresh_token") as? String)?.takeIf { it.isNotBlank() }
        // Bound optional expiry before converting seconds to milliseconds.
        val expires = response.optLong("expires_in", 0).takeIf { it in 1..Int.MAX_VALUE } ?: 0
        return Tokens(access, refresh, expires)
    }
}
