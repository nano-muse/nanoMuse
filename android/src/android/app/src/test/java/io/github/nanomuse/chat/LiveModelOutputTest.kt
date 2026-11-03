package io.github.nanomuse.chat

import com.openminis.app.data.model.LLMModel
import com.openminis.app.data.model.ModelEntry
import com.openminis.app.data.model.ModelOverrides
import com.openminis.app.data.model.ProviderConfig
import com.openminis.app.data.repository.ProviderRepository
import com.openminis.app.provider.LLMProvider
import com.openminis.app.ui.chat.ChatViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import org.junit.Assert.assertEquals
import org.junit.Test
import org.mockito.Mockito

class LiveModelOutputTest {
    @Test fun `usage sheet reads refreshed capacity and live manual overrides`() {
        val old = LLMModel("test-chat", "Test", "Custom", maxOutputTokens = 1024)
        val entry = ModelEntry("test-provider", old.copy(maxOutputTokens = 8192))
        val repository = Mockito.mock(ProviderRepository::class.java)
        val provider = Mockito.mock(LLMProvider::class.java)
        Mockito.`when`(provider.model).thenReturn(old)
        val viewModel = Mockito.mock(ChatViewModel::class.java, Mockito.CALLS_REAL_METHODS)
        fun field(name: String, value: Any) {
            ChatViewModel::class.java.getDeclaredField(name).apply { isAccessible = true }.set(viewModel, value)
        }
        field("providerRepository", repository)
        field("currentProvider", provider)
        field("currentModel", old)
        field("_activeEntryId", MutableStateFlow<String?>(entry.id))
        fun publish(updated: ModelEntry) {
            Mockito.`when`(repository.config).thenReturn(MutableStateFlow(ProviderConfig(modelEntries = mutableListOf(updated))))
        }
        publish(entry)
        assertEquals(8192, viewModel.currentModelMaxOutputTokens)
        publish(entry.copy(overrides = ModelOverrides(maxOutputTokens = 4096)))
        assertEquals(4096, viewModel.currentModelMaxOutputTokens)
        publish(entry)
        assertEquals(8192, viewModel.currentModelMaxOutputTokens)
    }
}
