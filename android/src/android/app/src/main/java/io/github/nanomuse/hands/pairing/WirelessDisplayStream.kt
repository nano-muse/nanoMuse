package io.github.nanomuse.hands.pairing

import io.github.nanomuse.hands.HandsDisplayActivation
import java.io.Closeable
import java.io.DataInputStream
import java.io.IOException
import java.net.Socket
import javax.net.ssl.SSLSocket

/** One authenticated ADB stream. Its only service starts our bundled, display-only helper. */
internal class WirelessDisplayStream private constructor(private val socket: SSLSocket) : Closeable {
    private val input = DataInputStream(socket.inputStream)
    private val output = socket.outputStream
    private var remoteId = 0

    private fun write(command: Int, arg0: Int, arg1: Int, payload: ByteArray = byteArrayOf()) {
        output.write(AdbMessage(command, arg0, arg1, payload).encode())
        output.flush()
    }

    private fun read() = AdbMessage.read(input, MAX_PACKET) ?: throw IOException("Local debugging disconnected")

    private fun start(activation: HandsDisplayActivation) {
        if (read().command != AdbMessage.CNXN) throw IOException("Debugging connection was not authorized")
        val endpoint = ("exec:" + activation.command + "\u0000").toByteArray(Charsets.UTF_8)
        write(AdbMessage.OPEN, LOCAL_ID, 0, endpoint)
        val opened = read()
        if (opened.command != AdbMessage.OKAY || opened.arg1 != LOCAL_ID || opened.arg0 == 0) {
            throw IOException("The phone refused to start the background screen")
        }
        remoteId = opened.arg0
        write(AdbMessage.WRTE, LOCAL_ID, remoteId, (activation.nonce + "\n").toByteArray(Charsets.US_ASCII))
        socket.soTimeout = 0
    }

    /** Stop on revocation, EOF, or any unexpected stream. Never retain diagnostic output. */
    fun awaitDisconnect() {
        while (true) {
            val packet = read()
            if (packet.arg1 != LOCAL_ID || packet.arg0 != remoteId) return
            when (packet.command) {
                AdbMessage.OKAY -> Unit
                AdbMessage.WRTE -> write(AdbMessage.OKAY, LOCAL_ID, remoteId)
                else -> return
            }
        }
    }

    override fun close() { socket.close() }

    companion object {
        private const val LOCAL_ID = 1
        private const val MAX_PACKET = 64 * 1024

        fun open(port: Int, tls: AdbTls, activation: HandsDisplayActivation): WirelessDisplayStream {
            val target = HandsWireless.loopback(port)
            val plain = Socket()
            try {
                plain.connect(target, 5_000)
                plain.soTimeout = 8_000
                val out = plain.getOutputStream()
                out.write(AdbMessage(AdbMessage.CNXN, AdbMessage.VERSION, MAX_PACKET, "host::\u0000".toByteArray()).encode())
                out.flush()
                val upgrade = AdbMessage.read(DataInputStream(plain.getInputStream()), MAX_PACKET)
                if (upgrade?.command != AdbMessage.STLS) throw IOException("This port does not offer wireless debugging TLS")
                out.write(AdbMessage(AdbMessage.STLS, AdbMessage.STLS_VERSION, 0).encode())
                out.flush()
                val ssl = tls.wrap(plain, target)
                return WirelessDisplayStream(ssl).also { it.start(activation) }
            } catch (cause: Throwable) {
                plain.close()
                throw cause
            }
        }
    }
}
