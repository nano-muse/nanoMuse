// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 wangzan101 (Mika). Adapted for nanoMuse background screen wireless setup.
package io.github.nanomuse.hands.pairing

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AdbConnectPortTest {
    private class MemoryPortCache(var port: Int? = null) : PortCache {
        override fun load(): Int? = port
        override fun save(port: Int) { this.port = port }
        override fun clear() { port = null }
    }

    @Test
    fun triesCachePropertyMdnsScanInOrderAndSavesWinningPort() = runBlocking {
        val tried = mutableListOf<Int>()
        val cache = MemoryPortCache(37001)
        val scanner = object : LocalPortScanner {
            override suspend fun openPorts(ports: IntRange, skip: Set<Int>, budgetMs: Long): List<Int> =
                listOf(37005, 37006).filterNot { it in skip }

            override fun speaksAdbTls(port: Int, timeoutMs: Int): Boolean = port == 37006
        }
        val scanningEvents = mutableListOf<Boolean>()
        val connector = AdbConnectPort(
            property = { 37002 },
            finder = AdbServiceFinder { _, _ -> listOf(37003, 37004) },
            cache = cache,
            scan = LocalPortScan(scanner, range = { 37000..37010 }),
            scanning = { scanningEvents += it },
            tlsRetryDelayMs = 1L,
        )

        val chosen = connector.connect { port ->
            tried += port
            if (port != 37006) {
                throw AdbConnectionException(AdbConnectionException.Reason.CONNECT_FAILED, "closed")
            }
            port
        }

        assertEquals(37006, chosen)
        assertEquals(listOf(37001, 37002, 37003, 37004, 37006), tried)
        assertEquals(37006, cache.port)
        assertEquals(listOf(true, false), scanningEvents)
    }

    @Test
    fun retriesTlsRejectionOnceBeforeGivingUpAndSkipsScanWhenUnauthorized() = runBlocking {
        var attempts = 0
        var scanned = false
        val connector = AdbConnectPort(
            property = { 37100 },
            finder = AdbServiceFinder { _, _ -> emptyList() },
            cache = MemoryPortCache(),
            scan = LocalPortScan(
                object : LocalPortScanner {
                    override suspend fun openPorts(ports: IntRange, skip: Set<Int>, budgetMs: Long): List<Int> {
                        scanned = true
                        return emptyList()
                    }
                    override fun speaksAdbTls(port: Int, timeoutMs: Int): Boolean = false
                },
            ),
            tlsRetryDelayMs = 1L,
        )

        val result = connector.connect { port ->
            attempts++
            if (attempts == 1) {
                throw AdbConnectionException(AdbConnectionException.Reason.TLS_FAILED, "transient")
            }
            port
        }
        assertEquals(37100, result)
        assertEquals(2, attempts)
        assertFalse(scanned)
    }

    @Test
    fun throwsUnauthorizedOverLaterConnectErrorsAndSkipsScan() = runBlocking {
        var scanned = false
        val connector = AdbConnectPort(
            property = { 37100 },
            finder = AdbServiceFinder { _, _ -> listOf(37101) },
            cache = MemoryPortCache(),
            scan = LocalPortScan(
                object : LocalPortScanner {
                    override suspend fun openPorts(ports: IntRange, skip: Set<Int>, budgetMs: Long): List<Int> {
                        scanned = true
                        return listOf(37102)
                    }
                    override fun speaksAdbTls(port: Int, timeoutMs: Int): Boolean = true
                },
            ),
            tlsRetryDelayMs = 1L,
        )

        val thrown = runCatching {
            connector.connect { port ->
                if (port == 37100) {
                    throw AdbConnectionException(AdbConnectionException.Reason.UNAUTHORIZED, "revoked")
                }
                throw AdbConnectionException(AdbConnectionException.Reason.CONNECT_FAILED, "closed")
            }
        }.exceptionOrNull() as AdbConnectionException

        assertEquals(AdbConnectionException.Reason.UNAUTHORIZED, thrown.reason)
        assertFalse(scanned)
    }

    @Test
    fun manualPortBypassesDiscoveryAndScan() = runBlocking {
        var mDnsCalled = false
        val cache = MemoryPortCache(37001)
        val connector = AdbConnectPort(
            property = { 37002 },
            finder = AdbServiceFinder { _, _ -> mDnsCalled = true; listOf(37003) },
            cache = cache,
            manual = { 39999 },
            tlsRetryDelayMs = 1L,
        )

        val port = connector.connect { it }
        assertEquals(39999, port)
        assertFalse(mDnsCalled)
        assertEquals(39999, cache.port)
    }

    @Test
    fun parsesProcEphemeralPortRangeSafely() {
        assertEquals(32768..60999, LocalPortScan.parseRange("32768\t60999\n"))
        assertEquals(LocalPortScan.FALLBACK_RANGE, LocalPortScan.parseRange("bad"))
        assertEquals(LocalPortScan.FALLBACK_RANGE, LocalPortScan.parseRange("80 100"))
        assertTrue(LocalPortScan.FALLBACK_RANGE.first >= 1024)
    }
}
