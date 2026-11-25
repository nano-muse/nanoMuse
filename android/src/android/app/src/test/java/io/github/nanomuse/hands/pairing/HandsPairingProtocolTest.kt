package io.github.nanomuse.hands.pairing

import java.io.ByteArrayInputStream
import java.io.DataInputStream
import java.io.IOException
import java.nio.ByteBuffer
import javax.crypto.AEADBadTagException
import org.junit.Assert.*
import org.junit.Test

class HandsPairingProtocolTest {
    // Interoperability vector from Mika's adb/spake2-vectors.txt, Apache-2.0.
    private fun bytes(hex: String) = hex.chunked(2).map { it.toInt(16).toByte() }.toByteArray()

    @Test fun clientMatchesAndroidPairingVector() {
        val client = PairingAuth.client(bytes("32363532333543c733885a3d925d056813df66ca344f584bfd964293f3df5a0b9167052474dde398d060254abcf40d4839936842d7c75fb5540a9107b7d9f04540dde3d2ebc2"), bytes("ae27b884a0b2f1809bb7f294f5ab3d5287be454dc3b45a0547c5b32645f0d33a3118ef09d0e950cf9a9afbb627a5ec990ab98c2e02d63ca5ad15a7225346fcc8"))
        assertArrayEquals(bytes("507f1708d35b116d592f2f9b20613cbd0bad6ba31057e90f648cd1a484bb6f33"), client.message)
        client.initCipher(bytes("98848b90a5e5b6da50385722057ab92674dcea0a616af47f5aedf1f7450fe3cb"))
        assertArrayEquals(bytes("99add9c6d77865c60c8affc3e635d8fcbb7fae6b1fe6cca32c9a58fb1cd2d2b77a0466f1cb050db0a8f42302fce2d052b632db7366"), client.encrypt(bytes("f9086b7b081ca7800d42e4f26954c59008c849903dd990c6187241da1bf14f5d1f13e150b4")))
    }

    @Test fun differentCodesCannotReadPeerInformation() {
        val client = PairingAuth.client("123456".toByteArray())
        val server = PairingAuth.server("654321".toByteArray())
        client.initCipher(server.message)
        server.initCipher(client.message)
        assertThrows(AEADBadTagException::class.java) { server.decrypt(client.encrypt(byteArrayOf(1))) }
    }

    @Test fun transportOnlyTargetsThisPhoneAndValidPorts() {
        for (port in listOf(1, 37001, 65535)) {
            val target = HandsWireless.loopback(port)
            assertTrue(target.address.isLoopbackAddress)
            assertEquals(port, target.port)
        }
        for (port in listOf(0, -1, 65536)) {
            assertThrows(IllegalArgumentException::class.java) { HandsWireless.loopback(port) }
        }
    }

    @Test fun rejectsOversizedPairingAndAdbFramesBeforeReadingPayload() {
        val badPairing = ByteBuffer.allocate(6).put(1).put(0).putInt(Int.MAX_VALUE).array()
        assertThrows(IOException::class.java) {
            AdbPairing.readPacket(DataInputStream(ByteArrayInputStream(badPairing)), AdbPairing.TYPE_SPAKE2)
        }
        val frame = AdbMessage(AdbMessage.CNXN, 0, 0, ByteArray(9)).encode()
        assertThrows(IOException::class.java) { AdbMessage.read(DataInputStream(ByteArrayInputStream(frame)), 8) }
    }
}
