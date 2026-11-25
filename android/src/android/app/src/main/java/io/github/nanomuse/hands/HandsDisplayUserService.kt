package io.github.nanomuse.hands

import android.app.KeyguardManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.ActivityInfo
import android.graphics.Point
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.os.Binder
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.os.Process
import android.os.UserHandle
import android.view.Display
import android.view.Surface
import androidx.annotation.Keep
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import kotlin.system.exitProcess

/** Check the same exported launcher in the app process and the authorized service. */
internal fun handsDisplayLauncher(context: Context, pkg: String): ComponentName {
    val pm = context.packageManager
    val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER).setPackage(pkg)
    val info = checkNotNull(pm.resolveActivity(intent, 0)?.activityInfo) { "No launcher activity was found." }
    check(info.exported && info.packageName == pkg && pkg != context.packageName && info.permission.isNullOrEmpty())
    val activity = info.targetActivity?.let { pm.getActivityInfo(ComponentName(pkg, it), 0) } ?: info
    check(activity.launchMode in ActivityInfo.LAUNCH_MULTIPLE..ActivityInfo.LAUNCH_SINGLE_TOP &&
        activity.flags and ActivityInfo.FLAG_ALLOW_TASK_REPARENTING == 0) {
        "This app requires a shared task and cannot be opened safely on the background screen."
    }
    return ComponentName(pkg, info.name)
}

