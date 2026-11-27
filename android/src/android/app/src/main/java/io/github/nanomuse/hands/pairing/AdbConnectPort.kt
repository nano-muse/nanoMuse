// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 wangzan101 (Mika). Adapted for nanoMuse local wireless pairing.
package io.github.nanomuse.hands.pairing

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.withContext
import java.io.DataInputStream
import java.io.IOException
import java.net.InetSocketAddress
import java.net.Socket
import java.nio.channels.SelectionKey
import java.nio.channels.Selector
import java.nio.channels.SocketChannel
import java.util.TreeSet

internal class AdbConnectionException(
    val reason: Reason,
    message: String,
    cause: Throwable? = null,
) : IOException(message, cause) {
    enum class Reason {
        CONNECT_FAILED,
        TLS_FAILED,
        UNAUTHORIZED,
        HELPER_START_FAILED,
    }
}

/** Persists the last working local wireless debugging port in app-private storage. */
internal interface PortCache {
    fun load(): Int?
    fun save(port: Int)
    fun clear()
}

/** Low-level loopback port probing for [LocalPortScan]; replaceable in unit tests. */
internal interface LocalPortScanner {
    suspend fun openPorts(ports: IntRange, skip: Set<Int>, budgetMs: Long): List<Int>
    fun speaksAdbTls(port: Int, timeoutMs: Int): Boolean
}

internal data class ScanResult(val ports: List<Int>, val open: Int, val adb: Int)

/**
 * Last-resort port finder when cache, system property and mDNS do not yield a working port.
 * Scans only loopback (127.0.0.1) in the local ephemeral port range and probes open ports with
 * an ADB CNXN banner, accepting only ports that reply with STLS.
 */
internal class LocalPortScan(
    private val scanner: LocalPortScanner,
    private val range: () -> IntRange = { FALLBACK_RANGE },
    private val budgetMs: Long = 10_000,
    private val probeTimeoutMs: Int = 1_000,
    private val now: () -> Long = System::currentTimeMillis,
) {
    suspend fun scan(skip: Set<Int>): ScanResult {
        val deadline = now() + budgetMs
        val ports = range()
        val found = ArrayList<Int>()
        val left = deadline - now()
        if (left <= 0) return ScanResult(emptyList(), 0, 0)
        val openPorts = scanner.openPorts(ports, skip, left)
        for (port in openPorts) {
            if (now() >= deadline) break
            if (scanner.speaksAdbTls(port, probeTimeoutMs)) found += port
        }
        return ScanResult(found, openPorts.size, found.size)
    }

    companion object {
        val FALLBACK_RANGE = 30_000..65_535

        fun parseRange(text: String?): IntRange {
            val nums = text?.trim()?.split(Regex("\\s+"))?.mapNotNull { it.toIntOrNull() } ?: return FALLBACK_RANGE
            if (nums.size != 2) return FALLBACK_RANGE
            val (lo, hi) = nums
            return if (lo in 1024..65_535 && hi in lo..65_535) lo..hi else FALLBACK_RANGE
        }
    }
}

