package io.github.nanomuse.skills

import com.openminis.app.data.repository.SkillRepository
import org.yaml.snakeyaml.LoaderOptions
import org.yaml.snakeyaml.DumperOptions
import org.yaml.snakeyaml.Yaml
import org.yaml.snakeyaml.constructor.SafeConstructor
import org.yaml.snakeyaml.nodes.MappingNode
import org.yaml.snakeyaml.nodes.ScalarNode
import org.yaml.snakeyaml.representer.Representer
import java.io.StringReader
import java.security.MessageDigest
import java.util.Locale

/** SKILL.md parsing, serialization and model-facing discovery, shared by Android entry points. */
object SkillDocuments {
    private const val MAX_DESCRIPTION_CODE_POINTS = 1024

    private data class Document(val lines: List<String>, val end: Int, val rawBody: String) {
        val header: String get() = lines.subList(1, end).joinToString("\n")
        val body: String get() = lines.drop(end + 1).joinToString("\n").trim('\n')
    }

    private fun document(content: String): Document? {
        val normalized = content.trimStart('\uFEFF', ' ', '\t', '\r', '\n')
        val lines = normalized.lines()
        if (lines.firstOrNull()?.trimEnd() != "---") return null
        val end = (1 until lines.size).firstOrNull { lines[it].trimEnd() == "---" } ?: return null
        var bodyStart = 0
        repeat(end + 1) {
            val newline = normalized.indexOfAny(charArrayOf('\r', '\n'), bodyStart)
            bodyStart = if (newline < 0) normalized.length else {
                newline + if (normalized[newline] == '\r' && normalized.getOrNull(newline + 1) == '\n') 2 else 1
            }
        }
        return Document(lines, end, normalized.substring(bodyStart))
    }

    private fun yaml(): Yaml {
        val options = LoaderOptions().apply {
            codePointLimit = 65536
            nestingDepthLimit = 32
            maxAliasesForCollections = 20
            isAllowDuplicateKeys = false
            allowRecursiveKeys = false
        }
        val dump = DumperOptions().apply {
            defaultFlowStyle = DumperOptions.FlowStyle.BLOCK
            splitLines = false
        }
        return Yaml(SafeConstructor(options), Representer(dump), dump, options)
    }

    fun parse(content: String): SkillRepository.ParsedSkill? {
        val doc = document(content) ?: return null
        val fields = try {
            val parser = yaml()
            // Validate duplicates, tags and resource limits using safe construction.
            if (parser.load<Any?>(doc.header) !is Map<*, *>) return null
            val node = parser.compose(StringReader(doc.header)) as? MappingNode ?: return null
            node.value.mapNotNull { pair ->
                val key = pair.keyNode as? ScalarNode ?: return@mapNotNull null
                key.value to pair.valueNode
            }.toMap()
        } catch (_: Exception) { return null }
        // ScalarNode retains the lexical string: YAML 1.1 would otherwise turn `on`
        // into Boolean or version 1.10 into Double 1.1. Quoted/block strings are decoded.
        val name = (fields["name"] as? ScalarNode)?.value?.takeIf { it.isNotBlank() } ?: return null
        val description = (fields["description"] as? ScalarNode)?.value ?: ""
        val version = (fields["version"] as? ScalarNode)?.value ?: "1.0.0"
        return SkillRepository.ParsedSkill(name, description, version, doc.body)
    }

    /** Imports are verbatim. Metadata edits preserve all unknown YAML values. */
    fun render(
        skill: SkillRepository.Skill,
        previousContent: String? = null,
        importedContent: String? = null,
        preserveBody: Boolean = false,
    ): String {
        if (importedContent != null) return importedContent
        val parser = yaml()
        val doc = previousContent?.let {
            requireNotNull(parse(it)) { "Existing skill frontmatter is missing, incomplete or invalid" }
            requireNotNull(document(it))
        }
        val header = linkedMapOf<Any?, Any?>()
        if (doc != null) {
            // A semantic rewrite supports quoted keys without duplicating them, while
            // preserving distinct unknown keys such as `Description` and nested metadata.
            val original = parser.load<Any?>(doc.header) as? Map<*, *>
                ?: throw IllegalArgumentException("Skill frontmatter must be a mapping")
            header.putAll(original)
        }
        header["name"] = skill.name
        header["description"] = skill.description
        header["version"] = skill.version
        val body = if (preserveBody && doc != null) doc.rawBody else skill.body
        return "---\n" + parser.dump(header) + "---\n" + body
    }

    /** Values persisted by the legacy parser retained these scalar delimiters. */
    fun isQuoted(value: String): Boolean = value.trim().let {
        it.length >= 2 && it.first() in charArrayOf('\'', '"') && it.last() == it.first()
    }

    /** Preserve existing ASCII directory IDs; give other nonblank names a safe stable fallback. */
    fun id(name: String): String {
        val normalized = name.trim().lowercase(Locale.ROOT)
        val ascii = normalized.replace(Regex("[^a-z0-9]+"), "-").trim('-')
        if (ascii.isNotEmpty() || normalized.isEmpty()) return ascii
        val hash = MessageDigest.getInstance("SHA-256").digest(normalized.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }.take(24)
        return "skill-$hash"
    }

    /** All enabled metadata stays discoverable; instructions are still read only when needed. */
    fun prompt(enabled: List<SkillRepository.Skill>): String? {
        if (enabled.isEmpty()) return null
        return buildString {
            append("Skills:\n")
            append("Reusable instruction sets are listed below with their exact file paths. Read the SKILL.md file before using a skill.\n\n")
            append("<available_skills>\n")
            for (skill in enabled.sortedByDescending { it.updatedAt }) {
                val description = skill.description.let {
                    if (it.codePointCount(0, it.length) <= MAX_DESCRIPTION_CODE_POINTS) it
                    else it.substring(0, it.offsetByCodePoints(0, MAX_DESCRIPTION_CODE_POINTS)) + "…"
                }
                append("  <skill>\n")
                append("    <name>").append(escapeXml(skill.name)).append("</name>\n")
                append("    <description>").append(escapeXml(description)).append("</description>\n")
                append("    <path>/var/minis/skills/").append(escapeXml(skill.id)).append("/SKILL.md</path>\n")
                append("  </skill>\n")
            }
            append("</available_skills>")
        }
    }

    private fun escapeXml(text: String): String = text.replace("&", "&amp;")
        .replace("<", "&lt;").replace(">", "&gt;")
}
