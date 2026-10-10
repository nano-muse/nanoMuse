package io.github.nanomuse.cloud

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * docs/parity.md, item 34: the ways-on card lists what the relay sent (`spend.guidance`,
 * contract C11) first — its order, its plans for this client, its caveat — and the bundled
 * catalogue only when the relay sent none.
 */
class GuidanceTest {
    private val shipped: List<CatalogueProvider> by lazy {
        val f = listOf("src/main/assets/nanomuse/providers.json", "app/src/main/assets/nanomuse/providers.json").map(::File).first { it.exists() }
        ProviderCatalogue.parse(f.readText())
    }

    /** A relay's answer for a mainland-China account, in the public shape of `cloud/nanomuse_cloud/providers.py`. */
    private val guidance = """{
      "version": 1, "updated": "2026-10", "region": "cn", "docs": "https://relay.example/docs/own-key",
      "providers": [
        {"id": "deepseek", "name": "DeepSeek", "name_zh": "深度求索", "protocol": "openai", "base_url": "https://api.deepseek.com/v1",
         "key_url": "https://platform.deepseek.com/api_keys", "auth": ["key"], "regions": ["cn", "global"], "covers": ["chat"], "defaults": {"chat": "deepseek-chat"}},
        {"id": "bailian", "name": "Alibaba Cloud Bailian", "name_zh": "阿里云百炼", "protocol": "openai", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
         "key_url": "https://bailian.console.aliyun.com/?apiKey=1", "auth": ["key"], "regions": ["cn"], "covers": ["chat", "vision", "image", "video"], "one_key": true},
        {"id": "newvendor", "name": "New Vendor", "protocol": "openai", "base_url": "https://api.newvendor.example/v1",
         "key_url": "https://newvendor.example/keys", "auth": ["key", "oauth-newvendor"], "regions": ["global"], "covers": ["chat", "vision"]}
      ],
      "plans": [
        {"id": "chatgpt", "provider": "openai", "name": "ChatGPT", "auth": "oauth-chatgpt", "clients": ["android", "ios", "desktop"], "covers": ["chat", "vision"]},
        {"id": "claude", "provider": "anthropic", "name": "Claude", "auth": "oauth-claude", "clients": ["desktop"], "covers": ["chat", "vision"]},
        {"id": "newvendor", "provider": "newvendor", "name": "New Vendor Pro", "auth": "oauth-newvendor", "clients": [], "covers": []}
      ],
      "local": [
        {"id": "ollama", "name": "Ollama", "protocol": "openai", "base_url": "http://localhost:11434/v1", "key_url": "", "auth": ["none"], "regions": ["cn", "global"], "covers": ["chat"]}
      ],
      "caveats": {"chatgpt": "OpenAI's terms cover Codex; other apps have lost this before.", "chatgpt_zh": "OpenAI 的条款只覆盖 Codex。"}
    }"""

    @Test fun `the relay's guidance parses, providers in its order and the plans with their clients`() {
        val g = Guidance.parse(guidance)!!
        assertEquals("cn", g.region)
        assertEquals(listOf("deepseek", "bailian", "newvendor"), g.providers.map { it.id })
        assertEquals(setOf("chat", "vision", "image", "video"), g.providers[1].capabilities)
        assertEquals("深度求索", g.providers[0].displayName(chinese = true))
        assertEquals(mapOf("chat" to "deepseek-chat"), g.providers[0].defaults)
        assertEquals(setOf("android", "ios", "desktop"), g.plans[0].clients)
        assertTrue(g.local.single().local)
        assertEquals("OpenAI 的条款只覆盖 Codex。", g.caveat(chinese = true))
        assertTrue(g.caveat(chinese = false).startsWith("OpenAI's terms"))
        // nothing to list is no guidance: the card falls back
        assertNull(Guidance.parse("""{"version":1,"providers":[]}"""))
        assertNull(Guidance.parse("not json"))
        assertNull(Guidance.parse(null as org.json.JSONObject?))
    }

