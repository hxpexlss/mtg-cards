package de.mtgcards.scanner

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.URL
import java.security.KeyStore
import java.security.MessageDigest
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import javax.net.ssl.HostnameVerifier
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.TrustManagerFactory
import javax.net.ssl.X509TrustManager

/**
 * HTTPS mit selbstsigniertem Zertifikat: Der Fingerabdruck wird beim ersten Verbinden bestätigt
 * und danach bei jeder Verbindung geprüft (Zertifikats-Pinning). Normale, gültige Zertifikate
 * (z.B. von "tailscale cert") funktionieren ohne Pinning.
 */
object Tls {
    fun fingerprint(cert: X509Certificate): String =
        MessageDigest.getInstance("SHA-256").digest(cert.encoded).joinToString(":") { "%02X".format(it) }

    fun normalize(fp: String) = fp.replace(":", "").replace(" ", "").uppercase()

    private val systemTrust: X509TrustManager by lazy {
        val tmf = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm())
        tmf.init(null as KeyStore?)
        tmf.trustManagers.first { it is X509TrustManager } as X509TrustManager
    }

    private class PinningTrustManager(private val pin: String) : X509TrustManager {
        override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) {
            throw CertificateException("Client-Zertifikate werden nicht unterstützt")
        }

        override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {
            if (pin.isNotBlank() && chain.isNotEmpty() && normalize(fingerprint(chain[0])) == normalize(pin)) return
            systemTrust.checkServerTrusted(chain, authType)
        }

        override fun getAcceptedIssuers(): Array<X509Certificate> = systemTrust.acceptedIssuers
    }

    /** Richtet eine HTTPS-Verbindung mit optionalem Pinning ein. */
    fun configure(conn: HttpsURLConnection, pin: String) {
        if (pin.isBlank()) return
        val ctx = SSLContext.getInstance("TLS")
        ctx.init(null, arrayOf(PinningTrustManager(pin)), null)
        conn.sslSocketFactory = ctx.socketFactory
        val default = HttpsURLConnection.getDefaultHostnameVerifier()
        conn.hostnameVerifier = HostnameVerifier { host, session ->
            val leaf = session.peerCertificates.firstOrNull() as? X509Certificate
            (leaf != null && normalize(fingerprint(leaf)) == normalize(pin)) || default.verify(host, session)
        }
    }

    /** Liest den Fingerabdruck eines Servers, ohne ihm zu vertrauen (nur zur Anzeige / Bestätigung). */
    suspend fun fetchFingerprint(url: String): String = withContext(Dispatchers.IO) {
        var seen: X509Certificate? = null
        val capture = object : X509TrustManager {
            override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) {
                throw CertificateException()
            }
            override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {
                seen = chain.firstOrNull()
                throw CertificateException("nur Fingerabdruck lesen")
            }
            override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
        }
        val ctx = SSLContext.getInstance("TLS")
        ctx.init(null, arrayOf(capture), null)
        val conn = URL("$url/api/health").openConnection() as HttpsURLConnection
        conn.sslSocketFactory = ctx.socketFactory
        conn.connectTimeout = 5000
        try {
            conn.connect()
        } catch (_: Exception) {
            // erwartet: Handshake wird nach dem Lesen des Zertifikats abgebrochen
        } finally {
            conn.disconnect()
        }
        seen?.let { fingerprint(it) } ?: throw ApiException("Zertifikat konnte nicht gelesen werden", Api.UNREACHABLE)
    }
}
