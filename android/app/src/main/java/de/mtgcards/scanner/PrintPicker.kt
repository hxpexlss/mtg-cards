package de.mtgcards.scanner

import android.content.Context
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import org.json.JSONObject

/** Dialog "Druck ändern": alle Drucke einer Karte mit Edition, Nummer, Jahr, Künstler und Preis – in einer Sprache. */
object PrintPicker {
    fun show(ctx: Context, scope: CoroutineScope, name: String, lang: String?, rememberSet: Boolean = true,
             onPicked: (JSONObject) -> Unit) {
        val language = lang?.takeIf { it.isNotBlank() && it != "null" && it != "auto" } ?: "en"
        scope.launch {
            try {
                val api = Api.fromPrefs(ctx)
                val arr = api.prints(name.split(" // ").first(), language).getJSONArray("data")
                val prints = (0 until arr.length()).map { arr.getJSONObject(it) }.reversed()   // neueste zuerst
                val labels = listOf("🌐 Sprache: ${Languages.label(language)} – ändern …") + prints.map { p ->
                    val price = p.optString("price_eur").takeIf { it.isNotBlank() && it != "null" }?.let { " · $it €" } ?: ""
                    val year = p.optString("released_at").take(4).takeIf { it.length == 4 }?.let { " · $it" } ?: ""
                    val artist = p.optString("artist").takeIf { it.isNotBlank() && it != "null" }?.let { " · $it" } ?: ""
                    "${p.optString("set_code")} – ${p.optString("set_name")} #${p.optString("collector_number")}$year$artist$price"
                }
                AlertDialog.Builder(ctx)
                    .setTitle(if (prints.isEmpty()) "Keine Drucke auf ${Languages.label(language)}" else "Druck wählen – $name")
                    .setItems(labels.toTypedArray()) { _, which ->
                        if (which == 0) {
                            chooseLanguage(ctx, language) { show(ctx, scope, name, it, rememberSet, onPicked) }
                            return@setItems
                        }
                        scope.launch {
                            try {
                                val card = api.lookup(null, scryfallId = prints[which - 1].optString("scryfall_id"),
                                    lang = language)
                                if (rememberSet) Prefs.setLastSet(ctx, card.optString("set_code"))
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

    private fun chooseLanguage(ctx: Context, current: String, onChosen: (String) -> Unit) {
        val langs = Languages.all.filter { it.first != "auto" }
        AlertDialog.Builder(ctx)
            .setTitle("Sprache der Karte")
            .setSingleChoiceItems(langs.map { it.second }.toTypedArray(),
                langs.indexOfFirst { it.first == current }) { d, which ->
                d.dismiss()
                onChosen(langs[which].first)
            }
            .setNegativeButton("Abbrechen", null)
            .show()
    }

    /** Kurztext, wie sicher der Druck ist (Feld "match" vom Server). */
    fun matchText(card: JSONObject): String = when (card.optString("match")) {
        "exact", "id" -> "✓ Druck erkannt"
        "set" -> "✓ Edition erkannt"
        "likely" -> "≈ Druck erkannt (Nummer/Künstler/Jahr)"
        "art" -> "≈ Druck über das Artwork erkannt"
        "preferred" -> "≈ Edition übernommen (zuletzt/festgelegt)"
        "proxy" -> "🅿 Standard-Druck (Proxy)"
        "name" -> "⚠ Druck geraten – bitte prüfen"
        else -> ""
    }

    /** Preis als Text: Euro (Foil-Preis für Foils), sonst Dollar – Scryfall hat nicht für jeden Druck Euro-Preise. */
    fun priceText(c: JSONObject, foil: Boolean = c.optBoolean("foil")): String? {
        fun v(k: String) = c.optString(k).takeIf { it.isNotBlank() && it != "null" }
        val eur = if (foil) v("price_eur_foil") ?: v("price_eur") else v("price_eur") ?: v("price_eur_foil")
        if (eur != null) return "$eur €"
        val usd = if (foil) v("price_usd_foil") ?: v("price_usd") else v("price_usd") ?: v("price_usd_foil")
        return usd?.let { "$$it" }
    }
}
