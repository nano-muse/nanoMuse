package com.openminis.app.provider.openai

import android.content.Context
import com.openminis.app.data.model.LLMModel
import com.openminis.app.data.model.normalizeModalities
import com.openminis.app.logging.AppLogger
import com.openminis.app.provider.ModelsDevApi
import com.openminis.app.provider.ProviderModelsCache
import com.openminis.app.provider.applyUserAgentOverride
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject

object OpenAIModelsApi {
    private const val TAG = "OpenAIModelsApi"
    private val client = OkHttpClient.Builder().proxyAuthenticator(io.github.nanomuse.net.OwnProviderProxy.authenticator).build() // nanoMuse: Settings → Network, a proxy with a password
    private val cache = ProviderModelsCache("openai")

    /**
     * Static model list for Codex OAuth (tokens can't call /v1/models).
     * Matches iOS `LLMModel.allOpenAICodexOAuth` (Providers/LLMTypes.swift).
     * Order is preserved so the model picker shows the same default rank.
     */
    // T119: every GPT-5.x model on Codex OAuth supports reasoning_effort
    // (`/v1/responses` requires the `reasoning` object on this auth path),
    // so set supportsReasoning = true up front. Without it the Thinking
    // pill in chat is disabled and the user can't pick low/medium/high.
    // nanoMuse: GPT-6 series and live Codex OAuth models refresh (#475)
    private val builtInCodexOAuthModels: List<LLMModel> = listOf(
        LLMModel("gpt-6.1-sol", "GPT-6.1 Sol", "OpenAI", supportsReasoning = true),
        LLMModel("gpt-6-sol", "GPT-6 Sol", "OpenAI", supportsReasoning = true),
        LLMModel("gpt-6-luna", "GPT-6 Luna", "OpenAI", supportsReasoning = true),
        LLMModel("gpt-6-astra", "GPT-6 Astra", "OpenAI", supportsReasoning = true),
        // [T-android-thinking-level-arch] GPT-5.6 family — Codex OAuth only
        // (not in LLMModel.allOpenAI, matching iOS). sol/terra reach ULTRA,
        // luna reaches MAX (see ThinkingLevelCatalog).
        LLMModel("gpt-5.6-sol", "GPT-5.6 Sol", "OpenAI", supportsReasoning = true),
        LLMModel("gpt-5.6-terra", "GPT-5.6 Terra", "OpenAI", supportsReasoning = true),
        LLMModel("gpt-5.6-luna", "GPT-5.6 Luna", "OpenAI", supportsReasoning = true),
        LLMModel("gpt-5.5", "GPT-5.5", "OpenAI", supportsReasoning = true),
        LLMModel("gpt-5.4", "GPT-5.4", "OpenAI", supportsReasoning = true),
        // [T-codex-oauth-model-prune] Verified callable on a live
        // ChatGPT-account token (2026-08-01); we had never listed it.
        LLMModel("gpt-5.4-mini", "GPT-5.4 Mini", "OpenAI", supportsReasoning = true),
    )

    private val codexImageModels: List<LLMModel> = listOf(
        LLMModel(
            id = "gpt-image-2",
            displayName = "GPT Image 2",
            provider = "OpenAI",
            inputModalities = listOf("text", "image"),
            outputModalities = listOf("image"),
        ),
    )

    fun fetchModelsOAuth(): List<LLMModel> = builtInCodexOAuthModels.let {
        AppLogger.info(TAG, "Codex OAuth model list (${it.size} models): ${it.joinToString { m -> m.id }}")
        ModelsDevApi.enrichModels(it)
    } + codexImageModels

