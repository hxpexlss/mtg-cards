package de.mtgcards.scanner

import android.content.Context
import android.net.Uri
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

class ApiException(message: String, val code: Int = 0) : Exception(message)

/** Client für die REST-API von Desktop-App bzw. Headless-Server. */
class Api(private val baseUrl: String, private val token: String) {

    companion object {
        const val DEFAULT_PORT = 8765

        fun fromPrefs(ctx: Context): Api = Api(Prefs.serverUrl(ctx), Prefs.token(ctx))

        /** "192.168.1.5" -> "http://192.168.1.5:8765" */
        fun normalizeUrl(input: String): String {
            var s = input.trim().trimEnd('/')
            if (s.isEmpty()) return s
            if (!s.startsWith("http://") && !s.startsWith("https://")) s = "http://$s"
            val uri = Uri.parse(s)
            if (uri.port == -1 && uri.scheme == "http" && uri.host != null) {
                s = "http://${uri.host}:$DEFAULT_PORT${uri.path ?: ""}"
            }
            return s.trimEnd('/')
        }

        private fun enc(s: String) = URLEncoder.encode(s, "UTF-8")
    }

    private suspend fun request(method: String, path: String, body: JSONObject? = null): String =
        withContext(Dispatchers.IO) {
            if (baseUrl.isBlank()) {
                throw ApiException("Kein Server eingestellt – bitte unter Einstellungen eintragen")
            }
            var conn: HttpURLConnection? = null
            try {
                conn = URL(baseUrl + path).openConnection() as HttpURLConnection
                conn.requestMethod = method
                conn.connectTimeout = 6000
                conn.readTimeout = 30000
                conn.setRequestProperty("Authorization", "Bearer $token")
                conn.setRequestProperty("Accept", "application/json")
                if (body != null) {
                    conn.doOutput = true
                    conn.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                    conn.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
                }
                val code = conn.responseCode
                val stream = if (code in 200..299) conn.inputStream else conn.errorStream
                val text = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } ?: ""
                if (code !in 200..299) {
                    val msg = try { JSONObject(text).optString("error") } catch (e: Exception) { "" }
                    throw ApiException(msg.ifBlank { "HTTP-Fehler $code" }, code)
                }
                text
            } catch (e: IOException) {
                throw ApiException("Server nicht erreichbar (${e.message ?: e.javaClass.simpleName})")
            } finally {
                conn?.disconnect()
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

    suspend fun lookup(name: String?, setCode: String? = null, cn: String? = null): JSONObject {
        val q = buildList {
            if (!name.isNullOrBlank()) add("name=${enc(name)}")
            if (!setCode.isNullOrBlank()) add("set=${enc(setCode)}")
            if (!cn.isNullOrBlank()) add("cn=${enc(cn)}")
        }.joinToString("&")
        return json("GET", "/api/lookup?$q")
    }

    suspend fun addCard(scryfallId: String, quantity: Int, foil: Boolean): JSONObject =
        json("POST", "/api/cards", JSONObject().apply {
            put("scryfall_id", scryfallId)
            put("quantity", quantity)
            put("foil", foil)
        })

    suspend fun search(q: String, ci: String, tag: String, sort: String = "name"): JSONObject {
        val params = buildList {
            if (q.isNotBlank()) add("q=${enc(q)}")
            if (ci.isNotBlank()) add("ci=${enc(ci)}")
            if (tag.isNotBlank()) add("tag=${enc(tag)}")
            add("sort=$sort")
            add("limit=1000")
        }.joinToString("&")
        return json("GET", "/api/cards?$params")
    }

    suspend fun card(id: Long) = json("GET", "/api/cards/$id")

    /** PUT wird vom Server wie PATCH behandelt (HttpURLConnection kann kein PATCH). */
    suspend fun update(id: Long, changes: JSONObject) = json("PUT", "/api/cards/$id", changes)

    suspend fun delete(id: Long) = json("DELETE", "/api/cards/$id")
}
