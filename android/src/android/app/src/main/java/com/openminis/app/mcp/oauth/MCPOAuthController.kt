package com.openminis.app.mcp.oauth

import android.content.Context
import android.net.Uri
import androidx.browser.customtabs.CustomTabsIntent
import com.openminis.app.auth.OAuthCallbackServer
import com.openminis.app.logging.AppLogger
// nanoMuse: Safe JSON token negotiation and localized exchange failures.
import com.openminis.app.R
import io.github.nanomuse.connectors.McpOAuthTokens
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import java.net.URI
import java.net.URLEncoder
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume

/**
 * [T-android-mcp-oauth] Drives the MCP Static-OAuth PKCE Authorization Code
 * flow (RFC 7636 + RFC 8252 loopback redirect + RFC 8707 resource). Android
 * port of iOS `MCPOAuthController.authorize`, reusing the app's existing
 * [OAuthCallbackServer] + Chrome Custom Tab pattern (same as ClaudeOAuthManager).
 *
 * Phase 2 scope: authorize() runs the browser round-trip and token exchange and
 * stores the issued tokens in [MCPOAuthStore]. The in-guest transport bridge
 * (materializing refresh material for minis-mcp-cli) and autonomous refresh are
 * intentionally out of this phase.
 */
class MCPOAuthController(private val context: Context) {

    sealed class Result {
        object Success : Result()
        object Cancelled : Result()
        data class Failed(val message: String) : Result()
    }

    private val http: OkHttpClient by lazy {
        OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(30, TimeUnit.SECONDS)
            .build()
    }

    @Volatile
    private var callbackServer: OAuthCallbackServer? = null

    /**
     * Run the full authorize flow for [server] against [oauth]. [serverUrl] is
     * the server's own URL, used verbatim as the RFC 8707 resource indicator
     * (canonicalized). Opens the authorization page in a Custom Tab, waits (up
     * to 5 min) for the loopback callback, verifies state, exchanges the code,
     * and persists tokens. Never throws — returns a [Result].
     */
    suspend fun authorize(server: String, serverUrl: String?, oauth: MCPOAuthConfig): Result {
        if (!oauth.isConfigured) {
            return Result.Failed("OAuth is not fully configured (client id + endpoints required).")
        }
        val redirect = redirectUri(oauth)
        val redirectHost = runCatching { URI(redirect).host?.lowercase() }.getOrNull()
        if (redirectHost != "localhost" && redirectHost != "127.0.0.1") {
            return Result.Failed("Redirect URI must be a loopback address, e.g. $DEFAULT_REDIRECT_URI.")
        }
        val port = runCatching { URI(redirect).port.takeIf { it > 0 } }.getOrNull() ?: LOOPBACK_PORT
        val resource = McpPkce.canonicalResourceUri(serverUrl)
        val pkce = McpPkce.newPkce()
        val authUrl = McpPkce.buildAuthorizationUrl(
            authorizationEndpoint = oauth.authorizationEndpoint,
            clientId = oauth.clientId,
            redirectUri = redirect,
            pkce = pkce,
            resource = resource,
            scopes = oauth.scopes,
        )

        return withContext(Dispatchers.IO) {
            callbackServer?.stop()
            callbackServer = null

            val callback = try {
                suspendCancellableCoroutine<Pair<String, String?>?> { cont ->
                    val srv = OAuthCallbackServer(port) { code, state ->
                        if (cont.isActive) cont.resume(code to state)
                    }
                    callbackServer = srv
                    // If the user dismisses the Custom Tab, stop() fires this so
                    // we don't hang until the OS eventually tears the socket down.
                    srv.onExternalCancel = { if (cont.isActive) cont.resume(null) }
                    srv.start()
                    AppLogger.info(TAG, "[Authorize] '$server' callback server on :$port")

                    cont.invokeOnCancellation {
                        srv.stop()
                        callbackServer = null
                    }

                    // Do NOT set FLAG_ACTIVITY_NEW_TASK — MainActivity is
                    // singleTask (matches ClaudeOAuthManager's note about IME).
                    CustomTabsIntent.Builder().setShowTitle(true).build()
                        .launchUrl(context, Uri.parse(authUrl))
                    AppLogger.info(TAG, "[Authorize] '$server' opened Custom Tab")
                }
            } finally {
                callbackServer?.stop()
                callbackServer = null
            } ?: return@withContext Result.Cancelled

            val (code, state) = callback
            if (state != null && state != pkce.state) {
                AppLogger.warning(TAG, "[Authorize] '$server' state mismatch")
                return@withContext Result.Failed("State mismatch in the OAuth callback.")
            }

            exchangeCode(server, oauth, redirect, resource, code, pkce.verifier)
        }
    }

