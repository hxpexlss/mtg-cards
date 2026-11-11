package de.mtgcards.scanner

import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import androidx.appcompat.app.AlertDialog
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import com.google.android.material.materialswitch.MaterialSwitch
import kotlinx.coroutines.launch

class SettingsFragment : Fragment(R.layout.fragment_settings) {

    private lateinit var url: EditText
    private lateinit var token: EditText
    private lateinit var result: TextView

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        url = view.findViewById(R.id.serverUrl)
        token = view.findViewById(R.id.token)
        result = view.findViewById(R.id.result)
        url.setText(Prefs.serverUrl(requireContext()))
        token.setText(Prefs.token(requireContext()))

        view.findViewById<MaterialSwitch>(R.id.autoAddSetting).apply {
            isChecked = Prefs.autoAdd(requireContext())
            setOnCheckedChangeListener { _, c -> Prefs.setAutoAdd(requireContext(), c) }
        }
        view.findViewById<Button>(R.id.btnSave).setOnClickListener { saveAndTest() }
        view.findViewById<Button>(R.id.btnDiscover).setOnClickListener { discover() }
    }

    private fun saveAndTest() {
        val u = Api.normalizeUrl(url.text.toString())
        val t = token.text.toString().trim().uppercase()
        url.setText(u)
        result.text = "Teste Verbindung …"
        viewLifecycleOwner.lifecycleScope.launch {
            try {
                val health = Api(u, t).check()
                Prefs.saveServer(requireContext(), u, t)
                val kind = if (health.optString("kind") == "server") "Server" else "PC"
                val mode = if (health.optString("mode") == "remote") " (leitet an Headless-Server weiter)" else ""
                result.text = "✓ Verbunden mit $kind „${health.optString("name")}“$mode – Version ${health.optString("version")}"
            } catch (e: ApiException) {
                // trotzdem speichern, damit man es später erneut versuchen kann
                Prefs.saveServer(requireContext(), u, t)
                result.text = "✗ ${e.message}" + if (e.code == 401) "\nToken prüfen (am PC unter Einstellungen sichtbar)." else ""
            }
        }
    }

    private fun discover() {
        result.text = "Suche im WLAN …"
        viewLifecycleOwner.lifecycleScope.launch {
            val found = try { Discovery.discover() } catch (e: Exception) { emptyList() }
            if (found.isEmpty()) {
                result.text = "Nichts gefunden. Läuft MTG Cards am PC/Server und ist das Handy im selben WLAN?\n" +
                    "Über Tailscale bitte die 100.x.y.z-Adresse oder den MagicDNS-Namen eintragen."
                return@launch
            }
            result.text = "${found.size} gefunden"
            AlertDialog.Builder(requireContext())
                .setTitle("Gefundene Geräte")
                .setItems(found.map { it.label }.toTypedArray()) { _, i ->
                    url.setText(found[i].url)
                    result.text = "Adresse übernommen – Token eingeben und „Speichern & testen“ tippen."
                    token.requestFocus()
                }
                .show()
        }
    }
}
