package io.github.nanomuse.cloud

import com.openminis.app.data.model.LLMModel
import io.github.nanomuse.chat.ContextBudget
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import com.openminis.app.provider.openai.OpenAIModelsApi
import com.openminis.app.provider.ModelsDevApi
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer

class ModelCapacityTest {
    @Test fun `public catalog fills absent capacities but cannot replace the serving endpoint`() {
        val registry = ModelsDevApi::class.java.getDeclaredField("cachedRegistry").apply { isAccessible = true }
        val timestamp = ModelsDevApi::class.java.getDeclaredField("cacheTimestamp").apply { isAccessible = true }
        val oldRegistry = registry.get(ModelsDevApi)
        val oldTimestamp = timestamp.getLong(ModelsDevApi)
        val dev = ModelsDevApi.ModelDevEntry("test", null, null, 128000, 8192,
            null, null, null, null, null, releaseDate = null, outputCost = null)
        try {
            registry.set(ModelsDevApi, mapOf("test-provider" to ModelsDevApi.ProviderEntry(
                "test-provider", null, null, mapOf("test" to dev))))
            timestamp.setLong(ModelsDevApi, System.currentTimeMillis())
            val explicit = LLMModel("test", "Test", "Custom", contextWindow = 98304, maxOutputTokens = 4096)
            val enriched = ModelsDevApi.enrichModels(listOf(explicit)).single()
            assertEquals(98304, enriched.contextWindow)
            assertEquals(4096, enriched.maxOutputTokens)
            val fallback = ModelsDevApi.enrichModels(listOf(explicit.copy(contextWindow = null, maxOutputTokens = null))).single()
            assertEquals(128000, fallback.contextWindow)
            assertEquals(8192, fallback.maxOutputTokens)
        } finally {
            registry.set(ModelsDevApi, oldRegistry)
            timestamp.setLong(ModelsDevApi, oldTimestamp)
        }
    }

    @Test fun `normal endpoint discovery reads capacities`() = runBlocking {
        val server = MockWebServer()
        server.start()
        try {
            server.enqueue(MockResponse().setBody("""{"data":[{"id":"test-chat","context_length":98304,"max_output_tokens":4096}]}"""))
            val model = OpenAIModelsApi.fetchModels("test-key", server.url("/v1").toString()).single()
            assertEquals(98304, model.contextWindow)
            assertEquals(4096, model.maxOutputTokens)
            val fallbackParser = NanoMuseCloud::class.java.getDeclaredMethod("modelFromRelay", JSONObject::class.java)
                .apply { isAccessible = true }
            val fallback = fallbackParser.invoke(NanoMuseCloud,
                JSONObject("""{"id":"test-chat","context_length":98304,"max_output_tokens":4096}""")) as LLMModel
            assertEquals(model.contextWindow, fallback.contextWindow)
            assertEquals(model.maxOutputTokens, fallback.maxOutputTokens)
        } finally { server.shutdown() }
    }
    @Test fun `wire capacities determine the actual request budget`() {
        val model = ModelCapacity.apply(LLMModel("test", "Test", "Custom"),
            JSONObject("""{"context_length":98304,"max_output_tokens":4096}"""))
        assertEquals(98304, model.contextWindow)
        assertEquals(4096, model.maxOutputTokens)
        val budget = ContextBudget.forModel(model.contextWindow!!, model.maxOutputTokens!!)
        assertEquals(94208, budget.hardLimit)
        assertEquals(4096, budget.outputReserve)
    }

    @Test fun `invalid values cannot become capacities`() {
        for (value in listOf("null", "true", "0", "-1", "1.5", "2147483648", "\"8192\"")) {
            val model = ModelCapacity.apply(LLMModel("test", "Test", "Custom"),
                JSONObject("""{"context_length":$value,"max_output_tokens":$value}"""))
            assertNull(model.contextWindow)
            assertNull(model.maxOutputTokens)
        }
    }

    @Test fun `old relays keep the existing fallback`() {
        val model = LLMModel("test", "Test", "Custom", contextWindow = 32000, maxOutputTokens = 2048)
        assertEquals(model, ModelCapacity.apply(model, JSONObject()))
    }
}
