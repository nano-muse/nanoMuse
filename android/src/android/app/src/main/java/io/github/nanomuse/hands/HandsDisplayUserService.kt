package io.github.nanomuse.hands

import android.content.Context
import android.graphics.Point
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.os.Binder
import android.os.Build
import android.os.IBinder
import android.os.Process
import android.os.UserHandle
import android.view.Display
import android.view.Surface
import androidx.annotation.Keep
import kotlin.system.exitProcess

/** Runs as the user's authorized Shizuku identity. Only the originating app may allocate a screen. */
@Keep
class HandsDisplayUserService(private val context: Context) : IHandsDisplay.Stub() {
    private val clientUid = context.applicationInfo.uid
    private var virtual: VirtualDisplay? = null
    private var surface: Surface? = null
    private var client: IBinder? = null
    private val clientDied = IBinder.DeathRecipient { synchronized(this) { releaseDisplay() } }

    @Synchronized
    override fun open(surface: Surface, width: Int, height: Int, dpi: Int, owner: IBinder): IntArray {
        enforceClient()
        if (client != null) {
            surface.release()
            error("A background display is already open.")
        }
        val identity = Binder.clearCallingIdentity()
        try {
            this.surface = surface
            check(Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE)
            require(surface.isValid && width in 1..4096 && height in 1..4096 && dpi in 72..640)
            client = owner
            owner.linkToDeath(clientDied, 0)
            // DisplayManagerService matches the calling package to the actual binder UID.
            val shell = context.createPackageContext("com.android.shell", 0)
            val dm = shell.getSystemService(DisplayManager::class.java)
            val screen = checkNotNull(dm.createVirtualDisplay("nanoMuse Hands", width, height, dpi, surface, FLAGS))
            virtual = screen
            val display = screen.display
            val size = Point()
            @Suppress("DEPRECATION")
            display.getRealSize(size)
            check(display.isValid && display.displayId > Display.DEFAULT_DISPLAY && size.x == width && size.y == height)
            check(display.flags and REQUIRED_DISPLAY_FLAGS == REQUIRED_DISPLAY_FLAGS &&
                display.flags and (Display.FLAG_SECURE or Display.FLAG_SUPPORTS_PROTECTED_BUFFERS) == 0) {
                "Android did not provide independent input focus and a non-secure screen."
            }
            // System APIs in the authorized user service. Read back both policies before any app starts.
            check(Display::class.java.getMethod("getRemoveMode").invoke(display) == REMOVE_MODE_DESTROY_CONTENT) {
                "Android would move the background app to another display on removal."
            }
            hideKeyboard(display.displayId)
            val profile = UserHandle.getUserHandleForUid(clientUid)
            val userId = UserHandle::class.java.getMethod("getIdentifier").invoke(profile) as Int
            check(userId >= 0)
            return intArrayOf(display.displayId, userId)
        } catch (failure: Throwable) {
            releaseDisplay()
            throw IllegalStateException("Could not create an isolated background screen: ${failure.message ?: failure.javaClass.simpleName}", failure)
        } finally {
            Binder.restoreCallingIdentity(identity)
        }
    }

    private fun hideKeyboard(id: Int) {
        val wm = Class.forName("android.view.WindowManagerGlobal").getMethod("getWindowManagerService").invoke(null)
        val api = Class.forName("android.view.IWindowManager")
        api.getMethod("setDisplayImePolicy", Integer.TYPE, Integer.TYPE).invoke(wm, id, IME_HIDE)
        check(api.getMethod("getDisplayImePolicy", Integer.TYPE).invoke(wm, id) == IME_HIDE) {
            "Android did not isolate the background keyboard."
        }
    }

    private fun enforceClient() {
        check(Binder.getCallingUid() == clientUid) { "The display belongs to a different caller." }
    }

    @Synchronized
    override fun close() {
        enforceClient()
        releaseDisplay()
    }

    @Synchronized
    override fun destroy() {
        val caller = Binder.getCallingUid()
        check(caller == clientUid || caller == Process.myUid() || caller == 0 || caller == 2000)
        try {
            releaseDisplay()
        } finally {
            exitProcess(0)
        }
    }

    private fun releaseDisplay() {
        client?.let { runCatching { it.unlinkToDeath(clientDied, 0) } }
        client = null
        try {
            virtual?.release()
        } finally {
            virtual = null
            surface?.release()
            surface = null
        }
    }

    private companion object {
        // Android 14 DisplayManager creation flags. Secure output, mirroring and always-unlocked are excluded.
        const val SUPPORTS_TOUCH = 1 shl 6
        const val DESTROY_CONTENT_ON_REMOVAL = 1 shl 8
        const val TRUSTED = 1 shl 10
        const val OWN_FOCUS = 1 shl 14
        const val STEAL_TOP_FOCUS_DISABLED = 1 shl 16
        const val FLAGS = DisplayManager.VIRTUAL_DISPLAY_FLAG_PUBLIC or DisplayManager.VIRTUAL_DISPLAY_FLAG_OWN_CONTENT_ONLY or
            SUPPORTS_TOUCH or DESTROY_CONTENT_ON_REMOVAL or TRUSTED or OWN_FOCUS or STEAL_TOP_FOCUS_DISABLED

        // Display.getFlags() reports these in a different bit field than DisplayManager accepts.
        const val DISPLAY_TRUSTED = 1 shl 7
        const val DISPLAY_OWN_FOCUS = 1 shl 11
        const val DISPLAY_STEAL_TOP_FOCUS_DISABLED = 1 shl 12
        const val REQUIRED_DISPLAY_FLAGS = DISPLAY_TRUSTED or DISPLAY_OWN_FOCUS or DISPLAY_STEAL_TOP_FOCUS_DISABLED
        const val REMOVE_MODE_DESTROY_CONTENT = 1
        const val IME_HIDE = 2
    }
}
