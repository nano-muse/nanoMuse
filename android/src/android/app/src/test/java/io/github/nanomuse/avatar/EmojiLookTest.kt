package io.github.nanomuse.avatar

import java.io.File
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

class EmojiLookTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun `profile keeps a complete Unicode emoji and normalizes its colour`() {
        val look = EmojiLook.fromProfile(JSONObject().put("avatar", "emoji").put("emoji", " 👩🏽‍💻 ").put("color", "A1b2C3"))!!
        assertEquals("👩🏽‍💻", look.emoji)
        assertEquals("#a1b2c3", look.color)
    }

    @Test fun `missing emoji and invalid colour use the other clients defaults`() {
        val look = EmojiLook.fromProfile(JSONObject().put("avatar", "emoji").put("color", "bad-colour"))!!
        assertEquals("✨", look.emoji)
        assertEquals("#0064d4", look.color)
        assertNull(EmojiLook.fromProfile(JSONObject().put("avatar", "dragon")))
        assertNull(EmojiLook.fromProfile(JSONObject().put("avatar", "face")))
    }

    @Test fun `restart reads the look and switching account directories isolates it`() {
        val first = File(tmp.newFolder("first"), "emoji.json")
        val second = File(tmp.newFolder("second"), "emoji.json")
        val look = EmojiLook("🦊", "#112233")
        EmojiLook.save(first, look)
        assertEquals(look, EmojiLook.load(first))
        assertNull(EmojiLook.load(second))
        EmojiLook.save(first, null)
        assertNull(EmojiLook.load(first))
    }

    @Test fun `a rename preserves the remote emoji while an explicit reset publishes dragon`() {
        val look = EmojiLook("🦊", "#112233")
        val body = JSONObject()
        EmojiLook.writeProfile(body, look, changed = false)
        assertFalse(body.has("avatar"))
        EmojiLook.writeProfile(body, look, changed = true)
        assertEquals("emoji", body.getString("avatar"))
        assertEquals("🦊", body.getString("emoji"))
        assertEquals("#112233", body.getString("color"))
        val reset = JSONObject()
        EmojiLook.writeProfile(reset, null, changed = true)
        assertEquals("dragon", reset.getString("avatar"))
    }

    @Test fun `damaged persisted metadata does not prevent startup`() {
        val file = tmp.newFile("emoji.json").apply { writeText("not json") }
        assertNull(EmojiLook.load(file))
    }
}
