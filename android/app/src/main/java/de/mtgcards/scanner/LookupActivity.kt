package de.mtgcards.scanner

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.text.InputType
import android.view.Gravity
import android.view.inputmethod.EditorInfo
import android.widget.ArrayAdapter
import android.widget.AutoCompleteTextView
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.ImageButton
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.widget.doAfterTextChanged
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONObject

/** Karte nachschlagen: beliebige Karte per Name ansehen – gespeichert wird nur auf ausdrücklichen Wunsch. */
class LookupActivity : AppCompatActivity() {
    private var card: JSONObject? = null
    private var showBack = false
    private lateinit var image: ImageView
    private lateinit var titleView: TextView
    private lateinit var body: TextView
    private lateinit var actions: LinearLayout
    private var acJob: Job? = null

    private val formats = linkedMapOf("commander" to "Commander", "standard" to "Standard", "pioneer" to "Pioneer",
        "modern" to "Modern", "legacy" to "Legacy", "vintage" to "Vintage", "pauper" to "Pauper", "brawl" to "Brawl")

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val dp = resources.displayMetrics.density
        fun px(v: Int) = (v * dp).toInt()
        val input = AutoCompleteTextView(this).apply {
            hint = "Kartenname (deutsch oder englisch)"
            isSingleLine = true
            imeOptions = EditorInfo.IME_ACTION_SEARCH
            inputType = InputType.TYPE_CLASS_TEXT
            threshold = 2
        }
        val adapter = ArrayAdapter<String>(this, android.R.layout.simple_dropdown_item_1line, mutableListOf())
        input.setAdapter(adapter)
        input.doAfterTextChanged { t ->
            val q = t?.toString()?.trim() ?: ""
            acJob?.cancel()
            if (q.length < 2) return@doAfterTextChanged
            acJob = lifecycleScope.launch {
                delay(250)
                try {
                    val arr = Api.fromPrefs(this@LookupActivity).autocomplete(q).getJSONArray("data")
                    adapter.clear()
                    adapter.addAll((0 until minOf(arr.length(), 15)).map { arr.getString(it) })
                    adapter.notifyDataSetChanged()
                    if (input.hasFocus()) input.showDropDown()
                } catch (_: ApiException) {
                }
            }
        }
        input.setOnItemClickListener { _, _, pos, _ -> search(adapter.getItem(pos) ?: "", null) }
        input.setOnEditorActionListener { v, _, _ -> search(v.text.toString().trim(), null); true }

