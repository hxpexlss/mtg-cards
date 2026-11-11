package de.mtgcards.scanner

import android.content.Intent
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import kotlinx.coroutines.launch
import org.json.JSONObject

/** Liste der Decks mit Fortschritt (wie viele Karten bereits in der Sammlung sind). */
class DecksFragment : Fragment(R.layout.fragment_decks) {
    private lateinit var info: TextView
    private val adapter = DeckAdapter { id ->
        startActivity(Intent(requireContext(), DeckActivity::class.java).putExtra("id", id))
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        info = view.findViewById(R.id.decksInfo)
        view.findViewById<RecyclerView>(R.id.decksList).apply {
            layoutManager = LinearLayoutManager(requireContext())
            adapter = this@DecksFragment.adapter
        }
    }

    override fun onResume() {
        super.onResume()
        viewLifecycleOwner.lifecycleScope.launch {
            try {
                val arr = Api.fromPrefs(requireContext()).decks().getJSONArray("decks")
                val list = (0 until arr.length()).map { arr.getJSONObject(it) }
                adapter.submit(list)
                info.text = if (list.isEmpty()) "Noch keine Decks. Decks werden am PC angelegt (Tab „Decks“) – " +
                    "z.B. durch Einfügen einer Deckliste aus Moxfield oder Archidekt." else "${list.size} Decks"
            } catch (e: ApiException) {
                info.text = e.message
            }
        }
    }
}

class DeckAdapter(private val onClick: (Long) -> Unit) : RecyclerView.Adapter<DeckAdapter.VH>() {
    private var items: List<JSONObject> = emptyList()

    fun submit(list: List<JSONObject>) {
        items = list
        notifyDataSetChanged()
    }

    class VH(v: View) : RecyclerView.ViewHolder(v) {
        val name: TextView = v.findViewById(R.id.deckName)
        val sub: TextView = v.findViewById(R.id.deckSub)
        val progress: com.google.android.material.progressindicator.LinearProgressIndicator = v.findViewById(R.id.deckProgress)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int) =
        VH(LayoutInflater.from(parent.context).inflate(R.layout.item_deck, parent, false))

    override fun getItemCount() = items.size

    override fun onBindViewHolder(holder: VH, position: Int) {
        val d = items[position]
        val st = d.getJSONObject("stats")
        val cmd = d.optJSONArray("commanders")
        val commanders = (0 until (cmd?.length() ?: 0)).joinToString(" & ") { cmd!!.getString(it) }
        holder.name.text = d.optString("name")
        val missing = st.optInt("missing")
        holder.sub.text = buildString {
            if (commanders.isNotBlank()) append(commanders).append(" · ")
            val ci = d.optString("color_identity")
            if (ci.isNotBlank()) append(ci).append(" · ")
            append("${st.optInt("owned")}/${st.optInt("cards")} vorhanden")
            append(if (missing > 0) " · $missing fehlen" else " · ✓ komplett")
        }
        val cards = st.optInt("cards")
        holder.progress.max = if (cards > 0) cards else 1
        holder.progress.progress = st.optInt("owned")
        holder.itemView.setOnClickListener { onClick(d.optLong("id")) }
    }
}
