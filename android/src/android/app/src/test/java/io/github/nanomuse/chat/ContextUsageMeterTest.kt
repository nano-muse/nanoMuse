package io.github.nanomuse.chat

import com.openminis.app.data.model.AgentContentPart
import com.openminis.app.data.model.AgentToolDefinition
import com.openminis.app.data.model.LLMMessage
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ContextUsageMeterTest {
    private fun user(text: String) = LLMMessage(LLMMessage.Role.USER, text)
    private val calibration = ContextEstimate.Calibration(
        ContextEstimate.Snapshot(scale = 0.5, samples = 10),
    )

    @Test
    fun `exact prefix uses real input plus new content rather than rescaling old input`() {
        val meter = ContextUsageMeter()
        val prefix = listOf(user("Read the report"))
        val first = meter.snapshot("route", "model", prefix, "instructions")
        meter.observe(first, actualInputTokens = 15_000, localInputEstimate = 40_000)
        val next = meter.snapshot("route", "model", prefix + user("Continue"), "instructions")
        assertEquals(16_000, meter.estimate(next, 42_000, calibration))
        assertTrue(meter.lastEstimateUsedAnchor)
        assertEquals(15_000, meter.estimate(first, 40_000, calibration))
    }

    @Test
    fun `same length rewritten history invalidates the anchor permanently`() {
        val meter = ContextUsageMeter()
        val first = meter.snapshot("route", "model", listOf(user("before")))
        meter.observe(first, 1000, 4000)
        val changed = meter.snapshot("route", "model", listOf(user("after!")))
        assertEquals(2000, meter.estimate(changed, 4000, calibration))
        assertFalse(meter.lastEstimateUsedAnchor)
        assertEquals(2000, meter.estimate(first, 4000, calibration))
    }

    @Test
    fun `provider model prompt tools and serializer changes invalidate known usage`() {
        val meter = ContextUsageMeter()
        val messages = listOf(user("question"))
        val tool = AgentToolDefinition("read", "Read a report", emptyMap())
        val first = meter.snapshot("route", "model", messages, "prompt", listOf(tool), "off")
        val changes = listOf(
            meter.snapshot("other", "model", messages, "prompt", listOf(tool), "off"),
            meter.snapshot("route", "other", messages, "prompt", listOf(tool), "off"),
            meter.snapshot("route", "model", messages, "changed", listOf(tool), "off"),
            meter.snapshot("route", "model", messages, "prompt", emptyList(), "off"),
            meter.snapshot("route", "model", messages, "prompt", listOf(tool), "on"),
        )
        for (changed in changes) {
            meter.observe(first, 1000, 4000)
            assertEquals(2000, meter.estimate(changed, 4000, calibration))
        }
    }

    @Test
    fun `mutating a JSON argument or image bytes cannot mutate a captured fingerprint`() {
        val meter = ContextUsageMeter()
        val arguments = JSONObject().put("path", "before.txt")
        val image = byteArrayOf(1, 2, 3)
        val messages = listOf(user("look").copy(contentParts = listOf(
            AgentContentPart.ToolUse("call", "read", arguments),
            AgentContentPart.ImageData(image, "image/png"),
        )))
        val before = meter.snapshot("route", "model", messages)
        meter.observe(before, 1000, 4000)
        arguments.put("path", "after!.txt")
        assertEquals(2000, meter.estimate(meter.snapshot("route", "model", messages), 4000, calibration))
        val beforeImage = meter.snapshot("route", "model", messages)
        meter.observe(beforeImage, 1000, 4000)
        image[0] = 9
        assertEquals(2000, meter.estimate(meter.snapshot("route", "model", messages), 4000, calibration))
    }

    @Test
    fun `reasoning audio and image placeholders are part of the checked prefix`() {
        val meter = ContextUsageMeter()
        val original = user("look").copy(
            reasoningContent = "earlier reasoning",
            audioParts = listOf(LLMMessage.AudioPart("wav", "AQID")),
            imageParts = listOf(LLMMessage.ImagePart(byteArrayOf(1), "image/png", noVisionPlaceholder = "first")),
        )
        val first = meter.snapshot("route", "model", listOf(original))
        for (changed in listOf(
            original.copy(reasoningContent = ""),
            original.copy(audioParts = listOf(LLMMessage.AudioPart("wav", "BAUG"))),
            original.copy(imageParts = original.imageParts.map { it.copy(noVisionPlaceholder = "other") }),
        )) {
            meter.observe(first, 1000, 4000)
            assertEquals(2000, meter.estimate(meter.snapshot("route", "model", listOf(changed)), 4000, calibration))
        }
    }

    @Test
    fun `invalid usage explicit clear and shorter history use calibrated fallback`() {
        val meter = ContextUsageMeter()
        val first = meter.snapshot("route", "model", listOf(user("first"), user("second")))
        meter.observe(first, 1000, 4000)
        assertEquals(1500, meter.estimate(meter.snapshot("route", "model", listOf(user("first"))), 3000, calibration))
        meter.observe(first, 1000, 4000)
        meter.clear()
        assertFalse(meter.lastEstimateUsedAnchor)
        assertEquals(2000, meter.estimate(first, 4000, calibration))
        assertFalse(meter.observe(first, 0, 4000))
        assertEquals(2000, meter.estimate(first, 4000, calibration))
    }
}
