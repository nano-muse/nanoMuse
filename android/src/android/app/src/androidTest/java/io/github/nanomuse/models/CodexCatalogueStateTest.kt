package io.github.nanomuse.models

import android.content.Context
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.util.UUID
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class CodexCatalogueStateTest {
    @Test fun offlineRefreshKeepsOnlyMenusConfirmedForThisAccountAndProvider() = runBlocking {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val file = "catalogue-test-${UUID.randomUUID()}"
        val prefs = context.getSharedPreferences(file, Context.MODE_PRIVATE)
        try {
            val store = CodexCatalogueState(prefs)
            store.recordLive("provider", "account-a")
            assertTrue(store.hasLiveFor("provider", "account-a"))
            assertFalse(store.hasLiveFor("provider", "account-b"))
            assertFalse(store.hasLiveFor("second-provider", "account-a"))
            store.recordFallback("provider", keepSaved = true)
            val reopened = CodexCatalogueState(prefs)
            assertTrue(reopened.fallback("provider").first())
            assertTrue(reopened.hasLiveFor("provider", "account-a"))
            reopened.recordFallback("provider", keepSaved = false)
            assertFalse(reopened.hasLiveFor("provider", "account-a"))
            reopened.recordLive("provider", "account-b")
            assertFalse(reopened.fallback("provider").first())
            reopened.remove("provider")
            assertFalse(reopened.hasLiveFor("provider", "account-b"))
        } finally {
            context.deleteSharedPreferences(file)
        }
    }
}
