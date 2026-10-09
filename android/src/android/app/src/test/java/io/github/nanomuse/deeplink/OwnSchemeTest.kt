package io.github.nanomuse.deeplink

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** The app's two link names: `minis` inside, `nanomuse` towards the system; nothing else is ours. */
class OwnSchemeTest {
    /** The module directory is the working directory of a unit test; the project directory when run from the IDE. */
    private fun source(rel: String): File = listOf(rel, "app/$rel").map(::File).first { it.exists() }

    @Test
    fun `both names are ours, in any case, and nothing else is`() {
        for (s in listOf("minis", "MINIS", "nanomuse", "NanoMuse")) assertTrue(s, OwnScheme.isOwn(s))
        for (s in listOf(null, "", "http", "https", "minis-mcp", "nanomuse-mcp", "intent", "file")) {
            assertFalse(s ?: "null", OwnScheme.isOwn(s))
        }
    }

    @Test
    fun `the system's name reads as the app's own`() {
        assertEquals("minis", OwnScheme.internal("nanomuse"))
        assertEquals("minis", OwnScheme.internal("NANOMUSE"))
        assertEquals("minis", OwnScheme.internal("minis"))
        assertEquals("https", OwnScheme.internal("https"))
        assertEquals(null, OwnScheme.internal(null))
        assertEquals("minis://settings/soul", OwnScheme.internalUrl("nanomuse://settings/soul"))
        assertEquals("minis://session/abc/index.html?title=x", OwnScheme.internalUrl("NanoMuse://session/abc/index.html?title=x"))
        assertEquals("minis://attachments/a.png", OwnScheme.internalUrl("minis://attachments/a.png"))
        assertEquals("https://nanomuse.cn/", OwnScheme.internalUrl("https://nanomuse.cn/"))
        // the host part is not a scheme
        assertEquals("https://nanomuse.cn/nanomuse://x", OwnScheme.internalUrl("https://nanomuse.cn/nanomuse://x"))
    }

    @Test
    fun `the manifest registers the system's name only, and the deep-link activity by its class`() {
        val manifest = source("src/main/AndroidManifest.xml").readText()
        assertTrue(manifest.contains("android:scheme=\"${OwnScheme.SYSTEM}\""))
        assertFalse("upstream's scheme must not be registered with the system", manifest.contains("android:scheme=\"${OwnScheme.INTERNAL}\""))
        assertTrue(manifest.contains("android:name=\".MainActivity\""))
        assertEquals("com.openminis.app.MainActivity", OwnScheme.ACTIVITY)
    }

    @Test
    fun `no implicit VIEW intent on the app's own links is left in the sources`() {
        // an implicit intent on `minis://` is resolved by the system, which can hand it to another app
        // that registers the scheme; every one of ours is addressed to MainActivity by name instead
        val root = source("src/main/java")
        val offenders = root.walkTopDown().filter { it.isFile && it.extension == "kt" && it.name != "OwnScheme.kt" }.flatMap { file ->
            val lines = file.readLines()
            lines.indices.filter { i ->
                val window = lines.subList(i, minOf(lines.size, i + 3)).joinToString(" ")
                Regex("""Intent\(\s*(android\.content\.)?Intent\.ACTION_VIEW\s*,[^)]*"minis://""").containsMatchIn(window)
            }.map { "${file.relativeTo(root)}:${it + 1}" }
        }.toList()
        assertEquals(emptyList<String>(), offenders)
    }
}
