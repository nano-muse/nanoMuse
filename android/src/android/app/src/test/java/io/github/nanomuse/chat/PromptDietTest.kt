package io.github.nanomuse.chat

import com.openminis.app.data.ContextPolicy
import com.openminis.app.tools.AgentTools
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * The prompt diet (1.0.8): the same instructions in fewer tokens. `browser_use` keeps every
 * action, parameter and the hand-over sentence; the Android tools section keeps its
 * `android-*` lines and condenses the `minis-*` paragraphs; the compaction line is 32k on
 * every window from 64k up.
 */
class PromptDietTest {
    private val viewModelSource: String by lazy {
        val f = listOf(
            "src/main/java/com/openminis/app/ui/chat/ChatViewModel.kt",
            "app/src/main/java/com/openminis/app/ui/chat/ChatViewModel.kt",
        ).map(::File).first { it.exists() }
        f.readText()
    }

    @Test
    fun `browser_use says the same in fewer characters`() {
        val tools = AgentTools.makeAgentTools()
        val before = tools.first { it.name == "browser_use" }
        val after = PromptDiet.tools(tools).first { it.name == "browser_use" }
        // every action the enum has is named in the description, so the model knows what each does
        val actions = before.parameters.getValue("action").enumValues!!
        for (action in actions) assertTrue(action, after.description.contains(action))
        assertEquals(before.parameters.keys, after.parameters.keys)
        assertEquals(before.required, after.required)
        assertEquals(before.propertyOrdering, after.propertyOrdering)
        assertEquals(actions, after.parameters.getValue("action").enumValues)
        assertTrue(after.description.contains("call hand_over with a short 'reason'"))
        assertTrue(after.description.contains("Never type credentials"))
        val sizeBefore = before.toOpenAIJson().toString().length
        val sizeAfter = after.toOpenAIJson().toString().length
        assertTrue("$sizeBefore -> $sizeAfter", sizeAfter < sizeBefore - 2_500)
        // every other tool is the very same object
        val others = tools.filter { it.name != "browser_use" }
        val dieted = PromptDiet.tools(tools).filter { it.name != "browser_use" }
        others.zip(dieted).forEach { (a, b) -> assertSame(a, b) }
    }

    @Test
    fun `the Android tools section keeps its android lines and condenses the minis paragraphs`() {
        // the upstream prompt still has the section where this expects it
        assertTrue(viewModelSource.contains(PromptDiet.SECTION_HEAD))
        assertTrue(viewModelSource.contains(PromptDiet.SECTION_END))
        val base = "Tone and style:\n- Be concise.\n" +
            PromptDiet.SECTION_HEAD +
            "CLI tools at /usr/local/bin with the `android-` prefix give you access to Android framework capabilities.\n" +
            "- android-alarm — schedule alarms/timers (`schedule <HH:MM>`).\n" +
            "- android-weather <latitude> <longitude> — Open-Meteo forecast.\n" +
            "- minis-open <url-or-path>: Opens a resource inside nanoMuse without leaving the chat. " + "x".repeat(700) + "\n" +
            "- minis-sessions-cli: Manage chat sessions. Run --help for full options.\n" +
            "- minis-model-use: Invoke other LLM models pre-configured by the user. " + "x".repeat(1600) + "\n" +
            "- minis-config: Read or change nanoMuse settings programmatically. " + "x".repeat(1500) + "\n" +
            "- minis-scheduled: Create and manage scheduled tasks. " + "x".repeat(800) + "\n" +
            "- minis-new-thing: a CLI this diet does not know about.\n" +
            "Interactive terminal: minis://open_terminal opens a terminal. " + "x".repeat(500) +
            PromptDiet.SECTION_END +
            "\n- Shell environment variables may contain sensitive API keys.\n\nScheduled tasks: crontab will stop."
        val out = PromptDiet.prompt(base)
        assertTrue(out.startsWith("Tone and style:\n- Be concise.\n" + PromptDiet.SECTION_HEAD + "CLI tools at /usr/local/bin"))
        assertTrue(out.endsWith(PromptDiet.SECTION_END + "\n- Shell environment variables may contain sensitive API keys.\n\nScheduled tasks: crontab will stop."))
        assertTrue(out.contains("- android-alarm — schedule alarms/timers (`schedule <HH:MM>`).\n"))
        assertTrue(out.contains("- android-weather <latitude> <longitude> — Open-Meteo forecast.\n"))
        assertTrue(out.contains("- minis-sessions-cli: Manage chat sessions. Run --help for full options.\n"))
        assertTrue(out.contains("- minis-new-thing: a CLI this diet does not know about.\n"))
        assertFalse(out.contains("xxxx"))
        for (cli in listOf("- minis-open <url-or-path>:", "- minis-model-use:", "- minis-config:", "- minis-scheduled:", "Interactive terminal:")) {
            assertEquals(cli, 1, out.windowed(cli.length).count { it == cli })
        }
        assertTrue(out.contains("minis-config --help"))
        assertTrue(out.contains("minis://open_terminal?init_command=ssh%20user%40host"))
        assertTrue("${base.length} -> ${out.length}", out.length < base.length - 2_000)
        // the condensed lines have no dash to spare: every paragraph is one line
        assertEquals(base.count { it == '\n' }, out.count { it == '\n' })
    }

    @Test
    fun `a prompt without the section is returned as it is`() {
        val base = "Tone and style:\n- Be concise.\n\nEnvironment variables:\n- none"
        assertSame(base, PromptDiet.prompt(base))
        val headOnly = "x" + PromptDiet.SECTION_HEAD + "- minis-config: long\nno end marker"
        assertSame(headOnly, PromptDiet.prompt(headOnly))
    }

    @Test
    fun `legacy policy keeps model tiers without a universal 32k cap`() {
        for (window in listOf(64_000, 100_000, 128_000, 200_000, 1_000_000)) {
            val policy = ContextPolicy.forContextWindow(window)
            val reserve = if (window < 128_000) 10_000 else 20_000
            assertEquals(window - reserve, policy.compactThreshold)
            assertFalse(policy.exhaustedOnly)
            assertTrue(policy.manualCompactAllowed)
            assertEquals(ContextPolicy.CheckResult.OK, policy.check(32_000, window))
            assertEquals(ContextPolicy.CheckResult.NEEDS_COMPACT, policy.check(window - reserve, window))
        }
        val small = ContextPolicy.forContextWindow(40_000)
        assertEquals(0, small.compactThreshold)
        assertEquals(30_000, small.offloadThreshold)
        assertTrue(small.exhaustedOnly)
        assertEquals(0, ContextPolicy.forContextWindow(16_000).offloadThreshold)
    }
}
