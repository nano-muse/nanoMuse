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
import android.graphics.Region
import android.media.Image
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
    class WindowChanged : HandsCaptureFailure("The background window changed. Take a new screenshot before acting.")
    class WindowPending : HandsCaptureFailure("Android is changing the background app window.")
}

/** Android may briefly expose neither activity's accessibility root during a same-task change.
 * A known foreign owner anywhere in the list always wins over a missing root. */
internal enum class HandsWindowOwnership { Target, Pending, Foreign }

internal fun handsWindowOwnership(owners: List<CharSequence?>, pkg: String): HandsWindowOwnership {
    if (owners.any { !it.isNullOrEmpty() && it != pkg }) return HandsWindowOwnership.Foreign
    if (owners.isEmpty() || owners.any { it.isNullOrEmpty() }) return HandsWindowOwnership.Pending
    return HandsWindowOwnership.Target
}

/** Wait only for a new observation. Every read must recheck the display, lock and owner. */
internal fun <T> awaitHandsObservation(attempts: Int, pause: () -> Unit, read: () -> T): T {
    var remaining = attempts
    while (true) {
        try { return read() } catch (pending: HandsCaptureFailure.WindowPending) {
            if (--remaining <= 0) throw pending
            pause()
        }
    }
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
            if (next != window || retry is HandsCaptureFailure.WindowPending) {
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
    private data class WindowFrame(val id: Int, val touchable: Region) {
        val bounds = touchable.bounds
    }

    private val captureLock = ReentrantLock(true)
    private var lastCaptureAt = -1L
    private data class Observation(val frame: WindowFrame, val registered: Boolean)
    @Volatile private var observation: Observation? = null
    @Volatile private var closed = false

    private fun frameOf(window: AccessibilityWindowInfo) =
        WindowFrame(window.id, Region().also { window.getRegionInScreen(it) })

    private fun observedWindow(): AccessibilityWindowInfo {
        val window = targetWindows().first()
        val previous = observation
        if (previous == null || frameOf(window) != previous.frame) throw HandsCaptureFailure.WindowChanged()
        if (previous.registered && !previewable(window)) {
            observation = null
            throw ProtectedScreen()
        }
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

    private fun targetWindows(): List<AccessibilityWindowInfo> = try {
        check(!closed && id > Display.DEFAULT_DISPLAY && display.isValid && ShizukuManager.isReady()) {
            "The background screen is unavailable."
        }
        checkUnlocked(context)
        checkGeometry()
        val all = svc.windowsOnAllDisplays
        checkOtherScreens(all, pkg, id)
        val windows = all[id].orEmpty()
        val ownership = if (windows.any { it.displayId != id || it.type != AccessibilityWindowInfo.TYPE_APPLICATION }) {
            HandsWindowOwnership.Foreign
        } else {
            handsWindowOwnership(windows.map { it.root?.packageName }, pkg)
        }
        if (ownership != HandsWindowOwnership.Target) {
            observation = null
            if (ownership == HandsWindowOwnership.Pending) throw HandsCaptureFailure.WindowPending()
            error("The requested app no longer owns the background screen.")
        }
        windows.sortedByDescending { it.layer }.also { ordered ->
            val prior = observation
            if (prior != null && prior.frame != frameOf(ordered.first())) observation = null
        }
    } catch (failure: Exception) {
        observation = null
        throw failure
    }

    private fun nextWindow(attempts: Int = 17): WindowFrame = try {
        awaitHandsObservation(attempts, { Thread.sleep(75) }) {
            checkRunning()
            frameOf(targetWindows().first())
        }
    } catch (_: HandsCaptureFailure.WindowPending) {
        throw UnmappedWindow("Android did not identify the background window in time.")
    }

    fun roots(): List<AccessibilityNodeInfo> {
        val window = observedWindow()
        return listOf(checkNotNull(window.root?.takeIf { it.packageName == pkg && it.windowId == window.id }))
    }

    /** Recheck after inference. A new dialog in the same app needs a new observation. */
    fun stillObserved(): Boolean = try {
        observedWindow()
        true
    } catch (_: HandsCaptureFailure.WindowPending) {
        false
    } catch (_: HandsCaptureFailure.WindowChanged) {
        false
    }

    fun foregroundPackage(): String {
        targetWindows()
        return pkg
    }

    fun screenshot(): Bitmap {
        captureLock.lockInterruptibly()
        try {
            observation = null
            return captureHandsWindow(
                current = { nextWindow() },
                waitForInterval = { Thread.sleep(CAPTURE_INTERVAL_MS) },
            ) { target ->
                val bitmap = capture(target.id, 5_000)
                var output: Bitmap? = null
                try {
                    checkRunning()
                    if (target != frameOf(targetWindows().first())) throw HandsCaptureFailure.WindowChanged()
                    output = compose(bitmap, target, viewport.width, viewport.height)
                    observation = Observation(target,
                        bitmap.width != target.bounds.width() || bitmap.height != target.bounds.height())
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
                thumbnail = compose(bitmap, target, viewport.previewWidth, viewport.previewHeight)
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

    private fun safeToRegister(target: WindowFrame) {
        checkRunning()
        val current = targetWindows().first()
        if (frameOf(current) != target) throw HandsCaptureFailure.WindowChanged()
        if (!previewable(current)) throw ProtectedScreen()
    }

    private fun windowCrop(bitmap: Bitmap, target: WindowFrame): Rect? {
        val bounds = target.bounds
        val w = bounds.width()
        val h = bounds.height()
        val screen = Rect(0, 0, viewport.width, viewport.height)
        if (bitmap.width == w && bitmap.height == h && Rect.intersects(screen, bounds)) return null
        // If the target is clipped or its shape cannot be registered unambiguously, hand it back.
        fun failure() = UnmappedWindow("The window image cannot be mapped to safe touch coordinates.")
        if (!target.touchable.isRect || !screen.contains(bounds) || !HandsWindowRegistration.supported(w, h, bitmap.width, bitmap.height)) throw failure()
        safeToRegister(target)
        val evidence = frames.sample(bounds) ?: throw failure()
        val pixels = IntArray(bitmap.width * bitmap.height)
        bitmap.getPixels(pixels, 0, bitmap.width, 0, 0, bitmap.width, bitmap.height)
        val offset = HandsWindowRegistration.match(w, h, bitmap.width, bitmap.height, pixels, evidence) ?: throw failure()
        safeToRegister(target)
        return Rect(offset.x, offset.y, offset.x + w, offset.y + h)
    }

    private fun compose(bitmap: Bitmap, target: WindowFrame, width: Int, height: Int): Bitmap {
        val bounds = target.bounds
        val full = isFullFrame(bitmap, bounds)
        if (full && width == viewport.width && height == viewport.height) return bitmap
        val crop = windowCrop(bitmap, target)
        // Only the OS-authorized window bitmap is ever drawn. Clip translated frames at the
        // display edge and place the verified crop in the same coordinates used for touch.
        val output = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
        try {
            Canvas(output).apply {
                drawColor(Color.BLACK)
                scale(width.toFloat() / viewport.width, height.toFloat() / viewport.height)
                drawBitmap(bitmap, crop, bounds, Paint(Paint.FILTER_BITMAP_FLAG))
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

    private fun touchedWindow(): Region = Region().also { observedWindow().getRegionInScreen(it) }

    private fun inside(x: Int, y: Int, bounds: Region): Boolean =
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
        if (!bounds.isRect) {
            // A disconnected/nonrectangular region can contain both endpoints while leaving
            // another window in between. Require the complete gesture footprint to be inside.
            val footprint = Region(minOf(x1, x2), minOf(y1, y2), maxOf(x1, x2) + 1, maxOf(y1, y2) + 1)
            if (footprint.op(bounds, Region.Op.DIFFERENCE)) return false
        }
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

    @Volatile var canHandOff = false
        private set

    /** Only the operator thread enters here, after ending model and input work. */
    fun handOffToPhone(): Boolean {
        if (!canHandOff || closed) return false
        checkUnlocked(context)
        observation = null
        canHandOff = false
        return host.handOffToPhone()
    }

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
                session.nextWindow(attempts = 81)
                session.canHandOff = host.rememberTask(app.packageName)
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
        // One held image plus two acquisition slots allows acquireLatestImage to discard superseded frames.
        val reader: ImageReader = ImageReader.newInstance(viewport.width, viewport.height, PixelFormat.RGBA_8888, 3)
        private val thread = HandlerThread("Hands display output").apply { start() }
        private var latest: Image? = null
        private var closed = false

        init {
            reader.setOnImageAvailableListener({ synchronized(this) { if (!closed) refresh() } }, Handler(thread.looper))
        }

        private fun refresh() {
            val image = reader.acquireLatestImage() ?: return
            latest?.close()
            latest = image
        }

        // The display surface never supplies screenshot pixels. Read only a sparse grid inside
        // an independently authorized window to identify its offset in the window screenshot.
        @Synchronized fun sample(bounds: Rect): HandsWindowRegistration.Evidence? {
            if (closed) return null
            refresh()
            val image = latest ?: return null
            if (image.format != PixelFormat.RGBA_8888 || !image.cropRect.contains(bounds)) return null
            val plane = image.planes.singleOrNull() ?: return null
            val buf = plane.buffer
            val start = buf.position()
            val stride = plane.rowStride
            if (plane.pixelStride != 4 || stride < image.width * 4 ||
                start.toLong() + (bounds.bottom - 1L) * stride + bounds.right.toLong() * 4 > buf.limit()) return null
            return HandsWindowRegistration.sample(bounds.width(), bounds.height()) { x, y ->
                val i = start + (y + bounds.top) * stride + (x + bounds.left) * 4
                ((buf[i + 3].toInt() and 255) shl 24) or ((buf[i].toInt() and 255) shl 16) or
                    ((buf[i + 1].toInt() and 255) shl 8) or (buf[i + 2].toInt() and 255)
            }
        }

        @Synchronized override fun close() {
            closed = true
            reader.setOnImageAvailableListener(null, null)
            latest?.close()
            latest = null
            reader.close()
            thread.quitSafely()
        }
    }
}
