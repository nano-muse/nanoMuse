package io.github.nanomuse.hands

import android.content.Context
import android.graphics.Color
import android.hardware.display.DisplayManager
import android.os.Build
import android.os.ParcelFileDescriptor
import android.os.SystemClock
import android.view.Display
import android.view.accessibility.AccessibilityWindowInfo
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.openminis.app.accessibility.MinisAccessibilityService
import com.openminis.app.offload.ShizukuManager
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Run on an unlocked test device with Shizuku authorized for nanoMuse and its accessibility
 * service enabled, starting from the launcher. The fixture lives in the instrumentation APK.
 *
 * ./gradlew :app:connectedDebugAndroidTest -Pnm.abi=x86_64 \
 *   -Pandroid.testInstrumentationRunnerArguments.class=io.github.nanomuse.hands.BackgroundHandsDisplayInstrumentedTest \
 *   -Pandroid.testInstrumentationRunnerArguments.handsDisplayTest=true
 */
@RunWith(AndroidJUnit4::class)
class BackgroundHandsDisplayInstrumentedTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context: Context get() = instrumentation.targetContext
    private val pkg: String get() = instrumentation.context.packageName
    private val fixture get() = HandsApps.App("Hands display fixture", pkg)
    private lateinit var service: MinisAccessibilityService

    @Before fun prepare() {
        assumeTrue("opt in on a dedicated test device",
            InstrumentationRegistry.getArguments().getString("handsDisplayTest") == "true")
        assertTrue("Android 14 or later required", Build.VERSION.SDK_INT >= 34)
        until("Enable the accessibility service first.") { MinisAccessibilityService.getInstance() != null }
        service = checkNotNull(MinisAccessibilityService.getInstance())
        until("Start Shizuku and grant nanoMuse access first.") { ShizukuManager.isReady() }
    }

    private fun primaryApps(): Set<String> =
        service.windowsOnAllDisplays[Display.DEFAULT_DISPLAY].orEmpty()
            .filter { it.type == AccessibilityWindowInfo.TYPE_APPLICATION }
            .mapNotNull { it.root?.packageName?.toString() }.toSet()

    private fun until(message: String, predicate: () -> Boolean) {
        val end = SystemClock.elapsedRealtime() + 12_000
        while (!predicate()) {
            assertTrue(message, SystemClock.elapsedRealtime() < end)
            SystemClock.sleep(100)
        }
    }

    @Test fun capturesAndTapsOnlyTheNewDisplayAndRemovesIt() {
        val home = instrumentation.uiAutomation.executeShellCommand(
            "am start -W --display 0 -a android.intent.action.MAIN -c android.intent.category.HOME"
        )
        ParcelFileDescriptor.AutoCloseInputStream(home).use { it.readBytes() }
        until("The launcher did not appear on the main display.") { primaryApps().let { it.isNotEmpty() && pkg !in it } }
        val original = primaryApps()
        val displays = context.getSystemService(DisplayManager::class.java)
        val previous = displays.displays.map { it.displayId }.toSet()
        val session = BackgroundHandsDisplay.open(context, service, fixture)
        val id = try {
            val id = service.windowsOnAllDisplays.let { all ->
                (0 until all.size()).map { all.keyAt(it) }.single { display ->
                    display !in previous && all[display].any { it.root?.packageName == pkg }
                }
            }
            assertTrue(id > Display.DEFAULT_DISPLAY)
            assertEquals(original, primaryApps())
            until("The fixture did not render on the secondary display.") {
                session.roots().any { it.findAccessibilityNodeInfosByText("Ready on display $id").isNotEmpty() }
            }
            assertThrows(IllegalStateException::class.java) { session.tap(10, 10, 60) }
            val screen = session.screenshot()
            val x = screen.width / 2
            val y = screen.height / 2
            try {
                assertEquals(Color.GREEN, screen.getPixel(x, y))
            } finally {
                screen.recycle()
            }
            assertTrue(session.tap(x, y, 60))
            until("The fixture did not receive the tap.") {
                session.roots().any { it.findAccessibilityNodeInfosByText("Tapped on display $id").isNotEmpty() }
            }
            SystemClock.sleep(500) // AccessibilityService rate-limits captures of the same window.
            val tapped = session.screenshot()
            try {
                assertEquals(Color.BLUE, tapped.getPixel(x, y))
            } finally {
                tapped.recycle()
            }
            assertEquals(original, primaryApps())
            assertTrue(session.tap(x, y, 1100))
            assertThrows(BackgroundHandsDisplay.ProtectedScreen::class.java) { session.screenshot() }
            id
        } finally {
            session.close()
        }
        until("The secondary display was not removed.") { displays.getDisplay(id) == null }
        assertThrows(IllegalStateException::class.java) { session.tap(10, 10, 60) }
        assertEquals(original, primaryApps())
    }

    @Test fun refusesFixtureAlreadyVisibleOnThePrimaryDisplay() {
        val before = context.getSystemService(DisplayManager::class.java).displays.map { it.displayId }.toSet()
        val command = "am start -W --display 0 -n $pkg/io.github.nanomuse.hands.HandsDisplayFixture"
        val pfd = instrumentation.uiAutomation.executeShellCommand(command)
        ParcelFileDescriptor.AutoCloseInputStream(pfd).bufferedReader().use { it.readText() }
        until("The fixture did not appear on the primary display.") { pkg in primaryApps() }
        try {
            val refusal = assertThrows(IllegalStateException::class.java) {
                BackgroundHandsDisplay.open(context, service, fixture).close()
            }
            assertTrue(refusal.message, refusal.message.orEmpty().contains("visible on another screen"))
            assertEquals(before, context.getSystemService(DisplayManager::class.java).displays.map { it.displayId }.toSet())
            assertTrue(pkg in primaryApps())
        } finally {
            until("The primary test fixture did not close.") { pkg !in primaryApps() }
        }
    }
}
