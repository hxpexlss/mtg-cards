package de.mtgcards.scanner

import android.content.Intent
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.ImageView
import android.widget.TextView
import androidx.core.widget.doAfterTextChanged
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.chip.Chip
import com.google.android.material.chip.ChipGroup
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONObject

class SearchFragment : Fragment(R.layout.fragment_search) {

    private lateinit var input: EditText
    private lateinit var count: TextView
    private lateinit var adapter: CardAdapter
    private val colors = linkedSetOf<String>()
    private var tagFilter = ""   // bewusst nicht "tag": kollidiert sonst mit View.tag in apply-Blöcken
    private var dupMin = 0
    private var job: Job? = null

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        input = view.findViewById(R.id.searchInput)
        count = view.findViewById(R.id.count)
        adapter = CardAdapter(viewLifecycleOwner.lifecycleScope) { id ->
            startActivity(Intent(requireContext(), CardDetailActivity::class.java).putExtra("id", id))
        }
        view.findViewById<RecyclerView>(R.id.list).apply {
            layoutManager = LinearLayoutManager(requireContext())
            adapter = this@SearchFragment.adapter
        }

        val inflater = LayoutInflater.from(requireContext())
        fun filterChip(group: ChipGroup, label: String, key: String): Chip =
            (inflater.inflate(R.layout.item_filter_chip, group, false) as Chip).apply {
                id = View.generateViewId()
                text = label
                tag = key          // View-Tag: Filterwert
                group.addView(this)
            }

        // Farben: mehrere gleichzeitig möglich
        val colorGroup = view.findViewById<ChipGroup>(R.id.colorChips)
        for ((code, label) in listOf("W" to "Weiß", "U" to "Blau", "B" to "Schwarz", "R" to "Rot", "G" to "Grün", "C" to "Farblos")) {
            filterChip(colorGroup, label, code)
        }
        colorGroup.setOnCheckedStateChangeListener { group, ids ->
            colors.clear()
            ids.forEach { cid -> group.findViewById<Chip>(cid)?.tag?.let { colors.add(it.toString()) } }
            search()
        }

        // Tags: höchstens einer (singleSelection im Layout)
        val tagGroup = view.findViewById<ChipGroup>(R.id.tagChips)
        for (t in listOf("Commander", "Partner", "Companion", "Token", PROXY_TAG)) filterChip(tagGroup, t, t)
        tagGroup.setOnCheckedStateChangeListener { group, ids ->
            tagFilter = ids.firstOrNull()?.let { group.findViewById<Chip>(it)?.tag?.toString() } ?: ""
            search()
        }

        // Doppelte: unabhängig von den Tags kombinierbar
        val dupGroup = view.findViewById<ChipGroup>(R.id.dupChips)
        filterChip(dupGroup, "Doppelte (ab 2)", "2")
        dupGroup.setOnCheckedStateChangeListener { _, ids ->
            dupMin = if (ids.isNotEmpty()) 2 else 0
            search()
        }
        view.findViewById<android.widget.Button>(R.id.btnSets).setOnClickListener {
            startActivity(Intent(requireContext(), SetsActivity::class.java))
        }

        input.doAfterTextChanged { search(300) }
    }

    override fun onResume() {
        super.onResume()
        search()
    }

    private fun search(delayMs: Long = 0) {
        job?.cancel()
        job = viewLifecycleOwner.lifecycleScope.launch {
            if (delayMs > 0) delay(delayMs)
            try {
                val res = Api.fromPrefs(requireContext()).search(input.text.toString(), colors.joinToString(""), tagFilter,
                    dupMin = dupMin)
                val arr = res.getJSONArray("cards")
                val items = (0 until arr.length()).map { arr.getJSONObject(it) }
                adapter.submit(items)
                val total = items.sumOf { it.optInt("quantity") }
                count.text = "${res.optInt("total")} Einträge · $total Karten" +
                    (if (colors.isNotEmpty()) " · passt in ${colors.joinToString("")}" else "") +
                    (res.optJSONObject("duplicates")?.let { d ->
                        "\n${d.optInt("cards")} Karten doppelt · ${d.optInt("extra_copies")} überzählig · " +
                            "Wert ca. ${euro(d.optDouble("extra_value_eur"))}"
                    } ?: "")
            } catch (e: ApiException) {
                count.text = e.message
            }
        }
    }
}

class CardAdapter(
    private val scope: CoroutineScope,
    private val onClick: (Long) -> Unit,
) : RecyclerView.Adapter<CardAdapter.VH>() {

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

    override fun onBindViewHolder(holder: VH, position: Int) {
        val c = items[position]
        holder.name.text = c.optString("name")
        holder.type.text = "${c.optString("mana_cost")}  ${c.optString("type_line")}".trim()
        val tags = c.optJSONArray("tags")
        val tagText = (0 until (tags?.length() ?: 0)).joinToString(" ") { "#" + tags!!.getString(it) }
        val ci = c.optString("color_identity").ifBlank { "C" }
        holder.sub.text = "${c.optString("set_code")} #${c.optString("collector_number")} · $ci  $tagText"
        holder.qty.text = "${c.optInt("quantity")}×" + (if (c.optBoolean("foil")) " ✦" else "") +
            (if (c.optBoolean("proxy")) " 🅿" else "")
        ImageLoader.load(scope, c.optString("image_url"), holder.image, 4)
        holder.itemView.setOnClickListener { onClick(c.optLong("id")) }
    }
}
