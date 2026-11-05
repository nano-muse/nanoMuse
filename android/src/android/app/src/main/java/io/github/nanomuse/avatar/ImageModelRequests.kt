package io.github.nanomuse.avatar

import com.openminis.app.data.model.LLMMessage
import com.openminis.app.data.model.LLMModel
import com.openminis.app.data.model.LLMResponse
import com.openminis.app.data.model.ProviderCredential
import com.openminis.app.data.model.ProviderInstance
import com.openminis.app.data.model.ProviderType
import com.openminis.app.provider.LLMProvider
import com.openminis.app.provider.openai.OpenAIProvider

/** The image slot uses each provider's existing image transport. */
internal object ImageModelRequests {
    fun supports(instance: ProviderInstance): Boolean =
        instance.isEnabled && instance.credentialType == ProviderCredential.apiKey &&
            instance.providerType in setOf(
                ProviderType.openAI, ProviderType.openAIResponses, ProviderType.openRouter,
                ProviderType.xAI, ProviderType.gemini,
            )

    fun supportsModel(type: ProviderType, id: String): Boolean =
        // Imagen uses a separate prediction API, not Gemini's generateContent route.
        type != ProviderType.gemini || !id.removePrefix("models/").startsWith("imagen", ignoreCase = true)

    fun modelFor(type: ProviderType, model: LLMModel): LLMModel =
        if (type == ProviderType.gemini) model.copy(
            id = model.id.removePrefix("models/"),
            inputModalities = listOf("text", "image"),
            outputModalities = listOf("text", "image"),
        ) else model

    suspend fun request(
        provider: LLMProvider,
        prompt: String,
        size: String = "1024x1024",
        images: List<LLMMessage.ImagePart> = emptyList(),
    ): LLMResponse = if (provider is OpenAIProvider) {
        if (images.isEmpty()) provider.generateImage(prompt = prompt, n = 1, size = size)
        else provider.editImage(prompt = prompt, images = images, n = 1, size = size)
    } else {
        provider.sendMessage(
            messages = listOf(LLMMessage(LLMMessage.Role.USER, prompt)),
            systemPrompt = null,
            maxTokens = provider.effectiveMaxOutputTokens(provider.model),
            imageParts = images,
        )
    }
}
