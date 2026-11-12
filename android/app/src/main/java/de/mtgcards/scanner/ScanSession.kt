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
    val deckId: Long = 0L,
    /** Kennung der Speicher-Anfrage: Wird der Scan erneut gesendet, legt der Server die Karte nicht doppelt an. */
    val requestId: String = Api.newRequestId(),
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
                o.optLong("deck_id"),
                o.optString("request_id").ifBlank { Api.newRequestId() },
            )
        }
    }

    fun size(ctx: Context) = all(ctx).size

    fun add(ctx: Context, scan: PendingScan) = save(ctx, all(ctx) + scan)

    /** Entfernt genau diesen Scan (sofort gespeichert, damit nach einem Abbruch nichts doppelt gesendet wird). */
    fun remove(ctx: Context, scan: PendingScan) {
        val list = all(ctx).toMutableList()
        val i = list.indexOfFirst { it.requestId == scan.requestId }.takeIf { it >= 0 }
            ?: list.indexOfFirst { it.copy(requestId = scan.requestId) == scan }
        if (i >= 0) {
            list.removeAt(i)
            save(ctx, list)
        }
    }

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
                put("deck_id", p.deckId)
                put("request_id", p.requestId)
            })
        }
        Prefs.setPendingJson(ctx, arr.toString())
    }
}
