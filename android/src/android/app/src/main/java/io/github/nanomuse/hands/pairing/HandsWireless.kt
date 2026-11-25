// SPDX-License-Identifier: Apache-2.0
// Adapted from Mika (Copyright 2026 wangzan101) for nanoMuse local wireless pairing.
package io.github.nanomuse.hands.pairing

import android.annotation.SuppressLint
import android.content.Context
import android.net.ssl.SSLSockets
import android.util.Log
import io.github.nanomuse.hands.HandsDisplayBridge
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
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
    private const val TAG = "HandsWireless"
    private const val PREFS = "nanomuse_hands_wireless"
    private const val KEY_LAST_PORT = "last_connect_port"
    private const val TLS_PORT_PROPERTY = "service.adb.tls.port"
    private const val PORT_RANGE_FILE = "/proc/sys/net/ipv4/ip_local_port_range"
    private const val DISCOVERY_TIMEOUT_MS = 10 * 60_000L
    private const val PAIRING_FALLBACK_TIMEOUT_MS = 5_000L

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val operations = Mutex()
    private val lifetime = Any()
    private var current: WirelessDisplayStream? = null
    private var discoveryJob: Job? = null

    private val _status = MutableStateFlow<WirelessStatus>(WirelessStatus.NotPaired)
    internal val status: StateFlow<WirelessStatus> = _status.asStateFlow()

    private val _pairingDiscovery = MutableStateFlow<PairingDiscovery>(PairingDiscovery.Idle)
    internal val pairingDiscovery: StateFlow<PairingDiscovery> = _pairingDiscovery.asStateFlow()

    private val _scanningPorts = MutableStateFlow(false)
    internal val scanningPorts: StateFlow<Boolean> = _scanningPorts.asStateFlow()

    internal fun loopback(port: Int): InetSocketAddress {
        require(port in 1..65535)
        return InetSocketAddress(InetAddress.getByAddress(byteArrayOf(127, 0, 0, 1)), port)
    }

    private fun marker(context: Context) = File(context.applicationContext.noBackupFilesDir, "hands-wireless-paired")
    fun hasIdentity(context: Context): Boolean = marker(context).isFile

    private fun portCache(context: Context): PortCache {
        val prefs = context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        return object : PortCache {
            override fun load(): Int? = prefs.getInt(KEY_LAST_PORT, -1).takeIf { it in 1..65535 }
            override fun save(port: Int) { prefs.edit().putInt(KEY_LAST_PORT, port).apply() }
            override fun clear() { prefs.edit().remove(KEY_LAST_PORT).apply() }
        }
    }

    @SuppressLint("PrivateApi")
    private fun readTlsPortProperty(): Int? = runCatching {
        Class.forName("android.os.SystemProperties")
            .getMethod("get", String::class.java)
            .invoke(null, TLS_PORT_PROPERTY) as? String
    }.getOrNull()?.trim()?.toIntOrNull()?.takeIf { it in 1..65535 }

    private fun readEphemeralPortRange(): IntRange =
        LocalPortScan.parseRange(runCatching { File(PORT_RANGE_FILE).readText() }.getOrNull())

    /** Reconciles [status] with current bridge readiness, pairing marker and wireless debugging toggle. */
    internal fun refreshState(context: Context) {
        val app = context.applicationContext
        if (HandsDisplayBridge.isReady()) {
            _status.value = WirelessStatus.Running
            return
        }
        val cur = _status.value
        if (cur == WirelessStatus.Connecting) return
        if (!hasIdentity(app)) {
            if (cur !is WirelessStatus.Failed || !cur.reason.duringPairing) {
                _status.value = WirelessStatus.NotPaired
            }
            return
        }
        val wirelessOn = DeveloperSettings.wirelessDebugging(app.contentResolver)
        if (wirelessOn == false) {
            _status.value = WirelessStatus.WirelessDebuggingOff
        } else if (cur == WirelessStatus.Running || cur == WirelessStatus.NotPaired) {
            _status.value = WirelessStatus.WirelessDebuggingOff
        }
    }

    /** Starts or restarts background mDNS discovery for the system pairing dialog port. */
    internal fun startDiscovery(context: Context) {
        val app = context.applicationContext
        synchronized(this) {
            discoveryJob?.cancel()
            _pairingDiscovery.value = PairingDiscovery.Searching
            discoveryJob = scope.launch {
                val port = withContext(Dispatchers.IO) {
                    runCatching {
                        NsdAdbServiceFinder(app).findFirstPort(AdbServiceTypes.PAIRING, DISCOVERY_TIMEOUT_MS)
                    }.getOrNull()
                }
                _pairingDiscovery.value = port?.let { PairingDiscovery.Found(it) } ?: PairingDiscovery.Idle
                Log.i(TAG, if (port != null) "found pairing window on port $port" else "no pairing window found")
            }
        }
    }

    internal fun stopDiscovery() {
        synchronized(this) {
            discoveryJob?.cancel()
            discoveryJob = null
        }
        _pairingDiscovery.value = PairingDiscovery.Idle
    }

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

    /**
     * Pairs using [code] and [port] (falling back to mDNS discovery when [port] is null),
     * then immediately connects and starts the background display helper.
     * Results are published through [status]; never logs the pairing code.
     */
    internal suspend fun startPairing(context: Context, code: String, port: Int? = null) {
        val app = context.applicationContext
        _status.value = WirelessStatus.Connecting
        val discoveredPort = (_pairingDiscovery.value as? PairingDiscovery.Found)?.port
        val target = port
            ?: discoveredPort
            ?: withContext(Dispatchers.IO) {
                runCatching {
                    NsdAdbServiceFinder(app).findFirstPort(AdbServiceTypes.PAIRING, PAIRING_FALLBACK_TIMEOUT_MS)
                }.getOrNull()
            }
        if (target == null) {
            _status.value = WirelessStatus.Failed(WirelessFailure.PairingWindowClosed)
            return
        }
        val failure = try {
            pair(app, target, code)
            null
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (e: AdbPairingException) {
            if (port == null && e.reason == AdbPairingException.Reason.CONNECT_FAILED) {
                val freshPort = withContext(Dispatchers.IO) {
                    runCatching {
                        NsdAdbServiceFinder(app).findFirstPort(AdbServiceTypes.PAIRING, PAIRING_FALLBACK_TIMEOUT_MS)
                    }.getOrNull()
                }
                if (freshPort != null && freshPort != target) {
                    _pairingDiscovery.value = PairingDiscovery.Found(freshPort)
                    try {
                        pair(app, freshPort, code)
                        null
                    } catch (retryCancelled: CancellationException) {
                        throw retryCancelled
                    } catch (retryErr: AdbPairingException) {
                        mapPairingFailure(retryErr.reason)
                    } catch (_: Exception) {
                        WirelessFailure.Unknown
                    }
                } else {
                    mapPairingFailure(e.reason)
                }
            } else {
                mapPairingFailure(e.reason)
            }
        } catch (_: Exception) {
            WirelessFailure.Unknown
        }
        if (failure != null) {
            _status.value = WirelessStatus.Failed(failure)
            return
        }
        stopDiscovery()
        connectAndActivate(app, manualPort = null)
    }

    /** Connects using all port sources (or an explicit [manualPort]) and updates [status]. */
    internal suspend fun connectAndActivate(context: Context, manualPort: Int? = null) {
        val app = context.applicationContext
        if (!hasIdentity(app)) {
            _status.value = WirelessStatus.NotPaired
            return
        }
        if (HandsDisplayBridge.isReady()) {
            _status.value = WirelessStatus.Running
            return
        }
        _status.value = WirelessStatus.Connecting
        val finder = NsdAdbServiceFinder(app)
        val scanner = LocalPortScan(
            scanner = NioLoopbackPortScanner(),
            range = ::readEphemeralPortRange,
        )
        val connector = AdbConnectPort(
            property = ::readTlsPortProperty,
            finder = finder,
            cache = portCache(app),
            scan = scanner,
            manual = { manualPort },
            scanning = { _scanningPorts.value = it },
        )
        try {
            connector.connect { port ->
                activate(app, port)
            }
            _status.value = WirelessStatus.Running
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (e: AdbConnectionException) {
            val failure = mapConnectionFailure(e.reason, DeveloperSettings.wifiConnected(app))
            _status.value = WirelessStatus.Failed(failure)
        } catch (_: Exception) {
            val failure = if (!DeveloperSettings.wifiConnected(app)) WirelessFailure.NoWifi else WirelessFailure.ConnectFailed
            _status.value = WirelessStatus.Failed(failure)
        }
    }

    internal suspend fun retry(context: Context) {
        connectAndActivate(context, manualPort = null)
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
                            if (current === stream) {
                                stop()
                                if (_status.value == WirelessStatus.Running) {
                                    _status.value = if (hasIdentity(context)) {
                                        WirelessStatus.WirelessDebuggingOff
                                    } else {
                                        WirelessStatus.NotPaired
                                    }
                                }
                            }
                        }
                    }
                }
                val connected = withTimeoutOrNull(12_000) {
                    while (!HandsDisplayBridge.isReady()) {
                        if (synchronized(lifetime) { current !== stream }) {
                            throw AdbConnectionException(
                                AdbConnectionException.Reason.HELPER_START_FAILED,
                                "The display helper disconnected",
                            )
                        }
                        delay(80)
                    }
                    true
                }
                currentCoroutineContext().ensureActive()
                if (connected != true) {
                    throw AdbConnectionException(
                        AdbConnectionException.Reason.HELPER_START_FAILED,
                        "The display helper did not connect",
                    )
                }
            } catch (cause: Throwable) {
                stop()
                throw cause
            }
        }
    }

    /** Reconnect using cached port, system property, mDNS candidates, or loopback scan. */
    suspend fun reconnect(context: Context): Boolean {
        if (HandsDisplayBridge.isReady()) {
            _status.value = WirelessStatus.Running
            return true
        }
        if (!hasIdentity(context)) return false
        return withTimeoutOrNull(18_000L) {
            try {
                connectAndActivate(context, manualPort = null)
                HandsDisplayBridge.isReady()
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
        stopDiscovery()
        operations.withLock {
            stop()
            portCache(context).clear()
            AdbIdentity.forget()
            val paired = marker(context)
            check(!paired.exists() || paired.delete()) { "Could not clear the pairing record" }
            _status.value = WirelessStatus.NotPaired
        }
    }

    internal fun mapPairingFailure(reason: AdbPairingException.Reason): WirelessFailure = when (reason) {
        AdbPairingException.Reason.WRONG_CODE -> WirelessFailure.WrongCode
        AdbPairingException.Reason.CONNECT_FAILED -> WirelessFailure.PairingWindowClosed
        AdbPairingException.Reason.TLS_FAILED, AdbPairingException.Reason.PROTOCOL -> WirelessFailure.Unknown
    }

    internal fun mapConnectionFailure(reason: AdbConnectionException.Reason, wifiConnected: Boolean): WirelessFailure = when (reason) {
        AdbConnectionException.Reason.UNAUTHORIZED -> WirelessFailure.AuthorizationRevoked
        AdbConnectionException.Reason.HELPER_START_FAILED -> WirelessFailure.HelperStartFailed
        AdbConnectionException.Reason.CONNECT_FAILED, AdbConnectionException.Reason.TLS_FAILED ->
            if (!wifiConnected) WirelessFailure.NoWifi else WirelessFailure.ConnectFailed
    }
}
