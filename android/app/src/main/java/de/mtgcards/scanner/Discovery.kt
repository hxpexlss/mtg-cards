package de.mtgcards.scanner

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONException
import org.json.JSONObject
import java.io.IOException
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.NetworkInterface
import java.net.SocketTimeoutException

data class FoundServer(
    val name: String, val address: String, val port: Int, val kind: String,
    val tls: Boolean = false, val fingerprint: String = "",
) {
    val url get() = "${if (tls) "https" else "http"}://$address:$port"
    val label get() = "$name (${if (kind == "server") "Server" else "PC"}) – $address:$port"
}

/** Findet MTG-Cards-Rechner im WLAN per UDP-Broadcast (nicht über Tailscale). */
object Discovery {
    private const val PORT = 47811
    private val MAGIC = "MTGCARDS_DISCOVER_V1".toByteArray()

    suspend fun discover(timeoutMs: Long = 2000): List<FoundServer> = withContext(Dispatchers.IO) {
        val result = LinkedHashMap<String, FoundServer>()
        DatagramSocket().use { socket ->
            socket.broadcast = true
            socket.soTimeout = 300
            val targets = mutableSetOf<InetAddress>(InetAddress.getByName("255.255.255.255"))
            targets.addAll(broadcastAddresses())
            repeat(2) {
                for (t in targets) {
                    try {
                        socket.send(DatagramPacket(MAGIC, MAGIC.size, t, PORT))
                    } catch (_: IOException) {
                    }
                }
            }
            val end = System.currentTimeMillis() + timeoutMs
            val buf = ByteArray(2048)
            while (System.currentTimeMillis() < end) {
                val packet = DatagramPacket(buf, buf.size)
                try {
                    socket.receive(packet)
                } catch (_: SocketTimeoutException) {
                    continue
                } catch (_: IOException) {
                    break
                }
                try {
                    val j = JSONObject(String(packet.data, 0, packet.length, Charsets.UTF_8))
                    if (j.optString("app") != "mtg-cards") continue
                    val addr = packet.address.hostAddress ?: continue
                    val port = j.optInt("port", Api.DEFAULT_PORT)
                    result["$addr:$port"] = FoundServer(
                        j.optString("name", addr), addr, port, j.optString("kind"),
                        j.optBoolean("tls"), if (j.isNull("fingerprint")) "" else j.optString("fingerprint"),
                    )
                } catch (_: JSONException) {
                }
            }
        }
        result.values.toList()
    }

    private fun broadcastAddresses(): List<InetAddress> = try {
        NetworkInterface.getNetworkInterfaces().toList()
            .filter { it.isUp && !it.isLoopback }
            .flatMap { it.interfaceAddresses }
            .mapNotNull { it.broadcast }
    } catch (_: Exception) {
        emptyList()
    }
}
