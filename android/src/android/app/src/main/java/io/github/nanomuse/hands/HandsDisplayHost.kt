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
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

/** A separate display that cannot become the destination for the user's undirected key events. */
internal object HandsDisplayHost {
    class Handle internal constructor(val display: Display, val userId: Int, private val release: () -> Unit) : AutoCloseable {
        private val closed = AtomicBoolean()
        override fun close() {
            if (closed.compareAndSet(false, true)) release()
        }
    }

    fun open(context: Context, surface: Surface, width: Int, height: Int, dpi: Int): Handle {
        check(Build.VERSION.SDK_INT >= Hands.BACKGROUND_MIN_SDK && ShizukuManager.isReady() && Shizuku.getVersion() >= Hands.BACKGROUND_MIN_SHIZUKU) {
            "An authorized Shizuku 13 or newer and Android 14 or newer are required for an independent screen."
        }
        check(Looper.myLooper() != Looper.getMainLooper()) { "Waiting for the background display would block the main thread." }
        val args = Shizuku.UserServiceArgs(ComponentName(context, HandsDisplayUserService::class.java))
            .tag("nanomuse-hands-display").version(2).daemon(false).processNameSuffix("hands_display")
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
        // Retained by the service as a death token. A process exit also releases the display.
        val owner = Binder()
        fun release() {
            try {
                connection.remote?.close()
            } finally {
                Shizuku.unbindUserService(args, connection, true)
            }
        }
        Shizuku.bindUserService(args, connection)
        try {
            check(connected.await(10, TimeUnit.SECONDS)) { "The background display service did not connect." }
            val remote = checkNotNull(connection.remote) { "The background display service disconnected." }
            val session = remote.open(surface, width, height, dpi, owner)
            check(session.size == 2 && session[1] >= 0) { "Could not identify the Android profile for this display." }
            val id = session[0]
            check(id > Display.DEFAULT_DISPLAY) { "Android did not allocate a separate screen." }
            val display = checkNotNull(context.getSystemService(DisplayManager::class.java).getDisplay(id))
            check(display.isValid) { "The background display was removed." }
            return Handle(display, session[1], ::release)
        } catch (failure: Throwable) {
            runCatching { release() }.exceptionOrNull()?.let { failure.addSuppressed(it) }
            throw failure
        }
    }
}