    @Test fun `the relay's session providers follow its list, once each`() {
        val g = Guidance.parse(
            """{"region":"intl","providers":[
              {"id":"openrouter","name":"OpenRouter","protocol":"openai","base_url":"https://openrouter.ai/api/v1","key_url":"https://openrouter.ai/keys","auth":["key"],"regions":["global"],"covers":["chat"]}
            ],"session_providers":[
              {"id":"opencode-go","name":"OpenCode Go","protocol":"openai","base_url":"https://opencode.ai/zen/go/v1","key_url":"https://opencode.ai/auth","auth":["key"],"regions":["global"],"covers":["chat"],"session_header":"x-opencode-session"},
              {"id":"openrouter","name":"OpenRouter twice","protocol":"openai","base_url":"https://openrouter.ai/api/v1","key_url":"","auth":["key"],"regions":["global"],"covers":["chat"]}
            ]}""",
        )!!
        assertEquals(listOf("openrouter", "opencode-go"), g.providers.map { it.id })
        assertEquals("OpenRouter", g.providers[0].name)
        // session providers alone are no guidance: the relay always sends its main list
        assertNull(Guidance.parse("""{"providers":[],"session_providers":[{"id":"opencode-go","base_url":"https://opencode.ai/zen/go/v1"}]}"""))
    }

    @Test fun `guidance first - the relay's order and docs win over the bundled catalogue`() {
        val ways = Ways.resolve(Guidance.parse(guidance), shipped, mainland = true)
        assertTrue(ways.fromRelay)
        // the relay put DeepSeek first; the catalogue would have put Bailian first
        assertEquals(listOf("deepseek", "bailian", "newvendor"), ways.vendors.map { it.id })
        assertEquals("bailian", ProviderCatalogue.ordered(shipped, mainland = true).first().id)
        assertEquals("https://relay.example/docs/own-key", ways.docs)
        assertEquals(listOf("ollama"), ways.locals.map { it.id })
        assertTrue(ways.chatgptCaveat.startsWith("OpenAI's terms"))
        assertEquals("OpenAI 的条款只覆盖 Codex。", Ways.resolve(Guidance.parse(guidance), shipped, mainland = true, chinese = true).chatgptCaveat)
    }

    @Test fun `the plans - this client's only, the known vendor's form, and a vendor the app has not met yet`() {
        val ways = Ways.resolve(Guidance.parse(guidance), shipped, mainland = true)
        val names = ways.signIns.map { it.name }
        // Claude is listed for the desktop only: not on the phone
        assertEquals(listOf("ChatGPT", "New Vendor Pro"), names)
        val chatgpt = ways.signIns[0]
        assertEquals("openai", chatgpt.vendor.id) // the bundled vendor, so the form pre-fills as before
        assertEquals(ProviderCatalogue.AUTH_CHATGPT, chatgpt.auth)
        assertEquals(setOf("chat", "vision"), chatgpt.covers)
        // a plan with no clients named is for everyone; its vendor comes from the relay's own list
        val fresh = ways.signIns[1]
        assertEquals("newvendor", fresh.vendor.id)
        assertEquals(setOf("chat", "vision"), fresh.covers) // empty covers → the vendor's
        // a plan for a vendor nobody knows is left out rather than shown with no form to open
        val orphan = Guidance.parse(guidance.replace("\"provider\": \"anthropic\"", "\"provider\": \"nobody\"").replace("\"clients\": [\"desktop\"]", "\"clients\": [\"android\"]"))
        assertEquals(listOf("ChatGPT", "New Vendor Pro"), Ways.resolve(orphan, shipped, mainland = true).signIns.map { it.name })
    }

    @Test fun `no guidance - the bundled catalogue, ordered for the region, as before`() {
        val cn = Ways.resolve(null, shipped, mainland = true)
        assertFalse(cn.fromRelay)
        assertEquals(ProviderCatalogue.ordered(shipped, mainland = true).map { it.id }, cn.vendors.map { it.id })
        assertEquals(setOf("ChatGPT", "Claude", "Kimi", "OpenRouter"), cn.signIns.map { it.name }.toSet())
        assertEquals(ProviderCatalogue.AUTH_CHATGPT, cn.signIns.first { it.name == "ChatGPT" }.auth)
        assertEquals(setOf("chat", "vision"), cn.signIns.first { it.name == "ChatGPT" }.covers)
        assertTrue(cn.locals.all { it.local })
        assertEquals("", cn.docs)
        assertEquals("", cn.chatgptCaveat) // the app's own line is used
        val global = Ways.resolve(null, shipped, mainland = false)
        assertEquals(listOf("openrouter", "openai"), global.vendors.take(2).map { it.id })
    }
}
