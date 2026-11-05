package io.github.nanomuse.avatar

import com.openminis.app.data.model.AgentToolDefinition
import com.openminis.app.data.model.LLMMediaAttachment
import com.openminis.app.data.model.LLMMessage
import com.openminis.app.data.model.LLMModel
import com.openminis.app.data.model.LLMResponse
import com.openminis.app.data.model.LLMStreamChunk
import com.openminis.app.data.model.ProviderCredential
import com.openminis.app.data.model.ProviderInstance
import com.openminis.app.data.model.ProviderType
import com.openminis.app.data.model.ThinkingLevel
import com.openminis.app.provider.LLMProvider
import com.openminis.app.provider.gemini.GeminiProvider
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONObject
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

class ImageModelRequestsTest {
    private fun instance(type: ProviderType) = ProviderInstance(
        id = "image-provider", label = "Image provider", providerType = type,
        credentialType = ProviderCredential.apiKey,
    )

    @Test fun `native Gemini image slot requires an enabled API key provider`() {
        val gemini = instance(ProviderType.gemini)
        assertTrue(ImageModelRequests.supports(gemini))
        assertFalse(ImageModelRequests.supports(gemini.copy(isEnabled = false)))
        assertFalse(ImageModelRequests.supports(gemini.copy(credentialType = ProviderCredential.oauth)))
        assertFalse(ImageModelRequests.supports(instance(ProviderType.anthropic)))
        assertFalse(ImageModelRequests.supports(instance(ProviderType.openAI).copy(credentialType = ProviderCredential.oauth)))
        listOf(ProviderType.openAI, ProviderType.openAIResponses, ProviderType.openRouter, ProviderType.xAI).forEach {
            assertTrue(it.name, ImageModelRequests.supports(instance(it)))
        }
    }

    @Test fun `Imagen is excluded only from the native Gemini generateContent route`() {
        listOf("imagen-4.0-generate-001", "models/imagen-4.0-generate-001", "IMAGEN-4.0-fast-generate-001").forEach {
            assertFalse(it, ImageModelRequests.supportsModel(ProviderType.gemini, it))
        }
        listOf("gemini-2.5-flash-image", "nano-banana", "nano-banana-2.1").forEach {
            assertTrue(it, ImageModelRequests.supportsModel(ProviderType.gemini, it))
            assertTrue(it, ImageGen.looksLikeImageModel(it))
        }
        assertTrue(ImageModelRequests.supportsModel(ProviderType.openAI, "imagen-4.0-generate-001"))
        assertFalse(ImageGen.looksLikeImageModel("gemini-2.5-flash"))
        assertFalse(ImageGen.looksLikeImageModel("image-embedding"))
    }

    @Test fun `image request enables Gemini input and output without changing the saved model`() {
        val original = LLMModel(
            id = "gemini-2.5-flash-image", displayName = "Image model", provider = "gemini",
            contextWindow = 32768, maxOutputTokens = 4096,
            inputModalities = listOf("text"), outputModalities = listOf("text"),
        )
        val image = ImageModelRequests.modelFor(ProviderType.gemini, original)
        assertEquals(listOf("text", "image"), image.inputModalities)
        assertEquals(listOf("text", "image"), image.outputModalities)
        assertEquals(original.id, image.id)
        assertEquals(original.contextWindow, image.contextWindow)
        assertEquals(original.maxOutputTokens, image.maxOutputTokens)
        assertEquals(listOf("text"), original.inputModalities)
        assertEquals(listOf("text"), original.outputModalities)
        assertSame(original, ImageModelRequests.modelFor(ProviderType.openAI, original))
    }

    @Test fun `image request uses native Gemini URL and requests text plus image output`() = runBlocking {
        val server = MockWebServer()
        server.start()
        try {
            // The Android JVM Base64 implementation is a stub. This checks the real wire
            // request without claiming to decode an inline image in a JVM unit test.
            server.enqueue(MockResponse().setBody("""{"candidates":[{"content":{"parts":[{"text":"No picture returned"}]},"finishReason":"STOP"}]}"""))
            val model = ImageModelRequests.modelFor(ProviderType.gemini, LLMModel(
                id = "models/gemini-2.5-flash-image", displayName = "Image model", provider = "gemini",
                maxOutputTokens = 4096,
            ))
            val provider = GeminiProvider(
                apiKey = "test-key", model = model,
                basePath = server.url("/v1beta").toString().trimEnd('/'),
            )
            val response = ImageModelRequests.request(provider, "Draw a small blue bird")
            val request = requireNotNull(server.takeRequest(5, TimeUnit.SECONDS))
            assertEquals("POST", request.method)
            assertEquals("/v1beta/models/gemini-2.5-flash-image:generateContent", request.requestUrl!!.encodedPath)
            assertEquals("test-key", request.requestUrl!!.queryParameter("key"))
            val body = JSONObject(request.body.readUtf8())
            val config = body.getJSONObject("generationConfig")
            val modalities = config.getJSONArray("responseModalities")
            assertEquals(listOf("TEXT", "IMAGE"), (0 until modalities.length()).map { modalities.getString(it) })
            assertEquals(4096, config.getInt("maxOutputTokens"))
            val contents = body.getJSONArray("contents")
            assertEquals(1, contents.length())
            assertEquals("user", contents.getJSONObject(0).getString("role"))
            assertEquals("Draw a small blue bird", contents.getJSONObject(0).getJSONArray("parts").getJSONObject(0).getString("text"))
            assertFalse(body.has("systemInstruction"))
            assertFalse(body.has("tools"))
            assertEquals("No picture returned", response.text)
            assertTrue(response.mediaAttachments.isEmpty())
        } finally {
            server.shutdown()
        }
    }

