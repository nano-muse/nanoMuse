package io.github.nanomuse.connectors

import android.content.Context
import com.openminis.app.MinisApp
import com.openminis.app.data.repository.MCPRepository
import com.openminis.app.logging.AppLogger
import com.openminis.app.mcp.oauth.MCPOAuthController
import com.openminis.app.mcp.oauth.MCPOAuthStore
import com.openminis.app.mcp.oauth.McpPkce
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import java.net.URLEncoder
import java.util.concurrent.TimeUnit

/**
 * Connecting a catalogue service on the phone. A connector is an MCP server entry whose id is
 * the catalogue id: open servers get the URL alone; a key goes into the headers (or the URL)
 * as the vendor wants it; OAuth runs discovery + registration ([McpAuthDiscovery]) and then the
 * upstream PKCE flow, and the access token is written into the entry's `Authorization` header,
 * which is how the in-guest MCP client ([T-android-mcp-oauth] left that bridge for later). Tokens
 * near their end are refreshed when the app starts and when the Connectors page opens.
 */
object Connectors {
    private const val TAG = "Connectors"
    private const val AUTH_HEADER = "Authorization"
    private const val REFRESH_AHEAD_MS = 2 * 60 * 1000L
    /** One supervised scope for the background refresh passes; a failed pass does not take the next one down. */
    private val refreshScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    sealed class Outcome {
        object Connected : Outcome()
        object Cancelled : Outcome()
        /** The server wants a key after all (an `auto` or `oauth` entry that answered 401 without an authorization server). */
        data class NeedsKey(val hint: String) : Outcome()
        /** The service registers no clients by itself: an OAuth app made at [developer] with [redirectUri], its client id pasted here. */
        data class NeedsClient(val developer: String?, val redirectUri: String) : Outcome()
        data class Failed(val message: String) : Outcome()
    }

    enum class State { Off, Connected, NeedsSignIn }

    private val http: OkHttpClient by lazy {
        OkHttpClient.Builder().connectTimeout(15, TimeUnit.SECONDS).readTimeout(15, TimeUnit.SECONDS).build()
    }

    fun repo(context: Context): MCPRepository? = (context.applicationContext as? MinisApp)?.mcpRepository

    /** Where a connector stands: not added, added and usable, or added but waiting for a sign-in. */
    fun state(context: Context, connector: Connector, servers: List<MCPRepository.MCPServerConfig>): State {
        val server = servers.firstOrNull { it.id == connector.serverId } ?: return State.Off
        val wantsToken = server.oauth?.isConfigured == true || connector.auth is ConnectorAuth.OAuth
        if (wantsToken && !server.headers.containsKey(AUTH_HEADER) && !MCPOAuthStore.isAuthorized(context, server.id)) return State.NeedsSignIn
        return State.Connected
    }

    /**
     * Connect [connector]. [key] is what the person pasted for a key-auth service (or for an
     * `auto`/`oauth` one that turned out to want a key). Suspends through the browser round-trip.
     */
    suspend fun connect(context: Context, connector: Connector, key: String? = null, clientId: String? = null, clientSecret: String? = null): Outcome {
        val repo = repo(context) ?: return Outcome.Failed("MCP is not ready")
        val auth = connector.auth
        if (!key.isNullOrBlank()) return withKey(repo, connector, auth as? ConnectorAuth.Key, key.trim())
        return when (auth) {
            is ConnectorAuth.None -> { add(repo, connector, server(connector)); Outcome.Connected }
            is ConnectorAuth.Key -> Outcome.NeedsKey(auth.where)
            is ConnectorAuth.OAuth -> {
                if (auth.clientIdRequired && clientId.isNullOrBlank()) Outcome.NeedsClient(auth.developer, MCPOAuthController.DEFAULT_REDIRECT_URI)
                else oauth(context, repo, connector, clientId, clientSecret)
            }
            is ConnectorAuth.Auto -> oauth(context, repo, connector, clientId, clientSecret)
        }
    }

    /** Remove the entry and everything kept for it (tokens, client secret). */
    fun disconnect(context: Context, connector: Connector) {
        repo(context)?.delete(connector.serverId)
        MCPOAuthStore.purge(context, connector.serverId)
    }

    /** Refresh the tokens about to lapse and rewrite their headers; off the main thread, quiet. */
    fun refreshStaleAsync(context: Context) {
        val app = context.applicationContext
        refreshScope.launch { runCatching { refreshStale(app) }.onFailure { AppLogger.warning(TAG, "refresh pass failed: ${it.message}") } }
    }

    private fun withKey(repo: MCPRepository, connector: Connector, auth: ConnectorAuth.Key?, key: String): Outcome {
        val header = auth?.header ?: if (auth?.query == null) AUTH_HEADER else null
        val prefix = auth?.prefix ?: "Bearer "
        val entry = if (header != null) {
            server(connector).copy(headers = mapOf(header to "$prefix$key"))
        } else {
            val sep = if (connector.url.contains('?')) '&' else '?'
            server(connector).copy(url = "${connector.url}$sep${auth?.query}=${URLEncoder.encode(key, "UTF-8")}")
        }
        add(repo, connector, entry)
        return Outcome.Connected
    }

