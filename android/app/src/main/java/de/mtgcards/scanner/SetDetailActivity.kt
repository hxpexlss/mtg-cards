package de.mtgcards.scanner

import android.graphics.Color
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

/** Karten einer Edition: vorhanden ✓ / fehlt ✗, Filter Grundset/Varianten und Fehlende. */
class SetDetailActivity : AppCompatActivity() {
    private var data: JSONObject? = null
    private var withVariants = false
    private var onlyMissing = true

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_deck)
        findViewById<View>(R.id.deckBack).setOnClickListener { finish() }
        findViewById<View>(R.id.deckProxies).visibility = View.GONE
        findViewById<View>(R.id.deckStatus).visibility = View.GONE
        val filter = findViewById<Button>(R.id.deckFilter)
        val scope = findViewById<Button>(R.id.deckShare)
        filter.text = "Alle zeigen"
        scope.text = "inkl. Varianten"
        filter.setOnClickListener {
            onlyMissing = !onlyMissing
            filter.text = if (onlyMissing) "Alle zeigen" else "Nur fehlende"
            data?.let { render(it) }
        }
        scope.setOnClickListener {
            withVariants = !withVariants
            scope.text = if (withVariants) "nur Grundset" else "inkl. Varianten"
            data?.let { render(it) }
        }
        val code = intent.getStringExtra("code") ?: return finish()
        findViewById<TextView>(R.id.deckTitle).text = code
        findViewById<TextView>(R.id.deckSummary).text = "Lade Kartenliste …"
        lifecycleScope.launch {
            try {
                val d = Api.fromPrefs(this@SetDetailActivity).set(code)
                data = d
                render(d)
            } catch (e: ApiException) {
                Toast.makeText(this@SetDetailActivity, e.message, Toast.LENGTH_LONG).show()
                finish()
            }
        }
    }

    private fun render(d: JSONObject) {
        findViewById<TextView>(R.id.deckTitle).text = "${d.optString("name")} (${d.optString("code")})"
        val st = d.optJSONObject("stats")?.optJSONObject(if (withVariants) "all" else "main")?.optJSONObject("_all")
        findViewById<TextView>(R.id.deckSummary).text = if (st == null) "" else
            "${st.optInt("owned")} von ${st.optInt("total")} Karten (${st.optDouble("percent")} %) · " +
                "${st.optInt("total") - st.optInt("owned")} fehlen · Wert der fehlenden ${euro(st.optDouble("missing_value"))}"
        val container = findViewById<LinearLayout>(R.id.deckCards)
        container.removeAllViews()
        val arr = d.getJSONArray("cards")
        val dp = resources.displayMetrics.density
        var shown = 0
        for (i in 0 until arr.length()) {
            val c = arr.getJSONObject(i)
            if (!withVariants && !c.optBoolean("main")) continue
            val owned = c.optInt("owned")
            if (onlyMissing && owned > 0) continue
            shown++
            container.addView(TextView(this).apply {
                val rarity = c.optString("rarity").take(1).uppercase()
                val price = c.optDouble("price")
                text = "${if (owned > 0) "✓ ${owned}×" else "✗"}  #${c.optString("collector_number")}  " +
                    "${c.optString("name")}  ($rarity${if (price > 0) " · ${euro(price)}" else ""})"
                textSize = 15f
                setPadding(0, (3 * dp).toInt(), 0, (3 * dp).toInt())
                if (owned == 0) setTextColor(Color.rgb(229, 72, 77))
            })
        }
        if (shown == 0) {
            container.addView(TextView(this).apply {
                text = if (onlyMissing) "Komplett! 🎉" else "Keine Karten"
                setPadding(0, (20 * dp).toInt(), 0, 0)
            })
        }
    }
}
