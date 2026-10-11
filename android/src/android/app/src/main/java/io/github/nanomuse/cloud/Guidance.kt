package io.github.nanomuse.cloud

import org.json.JSONArray
import org.json.JSONObject

/**
 * The ways-on card as data, the relay's way (relay 0.21, contract C11, `docs/cloud.md`):
 * `spend.guidance` of `/v1/me` and `guidance` beside a `429 allowance_exhausted` list the
 * providers for the person's region in order, each with what its key covers, the plans a
 * person may already pay for and which clients sign in with them, the local servers, the
 * docs link and the honest line about the ChatGPT sign-in. The card reads this first and
 * falls back to the bundled catalogue only when the relay sent none ([Ways.resolve]).
 *
 * Pure Kotlin: the unit tests run it without Android.
 */
data class Guidance(
    val region: String,
    val docs: String,
    /** The region's providers in the relay's order, as [CatalogueProvider]s (the public shape). */
    val providers: List<CatalogueProvider>,
    val plans: List<Plan>,
    val local: List<CatalogueProvider>,
    /** The honest line about the ChatGPT sign-in, English and Chinese; empty when the relay sent none. */
    val chatgptCaveat: String,
    val chatgptCaveatZh: String,
) {
    /** A plan a person may already pay for, and the sign-in that uses it. */
    data class Plan(
        val id: String,
        /** The catalogue id of the provider whose sign-in it is (`openai` for ChatGPT). */
        val provider: String,
        val name: String,
        /** `oauth-chatgpt` | `oauth-claude` | `device-kimi` | `oauth-openrouter`. */
        val auth: String,
        /** Which clients sign in with it: `android`, `ios`, `desktop`, `web`. */
        val clients: Set<String>,
        val covers: Set<String>,
    )

    fun caveat(chinese: Boolean): String = if (chinese && chatgptCaveatZh.isNotBlank()) chatgptCaveatZh else chatgptCaveat

    companion object {
        const val CLIENT = "android"

        /** The guidance in a `spend.guidance` / `error.guidance` object; null when it has no providers. */
        fun parse(json: String): Guidance? = runCatching { parse(JSONObject(json)) }.getOrNull()

        fun parse(o: JSONObject?): Guidance? {
            o ?: return null
            // `session_providers`: vendors that want a session id per conversation (OpenCode Go),
            // which the relay lists apart for the apps of before this one; this app sends the id
            // (io.github.nanomuse.net.OpenCodeSession), so they follow the relay's own list
            val providers = providers(o.optJSONArray("providers")).let { main ->
                if (main.isEmpty()) main else main + providers(o.optJSONArray("session_providers")).filter { s -> main.none { it.id == s.id } }
            }
            if (providers.isEmpty()) return null
            val plans = (0 until (o.optJSONArray("plans")?.length() ?: 0)).mapNotNull { i ->
                val p = o.optJSONArray("plans")?.optJSONObject(i) ?: return@mapNotNull null
                val id = p.optString("id").takeIf { it.isNotBlank() } ?: return@mapNotNull null
                Plan(
                    id = id,
                    provider = p.optString("provider"),
                    name = p.optString("name").ifBlank { id },
                    auth = p.optString("auth"),
                    clients = strings(p.optJSONArray("clients")).toSet(),
                    covers = strings(p.optJSONArray("covers")).toSet(),
                )
            }
            val caveats = o.optJSONObject("caveats")
            return Guidance(
                region = o.optString("region"),
                docs = o.optString("docs"),
                providers = providers,
                plans = plans,
                local = providers(o.optJSONArray("local")),
                chatgptCaveat = caveats?.optString("chatgpt").orEmpty(),
                chatgptCaveatZh = caveats?.optString("chatgpt_zh").orEmpty(),
            )
        }

        private fun providers(arr: JSONArray?): List<CatalogueProvider> =
            (0 until (arr?.length() ?: 0)).mapNotNull { i -> arr?.optJSONObject(i)?.let { provider(it) } }

        /**
         * One provider of the relay's list as a [CatalogueProvider]: the public shape has the
         * region's edition already chosen (`base_url`, `key_url`), `covers` for the key's
         * capabilities, and no `auth_capabilities` — a ChatGPT sign-in's narrower set is read
         * from the plan's own `covers`.
         */
        private fun provider(p: JSONObject): CatalogueProvider? {
            val id = p.optString("id").takeIf { it.isNotBlank() } ?: return null
            val defaults = p.optJSONObject("defaults")?.let { d -> d.keys().asSequence().associateWith { k -> d.optString(k) } } ?: emptyMap()
            return CatalogueProvider(
                id = id,
                name = p.optString("name").ifBlank { id },
                nameZh = p.optString("name_zh"),
                protocol = p.optString("protocol", "openai"),
                baseUrl = p.optString("base_url"),
                baseUrlGlobal = null,
                keyUrl = p.optString("key_url"),
                keyUrlGlobal = null,
                keyHint = null,
                auth = strings(p.optJSONArray("auth")),
                authCapabilities = emptyMap(),
                regions = strings(p.optJSONArray("regions")).toSet(),
                capabilities = strings(p.optJSONArray("covers")).ifEmpty { strings(p.optJSONArray("capabilities")) }.toSet(),
                userCapabilities = p.optBoolean("user_capabilities", false),
                defaults = defaults,
                note = p.optString("note"),
                noteZh = p.optString("note_zh"),
                verified = p.optString("verified"),
                sessionHeader = p.optString("session_header").takeIf { it.isNotBlank() },
            )
        }

        private fun strings(arr: JSONArray?): List<String> =
            (0 until (arr?.length() ?: 0)).map { arr!!.optString(it) }.filter { it.isNotBlank() }
    }
}

