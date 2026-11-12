package de.mtgcards.scanner

import android.content.Context
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import org.json.JSONObject

/** Dialog "Druck ändern": alle Drucke einer Karte mit Edition, Nummer und Preis. */
object PrintPicker {
    fun show(ctx: Context, scope: CoroutineScope, name: String, lang: String?, onPicked: (JSONObject) -> Unit) {
        scope.launch {
            try {
                val api = Api.fromPrefs(ctx)
                val arr = api.prints(name.split(" // ").first()).getJSONArray("data")
                val prints = (0 until arr.length()).map { arr.getJSONObject(it) }
                if (prints.isEmpty()) {
                    Toast.makeText(ctx, "Keine weiteren Drucke gefunden", Toast.LENGTH_SHORT).show()
                    return@launch
                }
                val labels = prints.map { p ->
                    val price = p.optString("price_eur").takeIf { it.isNotBlank() && it != "null" }?.let { " · $it €" } ?: ""
                    "${p.optString("set_code")} – ${p.optString("set_name")} #${p.optString("collector_number")}$price"
                }.toTypedArray()
                AlertDialog.Builder(ctx)
                    .setTitle("Druck wählen – $name")
                    .setItems(labels) { _, which ->
                        scope.launch {
                            try {
                                val card = api.lookup(null, scryfallId = prints[which].optString("scryfall_id"),
                                    lang = lang?.takeIf { it.isNotBlank() && it != "en" })
                                Prefs.setLastSet(ctx, card.optString("set_code"))
                                onPicked(card)
                            } catch (e: ApiException) {
                                Toast.makeText(ctx, e.message, Toast.LENGTH_LONG).show()
                            }
                        }
                    }
                    .setNegativeButton("Abbrechen", null)
                    .show()
            } catch (e: ApiException) {
                Toast.makeText(ctx, e.message, Toast.LENGTH_LONG).show()
            }
        }
    }

    /** Kurztext, wie sicher der Druck ist (Feld "match" vom Server). */
    fun matchText(card: JSONObject): String = when (card.optString("match")) {
        "exact", "id" -> "✓ Druck erkannt"
        "set" -> "✓ Edition erkannt"
        "preferred" -> "≈ Edition übernommen (zuletzt/festgelegt)"
        "name" -> "⚠ Druck geraten – bitte prüfen"
        else -> ""
    }
}
