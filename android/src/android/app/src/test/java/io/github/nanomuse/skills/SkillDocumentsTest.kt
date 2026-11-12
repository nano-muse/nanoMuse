package io.github.nanomuse.skills

import com.openminis.app.data.repository.SkillRepository
import org.junit.Assert.*
import org.junit.Test
import org.yaml.snakeyaml.LoaderOptions
import org.yaml.snakeyaml.Yaml
import org.yaml.snakeyaml.constructor.SafeConstructor

class SkillDocumentsTest {
    private fun skill(name: String = "sample", description: String = "Use for samples", body: String = "Instructions") =
        SkillRepository.Skill(id = SkillDocuments.id(name), name = name, description = description, body = body)

    private val original = """
        ---
        name: sample
        description: |-
          First line
          Second line: use this for reports
        version: "2.0"
        license: GPL-3.0-or-later
        allowed-tools: shell read_file
        metadata:
          name: nested-name
          description: nested-description
          version: "9.9"
        channel: team
        ---

        Instructions
    """.trimIndent() + "\n"

    @Test fun runtimeQuotedScalarsDoNotLetNestedMetadataOverwriteTopLevelFields() {
        val parsed = requireNotNull(SkillDocuments.parse(original))
        assertEquals("sample", parsed.name)
        assertEquals("First line\nSecond line: use this for reports", parsed.description)
        assertEquals("2.0", parsed.version)
    }

    @Test fun runtimeDoubleQuotesEscapesAndYamlSingleQuotesAreDecoded() {
        val parsed = requireNotNull(SkillDocuments.parse("""
            ---
            name: 'reader''s helper'
            description: "Use: reports #1 and \"quotes\" in C:\\notes"
            ---
            Body
        """.trimIndent()))
        assertEquals("reader's helper", parsed.name)
        assertEquals("Use: reports #1 and \"quotes\" in C:\\notes", parsed.description)
    }

    @Test fun importKeepsTheOriginalSkillFileIncludingUnknownFrontmatterAndBody() {
        assertEquals(original, SkillDocuments.render(skill(), importedContent = original))
    }

    @Test fun editingKnownFieldsKeepsLicenseToolsChannelAndNestedMetadata() {
        val edited = SkillDocuments.render(skill(description = "New: description"), previousContent = original)
        val metadata = header(edited)
        assertEquals("GPL-3.0-or-later", metadata["license"])
        assertEquals("shell read_file", metadata["allowed-tools"])
        assertEquals("team", metadata["channel"])
        val nested = metadata["metadata"] as Map<*, *>
        assertEquals("nested-name", nested["name"])
        assertEquals("nested-description", nested["description"])
        assertEquals("9.9", nested["version"])
        assertEquals("New: description", SkillDocuments.parse(edited)?.description)
    }

    @Test fun generatedMultilineAndSpecialCharacterValuesRoundTrip() {
        val item = skill(name = "Name: #1", description = "First line\nSecond: \"quoted\"", body = "Body\n")
        val parsed = requireNotNull(SkillDocuments.parse(SkillDocuments.render(item)))
        assertEquals(item.name, parsed.name)
        assertEquals(item.description, parsed.description)
        assertEquals(item.body.trim('\n'), parsed.body)
    }

    @Test fun everyEnabledSkillKeepsItsTriggerDescriptionBeyondTwentyEntries() {
        val items = (1..32).map { skill("skill-$it", "Specific trigger-$it") }
        val prompt = requireNotNull(SkillDocuments.prompt(items))
        for (i in 1..32) assertTrue("description $i", prompt.contains("Specific trigger-$i"))
        assertEquals(32, Regex("<description>").findAll(prompt).count())
    }

    @Test fun aTriggerAfterCharacterTwoHundredReachesTheModel() {
        val description = "a".repeat(220) + " Use for quarterly-reports"
        val prompt = requireNotNull(SkillDocuments.prompt(listOf(skill(description = description))))
        assertTrue(prompt.contains("Use for quarterly-reports"))
    }

    @Test fun descriptionLimitUsesUnicodeCodePointsWithoutSplittingEmoji() {
        val description = "a".repeat(1023) + "😀" + "b"
        val prompt = requireNotNull(SkillDocuments.prompt(listOf(skill(description = description))))
        val disclosed = prompt.substringAfter("<description>").substringBefore("</description>")
        assertEquals("a".repeat(1023) + "😀…", disclosed)
        assertEquals(1025, disclosed.codePointCount(0, disclosed.length))
    }

    @Test fun nonAsciiNamesHaveStableSafeIdsWhileExistingAsciiIdsStayCompatible() {
        assertEquals("my-skill", SkillDocuments.id("My_Skill"))
        val chinese = SkillDocuments.id("报告助手")
        assertTrue(chinese.isNotBlank())
        assertEquals(chinese, SkillDocuments.id("报告助手"))
        assertFalse(chinese.contains('/'))
        assertNotEquals(chinese, SkillDocuments.id("旅行助手"))
    }