/** Runs under a device-owner authorized debugging identity. Only the originating app may operate its own screen. */
@Keep
class HandsDisplayUserService(private val context: Context) : IHandsDisplay.Stub() {
    internal var wirelessAccess: HandsShellBridgeCalls? = null
    private val clientUid = context.applicationInfo.uid
    private var virtual: VirtualDisplay? = null
    private data class TargetTask(val id: Int, val pkg: String)
    private var target: TargetTask? = null
    private var selectedPackage: String? = null
    private val child = AtomicReference<java.lang.Process?>()
    private var profileId = -1
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
            profileId = userId
            return intArrayOf(display.displayId, userId)
        } catch (failure: Throwable) {
            releaseDisplay()
            throw IllegalStateException("Could not create an isolated background screen: ${failure.message ?: failure.javaClass.simpleName}", failure)
        } finally {
            Binder.restoreCallingIdentity(identity)
        }
    }

    // These system calls run under the already authorized debugging identity. Query only our
    // private display. Never accept a task ID, profile or destination display from a caller.
    private val taskApi get() = Class.forName("android.app.IActivityTaskManager")
    private fun manager() = Class.forName("android.app.ActivityTaskManager").getMethod("getService").invoke(null)

    private fun onlyTask(service: Any?, pkg: String): TargetTask? {
        val display = virtual?.display?.takeIf { it.isValid && it.displayId > Display.DEFAULT_DISPLAY } ?: return null
        val roots = taskApi.getMethod("getAllRootTaskInfosOnDisplay", Integer.TYPE)
            .invoke(service, display.displayId) as? List<*> ?: return null
        val root = roots.singleOrNull() ?: return null
        val type = root.javaClass
        val taskId = type.getField("taskId").getInt(root)
        val leaves = type.getField("childTaskIds").get(root) as? IntArray ?: return null
        val users = type.getField("childTaskUserIds").get(root) as? IntArray ?: return null
        val sameDisplay = type.getField("displayId").getInt(root) == display.displayId
        val sameUser = type.getField("userId").getInt(root) == profileId
        if (taskId < 0 || !sameDisplay || !sameUser || leaves.singleOrNull() != taskId ||
            users.singleOrNull() != profileId) {
            android.util.Log.i("HandsDisplay", "Unsupported task layout: sameDisplay=$sameDisplay, sameUser=$sameUser, singleLeaf=" +
                (leaves.singleOrNull() == taskId) + ", singleProfile=" + (users.singleOrNull() == profileId))
            return null
        }
        val base = type.getField("baseActivity").get(root) as? ComponentName
        val top = type.getField("topActivity").get(root) as? ComponentName
        return if (base?.packageName == pkg && top?.packageName == pkg) TargetTask(taskId, pkg) else null
    }

    @Synchronized
    override fun rememberTask(packageName: String): Boolean {
        enforceClient()
        val identity = Binder.clearCallingIdentity()
        return try {
            if (packageName != selectedPackage) return false
            if (target == null) target = onlyTask(manager(), packageName)
            target?.pkg == packageName
        } catch (failure: ReflectiveOperationException) {
            android.util.Log.i("HandsDisplay", "Task handoff unavailable: " + (failure.cause ?: failure).javaClass.simpleName)
            false
        } finally { Binder.restoreCallingIdentity(identity) }
    }

    @Synchronized
    override fun handOffToPhone(): Boolean {
        enforceClient()
        val identity = Binder.clearCallingIdentity()
        return try {
            val expected = target ?: return false
            val service = manager()
            if (onlyTask(service, expected.pkg) != expected ||
                context.getSystemService(KeyguardManager::class.java).isDeviceLocked ||
                !context.getSystemService(PowerManager::class.java).isInteractive) return false
            target = null
            taskApi.getMethod("moveRootTaskToDisplay", Integer.TYPE, Integer.TYPE)
                .invoke(service, expected.id, Display.DEFAULT_DISPLAY)
            true
        } finally { Binder.restoreCallingIdentity(identity) }
    }

    @Synchronized override fun launchPackage(packageName: String): Boolean = withOwner {
        val screen = ownDisplay() ?: return@withOwner false
        if (selectedPackage != null || !unlocked() || packageName == context.packageName) return@withOwner false
        val launcher = handsDisplayLauncher(context, packageName)
        selectedPackage = packageName
        val flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_MULTIPLE_TASK or Intent.FLAG_ACTIVITY_EXCLUDE_FROM_RECENTS
        fixedCommand("/system/bin/am", "start", "--user", profileId.toString(), "--display", screen.displayId.toString(),
            "-f", flags.toString(), "-a", Intent.ACTION_MAIN, "-c", Intent.CATEGORY_LAUNCHER,
            "-n", launcher.flattenToString())
    }

    private fun ownDisplay() = virtual?.display?.takeIf { it.isValid && it.displayId > Display.DEFAULT_DISPLAY }
    private fun unlocked() = !context.getSystemService(KeyguardManager::class.java).isDeviceLocked &&
        context.getSystemService(PowerManager::class.java).isInteractive

    private inline fun <T> withOwner(block: () -> T): T {
        enforceClient()
        val identity = Binder.clearCallingIdentity()
        try { return block() } finally { Binder.restoreCallingIdentity(identity) }
    }

    private fun validInput(): Display? {
        val screen = ownDisplay() ?: return null
        val pinned = target ?: return null
        return screen.takeIf { unlocked() && onlyTask(manager(), pinned.pkg) == pinned }
    }

    private fun contains(screen: Display, x: Int, y: Int): Boolean {
        val size = Point()
        @Suppress("DEPRECATION")
        screen.getRealSize(size)
        return x in 0 until size.x && y in 0 until size.y
    }

    @Synchronized override fun tap(x: Int, y: Int): Boolean = withOwner {
        val screen = validInput() ?: return@withOwner false
        contains(screen, x, y) && fixedCommand("/system/bin/input", "touchscreen", "-d", screen.displayId.toString(),
            "tap", x.toString(), y.toString())
    }

    @Synchronized override fun swipe(x1: Int, y1: Int, x2: Int, y2: Int, durationMs: Int): Boolean = withOwner {
        val screen = validInput() ?: return@withOwner false
        durationMs in 1..5_000 && contains(screen, x1, y1) && contains(screen, x2, y2) &&
            fixedCommand("/system/bin/input", "touchscreen", "-d", screen.displayId.toString(), "swipe",
                x1.toString(), y1.toString(), x2.toString(), y2.toString(), durationMs.toString())
    }

    @Synchronized override fun back(): Boolean = withOwner {
        val screen = validInput() ?: return@withOwner false
        fixedCommand("/system/bin/input", "keyboard", "-d", screen.displayId.toString(), "keyevent", "KEYCODE_BACK")
    }

    override fun identity(): IntArray {
        enforceClient()
        return intArrayOf(Process.myUid(), Process.myPid())
    }

    // Only the typed operations above construct argv. No shell interpretation or arbitrary text.
    private fun fixedCommand(vararg argv: String): Boolean {
        val process = ProcessBuilder(*argv).redirectErrorStream(true).start()
        child.set(process)
        try {
            process.outputStream.close()
            if (!process.waitFor(8, TimeUnit.SECONDS)) return false
            val output = ByteArray(4097)
            var length = 0
            while (length < output.size) {
                val count = process.inputStream.read(output, length, output.size - length)
                if (count < 0) break
                length += count
            }
            if (length == output.size) return false
            val message = String(output, 0, length, Charsets.UTF_8)
            return process.exitValue() == 0 && !message.contains("Error:", true) && !message.contains("Exception", true)
        } finally {
            child.compareAndSet(process, null)
            if (process.isAlive) process.destroyForcibly()
            process.inputStream.close()
            process.errorStream.close()
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
        wirelessAccess?.let { calls ->
            val identity = Binder.clearCallingIdentity()
            try { check(calls.wirelessEnabled()) { "Wireless debugging was disabled." } }
            finally { Binder.restoreCallingIdentity(identity) }
        }
    }

    @Synchronized
    override fun close() {
        enforceClient()
        releaseDisplay()
    }

    override fun destroy() {
        val caller = Binder.getCallingUid()
        check(caller == clientUid || caller == Process.myUid() || caller == 0 || caller == 2000)
        // Revocation also interrupts a gesture in progress. Binder death destroys the owned
        // display even when another call is blocked in a platform input or launch operation.
        child.getAndSet(null)?.destroyForcibly()
        exitProcess(0)
    }

    private fun releaseDisplay() {
        target = null
        selectedPackage = null
        profileId = -1
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