/** Non-blocking loopback-only NIO port scanner for local wireless debugging discovery. */
internal class NioLoopbackPortScanner(
    private val concurrency: Int = 200,
    private val connectTimeoutMs: Long = 150,
) : LocalPortScanner {
    override suspend fun openPorts(ports: IntRange, skip: Set<Int>, budgetMs: Long): List<Int> = withContext(Dispatchers.IO) {
        val ctx = currentCoroutineContext()
        sweep(ports, skip, System.currentTimeMillis() + budgetMs) { ctx.isActive }
    }

    private fun sweep(ports: IntRange, skip: Set<Int>, deadline: Long, active: () -> Boolean): List<Int> {
        val open = TreeSet<Int>()
        val next = ports.iterator()
        Selector.open().use { selector ->
            val startedAt = HashMap<SelectionKey, Long>()
            try {
                while ((next.hasNext() || startedAt.isNotEmpty()) && System.currentTimeMillis() < deadline && active()) {
                    while (next.hasNext() && startedAt.size < concurrency) {
                        val port = next.nextInt()
                        if (port in skip) continue
                        val ch = SocketChannel.open()
                        try {
                            ch.configureBlocking(false)
                            val target = HandsWireless.loopback(port)
                            if (ch.connect(target)) {
                                if (!selfConnected(ch, port)) open += port
                                ch.close()
                            } else {
                                startedAt[ch.register(selector, SelectionKey.OP_CONNECT, port)] = System.currentTimeMillis()
                            }
                        } catch (_: IOException) {
                            ch.close()
                        }
                    }
                    selector.select(SELECT_MS)
                    for (key in selector.selectedKeys()) {
                        val ch = key.channel() as SocketChannel
                        val ok = try { ch.finishConnect() } catch (_: IOException) { false }
                        val port = key.attachment() as Int
                        if (ok && !selfConnected(ch, port)) open += port
                        startedAt.remove(key)
                        key.cancel()
                        ch.close()
                    }
                    selector.selectedKeys().clear()
                    val t = System.currentTimeMillis()
                    val late = startedAt.filterValues { t - it > connectTimeoutMs }.keys
                    for (key in late) {
                        startedAt.remove(key)
                        key.cancel()
                        key.channel().close()
                    }
                }
            } finally {
                for (key in startedAt.keys) runCatching { key.channel().close() }
            }
        }
        return open.toList()
    }

    private fun selfConnected(ch: SocketChannel, port: Int): Boolean = runCatching {
        val s = ch.socket()
        s.localPort == port && s.localAddress == s.inetAddress
    }.getOrDefault(false)

    override fun speaksAdbTls(port: Int, timeoutMs: Int): Boolean = try {
        val target = HandsWireless.loopback(port)
        Socket().use { s ->
            s.connect(target, timeoutMs)
            if (s.localPort == port && s.localAddress == s.inetAddress) return false
            s.soTimeout = timeoutMs
            s.getOutputStream().apply {
                write(AdbMessage(AdbMessage.CNXN, AdbMessage.VERSION, MAX_PROBE_PAYLOAD, HOST_BANNER).encode())
                flush()
            }
            AdbMessage.read(DataInputStream(s.getInputStream()), maxData = 4096)?.command == AdbMessage.STLS
        }
    } catch (e: CancellationException) {
        throw e
    } catch (_: Exception) {
        false
    }

    private companion object {
        const val SELECT_MS = 20L
        const val MAX_PROBE_PAYLOAD = 64 * 1024
        val HOST_BANNER = "host::\u0000".toByteArray(Charsets.US_ASCII)
    }
}

/**
 * Finds the local wireless debugging connection port and connects in priority order:
 * cached last port -> system property (service.adb.tls.port) -> all mDNS candidates ->
 * optional loopback scan -> manual port.
 *
 * Retries a port once after [tlsRetryDelayMs] when TLS handshake/auth is rejected, since some
 * devices let another handler intercept the first TLS attempt on the port.
 */
internal class AdbConnectPort(
    private val property: () -> Int?,
    private val finder: AdbServiceFinder,
    private val cache: PortCache,
    private val mdnsTimeoutMs: Long = 3_000,
    private val scan: LocalPortScan? = null,
    private val manual: () -> Int? = { null },
    private val scanning: (Boolean) -> Unit = {},
    private val tlsRetryDelayMs: Long = 300,
) {
    suspend fun <T> connect(open: suspend (port: Int) -> T): T {
        val tried = HashSet<Int>()
        var last: AdbConnectionException? = null
        var rejected: AdbConnectionException? = null
        val manualPort = manual()?.takeIf { it in 1..65535 }

        val sources: List<suspend () -> List<Int>> = if (manualPort != null) {
            listOf { listOf(manualPort) }
        } else {
            listOf(
                { listOfNotNull(cache.load()) },
                { listOfNotNull(property()) },
                { finder.findPorts(AdbServiceTypes.CONNECT, mdnsTimeoutMs) },
                {
                    if (scan == null || rejected != null) {
                        emptyList()
                    } else {
                        scanning(true)
                        try {
                            scan.scan(tried).ports
                        } finally {
                            scanning(false)
                        }
                    }
                },
            )
        }

        for (source in sources) {
            val ports = try {
                source()
            } catch (e: CancellationException) {
                throw e
            } catch (_: Exception) {
                emptyList()
            }
            for (port in ports) {
                if (port !in 1..65535 || !tried.add(port)) continue
                var retried = false
                while (true) {
                    try {
                        return open(port).also { cache.save(port) }
                    } catch (e: CancellationException) {
                        throw e
                    } catch (e: AdbConnectionException) {
                        val tls = e.reason == AdbConnectionException.Reason.UNAUTHORIZED ||
                            e.reason == AdbConnectionException.Reason.TLS_FAILED
                        if (tls && !retried) {
                            retried = true
                            delay(tlsRetryDelayMs)
                            continue
                        }
                        if (e.reason == AdbConnectionException.Reason.UNAUTHORIZED) rejected = e
                        last = e
                        break
                    }
                }
            }
        }
        throw rejected ?: last ?: AdbConnectionException(
            AdbConnectionException.Reason.CONNECT_FAILED,
            "No local wireless debugging port found",
        )
    }
}
