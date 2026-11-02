package io.github.nanomuse.skills

import android.content.Context
import com.openminis.app.data.repository.SkillRepository

/** App-managed instructions remain readable and can still be disabled. */
object BundledSkills {
    const val CREATOR_VERSION = "2.1.0"

    fun creator(context: Context): String =
        context.assets.open("nanomuse/skill-creator.md").bufferedReader().use { it.readText() }

    fun canEdit(source: String): Boolean = source != "bundled"

    /** Preserve user-owned names and all installed state when refreshing bundled text. */
    fun creatorUpdate(
        current: SkillRepository.Skill,
        description: String,
        body: String,
        now: Long,
    ): SkillRepository.Skill? {
        if (!current.isReadOnly || current.version >= CREATOR_VERSION) return null
        return current.copy(
            description = description,
            version = CREATOR_VERSION,
            body = body,
            updatedAt = now,
        )
    }
}