    @Test fun `native Gemini model resource prefix is removed without changing other providers`() {
        val model = LLMModel("models/nano-banana", "Image model", "gemini")
        assertEquals("nano-banana", ImageModelRequests.modelFor(ProviderType.gemini, model).id)
        assertEquals("models/nano-banana", model.id)
        assertSame(model, ImageModelRequests.modelFor(ProviderType.openRouter, model))
    }

    @Test fun `native edit passes original image bytes and instruction to the provider`() = runBlocking {
        val provider = RecordingProvider()
        val first = LLMMessage.ImagePart(byteArrayOf(1, 2, 3), "image/png")
        val second = LLMMessage.ImagePart(byteArrayOf(4, 5, 6), "image/jpeg")
        val response = ImageModelRequests.request(provider, "Give the bird a scarf", images = listOf(first, second))
        assertEquals(listOf(LLMMessage(LLMMessage.Role.USER, "Give the bird a scarf")), provider.messages)
        assertEquals(2, provider.images.size)
        assertSame(first, provider.images[0])
        assertSame(second, provider.images[1])
        assertArrayEquals(byteArrayOf(1, 2, 3), provider.images[0].data)
        assertEquals("image/png", provider.images[0].mimeType)
        assertNull(provider.systemPrompt)
        assertEquals(4096, provider.maxTokens)
        assertTrue(provider.tools.isEmpty())
        assertSame(provider.response, response)
        assertArrayEquals(byteArrayOf(7, 8), response.mediaAttachments.single().data)
    }

    @Test fun `native generation has no accidental edit input`() = runBlocking {
        val provider = RecordingProvider()
        ImageModelRequests.request(provider, "Draw a bird")
        assertTrue(provider.images.isEmpty())
        assertEquals("Draw a bird", provider.messages.single().content)
    }

    @Test fun `native image cancellation remains cancellation`() = runBlocking {
        val cancellation = CancellationException("cancelled by caller")
        val provider = RecordingProvider().apply { failure = cancellation }
        try {
            ImageModelRequests.request(provider, "Draw a bird")
            fail("Cancellation must propagate")
        } catch (actual: CancellationException) {
            assertSame(cancellation, actual)
        }
    }

    @Test fun `native provider failure is preserved for the caller`() = runBlocking {
        val failure = IOException("image endpoint unavailable")
        val provider = RecordingProvider().apply { this.failure = failure }
        try {
            ImageModelRequests.request(provider, "Draw a bird")
            fail("Provider failure must propagate")
        } catch (actual: IOException) {
            assertSame(failure, actual)
        }
    }

    private class RecordingProvider : LLMProvider {
        override val name = "Image test provider"
        override var model = LLMModel("image-test", "Image test", "gemini", maxOutputTokens = 4096)
        var messages = emptyList<LLMMessage>()
        var images = emptyList<LLMMessage.ImagePart>()
        var systemPrompt: String? = "not called"
        var maxTokens = 0
        var tools = emptyList<AgentToolDefinition>()
        var failure: Exception? = null
        val response = LLMResponse("", "end_turn", null, listOf(
            LLMMediaAttachment(LLMMediaAttachment.MediaType.IMAGE, "image/png", byteArrayOf(7, 8)),
        ))

        override suspend fun sendMessageClamped(
            messages: List<LLMMessage>, systemPrompt: String?, maxTokens: Int,
            temperature: Double?, imageParts: List<LLMMessage.ImagePart>,
            tools: List<AgentToolDefinition>, thinkingLevel: ThinkingLevel,
        ): LLMResponse {
            failure?.let { throw it }
            this.messages = messages
            this.images = imageParts
            this.systemPrompt = systemPrompt
            this.maxTokens = maxTokens
            this.tools = tools
            return response
        }

        override fun streamMessageClamped(
            messages: List<LLMMessage>, systemPrompt: String?, maxTokens: Int,
            temperature: Double?, imageParts: List<LLMMessage.ImagePart>,
            tools: List<AgentToolDefinition>, thinkingLevel: ThinkingLevel,
        ): Flow<LLMStreamChunk> = error("Image requests must use a complete response")
    }
}
