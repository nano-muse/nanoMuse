package io.github.nanomuse.hands

import android.content.Context
import android.database.ContentObserver
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.Process
import android.os.UserHandle
import android.provider.Settings
import androidx.annotation.Keep
import com.openminis.app.BuildConfig
import kotlin.system.exitProcess

/** Entry point of the single fixed operation offered to an authenticated local ADB connection.
 * It accepts no shell commands, command-line nonce, network clients or external display IDs. */
@Keep
object HandsDisplayBridgeMain {
    private const val WIFI_SETTING = "adb_wifi_enabled"

    fun wirelessEnabled(shell: Context): Boolean = runCatching {
        Settings.Global.getInt(shell.contentResolver, WIFI_SETTING, 0) == 1
    }.getOrDefault(false)

    @JvmStatic fun main(args: Array<String>) {
        if (Process.myUid() != HandsDisplayBridge.SHELL_UID || args.size != 1) exitProcess(1)
        try {
            val uid = args.single().toInt()
            check(uid >= Process.FIRST_APPLICATION_UID)
            // Read a fixed-length URL-safe ticket. Never echo it or keep it in the command line.
            val bytes = ByteArray(43)
            java.io.DataInputStream(System.`in`).readFully(bytes)
            check(System.`in`.read() == 10)
            val nonce = bytes.toString(Charsets.US_ASCII)
            check(nonce.matches(Regex("[A-Za-z0-9_-]{43}")))
            @Suppress("DEPRECATION")
            Looper.prepareMainLooper()
            val thread = Class.forName("android.app.ActivityThread")
            val system = thread.getMethod("getSystemContext").invoke(thread.getMethod("systemMain").invoke(null)) as Context
            val profile = UserHandle.getUserHandleForUid(uid)
            val contextFor = Context::class.java.getMethod("createPackageContextAsUser",
                String::class.java, Integer.TYPE, UserHandle::class.java)
            val pkg = BuildConfig.APPLICATION_ID
            val shell = contextFor.invoke(system, "com.android.shell", 0, profile) as Context
            val app = contextFor.invoke(system, pkg, 0, profile) as Context
            check(app.applicationInfo.uid == uid && app.applicationInfo.sourceDir == System.getenv("CLASSPATH"))
            check(wirelessEnabled(shell))
            val display = HandsDisplayUserService(app).also { it.wirelessContext = shell }
            val argsForProvider = Bundle().apply { putString("nonce", nonce); putBinder("display", display) }
            val owner = shell.contentResolver.call(Uri.parse("content://$pkg.hands-bridge"),
                HandsDisplayBridge.METHOD, null, argsForProvider)?.getBinder("owner") ?: error("Activation was rejected.")
            owner.linkToDeath({ exitProcess(0) }, 0)
            val observer = object : ContentObserver(Handler(Looper.getMainLooper())) {
                override fun onChange(selfChange: Boolean) { if (!wirelessEnabled(shell)) exitProcess(0) }
            }
            shell.contentResolver.registerContentObserver(Settings.Global.getUriFor(WIFI_SETTING), false, observer)
            check(owner.isBinderAlive && wirelessEnabled(shell))
            Looper.loop()
        } catch (failure: Exception) {
            // Only the exception type is useful for local diagnostics. The ticket stays private.
            android.util.Log.w("HandsDisplay", "Local activation ended: " + (failure.cause ?: failure).javaClass.simpleName)
            exitProcess(1)
        }
    }
}
