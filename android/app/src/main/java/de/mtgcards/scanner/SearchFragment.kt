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
    private var tag = ""
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

        val colorGroup = view.findViewById<ChipGroup>(R.id.colorChips)
        for ((code, label) in listOf("W" to "Weiß", "U" to "Blau", "B" to "Schwarz", "R" to "Rot", "G" to "Grün", "C" to "Farblos")) {
            colorGroup.addView(Chip(requireContext()).apply {
                text = label
                isCheckable = true
                setOnCheckedChangeListener { _, checked ->
                    if (checked) colors.add(code) else colors.remove(code)
                    search()
                }
            })
        }
        val tagGroup = view.findViewById<ChipGroup>(R.id.tagChips)
        for (t in listOf("Commander", "Partner", "Companion")) {
            tagGroup.addView(Chip(requireContext()).apply {
                text = t
                isCheckable = true
                setOnCheckedChangeListener { _, checked ->
                    if (checked) {
                        tag = t
                        for (i in 0 until tagGroup.childCount) {
                            val other = tagGroup.getChildAt(i) as Chip
                            if (other !== this && other.text.toString() in listOf("Commander", "Partner", "Companion")) {
                                other.isChecked = false
                            }
                        }
                    } else if (tag == t) {
                        tag = ""
                    }
                    search()
                }
            })
        }
        tagGroup.isSingleSelection = false
        tagGroup.addView(Chip(requireContext()).apply {
            text = "Doppelte (ab 2)"
            isCheckable = true
            setOnCheckedChangeListener { _, checked ->
                dupMin = if (checked) 2 else 0
                search()
            }
        })
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
                val res = Api.fromPrefs(requireContext()).search(input.text.toString(), colors.joinToString(""), tag,
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
        holder.qty.text = "${c.optInt("quantity")}×" + if (c.optBoolean("foil")) " ✦" else ""
        ImageLoader.load(scope, c.optString("image_url"), holder.image, 4)
        holder.itemView.setOnClickListener { onClick(c.optLong("id")) }
    }
}
