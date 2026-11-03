package io.github.nanomuse.sync

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class RemoteTaskReplyTest {
    @Test fun `partial text replaces the current segment and tools keep earlier text`() {
        val reply = RemoteTaskReply("desk")
        reply.event(JSONObject("""{"stage":"text","text":"Hel","partial":true}"""))
        reply.event(JSONObject("""{"stage":"text","text":"Hello","partial":true}"""))
        assertEquals(listOf("Hello"), reply.blocks.map { it.content })
        reply.event(JSONObject("""{"stage":"tool","id":"one","name":"shell","summary":"List files"}"""))
        reply.event(JSONObject("""{"stage":"tool_result","id":"one","ok":false,"summary":"Denied"}"""))
        reply.event(JSONObject("""{"stage":"text","text":"Finished"}"""))
        assertEquals(listOf("text", "tool_use", "text"), reply.blocks.map { it.kind })
        assertEquals("Hello", reply.blocks.first().content)
        assertEquals("desk:one", reply.blocks[1].id)
        assertEquals(com.openminis.app.ui.chat.ToolBlockStatus.FAILED, reply.blocks[1].toolStatus)
        assertTrue(reply.finish("Finished"))
        assertEquals(1, reply.blocks.count { it.content == "Finished" })
    }

    @Test fun `failure and stop settle running tools and reject late events and duplicate completion`() {
        for (failed in listOf(true, false)) {
            val reply = RemoteTaskReply("desk")
            reply.event(JSONObject("""{"stage":"tool","id":"one","name":"shell"}"""))
            assertTrue(reply.finish("End", failed))
            val snapshot = reply.blocks
            reply.event(JSONObject("""{"stage":"text","text":"late"}"""))
            assertFalse(reply.finish("another"))
            assertEquals(snapshot, reply.blocks)
            assertNotEquals(com.openminis.app.ui.chat.ToolBlockStatus.RUNNING, reply.blocks.first().toolStatus)
        }
    }

    @Test fun `an empty successful result is not reported as work completed`() {
        assertNull(RemoteTaskReply.answer(JSONObject()))
        assertNull(RemoteTaskReply.answer(JSONObject().put("text", "  ")))
        assertEquals("answer", RemoteTaskReply.answer(JSONObject().put("text", " answer ")))
    }
}
