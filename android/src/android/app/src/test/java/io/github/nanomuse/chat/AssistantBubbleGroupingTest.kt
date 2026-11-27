package io.github.nanomuse.chat

import com.openminis.app.ui.chat.AssistantBlock
import com.openminis.app.ui.chat.ChatMessage
import com.openminis.app.ui.chat.FlatChatItem
import com.openminis.app.ui.chat.ToolBlockStatus
import com.openminis.app.ui.chat.buildFlatChatItems
import io.github.nanomuse.ui.chat.isBareBlock
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AssistantBubbleGroupingTest {

    @Test fun liveBackgroundScreenProgressStaysVisibleWhenStepsAreHidden() {
        val block = AssistantBlock(
            id = "call",
            kind = "tool_use",
            toolName = "shell_execute",
            toolStatus = ToolBlockStatus.RUNNING,
            handsProgress = "Step 2 · Looking",
        )
        val message = ChatMessage(
            "reply",
            "assistant",
            "",
            isStreaming = true,
            toolBlocks = listOf(block),
        )
        val items = buildFlatChatItems(listOf(message), showSteps = false)
        assertEquals(
            "Step 2 · Looking",
            items.filterIsInstance<FlatChatItem.AssistantToolUse>().single().block.handsProgress,
        )
        assertTrue(items.none { it is FlatChatItem.AssistantTyping })
    }

    @Test fun finishedBackgroundProgressWithoutReplayIsHiddenWithOtherSteps() {
        val block = AssistantBlock(
            id = "call",
            kind = "tool_use",
            toolName = "shell_execute",
            toolStatus = ToolBlockStatus.SUCCESS,
            handsProgress = "Done",
        )
        val message = ChatMessage("reply", "assistant", "", toolBlocks = listOf(block))
        assertTrue(buildFlatChatItems(listOf(message), showSteps = false).isEmpty())
    }

    @Test fun savedScreenReplayRemainsInTheChatWhenStepsAreHidden() {
        val block = AssistantBlock(id = "call", kind = "tool_use", toolName = "shell_execute", handsRunId = "20260112-032915")
        val message = ChatMessage("reply", "assistant", "", toolBlocks = listOf(block))
        for (show in listOf(false, true)) {
            val items = buildFlatChatItems(listOf(message), showSteps = show)
            assertEquals("20260112-032915", items.filterIsInstance<FlatChatItem.HandsReplay>().single().runId)
            assertEquals(show, items.any { it is FlatChatItem.AssistantToolUse })
        }
    }

    @Test
    fun `a single assistant markdown turn stays in one bubble across lists headings and code blocks`() {
        val md = """
            - SOUL.md: persona settings
            - Memory system: `/var/minis/memory/`

            ### One design detail worth noting

            Each chat session has its own isolated storage:

            ```text
            /var/minis/
            |-- attachments/
            |-- shared/
            ```
        """.trimIndent()

        val msg = ChatMessage(
            id = "a-1",
            role = "assistant",
            content = md,
            isStreaming = false,
            toolBlocks = listOf(
                AssistantBlock(id = "b-1", kind = "text", content = md),
            ),
        )

        val items = buildFlatChatItems(listOf(msg))
        val mdBlocks = items.filterIsInstance<FlatChatItem.AssistantMarkdownBlock>()
        assertEquals(1, mdBlocks.size)
        assertEquals(md, mdBlocks.single().rawText)
        assertEquals(0, mdBlocks.single().blockIndex)
        assertTrue(mdBlocks.single().isLastBlockOfMessage)
        assertFalse(isBareBlock(mdBlocks.single().rawText))
    }

    @Test
    fun `streaming assistant markdown turn also stays in one bubble`() {
        val md = "First paragraph\n\n### Heading\n\n```bash\nls -la\n```"
        val msg = ChatMessage(
            id = "a-stream",
            role = "assistant",
            content = md,
            isStreaming = true,
            toolBlocks = listOf(
                AssistantBlock(id = "b-stream", kind = "text", content = md),
            ),
        )

        val items = buildFlatChatItems(listOf(msg))
        val mdBlocks = items.filterIsInstance<FlatChatItem.AssistantMarkdownBlock>()
        assertEquals(1, mdBlocks.size)
        assertEquals(md, mdBlocks.single().rawText)
        assertTrue(mdBlocks.single().messageIsStreaming)
    }

    @Test
    fun `assistant text before and after a tool call remain separate bubbles`() {
        val before = "Let me check the directory structure first."
        val after = "Here is what I found:\n\n### Summary\n\n- Item A\n- Item B"
        val msg = ChatMessage(
            id = "a-2",
            role = "assistant",
            content = "$before\n\n$after",
            isStreaming = false,
            toolBlocks = listOf(
                AssistantBlock(id = "t-before", kind = "text", content = before),
                AssistantBlock(
                    id = "tool-1",
                    kind = "tool_use",
                    toolName = "bash",
                    toolArgs = "{\"command\":\"ls\"}",
                    toolStatus = ToolBlockStatus.SUCCESS,
                ),
                AssistantBlock(id = "t-after", kind = "text", content = after),
            ),
        )

        val items = buildFlatChatItems(listOf(msg))
        val mdBlocks = items.filterIsInstance<FlatChatItem.AssistantMarkdownBlock>()
        assertEquals(2, mdBlocks.size)
        assertEquals(before, mdBlocks[0].rawText)
        assertFalse(mdBlocks[0].isLastBlockOfMessage)
        assertEquals(after, mdBlocks[1].rawText)
        assertTrue(mdBlocks[1].isLastBlockOfMessage)
    }

    @Test
    fun `isBareBlock only unwraps standalone nanomuse protocol fences`() {
        assertTrue(isBareBlock("```nanomuse-naming\n{\"agent_name\":\"Pip\"}\n```"))
        assertTrue(isBareBlock("  ```nanomuse-goal\n{\"title\":\"Read\"}\n```  "))
        assertFalse(isBareBlock("```python\nprint(1)\n```"))
        assertFalse(isBareBlock("| a | b |\n|---|---|\n| 1 | 2 |"))
        assertFalse(isBareBlock("Hello\n\n```nanomuse-goal\n{\"title\":\"Read\"}\n```"))
    }
}
