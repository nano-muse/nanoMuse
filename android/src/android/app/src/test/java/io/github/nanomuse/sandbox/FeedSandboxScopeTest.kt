package io.github.nanomuse.sandbox

import android.content.Context
import com.openminis.app.tools.FileEditTool
import com.openminis.app.tools.FileWriteTool
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.mockito.Mockito.mock
import java.io.File

class FeedSandboxScopeTest {
    private lateinit var base: File
    private lateinit var source: File
    private lateinit var mirror: File

    @Before
    fun setUp() {
        base = File(System.getProperty("java.io.tmpdir"), "feed-scope-${System.nanoTime()}")
        source = File(base, "source").apply { mkdirs() }
        mirror = File(base, "mirror")
    }

    @After
    fun tearDown() {
        makeWritable(base)
        base.deleteRecursively()
    }

    @Test
    fun `feed guest directory and descendants are read only`() {
        assertEquals("/var/minis/feed", FeedSandboxScope.LINUX_ROOT)
        assertTrue(FeedSandboxScope.isReadOnlyPath("/var/minis/feed"))
        assertTrue(FeedSandboxScope.isReadOnlyPath("/var/minis/feed/2026-10-23/01.md"))
        assertFalse(FeedSandboxScope.isReadOnlyPath("/var/minis/feedback.md"))
    }

    @Test
    fun `mirror copies one day level and exposes liked frontmatter`() {
        val day = File(source, "2026-10-23").apply { mkdirs() }
        File(day, "01.md").writeText("---\nliked: true\n---\n\nUseful topic\n")
        File(day, "02.md").writeText("---\npreparation: a1\n---\nQuoted private records")
        File(day, "notes.txt").writeText("not a post")
        File(File(day, "nested").apply { mkdirs() }, "02.md").writeText("too deep")
        File(source, "not-a-day").apply { mkdirs() }.resolve("03.md").writeText("wrong dir")

        FeedSandboxScope.refresh(source, mirror)

        val visible = File(mirror, "2026-10-23/01.md")
        assertTrue(visible.readText().contains("liked: true"))
        assertFalse(File(mirror, "2026-10-23/02.md").exists())
        assertFalse(File(mirror, "2026-10-23/notes.txt").exists())
        assertFalse(File(mirror, "2026-10-23/nested/02.md").exists())
        assertFalse(File(mirror, "not-a-day/03.md").exists())
    }

    @Test
    fun `mirror rejects ordinary writes and never changes host feed`() {
        val hostPost = File(File(source, "2026-10-23").apply { mkdirs() }, "01.md")
        hostPost.writeText("---\nliked: true\n---\n")
        FeedSandboxScope.refresh(source, mirror)
        val mirroredPost = File(mirror, "2026-10-23/01.md")

        val writeFailed = runCatching { mirroredPost.writeText("---\nliked: false\n---\n") }.isFailure

        assertTrue("the sandbox copy must reject a direct write", writeFailed)
        assertEquals("---\nliked: true\n---\n", hostPost.readText())

        makeWritable(mirroredPost)
        mirroredPost.writeText("tampered mirror")
        assertEquals("a bypass may alter only the disposable mirror", "---\nliked: true\n---\n", hostPost.readText())
        FeedSandboxScope.refresh(source, mirror)
        assertEquals("---\nliked: true\n---\n", mirroredPost.readText())
    }

    @Test
    fun `file tools reject writes anywhere under feed mapping`() {
        val context = mock(Context::class.java)
        val write = FileWriteTool.execute(
            """{"tool_title":"test","path":"/var/minis/feed/2026-10-23/01.md","content":"changed"}""",
            "session",
            context,
        )
        val edit = FileEditTool.execute(
            """{"tool_title":"test","path":"/var/minis/feed/2026-10-23/01.md","old_string":"liked: true","new_string":"liked: false"}""",
            "session",
            context,
        )

        assertFalse(write.success)
        assertFalse(edit.success)
        assertTrue(write.output.contains("read-only Feed"))
        assertTrue(edit.output.contains("read-only Feed"))
    }

    private fun makeWritable(file: File) {
        if (!file.exists()) return
        file.setWritable(true, false)
        if (file.isDirectory) file.listFiles()?.forEach(::makeWritable)
    }
}
