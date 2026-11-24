package io.github.nanomuse.hands.pairing

import io.github.nanomuse.hands.HandsDisplayActivation
import java.io.Closeable
import java.io.DataInputStream
import java.io.EOFException
import java.io.IOException
import java.net.Socket
import javax.net.ssl.SSLException
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

    private fun read() = AdbMessage.read(input, MAX_PACKET) ?: throw EOFException("Local debugging disconnected")

    private fun start(activation: HandsDisplayActivation) {
        val cnxn = try {
            read()
        } catch (e: SSLException) {
            throw AdbConnectionException(AdbConnectionException.Reason.UNAUTHORIZED, "Wireless debugging rejected the saved key", e)
        } catch (e: IOException) {
            throw AdbConnectionException(AdbConnectionException.Reason.UNAUTHORIZED, "Debugging connection was not authorized", e)
        }
        if (cnxn.command != AdbMessage.CNXN) {
            throw AdbConnectionException(AdbConnectionException.Reason.UNAUTHORIZED, "Debugging connection was not authorized")
        }
        val endpoint = ("exec:" + activation.command + "\u0000").toByteArray(Charsets.UTF_8)
        try {
            write(AdbMessage.OPEN, LOCAL_ID, 0, endpoint)
            val opened = read()
            if (opened.command != AdbMessage.OKAY || opened.arg1 != LOCAL_ID || opened.arg0 == 0) {
                throw AdbConnectionException(
                    AdbConnectionException.Reason.HELPER_START_FAILED,
                    "The phone refused to start the background screen",
                )
            }
            remoteId = opened.arg0
            write(AdbMessage.WRTE, LOCAL_ID, remoteId, (activation.nonce + "\n").toByteArray(Charsets.US_ASCII))
            socket.soTimeout = 0
        } catch (e: AdbConnectionException) {
            throw e
        } catch (e: IOException) {
            throw AdbConnectionException(
                AdbConnectionException.Reason.HELPER_START_FAILED,
                "The background screen helper could not start",
                e,
            )
        }
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
                try {
                    plain.connect(target, 5_000)
                    plain.soTimeout = 8_000
                    val out = plain.getOutputStream()
                    out.write(AdbMessage(AdbMessage.CNXN, AdbMessage.VERSION, MAX_PACKET, "host::\u0000".toByteArray()).encode())
                    out.flush()
                    val upgrade = AdbMessage.read(DataInputStream(plain.getInputStream()), MAX_PACKET)
                    if (upgrade?.command != AdbMessage.STLS) {
                        throw AdbConnectionException(
                            AdbConnectionException.Reason.CONNECT_FAILED,
                            "This port does not offer wireless debugging TLS",
                        )
                    }
                    out.write(AdbMessage(AdbMessage.STLS, AdbMessage.STLS_VERSION, 0).encode())
                    out.flush()
                } catch (e: AdbConnectionException) {
                    throw e
                } catch (e: IOException) {
                    throw AdbConnectionException(
                        AdbConnectionException.Reason.CONNECT_FAILED,
                        "Cannot connect to local wireless debugging port",
                        e,
                    )
                }
                val ssl = try {
                    tls.wrap(plain, target)
                } catch (e: SSLException) {
                    throw AdbConnectionException(
                        AdbConnectionException.Reason.TLS_FAILED,
                        "Wireless debugging TLS handshake failed",
                        e,
                    )
                } catch (e: IOException) {
                    throw AdbConnectionException(
                        AdbConnectionException.Reason.CONNECT_FAILED,
                        "Wireless debugging TLS connection interrupted",
                        e,
                    )
                }
                return WirelessDisplayStream(ssl).also { it.start(activation) }
            } catch (cause: Throwable) {
                runCatching { plain.close() }
                throw cause
            }
        }
    }
}
