package io.github.nanomuse.hands

import android.content.Context
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Point
import android.graphics.Rect
import android.hardware.display.DisplayManager
import android.media.ImageReader
import android.os.Build
import android.os.ParcelFileDescriptor
import android.os.SystemClock
import android.view.Display
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityWindowInfo
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.openminis.app.accessibility.MinisAccessibilityService
import com.openminis.app.offload.ShizukuManager
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
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
            until("The preview did not show the fixture.") {
                val preview = session.preview() ?: return@until false
                try {
                    preview.width <= 320 && preview.height <= 640 && preview.getPixel(preview.width / 2, preview.height / 2) == Color.GREEN
                } finally { preview.recycle() }
            }
            // A UI observer may see the fixture before the operator has seen any screenshot.
            assertThrows(IllegalStateException::class.java) { session.tap(10, 10, 60) }
            val screen = session.screenshot()
            val x = screen.width / 2
            val y = screen.height / 2
            try {
                @Suppress("DEPRECATION")
                val size = Point().also { displays.getDisplay(id).getRealSize(it) }
                assertEquals(size.x, screen.width)
                assertEquals(size.y, screen.height)
                assertEquals(Color.GREEN, screen.getPixel(x, y))
            } finally {
                screen.recycle()
            }
            assertTrue(session.tap(x, y, 60))
            until("The fixture did not receive the tap.") {
                session.roots().any { it.findAccessibilityNodeInfosByText("Tapped on display $id").isNotEmpty() }
            }
            until("The preview did not update after input.") {
                val preview = session.preview() ?: return@until false
                try { preview.getPixel(preview.width / 2, preview.height / 2) == Color.BLUE } finally { preview.recycle() }
            }
            // Request the model screenshot immediately after a preview, including on rate-limited devices.
            val tapped = session.screenshot()
            try {
                assertEquals(Color.BLUE, tapped.getPixel(x, y))
            } finally {
                tapped.recycle()
            }
            assertEquals(original, primaryApps())
            ImageReader.newInstance(320, 480, PixelFormat.RGBA_8888, 2).use { competing ->
                val rejected = assertThrows(IllegalStateException::class.java) {
                    HandsDisplayHost.open(context, competing.surface, 320, 480, 280).close()
                }
                assertTrue(rejected.message.orEmpty().contains("already open"))
            }
            assertTrue(session.tap(x, y, 1100))
            assertThrows(BackgroundHandsDisplay.ProtectedScreen::class.java) { session.screenshot() }
            assertNull(session.preview())
            assertThrows(IllegalStateException::class.java) { session.roots() }
            assertThrows(IllegalStateException::class.java) { session.back() }
            id
        } finally {
            session.close()
        }
        until("The secondary display was not removed.") { displays.getDisplay(id) == null }
        assertThrows(IllegalStateException::class.java) { session.tap(10, 10, 60) }
        assertEquals(original, primaryApps())
    }

    @Test fun movingTheSameWindowNeedsANewModelScreenshotAndPasswordFieldsHideThePreview() {
        BackgroundHandsDisplay.open(context, service, fixture).use { session ->
            session.screenshot().recycle()
            val button = session.roots().single().findAccessibilityNodeInfosByText("Moving window").single()
            assertTrue(button.performAction(AccessibilityNodeInfo.ACTION_CLICK))
            fun dialog(): AccessibilityWindowInfo? {
                val displays = service.windowsOnAllDisplays
                return (0 until displays.size()).asSequence().filter { displays.keyAt(it) != Display.DEFAULT_DISPLAY }
                    .flatMap { displays.valueAt(it).asSequence() }.firstOrNull {
                        it.root?.packageName == pkg && it.root?.findAccessibilityNodeInfosByText("Move dialog")?.isNotEmpty() == true
                    }
            }
            until("The fixture's dialog did not appear.") { dialog() != null }
            session.screenshot().recycle()
            val original = checkNotNull(dialog())
            val oldBounds = Rect().also { original.getBoundsInScreen(it) }
            val move = session.roots().single().findAccessibilityNodeInfosByText("Move dialog").single()
            assertTrue(move.performAction(AccessibilityNodeInfo.ACTION_CLICK))
            until("Android did not move the fixture window.") {
                dialog()?.let { it.id == original.id && Rect().also { r -> it.getBoundsInScreen(r) } != oldBounds } == true
            }
            // Even a successful fresh preview cannot turn old model coordinates into safe input.
            until("The moved window could not be previewed.") { session.preview()?.let { it.recycle(); true } == true }
            assertThrows(IllegalStateException::class.java) { session.tap(oldBounds.centerX(), oldBounds.centerY(), 60) }
            session.screenshot().recycle()
            val form = session.roots().single().findAccessibilityNodeInfosByText("Change form").single()
            assertTrue(form.performAction(AccessibilityNodeInfo.ACTION_CLICK))
            until("Android did not expose the private field.") {
                val root = dialog()?.root ?: return@until false
                fun hasPassword(node: AccessibilityNodeInfo): Boolean =
                    node.isPassword || (0 until node.childCount).any { node.getChild(it)?.let(::hasPassword) == true }
                hasPassword(root)
            }
            SystemClock.sleep(600)
            assertNull(session.preview())
        }
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