    @Test fun promptPointsToTheStoredIdRatherThanTheDisplayName() {
        val prompt = requireNotNull(SkillDocuments.prompt(listOf(skill("My_Skill"))))
        assertTrue(prompt.contains("/var/minis/skills/my-skill/SKILL.md"))
        assertFalse(prompt.contains("/var/minis/skills/<name>/SKILL.md"))
    }

    private fun header(content: String): Map<*, *> = Yaml(SafeConstructor(LoaderOptions()))
        .load<Map<*, *>>(content.substringAfter("---\n").substringBefore("\n---"))

    @Test fun quotedTopLevelKeysCanBeEditedWithoutDuplicatingThem() {
        val previous = "---\nemoji: 😀\n\"name\": sample\n'description': previous\n---\nBody"
        val edited = SkillDocuments.render(skill(name = "new-name", description = "New description"), previousContent = previous)
        assertEquals("new-name", SkillDocuments.parse(edited)?.name)
        assertEquals("New description", SkillDocuments.parse(edited)?.description)
        assertEquals("😀", header(edited)["emoji"])
    }

    @Test fun caseSensitiveUnknownMetadataIsNotConfusedWithKnownFields() {
        val previous = "---\nDescription: Preserve this field\nname: sample\ndescription: previous\n---\nBody"
        val edited = SkillDocuments.render(skill(description = "New description"), previousContent = previous)
        assertEquals("New description", SkillDocuments.parse(edited)?.description)
        assertEquals("Preserve this field", header(edited)["Description"])
    }

    @Test fun scalarNamesAndVersionLexemesRemainStringsInsteadOfYamlImplicitTypes() {
        for (name in listOf("on", "off", "yes", "no", "null")) {
            val parsed = requireNotNull(SkillDocuments.parse("---\nname: $name\ndescription: yes\nversion: 1.10\n---\nBody"))
            assertEquals(name, parsed.name)
            assertEquals("yes", parsed.description)
            assertEquals("1.10", parsed.version)
        }
    }

    @Test fun anIndentedMarkdownFenceIsPartOfTheDescription() {
        val parsed = requireNotNull(SkillDocuments.parse("---\nname: sample\ndescription: |-\n  First\n  ---\n  Last\n---\nBody"))
        assertEquals("First\n---\nLast", parsed.description)
    }

    @Test fun missingOrUnterminatedPreviousFrontmatterCannotBeRewritten() {
        for (previous in listOf(
            "name: sample\nlicense: KEEP-LICENSE\nNew body not in the stored record",
            "---\nname: sample\nlicense: KEEP-LICENSE\nNew body not in the stored record",
            "---\ndescription: No name\nlicense: KEEP-LICENSE\n---\nNew body not in the stored record",
            "---\nname: [not, a, scalar]\nlicense: KEEP-LICENSE\n---\nNew body not in the stored record",
        )) {
            assertThrows(IllegalArgumentException::class.java) {
                SkillDocuments.render(skill(), previousContent = previous)
            }
        }
    }

    @Test fun metadataOnlyEditsRetainTheCurrentDiskBodyWithCrLfOrCrAndNonBmpHeaderText() {
        for (newline in listOf("\r\n", "\r")) {
            val diskBody = newline + "New body not in the stored record" + newline
            val previous = listOf("---", "emoji: 😀", "name: sample", "description: Current", "---")
                .joinToString(newline, postfix = newline) + diskBody
            val edited = SkillDocuments.render(skill(body = "Stale body"), previousContent = previous, preserveBody = true)
            assertEquals(diskBody, edited.substringAfter("\n---\n"))
            val replaced = SkillDocuments.render(skill(body = "Explicit body"), previousContent = previous)
            assertEquals("Explicit body", replaced.substringAfter("\n---\n"))
        }
    }

    @Test fun invalidOrUnboundedFrontmatterDoesNotConstructCustomObjects() {
        assertNull(SkillDocuments.parse("---\nname: sample\nmetadata: !!java.lang.ProcessBuilder [unsafe]\n---\nBody"))
        assertNull(SkillDocuments.parse("---\nname: first\nname: duplicate\n---\nBody"))
        assertNull(SkillDocuments.parse("---\nname: sample\ndescription: " + "x".repeat(65537) + "\n---\nBody"))
        val deeplyNested = (1..40).joinToString("\n") { "  ".repeat(it) + "level: " }
        assertNull(SkillDocuments.parse("---\nname: sample\nmetadata:\n$deeplyNested\n---\nBody"))
        val aliases = List(21) { "*items" }.joinToString(", ")
        assertNull(SkillDocuments.parse("---\nname: sample\nitems: &items [one, two]\nmetadata: [$aliases]\n---\nBody"))
    }
}
