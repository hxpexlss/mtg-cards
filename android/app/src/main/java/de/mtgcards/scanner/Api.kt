package de.mtgcards.scanner

import android.content.Context
import android.net.Uri
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLException

class ApiException(message: String, val code: Int = 0) : Exception(message)

/** Client für die REST-API von Desktop-App bzw. Headless-Server. */
class Api(private val baseUrl: String, private val token: String, private val fingerprint: String = "") {

    companion object {
        const val DEFAULT_PORT = 8765
        /** Fehlercode: Server nicht erreichbar (Netzwerk). */
        const val UNREACHABLE = 0
        const val NOT_CONFIGURED = -1
        /** HTTPS-Zertifikat unbekannt -> Fingerabdruck bestätigen lassen. */
        const val TLS_UNTRUSTED = -2

        fun fromPrefs(ctx: Context): Api = Api(Prefs.serverUrl(ctx), Prefs.token(ctx), Prefs.fingerprint(ctx))

        /** "192.168.1.5" -> "http://192.168.1.5:8765" */
        fun normalizeUrl(input: String): String {
            var s = input.trim().trimEnd('/')
            if (s.isEmpty()) return s
            if (!s.startsWith("http://") && !s.startsWith("https://")) s = "http://$s"
            val uri = Uri.parse(s)
            if (uri.port == -1 && uri.host != null) {
                s = "${uri.scheme}://${uri.host}:$DEFAULT_PORT${uri.path ?: ""}"
            }
            return s.trimEnd('/')
        }

        private fun enc(s: String) = URLEncoder.encode(s, "UTF-8")
    }

    /**
     * HTTP-Anfrage mit automatischer Wiederholung bei Netzwerkfehlern (z.B. Tailscale wacht gerade auf,
     * WLAN/Mobilfunk-Wechsel). POST wird nur wiederholt, wenn die Anfrage den Server noch nicht erreicht hat,
     * damit keine Karten doppelt gespeichert werden.
     */
    private suspend fun request(method: String, path: String, body: JSONObject? = null): String {
        if (baseUrl.isBlank()) {
            throw ApiException("Kein Server eingestellt – bitte unter Einstellungen eintragen", NOT_CONFIGURED)
        }
        var lastError: IOException? = null
        var attempts = 0
        for (attempt in 0 until 3) {
            if (attempt > 0) delay(if (attempt == 1) 800L else 2500L)
            attempts++
            val sent = booleanArrayOf(false)
            try {
                val text = withContext(Dispatchers.IO) { doRequest(method, path, body, sent) }
                ConnectionLog.ok(attempt)
                return text
            } catch (e: SSLException) {
                ConnectionLog.error(path, "Zertifikat abgelehnt", attempts)
                throw ApiException("Zertifikat des Servers ist nicht vertrauenswürdig oder hat sich geändert", TLS_UNTRUSTED)
            } catch (e: IOException) {
                lastError = e
                if (sent[0] && method == "POST") break   // Server hat die Anfrage evtl. schon verarbeitet
            }
        }
        val msg = lastError?.let { it.message ?: it.javaClass.simpleName } ?: "unbekannt"
        ConnectionLog.error(path, "${lastError?.javaClass?.simpleName}: $msg", attempts)
        throw ApiException("Server nicht erreichbar ($msg)")
    }

