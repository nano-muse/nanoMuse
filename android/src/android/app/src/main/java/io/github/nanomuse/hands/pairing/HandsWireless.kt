package io.github.nanomuse.hands.pairing

import android.content.Context
import android.net.ssl.SSLSockets
import io.github.nanomuse.hands.HandsDisplayBridge
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.delay
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import java.io.File
import java.io.IOException
import java.net.InetAddress
import java.net.InetSocketAddress
import javax.net.ssl.SSLException
import kotlin.concurrent.thread

/** User-initiated, on-device Android wireless debugging for the Hands background screen. */
object HandsWireless {
    private val operations = Mutex()
    private val lifetime = Any()
    private var current: WirelessDisplayStream? = null

    internal fun loopback(port: Int): InetSocketAddress {
        require(port in 1..65535)
        return InetSocketAddress(InetAddress.getByAddress(byteArrayOf(127, 0, 0, 1)), port)
    }

    private fun marker(context: Context) = File(context.noBackupFilesDir, "hands-wireless-paired")
    fun hasIdentity(context: Context): Boolean = marker(context).isFile

    suspend fun discover(context: Context, pairing: Boolean): List<Int> =
        NsdAdbServiceFinder(context).findPorts(if (pairing) AdbServiceTypes.PAIRING else AdbServiceTypes.CONNECT, 3_000L)

    private fun tls(pairing: Boolean) = AdbTls(AdbIdentity.load(pairing), KeyingMaterialExporter { socket, label, length ->
        SSLSockets.exportKeyingMaterial(socket, label, byteArrayOf(), length)
            ?: throw SSLException("The phone could not export pairing material")
    })

    suspend fun pair(context: Context, port: Int, code: String) = withContext(Dispatchers.IO) {
        operations.withLock {
            require(code.length == 6 && code.all { it in '0'..'9' })
            val peer = AdbPairing(tls(pairing = true)).pair(port, code)
            if (peer.type != AdbPairing.PEER_DEVICE_GUID.toInt() || peer.data.isBlank()) {
                throw IOException("Unexpected wireless debugging peer")
            }
            marker(context).createNewFile()
            Unit
        }
    }

    suspend fun activate(context: Context, port: Int) = withContext(Dispatchers.IO) {
        operations.withLock {
            check(hasIdentity(context)) { "Pair this phone first" }
            if (HandsDisplayBridge.isReady()) return@withLock
            stop()
            try {
                val activation = HandsDisplayBridge.beginActivation(context)
                val stream = WirelessDisplayStream.open(port, tls(pairing = false), activation)
                synchronized(lifetime) { current = stream }
                thread(isDaemon = true, name = "hands-display-pairing") {
                    try {
                        stream.awaitDisconnect()
                    } catch (_: IOException) {
                        // Android closes TLS when wireless debugging or the device authorization is revoked.
                    } finally {
                        synchronized(lifetime) {
                            if (current === stream) stop()
                        }
                    }
                }
                val connected = withTimeoutOrNull(12_000) {
                    while (!HandsDisplayBridge.isReady()) {
                        if (synchronized(lifetime) { current !== stream }) throw IOException("The display helper disconnected")
                        delay(80)
                    }
                    true
                }
                currentCoroutineContext().ensureActive()
                if (connected != true) throw IOException("The display helper did not connect")
            } catch (cause: Throwable) {
                stop()
                throw cause
            }
        }
    }

    /** Reconnect only to this phone's advertised debugging port after an explicit screen task or settings visit. */
    suspend fun reconnect(context: Context): Boolean {
        if (HandsDisplayBridge.isReady()) return true
        if (!hasIdentity(context)) return false
        return withTimeoutOrNull(18_000L) {
            try {
                val port = discover(context, pairing = false).distinct().singleOrNull() ?: return@withTimeoutOrNull false
                activate(context, port)
                true
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                false
            }
        } ?: false
    }

    private fun stop() = synchronized(lifetime) {
        val previous = current
        current = null
        runCatching { previous?.close() }
        HandsDisplayBridge.disconnect()
    }

    suspend fun forget(context: Context) = withContext(Dispatchers.IO) {
        operations.withLock {
            stop()
            AdbIdentity.forget()
            val paired = marker(context)
            check(!paired.exists() || paired.delete()) { "Could not clear the pairing record" }
        }
    }
}
