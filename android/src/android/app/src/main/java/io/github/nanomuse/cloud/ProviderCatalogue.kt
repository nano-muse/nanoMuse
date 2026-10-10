package io.github.nanomuse.cloud

import android.content.Context
import com.openminis.app.data.model.ProviderCredential
import com.openminis.app.data.model.ProviderInstance
import com.openminis.app.data.model.ProviderType
import org.json.JSONArray
import org.json.JSONObject
import java.util.Locale

/**
 * One vendor of the own-key catalogue (contract C11): where its endpoint is, where a key is
 * made, how one signs in, where it signs people up, and what its models can do — `chat`,
 * `vision` (the hands' screen), `image` (pictures), `video` (clips). Facts, not opinions: the
 * app says what each covers and recommends none.
 */
data class CatalogueProvider(
    val id: String,
    val name: String,
    val nameZh: String,
    /** `openai` | `openai-responses` | `anthropic` | `gemini`. */
    val protocol: String,
    val baseUrl: String,
    /** The endpoint outside mainland China when the vendor runs two (Kimi, MiniMax). */
    val baseUrlGlobal: String?,
    val keyUrl: String,
    val keyUrlGlobal: String?,
    val keyHint: String?,
    /** `key` | `none` | `oauth-chatgpt` | `oauth-claude` | `oauth-openrouter` | `device-kimi`. */
    val auth: List<String>,
    /** A sign-in that gives less than the key does (`oauth-chatgpt`: chat and vision only). */
    val authCapabilities: Map<String, Set<String>>,
    /** `cn`, `global`, or both — where sign-up and the endpoint work. */
    val regions: Set<String>,
    val capabilities: Set<String>,
    /** `custom`: the person says what the endpoint can do; the catalogue does not. */
    val userCapabilities: Boolean,
    val defaults: Map<String, String>,
    val note: String,
    val noteZh: String,
    val verified: String,
    /**
     * The header the vendor wants one stable id per conversation in (OpenCode Go:
     * `x-opencode-session`); [io.github.nanomuse.net.OpenCodeSession] sends it. Null for the rest.
     */
    val sessionHeader: String? = null,
) {
    fun displayName(chinese: Boolean): String = if (chinese && nameZh.isNotBlank()) nameZh else name
    fun note(chinese: Boolean): String = if (chinese && noteZh.isNotBlank()) noteZh else note
    fun baseUrl(mainland: Boolean): String = if (!mainland && !baseUrlGlobal.isNullOrBlank()) baseUrlGlobal else baseUrl
    fun keyUrl(mainland: Boolean): String = if (!mainland && !keyUrlGlobal.isNullOrBlank()) keyUrlGlobal else keyUrl

    /** The sign-in this vendor offers besides a key, if any (`oauth-chatgpt`, `oauth-claude`, `oauth-openrouter`, `device-kimi`). */
    val signIn: String? get() = auth.firstOrNull { it.startsWith("oauth-") || it.startsWith("device-") }

    /** Takes a pasted key. */
    val takesKey: Boolean get() = "key" in auth

    /** Needs no credential at all — a server the person runs (Ollama, LM Studio, vLLM). */
    val local: Boolean get() = "none" in auth && signIn == null && baseUrl.startsWith("http://")

    /** What the models can do under [auth] (null: the key). */
    fun capabilitiesFor(auth: String?): Set<String> = auth?.let { authCapabilities[it] } ?: capabilities

    /** True when sign-up and the endpoint work in the region. */
    fun servesMainland(): Boolean = ProviderCatalogue.REGION_CN in regions
    fun servesGlobal(): Boolean = ProviderCatalogue.REGION_GLOBAL in regions

    /** The host of the endpoint (either edition), for matching a configured provider by its base URL. */
    fun hosts(): Set<String> = listOfNotNull(baseUrl, baseUrlGlobal).mapNotNull { ProviderCatalogue.host(it) }.toSet()
}