    private fun doRequest(method: String, path: String, body: JSONObject?, sent: BooleanArray): String {
        val conn = URL(baseUrl + path).openConnection() as HttpURLConnection
        try {
            if (conn is HttpsURLConnection) Tls.configure(conn, fingerprint)
            conn.requestMethod = method
            conn.connectTimeout = 10000      // Tailscale braucht nach Funkstille manchmal ein paar Sekunden
            conn.readTimeout = 45000         // Scryfall-Abfragen des Servers können dauern
            conn.useCaches = false
            conn.setRequestProperty("Connection", "close")   // keine abgerissenen Verbindungen wiederverwenden
            conn.setRequestProperty("Authorization", "Bearer $token")
            conn.setRequestProperty("Accept", "application/json")
            if (body != null) {
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                conn.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
            } else {
                conn.connect()
            }
            sent[0] = true
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val text = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } ?: ""
            if (code !in 200..299) {
                val msg = try { JSONObject(text).optString("error") } catch (e: Exception) { "" }
                throw ApiException(msg.ifBlank { "HTTP-Fehler $code" }, code)
            }
            return text
        } finally {
            conn.disconnect()
        }
    }

    private suspend fun json(method: String, path: String, body: JSONObject? = null) =
        JSONObject(request(method, path, body))

    suspend fun health() = json("GET", "/api/health")

    /** Prüft Erreichbarkeit UND Token. */
    suspend fun check(): JSONObject {
        val health = health()
        if (health.optString("app") != "mtg-cards") throw ApiException("Gegenstelle ist kein MTG-Cards-Server")
        json("GET", "/api/revision")
        return health
    }

    suspend fun lookup(name: String?, setCode: String? = null, cn: String? = null,
                       alternatives: List<String> = emptyList(), lang: String? = null,
                       scryfallId: String? = null, preferSet: String? = null,
                       total: String? = null, artist: String? = null, year: String? = null): JSONObject {
        val q = buildList {
            if (!total.isNullOrBlank()) add("total=${enc(total)}")
            if (!artist.isNullOrBlank()) add("artist=${enc(artist)}")
            if (!year.isNullOrBlank()) add("year=${enc(year)}")
            if (!preferSet.isNullOrBlank()) add("prefer_set=${enc(preferSet)}")
            if (!scryfallId.isNullOrBlank()) add("id=${enc(scryfallId)}")
            if (!lang.isNullOrBlank()) add("lang=${enc(lang)}")
            if (!name.isNullOrBlank()) add("name=${enc(name)}")
            alternatives.forEach { add("alt=${enc(it)}") }
            if (!setCode.isNullOrBlank()) add("set=${enc(setCode)}")
            if (!cn.isNullOrBlank()) add("cn=${enc(cn)}")
        }.joinToString("&")
        return json("GET", "/api/lookup?$q")
    }

    suspend fun addCard(scryfallId: String, quantity: Int, foil: Boolean, tags: List<String> = emptyList(),
                        deckId: Long = 0L): JSONObject =
        json("POST", "/api/cards", JSONObject().apply {
            put("scryfall_id", scryfallId)
            if (deckId > 0) put("deck_id", deckId)
            put("quantity", quantity)
            put("foil", foil)
            if (tags.isNotEmpty()) put("tags", org.json.JSONArray(tags))
        })

    /** Hinzufügen per Name (+ optional Set/Nummer) – der Server schlägt bei Scryfall nach. */
    suspend fun addByName(name: String, setCode: String?, cn: String?, quantity: Int, foil: Boolean,
                          lang: String? = null, tags: List<String> = emptyList(), deckId: Long = 0L): JSONObject =
        json("POST", "/api/cards", JSONObject().apply {
            put("name", name)
            if (deckId > 0) put("deck_id", deckId)
            if (tags.isNotEmpty()) put("tags", org.json.JSONArray(tags))
            if (!lang.isNullOrBlank()) put("lang", lang)
            if (!setCode.isNullOrBlank()) put("set", setCode)
            if (!cn.isNullOrBlank()) put("cn", cn)
            put("quantity", quantity)
            put("foil", foil)
        })

    suspend fun search(q: String, ci: String, tag: String, sort: String = "name", dupMin: Int = 0): JSONObject {
        val params = buildList {
            if (dupMin > 1) add("dup_min=$dupMin")
            if (q.isNotBlank()) add("q=${enc(q)}")
            if (ci.isNotBlank()) add("ci=${enc(ci)}")
            if (tag.isNotBlank()) add("tag=${enc(tag)}")
            add("sort=$sort")
            add("limit=1000")
        }.joinToString("&")
        return json("GET", "/api/cards?$params")
    }

    suspend fun card(id: Long) = json("GET", "/api/cards/$id")

    suspend fun decks() = json("GET", "/api/decks")

    /** Alle Drucke einer Karte (Edition, Nummer, Preis) – für "Druck ändern". */
    suspend fun prints(name: String, lang: String? = null) =
        json("GET", "/api/prints?name=${enc(name)}" + (lang?.takeIf { it.isNotBlank() && it != "en" }?.let { "&lang=${enc(it)}" } ?: ""))

    /** Anderen Druck (Edition/Sprache) für einen Sammlungseintrag übernehmen. */
    suspend fun changePrint(id: Long, scryfallId: String) =
        json("PUT", "/api/cards/$id", JSONObject().put("scryfall_id", scryfallId))

    suspend fun sets() = json("GET", "/api/sets")

    suspend fun set(code: String) = json("GET", "/api/sets/${enc(code)}")

    /** Binärdaten laden (z.B. Proxy-PDF). */
    suspend fun download(path: String): ByteArray = withContext(Dispatchers.IO) {
        if (baseUrl.isBlank()) throw ApiException("Kein Server eingestellt", NOT_CONFIGURED)
        var conn: HttpURLConnection? = null
        try {
            conn = URL(baseUrl + path).openConnection() as HttpURLConnection
            if (conn is HttpsURLConnection) Tls.configure(conn, fingerprint)
            conn.connectTimeout = 6000
            conn.readTimeout = 180000          // Kartenbilder werden serverseitig geladen
            conn.setRequestProperty("Authorization", "Bearer $token")
            val code = conn.responseCode
            if (code !in 200..299) {
                val text = conn.errorStream?.bufferedReader()?.use { it.readText() } ?: ""
                val msg = try { JSONObject(text).optString("error") } catch (e: Exception) { "" }
                throw ApiException(msg.ifBlank { "HTTP-Fehler $code" }, code)
            }
            conn.inputStream.use { it.readBytes() }
        } catch (e: SSLException) {
            throw ApiException("Zertifikat des Servers ist nicht vertrauenswürdig", TLS_UNTRUSTED)
        } catch (e: IOException) {
            throw ApiException("Server nicht erreichbar (${e.message ?: e.javaClass.simpleName})")
        } finally {
            conn?.disconnect()
        }
    }

    suspend fun wishlist() = json("GET", "/api/wishlist")

    suspend fun wishAdd(name: String, maxPrice: String, quantity: Int = 1) = json("POST", "/api/wishlist", JSONObject().apply {
        put("name", name)
        put("quantity", quantity)
        if (maxPrice.isNotBlank()) put("max_price_eur", maxPrice)
    })

    suspend fun wishUpdate(id: Long, changes: JSONObject) = json("PUT", "/api/wishlist/$id", changes)

    suspend fun wishDelete(id: Long) = json("DELETE", "/api/wishlist/$id")

    /** Stapel-Scan: alle Karten auf einmal speichern. */
    suspend fun addBatch(cards: org.json.JSONArray) = json("POST", "/api/cards/batch", JSONObject().put("cards", cards))

    suspend fun deck(id: Long) = json("GET", "/api/decks/$id")

    /** Karte im Deck ändern: {"board": "commander"|"companion"|"main"|"side"} oder {"quantity": n}. */
    suspend fun deckCardUpdate(id: Long, changes: JSONObject) = json("PUT", "/api/deck-cards/$id", changes)

    suspend fun deckCardDelete(id: Long) = json("DELETE", "/api/deck-cards/$id")

    /** Deck ändern (z.B. Status "owned" = Besitz / "build" = Bau). */
    suspend fun deckUpdate(id: Long, changes: JSONObject) = json("PUT", "/api/decks/$id", changes)

    suspend fun deckMissingText(id: Long) = request("GET", "/api/decks/$id/export?missing=1")

    /** PUT wird vom Server wie PATCH behandelt (HttpURLConnection kann kein PATCH). */
    suspend fun update(id: Long, changes: JSONObject) = json("PUT", "/api/cards/$id", changes)

    suspend fun delete(id: Long) = json("DELETE", "/api/cards/$id")
}
