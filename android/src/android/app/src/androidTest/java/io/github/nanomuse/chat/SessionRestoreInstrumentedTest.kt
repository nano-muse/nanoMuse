package io.github.nanomuse.chat

import android.content.Context
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.ViewModelStore
import androidx.room.Room
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.openminis.app.data.db.AppDatabase
import com.openminis.app.data.db.ChatSessionEntity
import com.openminis.app.data.db.CompactMarkerEntity
import com.openminis.app.data.db.MessageEntity
import com.openminis.app.data.model.AgentContentPart
import com.openminis.app.data.model.LLMMessage
import com.openminis.app.data.repository.ChatRepository
import com.openminis.app.data.repository.ProviderRepository
import com.openminis.app.ui.chat.ChatViewModel
import com.openminis.app.provider.openai.OpenAIProvider
import kotlinx.coroutines.Job
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID
import java.util.concurrent.atomic.AtomicReference
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executor
import java.util.concurrent.TimeUnit

/** Real Room pages and the production ViewModel, with no model requests or sandbox tasks. */
@RunWith(AndroidJUnit4::class)
class SessionRestoreInstrumentedTest {
    private val instrumentation get() = InstrumentationRegistry.getInstrumentation()
    private val context: Context get() = instrumentation.targetContext

    private fun text(value: String): String = JSONArray().put(
        JSONObject().put("type", "text").put("value", value),
    ).toString()

    private fun history(vm: ChatViewModel): List<LLMMessage> {
        val field = ChatViewModel::class.java.getDeclaredField("agentHistory").apply { isAccessible = true }
        @Suppress("UNCHECKED_CAST")
        return (field.get(vm) as List<LLMMessage>).toList()
    }

    private fun awaitRestore(vm: ChatViewModel, reloads: Int = 0) {
        val job = AtomicReference<Job>()
        instrumentation.runOnMainSync {
            if (reloads > 0) {
                val load = ChatViewModel::class.java.getDeclaredMethod("loadSession").apply { isAccessible = true }
                repeat(reloads) { load.invoke(vm) }
            }
            val field = ChatViewModel::class.java.getDeclaredField("sessionLoadJob").apply { isAccessible = true }
            job.set(field.get(vm) as Job)
        }
        runBlocking { job.get().join() }
        assertFalse("restore must complete successfully", job.get().isCancelled)
    }

    private fun newModel(sid: String, repo: ChatRepository, store: ViewModelStore): ChatViewModel {
        val providers = ProviderRepository(context)
        val vm = AtomicReference<ChatViewModel>()
        instrumentation.runOnMainSync {
            vm.set(ViewModelProvider(store, object : ViewModelProvider.Factory {
                @Suppress("UNCHECKED_CAST")
                override fun <T : androidx.lifecycle.ViewModel> create(modelClass: Class<T>): T =
                    ChatViewModel(sid, repo, providers, context) as T
            })[ChatViewModel::class.java])
        }
        return vm.get()
    }

