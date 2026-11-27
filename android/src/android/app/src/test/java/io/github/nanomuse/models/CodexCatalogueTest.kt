package io.github.nanomuse.models

import com.openminis.app.provider.openai.OpenAIModelsApi
import com.openminis.app.provider.openai.OpenAIProvider
import kotlinx.coroutines.runBlocking
import org.json.JSONException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class CodexCatalogueTest {
    @Test
    fun unavailableAccountUsesUpdatedBuiltInsWhileLiveMenusKeepOnlyVisibleModels() = runBlocking {
        assertNull(OpenAIModelsApi.fetchLiveModelsOAuth(null))
        val builtIn = OpenAIModelsApi.fetchModelsOAuth().map { it.id }
        assertTrue("gpt-6.2-astra" in builtIn && "gpt-6.2-sol" in builtIn)
        assertEquals(1, builtIn.count { it == "gpt-image-2" })
        val live = OpenAIModelsApi.parseCodexModelsJson(
            """{"models":[{"slug":"new-model","visibility":"list"},{"slug":"gpt-6.2-sol","visibility":"hide"}]}""",
        )
        assertEquals(listOf("new-model"), live.map { it.id })
        assertTrue(OpenAIModelsApi.parseCodexModelsJson("""{"models":[]}""").isEmpty())
    }

    @Test
    fun codexImageVariantsRouteOnlyThroughOAuthAndSelectTheRequestedImageTool() {
        val expected = listOf("gpt-image-2", "gpt-image-2.5-sunburst", "gpt-image-2.5-flare")
        assertEquals(expected, OpenAIModelsApi.codexImageModels.map { it.id })
        for (model in OpenAIModelsApi.codexImageModels) {
            val provider = OpenAIProvider(oauthTokenProvider = { "fixture" }, model = model)
            assertTrue(provider.isCodexImageModel)
            assertTrue(!OpenAIProvider(apiKey = "fixture", model = model).isCodexImageModel)
            val body = provider.buildCodexImageBody(emptyList())
            assertEquals("gpt-5.5", body.getString("model"))
            val tool = body.getJSONArray("tools").getJSONObject(0)
            assertEquals("image_generation", tool.getString("type"))
            if (model.id == "gpt-image-2") assertTrue(!tool.has("model"))
            else assertEquals(model.id, tool.getString("model"))
        }
    }

    @Test(expected = JSONException::class)
    fun malformedAccountCatalogueIsNotAValidEmptyCatalogue() {
        OpenAIModelsApi.parseCodexModelsJson("""{"error":"temporarily unavailable"}""")
    }
}