    private suspend fun oauth(context: Context, repo: MCPRepository, connector: Connector, clientId: String? = null, clientSecret: String? = null): Outcome {
        val redirect = MCPOAuthController.DEFAULT_REDIRECT_URI
        val probe = try {
            withContext(Dispatchers.IO) { McpAuthDiscovery.probe(connector.url, redirect, clientId, clientSecret) }
        } catch (e: Exception) {
            AppLogger.warning(TAG, "probe '${connector.id}' failed: ${e.message}")
            return Outcome.Failed(e.message ?: "The server did not answer")
        }
        return when (probe) {
            is McpAuthDiscovery.Probe.Open -> { add(repo, connector, server(connector)); Outcome.Connected }
            is McpAuthDiscovery.Probe.Key -> Outcome.NeedsKey(probe.hint)
            is McpAuthDiscovery.Probe.NeedsClient -> Outcome.NeedsClient((connector.auth as? ConnectorAuth.OAuth)?.developer, redirect)
            is McpAuthDiscovery.Probe.OAuth -> {
                val id = connector.serverId
                MCPOAuthStore.setClientSecret(context, id, probe.clientSecret)
                // the entry first, so the upstream MCP page can re-authorize it too
                add(repo, connector, server(connector).copy(oauth = probe.config))
                when (val result = MCPOAuthController(context).authorize(id, connector.url, probe.config)) {
                    is MCPOAuthController.Result.Success -> {
                        materialize(context, repo, id)
                        Outcome.Connected
                    }
                    is MCPOAuthController.Result.Cancelled -> Outcome.Cancelled
                    is MCPOAuthController.Result.Failed -> Outcome.Failed(result.message)
                }
            }
        }
    }

    private fun server(connector: Connector) = MCPRepository.MCPServerConfig(
        id = connector.serverId,
        note = connector.about(),
        url = connector.url,
    )

    private fun add(repo: MCPRepository, connector: Connector, entry: MCPRepository.MCPServerConfig) {
        // keep what the person may have set on an existing entry (note, enabled flag)
        val existing = repo.servers.value.firstOrNull { it.id == connector.serverId }
        repo.add(if (existing == null) entry else entry.copy(note = existing.note ?: entry.note, enabled = existing.enabled, createdAt = existing.createdAt))
    }

    /** The stored access token → the entry's `Authorization` header, where the guest's MCP client reads it. */
    private fun materialize(context: Context, repo: MCPRepository, id: String) {
        val tokens = MCPOAuthStore.tokens(context, id) ?: return
        val server = repo.servers.value.firstOrNull { it.id == id } ?: return
        repo.update(server.copy(headers = server.headers + (AUTH_HEADER to "Bearer ${tokens.accessToken}")))
    }

    private fun refreshStale(context: Context) {
        val repo = repo(context) ?: return
        val now = System.currentTimeMillis()
        for (server in repo.servers.value) {
            val oauth = server.oauth?.takeIf { it.isConfigured } ?: continue
            val tokens = MCPOAuthStore.tokens(context, server.id) ?: continue
            val refresh = tokens.refreshToken ?: continue
            if (tokens.expiresAtMs <= 0 || tokens.expiresAtMs - now > REFRESH_AHEAD_MS) continue
            val form = linkedMapOf(
                "grant_type" to "refresh_token",
                "refresh_token" to refresh,
                "client_id" to oauth.clientId,
            )
            MCPOAuthStore.clientSecret(context, server.id)?.let { form["client_secret"] = it }
            McpPkce.canonicalResourceUri(server.url)?.let { form["resource"] = it }
            val body = form.entries.joinToString("&") { (k, v) -> "$k=${URLEncoder.encode(v, "UTF-8")}" }
            try {
                val req = McpOAuthTokens.request(oauth.tokenEndpoint, body)
                http.newCall(req).execute().use { resp ->
                    val updated = McpOAuthTokens.parse(resp.code, resp.body?.string().orEmpty())
                    val expiresIn = updated.expiresIn
                    MCPOAuthStore.setTokens(
                        context, server.id,
                        MCPOAuthStore.StoredTokens(
                            accessToken = updated.accessToken,
                            refreshToken = updated.refreshToken ?: refresh,
                            expiresAtMs = if (expiresIn > 0) System.currentTimeMillis() + expiresIn * 1000 else 0L,
                        ),
                    )
                    materialize(context, repo, server.id)
                    AppLogger.info(TAG, "refreshed '${server.id}'")
                }
            } catch (e: Exception) {
                val code = (e as? McpOAuthTokens.Failure)?.code ?: "connection_failed"
                AppLogger.warning(TAG, "token refresh failed: $code")
            }
        }
    }
}
