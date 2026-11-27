package io.github.nanomuse.models

import com.openminis.app.provider.openai.OpenAIModelsApi
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

    @Test(expected = JSONException::class)
    fun malformedAccountCatalogueIsNotAValidEmptyCatalogue() {
        OpenAIModelsApi.parseCodexModelsJson("""{"error":"temporarily unavailable"}""")
    }
}
