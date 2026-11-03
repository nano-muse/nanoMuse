package io.github.nanomuse.chat

import com.openminis.app.data.db.ChatSessionEntity
import com.openminis.app.data.db.FolderEntity
import com.openminis.app.ui.sessions.partitionByFolder
import org.junit.Assert.*
import org.junit.Test

class CollapsedUnreadGroupTest {
    private val sessions = listOf("one", "two").map {
        ChatSessionEntity(id = it, modelId = "model", createdAt = 0, updatedAt = 0, folderId = "group")
    }
    private val folders = listOf("group", "empty").map {
        FolderEntity(id = it, name = it, createdAt = 0, updatedAt = 0)
    }

    @Test fun collapsedRowsKeepEveryMemberForUnreadAggregation() {
        val group = partitionByFolder(sessions, folders, setOf("group")).first.first { it.folder.id == "group" }
        val unread = UnreadReplies()
        unread.started("two"); unread.finished("two", true, false)
        assertTrue(group.isCollapsed)
        assertTrue(group.ids.isEmpty())
        assertEquals(listOf("one", "two"), group.memberIds)
        assertTrue(group.memberIds.any { it in unread.ids })
        unread.opened("two")
        assertFalse(group.memberIds.any { it in unread.ids })
    }

    @Test fun expandingPreservesTheSameMembership() {
        val collapsed = partitionByFolder(sessions, folders, setOf("group")).first.first { it.folder.id == "group" }
        val expanded = partitionByFolder(sessions, folders, emptySet()).first.first { it.folder.id == "group" }
        assertEquals(collapsed.memberIds, expanded.memberIds)
        assertEquals(expanded.ids, expanded.memberIds)
    }

    @Test fun emptyGroupsHaveNoUnreadMembers() {
        val empty = partitionByFolder(sessions, folders, setOf("empty")).first.first { it.folder.id == "empty" }
        assertTrue(empty.memberIds.isEmpty())
    }
}
