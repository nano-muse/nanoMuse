package io.github.nanomuse.hands

import android.accessibilityservice.AccessibilityService
import android.app.KeyguardManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.ActivityInfo
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.PixelFormat
import android.graphics.Point
import android.graphics.Rect
import android.media.ImageReader
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.PowerManager
import android.os.SystemClock
import android.text.InputType
import android.util.DisplayMetrics
import android.view.Display
import android.view.Surface
import android.view.WindowManager
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityWindowInfo
import com.openminis.app.accessibility.MinisAccessibilityService
import com.openminis.app.offload.ShizukuManager
import io.github.nanomuse.guard.TapWords
import java.util.concurrent.CompletableFuture
import java.util.concurrent.ExecutionException
import java.util.concurrent.ForkJoinPool
import java.util.concurrent.TimeUnit
import java.util.concurrent.locks.ReentrantLock
import kotlin.math.roundToInt

/** Pixel dimensions and density are scaled together to preserve the Android app's dp layout. */
internal data class HandsViewport(val width: Int, val height: Int, val dpi: Int) {
    companion object {
        fun fromDisplay(width: Int, height: Int, dpi: Int): HandsViewport {
            require(width > 0 && height > 0 && dpi > 0) { "The primary display geometry is unavailable." }
            val scale = minOf(1.0, 720.0 / minOf(width, height), 1600.0 / maxOf(width, height))
            return HandsViewport((width * scale).roundToInt().coerceAtLeast(1),
                (height * scale).roundToInt().coerceAtLeast(1), (dpi * scale).roundToInt().coerceIn(72, 640))
        }
    }

    private val previewScale get() = minOf(1.0, 320.0 / width, 640.0 / height)
    val previewWidth get() = (width * previewScale).roundToInt().coerceAtLeast(1)
    val previewHeight get() = (height * previewScale).roundToInt().coerceAtLeast(1)
}

/** Limited to recoverable failures reported while requesting a new image, never while sending input. */
internal sealed class HandsCaptureFailure(message: String) : IllegalStateException(message) {
    class RateLimited : HandsCaptureFailure("Android rate-limited window capture.")
    class WindowChanged : HandsCaptureFailure("The background window changed during capture.")
}

/** A starting window can be replaced by an actual activity. Re-sample its successor only after
 * identifying it again. One window transition and one independent platform throttle are tolerated. */
internal fun <W, T> captureHandsWindow(current: () -> W, waitForInterval: () -> Unit, capture: (W) -> T): T {
    var window = current()
    var changed = false
    var waited = false
    while (true) {
        try {
            return capture(window)
        } catch (retry: HandsCaptureFailure) {
            if (retry is HandsCaptureFailure.RateLimited) {
                if (waited) throw retry
                waited = true
                waitForInterval()
            }
            val next = current()
            if (next != window) {
                if (changed) throw HandsCaptureFailure.WindowChanged()
                changed = true
            } else if (retry is HandsCaptureFailure.WindowChanged) {
                // Android rejected this window ID, but we cannot confirm a replacement.
                throw retry
            }
            window = next
        }
    }
}

