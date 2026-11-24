package io.github.nanomuse.hands

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import java.nio.file.Files

class HandsReplayTest {
    private val id = "20260112-032915"
    private fun row(n: Int, action: String, target: String = "minis://attachments/hands/$id/step-$n.jpg", result: String = "ok") =
        JSONObject().put("step", n).put("at", n * 100L).put("thought", "private reasoning")
            .put("reply", "Thought: private reasoning\nAction: $action").put("result", result).put("screen", target).toString()
    private fun lines(vararg values: String): ByteArray = (values.joinToString("\n") + "\n").toByteArray()

    @Test fun onlyHandsToolReceiptsForCanonicalSavedRunsBecomeReplayEntries() {
        val args = JSONObject().put("command", "nanomuse-hands run --task 'check the screen'").toString()
        fun body(run: String, trace: String?) = JSONObject().put("run_id", run).put("trace", trace ?: JSONObject.NULL).toString()
        val path = "/var/minis/attachments/hands/$id/trace.jsonl"
        assertEquals(id, HandsReplay.receiptId("shell_execute", args, body(id, path) + "\n (exit code 4)"))
        assertNull(HandsReplay.receiptId("file_read", args, body(id, path)))
        assertNull(HandsReplay.receiptId("shell_execute", """{"command":"ls"}""", body(id, path)))
        assertNull(HandsReplay.receiptId("shell_execute", """{"command":"echo 'nanomuse-hands run --task test'"}""", body(id, path)))
        assertEquals(id, HandsReplay.receiptId("shell_execute", """{"command":"cd /tmp && timeout 30 /usr/bin/nanomuse-hands run --task 'look'"}""", body(id, path)))
        assertNull(HandsReplay.receiptId("shell_execute", args, body(id, null)))
        assertNull(HandsReplay.receiptId("shell_execute", args, body(id, "/tmp/trace.jsonl")))
        assertNull(HandsReplay.receiptId("shell_execute", args, body("../other", path)))
    }

    @Test fun legacyCaptureAndSwipeKeepGridCoordinatesInStepOrder() {
        val a = row(9, """{"action_type":"swipe","start_coordinate":[200,400],"end_coordinate":[700,300]}""")
        val b = row(2, """{"action_type":"click","coordinate":[300,550],"target":"OK"}""")
        val replay = HandsReplay.record(id, lines(a, b), setOf(2, 9, 12), null)
        assertEquals(listOf(2, 9, 12), replay.frames.map { it.number })
        assertEquals(HandsAction.Point(300, 550), replay.frames[0].start)
        assertEquals(HandsAction.Point(700, 300), replay.frames[1].end)
        assertEquals(HandsReplay.Action.OTHER, replay.frames[2].action)
        assertTrue(replay.frames.all { it.screen })
        assertNull(replay.outcome)
    }

    @Test fun pruneMissingAndUntrustedScreenReferencesAreHandledLocally() {
        val tap = """{"action_type":"click","coordinate":[50,80]}"""
        val rows = lines(row(1, tap), row(2, tap, "https://example.org/foreign.jpg"), row(3, tap, "minis://attachments/hands/another/step-3.jpg"),
            row(4, tap, result = "refused: not allowed"))
        val replay = HandsReplay.record(id, rows, setOf(2, 3, 4), """{"mode":"background","outcome":"stopped","steps":4}""".toByteArray())
        assertEquals(listOf(false, false, false, true), replay.frames.map { it.screen })
        assertEquals(HandsReplay.Action.BLOCKED, replay.frames.last().action)
        assertNull(replay.frames.last().start)
        assertEquals("background", replay.mode)
        assertEquals("stopped", replay.outcome)
    }

    @Test fun textInputsRawRepliesAndMalformedTrailingRowStayOutOfTheViewer() {
        val first = row(1, """{"action_type":"input_text","text":"private input"}""")
        val second = row(2, """{"action_type":"back"}""")
        val replay = HandsReplay.record(id, (first + "\n{bad}\n" + second).toByteArray(), setOf(1), null)
        assertEquals(1, replay.frames.size)
        assertEquals(HandsReplay.Action.TYPE, replay.frames.first().action)
        assertFalse(replay.toString().contains("private"))
        assertFalse(replay.toString().contains("reasoning"))
    }

    @Test fun boundsStopUnboundedTraceInputsAndKeepAvailableSteps() {
        val oversized = ByteArray(HandsReplay.MAX_TRACE + 1) { 'x'.code.toByte() }
        val first = lines(row(1, """{"action_type":"back"}""")); first.copyInto(oversized)
        val replay = HandsReplay.record(id, oversized, (1..700).toSet(), "{}".toByteArray())
        assertTrue(replay.partial)
        assertEquals(HandsReplay.MAX_STEPS, replay.frames.size)
        assertEquals(HandsReplay.Action.BACK, replay.frames.first().action)
        assertNull(replay.mode)
    }

    @Test fun trustedSessionAndRunDirectoriesOnly() {
        val base = Files.createTempDirectory("nm-replay").toFile()
        try {
            val hands = base.resolve("minis-sessions/chat/attachments/hands").apply { mkdirs() }
            hands.resolve(id).mkdir(); hands.resolve("$id-15a8c").mkdir()
            hands.resolve("other").mkdir()
            val elsewhere = base.resolve("other-files").apply { mkdir() }
            Files.createSymbolicLink(hands.resolve("$id-symlink").toPath(), elsewhere.toPath())
            Files.createSymbolicLink(base.resolve("minis-sessions/linked").toPath(), base.resolve("minis-sessions/chat").toPath())
            Files.createSymbolicLink(hands.resolve("$id/step-1.jpg").toPath(), elsewhere.toPath())
            assertEquals(listOf("$id-15a8c", id), HandsReplay.list(base, "chat", null).map { it.id })
            assertTrue(HandsReplay.list(base, "linked", null).isEmpty())
            assertTrue(HandsReplay.list(base, "../chat", null).isEmpty())
            assertNull(HandsReplay.runDir(base, HandsReplay.Run("chat", "../other-files", null)))
            assertTrue(HandsReplay.screenshots(hands.resolve(id)).isEmpty())
        } finally { base.deleteRecursively() }
    }
}
