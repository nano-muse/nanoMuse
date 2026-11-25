package io.github.nanomuse.hands

import android.content.Context
import android.content.AttributionSource
import android.os.Bundle
import android.os.Binder
import android.os.IBinder
import android.os.Looper
import android.os.Process
import android.os.UserHandle
import androidx.annotation.Keep
import com.openminis.app.BuildConfig
import kotlin.system.exitProcess

/** Android's own content shell command acquires an external provider with the shell UID.
 * A standalone shell process has no registered APK ApplicationThread for a normal resolver.
 * These are the only two requests the helper can issue; neither URI nor method comes from IPC. */
internal class HandsShellBridgeCalls(private val user: Int) {
    private val manager = Class.forName("android.app.ActivityManager").getMethod("getService").invoke(null)
    private val api = Class.forName("android.app.IActivityManager")
    private val acquire = api.getMethod("getContentProviderExternal", String::class.java, Integer.TYPE, IBinder::class.java, String::class.java)
    private val release = api.getMethod("removeContentProviderExternalAsUser", String::class.java, IBinder::class.java, Integer.TYPE)
    private val providerCall = Class.forName("android.content.IContentProvider").getMethod("call", AttributionSource::class.java,
        String::class.java, String::class.java, String::class.java, Bundle::class.java)
    private val shell = AttributionSource.Builder(Process.myUid()).setPackageName("com.android.shell").build()

    fun wirelessEnabled(): Boolean = runCatching {
        call("settings", "GET_global", "adb_wifi_enabled", null)?.getString("value") == "1"
    }.getOrDefault(false)

    fun offer(extras: Bundle): IBinder? = call(BuildConfig.APPLICATION_ID + ".hands-bridge",
        HandsDisplayBridge.METHOD, null, extras)?.getBinder("owner")

    private fun call(authority: String, method: String, key: String?, extras: Bundle?): Bundle? {
        val token = Binder()
        val holder = acquire.invoke(manager, authority, user, token, "nanoMuse Hands") ?: return null
        return try {
            val provider = holder.javaClass.getField("provider").get(holder) ?: return null
            providerCall.invoke(provider, shell, authority, method, key, extras) as? Bundle
        } finally { release.invoke(manager, authority, token, user) }
    }
}

/** Entry point of the single fixed operation offered to an authenticated local ADB connection.
 * It accepts no shell commands, command-line nonce, network clients or external display IDs. */
@Keep
object HandsDisplayBridgeMain {
    @JvmStatic fun main(args: Array<String>) {
        if (Process.myUid() != HandsDisplayBridge.SHELL_UID || args.size != 1) exitProcess(1)
        var stage = "caller"
        try {
            val uid = args.single().toInt()
            check(uid >= Process.FIRST_APPLICATION_UID)
            // Read a fixed-length URL-safe ticket. Never echo it or keep it in the command line.
            stage = "ticket input"
            val bytes = ByteArray(43)
            java.io.DataInputStream(System.`in`).readFully(bytes)
            check(System.`in`.read() == 10)
            val nonce = bytes.toString(Charsets.US_ASCII)
            check(nonce.matches(Regex("[A-Za-z0-9_-]{43}")))
            stage = "main looper"
            @Suppress("DEPRECATION")
            Looper.prepareMainLooper()
            stage = "system context"
            val thread = Class.forName("android.app.ActivityThread")
            val system = thread.getMethod("getSystemContext").invoke(thread.getMethod("systemMain").invoke(null)) as Context
            stage = "package context"
            val profile = UserHandle.getUserHandleForUid(uid)
            val contextFor = Context::class.java.getMethod("createPackageContextAsUser",
                String::class.java, Integer.TYPE, UserHandle::class.java)
            val pkg = BuildConfig.APPLICATION_ID
            val calls = HandsShellBridgeCalls(UserHandle::class.java.getMethod("getIdentifier").invoke(profile) as Int)
            val app = contextFor.invoke(system, pkg, 0, profile) as Context
            stage = "installed package"
            check(app.applicationInfo.uid == uid && app.applicationInfo.sourceDir == System.getenv("CLASSPATH"))
            stage = "wireless authorization"
            check(calls.wirelessEnabled())
            val display = HandsDisplayUserService(app).also { it.wirelessAccess = calls }
            val argsForProvider = Bundle().apply { putString("nonce", nonce); putBinder("display", display) }
            stage = "binder delivery"
            val owner = calls.offer(argsForProvider) ?: error("Activation was rejected.")
            stage = "owner lifecycle"
            owner.linkToDeath({ exitProcess(0) }, 0)
            // The authenticated ADB transport stays open. Disconnecting it destroys the
            // service. Also verify the system setting before every subsequent operation.
            check(owner.isBinderAlive && calls.wirelessEnabled())
            stage = "display service"
            Looper.loop()
        } catch (failure: Exception) {
            // Only the exception type is useful for local diagnostics. The ticket stays private.
            val reason = failure.cause ?: failure
            val line = failure.stackTrace.firstOrNull { it.className == HandsDisplayBridgeMain::class.java.name }?.lineNumber
            android.util.Log.w("HandsDisplay", "Local activation ended at $stage ($line): " + reason.javaClass.simpleName)
            exitProcess(1)
        }
    }
}