    private fun exchangeCode(
        server: String,
        oauth: MCPOAuthConfig,
        redirect: String,
        resource: String?,
        code: String,
        verifier: String,
    ): Result {
        val body = buildTokenExchangeBody(
            code = code,
            redirect = redirect,
            clientId = oauth.clientId,
            verifier = verifier,
            clientSecret = MCPOAuthStore.clientSecret(context, server),
            resource = resource,
        )
        return try {
            // nanoMuse: Negotiate JSON and include invalid endpoint errors in safe failure handling.
            val request = McpOAuthTokens.request(oauth.tokenEndpoint, body)
            http.newCall(request).execute().use { resp ->
                // nanoMuse: Reject OAuth errors even on HTTP 200; never expose response text.
                val tokens = McpOAuthTokens.parse(resp.code, resp.body?.string().orEmpty())
                val expiresIn = tokens.expiresIn
                val expiresAt = if (expiresIn > 0) System.currentTimeMillis() + expiresIn * 1000 else 0L
                MCPOAuthStore.setTokens(
                    context, server,
                    MCPOAuthStore.StoredTokens(
                        // nanoMuse: Persist only validated token fields.
                        accessToken = tokens.accessToken,
                        refreshToken = tokens.refreshToken,
                        expiresAtMs = expiresAt,
                    ),
                )
                AppLogger.info(
                    TAG,
                    // nanoMuse: Log token metadata only.
                    "[Authorize] '$server' OK (hasRefresh=${tokens.refreshToken != null}, expiresIn=${expiresIn}s)",
                )
                Result.Success
            }
        } catch (e: Exception) {
            // nanoMuse: Provider bodies and exception messages may contain credentials.
            val code = (e as? McpOAuthTokens.Failure)?.code ?: "connection_failed"
            AppLogger.error(TAG, "[Authorize] token exchange failed: $code")
            Result.Failed(context.getString(R.string.nm_mcp_oauth_token_failed, code))
        }
    }

    private fun redirectUri(oauth: MCPOAuthConfig): String =
        oauth.redirectUri?.trim()?.takeIf { it.isNotEmpty() } ?: DEFAULT_REDIRECT_URI

    companion object {
        private const val TAG = "MCPOAuthController"

        /**
         * Assemble the form-urlencoded token-exchange body for the
         * authorization_code grant (MCP auth spec / RFC 6749). client_secret is
         * included only when present; the RFC 8707 `resource` only when non-null.
         * Extracted for unit testing. Mirrors iOS authorize()'s token form.
         */
        internal fun buildTokenExchangeBody(
            code: String,
            redirect: String,
            clientId: String,
            verifier: String,
            clientSecret: String?,
            resource: String?,
        ): String {
            val form = linkedMapOf(
                "grant_type" to "authorization_code",
                "code" to code,
                "redirect_uri" to redirect,
                "client_id" to clientId,
                "code_verifier" to verifier,
            )
            if (!clientSecret.isNullOrEmpty()) form["client_secret"] = clientSecret
            if (!resource.isNullOrEmpty()) form["resource"] = resource
            return form.entries.joinToString("&") { (k, v) ->
                "$k=${URLEncoder.encode(v, "UTF-8")}"
            }
        }

        /** Fixed loopback port for MCP OAuth — distinct from ClaudeOAuthManager's
         *  54545 so a concurrent login never collides. Mirrors iOS 54546. */
        const val LOOPBACK_PORT = 54546
        const val DEFAULT_REDIRECT_URI = "http://localhost:$LOOPBACK_PORT/callback"
    }
}
