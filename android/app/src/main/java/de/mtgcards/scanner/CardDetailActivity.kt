package de.mtgcards.scanner

import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.CheckBox
import android.widget.ImageView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject

class CardDetailActivity : AppCompatActivity() {

    private var cardId = 0L
    private var card: JSONObject? = null
    private lateinit var foil: CheckBox
    private var binding = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_card_detail)
        cardId = intent.getLongExtra("id", 0)
        foil = findViewById(R.id.dFoil)
        findViewById<View>(R.id.dBack).setOnClickListener { finish() }
        findViewById<Button>(R.id.dMinus).setOnClickListener { changeQty(-1) }
        findViewById<Button>(R.id.dPlus).setOnClickListener { changeQty(1) }
        findViewById<Button>(R.id.dDelete).setOnClickListener { confirmDelete() }
        foil.setOnCheckedChangeListener { _, checked ->
            if (!binding) patch(JSONObject().put("foil", checked))
        }
        load()
    }

    private fun load() {
        lifecycleScope.launch {
            try {
                bind(Api.fromPrefs(this@CardDetailActivity).card(cardId))
            } catch (e: ApiException) {
                Toast.makeText(this@CardDetailActivity, e.message, Toast.LENGTH_LONG).show()
                finish()
            }
        }
    }

    private fun bind(c: JSONObject) {
        card = c
        cardId = c.optLong("id")
        binding = true
        findViewById<TextView>(R.id.dTitle).text = c.optString("name")
        findViewById<TextView>(R.id.dName).text = c.optString("name")
        val printed = c.optString("printed_name")
        findViewById<TextView>(R.id.dPrinted).apply {
            text = "$printed (${c.optString("lang")})"
            visibility = if (printed.isNotBlank() && printed != c.optString("name")) View.VISIBLE else View.GONE
        }
        val pt = if (!c.isNull("power")) " · ${c.optString("power")}/${c.optString("toughness")}" else ""
        findViewById<TextView>(R.id.dType).text = "${c.optString("mana_cost")}   ${c.optString("type_line")}$pt"
        findViewById<TextView>(R.id.dOracle).text = c.optString("oracle_text").ifBlank { "Kein Regeltext" }
        val tags = c.optJSONArray("tags") ?: JSONArray()
        val price = if (c.optBoolean("foil")) c.optString("price_eur_foil") else c.optString("price_eur")
        findViewById<TextView>(R.id.dInfo).text = buildString {
            append("Farbidentität: ").append(c.optString("color_identity").ifBlank { "farblos" }).append('\n')
            append("Edition: ${c.optString("set_name")} (${c.optString("set_code")}) #${c.optString("collector_number")}\n")
            append("Seltenheit: ${c.optString("rarity")}\n")
            if (price.isNotBlank() && price != "null") append("Preis: $price €\n")
            if (tags.length() > 0) append("Tags: ").append((0 until tags.length()).joinToString(", ") { tags.getString(it) }).append('\n')
            val kw = c.optJSONArray("keywords")
            if (kw != null && kw.length() > 0) append("Schlüsselwörter: ").append((0 until kw.length()).joinToString(", ") { kw.getString(it) })
        }
        findViewById<TextView>(R.id.dQty).text = c.optInt("quantity").toString()
        foil.isChecked = c.optBoolean("foil")
        ImageLoader.load(lifecycleScope, c.optString("image_url"), findViewById<ImageView>(R.id.dImage))
        binding = false
    }

    private fun changeQty(delta: Int) {
        val c = card ?: return
        val q = c.optInt("quantity") + delta
        if (q <= 0) return confirmDelete()
        patch(JSONObject().put("quantity", q))
    }

    private fun patch(changes: JSONObject) {
        lifecycleScope.launch {
            try {
                val res = Api.fromPrefs(this@CardDetailActivity).update(cardId, changes)
                if (res.optBoolean("deleted")) finish() else bind(res)
            } catch (e: ApiException) {
                Toast.makeText(this@CardDetailActivity, e.message, Toast.LENGTH_LONG).show()
            }
        }
    }

    private fun confirmDelete() {
        val c = card ?: return
        AlertDialog.Builder(this)
            .setTitle("Löschen?")
            .setMessage("${c.optString("name")} (${c.optInt("quantity")}×) aus der Sammlung entfernen?")
            .setPositiveButton("Löschen") { _, _ ->
                lifecycleScope.launch {
                    try {
                        Api.fromPrefs(this@CardDetailActivity).delete(cardId)
                        finish()
                    } catch (e: ApiException) {
                        Toast.makeText(this@CardDetailActivity, e.message, Toast.LENGTH_LONG).show()
                    }
                }
            }
            .setNegativeButton("Abbrechen", null)
            .show()
    }
}
