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
import android.graphics.PixelFormat
import android.graphics.Point
import android.graphics.Rect
import android.media.ImageReader
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.PowerManager
import android.os.SystemClock
import android.view.Display
import android.view.Surface
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityWindowInfo
import com.openminis.app.accessibility.MinisAccessibilityService
import com.openminis.app.offload.ShizukuManager
import java.util.concurrent.CompletableFuture
import java.util.concurrent.ExecutionException
import java.util.concurrent.ForkJoinPool
import java.util.concurrent.TimeUnit

/** One run owns one non-mirroring display and a fresh launcher task. */
internal class BackgroundHandsDisplay private constructor(
    private val context: Context,
    private val svc: MinisAccessibilityService,
    private val pkg: String,
    private val host: HandsDisplayHost.Handle,
    private val frames: Frames,
) : AutoCloseable {
    class ProtectedScreen : IllegalStateException("The background app protects this window.")

    private val display = host.display
    private val id = display.displayId
    private var observedWindow: Int? = null
    private var closed = false

    @Suppress("DEPRECATION") // getRealSize reads the logical dimensions of this specific display.
    private fun checkGeometry() {
        val size = Point()
        display.getRealSize(size)
        check(display.rotation == Surface.ROTATION_0 && size.x == WIDTH && size.y == HEIGHT) {
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
        val window = targetWindows().first()
        check(observedWindow == null || observedWindow == window.id) { "The background app window changed." }
        return listOf(checkNotNull(window.root?.takeIf { it.packageName == pkg && it.windowId == window.id }))
    }

    fun foregroundPackage(): String {
        targetWindows()
        return pkg
    }

    fun screenshot(): Bitmap {
        val window = targetWindows().first()
        val bounds = Rect().also { window.getBoundsInScreen(it) }
        val frame = CompletableFuture<Bitmap>()
        // Capture the verified window itself. Display surfaces can still hold a previous
        // frame after Android changes apps or covers one with a protected window.
        svc.takeScreenshotOfWindow(window.id, ForkJoinPool.commonPool(), object : AccessibilityService.TakeScreenshotCallback {
            override fun onSuccess(result: AccessibilityService.ScreenshotResult) {
                try {
                    result.hardwareBuffer.use { buffer ->
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
                val error = if (errorCode == AccessibilityService.ERROR_TAKE_SCREENSHOT_SECURE_WINDOW) ProtectedScreen()
                    else IllegalStateException("Android could not capture the background app window (code $errorCode).")
                frame.completeExceptionally(error)
            }
        })
        val bitmap = try {
            frame.get(5, TimeUnit.SECONDS)
        } catch (failure: ExecutionException) {
            throw failure.cause ?: failure
        } catch (failure: Exception) {
            // Dispose of a callback that wins the race with a timeout.
            if (!frame.cancel(false)) frame.getNow(null)?.recycle()
            throw failure
        }
        try {
            val current = targetWindows().first()
            check(current.id == window.id && Rect().also { current.getBoundsInScreen(it) } == bounds) {
                "The background app window changed during capture."
            }
            observedWindow = current.id
            if (bitmap.width == WIDTH && bitmap.height == HEIGHT && bounds.left == 0 && bounds.top == 0) return bitmap
            check(bitmap.width == bounds.width() && bitmap.height == bounds.height() &&
                Rect(0, 0, WIDTH, HEIGHT).contains(bounds)) { "The app window does not match the background screen." }
            val screen = Bitmap.createBitmap(WIDTH, HEIGHT, Bitmap.Config.ARGB_8888)
            Canvas(screen).apply {
                drawColor(Color.BLACK)
                drawBitmap(bitmap, null, bounds, null)
            }
            bitmap.recycle()
            return screen
        } catch (failure: Throwable) {
            bitmap.recycle()
            throw failure
        }
    }

    private fun touchedWindow(): Rect {
        val top = targetWindows().first()
        check(top.id == observedWindow) { "The background app window changed. Take a new screenshot before acting." }
        return Rect().also { top.getBoundsInScreen(it) }
    }

    private fun inside(x: Int, y: Int, bounds: Rect): Boolean =
        x in 0 until WIDTH && y in 0 until HEIGHT && bounds.contains(x, y)

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
        private const val WIDTH = 720
        private const val HEIGHT = 1280
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
            val frames = Frames()
            val host = try {
                HandsDisplayHost.open(context, frames.reader.surface, WIDTH, HEIGHT, 280)
            } catch (failure: Throwable) {
                frames.close()
                throw failure
            }
            val session = BackgroundHandsDisplay(context, svc, app.packageName, host, frames)
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
    private class Frames : AutoCloseable {
        val reader: ImageReader = ImageReader.newInstance(WIDTH, HEIGHT, PixelFormat.RGBA_8888, 2)
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