/**
 * What the ways-on card lists, resolved once: the relay's guidance when it sent one, else
 * the bundled catalogue ordered for the region (docs/parity.md, item 34). Pure.
 */
data class Ways(
    /** The vendors with a key, the region's lead first. */
    val vendors: List<CatalogueProvider>,
    /** The plans a person may already pay for that this phone signs in with, as a vendor and its sign-in. */
    val signIns: List<SignIn>,
    /** The servers a person runs on a computer of their own. */
    val locals: List<CatalogueProvider>,
    /** Where the guide is; empty when neither the relay nor the catalogue named one. */
    val docs: String,
    /** The honest line about the ChatGPT sign-in; empty when the relay sent none (the app has its own). */
    val chatgptCaveat: String,
    /** True when the list came from the relay. */
    val fromRelay: Boolean,
) {
    /** One plan: the vendor to open the form on, how it signs in, and what the sign-in covers. */
    data class SignIn(val vendor: CatalogueProvider, val auth: String, val covers: Set<String>, val name: String)

    companion object {
        /**
         * The guidance first — its providers in the relay's order, its plans that name this
         * client, its local servers — and the catalogue only when the relay sent none. A plan
         * whose provider the bundled catalogue knows opens that vendor's form; one it does
         * not is still listed with the relay's provider entry, so a new vendor on the relay
         * shows before the app is updated.
         */
        fun resolve(guidance: Guidance?, catalogue: List<CatalogueProvider>, mainland: Boolean, chinese: Boolean = false): Ways {
            if (guidance == null) {
                val vendors = ProviderCatalogue.ordered(catalogue, mainland)
                return Ways(
                    vendors = vendors,
                    signIns = ProviderCatalogue.signIns(catalogue, mainland).map { v -> SignIn(v, v.signIn!!, v.capabilitiesFor(v.signIn), planName(v.signIn!!, v, chinese)) },
                    locals = catalogue.filter { it.local },
                    docs = "",
                    chatgptCaveat = "",
                    fromRelay = false,
                )
            }
            val known = (guidance.providers + guidance.local + catalogue).associateBy { it.id }
            val signIns = guidance.plans
                .filter { Guidance.CLIENT in it.clients || it.clients.isEmpty() }
                .mapNotNull { plan ->
                    val vendor = catalogue.firstOrNull { it.id == plan.provider } ?: known[plan.provider] ?: return@mapNotNull null
                    SignIn(vendor, plan.auth, plan.covers.ifEmpty { vendor.capabilitiesFor(plan.auth) }, plan.name)
                }
            return Ways(
                vendors = guidance.providers.filter { !it.local && it.id != ProviderCatalogue.CUSTOM },
                signIns = signIns,
                locals = guidance.local,
                docs = guidance.docs,
                chatgptCaveat = guidance.caveat(chinese),
                fromRelay = true,
            )
        }

        /** The plan's brand for a catalogue sign-in: ChatGPT, Claude, Kimi; else the vendor's name. */
        fun planName(auth: String, vendor: CatalogueProvider, chinese: Boolean): String = when (auth) {
            ProviderCatalogue.AUTH_CHATGPT -> "ChatGPT"
            ProviderCatalogue.AUTH_CLAUDE -> "Claude"
            ProviderCatalogue.AUTH_KIMI -> "Kimi"
            else -> vendor.displayName(chinese)
        }
    }
}
