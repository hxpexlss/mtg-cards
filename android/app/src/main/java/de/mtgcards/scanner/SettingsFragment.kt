package de.mtgcards.scanner

import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
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
        view.findViewById<MaterialSwitch>(R.id.soundSetting).apply {
            isChecked = Prefs.sound(requireContext())
            setOnCheckedChangeListener { _, c -> Prefs.setSound(requireContext(), c) }
        }
        val log = view.findViewById<TextView>(R.id.connLog)
        log.text = ConnectionLog.summary()
        view.findViewById<Button>(R.id.connLogClear).setOnClickListener {
            ConnectionLog.clear()
            log.text = ConnectionLog.summary()
        }
        view.findViewById<Button>(R.id.btnSave).setOnClickListener { saveAndTest() }
        view.findViewById<Button>(R.id.btnDiscover).setOnClickListener { discover() }
    }

    private fun saveAndTest(fingerprint: String? = null) {
        val u = Api.normalizeUrl(url.text.toString())
        val t = cleanToken(token.text.toString())
        token.setText(t)
        url.setText(u)
        val ctx = requireContext()
        // Fingerabdruck nur behalten, wenn die Adresse gleich bleibt
        val fp = fingerprint ?: if (u == Prefs.serverUrl(ctx)) Prefs.fingerprint(ctx) else ""
        result.text = "Teste Verbindung …"
        viewLifecycleOwner.lifecycleScope.launch {
            try {
                val health = Api(u, t, fp).check()
                Prefs.saveServer(ctx, u, t, fp)
                val kind = if (health.optString("kind") == "server") "Server" else "PC"
                val mode = if (health.optString("mode") == "remote") " (leitet an Headless-Server weiter)" else ""
                val lock = if (u.startsWith("https")) "🔒 " else ""
                result.text = "✓ ${lock}Verbunden mit $kind „${health.optString("name")}“$mode – Version ${health.optString("version")}"
            } catch (e: ApiException) {
                if (e.code == Api.TLS_UNTRUSTED && fingerprint == null) {
                    confirmFingerprint(u)
                    return@launch
                }
                // trotzdem speichern, damit man es später erneut versuchen kann
                Prefs.saveServer(ctx, u, t, fp)
                result.text = "✗ ${e.message}" + if (e.code == 401) "\nToken prüfen (am PC unter Einstellungen sichtbar)." else ""
            }
        }
    }

    /** Selbstsigniertes Zertifikat: Fingerabdruck anzeigen und bestätigen lassen (einmalig). */
    private fun confirmFingerprint(u: String) {
        viewLifecycleOwner.lifecycleScope.launch {
            val fp = try { Tls.fetchFingerprint(u) } catch (e: ApiException) {
                result.text = "✗ ${e.message}"
                return@launch
            }
            AlertDialog.Builder(requireContext())
                .setTitle("Zertifikat bestätigen")
                .setMessage("Der Server verwendet ein eigenes Zertifikat. Stimmt dieser Fingerabdruck mit dem am PC " +
                    "(⚙ Einstellungen) bzw. „sudo mtg-cards-server --show-fingerprint“ überein?\n\n$fp")
                .setPositiveButton("Ja, vertrauen") { _, _ -> saveAndTest(fp) }
                .setNegativeButton("Nein", null)
                .show()
            result.text = "Bitte Fingerabdruck vergleichen"
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
                    if (found[i].tls) {
                        Toast.makeText(requireContext(), "Verschlüsselt (HTTPS) – Fingerabdruck wird beim Speichern abgefragt",
                            Toast.LENGTH_LONG).show()
                    }
                    result.text = "Adresse übernommen – Token eingeben und „Speichern & testen“ tippen."
                    token.requestFocus()
                }
                .show()
        }
    }
}
