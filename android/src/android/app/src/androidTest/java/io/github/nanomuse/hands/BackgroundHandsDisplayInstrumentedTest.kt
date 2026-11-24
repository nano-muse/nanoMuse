package io.github.nanomuse.hands

import android.app.UiAutomation
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
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/**
 * Run on an unlocked test device with a background screen connection authorized for nanoMuse and its accessibility
 * service enabled, starting from the launcher. The fixture lives in the instrumentation APK.
 *
 * ./gradlew :app:connectedDebugAndroidTest -Pnm.abi=x86_64 \
 *   -Pandroid.testInstrumentationRunnerArguments.class=io.github.nanomuse.hands.BackgroundHandsDisplayInstrumentedTest \
 *   -Pandroid.testInstrumentationRunnerArguments.handsDisplayTest=true
 */
@RunWith(AndroidJUnit4::class)
class BackgroundHandsDisplayInstrumentedTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val automation get() = instrumentation.getUiAutomation(UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES)
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
        until("Authorize the background screen connection first.") { HandsDisplayHost.isReady() }
        val home = automation.executeShellCommand(
            "am start -W --display 0 -a android.intent.action.MAIN -c android.intent.category.HOME"
        )
        ParcelFileDescriptor.AutoCloseInputStream(home).use { it.readBytes() }
        // am -W may finish while a closing fixture, splash, or launcher transition still has
        // an accessibility window without a root. Require two stable, identifiable snapshots.
        var prior = emptyList<Pair<Int, String>>()
        until("The test fixture left a visible or unidentifiable window after returning Home.") {
            val all = service.windowsOnAllDisplays
            val mainHasApp = all[Display.DEFAULT_DISPLAY].orEmpty().any { it.type == AccessibilityWindowInfo.TYPE_APPLICATION }
            val visible = (0 until all.size()).flatMap { index -> all.valueAt(index) }
                .filter { it.type == AccessibilityWindowInfo.TYPE_APPLICATION }
                .map { it.id to it.root?.packageName?.toString().orEmpty() }
            val ready = mainHasApp && visible.isNotEmpty() && visible == prior &&
                visible.all { (_, owner) -> owner.isNotEmpty() && owner != pkg }
            prior = visible
            ready
        }
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

    @Test fun applicationCodeCannotRegisterAnAlternateDisplayService() {
        val uri = android.net.Uri.parse("content://${context.packageName}.hands-bridge")
        val extras = android.os.Bundle().apply {
            putString("nonce", "a".repeat(43))
            putBinder("display", android.os.Binder())
        }
        assertNull(context.contentResolver.call(uri, HandsDisplayBridge.METHOD, null, extras))
    }

    @Test fun capturesAndTapsOnlyTheNewDisplayAndRemovesIt() {
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

    /** open() may see Android's starting window before the actual fixture UI has rendered. */
    private fun observeFixture(session: BackgroundHandsDisplay, label: String) {
        var previous: Pair<Int, Rect>? = null
        var lastMovement = SystemClock.uptimeMillis()
        until("Could not observe the fixture control '$label' on a stable secondary window.") {
            val all = service.windowsOnAllDisplays
            val top = (0 until all.size()).asSequence().filter { all.keyAt(it) != Display.DEFAULT_DISPLAY }
                .mapNotNull { all.valueAt(it).maxByOrNull { win -> win.layer } }
                .firstOrNull { win -> win.root?.let {
                    it.packageName == pkg && it.findAccessibilityNodeInfosByText(label).isNotEmpty()
                } == true }
            val geometry = top?.let { it.id to Rect().also { bounds -> it.getBoundsInScreen(bounds) } }
            if (geometry != previous) {
                previous = geometry
                lastMovement = SystemClock.uptimeMillis()
            }
            if (geometry == null || SystemClock.uptimeMillis() - lastMovement < 300) return@until false
            try {
                session.screenshot().recycle()
                session.roots().single().findAccessibilityNodeInfosByText(label).isNotEmpty()
            } catch (_: HandsCaptureFailure.WindowChanged) {
                false
            } catch (_: HandsCaptureFailure.WindowPending) {
                false
            }
        }
    }

    @Test fun movingTheSameWindowNeedsANewModelScreenshotAndPasswordFieldsHideThePreview() {
        BackgroundHandsDisplay.open(context, service, fixture).use { session ->
            observeFixture(session, "Moving window")
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
            observeFixture(session, "Move dialog")
            val original = checkNotNull(dialog())
            val oldBounds = Rect().also { original.getBoundsInScreen(it) }
            val move = session.roots().single().findAccessibilityNodeInfosByText("Move dialog").single()
            assertTrue(move.performAction(AccessibilityNodeInfo.ACTION_CLICK))
            until("Android did not move the fixture window.") {
                dialog()?.let { it.id == original.id && Rect().also { r -> it.getBoundsInScreen(r) } != oldBounds } == true
            }
            assertFalse("An action planned for the old bounds must be discarded.", session.stillObserved())
            // Even a successful fresh preview cannot turn old model coordinates into safe input.
            until("The moved window could not be previewed.") { session.preview()?.let { it.recycle(); true } == true }
            assertThrows(IllegalStateException::class.java) { session.tap(oldBounds.centerX(), oldBounds.centerY(), 60) }
            observeFixture(session, "Change form")
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

    @Test fun raisedDialogUsesWindowPixelsAndClickCoordinatesAfterMoving() {
        BackgroundHandsDisplay.open(context, service, fixture).use { session ->
            observeFixture(session, "Raised window")
            assertTrue(session.roots().single().findAccessibilityNodeInfosByText("Raised window").single()
                .performAction(AccessibilityNodeInfo.ACTION_CLICK))
            observeFixture(session, "Move dialog")
            fun control(label: String) = Rect().also {
                session.roots().single().findAccessibilityNodeInfosByText(label).single().getBoundsInScreen(it)
            }
            val move = control("Move dialog")
            val form = control("Change form")
            val image = session.screenshot()
            val imageWidth = image.width
            val imageHeight = image.height
            try {
                assertEquals(Color.BLACK, image.getPixel(2, 2))
                assertEquals(Color.RED, image.getPixel(move.left + 12, move.centerY()))
                assertEquals(Color.CYAN, image.getPixel(form.right - 12, form.centerY()))
            } finally { image.recycle() }
            until("The raised dialog was not correctly mapped in preview.") {
                val thumb = session.preview() ?: return@until false
                try { thumb.getPixel((form.right - 12) * thumb.width / imageWidth,
                    form.centerY() * thumb.height / imageHeight) == Color.CYAN } finally { thumb.recycle() }
            }
            assertTrue(session.tap(move.centerX(), move.centerY(), 60))
            until("Tapping the mapped control did not move the window.") { !session.stillObserved() }
            observeFixture(session, "Change form")
            val moved = control("Change form")
            assertTrue(moved.left > form.left)
            assertTrue(session.tap(moved.right - 12, moved.centerY(), 60))
            until("The edge tap did not show the protected field.") {
                val all = service.windowsOnAllDisplays
                (0 until all.size()).asSequence().filter { all.keyAt(it) != Display.DEFAULT_DISPLAY }
                    .flatMap { all.valueAt(it).asSequence() }.any { win ->
                        val root = win.root?.takeIf { it.packageName == pkg } ?: return@any false
                        fun secret(node: AccessibilityNodeInfo): Boolean = node.isPassword ||
                            (0 until node.childCount).any { node.getChild(it)?.let(::secret) == true }
                        secret(root)
                    }
            }
            assertThrows(BackgroundHandsDisplay.ProtectedScreen::class.java) { session.tap(moved.centerX(), moved.centerY(), 60) }
            assertNull(session.preview())
            assertThrows(BackgroundHandsDisplay.ProtectedScreen::class.java) { session.screenshot() }
            assertThrows(IllegalStateException::class.java) { session.back() }
        }
    }

    @Test fun systemAlertWithOrdinaryTextAndButtonsCanBeOperated() {
        BackgroundHandsDisplay.open(context, service, fixture).use { session ->
            observeFixture(session, "Standard alert")
            assertTrue(session.roots().single().findAccessibilityNodeInfosByText("Standard alert").single()
                .performAction(AccessibilityNodeInfo.ACTION_CLICK))
            observeFixture(session, "Review draft")
            val read = session.roots().single().findAccessibilityNodeInfosByText("Read draft").single()
            val button = Rect().also { read.getBoundsInScreen(it) }
            assertTrue(session.tap(button.centerX(), button.centerY(), 60))
            observeFixture(session, "Draft opened")
        }
    }

    @Test fun ambiguousFlatRaisedWindowBlocksModelPreviewAndInput() {
        BackgroundHandsDisplay.open(context, service, fixture).use { session ->
            observeFixture(session, "Flat window")
            assertTrue(session.roots().single().findAccessibilityNodeInfosByText("Flat window").single()
                .performAction(AccessibilityNodeInfo.ACTION_CLICK))
            assertThrows(BackgroundHandsDisplay.UnmappedWindow::class.java) { observeFixture(session, "Flat surface") }
            SystemClock.sleep(600)
            assertNull(session.preview())
            assertThrows(IllegalStateException::class.java) { session.back() }
        }
    }

    @Test fun handoffRefusesASecondTaskFromTheSameApp() {
        val displays = context.getSystemService(DisplayManager::class.java)
        val before = displays.displays.map { it.displayId }.toSet()
        BackgroundHandsDisplay.open(context, service, fixture).use { session ->
            observeFixture(session, "Moving window")
            val original = session.roots().single().findAccessibilityNodeInfosByText("Fixture task").single()
                .contentDescription.toString()
            val owned = (displays.displays.map { it.displayId }.toSet() - before).single()
            val launch = "am start -W --display $owned -f 0x18000000 -n $pkg/io.github.nanomuse.hands.HandsDisplayFixture"
            ParcelFileDescriptor.AutoCloseInputStream(automation.executeShellCommand(launch)).bufferedReader().use { it.readText() }
            until("The second task did not become visible.") {
                service.windowsOnAllDisplays[owned].orEmpty().any { window ->
                    window.root?.findAccessibilityNodeInfosByText("Fixture task").orEmpty()
                        .any { node -> node.contentDescription?.toString()?.let { it != original } == true }
                }
            }
            assertFalse(session.handOffToPhone())
            assertFalse(pkg in primaryApps())
        }
        until("The secondary display was not removed.") { before == displays.displays.map { it.displayId }.toSet() }
    }

    @Test fun handoffMovesTheOriginalTaskAndReleasesTheSecondaryDisplay() {
        val displays = context.getSystemService(DisplayManager::class.java)
        val before = displays.displays.map { it.displayId }.toSet()
        BackgroundHandsDisplay.open(context, service, fixture).use { session ->
            observeFixture(session, "Moving window")
            val marker = session.roots().single().findAccessibilityNodeInfosByText("Fixture task").single()
                .contentDescription.toString()
            assertTrue(marker.matches(Regex("Fixture task [0-9]+")))
            assertFalse(pkg in primaryApps())
            assertTrue("Expected the isolated task to be eligible for handoff", session.canHandOff)
            assertTrue(session.handOffToPhone())
            assertFalse(session.handOffToPhone())
            try {
                until("The original task did not arrive on the main screen.") {
                    service.windowsOnAllDisplays[Display.DEFAULT_DISPLAY].orEmpty().any {
                        it.root?.let { root -> root.packageName == pkg &&
                            root.findAccessibilityNodeInfosByText(marker).any { node -> node.contentDescription == marker } } == true
                    }
                }
                assertThrows(IllegalStateException::class.java) { session.tap(10, 10, 60) }
            } finally {
                if (pkg in primaryApps()) {
                    automation.executeShellCommand("input -d 0 keyevent KEYCODE_BACK").close()
                    until("The handed-off fixture did not close.") { pkg !in primaryApps() }
                }
            }
        }
        until("The secondary display survived its handoff.") { before == displays.displays.map { it.displayId }.toSet() }
    }

    @Test fun enteringAnotherActivityRequiresAndAllowsAFreshObservation() {
        BackgroundHandsDisplay.open(context, service, fixture).use { session ->
            observeFixture(session, "Next page")
            val next = session.roots().single().findAccessibilityNodeInfosByText("Next page").single()
            val button = Rect().also { next.getBoundsInScreen(it) }
            assertTrue(session.tap(button.centerX(), button.centerY(), 60))
            until("The old activity remained authorized.") { !session.stillObserved() }
            assertThrows(IllegalStateException::class.java) { session.tap(button.centerX(), button.centerY(), 60) }
            session.screenshot().recycle()
            observeFixture(session, "Second activity")
            val detail = session.screenshot()
            try { assertEquals(Color.MAGENTA, detail.getPixel(detail.width / 2, detail.height / 2)) }
            finally { detail.recycle() }
        }
    }

    @Test fun refusesFixtureAlreadyVisibleOnThePrimaryDisplay() {
        val before = context.getSystemService(DisplayManager::class.java).displays.map { it.displayId }.toSet()
        val command = "am start -W --display 0 -n $pkg/io.github.nanomuse.hands.HandsDisplayFixture"
        val pfd = automation.executeShellCommand(command)
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
