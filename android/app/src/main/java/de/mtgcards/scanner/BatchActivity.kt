package de.mtgcards.scanner

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.CheckBox
import android.widget.ImageView
import android.widget.TextView
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import org.json.JSONArray

/** Zusammenfassung eines Stapel-Scans: korrigieren, dann alles auf einmal speichern. */
class BatchActivity : AppCompatActivity() {
    private lateinit var adapter: BatchAdapter
    private lateinit var summary: TextView
    private lateinit var saveButton: Button
    private var items = mutableListOf<BatchItem>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_batch)
        summary = findViewById(R.id.batchSummary)
        saveButton = findViewById(R.id.batchSave)
        findViewById<View>(R.id.batchBack).setOnClickListener { finish() }
        items = BatchStore.all(this)
        adapter = BatchAdapter(lifecycleScope, items) { persist() }
        findViewById<RecyclerView>(R.id.batchList).apply {
            layoutManager = LinearLayoutManager(this@BatchActivity)
            adapter = this@BatchActivity.adapter
        }
        saveButton.setOnClickListener { saveAll() }
        findViewById<Button>(R.id.batchDiscard).setOnClickListener {
            AlertDialog.Builder(this)
                .setTitle("Stapel verwerfen?")
                .setMessage("Alle ${items.sumOf { it.quantity }} gescannten Karten werden NICHT gespeichert.")
                .setPositiveButton("Verwerfen") { _, _ ->
                    BatchStore.clear(this)
                    finish()
                }
                .setNegativeButton("Abbrechen", null)
                .show()
        }
        updateSummary()
    }

    private fun persist() {
        BatchStore.save(this, items)
        updateSummary()
    }

    private fun updateSummary() {
        val n = items.sumOf { it.quantity }
        val value = items.sumOf { (it.unitPrice ?: 0.0) * it.quantity }
        val offline = items.count { it.scryfallId == null }
        summary.text = buildString {
            append("$n Karten · ${items.size} verschiedene · Wert ${euro(value)}")
            if (offline > 0) append("\n$offline offline gescannt – werden beim Speichern nachgeschlagen")
        }
        saveButton.isEnabled = n > 0
        saveButton.text = "Alle $n Karten speichern"
    }

    private fun saveAll() {
        saveButton.isEnabled = false
        saveButton.text = "Speichere …"
        lifecycleScope.launch {
            try {
                val req = JSONArray()
                items.forEach { req.put(it.toRequest()) }
                val res = Api.fromPrefs(this@BatchActivity).addBatch(req)
                val errors = res.optJSONArray("errors") ?: JSONArray()
                val failedIdx = (0 until errors.length()).map { errors.getJSONObject(it).optInt("index") }.toSet()
                val failed = items.filterIndexed { i, _ -> i in failedIdx }
                ScanSession.added += res.optInt("added")
                val wishes = res.optJSONArray("wish_fulfilled") ?: JSONArray()
                val msg = buildString {
                    append("${res.optInt("added")} Karten gespeichert.")
                    if (wishes.length() > 0) {
                        append("\n\n★ Wünsche erfüllt:\n")
                        append((0 until wishes.length()).joinToString("\n") { wishes.getJSONObject(it).optString("name") })
                    }
                    if (failed.isNotEmpty()) {
                        append("\n\nNicht gefunden (bleiben im Stapel):\n")
                        append((0 until errors.length()).joinToString("\n") { errors.getJSONObject(it).optString("name") })
                    }
                }
                items.clear()
                items.addAll(failed)
                adapter.notifyDataSetChanged()
                persist()
                AlertDialog.Builder(this@BatchActivity)
                    .setTitle(if (failed.isEmpty()) "✓ Gespeichert" else "Teilweise gespeichert")
                    .setMessage(msg)
                    .setPositiveButton("OK") { _, _ -> if (failed.isEmpty()) finish() }
                    .show()
            } catch (e: ApiException) {
                AlertDialog.Builder(this@BatchActivity)
                    .setTitle("Nicht gespeichert")
                    .setMessage("${e.message}\n\nDer Stapel bleibt erhalten – später erneut versuchen.")
                    .setPositiveButton("OK", null)
                    .show()
                updateSummary()
            }
        }
    }
}

class BatchAdapter(
    private val scope: CoroutineScope,
    private val items: MutableList<BatchItem>,
    private val onChange: () -> Unit,
) : RecyclerView.Adapter<BatchAdapter.VH>() {

    class VH(v: View) : RecyclerView.ViewHolder(v) {
        val image: ImageView = v.findViewById(R.id.bImage)
        val name: TextView = v.findViewById(R.id.bName)
        val sub: TextView = v.findViewById(R.id.bSub)
        val qty: TextView = v.findViewById(R.id.bQty)
        val minus: Button = v.findViewById(R.id.bMinus)
        val plus: Button = v.findViewById(R.id.bPlus)
        val foil: CheckBox = v.findViewById(R.id.bFoil)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int) =
        VH(LayoutInflater.from(parent.context).inflate(R.layout.item_batch, parent, false))

    override fun getItemCount() = items.size

    override fun onBindViewHolder(h: VH, position: Int) {
        val it = items[position]
        h.name.text = it.name
        val where = listOfNotNull(it.setCode?.uppercase(), it.cn?.let { cn -> "#$cn" }).joinToString(" ")
        h.sub.text = buildString {
            if (it.proxy) append("🅿 Proxy · ")
            if (where.isNotBlank()) append(where).append(" · ")
            append(if (it.scryfallId == null) "offline – wird geprüft" else euro(it.unitPrice))
            if (it.quantity > 1 && it.unitPrice != null) append(" · zus. ${euro(it.unitPrice!! * it.quantity)}")
        }
        h.qty.text = it.quantity.toString()
        h.foil.setOnCheckedChangeListener(null)
        h.foil.isChecked = it.foil
        ImageLoader.load(scope, it.imageUrl, h.image, 4)
        h.plus.setOnClickListener { _ ->
            it.quantity++
            notifyItemChanged(h.bindingAdapterPosition)
            onChange()
        }
        h.minus.setOnClickListener { _ ->
            val pos = h.bindingAdapterPosition
            if (it.quantity <= 1) {
                items.removeAt(pos)
                notifyItemRemoved(pos)
            } else {
                it.quantity--
                notifyItemChanged(pos)
            }
            onChange()
        }
        h.foil.setOnCheckedChangeListener { _, checked ->
            it.foil = checked
            notifyItemChanged(h.bindingAdapterPosition)
            onChange()
        }
    }
}