/**
 * The own-key provider catalogue — `assets/nanomuse/providers.json`, a copy of the runtime's
 * `nanomuse/llm/providers.json` written by `scripts/providers-json.mjs` (never edited here).
 * Read once per process. [ordered] is the order the allowance card shows them in; [match]
 * says which vendor a configured provider is, so [Capabilities] can tell what it covers.
 */
object ProviderCatalogue {
    const val ASSET = "nanomuse/providers.json"

    const val CHAT = "chat"
    const val VISION = "vision"
    const val IMAGE = "image"
    const val VIDEO = "video"

    const val REGION_CN = "cn"
    const val REGION_GLOBAL = "global"

    const val BAILIAN = "bailian"
    const val OPENROUTER = "openrouter"
    const val OPENAI = "openai"
    const val ANTHROPIC = "anthropic"
    const val GEMINI = "gemini"
    const val MOONSHOT = "moonshot"
    const val XAI = "xai"
    const val CUSTOM = "custom"

    const val AUTH_KEY = "key"
    const val AUTH_CHATGPT = "oauth-chatgpt"
    const val AUTH_CLAUDE = "oauth-claude"
    const val AUTH_OPENROUTER = "oauth-openrouter"
    const val AUTH_KIMI = "device-kimi"

    @Volatile private var cached: List<CatalogueProvider>? = null

    /** The catalogue as shipped in the APK; empty if the asset cannot be read (it is always there). */
    fun load(context: Context): List<CatalogueProvider> = cached ?: synchronized(this) {
        cached ?: runCatching {
            context.applicationContext.assets.open(ASSET).bufferedReader().use { it.readText() }
        }.map { parse(it) }.getOrDefault(emptyList()).also { cached = it }
    }

    /**
     * The vendor with this id: the bundled catalogue's entry, else the relay's own
     * (`spend.guidance`, contract C11) — so a vendor the relay lists before the app is
     * updated still opens a pre-filled form.
     */
    fun byId(context: Context, id: String?): CatalogueProvider? {
        val key = id?.trim()?.lowercase(Locale.ROOT)?.takeIf { it.isNotEmpty() } ?: return null
        return load(context).firstOrNull { it.id == key }
            ?: NanoMuseCloud.guidance(context)?.let { g -> (g.providers + g.local).firstOrNull { it.id == key } }
    }

    /** The file's `providers[]`; a malformed entry is skipped rather than failing the whole list. */
    fun parse(json: String): List<CatalogueProvider> {
        val root = JSONObject(json)
        val arr = root.optJSONArray("providers") ?: JSONArray()
        return (0 until arr.length()).mapNotNull { i -> arr.optJSONObject(i)?.let { runCatching { entry(it) }.getOrNull() } }
    }

    private fun entry(o: JSONObject): CatalogueProvider? {
        val id = o.optString("id").takeIf { it.isNotBlank() } ?: return null
        val authCaps = o.optJSONObject("auth_capabilities")?.let { ac ->
            ac.keys().asSequence().associateWith { k -> strings(ac.optJSONArray(k)).toSet() }
        } ?: emptyMap()
        val defaults = o.optJSONObject("defaults")?.let { d -> d.keys().asSequence().associateWith { k -> d.optString(k) } } ?: emptyMap()
        return CatalogueProvider(
            id = id,
            name = o.optString("name").ifBlank { id },
            nameZh = o.optString("name_zh"),
            protocol = o.optString("protocol", "openai"),
            baseUrl = o.optString("base_url"),
            baseUrlGlobal = o.optString("base_url_global").takeIf { it.isNotBlank() },
            keyUrl = o.optString("key_url"),
            keyUrlGlobal = o.optString("key_url_global").takeIf { it.isNotBlank() },
            keyHint = o.optString("key_hint").takeIf { it.isNotBlank() },
            auth = strings(o.optJSONArray("auth")),
            authCapabilities = authCaps,
            regions = strings(o.optJSONArray("regions")).toSet(),
            capabilities = strings(o.optJSONArray("capabilities")).toSet(),
            userCapabilities = o.optBoolean("user_capabilities", false),
            defaults = defaults,
            note = o.optString("note"),
            noteZh = o.optString("note_zh"),
            verified = o.optString("verified"),
            sessionHeader = o.optString("session_header").takeIf { it.isNotBlank() },
        )
    }