    // nanoMuse: use the same Codex client version for model discovery and responses.
    suspend fun fetchModelsOAuth(accessToken: String?, accountId: String? = null): List<LLMModel> = withContext(Dispatchers.IO) {
        val token = accessToken?.trim().orEmpty()
        if (token.isEmpty()) return@withContext fetchModelsOAuth()
        val live = try {
            val builder = Request.Builder()
                .url("https://chatgpt.com/backend-api/codex/models?client_version=${OpenAIProvider.CODEX_CLIENT_VERSION}")
                .header("Authorization", "Bearer $token")
                .header("Originator", "codex_cli_rs")
                .header("Accept", "application/json")
            if (!accountId.isNullOrBlank()) {
                builder.header("Chatgpt-Account-Id", accountId)
            }
            client.newCall(builder.build()).execute().use { resp ->
                val body = resp.body?.string().orEmpty()
                if (!resp.isSuccessful || body.isEmpty()) emptyList() else parseCodexModelsJson(body)
            }
        } catch (e: Exception) {
            AppLogger.warning(TAG, "Codex live models fetch failed, using built-in list: ${e.message}")
            emptyList()
        }
        if (live.isEmpty()) return@withContext fetchModelsOAuth()
        // nanoMuse: a live catalogue is authoritative for this account/client.
        // Do not append built-in entries that may be rejected with HTTP 400.
        ModelsDevApi.enrichModels(live) + codexImageModels
    }

    // nanoMuse: parse `{"models":[{"slug":"gpt-6.1-sol","display_name":"...","visibility":"list"}, ...]}`
    internal fun parseCodexModelsJson(body: String): List<LLMModel> = try {
        val rows = JSONObject(body).optJSONArray("models") ?: JSONArray()
        val out = mutableListOf<LLMModel>()
        val seen = mutableSetOf<String>()
        for (i in 0 until rows.length()) {
            val row = rows.optJSONObject(i) ?: continue
            val vis = row.optString("visibility", "")
            if (vis == "hide" || vis == "none") continue
            val slug = row.optString("slug").ifBlank { row.optString("id") }.trim()
            if (slug.isEmpty() || !seen.add(slug)) continue
            val builtIn = builtInCodexOAuthModels.find { it.id == slug }
            val title = row.optString("display_name").ifBlank { row.optString("title") }.trim()
            val name = title.ifEmpty { builtIn?.displayName ?: LLMModel.modelDisplayName(slug) }
            out.add(LLMModel(slug, name, "OpenAI", supportsReasoning = true))
        }
        out
    } catch (_: Exception) {
        emptyList()
    }

    // Chat-capable model prefixes (matching iOS)
    private val chatPrefixes = listOf("gpt-", "o1", "o3", "o4-", "codex-", "chatgpt-")

    // Suffixes to exclude (matching iOS)
    private val excludeSuffixes = listOf(
        "-instruct", "-realtime", "-audio", "-transcribe", "-tts", "-embedding"
    )

