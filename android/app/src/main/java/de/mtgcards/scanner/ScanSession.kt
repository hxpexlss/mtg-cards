package de.mtgcards.scanner

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

/** Eine in dieser Sitzung gescannte Karte (für Verlauf und Rückgängig). */
data class RecentScan(
    val cardId: Long,
    val name: String,
    val imageUrl: String?,
    var quantity: Int,
    val pending: Boolean = false,
)

/** Verlauf der aktuellen Scan-Sitzung (bleibt beim Tab-Wechsel erhalten). */
object ScanSession {
    val recent = mutableListOf<RecentScan>()
    var added = 0

    fun push(scan: RecentScan) {
        recent.removeAll { !it.pending && it.cardId == scan.cardId && scan.cardId != 0L }
        recent.add(0, scan)
        while (recent.size > 30) recent.removeAt(recent.size - 1)
    }
}

/** Scan, der wegen fehlender Verbindung noch nicht gesendet wurde. */
data class PendingScan(
    val name: String, val setCode: String?, val cn: String?, val foil: Boolean, val quantity: Int,
    val lang: String? = null,
    val proxy: Boolean = false,
)

/** Offline-Warteschlange, gespeichert in den SharedPreferences (übersteht Neustarts). */
object PendingQueue {
    fun all(ctx: Context): List<PendingScan> {
        val arr = try { JSONArray(Prefs.pendingJson(ctx)) } catch (e: Exception) { JSONArray() }
        return (0 until arr.length()).map { i ->
            val o = arr.getJSONObject(i)
            PendingScan(
                o.getString("name"),
                o.optString("set").ifBlank { null },
                o.optString("cn").ifBlank { null },
                o.optBoolean("foil"),
                o.optInt("quantity", 1),
                o.optString("lang").ifBlank { null },
                o.optBoolean("proxy"),
            )
        }
    }

    fun size(ctx: Context) = all(ctx).size

    fun add(ctx: Context, scan: PendingScan) = save(ctx, all(ctx) + scan)

    fun save(ctx: Context, list: List<PendingScan>) {
        val arr = JSONArray()
        for (p in list) {
            arr.put(JSONObject().apply {
                put("name", p.name)
                put("set", p.setCode ?: "")
                put("cn", p.cn ?: "")
                put("foil", p.foil)
                put("quantity", p.quantity)
                put("lang", p.lang ?: "")
                put("proxy", p.proxy)
            })
        }
        Prefs.setPendingJson(ctx, arr.toString())
    }
}
