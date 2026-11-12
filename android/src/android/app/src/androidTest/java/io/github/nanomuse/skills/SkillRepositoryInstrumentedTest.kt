package io.github.nanomuse.skills

import android.content.Context
import android.content.ContextWrapper
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.openminis.app.data.repository.SkillRepository
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.yaml.snakeyaml.LoaderOptions
import org.yaml.snakeyaml.Yaml
import org.yaml.snakeyaml.constructor.SafeConstructor
import java.io.File
import java.util.UUID

/** Uses private fixture files and a separate SQLite database, never the app's installed skills. */
@RunWith(AndroidJUnit4::class)
class SkillRepositoryInstrumentedTest {
    private fun isolatedContext(): Context {
        val app = InstrumentationRegistry.getInstrumentation().targetContext
        val root = File(app.cacheDir, "skill-fixture-${UUID.randomUUID()}").apply { mkdirs() }
        return object : ContextWrapper(app) {
            override fun getFilesDir(): File = File(root, "files").apply { mkdirs() }
            override fun getDatabasePath(name: String): File = File(root, "databases/$name").also {
                it.parentFile?.mkdirs()
            }
        }
    }

    @Test fun fileImportAndFullUpdatesPreserveSourceAndKeepTheExistingId() {
        val context = isolatedContext()
        val repo = SkillRepository(context)
        val source = """
            ---
            name: reports
            description: |-
              First line
              Second line: when to use it
            version: "2.0"
            license: GPL-3.0-or-later
            metadata:
              name: nested-name
              description: nested-description
              version: "9.9"
            allowed-tools: read_file
            channel: team
            ---

            Instructions
        """.trimIndent() + "\n"
        val imported = requireNotNull(repo.importFromContent(source))
        val file = File(repo.skillFileHostPath(imported.id, "SKILL.md"))
        assertEquals(source, file.readText())
        assertEquals("reports", imported.name)
        assertEquals("2.0", imported.version)
        assertTrue(imported.description.endsWith("when to use it"))
        repo.setEnabled(imported.id, false)
        repo.setSessionOverride("session", imported.id, true)
        val update = source.replace("name: reports", "name: renamed-reports")
        assertTrue(repo.updateFromContent(imported.id, update))
        assertEquals(update, file.readText())
        assertEquals("renamed-reports", repo.skills.value.first { it.id == imported.id }.name)
        assertFalse(repo.skills.value.first { it.id == imported.id }.isEnabled)
        assertTrue(repo.isEnabledForSession(imported.id, "session"))
        assertTrue(repo.renameSkill(imported.id, "Reports: #1"))
        assertTrue(file.readText().contains("license: GPL-3.0-or-later"))
        val header = Yaml(SafeConstructor(LoaderOptions())).load<Map<*, *>>(
            file.readText().substringAfter("---\n").substringBefore("\n---"),
        )
        assertEquals("9.9", (header["metadata"] as Map<*, *>)["version"])
        val reopened = SkillRepository(context).skills.value.first { it.id == imported.id }
        assertEquals("Reports: #1", reopened.name)
        assertEquals("2.0", reopened.version)
    }

    @Test fun allEnabledTriggersAndUnicodeNamesRemainDiscoverableThroughTheRepository() {
        val repo = SkillRepository(isolatedContext())
        for (i in 1..32) {
            assertNotNull(repo.importFromContent("---\nname: reports-$i\ndescription: " +
                "a".repeat(220) + " trigger-$i\n---\nInstructions"))
        }
        val chinese = requireNotNull(repo.importFromContent("---\nname: 报告助手\ndescription: 用于分析报告\n---\nInstructions"))
        assertTrue(chinese.id.isNotBlank())
        val prompt = requireNotNull(repo.skillPromptFragment("session"))
        for (i in 1..32) assertTrue("trigger-$i", prompt.contains("trigger-$i"))
        assertTrue(prompt.contains("/var/minis/skills/${chinese.id}/SKILL.md"))
        repo.setEnabled(chinese.id, false)
        assertFalse(requireNotNull(repo.skillPromptFragment("session")).contains("<name>报告助手</name>"))
        repo.setSessionOverride("session", chinese.id, true)
        assertTrue(requireNotNull(repo.skillPromptFragment("session")).contains("<name>报告助手</name>"))
    }

    @Test fun malformedLegacyYamlRejectsMetadataEditsWithoutCrashingOrChangingTheFile() {
        val context = isolatedContext()
        val repo = SkillRepository(context)
        val source = "---\nname: sample\ndescription: valid text\n---\nInstructions"
        val installed = requireNotNull(repo.importFromContent(source))
        val file = File(repo.skillFileHostPath(installed.id, "SKILL.md"))
        val legacy = "---\nname: sample\ndescription: Use: reports\n---\nInstructions"
        file.writeText(legacy)
        assertFalse(repo.renameSkill(installed.id, "New name"))
        assertFalse(repo.update(installed.id, description = "New description"))
        assertEquals(legacy, file.readText())
        val reopened = SkillRepository(context).skills.value.first { it.id == installed.id }
        assertEquals("sample", reopened.name)
        assertEquals("valid text", reopened.description)
        assertTrue(repo.updateFromContent(installed.id, source))
        assertEquals(source, file.readText())
    }
}
