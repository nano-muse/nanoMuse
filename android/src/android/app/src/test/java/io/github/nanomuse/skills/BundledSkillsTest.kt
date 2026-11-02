package io.github.nanomuse.skills

import com.openminis.app.data.repository.SkillRepository
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class BundledSkillsTest {
    @Test
    fun bundledUpgradePreservesInstalledState() {
        val installed = SkillRepository.Skill(
            id = "skill-creator", name = "skill-creator", version = "2.0.0",
            importSource = SkillRepository.ImportSource.BUNDLED,
            isEnabled = false, installedAt = 10L, updatedAt = 20L,
            useCount = 7.5, body = "Legacy instructions",
        )
        val updated = requireNotNull(BundledSkills.creatorUpdate(installed, "New guide", "New body", 30L))
        assertEquals(installed.id, updated.id)
        assertEquals(installed.name, updated.name)
        assertEquals(installed.importSource, updated.importSource)
        assertEquals(installed.installedAt, updated.installedAt)
        assertEquals(installed.useCount, updated.useCount, 0.0)
        assertFalse(updated.isEnabled)
        assertTrue(updated.isReadOnly)
        assertEquals("New guide", updated.description)
        assertEquals("New body", updated.body)
        assertEquals(30L, updated.updatedAt)
        assertEquals(BundledSkills.CREATOR_VERSION, updated.version)
        assertNull(BundledSkills.creatorUpdate(updated, "Again", "Again", 40L))
    }

    @Test
    fun userOwnedSkillWithBundledNameIsNeverUpgraded() {
        for (source in listOf(
            SkillRepository.ImportSource.FILE,
            SkillRepository.ImportSource.URL,
            SkillRepository.ImportSource.SESSION,
        )) {
            val own = SkillRepository.Skill(
                id = "skill-creator", name = "skill-creator", importSource = source,
                body = "My instructions", version = "1.0.0",
            )
            assertFalse(own.isReadOnly)
            assertNull(BundledSkills.creatorUpdate(own, "Bundled", "Bundled body", 30L))
            assertEquals("My instructions", own.body)
        }
    }
}
