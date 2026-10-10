package io.github.nanomuse.cloud

import com.openminis.app.data.model.ProviderCredential
import com.openminis.app.data.model.ProviderInstance
import com.openminis.app.data.model.ProviderType
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** Contract C11 on the phone: the shipped catalogue parses, the card's order, which vendor a configured provider is, and what it covers. */
class ProviderCatalogueTest {
    /** The asset as shipped (the module directory is the working directory of a unit test). */
    private val shipped: List<CatalogueProvider> by lazy {
        val f = listOf("src/main/assets/nanomuse/providers.json", "app/src/main/assets/nanomuse/providers.json").map(::File).first { it.exists() }
        ProviderCatalogue.parse(f.readText())
    }

    private fun inst(type: ProviderType, base: String? = null, cred: ProviderCredential = ProviderCredential.apiKey) =
        ProviderInstance(id = "i-${type.name}-${base ?: ""}", label = type.displayName, providerType = type, credentialType = cred, customBaseURL = base)

    @Test fun `the shipped catalogue parses with the vendors the contract names`() {
        val ids = shipped.map { it.id }
        for (id in listOf("bailian", "deepseek", "moonshot", "zhipu", "siliconflow", "volcengine", "minimax", "openrouter", "openai", "anthropic", "gemini", "xai", "groq", "mistral", "custom")) {
            assertTrue(id, id in ids)
        }
        val openai = shipped.first { it.id == "openai" }
        assertEquals(setOf("chat", "vision", "image"), openai.capabilities)
        // a ChatGPT plan through the Codex OAuth is chat and vision only
        assertEquals(setOf("chat", "vision"), openai.capabilitiesFor(ProviderCatalogue.AUTH_CHATGPT))
        assertEquals(ProviderCatalogue.AUTH_CHATGPT, openai.signIn)
        assertTrue(shipped.first { it.id == "bailian" }.servesMainland())
        assertFalse(shipped.first { it.id == "bailian" }.servesGlobal())
        assertTrue(shipped.first { it.id == "custom" }.userCapabilities)
        assertTrue(shipped.first { it.id == "ollama" }.local)
        for (p in shipped) assertTrue(p.id, p.verified.matches(Regex("\\d{4}-\\d{2}")))
    }

    @Test fun `a malformed entry is skipped, not the whole list`() {
        val list = ProviderCatalogue.parse(
            """{"providers":[{"name":"no id"},{"id":"x","name":"X","protocol":"openai","base_url":"https://x.example/v1","auth":["key"],"regions":["global"],"capabilities":["chat"]}]}""",
        )
        assertEquals(listOf("x"), list.map { it.id })
        assertEquals(setOf("x.example"), list.single().hosts())
    }

    @Test fun `a vendor that wants a session id per conversation is left out, the phone does not send one`() {
        assertFalse(shipped.any { it.id == "opencode-go" })
        assertTrue(shipped.any { it.id == "opencode-zen" })
        val list = ProviderCatalogue.parse(
            """{"providers":[{"id":"x","name":"X","protocol":"openai","base_url":"https://x.example/v1","auth":["key"],"regions":["global"],"capabilities":["chat"],"session_header":"x-session"}]}""",
        )
        assertTrue(list.isEmpty())
    }

    @Test fun `the card's order - the region's first, local servers and the blank entry left out`() {
        val cn = ProviderCatalogue.ordered(shipped, mainland = true).map { it.id }
        assertEquals("bailian", cn.first())
        assertTrue(cn.indexOf("deepseek") < cn.indexOf("openai")) // a vendor that signs up on the mainland before one that does not
        for (id in listOf("ollama", "lm-studio", "vllm", "custom")) assertFalse(id, id in cn)

        val global = ProviderCatalogue.ordered(shipped, mainland = false).map { it.id }
        assertEquals(listOf("openrouter", "openai"), global.take(2))
        assertTrue(global.indexOf("anthropic") < global.indexOf("bailian")) // Bailian signs up on the mainland only: after the rest
        assertEquals(cn.toSet(), global.toSet())

        // the sign-ins: ChatGPT, Claude, Kimi, OpenRouter, in the card's order
        assertEquals(setOf("openai", "anthropic", "moonshot", "openrouter"), ProviderCatalogue.signIns(shipped, false).map { it.id }.toSet())
    }

    @Test fun `which vendor a configured provider is - by host first, then by type, and unknown hosts are nobody's`() {
        // a Bailian key pasted into the OpenAI-compatible form (the preset's base, without /v1)
        assertEquals("bailian", ProviderCatalogue.match(shipped, inst(ProviderType.openAI, "https://dashscope.aliyuncs.com/compatible-mode"))?.id)
        // Kimi's global edition
        assertEquals("moonshot", ProviderCatalogue.match(shipped, inst(ProviderType.openAI, "https://api.moonshot.ai/v1"))?.id)
        // upstream's own types
        assertEquals("openrouter", ProviderCatalogue.match(shipped, inst(ProviderType.openRouter))?.id)
        assertEquals("anthropic", ProviderCatalogue.match(shipped, inst(ProviderType.anthropic))?.id)
        assertEquals("gemini", ProviderCatalogue.match(shipped, inst(ProviderType.gemini))?.id)
        assertEquals("xai", ProviderCatalogue.match(shipped, inst(ProviderType.xAI))?.id)
        assertEquals("moonshot", ProviderCatalogue.match(shipped, inst(ProviderType.kimiCode, cred = ProviderCredential.oauth))?.id)
        assertEquals("openai", ProviderCatalogue.match(shipped, inst(ProviderType.openAI))?.id)
        // a relay of one's own, nanoMuse Cloud: not in the catalogue, not gated
        assertNull(ProviderCatalogue.match(shipped, inst(ProviderType.openAI, "https://relay.example.org/v1")))
        assertNull(ProviderCatalogue.match(shipped, inst(ProviderType.openAI, "http://192.168.1.20:11434/v1")))
    }