    @Test fun clearDuringAPausedReloadCannotReintroduceTheOldTranscript() {
        val armed = AtomicBoolean(false)
        val entered = CountDownLatch(1)
        val release = CountDownLatch(1)
        val db = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java)
            .setQueryCallback({ sql, _ ->
                if (sql.trimStart().startsWith("SELECT * FROM messages") && armed.compareAndSet(true, false)) {
                    entered.countDown()
                    check(release.await(10, TimeUnit.SECONDS))
                }
            }, Executor { it.run() }).build()
        val store = ViewModelStore()
        try {
            val sid = "clear-${UUID.randomUUID()}"
            val repo = ChatRepository(db.chatDao())
            runBlocking {
                db.chatDao().insertSession(ChatSessionEntity(sid, modelId = "unconfigured", createdAt = 0, updatedAt = 0))
                db.chatDao().insertMessage(MessageEntity("original", sid, "user", text("old request"), 0, sortOrder = 0))
            }
            val vm = newModel(sid, repo, store)
            awaitRestore(vm)
            assertEquals(1, history(vm).size)
            val pending = AtomicReference<Job>()
            instrumentation.runOnMainSync {
                armed.set(true)
                ChatViewModel::class.java.getDeclaredMethod("loadSession").apply { isAccessible = true }.invoke(vm)
                pending.set(ChatViewModel::class.java.getDeclaredField("sessionLoadJob")
                    .apply { isAccessible = true }.get(vm) as Job)
            }
            assertTrue("reload read must be paused before Clear", entered.await(5, TimeUnit.SECONDS))
            instrumentation.runOnMainSync { vm.clearChat() }
            release.countDown()
            runBlocking { pending.get().join() }
            assertTrue("Clear invalidates the old restore", pending.get().isCancelled)
            runBlocking {
                kotlinx.coroutines.withTimeout(5_000) {
                    while (db.chatDao().messageCountForSession(sid) != 0) kotlinx.coroutines.delay(10)
                }
            }
            instrumentation.runOnMainSync {
                assertTrue(history(vm).isEmpty())
                assertTrue(vm.messages.value.isEmpty())
            }
        } finally {
            release.countDown()
            instrumentation.runOnMainSync { store.clear() }
            db.close()
        }
    }

    @Test fun sendBeforeInitialHistoryCompletesPreservesTheDraftAndDoesNotClaimATurn() {
        val entered = CountDownLatch(1)
        val release = CountDownLatch(1)
        val once = AtomicBoolean(true)
        val db = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java)
            .setQueryCallback({ sql, _ ->
                if (sql.trimStart().startsWith("SELECT * FROM messages") && once.compareAndSet(true, false)) {
                    entered.countDown()
                    check(release.await(10, TimeUnit.SECONDS))
                }
            }, Executor { it.run() }).build()
        val store = ViewModelStore()
        try {
            val sid = "initial-${UUID.randomUUID()}"
            val repo = ChatRepository(db.chatDao())
            runBlocking {
                db.chatDao().insertSession(ChatSessionEntity(sid, modelId = "unconfigured", createdAt = 0, updatedAt = 0))
                db.chatDao().insertMessage(MessageEntity("original", sid, "user", text("original instruction"), 0, sortOrder = 0))
            }
            val vm = newModel(sid, repo, store)
            assertTrue(entered.await(5, TimeUnit.SECONDS))
            instrumentation.runOnMainSync {
                // A usable provider makes the readiness check, rather than missing credentials,
                // the reason this send is refused. No request is issued.
                ChatViewModel::class.java.getDeclaredField("currentProvider").apply { isAccessible = true }
                    .set(vm, OpenAIProvider("fixture", basePath = "http://127.0.0.1:1/v1"))
                vm.setInputText("new draft")
                vm.sendMessage("new draft")
                assertEquals("new draft", vm.inputText.value)
                assertFalse(vm.isStreaming.value)
            }
            release.countDown()
            awaitRestore(vm)
            assertEquals(listOf("original"), history(vm).map { it.dbMessageId })
            assertEquals("original instruction", history(vm).single().content)
            assertEquals("new draft", vm.inputText.value)
            runBlocking { assertEquals(1, db.chatDao().messageCountForSession(sid)) }
        } finally {
            release.countDown()
            instrumentation.runOnMainSync { store.clear() }
            db.close()
        }
    }

    @Test fun repeatedAndOverlappingRestoresKeepOneCopyAndPairToolsAcrossDatabasePages() {
        val db = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java).build()
        val store = ViewModelStore()
        try {
            val dao = db.chatDao()
            val repo = ChatRepository(dao)
            val sid = "restore-${UUID.randomUUID()}"
            val rows = (0 until 405).map { index ->
                MessageEntity("row-$index", sid, "user", text("request-$index"), index.toLong(), sortOrder = index)
            }.toMutableList()
            rows[199] = rows[199].copy(role = "assistant", partsJson = """[{"type":"toolUse","value":{"toolUseId":"lookup","name":"read_file","description":"Read","input":"{}","thoughtSignature":"signed-step"}}]""")
            rows[200] = rows[200].copy(partsJson = """[{"type":"toolResult","value":{"toolUseId":"lookup","name":"read_file","output":"saved output","success":true}}]""")
            rows[201] = rows[201].copy(role = "assistant", partsJson = text("answer after lookup"))
            runBlocking {
                dao.insertSession(ChatSessionEntity(sid, modelId = "unconfigured", createdAt = 0, updatedAt = 0))
                for (row in rows) dao.insertMessage(row)
            }
            val vm = AtomicReference<ChatViewModel>()
            val providers = ProviderRepository(context)
            instrumentation.runOnMainSync {
                vm.set(ViewModelProvider(store, object : ViewModelProvider.Factory {
                    @Suppress("UNCHECKED_CAST")
                    override fun <T : androidx.lifecycle.ViewModel> create(modelClass: Class<T>): T =
                        ChatViewModel(sid, repo, providers, context) as T
                })[ChatViewModel::class.java])
            }
            awaitRestore(vm.get())
            repeat(3) {
                awaitRestore(vm.get(), reloads = 2)
                val restored = history(vm.get())
                assertEquals(rows.map { it.id }, restored.map { it.dbMessageId })
                assertEquals(405, restored.size)
                val call = restored[199].contentParts.single() as AgentContentPart.ToolUse
                val result = restored[200].contentParts.single() as AgentContentPart.ToolResult
                assertEquals("signed-step", call.thoughtSignature)
                assertEquals(call.id, result.id)
                assertEquals("saved output", result.content)
                val bubble = vm.get().messages.value.single { "row-199" in it.sourceDbIds }
                assertEquals(listOf("row-199", "row-201"), bubble.sourceDbIds)
                assertEquals("saved output", bubble.toolBlocks.single { it.id == "lookup" }.content)
                assertEquals("answer after lookup", bubble.content)
            }
            runBlocking {
                assertEquals(rows, repo.loadMessages(sid))
                assertEquals(rows.map { it.id }.toSet(), dao.messageIdsForSession(sid).toSet())
            }
        } finally {
            instrumentation.runOnMainSync { store.clear() }
            db.close()
        }
    }

    @Test fun pagedReaderKeepsEveryRowAndRestoresTheCheckpointWithoutRemovingOriginals() {
        val db = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java).build()
        val store = ViewModelStore()
        try {
            val dao = db.chatDao()
            val repo = ChatRepository(dao)
            val sid = "pages-${UUID.randomUUID()}"
            runBlocking {
                dao.insertSession(ChatSessionEntity(sid, modelId = "unconfigured", createdAt = 0, updatedAt = 0))
                repeat(405) { index ->
                    dao.insertMessage(MessageEntity("row-$index", sid, "user", text("x".repeat(2000)),
                        index.toLong(), sortOrder = index))
                }
                val marker = CompactMarkerEntity("checkpoint", sid, "preserved summary", Int.MAX_VALUE,
                    200, 200, lastCompactedMessageId = "missing-anchor", version = 2)
                dao.insertCompactMarker(marker)
                val sizes = mutableListOf<Int>()
                val ids = mutableListOf<String>()
                dao.withMessageReadTransaction {
                    repo.visitMessagePages(sid) { page ->
                        sizes.add(page.size)
                        ids.addAll(page.map { it.id })
                    }
                    assertEquals(marker, dao.latestCompactMarker(sid))
                }
                assertEquals(listOf(200, 200, 5), sizes)
                assertEquals((0 until 405).map { "row-$it" }, ids)
                assertEquals(405, dao.messageCountForSession(sid))
                assertEquals(marker, dao.latestCompactMarker(sid))
            }
            val vm = newModel(sid, repo, store)
            awaitRestore(vm)
            assertEquals(405, history(vm).size)
            val visible = vm.messages.value.filter { it.role != "system" }
            assertEquals(405, visible.size)
            assertTrue(visible.take(200).all { it.isCompactedHistory })
            assertTrue(visible.drop(200).none { it.isCompactedHistory })
            runBlocking {
                val healed = requireNotNull(dao.latestCompactMarker(sid))
                assertEquals("row-199", healed.lastCompactedMessageId)
                assertEquals("preserved summary", healed.summary)
                assertEquals(405, dao.messageCountForSession(sid))
            }
        } finally {
            instrumentation.runOnMainSync { store.clear() }
            db.close()
        }
    }
}
