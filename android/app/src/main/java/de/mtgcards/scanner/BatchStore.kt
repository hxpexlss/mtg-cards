package de.mtgcards.scanner

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

/** Eine Karte im Stapel (noch nicht gespeichert). */
data class BatchItem(
    val scryfallId: String?,      // null = offline gescannt, wird beim Speichern per Name aufgelöst
    val name: String,
    val setCode: String?,
    val cn: String?,
    var quantity: Int,
    var foil: Boolean,
    val priceEur: Double?,
    val priceEurFoil: Double?,
    val imageUrl: String?,
    val lang: String? = null,
    val proxy: Boolean = false,
) {
    val unitPrice get() = if (proxy) null else if (foil) priceEurFoil ?: priceEur else priceEur ?: priceEurFoil
    val key get() = "${scryfallId ?: name.lowercase()}|$foil|$proxy"

    fun toJson() = JSONObject().apply {
        put("scryfall_id", scryfallId ?: "")
        put("name", name)
        put("set", setCode ?: "")
        put("cn", cn ?: "")
        put("quantity", quantity)
        put("foil", foil)
        put("price_eur", priceEur ?: JSONObject.NULL)
        put("price_eur_foil", priceEurFoil ?: JSONObject.NULL)
        put("image_url", imageUrl ?: "")
        put("lang", lang ?: "")
        put("proxy", proxy)
    }

    /** Für POST /api/cards/batch */
    fun toRequest() = JSONObject().apply {
        if (!scryfallId.isNullOrBlank()) put("scryfall_id", scryfallId) else {
            put("name", name)
            if (!setCode.isNullOrBlank()) put("set", setCode)
            if (!cn.isNullOrBlank()) put("cn", cn)
            if (!lang.isNullOrBlank()) put("lang", lang)
        }
        put("quantity", quantity)
        put("foil", foil)
        if (proxy) put("tags", JSONArray(listOf(PROXY_TAG)))
    }

    companion object {
        private fun price(o: JSONObject, k: String): Double? =
            if (o.isNull(k)) null else o.optString(k).replace(",", ".").toDoubleOrNull()

        fun fromJson(o: JSONObject) = BatchItem(
            o.optString("scryfall_id").ifBlank { null }, o.getString("name"),
            o.optString("set").ifBlank { null }, o.optString("cn").ifBlank { null },
            o.optInt("quantity", 1), o.optBoolean("foil"), price(o, "price_eur"), price(o, "price_eur_foil"),
            o.optString("image_url").ifBlank { null },
            o.optString("lang").ifBlank { null },
            o.optBoolean("proxy"),
        )

        /** Aus einer Scryfall-Karte vom Server (/api/lookup). */
        fun fromCard(card: JSONObject, foil: Boolean, proxy: Boolean = false) = BatchItem(
            card.optString("scryfall_id"), card.optString("name"), card.optString("set_code"),
            card.optString("collector_number"), 1, foil, price(card, "price_eur"), price(card, "price_eur_foil"),
            card.optString("image_url").ifBlank { null }, proxy = proxy,
        )
    }
}

/** Stapel der aktuellen Scan-Sitzung, gespeichert in den SharedPreferences (übersteht Neustarts). */
object BatchStore {
    private fun sp(ctx: Context) = ctx.getSharedPreferences("mtgcards", Context.MODE_PRIVATE)

    fun all(ctx: Context): MutableList<BatchItem> {
        val arr = try { JSONArray(sp(ctx).getString("batch", "[]")) } catch (e: Exception) { JSONArray() }
        return (0 until arr.length()).map { BatchItem.fromJson(arr.getJSONObject(it)) }.toMutableList()
    }

    fun save(ctx: Context, items: List<BatchItem>) {
        val arr = JSONArray()
        items.forEach { arr.put(it.toJson()) }
        sp(ctx).edit().putString("batch", arr.toString()).apply()
    }

    /** Fügt hinzu; gleiche Karte (gleiche Foil-Art) erhöht die Anzahl. Gibt die neue Anzahl zurück. */
    fun add(ctx: Context, item: BatchItem): Int {
        val items = all(ctx)
        val ex = items.firstOrNull { it.key == item.key }
        val qty = if (ex != null) {
            ex.quantity += item.quantity
            items.remove(ex)
            items.add(0, ex)
            ex.quantity
        } else {
            items.add(0, item)
            item.quantity
        }
        save(ctx, items)
        return qty
    }

    fun clear(ctx: Context) = save(ctx, emptyList())

    fun count(ctx: Context) = all(ctx).sumOf { it.quantity }

    fun value(ctx: Context) = all(ctx).sumOf { (it.unitPrice ?: 0.0) * it.quantity }

    fun isEnabled(ctx: Context) = sp(ctx).getBoolean("batch_mode", false)
    fun setEnabled(ctx: Context, v: Boolean) = sp(ctx).edit().putBoolean("batch_mode", v).apply()
}

fun euro(v: Double?): String = if (v == null) "–" else String.format(java.util.Locale.GERMANY, "%.2f €", v)