    @Test fun `what a provider covers - the key's capabilities, or the sign-in's when that gives less`() {
        val chatgpt = inst(ProviderType.openAI, cred = ProviderCredential.oauth)
        val openai = ProviderCatalogue.match(shipped, chatgpt)!!
        assertEquals(ProviderCatalogue.AUTH_CHATGPT, ProviderCatalogue.authOf(chatgpt, openai))
        assertEquals(setOf("chat", "vision"), openai.capabilitiesFor(ProviderCatalogue.authOf(chatgpt, openai)))
        // the same vendor with a key draws
        val keyed = inst(ProviderType.openAI)
        assertNull(ProviderCatalogue.authOf(keyed, openai))
        assertTrue("image" in openai.capabilitiesFor(null))
        // DeepSeek has no image models; Bailian has everything
        assertFalse("image" in ProviderCatalogue.match(shipped, inst(ProviderType.openAI, "https://api.deepseek.com/v1"))!!.capabilities)
        assertEquals(setOf("chat", "vision", "image", "video"), ProviderCatalogue.match(shipped, inst(ProviderType.openAI, "https://dashscope.aliyuncs.com/compatible-mode/v1"))!!.capabilities)
        // OpenRouter's sign-in gives what the key gives
        val or = shipped.first { it.id == "openrouter" }
        assertEquals(or.capabilities, or.capabilitiesFor(ProviderCatalogue.AUTH_OPENROUTER))
    }

    @Test fun `the pre-filled form - endpoint split into base and the v1 toggle, the type per vendor, the sign-in's type`() {
        fun t(id: String, mainland: Boolean = true, signIn: Boolean = false) = OwnKeyPresets.template(shipped.first { it.id == id }, mainland, chinese = false, signIn = signIn)
        t("bailian").let { assertEquals(ProviderType.openAI, it.providerType); assertEquals("https://dashscope.aliyuncs.com/compatible-mode", it.baseURL); assertTrue(it.appendV1) }
        t("openrouter").let { assertEquals(ProviderType.openRouter, it.providerType); assertEquals("https://openrouter.ai/api", it.baseURL); assertTrue(it.appendV1) }
        t("zhipu").let { assertEquals("https://open.bigmodel.cn/api/paas/v4", it.baseURL); assertFalse(it.appendV1) }
        t("groq").let { assertEquals("https://api.groq.com/openai", it.baseURL); assertTrue(it.appendV1) }
        t("xai").let { assertEquals(ProviderType.xAI, it.providerType); assertEquals("https://api.x.ai", it.baseURL) }
        t("anthropic").let { assertEquals(ProviderType.anthropic, it.providerType); assertEquals("https://api.anthropic.com", it.baseURL); assertTrue(it.appendV1) }
        t("gemini").let { assertEquals(ProviderType.gemini, it.providerType); assertEquals("https://generativelanguage.googleapis.com/v1beta", it.baseURL); assertFalse(it.appendV1) }
        // the region picks the edition
        assertEquals("https://api.moonshot.cn", t("moonshot").baseURL)
        assertEquals("https://api.moonshot.ai", t("moonshot", mainland = false).baseURL)
        // a sign-in: Kimi's runs under upstream's device-code type, the others under their own
        assertEquals(ProviderType.kimiCode, t("moonshot", signIn = true).providerType)
        assertEquals(ProviderType.openAI, t("openai", signIn = true).providerType)
        assertEquals(ProviderType.anthropic, t("anthropic", signIn = true).providerType)
        // the Chinese name when the UI is Chinese
        assertEquals("阿里云百炼", OwnKeyPresets.template(shipped.first { it.id == "bailian" }, true, chinese = true).name)
    }

    @Test fun `the preset value - id and the sign-in suffix, the deep link`() {
        assertEquals("openai", OwnKeyPresets.id("openai:oauth"))
        assertEquals("bailian", OwnKeyPresets.id(" Bailian "))
        assertNull(OwnKeyPresets.id(""))
        assertTrue(OwnKeyPresets.wantsSignIn("openai:oauth"))
        assertFalse(OwnKeyPresets.wantsSignIn("openai"))
        assertEquals("minis://settings/providers/add?preset=openrouter:oauth", OwnKeyPresets.deepLink("openrouter", signIn = true))
        assertEquals("minis://settings/providers/add?preset=bailian", OwnKeyPresets.deepLink("bailian"))
        assertNotNull(ProviderCatalogue.host("https://api.openai.com/v1"))
        assertNull(ProviderCatalogue.host("not a url"))
    }
}
