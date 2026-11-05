package io.github.nanomuse.guard

import android.content.Context
import android.content.SharedPreferences
import com.openminis.app.data.SessionForkManager
import com.openminis.app.data.db.ChatSessionEntity
import com.openminis.app.data.db.ChatDao
import com.openminis.app.data.db.MessageEntity
import com.openminis.app.data.repository.ChatRepository
import com.openminis.app.share.ChatExporter
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Before
import org.junit.Test
import org.junit.Assert.*
import org.mockito.Mockito.*
import java.io.File

class SessionProtectionReviewTest {
    private val stateField = SessionAccess::class.java.getDeclaredField("state").apply { isAccessible = true }
    private val prefsField = SessionAccess::class.java.getDeclaredField("prefs").apply { isAccessible = true }
    @Suppress("UNCHECKED_CAST")
    private val protected = SessionAccess::class.java.getDeclaredField("_protected").apply { isAccessible = true }
        .get(SessionAccess) as MutableStateFlow<Set<String>>
    private var previousState: Any? = null
    private var previousPrefs: Any? = null
    private var previousIds = emptySet<String>()
    private lateinit var locks: SessionLocks

    @Before fun fixture() {
        previousState = stateField.get(SessionAccess); previousPrefs = prefsField.get(SessionAccess)
        previousIds = protected.value
        locks = SessionLocks(setOf("protected"), { protected.value = it }, { 100L })
        stateField.set(SessionAccess, locks)
        protected.value = setOf("protected")
        val prefs = mock(SharedPreferences::class.java)
        `when`(prefs.getInt("timeout", 300)).thenReturn(300)
        prefsField.set(SessionAccess, prefs)
    }
    @After fun restore() {
        stateField.set(SessionAccess, previousState); prefsField.set(SessionAccess, previousPrefs)
        protected.value = previousIds
    }
    @Test fun lockedExportCannotReadMessagesOrCreateAnArchive(): Unit = runBlocking {
        val repository = mock(ChatRepository::class.java)
        val session = ChatSessionEntity("protected", modelId = "fixture", createdAt = 0, updatedAt = 0)
        val error = runCatching { ChatExporter.exportToZip(mock(Context::class.java), session, repository, "json") }.exceptionOrNull()
        assertTrue("Export must require authentication before any I/O", error is SecurityException)
        verifyNoInteractions(repository)
    }
    @Test fun lockedDuplicationCannotReadSourceOrCreateAnUnprotectedCopy(): Unit = runBlocking {
        val repository = mock(ChatRepository::class.java)
        val error = runCatching { SessionForkManager(repository, filesDir = File("unused-fixture")).duplicateSession("protected") }.exceptionOrNull()
        assertTrue("Duplication must require authentication before reading source", error is SecurityException)
        verifyNoInteractions(repository)
    }
    @Test fun protectionNeverPersistsATransientDraftIdentifier() {
        runCatching { locks.protect("__new__fixture", true) }
        assertFalse("Protection must use the saved session ID", "__new__fixture" in locks.ids)
    }
    @Test fun cancelledActionsDoNotReadContentAndSuccessfulCopiesLockIndependently() {
        var actions = 0
        SessionAccess.authorizeAction("protected", { it(false) }) { actions++ }
        assertEquals(0, actions)
        assertTrue(SessionAccess.isLocked("protected"))
        SessionAccess.authorizeAction("protected", { it(true) }) { actions++ }
        assertEquals(1, actions)
        SessionAccess.inheritProtection("protected", "copy")
        assertFalse(SessionAccess.isLocked("protected"))
        assertTrue(SessionAccess.isProtected("copy"))
        assertTrue(SessionAccess.isLocked("copy"))
    }
    @Test fun draftPersistenceRunsOnlyAfterAuthenticationAndUsesTheSavedId(): Unit = runBlocking {
        var saves = 0
        assertNull(SessionAccess.protectPersisted(false) { saves++; "saved" })
        assertEquals(0, saves)
        assertEquals("saved", SessionAccess.protectPersisted(true) { saves++; "saved" })
        assertEquals(1, saves)
        assertTrue(SessionAccess.isProtected("saved"))
        assertTrue(SessionAccess.isLocked("saved"))
        assertFalse(SessionAccess.isProtected("__new__fixture"))
    }
    @Test fun backupApprovalIsScopedToTheExportWithoutUnlockingChats() {
        var exports = 0
        SessionAccess.authorizeExport(true, { it(false) }) { exports++ }
        assertEquals(0, exports)
        SessionAccess.authorizeExport(true, { it(true) }) { exports++ }
        assertEquals(1, exports)
        assertTrue(SessionAccess.isLocked("protected"))
        SessionAccess.authorizeExport(false, { error("Non-chat export should not request chat access") }) { exports++ }
        assertEquals(2, exports)
    }
    @Test fun actualDuplicateProtectsItsSavedIdentityBeforeCopyingMessages(): Unit = runBlocking {
        val repository = mock(ChatRepository::class.java)
        val dao = mock(ChatDao::class.java)
        val source = ChatSessionEntity("protected", title = "Fixture", modelId = "model", createdAt = 0, updatedAt = 0)
        val copy = source.copy(id = "copy")
        val message = MessageEntity("message", "protected", "assistant", "[]", 0, sortOrder = 0)
        `when`(repository.getSession("protected")).thenReturn(source)
        `when`(repository.loadMessages("protected")).thenReturn(listOf(message))
        `when`(repository.createSession("model", "Fixture (Copy)")).thenReturn(copy)
        `when`(repository.dao).thenReturn(dao)
        `when`(dao.listCompactMarkers("protected")).thenReturn(emptyList())
        `when`(repository.appendMessage("copy", "assistant", "[]")).thenAnswer {
            assertTrue("The copy must be protected before content is written", SessionAccess.isProtected("copy"))
            message.copy(id = "copy-message", sessionId = "copy")
        }
        locks.authenticate("protected", true)
        assertEquals("copy", SessionForkManager(repository, filesDir = File("unused-fixture")).duplicateSession("protected"))
        assertTrue(SessionAccess.isLocked("copy"))
    }
}
