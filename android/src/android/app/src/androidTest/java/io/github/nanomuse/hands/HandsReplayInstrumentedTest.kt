package io.github.nanomuse.hands

import android.graphics.Bitmap
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onAllNodesWithContentDescription
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.openminis.app.MinisApp
import com.openminis.app.R
import com.openminis.app.data.db.ChatSessionEntity
import com.openminis.app.data.db.MessageEntity
import com.openminis.app.ui.chat.ChatScreen
import com.openminis.app.ui.chat.ChatViewModelStore
import com.openminis.app.ui.settings.KEY_NM_SHOW_STEPS
import com.openminis.app.ui.settings.getAppearancePrefs
import io.github.nanomuse.account.AccountData
import io.github.nanomuse.sync.SyncDatabase
import io.github.nanomuse.ui.hands.HandsScreen
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.json.JSONArray
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.nio.file.Files
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class HandsReplayInstrumentedTest {
    @get:Rule val compose = createComposeRule()

    @Test fun restoredChatOpensItsExactRunWithStepsHiddenAndClosesOnAccessChange() {
        val app = InstrumentationRegistry.getInstrumentation().targetContext.applicationContext as MinisApp
        val repo = checkNotNull(app.chatRepositoryOrNull)
        val id = UUID.randomUUID().toString()
        val run = "20260112-032915-abc123"
        val root = File(app.filesDir, "minis-sessions/$id")
        val folder = File(root, "attachments/hands/$run")
        val mounted = mutableStateOf(true)
        val prefs = getAppearancePrefs(app)
        val previousShowSteps = if (prefs.contains(KEY_NM_SHOW_STEPS)) prefs.getBoolean(KEY_NM_SHOW_STEPS, true) else null
        fun part(type: String, value: JSONObject) = JSONArray().put(JSONObject().put("type", type).put("value", value)).toString()
        try {
            prefs.edit().putBoolean(KEY_NM_SHOW_STEPS, false).commit()
            assertTrue(folder.mkdirs())
            File(folder, "trace.jsonl").writeText("""{"step":7,"result":"ok"}""" + "\n")
            val tool = JSONObject().put("toolUseId", "receipt").put("name", "shell_execute")
            val args = JSONObject().put("command", "nanomuse-hands run --task 'Read the screen'").toString()
            val action = part("toolUse", JSONObject(tool.toString()).put("input", args))
            val output = JSONObject().put("run_id", run)
                .put("trace", "/var/minis/attachments/hands/$run/trace.jsonl")
                .put("log", JSONArray((1..110).map { "Step $it" })).toString(2)
            val result = part("toolResult", tool.put("output", output).put("success", true))
            runBlocking {
                repo.dao.insertSession(ChatSessionEntity(id, "Recorded screen task", "local-test", 1, 1))
                AccountData.claimNow(app, id)
                repo.dao.insertMessage(MessageEntity("use-$id", id, "assistant", action, 1, sortOrder = 1))
                repo.dao.insertMessage(MessageEntity("result-$id", id, "user", result, 2, sortOrder = 2))
            }
            compose.setContent { if (mounted.value) MaterialTheme {
                ChatScreen(id, repo, checkNotNull(app.providerRepositoryOrNull), onBack = {})
            } }
            val open = app.getString(R.string.nm_hands_replay_open)
            val step = app.getString(R.string.nm_hands_step, 7)
            compose.waitUntil(20_000) { compose.onAllNodesWithText(open).fetchSemanticsNodes().isNotEmpty() }
            compose.onNodeWithText(open).performClick()
            compose.waitUntil(10_000) { compose.onAllNodesWithText(step, substring = true).fetchSemanticsNodes().isNotEmpty() }
            compose.onNodeWithText(app.getString(R.string.nm_hands_replay_no_image)).assertIsDisplayed()
            HandsReplayAccess.invalidate()
            compose.waitUntil(10_000) { compose.onAllNodesWithText(step, substring = true).fetchSemanticsNodes().isEmpty() }
            compose.onNodeWithText(open).assertIsDisplayed()
        } finally {
            compose.runOnIdle { mounted.value = false }
            compose.waitForIdle()
            InstrumentationRegistry.getInstrumentation().runOnMainSync { ChatViewModelStore.release(id) }
            prefs.edit().apply { if (previousShowSteps == null) remove(KEY_NM_SHOW_STEPS) else putBoolean(KEY_NM_SHOW_STEPS, previousShowSteps) }.commit()
            runBlocking {
                SyncDatabase.get(app).dao().removeOwners(listOf(id))
                repo.dao.deleteSession(id)
            }
            root.deleteRecursively()
        }
    }

    @Test fun historyPlaysOwnedFramesAndOmitsOtherAccountsAndLinkedPictures() {
        val app = InstrumentationRegistry.getInstrumentation().targetContext.applicationContext as MinisApp
        val chats = checkNotNull(app.chatRepositoryOrNull).dao
        val owners = SyncDatabase.get(app).dao()
        val owned = UUID.randomUUID().toString()
        val other = UUID.randomUUID().toString()
        val ownedTitle = "Screen replay " + owned.take(8)
        val otherTitle = "Other replay " + other.take(8)
        val run = "20260112-032915"
        val sessionsDir = File(app.filesDir, "minis-sessions")
        fun folder(session: String) = File(sessionsDir, "$session/attachments/hands/$run")
        val history = app.getString(R.string.nm_hands_replay_title)
        val previous = app.getString(R.string.nm_hands_replay_previous)
        val next = app.getString(R.string.common_next)
        val noImage = app.getString(R.string.nm_hands_replay_no_image)
        val stepOne = app.getString(R.string.nm_hands_step, 1)
        val stepTwo = app.getString(R.string.nm_hands_step, 2)

        fun waitForText(text: String) = compose.waitUntil(10_000) {
            compose.onAllNodesWithText(text).fetchSemanticsNodes().isNotEmpty()
        }
        fun waitForPicture() = compose.waitUntil(10_000) {
            compose.onAllNodesWithContentDescription(stepOne).fetchSemanticsNodes().isNotEmpty()
        }

        try {
            runBlocking {
                for ((id, title) in listOf(owned to ownedTitle, other to otherTitle)) {
                    chats.insertSession(ChatSessionEntity(id, title, "local-test", 1L, 1L))
                    AccountData.claimNow(app, id, if (id == owned) AccountData.key(app) else "test-$other")
                    assertTrue(folder(id).mkdirs())
                }
            }
            val dir = folder(owned)
            val picture = File(dir, "step-1.jpg")
            val bitmap = Bitmap.createBitmap(40, 60, Bitmap.Config.ARGB_8888)
            try { picture.outputStream().use { assertTrue(bitmap.compress(Bitmap.CompressFormat.JPEG, 75, it)) } }
            finally { bitmap.recycle() }
            Files.createSymbolicLink(File(dir, "step-2.jpg").toPath(), picture.toPath())
            val action = """{"action_type":"click","coordinate":[300,550],"target":"OK"}"""
            File(dir, "trace.jsonl").writeText((1..2).joinToString("\n", postfix = "\n") { n ->
                JSONObject().put("step", n).put("reply", "Thought: OK\nAction: $action")
                    .put("screen", "minis://attachments/hands/$run/step-$n.jpg").toString()
            })

            compose.setContent { MaterialTheme { HandsScreen(onBack = {}, onOpenProviders = {}, onOpenShizuku = {}) } }
            compose.onNodeWithText(history).performScrollTo().performClick()
            waitForText(ownedTitle)
            compose.onNodeWithText(otherTitle).assertDoesNotExist()
            compose.onNodeWithText(ownedTitle).performClick()
            waitForPicture()
            compose.onNodeWithText(previous).assertIsNotEnabled()
            compose.onNodeWithText(next).performClick()
            waitForText(noImage)
            compose.onNodeWithText(stepTwo, substring = true).assertIsDisplayed()
            compose.onNodeWithText(next).assertIsNotEnabled()
            compose.onNodeWithText(previous).performClick()
            waitForPicture()
        } finally {
            runBlocking {
                owners.removeOwners(listOf(owned, other))
                chats.deleteSession(owned)
                chats.deleteSession(other)
            }
            // Remove the two synthetic sessions only. Unlink the fixture before walking its directory.
            Files.deleteIfExists(File(folder(owned), "step-2.jpg").toPath())
            for (id in listOf(owned, other)) File(sessionsDir, id).deleteRecursively()
        }
    }
}
