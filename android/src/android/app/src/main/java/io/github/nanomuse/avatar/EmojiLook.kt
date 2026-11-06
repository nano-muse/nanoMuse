package io.github.nanomuse.avatar

import java.io.File
import org.json.JSONObject

data class EmojiLook(val emoji: String, val color: String) {
    companion object {
        const val DEFAULT_EMOJI = "✨"
        const val DEFAULT_COLOR = "#0064d4"

        /** A missing drawn payload must not be recorded as uploaded; unchanged emoji stays shared. */
        fun sharedStamp(body: JSONObject, emoji: EmojiLook?, stamp: String): String =
            if (body.optString("avatar") == "face" || emoji != null) stamp else ""

        fun fromProfile(profile: JSONObject): EmojiLook? {
            if (profile.optString("avatar") != "emoji") return null
            val digits = profile.optString("color").trim().removePrefix("#")
            val color = if (digits.matches(Regex("[0-9a-fA-F]{6}"))) "#${digits.lowercase(java.util.Locale.ROOT)}" else DEFAULT_COLOR
            return EmojiLook(profile.optString("emoji").trim().ifEmpty { DEFAULT_EMOJI }, color)
        }

        fun load(file: File): EmojiLook? = runCatching { fromProfile(JSONObject(file.readText())) }.getOrNull()

        fun save(file: File, look: EmojiLook?) {
            if (look == null) { file.delete(); return }
            file.parentFile?.mkdirs()
            val body = JSONObject()
            writeProfile(body, look, changed = true)
            val temp = File(file.parentFile, file.name + ".tmp")
            temp.writeText(body.toString())
            java.nio.file.Files.move(temp.toPath(), file.toPath(), java.nio.file.StandardCopyOption.REPLACE_EXISTING)
        }

        /** An unchanged look is omitted: a rename must not overwrite a newer remote look. */
        fun writeProfile(body: JSONObject, look: EmojiLook?, changed: Boolean) {
            if (!changed) return
            body.put("avatar", if (look == null) "dragon" else "emoji")
            if (look != null) body.put("emoji", look.emoji).put("color", look.color)
        }
    }
}
