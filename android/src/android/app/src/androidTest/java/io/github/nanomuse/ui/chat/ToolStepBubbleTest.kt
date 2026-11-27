package io.github.nanomuse.ui.chat

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.getUnclippedBoundsInRoot
import androidx.compose.ui.test.hasScrollToIndexAction
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performScrollToKey
import androidx.lifecycle.ViewModelProvider
import androidx.room.Room
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.openminis.app.R
import com.openminis.app.data.db.AppDatabase
import com.openminis.app.data.db.ChatSessionEntity
import com.openminis.app.data.db.MessageEntity
import com.openminis.app.data.repository.ChatRepository
import com.openminis.app.data.repository.ProviderRepository
import com.openminis.app.ui.chat.ChatMessage
import com.openminis.app.ui.chat.ChatScreen
import com.openminis.app.ui.chat.ChatViewModel
import com.openminis.app.ui.chat.ChatViewModelStore
import com.openminis.app.ui.chat.STREAM_DEGRADE_CHARS
import com.openminis.app.ui.settings.KEY_NM_SHOW_STEPS
import com.openminis.app.ui.settings.getAppearancePrefs
import com.openminis.app.ui.theme.MinisTheme
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class ToolStepBubbleTest {
    @get:Rule val compose = createComposeRule()

    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val db = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java).build()
    private val repo = ChatRepository(db.chatDao())
    private val providers = ProviderRepository(context)
    private val sessionId = UUID.randomUUID().toString()
    private val showChat = mutableStateOf(true)
    private val prefs = getAppearancePrefs(context)
    private val previousShowSteps = prefs.all[KEY_NM_SHOW_STEPS] as? Boolean

    @After fun closeChat() {
        compose.runOnIdle { showChat.value = false }
        compose.runOnIdle { ChatViewModelStore.release(sessionId) }
        db.close()
        prefs.edit().apply {
            if (previousShowSteps == null) remove(KEY_NM_SHOW_STEPS)
            else putBoolean(KEY_NM_SHOW_STEPS, previousShowSteps)
        }.commit()
    }

    private fun tool(step: Int) = JSONObject().put("type", "toolUse").put("value", JSONObject()
        .put("toolUseId", "call-$step").put("name", "shell_execute").put("description", "Step $step")
        .put("input", "{}"))

    private fun text(value: String) = JSONObject().put("type", "text").put("value", value)

    private fun openChat() {
        prefs.edit().putBoolean(KEY_NM_SHOW_STEPS, true).commit()
        val parts = listOf(
            JSONArray().put(tool(1)).put(tool(2)),
            JSONArray().put(text(" \t ")).put(tool(3)),
            JSONArray().put(text("\n\n")).put(tool(4)).put(text("Visible reply")),
        )
        runBlocking {
            db.chatDao().insertSession(ChatSessionEntity(sessionId, modelId = "fixture", createdAt = 0, updatedAt = 0))
            parts.forEachIndexed { i, row ->
                db.chatDao().insertMessage(MessageEntity("turn-$i", sessionId, "assistant", row.toString(), 0, sortOrder = i))
            }
        }
        compose.setContent {
            if (showChat.value) MinisTheme {
                ChatScreen(sessionId, repo, providers, onBack = {}, nmHome = NmHomeChrome(false) {})
            }
        }
        waitForText("Visible reply")
    }

    private fun waitForText(label: String) {
        compose.waitUntil(30_000) { compose.onAllNodesWithText(label).fetchSemanticsNodes().isNotEmpty() }
    }

    private fun assertToolSpacing() {
        // Steps 1 and 2 are consecutive in the original message. A blank text row
        // before 3 or 4 paints its own padded bubble and increases that pair's gap.
        val tops = (1..4).map { n ->
            compose.onNodeWithText("Step $n").assertIsDisplayed().getUnclippedBoundsInRoot().top.value
        }
        val pitch = tops[1] - tops[0]
        for (i in 2..3) {
            assertEquals("Gap before Step ${i + 1} (dp)", pitch, tops[i] - tops[i - 1], 1f)
        }
    }

    @Test fun restoredToolRoundsHaveNoBlankBubbles() {
        openChat()
        assertToolSpacing()
    }

    private fun stream(value: String): ChatMessage {
        // Publish through the same streaming overlay used by the agent loop, without
        // making any provider requests or running the fixture's tool calls.
        val vm = compose.runOnIdle {
            ViewModelProvider(ChatViewModelStore.ownerFor(sessionId))[ChatViewModel::class.java]
        }
        val message = vm.messages.value.last()
        val reply = message.toolBlocks.last()
        val publish = ChatViewModel::class.java.getDeclaredMethod(
            "updateAssistantMessage", String::class.java, String::class.java, Boolean::class.javaPrimitiveType,
            List::class.java, Boolean::class.javaPrimitiveType,
        ).apply { isAccessible = true }
        compose.runOnIdle {
            val blocks = message.toolBlocks.dropLast(1) + reply.copy(content = value)
            publish.invoke(vm, message.id, value, true, blocks, false)
        }
        return message
    }

    @Test fun streamingToolRoundsHaveNoBlankBubbles() {
        openChat()
        stream("Streaming reply")
        waitForText("Streaming reply")
        compose.onNodeWithText(context.getString(R.string.chat_stream_degraded_notice)).assertDoesNotExist()
        assertToolSpacing()
    }

    @Test fun toolRoundsStayTogetherDuringSimplifiedRendering() {
        openChat()
        val message = stream("word ".repeat(STREAM_DEGRADE_CHARS / 5 + 1))
        val reply = message.toolBlocks.last()
        val notice = context.getString(R.string.chat_stream_degraded_notice)
        val list = compose.onNode(hasScrollToIndexAction())
        // The long reply can push all tool steps outside the lazy viewport.
        list.performScrollToKey("mdblock:${message.id}:${reply.id}:0")
        waitForText(notice)
        list.performScrollToKey("tool:${message.id}:call-4")
        assertToolSpacing()
    }
}
