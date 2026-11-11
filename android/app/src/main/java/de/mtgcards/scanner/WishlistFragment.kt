package de.mtgcards.scanner

import android.Manifest
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.text.InputType
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.core.content.ContextCompat
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import org.json.JSONObject

/** Wunschliste: Karten mit Zielpreis; grün = Zielpreis erreicht. */
class WishlistFragment : Fragment(R.layout.fragment_wishlist) {
    private lateinit var info: TextView
    private lateinit var adapter: WishAdapter

    private val notifPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        info = view.findViewById(R.id.wishInfo)
        adapter = WishAdapter(viewLifecycleOwner.lifecycleScope) { editWish(it) }
        view.findViewById<RecyclerView>(R.id.wishList).apply {
            layoutManager = LinearLayoutManager(requireContext())
            adapter = this@WishlistFragment.adapter
        }
        view.findViewById<Button>(R.id.wishAdd).setOnClickListener { addWish() }
        PriceAlertWorker.schedule(requireContext())
        if (Build.VERSION.SDK_INT >= 33 && ContextCompat.checkSelfPermission(requireContext(),
                Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            notifPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    override fun onResume() {
        super.onResume()
        load()
    }

    private fun load() {
        viewLifecycleOwner.lifecycleScope.launch {
            try {
                val res = Api.fromPrefs(requireContext()).wishlist()
                val arr = res.getJSONArray("items")
                val items = (0 until arr.length()).map { arr.getJSONObject(it) }
                adapter.submit(items)
                val alerts = res.optInt("alerts")
                info.text = if (items.isEmpty()) "Noch keine Wünsche. Mit „＋ Karte wünschen“ hinzufügen – oder am PC im Deck „Fehlende → Wunschliste“."
                else "${items.size} Karten · aktuell ${euro(res.optDouble("total_eur"))}" +
                    if (alerts > 0) " · $alerts unter Zielpreis ✓" else ""
            } catch (e: ApiException) {
                info.text = e.message
            }
        }
    }

    private fun priceField(hint: String, value: String = "") = EditText(requireContext()).apply {
        this.hint = hint
        inputType = InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_FLAG_DECIMAL
        setText(value)
    }

    private fun addWish() {
        val ctx = requireContext()
        val name = EditText(ctx).apply { hint = "Kartenname"; isSingleLine = true }
        val max = priceField("Zielpreis in € (optional)")
        val box = LinearLayout(ctx).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(48, 16, 48, 0)
            addView(name)
            addView(max)
        }
        AlertDialog.Builder(ctx)
            .setTitle("Karte wünschen")
            .setView(box)
            .setPositiveButton("Hinzufügen") { _, _ ->
                val n = name.text.toString().trim()
                if (n.isEmpty()) return@setPositiveButton
                viewLifecycleOwner.lifecycleScope.launch {
                    try {
                        val w = Api.fromPrefs(ctx).wishAdd(n, max.text.toString().trim())
                        Toast.makeText(ctx, "${w.optString("name")} gewünscht", Toast.LENGTH_SHORT).show()
                        load()
                    } catch (e: ApiException) {
                        Toast.makeText(ctx, e.message, Toast.LENGTH_LONG).show()
                    }
                }
            }
            .setNegativeButton("Abbrechen", null)
            .show()
    }

    private fun editWish(w: JSONObject) {
        val ctx = requireContext()
        val current = if (w.isNull("max_price_eur")) "" else w.optDouble("max_price_eur").toString().replace(".", ",")
        val max = priceField("Zielpreis in €", current)
        val qty = EditText(ctx).apply {
            hint = "Anzahl"
            inputType = InputType.TYPE_CLASS_NUMBER
            setText(w.optInt("quantity").toString())
        }
        val box = LinearLayout(ctx).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(48, 16, 48, 0)
            addView(TextView(ctx).apply {
                text = "Aktuell: ${if (w.isNull("price_eur")) "–" else euro(w.optDouble("price_eur"))}" +
                    if (w.optBoolean("any_print") && w.optString("price_set").isNotBlank()) " (${w.optString("price_set")})" else ""
            })
            addView(max)
            addView(qty)
        }
        AlertDialog.Builder(ctx)
            .setTitle(w.optString("name"))
            .setView(box)
            .setPositiveButton("Speichern") { _, _ ->
                update(w.optLong("id"), JSONObject().put("max_price_eur", max.text.toString().trim())
                    .put("quantity", qty.text.toString().toIntOrNull() ?: 1))
            }
            .setNeutralButton("Entfernen") { _, _ ->
                viewLifecycleOwner.lifecycleScope.launch {
                    try { Api.fromPrefs(ctx).wishDelete(w.optLong("id")); load() } catch (e: ApiException) {
                        Toast.makeText(ctx, e.message, Toast.LENGTH_LONG).show()
                    }
                }
            }
            .setNegativeButton("Abbrechen", null)
            .show()
    }

    private fun update(id: Long, changes: JSONObject) {
        viewLifecycleOwner.lifecycleScope.launch {
            try {
                Api.fromPrefs(requireContext()).wishUpdate(id, changes)
                load()
            } catch (e: ApiException) {
                Toast.makeText(requireContext(), e.message, Toast.LENGTH_LONG).show()
            }
        }
    }
}

class WishAdapter(
    private val scope: CoroutineScope,
    private val onClick: (JSONObject) -> Unit,
) : RecyclerView.Adapter<WishAdapter.VH>() {
    private var items: List<JSONObject> = emptyList()

    fun submit(list: List<JSONObject>) {
        items = list
        notifyDataSetChanged()
    }

    class VH(v: View) : RecyclerView.ViewHolder(v) {
        val image: ImageView = v.findViewById(R.id.itemImage)
        val name: TextView = v.findViewById(R.id.itemName)
        val type: TextView = v.findViewById(R.id.itemType)
        val sub: TextView = v.findViewById(R.id.itemSub)
        val qty: TextView = v.findViewById(R.id.itemQty)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int) =
        VH(LayoutInflater.from(parent.context).inflate(R.layout.item_card, parent, false))

    override fun getItemCount() = items.size

    override fun onBindViewHolder(h: VH, position: Int) {
        val w = items[position]
        val reached = w.optBoolean("target_reached")
        h.name.text = w.optString("name") + if (w.optBoolean("foil")) " ✦" else ""
        val price = if (w.isNull("price_eur")) "–" else euro(w.optDouble("price_eur"))
        val target = if (w.isNull("max_price_eur")) "kein Zielpreis" else "Ziel ${euro(w.optDouble("max_price_eur"))}"
        h.type.text = "Aktuell $price · $target"
        h.type.setTextColor(if (reached) Color.rgb(63, 185, 80) else h.sub.currentTextColor)
        h.sub.text = when {
            reached -> "✓ Zielpreis erreicht"
            w.optInt("owned") > 0 -> "${w.optInt("owned")} bereits in der Sammlung"
            w.optBoolean("any_print") -> "beliebiger Druck"
            else -> "${w.optString("set_code")} #${w.optString("collector_number")}"
        }
        h.qty.text = "${w.optInt("quantity")}×"
        ImageLoader.load(scope, w.optString("image_url"), h.image, 4)
        h.itemView.setOnClickListener { onClick(w) }
    }
}