    private fun strings(arr: JSONArray?): List<String> =
        (0 until (arr?.length() ?: 0)).map { arr!!.optString(it) }.filter { it.isNotBlank() }

    /**
     * The order the allowance card lists the vendors in (contract C11): the region's first —
     * on the mainland Bailian, then the rest that sign up there; elsewhere OpenRouter and
     * OpenAI, then the rest that serve the world — then the other region's, each group as the
     * file orders it. Servers one runs oneself and the blank "any endpoint" entry are not
     * ways on from a spent allowance on a phone and are left out.
     */
    fun ordered(list: List<CatalogueProvider>, mainland: Boolean): List<CatalogueProvider> {
        val shown = list.filter { !it.local && it.id != CUSTOM && it.baseUrl.isNotBlank() }
        val first = if (mainland) listOf(BAILIAN) else listOf(OPENROUTER, OPENAI)
        val home = shown.filter { if (mainland) it.servesMainland() else it.servesGlobal() }
        val away = shown.filter { it !in home }
        val lead = first.mapNotNull { id -> home.firstOrNull { it.id == id } }
        return lead + home.filter { it !in lead } + away
    }

    /** The vendors whose plan can sign in here without a key (ChatGPT, Claude, Kimi, OpenRouter), in the card's order. */
    fun signIns(list: List<CatalogueProvider>, mainland: Boolean): List<CatalogueProvider> =
        ordered(list, mainland).filter { it.signIn != null }

    /**
     * Which catalogue vendor a configured provider is: by the host of its base URL first (a
     * Bailian key pasted into an "OpenAI / compatible" form is Bailian's), else by the
     * provider type for the vendors upstream has a type for. Null for an endpoint the
     * catalogue does not know — a gateway, a relay of one's own, nanoMuse Cloud.
     */
    fun match(list: List<CatalogueProvider>, inst: ProviderInstance): CatalogueProvider? {
        val host = inst.customBaseURL?.let { host(it) }
        if (host != null) {
            // two vendors on one host (OpenCode Zen and Go) are told apart by the whole address
            val url = inst.customBaseURL?.trim()?.trimEnd('/')
            list.firstOrNull { p -> listOfNotNull(p.baseUrl, p.baseUrlGlobal).any { it.trimEnd('/') == url } }?.let { return it }
            list.firstOrNull { host in it.hosts() }?.let { return it }
            // the vendor's own host under a different path (an older /compatible-mode without /v1, a regional console)
            list.firstOrNull { p -> p.hosts().any { h -> host.endsWith(".$h") || h.endsWith(".$host") } }?.let { return it }
            return null
        }
        val id = when (inst.providerType) {
            ProviderType.openAI, ProviderType.openAIResponses -> OPENAI
            ProviderType.anthropic -> ANTHROPIC
            ProviderType.gemini -> GEMINI
            ProviderType.openRouter -> OPENROUTER
            ProviderType.xAI -> XAI
            ProviderType.kimiCode -> MOONSHOT
            ProviderType.antigravity, ProviderType.unsupported -> return null
        }
        return list.firstOrNull { it.id == id }
    }

    /** The catalogue's word for how [inst] signed in, when it did (`oauth-chatgpt` for an OpenAI OAuth instance, …). */
    fun authOf(inst: ProviderInstance, provider: CatalogueProvider): String? {
        if (inst.credentialType != ProviderCredential.oauth) return null
        return provider.signIn
    }

    /** The host of a URL, lower-case, or null when it is not one. */
    fun host(url: String): String? = runCatching {
        val u = java.net.URI(url.trim())
        u.host?.lowercase(Locale.ROOT)?.takeIf { it.isNotBlank() }
    }.getOrNull()

    /** The UI's language is Chinese (simplified or traditional): the catalogue's `name_zh` / `note_zh` read better. */
    fun chinese(context: Context): Boolean =
        (context.resources.configuration.locales[0] ?: Locale.getDefault()).language == "zh"
}
