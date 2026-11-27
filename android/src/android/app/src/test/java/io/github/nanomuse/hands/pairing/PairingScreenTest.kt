// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 wangzan101 (Mika). Adapted for nanoMuse background screen wireless setup.
package io.github.nanomuse.hands.pairing

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class PairingScreenTest {
    @Test
    fun readsStandardPairingDialogTexts() {
        val reading = PairingScreen.read(
            listOf(
                "Pair with device",
                "Wi-Fi pairing code",
                "482913",
                "IP address & port",
                "192.168.1.42:37891",
                "Cancel",
            ),
        )
        assertEquals("482913", reading.code)
        assertEquals(37891, reading.port)
    }

    @Test
    fun readsSpacedCodeAndIpv6Port() {
        val reading = PairingScreen.read(
            listOf(
                "123 456",
                "[fe80::1a2b:3c4d%wlan0]:41234",
            ),
        )
        assertEquals("123456", reading.code)
        assertEquals(41234, reading.port)
    }

    @Test
    fun returnsNullOnAmbiguousCodesOrPorts() {
        val twoCodes = PairingScreen.read(listOf("111111", "222222", "192.168.0.2:37001"))
        assertNull(twoCodes.code)
        assertEquals(37001, twoCodes.port)

        val twoPorts = PairingScreen.read(listOf("654321", "192.168.0.2:37001", "192.168.0.2:37002"))
        assertEquals("654321", twoPorts.code)
        assertNull(twoPorts.port)
    }

    @Test
    fun rejectsOutOfRangeIpv4AndPorts() {
        val invalid = PairingScreen.read(listOf("999.168.1.1:37001", "192.168.1.1:70000", "192.168.1.1:0"))
        assertNull(invalid.code)
        assertNull(invalid.port)
    }

    @Test
    fun attemptRespectsWaitingStateTriedSetAndPortAvailability() {
        val readingWithPort = PairingScreenReading("482913", 37891)
        val readingCodeOnly = PairingScreenReading("482913", null)

        assertEquals(
            PairingAttempt("482913", 37891),
            PairingScreen.attempt(readingWithPort, portFound = false, status = WirelessStatus.NotPaired, tried = emptySet()),
        )
        assertNull(
            PairingScreen.attempt(readingCodeOnly, portFound = false, status = WirelessStatus.NotPaired, tried = emptySet()),
        )
        assertEquals(
            PairingAttempt("482913", null),
            PairingScreen.attempt(readingCodeOnly, portFound = true, status = WirelessStatus.NotPaired, tried = emptySet()),
        )
        assertNull(
            PairingScreen.attempt(readingWithPort, portFound = true, status = WirelessStatus.NotPaired, tried = setOf("482913")),
        )
        assertNull(
            PairingScreen.attempt(readingWithPort, portFound = true, status = WirelessStatus.Connecting, tried = emptySet()),
        )
        assertNull(
            PairingScreen.attempt(readingWithPort, portFound = true, status = WirelessStatus.Running, tried = emptySet()),
        )
        assertEquals(
            PairingAttempt("482913", 37891),
            PairingScreen.attempt(
                readingWithPort,
                portFound = false,
                status = WirelessStatus.Failed(WirelessFailure.WrongCode),
                tried = emptySet(),
            ),
        )
        assertEquals(
            PairingAttempt("482913", 37891),
            PairingScreen.attempt(
                readingWithPort,
                portFound = false,
                status = WirelessStatus.Failed(WirelessFailure.AuthorizationRevoked),
                tried = emptySet(),
            ),
        )
    }

    @Test
    fun normalizesPairingCodeAndParsesPorts() {
        assertEquals("482913", PairingCode.normalize(" 482-913 "))
        assertEquals("482913", PairingCode.normalize("４８２－９１３"))
        assertNull(PairingCode.normalize("48291"))
        assertNull(PairingCode.normalize("48291a"))

        assertEquals(37891, PairingCode.parseConnectPort("192.168.1.42:37891"))
        assertEquals(37891, PairingCode.parseConnectPort("192.168.1.42：３７８９１"))
        assertEquals(37891, PairingCode.parseConnectPort(" 37891 "))
        assertNull(PairingCode.parseConnectPort("192.168.1.42:70000"))

        assertEquals("482913" to null, PairingCode.parseReply("482 913"))
        assertEquals("482913" to 37891, PairingCode.parseReply("37891 482-913"))
        assertNull(PairingCode.parseReply("99999 482913"))
    }
}