    suspend fun fetchModels(
        apiKey: String,
        baseURL: String? = null,
        context: Context? = null,
        forceRefresh: Boolean = false,
        // [T-provider-custom-user-agent] Per-provider UA override; null/blank
        // keeps the default UA. Threaded from ProviderRepository.refreshModels.
        customUserAgent: String? = null,
    ): List<LLMModel> = withContext(Dispatchers.IO) {
        val isCustomBase = baseURL != null && !isOfficialOpenAI(baseURL)
        // For third-party endpoints (vLLM, Ollama, etc.), return empty on failure
        // so the caller preserves existing models instead of replacing with built-in GPT list.
        val fallback = if (isCustomBase) emptyList() else LLMModel.allOpenAI

        val cacheKey = (baseURL ?: "") + "|" + apiKey
        if (context != null && !forceRefresh) {
            cache.load(context, cacheKey)?.let { return@withContext it }
        }

        val url = buildURL(baseURL)
        val request = Request.Builder()
            .url(url)
            .header("Authorization", "Bearer $apiKey")
            // [T-provider-custom-user-agent] models-list UA override.
            .applyUserAgentOverride(customUserAgent)
            .build()

        val response = client.newCall(request).execute()
        val body = response.body?.string() ?: return@withContext fallback

        if (!response.isSuccessful) {
            if (context != null && (response.code == 401 || response.code == 403)) {
                cache.invalidate(context, cacheKey)
            }
            return@withContext fallback
        }

        val models = try {
            val json = JSONObject(body)
            val data = json.optJSONArray("data") ?: return@withContext fallback
            val parsed = mutableListOf<LLMModel>()
            for (i in 0 until data.length()) {
                val obj = data.getJSONObject(i)
                val id = obj.getString("id")

                // Only filter by chat prefixes for official OpenAI endpoints;
                // custom endpoints (vLLM, Ollama) may serve any model ID.
                if (!isCustomBase) {
                    if (!chatPrefixes.any { id.startsWith(it) }) continue
                    if (excludeSuffixes.any { id.contains(it) }) continue
                    if (id.contains(":ft-")) continue
                }

                val displayName = obj.optString("name", id)
                // Third-party gateways (vLLM, OpenRouter-compat proxies) often
                // report per-model modalities under `architecture.{input,output}_modalities`
                // the same way OpenRouter does — pick them up so vision/audio
                // models are routable without waiting for models.dev enrichment.
                val arch = obj.optJSONObject("architecture")
                // OpenAI / OpenRouter return modalities as `image_input` / `text_output` with
                // suffixes; the rest of the codebase (models.dev, capability fragments,
                // ModelEntryDetailScreen toggles) uses the bare form. Normalize at the parse
                // boundary so persisted overrides round-trip correctly through the toggles.
                val inputModalities = arch?.optJSONArray("input_modalities")?.toStringList().normalizeModalities()
                val outputModalities = arch?.optJSONArray("output_modalities")?.toStringList().normalizeModalities()

                // T119: known reasoning families (GPT-5.x, o-series, Codex
                // Mini) get supportsReasoning pre-set to true so the
                // Thinking pill enables before models.dev enrichment lands
                // — for brand-new ids (e.g. gpt-5.5) the catalog rarely has
                // the `reasoning` flag yet, and without this the pill
                // stays disabled.
                val idLower = id.lowercase()
                val knownReasoning = idLower.startsWith("gpt-5") ||
                    idLower.startsWith("gpt-6") || // nanoMuse: GPT-6 series (#475)
                    idLower.startsWith("o1") ||
                    idLower.startsWith("o3") ||
                    idLower.startsWith("o4") ||
                    idLower.contains("codex")

                parsed.add(
                    io.github.nanomuse.cloud.ModelCapacity.apply(LLMModel(
                        id = id,
                        displayName = displayName,
                        provider = if (isCustomBase) "Custom" else "OpenAI",
                        inputModalities = inputModalities,
                        outputModalities = outputModalities,
                        supportsReasoning = if (knownReasoning) true else null,
                    ), obj) // nanoMuse: retain capacities disclosed by the serving endpoint.
                )
            }
            if (parsed.isEmpty()) return@withContext fallback
            ModelsDevApi.enrichModels(parsed)
        } catch (_: Exception) {
            return@withContext fallback
        }

        if (context != null) cache.save(context, cacheKey, models)
        models
    }

    private fun JSONArray.toStringList(): List<String> {
        val out = ArrayList<String>(length())
        for (i in 0 until length()) {
            val s = optString(i, "")
            if (s.isNotEmpty()) out.add(s)
        }
        return out
    }

    /** Check if a base URL points to official OpenAI endpoints. */
    private fun isOfficialOpenAI(baseURL: String): Boolean {
        val lower = baseURL.lowercase()
        return lower.contains("api.openai.com") || lower.contains("chatgpt.com")
    }

    private fun buildURL(baseURL: String?): String {
        if (baseURL == null) return "https://api.openai.com/v1/models"
        // baseURL is ProviderConfig.effectiveBaseURL — it already has /v1 iff the
        // appendV1Suffix toggle is on. Only append /models; never force /v1, or the
        // toggle is overridden and services without /v1 return 404.
        val base = baseURL.trimEnd('/')
        return "$base/models"
    }
}
