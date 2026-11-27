package io.github.nanomuse.hands

import android.content.ComponentName
import android.content.Context
import android.content.ServiceConnection
import android.hardware.display.DisplayManager
import android.os.Binder
import android.os.Build
import android.os.IBinder
import android.os.Looper
import android.view.Display
import android.view.Surface
import com.openminis.app.offload.ShizukuManager
import rikka.shizuku.Shizuku
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/** A separate display that cannot become the destination for the user's undirected key events. */
internal object HandsDisplayHost {
    private val inUse = AtomicBoolean()

    private fun shizukuReady() = ShizukuManager.isReady() &&
        runCatching { Shizuku.getVersion() >= Hands.BACKGROUND_MIN_SHIZUKU }.getOrDefault(false)

    fun isReady() = HandsDisplayBridge.isReady() || shizukuReady()

    class Handle internal constructor(val display: Display, private val service: IHandsDisplay,
        private val authorized: () -> Boolean, private val release: () -> Unit) : AutoCloseable {
        private val closed = AtomicBoolean()
        fun isReady() = !closed.get() && service.asBinder().isBinderAlive && authorized()
        fun launch(pkg: String) = isReady() && service.launchPackage(pkg)
        fun tap(x: Int, y: Int) = isReady() && service.tap(x, y)
        fun swipe(x1: Int, y1: Int, x2: Int, y2: Int, ms: Int) = isReady() && service.swipe(x1, y1, x2, y2, ms)
        fun back() = isReady() && service.back()
        fun rememberTask(pkg: String) = isReady() && runCatching { service.rememberTask(pkg) }.getOrDefault(false)
        fun handOffToPhone() = isReady() && runCatching { service.handOffToPhone() }.getOrDefault(false)
        override fun close() {
            if (closed.compareAndSet(false, true)) release()
        }
    }

    fun open(context: Context, surface: Surface, width: Int, height: Int, dpi: Int): Handle {
        check(Build.VERSION.SDK_INT >= Hands.BACKGROUND_MIN_SDK && isReady()) {
            "Android 14 or newer and an authorized background screen connection are required."
        }
        check(Looper.myLooper() != Looper.getMainLooper()) { "Waiting for the background display would block the main thread." }
        check(inUse.compareAndSet(false, true)) { "A background display is already open." }
        val local = HandsDisplayBridge.current()
        if (local != null) {
            val allocated = AtomicBoolean()
            fun releaseLocal() {
                try { if (allocated.get()) local.close() } finally { inUse.set(false) }
            }
            try {
                val display = allocate(context, local, surface, width, height, dpi, allocated)
                return Handle(display, local, { HandsDisplayBridge.current()?.asBinder() == local.asBinder() }, ::releaseLocal)
            } catch (failure: Throwable) {
                runCatching { releaseLocal() }
                throw failure
            }
        }
        // A binder timeout from a previous run must never tear down the next run's screen.
        val tag = "nanomuse-hands-display-" + UUID.randomUUID()
        val args = Shizuku.UserServiceArgs(ComponentName(context, HandsDisplayUserService::class.java))
            .tag(tag).version(4).daemon(false).processNameSuffix("hands_display")
        val connected = CountDownLatch(1)
        val connection = object : ServiceConnection {
            @Volatile var remote: IHandsDisplay? = null
            override fun onServiceConnected(name: ComponentName, binder: IBinder) {
                remote = IHandsDisplay.Stub.asInterface(binder)
                connected.countDown()
            }
            override fun onServiceDisconnected(name: ComponentName) {
                remote = null
                connected.countDown()
            }
        }
        fun release() {
            try {
                connection.remote?.close()
            } finally {
                try { Shizuku.unbindUserService(args, connection, true) } finally { inUse.set(false) }
            }
        }
        try {
            Shizuku.bindUserService(args, connection)
            check(connected.await(10, TimeUnit.SECONDS)) { "The background display service did not connect." }
            val remote = checkNotNull(connection.remote) { "The background display service disconnected." }
            val display = allocate(context, remote, surface, width, height, dpi, AtomicBoolean())
            return Handle(display, remote, ::shizukuReady, ::release)
        } catch (failure: Throwable) {
            runCatching { release() }.exceptionOrNull()?.let { failure.addSuppressed(it) }
            throw failure
        }
    }
    private fun allocate(context: Context, remote: IHandsDisplay, surface: Surface, width: Int, height: Int,
        dpi: Int, allocated: AtomicBoolean): Display {
        val session = remote.open(surface, width, height, dpi, Binder())
        allocated.set(true)
        check(session.size == 2 && session[1] >= 0 && session[0] > Display.DEFAULT_DISPLAY) {
            "Android did not allocate a separate screen and user profile."
        }
        return checkNotNull(context.getSystemService(DisplayManager::class.java).getDisplay(session[0])).also {
            check(it.isValid) { "The background display was removed." }
        }
    }

}
