package de.mtgcards.scanner

import android.content.Intent
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.progressindicator.LinearProgressIndicator
import kotlinx.coroutines.launch
import org.json.JSONObject

/** Editionen der Sammlung mit Sammelfortschritt (Grundset). */
class SetsActivity : AppCompatActivity() {
    private var items: List<JSONObject> = emptyList()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_list)
        findViewById<TextView>(R.id.listTitle).text = "Editionen"
        findViewById<View>(R.id.listBack).setOnClickListener { finish() }
        val list = findViewById<RecyclerView>(R.id.listItems)
        list.layoutManager = LinearLayoutManager(this)
        list.adapter = object : RecyclerView.Adapter<RecyclerView.ViewHolder>() {
            override fun onCreateViewHolder(parent: ViewGroup, viewType: Int) =
                object : RecyclerView.ViewHolder(LayoutInflater.from(parent.context)
                    .inflate(R.layout.item_deck, parent, false)) {}

            override fun getItemCount() = items.size

            override fun onBindViewHolder(holder: RecyclerView.ViewHolder, position: Int) {
                val s = items[position]
                val v = holder.itemView
                val pct = if (s.isNull("percent")) null else s.optDouble("percent")
                v.findViewById<TextView>(R.id.deckName).text =
                    "${s.optString("name")} (${s.optString("code")})" + (pct?.let { "  ·  ${it.toInt()} %" } ?: "")
                v.findViewById<TextView>(R.id.deckSub).text =
                    "${s.optInt("main_owned")}/${s.optInt("main_size")} im Grundset · ${s.optInt("owned_cards")} Karten"
                v.findViewById<LinearProgressIndicator>(R.id.deckProgress).apply {
                    max = maxOf(1, s.optInt("main_size"))
                    progress = s.optInt("main_owned")
                }
                v.setOnClickListener {
                    startActivity(Intent(this@SetsActivity, SetDetailActivity::class.java)
                        .putExtra("code", s.optString("code")))
                }
            }
        }
        val info = findViewById<TextView>(R.id.listInfo)
        info.text = "Lade …"
        lifecycleScope.launch {
            try {
                val arr = Api.fromPrefs(this@SetsActivity).sets().getJSONArray("sets")
                items = (0 until arr.length()).map { arr.getJSONObject(it) }
                list.adapter?.notifyDataSetChanged()
                info.text = "${items.size} Editionen in der Sammlung"
            } catch (e: ApiException) {
                info.text = e.message
                Toast.makeText(this@SetsActivity, e.message, Toast.LENGTH_LONG).show()
            }
        }
    }
}
