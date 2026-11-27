package io.github.nanomuse.hands

import android.content.ContentProvider
import android.content.ContentValues
import android.content.Context
import android.database.Cursor
import android.net.Uri
import android.os.Binder
import android.os.Bundle
import android.os.IBinder
import android.os.SystemClock
import android.util.Base64
import com.openminis.app.BuildConfig
import java.security.MessageDigest
import java.security.SecureRandom
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow

internal class HandsDisplayActivation(val command: String, val nonce: String)

/** A claim is valid once, and a disconnect invalidates even a handshake already in flight. */
internal class HandsBridgeTickets {
    private var generation = 0L
    private var ticket: String? = null
    private var expires = 0L

    fun issue(nonce: String, now: Long) {
        generation++
        ticket = nonce
        expires = now + 90_000L
    }

    fun clear() {
        generation++
        ticket = null
    }

    fun consume(nonce: String, now: Long): Long? {
        val expected = ticket ?: return null
        if (now >= expires || !MessageDigest.isEqual(expected.toByteArray(Charsets.US_ASCII),
                nonce.toByteArray(Charsets.US_ASCII))) return null
        ticket = null
        return generation
    }

    fun current(id: Long) = generation == id
}

/** One foreground activation for this app process. An ADB connection can hand over only the
 * narrow display interface. The pairing transport owns its lifetime and calls disconnect on EOF. */
internal object HandsDisplayBridge {
    const val METHOD = "offerHandsDisplay"
    const val SHELL_UID = 2000
    private val lock = Any()
    private val clientToken = Binder()
    private val state = MutableStateFlow(false)
    val ready = state.asStateFlow()
    private val tickets = HandsBridgeTickets()
    private var service: IHandsDisplay? = null

    fun beginActivation(context: Context): HandsDisplayActivation {
        disconnect()
        val app = context.applicationContext
        val path = app.applicationInfo.sourceDir
        check(app.packageName == BuildConfig.APPLICATION_ID && path.matches(Regex("/[a-zA-Z0-9_./~+=-]+\\.apk"))) {
            "The installed nanoMuse package could not be identified."
        }
        val nonce = Base64.encodeToString(ByteArray(32).also(SecureRandom()::nextBytes),
            Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)
        val command = "CLASSPATH='$path' exec /system/bin/app_process /system/bin --nice-name=nanomuse-hands " +
            "io.github.nanomuse.hands.HandsDisplayBridgeMain ${app.applicationInfo.uid}"
        synchronized(lock) { tickets.issue(nonce, SystemClock.elapsedRealtime()) }
        return HandsDisplayActivation(command, nonce)
    }

    fun isReady() = current() != null

    fun current(): IHandsDisplay? = synchronized(lock) { service?.takeIf { it.asBinder().isBinderAlive } }

    fun disconnect() {
        val old = synchronized(lock) {
            tickets.clear()
            val previous = service
            service = null
            state.value = false
            previous
        }
        runCatching { old?.destroy() }
    }

    fun offer(extras: Bundle?, uid: Int, pid: Int): Bundle? {
        if (uid != SHELL_UID || pid <= 0) return null
        val value = extras?.getString("nonce") ?: return null
        if (value.length != 43) return null
        val binder = extras.getBinder("display") ?: return null
        val remote = IHandsDisplay.Stub.asInterface(binder)
        val claim = synchronized(lock) { tickets.consume(value, SystemClock.elapsedRealtime()) } ?: return null
        val caller = Binder.clearCallingIdentity()
        try {
            if (!remote.identity().contentEquals(intArrayOf(uid, pid))) return null
            binder.linkToDeath({
                synchronized(lock) {
                    if (service?.asBinder() == binder) {
                        service = null
                        state.value = false
                    }
                }
            }, 0)
        } finally { Binder.restoreCallingIdentity(caller) }
        synchronized(lock) {
            if (!tickets.current(claim) || !binder.isBinderAlive) return null
            service = remote
            state.value = true
            return Bundle().apply { putBinder("owner", clientToken) }
        }
    }
}

/** A shell-only rendezvous. It never returns a service binder or handles any data operation. */
class HandsDisplayBridgeProvider : ContentProvider() {
    override fun onCreate() = true
    override fun call(method: String, arg: String?, extras: Bundle?): Bundle? {
        if (method != HandsDisplayBridge.METHOD) return null
        return HandsDisplayBridge.offer(extras, Binder.getCallingUid(), Binder.getCallingPid())
    }
    override fun query(uri: Uri, projection: Array<out String>?, selection: String?, selectionArgs: Array<out String>?, sortOrder: String?): Cursor? = null
    override fun getType(uri: Uri): String? = null
    override fun insert(uri: Uri, values: ContentValues?): Uri? = null
    override fun delete(uri: Uri, selection: String?, selectionArgs: Array<out String>?) = 0
    override fun update(uri: Uri, values: ContentValues?, selection: String?, selectionArgs: Array<out String>?) = 0
}
