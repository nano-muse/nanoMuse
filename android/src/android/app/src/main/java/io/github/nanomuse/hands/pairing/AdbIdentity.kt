// SPDX-License-Identifier: Apache-2.0
// ADB public key encoding adapted from Mika, Copyright 2026 wangzan101.
package io.github.nanomuse.hands.pairing

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.math.BigInteger
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.PrivateKey
import java.security.cert.X509Certificate
import java.security.interfaces.RSAPublicKey
import java.util.Base64
import java.util.Date
import javax.security.auth.x500.X500Principal

/** The Android Keystore signs the TLS handshake. The app only exports its public key. */
internal class AdbIdentity(val privateKey: PrivateKey, val certificate: X509Certificate) {
    val adbPublicKey: String get() {
        val key = certificate.publicKey as RSAPublicKey
        val n = key.modulus
        require(n.bitLength() == 2048)
        val r32 = BigInteger.ONE.shiftLeft(32)
        val rr = BigInteger.ONE.shiftLeft(4096).mod(n)
        val buffer = ByteBuffer.allocate(524).order(ByteOrder.LITTLE_ENDIAN)
        buffer.putInt(64).putInt(r32.subtract(n.modInverse(r32)).toInt())
        buffer.put(EdPoint.toLe(n, 256)).put(EdPoint.toLe(rr, 256)).putInt(key.publicExponent.toInt())
        return Base64.getEncoder().encodeToString(buffer.array()) + " nanoMuse"
    }

    companion object {
        private const val ALIAS = "nanomuse_hands_wireless_sign"
        private fun keyStore() = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }

        fun load(pairing: Boolean): AdbIdentity {
            val store = keyStore()
            if (!store.containsAlias(ALIAS)) {
                check(pairing) { "Pair this phone first" }
                val generator = KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_RSA, "AndroidKeyStore")
                generator.initialize(
                    KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY)
                        .setKeySize(2048)
                        .setDigests(KeyProperties.DIGEST_NONE, KeyProperties.DIGEST_SHA256, KeyProperties.DIGEST_SHA384, KeyProperties.DIGEST_SHA512)
                        // Conscrypt constructs the TLS signature padding, then uses a private
                        // RSA/NoPadding operation. The Keystore key still has sign/verify purposes only.
                        .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                        .setSignaturePaddings(KeyProperties.SIGNATURE_PADDING_RSA_PKCS1, KeyProperties.SIGNATURE_PADDING_RSA_PSS)
                        .setCertificateSubject(X500Principal("CN=nanoMuse"))
                        .setCertificateNotAfter(Date(4_102_444_800_000L))
                        .build()
                )
                generator.generateKeyPair()
            }
            return AdbIdentity(store.getKey(ALIAS, null) as PrivateKey, store.getCertificate(ALIAS) as X509Certificate)
        }

        fun forget() { keyStore().deleteEntry(ALIAS) }
    }
}