/** One run owns one non-mirroring display and a fresh launcher task. */
internal class BackgroundHandsDisplay private constructor(
    private val context: Context,
    private val svc: MinisAccessibilityService,
    private val pkg: String,
    private val host: HandsDisplayHost.Handle,
    private val frames: Frames,
    private val viewport: HandsViewport,
    private val checkRunning: () -> Unit,
) : AutoCloseable {
    sealed class NeedsUser(message: String) : IllegalStateException(message)
    class ProtectedScreen : NeedsUser("The background app protects this window.")
    class UnmappedWindow(message: String) : NeedsUser(message)

    private val display = host.display
    private val id = display.displayId
    private data class WindowFrame(val id: Int, val bounds: Rect)

    private val captureLock = ReentrantLock(true)
    private var lastCaptureAt = -1L
    @Volatile private var observation: WindowFrame? = null
    @Volatile private var closed = false

    private fun frameOf(window: AccessibilityWindowInfo) =
        WindowFrame(window.id, Rect().also { window.getBoundsInScreen(it) })

    private fun observedWindow(): AccessibilityWindowInfo {
        val window = targetWindows().first()
        check(frameOf(window) == observation) { "The background window changed. Take a new screenshot before acting." }
        return window
    }

    @Suppress("DEPRECATION") // getRealSize reads the logical dimensions of this specific display.
    private fun checkGeometry() {
        val size = Point()
        display.getRealSize(size)
        check(display.rotation == Surface.ROTATION_0 && size.x == viewport.width && size.y == viewport.height) {
            "The background app changed the screen orientation or size."
        }
    }

    private fun targetWindows(): List<AccessibilityWindowInfo> {
        check(!closed && id > Display.DEFAULT_DISPLAY && display.isValid && ShizukuManager.isReady()) {
            "The background screen is unavailable."
        }
        checkUnlocked(context)
        checkGeometry()
        val all = svc.windowsOnAllDisplays
        checkOtherScreens(all, pkg, id)
        val windows = all[id].orEmpty()
        check(windows.isNotEmpty() && windows.all {
            it.displayId == id && it.type == AccessibilityWindowInfo.TYPE_APPLICATION && it.root?.packageName == pkg
        }) { "The requested app no longer owns the background screen." }
        return windows.sortedByDescending { it.layer }
    }

    fun roots(): List<AccessibilityNodeInfo> {
        val window = observedWindow()
        return listOf(checkNotNull(window.root?.takeIf { it.packageName == pkg && it.windowId == window.id }))
    }

    /** Recheck after inference. A new dialog in the same app needs a new observation. */
    fun stillObserved() = frameOf(targetWindows().first()) == observation

    fun foregroundPackage(): String {
        targetWindows()
        return pkg
    }

    fun screenshot(): Bitmap {
        captureLock.lockInterruptibly()
        try {
            observation = null
            return captureHandsWindow(
                current = {
                    checkRunning()
                    frameOf(targetWindows().first())
                },
                waitForInterval = { Thread.sleep(CAPTURE_INTERVAL_MS) },
            ) { target ->
                val bitmap = capture(target.id, 5_000)
                var output: Bitmap? = null
                try {
                    checkRunning()
                    if (target != frameOf(targetWindows().first())) throw HandsCaptureFailure.WindowChanged()
                    output = compose(bitmap, target.bounds, viewport.width, viewport.height)
                    observation = target
                    output
                } finally {
                    if (output !== bitmap) bitmap.recycle()
                }
            }
        } finally {
            captureLock.unlock()
        }
    }

    /** Best-effort thumbnail for the person watching. It never grants authority to act. */
    fun preview(): Bitmap? {
        if (closed || captureLock.hasQueuedThreads() || !captureLock.tryLock()) return null
        try {
            if (SystemClock.elapsedRealtime() - lastCaptureAt < CAPTURE_INTERVAL_MS) return null
            checkRunning()
            val window = targetWindows().first()
            val target = frameOf(window)
            if (!previewable(window)) return null
            val bitmap = capture(target.id, 400)
            var thumbnail: Bitmap? = null
            try {
                checkRunning()
                val current = targetWindows().first()
                if (frameOf(current) != target || !previewable(current)) return null
                thumbnail = compose(bitmap, target.bounds, viewport.previewWidth, viewport.previewHeight)
                return thumbnail
            } finally {
                if (thumbnail !== bitmap) bitmap.recycle()
            }
        } catch (_: InterruptedException) {
            Thread.currentThread().interrupt()
            return null
        } catch (_: Exception) {
            // Losing focus, a locked/secure screen or a delayed capture clears the preview.
            return null
        } finally {
            captureLock.unlock()
        }
    }

    private fun previewable(window: AccessibilityWindowInfo): Boolean {
        val nodes = ArrayDeque<AccessibilityNodeInfo>()
        nodes.add(window.root ?: return false)
        var visited = 0
        while (nodes.isNotEmpty()) {
            val node = nodes.removeLast()
            if (++visited > 128 || node.windowId != window.id || node.packageName != pkg) return false
            if (node.isPassword || isPasswordInput(node.inputType)) return false
            if (listOf(node.hintText, node.contentDescription).any {
                    it != null && (it.length > 512 || TapWords.looksSecret(it.toString()))
                }) return false
            val label = node.text
            if (!node.isEditable && label != null && label.length <= 160 && TapWords.looksSecret(label.toString())) return false
            if (node.childCount > 128 - visited - nodes.size) return false
            for (index in 0 until node.childCount) nodes.add(node.getChild(index) ?: return false)
        }
        return true
    }

    private fun isFullFrame(bitmap: Bitmap, bounds: Rect) =
        bitmap.width == viewport.width && bitmap.height == viewport.height && bounds == Rect(0, 0, viewport.width, viewport.height)

    private fun compose(bitmap: Bitmap, bounds: Rect, width: Int, height: Int): Bitmap {
        val full = isFullFrame(bitmap, bounds)
        if (full && width == viewport.width && height == viewport.height) return bitmap
        val exactWindow = bitmap.width == bounds.width() && bitmap.height == bounds.height()
        if (!full && !(exactWindow && Rect.intersects(Rect(0, 0, viewport.width, viewport.height), bounds))) {
            throw UnmappedWindow("The window image cannot be mapped to safe touch coordinates. " +
                "Image ${bitmap.width}x${bitmap.height}, bounds ${bounds.toShortString()}, display ${viewport.width}x${viewport.height}.")
        }
        // During an activity transition the verified window can be translated partly outside
        // the display. Its pixels still map one-to-one to its bounds; Canvas clips the excess.
        val output = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
        try {
            Canvas(output).apply {
                drawColor(Color.BLACK)
                scale(width.toFloat() / viewport.width, height.toFloat() / viewport.height)
                drawBitmap(bitmap, null, if (full) Rect(0, 0, viewport.width, viewport.height) else bounds, Paint(Paint.FILTER_BITMAP_FLAG))
            }
            return output
        } catch (failure: Throwable) {
            output.recycle()
            throw failure
        }
    }

    private fun capture(windowId: Int, timeoutMs: Long): Bitmap {
        lastCaptureAt = SystemClock.elapsedRealtime()
        val frame = CompletableFuture<Bitmap>()
        // Capture the verified window itself. Display surfaces can still hold a previous
        // frame after Android changes apps or covers one with a protected window.
        svc.takeScreenshotOfWindow(windowId, ForkJoinPool.commonPool(), object : AccessibilityService.TakeScreenshotCallback {
            override fun onSuccess(result: AccessibilityService.ScreenshotResult) {
                try {
                    result.hardwareBuffer.use { buffer ->
                        if (frame.isDone) return
                        val hardware = checkNotNull(Bitmap.wrapHardwareBuffer(buffer, result.colorSpace))
                        val copy = try { checkNotNull(hardware.copy(Bitmap.Config.ARGB_8888, false)) }
                            finally { hardware.recycle() }
                        if (!frame.complete(copy)) copy.recycle()
                    }
                } catch (failure: Exception) {
                    frame.completeExceptionally(failure)
                }
            }
            override fun onFailure(errorCode: Int) {
                val error = when (errorCode) {
                    AccessibilityService.ERROR_TAKE_SCREENSHOT_SECURE_WINDOW -> ProtectedScreen()
                    AccessibilityService.ERROR_TAKE_SCREENSHOT_INTERVAL_TIME_SHORT -> HandsCaptureFailure.RateLimited()
                    AccessibilityService.ERROR_TAKE_SCREENSHOT_INVALID_WINDOW -> HandsCaptureFailure.WindowChanged()
                    else -> IllegalStateException("Android could not capture the background app window (code $errorCode).")
                }
                frame.completeExceptionally(error)
            }
        })
        return try {
            frame.get(timeoutMs, TimeUnit.MILLISECONDS)
        } catch (failure: ExecutionException) {
            throw failure.cause ?: failure
        } catch (failure: Exception) {
            // Dispose of a callback that wins the race with a timeout.
            if (!frame.cancel(false)) frame.whenComplete { result, _ -> result?.recycle() }
            throw failure
        }
    }

    private fun touchedWindow(): Rect = Rect().also { observedWindow().getBoundsInScreen(it) }

    private fun inside(x: Int, y: Int, bounds: Rect): Boolean =
        x in 0 until viewport.width && y in 0 until viewport.height && bounds.contains(x, y)

    fun tap(x: Int, y: Int, durationMs: Long): Boolean {
        if (!inside(x, y, touchedWindow())) return false
        return if (durationMs > 150) {
            touchSwipe(x, y, x, y, durationMs)
        } else {
            input("touchscreen", "tap", x.toString(), y.toString())
        }
    }

    fun swipe(x1: Int, y1: Int, x2: Int, y2: Int, durationMs: Long): Boolean {
        val bounds = touchedWindow()
        if (!inside(x1, y1, bounds) || !inside(x2, y2, bounds)) return false
        return touchSwipe(x1, y1, x2, y2, durationMs)
    }

    private fun touchSwipe(x1: Int, y1: Int, x2: Int, y2: Int, durationMs: Long) =
        input("touchscreen", "swipe", x1.toString(), y1.toString(), x2.toString(), y2.toString(),
            durationMs.coerceIn(1, 5_000).toString())

    fun back(): Boolean {
        touchedWindow()
        return input("keyboard", "keyevent", "KEYCODE_BACK")
    }

    private fun input(source: String, vararg args: String): Boolean =
        command("/system/bin/input", source, "-d", id.toString(), *args)

    override fun close() {
        if (closed) return
        closed = true
        try { host.close() } finally { frames.close() }
    }

    companion object {
        private const val CAPTURE_INTERVAL_MS = 550L
        internal fun isPasswordInput(inputType: Int): Boolean {
            val kind = inputType and InputType.TYPE_MASK_CLASS
            val variation = inputType and InputType.TYPE_MASK_VARIATION
            return when (kind) {
                InputType.TYPE_CLASS_NUMBER -> variation == InputType.TYPE_NUMBER_VARIATION_PASSWORD
                InputType.TYPE_CLASS_TEXT -> variation == InputType.TYPE_TEXT_VARIATION_PASSWORD ||
                    variation == InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD || variation == InputType.TYPE_TEXT_VARIATION_WEB_PASSWORD
                else -> false
            }
        }

        private fun checkUnlocked(context: Context) {
            check(!context.getSystemService(KeyguardManager::class.java).isDeviceLocked &&
                context.getSystemService(PowerManager::class.java).isInteractive) {
                "Unlock the phone to use the background screen."
            }
        }

        private fun checkOtherScreens(
            windows: android.util.SparseArray<List<AccessibilityWindowInfo>>, pkg: String, id: Int,
        ) {
            val primaryApps = windows[Display.DEFAULT_DISPLAY].orEmpty().filter {
                it.type == AccessibilityWindowInfo.TYPE_APPLICATION
            }
            check(primaryApps.isNotEmpty()) { "The current foreground app could not be identified." }
            for (i in 0 until windows.size()) {
                if (windows.keyAt(i) == id) continue
                for (window in windows.valueAt(i)) {
                    if (window.type != AccessibilityWindowInfo.TYPE_APPLICATION) continue
                    val owner = window.root?.packageName
                    check(owner != null && owner != pkg) {
                        "The app is already visible on another screen or its window could not be identified."
                    }
                }
            }
        }

        private fun command(vararg argv: String): Boolean {
            val result = ShizukuManager.runProcess(arrayOf(*argv), timeoutMs = 8_000)
            return result.exitCode == 0 && listOf(result.stderr, result.stdout).none {
                it.contains("Error:", ignoreCase = true) || it.contains("Exception")
            }
        }

        private fun launcher(context: Context, pkg: String): ComponentName {
            val pm = context.packageManager
            val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER).setPackage(pkg)
            val info = checkNotNull(pm.resolveActivity(intent, 0)?.activityInfo) { "No launcher activity was found." }
            check(info.exported && info.packageName == pkg && pkg != context.packageName)
            val activity = info.targetActivity?.let { pm.getActivityInfo(ComponentName(pkg, it), 0) } ?: info
            check(activity.launchMode in ActivityInfo.LAUNCH_MULTIPLE..ActivityInfo.LAUNCH_SINGLE_TOP &&
                activity.flags and ActivityInfo.FLAG_ALLOW_TASK_REPARENTING == 0) {
                "This app requires a shared task and cannot be opened safely on the background screen."
            }
            return ComponentName(pkg, info.name)
        }

        @JvmOverloads
        fun open(
            context: Context,
            svc: MinisAccessibilityService,
            app: HandsApps.App,
            checkRunning: () -> Unit = {},
        ): BackgroundHandsDisplay {
            check(Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE &&
                context.packageManager.hasSystemFeature(PackageManager.FEATURE_ACTIVITIES_ON_SECONDARY_DISPLAYS) &&
                ShizukuManager.isReady()) { "Background screens are unavailable on this device." }
            checkUnlocked(context)
            val component = launcher(context, app.packageName)
            checkOtherScreens(svc.windowsOnAllDisplays, app.packageName, Display.INVALID_DISPLAY)
            val primary = checkNotNull(context.getSystemService(android.hardware.display.DisplayManager::class.java)
                .getDisplay(Display.DEFAULT_DISPLAY)) { "The phone display is unavailable." }
            val windowContext = context.createWindowContext(primary, WindowManager.LayoutParams.TYPE_APPLICATION, null)
            val metrics = windowContext.getSystemService(WindowManager::class.java).maximumWindowMetrics
            val viewport = HandsViewport.fromDisplay(metrics.bounds.width(), metrics.bounds.height(),
                (metrics.density * DisplayMetrics.DENSITY_DEFAULT).roundToInt())
            val frames = Frames(viewport)
            val host = try {
                HandsDisplayHost.open(context, frames.reader.surface, viewport.width, viewport.height, viewport.dpi)
            } catch (failure: Throwable) {
                frames.close()
                throw failure
            }
            val session = BackgroundHandsDisplay(context, svc, app.packageName, host, frames, viewport, checkRunning)
            try {
                check(session.id > Display.DEFAULT_DISPLAY && host.display.isValid)
                checkOtherScreens(svc.windowsOnAllDisplays, app.packageName, session.id)
                checkUnlocked(context)
                checkRunning()
                val flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_MULTIPLE_TASK or
                    Intent.FLAG_ACTIVITY_EXCLUDE_FROM_RECENTS
                check(command("/system/bin/am", "start", "--user", host.userId.toString(), "--display", session.id.toString(),
                    "-f", flags.toString(), "-a", Intent.ACTION_MAIN, "-c", Intent.CATEGORY_LAUNCHER,
                    "-n", component.flattenToString())) { "Android refused to open the app on the background screen." }
                val deadline = SystemClock.elapsedRealtime() + 6_000
                while (svc.windowsOnAllDisplays[session.id].orEmpty().none { it.root?.packageName == app.packageName } &&
                    SystemClock.elapsedRealtime() < deadline) {
                    checkRunning()
                    SystemClock.sleep(100)
                }
                session.targetWindows()
                return session
            } catch (failure: Throwable) {
                session.close()
                throw failure
            }
        }
    }

    // A live output surface keeps Android composing the display. Images sent to the
    // model come exclusively from takeScreenshotOfWindow above.
    private class Frames(viewport: HandsViewport) : AutoCloseable {
        val reader: ImageReader = ImageReader.newInstance(viewport.width, viewport.height, PixelFormat.RGBA_8888, 2)
        private val thread = HandlerThread("Hands display output").apply { start() }
        private var closed = false

        init {
            reader.setOnImageAvailableListener({
                synchronized(this) { if (!closed) reader.acquireLatestImage()?.close() }
            }, Handler(thread.looper))
        }

        @Synchronized override fun close() {
            closed = true
            reader.setOnImageAvailableListener(null, null)
            reader.close()
            thread.quitSafely()
        }
    }
}
