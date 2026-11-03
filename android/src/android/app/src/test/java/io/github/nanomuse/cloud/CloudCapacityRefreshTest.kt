package io.github.nanomuse.cloud

import android.content.Context
import android.content.SharedPreferences
import com.openminis.app.MinisApp
import com.openminis.app.data.model.LLMModel
import com.openminis.app.data.model.ModelEntry
import com.openminis.app.data.model.ProviderConfig
import com.openminis.app.data.model.ProviderInstance
import com.openminis.app.data.repository.ProviderRepository
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.runBlocking
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Test
import org.mockito.Mockito
import kotlin.coroutines.Continuation
import kotlin.coroutines.intrinsics.suspendCoroutineUninterceptedOrReturn

class CloudCapacityRefreshTest {
    @Test fun `hourly refresh changes capacities without erasing other model metadata`() = runBlocking {
        val server = MockWebServer()
        server.start()
        try {
            server.enqueue(MockResponse().setBody("""{"data":[{"id":"test-relay-model","context_length":98304,"max_output_tokens":4096}]}"""))
            val old = LLMModel("test-relay-model", "Test", "Custom",
                contextWindow = 64000, maxOutputTokens = 1024, supportsReasoning = true)
            var refreshed: List<LLMModel>? = null
            val repository = Mockito.mock(ProviderRepository::class.java) { call ->
                if (call.method.name == "replaceEntries") {
                    refreshed = call.getArgument(1)
                    null
                } else Mockito.RETURNS_DEFAULTS.answer(call)
            }
            Mockito.`when`(repository.config).thenReturn(MutableStateFlow(ProviderConfig(
                modelEntries = mutableListOf(ModelEntry("test-provider", old)))))
            val instance = Mockito.mock(ProviderInstance::class.java)
            Mockito.`when`(instance.id).thenReturn("test-provider")
            Mockito.`when`(repository.instance("test-provider")).thenReturn(instance)
            val editor = Mockito.mock(SharedPreferences.Editor::class.java, Mockito.RETURNS_SELF)
            val preferences = Mockito.mock(SharedPreferences::class.java) { call ->
                when (call.method.name) {
                    "edit" -> editor
                    "getString" -> when (call.getArgument<String>(0)) {
                        "cloud.instance_id" -> "test-provider"
                        "cloud.base" -> server.url("/").toString().trimEnd('/')
                        else -> call.getArgument<String?>(1)
                    }
                    else -> Mockito.RETURNS_DEFAULTS.answer(call)
                }
            }
            val app = Mockito.mock(MinisApp::class.java)
            Mockito.`when`(app.applicationContext).thenReturn(app)
            Mockito.`when`(app.providerRepositoryOrNull).thenReturn(repository)
            Mockito.`when`(app.getSharedPreferences("nanomuse", Context.MODE_PRIVATE)).thenReturn(preferences)
            val sync = NanoMuseCloud::class.java.getDeclaredMethod("syncModels",
                Context::class.java, String::class.java, Continuation::class.java).apply { isAccessible = true }
            suspendCoroutineUninterceptedOrReturn<Unit> { continuation ->
                sync.invoke(NanoMuseCloud, app, "test-key", continuation)
            }
            val result = refreshed!!.single()
            assertEquals(98304, result.contextWindow)
            assertEquals(4096, result.maxOutputTokens)
            assertEquals(true, result.supportsReasoning)
        } finally { server.shutdown() }
    }
}
