package io.github.nanomuse.media

import io.github.nanomuse.avatar.AvatarMotion
import io.github.nanomuse.ui.avatar.AgentMood
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class MediaTest {

    @Test fun `args take flag value, flag=value and positionals`() {
        val a = MediaOffloadHandler.Args(listOf("image", "--prompt", "a corgi", "--size=512x512", "--from", "/var/minis/attachments/x.png", "--dry"))
        assertEquals(listOf("image"), a.positional)
        assertEquals("a corgi", a.get("prompt"))
        assertEquals("512x512", a.get("size"))
        assertEquals("/var/minis/attachments/x.png", a.get("from"))
        assertEquals("true", a.get("dry"))
        assertNull(a.get("seconds"))
    }

    @Test fun `only dashscope-shaped hosts are offered for video`() {
        assertTrue(VideoGen.speaksDashScope("https://dashscope.aliyuncs.com/compatible-mode/v1"))
        assertTrue(VideoGen.speaksDashScope("https://llm-abc.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"))
        assertTrue(VideoGen.speaksDashScope("http://10.0.2.2:8823/dashscope/v1"))
        assertFalse(VideoGen.speaksDashScope("https://api.openai.com/v1"))
        assertFalse(VideoGen.speaksDashScope("https://openrouter.ai/api/v1"))
    }

    @Test fun `public Cloud ignores retired cached media while self hosted relays follow their menu`() {
        val candidates = listOf("Qwen/Qwen3.6-27B-FP8", "qwen-image-3.0", "wan2.2-i2v-flash")
        val oldMenu = listOf("qwen-image-3.0", "wan2.2-i2v-flash")
        val current = listOf("musesteamer-air-image", "ernie-wizshot-me")
        assertEquals(current, RelayMediaPolicy.available("https://cloud.nanomuse.cn", oldMenu + current, candidates + current))
        assertEquals(emptyList<String>(), RelayMediaPolicy.available("https://cloud.nanomuse.cn", emptyList(), current))
        assertTrue(VideoGen.looksLikeVideoModel("ernie-wizshot-me"))
        assertEquals(
            emptyList<String>(),
            RelayMediaPolicy.available("https://cloud.nanomuse.cn/", oldMenu, candidates),
        )
        assertEquals(
            emptyList<String>(),
            RelayMediaPolicy.available("https://CLOUD.NANOMUSE.CN:443/v1", oldMenu, candidates),
        )
        assertEquals(
            oldMenu,
            RelayMediaPolicy.available("https://relay.example/v1", oldMenu, candidates),
        )
        assertEquals(
            listOf("qwen-image-3.0"),
            RelayMediaPolicy.available(
                "https://relay.example",
                listOf("qwen-image-3.0"),
                candidates,
            ),
        )
    }

    @Test fun `wan siblings and resolutions follow the model family`() {
        assertEquals("wan2.2-i2v-flash", MediaModels.DEFAULT_VIDEO_MODEL)
        assertEquals("wan2.2-i2v-flash", VideoGen.KNOWN_DASHSCOPE_MODELS.first())
        assertEquals("wan2.2-i2v-flash", VideoGen.modelFor("wan2.2-i2v-flash", fromImage = true))
        assertEquals("wan2.2-t2v-plus", VideoGen.modelFor("wan2.2-i2v-flash", fromImage = false)) // there is no 2.2 t2v flash
        assertEquals("wan2.6-t2v", VideoGen.modelFor("wan2.6-i2v", fromImage = false))
        assertEquals("wan2.6-i2v", VideoGen.modelFor("wan2.6-t2v", fromImage = true))
        assertEquals("MiniMax/MiniMax-H3", VideoGen.modelFor("MiniMax/MiniMax-H3", fromImage = false))
        assertEquals("wan2.7-i2v", VideoGen.modelFor("wan2.7-t2v-2026-06-12", fromImage = true)) // the dated snapshots differ between the two jobs
        assertEquals("wan2.7-i2v-2026-04-25", VideoGen.modelFor("wan2.7-i2v-2026-04-25", fromImage = true))
        assertEquals("wan2.7-t2v", VideoGen.modelFor("wan2.7-i2v", fromImage = false))
        assertTrue(VideoGen.KNOWN_DASHSCOPE_MODELS.containsAll(listOf("wan2.7-i2v", "wan2.7-t2v")))
        assertEquals("480P", VideoGen.wanResolution("wan2.2-i2v-flash"))
        assertEquals("720P", VideoGen.wanResolution("wan2.6-i2v"))
    }

    @Test fun `a video entry is known by its modalities or its name, and own entries join the probe's answer`() {
        assertTrue(VideoGen.isVideoEntry("wan2.7-t2v-2026-06-12", null)) // a hand-added snapshot, modalities empty (#508)
        assertTrue(VideoGen.isVideoEntry("my-clip-maker", listOf("video"))) // marked in the entry's details, whatever the name
        assertTrue(VideoGen.isVideoEntry("my-clip-maker", listOf("VIDEO_OUTPUT")))
        assertFalse(VideoGen.isVideoEntry("qwen3-max", listOf("text")))
        assertFalse(VideoGen.isVideoEntry("wan2.7-image", null))
        assertEquals(
            listOf("wan2.2-i2v-flash", "wan2.7-t2v-2026-06-12"),
            MediaModels.merge(listOf("wan2.2-i2v-flash"), listOf("wan2.7-t2v-2026-06-12", "wan2.2-i2v-flash")),
        )
        assertEquals(listOf("wan2.7-t2v-2026-06-12"), MediaModels.merge(null, listOf("wan2.7-t2v-2026-06-12")))
        assertEquals(emptyList<String>(), MediaModels.merge(emptyList(), emptyList()))
    }

    @Test fun `task bodies follow the family, Wan img_url, Wan 2 7 media and ratio, MiniMax 768P`() {
        val wan = VideoGen.imageToVideoBody("wan2.2-i2v-flash", "oss://x/y.png", "p", 4)
        assertEquals("oss://x/y.png", wan.getJSONObject("input").getString("img_url"))
        assertEquals("480P", wan.getJSONObject("parameters").getString("resolution"))
        assertFalse(wan.getJSONObject("parameters").has("duration"))
        val wan27 = VideoGen.imageToVideoBody("wan2.7-i2v", "oss://x/y.png", "p", 4)
        val media = wan27.getJSONObject("input").getJSONArray("media").getJSONObject(0)
        assertEquals("first_frame", media.getString("type"))
        assertEquals("oss://x/y.png", media.getString("url"))
        assertFalse(wan27.getJSONObject("input").has("img_url"))
        assertEquals("720P", wan27.getJSONObject("parameters").getString("resolution"))
        assertEquals(4, wan27.getJSONObject("parameters").getInt("duration"))
        val mm = VideoGen.imageToVideoBody("MiniMax/MiniMax-H3", "oss://x/y.png", "p", 2)
        assertEquals("768P", mm.getJSONObject("parameters").getString("resolution"))
        assertEquals(4, mm.getJSONObject("parameters").getInt("duration"))
        val t2v = VideoGen.textToVideoBody("wan2.2-t2v-plus", "p", 4, "16:9")
        assertEquals("1280*720", t2v.getJSONObject("parameters").getString("size"))
        val t2v27 = VideoGen.textToVideoBody("wan2.7-t2v", "p", 4, "21:9")
        assertEquals("16:9", t2v27.getJSONObject("parameters").getString("ratio"))
        assertEquals("720P", t2v27.getJSONObject("parameters").getString("resolution"))
        assertFalse(t2v27.getJSONObject("parameters").has("size"))
    }

    @Test fun `failure messages are plain for the user`() {
        val notActivated = JSONObject().put("code", "InvalidParameter").put("message", "The product is not activated, please activate it first")
        assertTrue(VideoGen.failureMessage(notActivated).contains("activate"))
        assertFalse(VideoGen.failureMessage(notActivated).contains("InvalidParameter"))
        assertEquals("Throttling: too many requests", VideoGen.failureMessage(JSONObject().put("code", "Throttling").put("message", "too many requests")))
        assertEquals("Video task CANCELED", VideoGen.failureMessage(JSONObject().put("task_status", "CANCELED")))
        assertEquals("Video task failed", VideoGen.failureMessage(JSONObject()))
    }

    @Test fun `every animated mood has a distinct prompt on a white background`() {
        val prompts = AvatarMotion.animated.map { AvatarMotion.motionPrompt(it) }
        assertEquals(prompts.size, prompts.toSet().size)
        prompts.forEach { assertTrue(it, it.contains("white background", ignoreCase = true)) }
        assertTrue(AvatarMotion.motionPrompt(AgentMood.WAITING).contains("crystal ball"))
        assertTrue(AvatarMotion.motionPrompt(AgentMood.HAPPY).contains("star"))
        assertTrue(AvatarMotion.motionPrompt(AgentMood.WORKING).contains("laptop"))
    }

    @Test fun `the missing-model addendum points at the setting and forbids inventing`() {
        val text = MediaModels.missingImageAddendum()
        assertTrue(text.contains(MediaModels.DEEP_LINK))
        assertTrue(text.contains("Bailian") && text.contains("Gemini") && text.contains("OpenRouter"))
        assertTrue(text.contains("not a ChatGPT plan signed in through Codex"))
        assertTrue(text.contains("do not describe or invent"))
    }

    @Test fun `help names the three subcommands and the setting`() {
        listOf("status", "image", "video", "--prompt", "--from", "--seconds").forEach { assertTrue(it, MediaOffloadHandler.HELP.contains(it)) }
        assertTrue(MediaOffloadHandler.HELP.contains(MediaModels.DEEP_LINK))
    }
}