        image = ImageView(this).apply {
            adjustViewBounds = true
            scaleType = ImageView.ScaleType.FIT_CENTER
            setOnClickListener {
                if (card?.optString("image_url_back")?.let { it.isNotBlank() && it != "null" } == true) {
                    showBack = !showBack
                    render()
                }
            }
        }
        titleView = TextView(this).apply { textSize = 22f; setTypeface(typeface, android.graphics.Typeface.BOLD) }
        body = TextView(this).apply { textSize = 15f; setLineSpacing(0f, 1.15f); setTextIsSelectable(true) }
        actions = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(px(14), px(8), px(14), px(20))
            addView(LinearLayout(context).apply {
                gravity = Gravity.CENTER_VERTICAL
                addView(ImageButton(context).apply {
                    setImageResource(R.drawable.ic_back)
                    setBackgroundResource(android.R.color.transparent)
                    contentDescription = "Zurück"
                    setOnClickListener { finish() }
                }, LinearLayout.LayoutParams(px(44), px(44)))
                addView(TextView(context).apply {
                    text = "Karte nachschlagen"
                    textSize = 20f
                    setTypeface(typeface, android.graphics.Typeface.BOLD)
                })
            })
            addView(input)
            addView(TextView(context).apply {
                text = "Nur ansehen – gespeichert wird nur, wenn du unten „Zur Sammlung“ oder „Wunschliste“ wählst."
                textSize = 12f
                alpha = 0.7f
                setPadding(0, px(4), 0, px(10))
            })
            addView(image, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, px(420)))
            addView(titleView)
            addView(body)
            addView(actions)
        }
        image.visibility = android.view.View.GONE
        setContentView(ScrollView(this).apply { addView(root) })
        intent.getStringExtra("name")?.let { input.setText(it); search(it, null) }
    }

    private fun search(name: String, scryfallId: String?, lang: String? = null) {
        if (name.isBlank() && scryfallId == null) return
        titleView.text = "Suche …"
        lifecycleScope.launch {
            try {
                card = Api.fromPrefs(this@LookupActivity).lookup(name.ifBlank { null }, scryfallId = scryfallId, lang = lang)
                showBack = false
                render()
            } catch (e: ApiException) {
                titleView.text = e.message
                body.text = ""
                actions.removeAllViews()
            }
        }
    }

    private fun render() {
        val c = card ?: return
        fun v(k: String) = c.optString(k).takeIf { it.isNotBlank() && it != "null" }
        val back = v("image_url_back")
        image.visibility = android.view.View.VISIBLE
        ImageLoader.load(lifecycleScope, if (showBack && back != null) back else v("image_url"), image)
        titleView.text = "${c.optString("name")}  ${c.optString("mana_cost")}"
        val pt = if (!c.isNull("power")) " · ${c.optString("power")}/${c.optString("toughness")}"
        else v("loyalty")?.let { " · Loyalität $it" } ?: ""
        val legal = c.optJSONObject("legalities")
        val owned = c.optJSONObject("owned")
        val decks = c.optJSONArray("decks")
        body.text = buildString {
            v("printed_name")?.takeIf { it != c.optString("name") }?.let { append(it).append('\n') }
            append(c.optString("type_line")).append(pt).append("\n\n")
            append(v("oracle_text") ?: "Kein Regeltext").append('\n')
            v("flavor_text")?.let { append('\n').append(it).append('\n') }
            append("\nDruck: ${c.optString("set_name")} (${c.optString("set_code")}) #${c.optString("collector_number")}")
            append(" · ${Languages.label(c.optString("lang").ifBlank { "en" })}")
            if (back != null) append("\nDoppelseitig – Bild antippen für die andere Seite")
            append("\nPreis: ${v("price_eur")?.let { "$it €" } ?: "–"} · Foil ${v("price_eur_foil")?.let { "$it €" } ?: "–"}")
            if (v("price_usd") != null) append("  (\$${v("price_usd")})")
            append("\nFarbidentität: ${c.optString("color_identity").ifBlank { "farblos" }}")
            v("artist")?.let { append("\nKünstler: $it") }
            if (legal != null && legal.length() > 0) {
                append("\nLegal: ")
                append(formats.filterKeys { legal.has(it) }.map { (k, n) ->
                    n + when (legal.optString(k)) { "legal" -> " ✓"; "banned" -> " gebannt"; "restricted" -> " beschränkt"; else -> " ✗" }
                }.joinToString(", "))
            }
            append("\n\nBei dir: ")
            val all = owned?.optInt("all_prints") ?: 0
            append(if (all > 0) "$all× in der Sammlung (${owned?.optInt("this_print") ?: 0}× dieser Druck)" else "nicht in der Sammlung")
            if (c.optInt("wished") > 0) append(" · ${c.optInt("wished")}× auf der Wunschliste")
            if (decks != null && decks.length() > 0) append("\nIn Decks: " + (0 until decks.length()).joinToString(", ") {
                decks.getJSONObject(it).let { u -> "${u.optString("deck")} (${u.optInt("quantity")})" } })
        }
        actions.removeAllViews()
        fun button(text: String, onClick: () -> Unit) = actions.addView(Button(this).apply {
            this.text = text
            setOnClickListener { onClick() }
        })
        button("Druck / Sprache wählen") {
            PrintPicker.show(this, lifecycleScope, c.optString("name"), c.optString("lang"), rememberSet = false) { picked ->
                card = picked
                showBack = false
                search("", picked.optString("scryfall_id"), picked.optString("lang"))
            }
        }
        button("＋ Zur Sammlung") { addToCollection(c) }
        button("★ Auf die Wunschliste") { addToWishlist(c) }
        button("🖨 In Proxie Maker") { addToProxies(c) }
        button("Auf Scryfall öffnen") {
            v("scryfall_uri")?.let { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(it))) }
        }
    }

    private fun addToCollection(c: JSONObject) {
        val qty = EditText(this).apply { inputType = InputType.TYPE_CLASS_NUMBER; setText("1"); hint = "Anzahl" }
        val foil = CheckBox(this).apply { text = "Foil" }
        AlertDialog.Builder(this).setTitle("Zur Sammlung: ${c.optString("name")}")
            .setView(LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(48, 16, 48, 0); addView(qty); addView(foil) })
            .setPositiveButton("Hinzufügen") { _, _ ->
                lifecycleScope.launch {
                    try {
                        val r = Api.fromPrefs(this@LookupActivity).addCard(c.optString("scryfall_id"),
                            qty.text.toString().toIntOrNull() ?: 1, foil.isChecked)
                        Toast.makeText(this@LookupActivity, "${r.optString("name")} – jetzt ${r.optInt("quantity")}×", Toast.LENGTH_SHORT).show()
                        search("", c.optString("scryfall_id"), c.optString("lang"))
                    } catch (e: ApiException) {
                        Toast.makeText(this@LookupActivity, e.message, Toast.LENGTH_LONG).show()
                    }
                }
            }
            .setNegativeButton("Abbrechen", null).show()
    }

    /** In eine Druckliste oder ein Deck von Proxie Maker – zum Gestalten und Drucken. */
    private fun addToProxies(c: JSONObject) {
        lifecycleScope.launch {
            val api = Api.fromPrefs(this@LookupActivity)
            val projects = try {
                val arr = api.pmProjects().getJSONArray("projects")
                (0 until arr.length()).map { arr.getJSONObject(it) }
            } catch (e: ApiException) {
                Toast.makeText(this@LookupActivity, e.message, Toast.LENGTH_LONG).show()
                return@launch
            }
            val qty = EditText(this@LookupActivity).apply { inputType = InputType.TYPE_CLASS_NUMBER; setText("1"); hint = "Anzahl" }
            val labels = listOf("＋ Neue Druckliste …") + projects.map {
                (if (it.optString("kind") == "deck") "Deck: " else "") + it.optString("name") + " (${it.optInt("cards")} Karten)"
            }
            AlertDialog.Builder(this@LookupActivity)
                .setTitle("In Proxie Maker: ${c.optString("name")}")
                .setItems(labels.toTypedArray()) { _, which ->
                    if (which == 0) {
                        val name = EditText(this@LookupActivity).apply { hint = "Name der Druckliste"; setText("Proxies") }
                        AlertDialog.Builder(this@LookupActivity).setTitle("Neue Druckliste")
                            .setView(LinearLayout(this@LookupActivity).apply {
                                orientation = LinearLayout.VERTICAL; setPadding(48, 16, 48, 0); addView(name); addView(qty)
                            })
                            .setPositiveButton("Anlegen") { _, _ ->
                                lifecycleScope.launch {
                                    try {
                                        val p = api.pmCreateList(name.text.toString().trim().ifBlank { "Proxies" })
                                        sendToProxies(p.getJSONObject("project").optLong("id"), c, qty.text.toString().toIntOrNull() ?: 1)
                                    } catch (e: ApiException) {
                                        Toast.makeText(this@LookupActivity, e.message, Toast.LENGTH_LONG).show()
                                    }
                                }
                            }
                            .setNegativeButton("Abbrechen", null).show()
                    } else {
                        val target = projects[which - 1]
                        AlertDialog.Builder(this@LookupActivity).setTitle("Anzahl")
                            .setView(LinearLayout(this@LookupActivity).apply { setPadding(48, 16, 48, 0); addView(qty) })
                            .setPositiveButton("Hinzufügen") { _, _ ->
                                lifecycleScope.launch { sendToProxies(target.optLong("id"), c, qty.text.toString().toIntOrNull() ?: 1) }
                            }
                            .setNegativeButton("Abbrechen", null).show()
                    }
                }
                .setNegativeButton("Abbrechen", null)
                .show()
        }
    }

    private suspend fun sendToProxies(projectId: Long, c: JSONObject, quantity: Int) {
        try {
            Api.fromPrefs(this).pmAddCard(projectId, c.optString("scryfall_id"), quantity.coerceAtLeast(1))
            AlertDialog.Builder(this)
                .setTitle("${c.optString("name")} ist in Proxie Maker")
                .setMessage("Jetzt gestalten und drucken?")
                .setPositiveButton("Proxie Maker öffnen") { _, _ -> startActivity(Intent(this, ProxieActivity::class.java)) }
                .setNegativeButton("Weiter nachschlagen", null)
                .show()
        } catch (e: ApiException) {
            Toast.makeText(this, e.message, Toast.LENGTH_LONG).show()
        }
    }

    private fun addToWishlist(c: JSONObject) {
        AlertDialog.Builder(this).setTitle("Auf die Wunschliste")
            .setItems(arrayOf("Genau dieser Druck (${c.optString("set_code")} #${c.optString("collector_number")})",
                "Beliebiger Druck (günstigster)")) { _, which ->
                lifecycleScope.launch {
                    try {
                        val api = Api.fromPrefs(this@LookupActivity)
                        val w = if (which == 0) api.wishAddPrint(c.optString("scryfall_id")) else api.wishAdd(c.optString("name"), "")
                        Toast.makeText(this@LookupActivity, "${w.optString("name")} auf der Wunschliste", Toast.LENGTH_SHORT).show()
                        search("", c.optString("scryfall_id"), c.optString("lang"))
                    } catch (e: ApiException) {
                        Toast.makeText(this@LookupActivity, e.message, Toast.LENGTH_LONG).show()
                    }
                }
            }
            .setNegativeButton("Abbrechen", null).show()
    }
}
