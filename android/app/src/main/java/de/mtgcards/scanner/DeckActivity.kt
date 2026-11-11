package de.mtgcards.scanner

import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.launch
import org.json.JSONObject

/** Deck-Ansicht: Karten nach Typ gruppiert, ✓ vorhanden / ✗ fehlt, fehlende Karten teilen. */
class DeckActivity : AppCompatActivity() {
    private var deckId = 0L
    private var onlyMissing = false
    private var deck: JSONObject? = null

    private val groupTitles = mapOf(
        "Commander" to "Commander", "Creature" to "Kreaturen", "Planeswalker" to "Planeswalker",
        "Battle" to "Schlachten", "Instant" to "Spontanzauber", "Sorcery" to "Hexereien",
        "Artifact" to "Artefakte", "Enchantment" to "Verzauberungen", "Land" to "Länder",
        "Sonstige" to "Sonstige", "side" to "Sideboard", "maybe" to "Vielleicht",
    )

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_deck)
        deckId = intent.getLongExtra("id", 0)
        findViewById<View>(R.id.deckBack).setOnClickListener { finish() }
        findViewById<Button>(R.id.deckFilter).setOnClickListener {
            onlyMissing = !onlyMissing
            (it as Button).text = if (onlyMissing) "Alle zeigen" else "Nur fehlende"
            deck?.let { d -> render(d) }
        }
        findViewById<Button>(R.id.deckShare).setOnClickListener { shareMissing() }
    }

    override fun onResume() {
        super.onResume()
        lifecycleScope.launch {
            try {
                val d = Api.fromPrefs(this@DeckActivity).deck(deckId)
                deck = d
                render(d)
            } catch (e: ApiException) {
                Toast.makeText(this@DeckActivity, e.message, Toast.LENGTH_LONG).show()
                finish()
            }
        }
    }

    private fun render(d: JSONObject) {
        val st = d.getJSONObject("stats")
        findViewById<TextView>(R.id.deckTitle).text = d.optString("name")
        val ci = d.optString("color_identity")
        findViewById<TextView>(R.id.deckSummary).text = buildString {
            append("${st.optInt("cards")} Karten · ${st.optInt("owned")} vorhanden · ${st.optInt("missing")} fehlen")
            if (ci.isNotBlank()) append(" · Farbidentität $ci")
            if (st.optInt("outside_identity") > 0) append("\n⚠ ${st.optInt("outside_identity")} Karte(n) außerhalb der Farbidentität")
        }
        val container = findViewById<LinearLayout>(R.id.deckCards)
        container.removeAllViews()
        val arr = d.getJSONArray("cards")
        val cards = (0 until arr.length()).map { arr.getJSONObject(it) }
            .filter { !onlyMissing || it.optInt("missing") > 0 }
        val order = listOf("Commander", "Creature", "Planeswalker", "Battle", "Instant", "Sorcery",
            "Artifact", "Enchantment", "Land", "Sonstige", "side", "maybe")
        val grouped = cards.groupBy { c ->
            val board = c.optString("board")
            if (board == "side" || board == "maybe") board else c.optString("group")
        }
        val dp = resources.displayMetrics.density
        for (g in order) {
            val list = grouped[g] ?: continue
            container.addView(TextView(this).apply {
                text = "${groupTitles[g] ?: g} (${list.sumOf { it.optInt("quantity") }})"
                setTypeface(typeface, Typeface.BOLD)
                setPadding(0, (14 * dp).toInt(), 0, (4 * dp).toInt())
                alpha = 0.7f
            })
            for (c in list) {
                val basic = c.optBoolean("basic")
                val missing = c.optInt("missing")
                container.addView(TextView(this).apply {
                    val status = when {
                        basic -> "–"
                        missing > 0 -> "✗"
                        else -> "✓"
                    }
                    val owned = c.optInt("owned")
                    val extra = if (missing > 0 && owned > 0) "  ($owned/${c.optInt("quantity")})" else ""
                    val warn = if (c.optBoolean("outside_identity")) "  ⚠" else ""
                    text = "$status  ${c.optInt("quantity")}  ${c.optString("name")}$extra$warn"
                    textSize = 15f
                    setPadding(0, (3 * dp).toInt(), 0, (3 * dp).toInt())
                    if (!basic) setTextColor(if (missing > 0) Color.rgb(229, 72, 77) else currentTextColor)
                })
            }
        }
        if (cards.isEmpty()) {
            container.addView(TextView(this).apply {
                text = if (onlyMissing) "Es fehlen keine Karten 🎉" else "Keine Karten im Deck"
                setPadding(0, (20 * dp).toInt(), 0, 0)
            })
        }
    }

    private fun shareMissing() {
        lifecycleScope.launch {
            try {
                val text = Api.fromPrefs(this@DeckActivity).deckMissingText(deckId)
                if (text.isBlank()) {
                    Toast.makeText(this@DeckActivity, "Es fehlen keine Karten 🎉", Toast.LENGTH_SHORT).show()
                    return@launch
                }
                val send = Intent(Intent.ACTION_SEND).apply {
                    type = "text/plain"
                    putExtra(Intent.EXTRA_SUBJECT, "Fehlende Karten – ${deck?.optString("name")}")
                    putExtra(Intent.EXTRA_TEXT, text)
                }
                startActivity(Intent.createChooser(send, "Fehlende Karten teilen"))
            } catch (e: ApiException) {
                Toast.makeText(this@DeckActivity, e.message, Toast.LENGTH_LONG).show()
            }
        }
    }
}
