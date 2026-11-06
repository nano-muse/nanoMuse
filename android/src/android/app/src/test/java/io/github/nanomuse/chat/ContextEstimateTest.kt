package io.github.nanomuse.chat

import com.openminis.app.data.model.AgentContentPart
import com.openminis.app.data.model.AgentToolDefinition
import com.openminis.app.data.model.AgentToolParam
import com.openminis.app.data.model.LLMMessage
import com.openminis.app.data.model.LLMUsage
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ContextEstimateTest {
    private fun user(text: String) = LLMMessage(LLMMessage.Role.USER, text)

    @Test
    fun `Anthropic fresh input and both cache buckets all occupy context`() {
        val usage = LLMUsage(
            inputTokens = 500,
            outputTokens = 200,
            cacheReadInputTokens = 30_000,
            cacheCreationInputTokens = 2_000,
            latestContextTokens = 500,
        )
        assertEquals(32_500, ContextEstimate.inputTokens(usage))
        assertEquals(32_000, ContextEstimate.inputTokens(usage.copy(inputTokens = 0, latestContextTokens = 0)))
    }

    @Test
    fun `OpenAI total prompt count is not added to its cache count again`() {
        val usage = LLMUsage(
            inputTokens = 500,
            outputTokens = 200,
            cacheReadInputTokens = 30_000,
            latestContextTokens = 30_500,
        )
        assertEquals(30_500, ContextEstimate.inputTokens(usage))
        assertEquals(31_000, ContextEstimate.inputTokens(usage.copy(latestContextTokens = 31_000)))
    }

    @Test
    fun `input usage saturates and output only chunks do not calibrate context`() {
        assertEquals(Int.MAX_VALUE, ContextEstimate.inputTokens(LLMUsage(
            inputTokens = Int.MAX_VALUE,
            outputTokens = 100,
            cacheReadInputTokens = 10,
            cacheCreationInputTokens = Int.MAX_VALUE,
        )))
        assertEquals(0, ContextEstimate.inputTokens(LLMUsage(inputTokens = 0, outputTokens = 500)))
        assertEquals(0, ContextEstimate.inputTokens(LLMUsage(
            inputTokens = -1,
            outputTokens = 500,
            cacheReadInputTokens = -1,
            latestContextTokens = -1,
        )))
    }

    @Test
    fun `a long Chinese canonical message counts without content parts`() {
        val chinese = "请继续读取中文报告，保留原文件。".repeat(300)
        val estimate = ContextEstimate.request(listOf(user(chinese)))
        assertTrue("plain content must not disappear from the estimate", estimate >= chinese.length)
        val english = "Read the report and keep the original file. ".repeat(300)
        assertTrue(ContextEstimate.text(english) < english.length / 2)
        assertTrue(ContextEstimate.text("😀".repeat(100)) >= 400)
    }

    @Test
    fun `a dozen Chinese tool results cross the compact threshold and offload reduces them`() {
        val output = "读取结果中文。".repeat(240)
        val history = buildList {
            add(user("只读取报告，不修改文件。"))
            repeat(12) { step ->
                add(LLMMessage(
                    role = LLMMessage.Role.ASSISTANT,
                    content = "",
                    contentParts = listOf(AgentContentPart.ToolUse(
                        "call-$step", "file_read", JSONObject().put("path", "report-$step.txt"),
                    )),
                ))
                add(LLMMessage(
                    role = LLMMessage.Role.USER,
                    content = "",
                    contentParts = listOf(AgentContentPart.ToolResult("call-$step", "file_read", output)),
                ))
            }
        }
        val before = ContextEstimate.request(history)
        val budget = ContextBudget.forModel(48_000, 8_192)
        assertTrue(before >= budget.compactThreshold)
        val offloaded = history.map { message ->
            message.copy(contentParts = message.contentParts.map { part ->
                if (part is AgentContentPart.ToolResult) {
                    part.copy(content = "[CONTEXT OFFLOADED] Read the original from report.txt")
                } else part
            })
        }
        assertTrue(ContextEstimate.request(offloaded) < budget.targetTokens)
        assertEquals(before, ContextEstimate.request(history))
        assertTrue(history.flatMap { it.contentParts }.filterIsInstance<AgentContentPart.ToolResult>()
            .all { it.content == output })
        assertEquals(12, offloaded.flatMap { it.contentParts }.filterIsInstance<AgentContentPart.ToolUse>().size)
        assertEquals(12, offloaded.flatMap { it.contentParts }.filterIsInstance<AgentContentPart.ToolResult>().size)
    }

    @Test
    fun `system instructions schemas reasoning and both image representations are counted`() {
        val message = user("看图")
        val plain = ContextEstimate.request(listOf(message))
        val tool = AgentToolDefinition(
            name = "file_read",
            description = "读取文件并返回内容。".repeat(200),
            parameters = mapOf("path" to AgentToolParam("string", "要读取的文件路径")),
            required = listOf("path"),
        )
        val withSchema = ContextEstimate.request(listOf(message), tools = listOf(tool))
        assertTrue(withSchema >= plain + ContextEstimate.text(tool.description))
        val withInstructions = ContextEstimate.request(listOf(message), systemPrompt = "只读取，不发送。")
        assertTrue(withInstructions > plain)
        val imageSizes = mutableListOf<Int>()
        val imageCounter: (ByteArray) -> Int = { imageSizes.add(it.size); 777 }
        val pictured = message.copy(imageParts = listOf(LLMMessage.ImagePart(ByteArray(5), "image/png")))
        assertEquals(plain + 777, ContextEstimate.request(listOf(pictured), imageTokens = imageCounter))
        val structured = message.copy(content = "ignored aggregate".repeat(1000), contentParts = listOf(
            AgentContentPart.Text(message.content),
            AgentContentPart.ImageData(ByteArray(7), "image/png"),
        ))
        assertEquals(plain + 777, ContextEstimate.request(listOf(structured), imageTokens = imageCounter))
        val toolImage = LLMMessage(LLMMessage.Role.USER, "", contentParts = listOf(
            AgentContentPart.ToolResult("call", "read_image", "", imageData = ByteArray(9)),
        ))
        assertTrue(ContextEstimate.request(listOf(toolImage), imageTokens = imageCounter) >= 777)
        assertEquals(listOf(5, 7, 9), imageSizes)
        val reasoned = message.copy(reasoningContent = "需要先查看报告来源。".repeat(200))
        assertTrue(ContextEstimate.request(listOf(reasoned)) > plain)
    }

    @Test
    fun `native audio bytes do not turn a short prompt into a full text context`() {
        val message = user("请转录这段录音。")
        val audio = LLMMessage.AudioPart(
            "wav", java.util.Base64.getEncoder().encodeToString(ByteArray(96 * 1024)),
        )
        assertTrue(ContextEstimate.text(audio.base64Data) >= 32_000)
        assertEquals(
            ContextEstimate.request(listOf(message)),
            ContextEstimate.request(listOf(message.copy(audioParts = listOf(audio)))),
        )
    }

    @Test
    fun `calibration follows smaller requests and recovers from a high sample`() {
        val calibration = ContextEstimate.Calibration()
        assertTrue(calibration.observe(actualTokens = 40_000, localEstimate = 20_000))
        assertEquals(25_000, calibration.estimate(20_000))
        assertEquals(125, calibration.estimate(100))
        repeat(20) { calibration.observe(actualTokens = 10_000, localEstimate = 20_000) }
        assertTrue(calibration.estimate(20_000) in 10_000..10_100)
        assertTrue(calibration.estimate(100) < 100)
        calibration.reset()
        assertEquals(100, calibration.estimate(100))
        assertEquals(0, calibration.snapshot().samples)
    }

    @Test
    fun `bad usage samples cannot poison later estimates`() {
        val calibration = ContextEstimate.Calibration()
        val badSamples = listOf(
            0 to 20_000, -1 to 20_000, 1000 to 0, 1000 to 127,
            Int.MAX_VALUE to 20_000, 20_000 to Int.MAX_VALUE,
            100_000 to 1000, 100 to 20_000,
        )
        for ((actual, local) in badSamples) assertFalse(calibration.observe(actual, local))
        assertEquals(ContextEstimate.Snapshot(), calibration.snapshot())
        assertEquals(32_038, calibration.estimate(32_038))
    }

    @Test
    fun `usage anchor charges only appended content and rejects a shorter rewritten prompt`() {
        val calibration = ContextEstimate.Calibration(ContextEstimate.Snapshot(scale = 0.5, samples = 10))
        val anchor = ContextEstimate.UsageAnchor(actualInputTokens = 15_000, localInputEstimate = 40_000)
        assertEquals(15_000, anchor.estimateAppendOnly(40_000, calibration))
        assertEquals(16_000, anchor.estimateAppendOnly(42_000, calibration))
        assertNull(anchor.estimateAppendOnly(20_000, calibration))
        // Offload/compaction uses a fresh estimate after the caller discards the old anchor.
        assertEquals(10_000, calibration.estimate(20_000))
        assertNull(ContextEstimate.UsageAnchor(0, 1000).estimateAppendOnly(2000, calibration))
    }

    @Test
    fun `unsupported and corrupt persisted calibration returns to the conservative heuristic`() {
        for (snapshot in listOf(
            ContextEstimate.Snapshot(version = -1, scale = 2.0),
            ContextEstimate.Snapshot(scale = Double.NaN),
            ContextEstimate.Snapshot(scale = Double.POSITIVE_INFINITY),
            ContextEstimate.Snapshot(scale = 50.0),
            ContextEstimate.Snapshot(scale = 0.0),
            ContextEstimate.Snapshot(samples = -1),
        )) assertEquals(1000, ContextEstimate.Calibration(snapshot).estimate(1000))
    }

    @Test
    fun `opaque image and calibrated counts saturate instead of wrapping below zero`() {
        val image = LLMMessage.ImagePart(byteArrayOf(1), "image/png")
        assertEquals(Int.MAX_VALUE, ContextEstimate.request(
            listOf(user("read").copy(imageParts = listOf(image, image))),
            imageTokens = { Int.MAX_VALUE },
        ))
        val calibration = ContextEstimate.Calibration(ContextEstimate.Snapshot(scale = 4.0, samples = 1))
        assertEquals(Int.MAX_VALUE, calibration.estimate(Int.MAX_VALUE))
        assertEquals(0, calibration.estimate(-1))
        assertEquals(Int.MAX_VALUE, ContextEstimate.UsageAnchor(Int.MAX_VALUE - 1, 1000)
            .estimateAppendOnly(Int.MAX_VALUE, calibration))
    }
}
