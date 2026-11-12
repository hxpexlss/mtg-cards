package de.mtgcards.scanner

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.util.LruCache
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import kotlin.math.sqrt

/**
 * Unterscheidet Drucke mit verschiedenem Artwork: vergleicht den Bildbereich der gescannten Karte
 * mit den Artwork-Ausschnitten (art_crop) der Drucke von Scryfall.
 *
 * Verglichen wird ein grobes Farbraster (16 x 10, je Farbkanal normiert) – unempfindlich gegen
 * Helligkeit, Weißabgleich und leichte Verschiebung, unterscheidet aber verschiedene Bilder gut.
 */
object ArtMatcher {
    private const val W = 16
    private const val H = 10

    /** Lage des Artworks auf der Karte (relativ), etwas nach innen gezogen. */
    const val CARD_LEFT = 0.12f
    const val CARD_RIGHT = 0.88f
    const val CARD_TOP = 0.14f
    const val CARD_BOTTOM = 0.52f

    /** Derselbe Ausschnitt innerhalb von Scryfalls art_crop (Artwork-Box ≈ x 8–92 %, y 11–55,5 % der Karte). */
    private const val ART_LEFT = 0.05f
    private const val ART_RIGHT = 0.95f
    private const val ART_TOP = 0.07f
    private const val ART_BOTTOM = 0.92f

    private val sigCache = LruCache<String, FloatArray>(200)

    data class Match(val print: JSONObject, val score: Float, val margin: Float)

    /** Signatur des Kamera-Ausschnitts (bereits auf das Artwork zugeschnitten). */
    fun signature(art: Bitmap): FloatArray {
        val small = Bitmap.createScaledBitmap(art, W, H, true)
        val px = IntArray(W * H)
        small.getPixels(px, 0, W, 0, 0, W, H)
        if (small !== art) small.recycle()
        val out = FloatArray(W * H * 3)
        for (i in px.indices) {
            out[i] = ((px[i] shr 16) and 0xFF).toFloat()
            out[W * H + i] = ((px[i] shr 8) and 0xFF).toFloat()
            out[2 * W * H + i] = (px[i] and 0xFF).toFloat()
        }
        // je Kanal auf Mittelwert 0 / Streuung 1 normieren (Belichtung, Weißabgleich)
        for (c in 0 until 3) {
            val off = c * W * H
            var mean = 0f
            for (i in 0 until W * H) mean += out[off + i]
            mean /= W * H
            var v = 0f
            for (i in 0 until W * H) { val d = out[off + i] - mean; v += d * d }
            val sd = sqrt(v / (W * H)).coerceAtLeast(4f)
            for (i in 0 until W * H) out[off + i] = (out[off + i] - mean) / sd
        }
        return out
    }

    /** Korrelation zweier Signaturen (-1..1). */
    fun similarity(a: FloatArray, b: FloatArray): Float {
        var s = 0f
        for (i in a.indices) s += a[i] * b[i]
        return s / a.size
    }

    private suspend fun artSignature(url: String): FloatArray? {
        sigCache.get(url)?.let { return it }
        val bmp = withContext(Dispatchers.IO) {
            try {
                val conn = URL(url).openConnection() as HttpURLConnection
                conn.connectTimeout = 6000
                conn.readTimeout = 10000
                conn.setRequestProperty("User-Agent", "MTGCardsScanner/1.0")
                conn.inputStream.use { BitmapFactory.decodeStream(it, null, BitmapFactory.Options().apply { inSampleSize = 2 }) }
            } catch (e: Exception) {
                null
            }
        } ?: return null
        val inner = Bitmap.createBitmap(bmp, (bmp.width * ART_LEFT).toInt(), (bmp.height * ART_TOP).toInt(),
            (bmp.width * (ART_RIGHT - ART_LEFT)).toInt().coerceAtLeast(1),
            (bmp.height * (ART_BOTTOM - ART_TOP)).toInt().coerceAtLeast(1))
        val sig = signature(inner)
        inner.recycle()
        bmp.recycle()
        sigCache.put(url, sig)
        return sig
    }

    /**
     * Bestes Artwork unter den Drucken. Gibt null zurück, wenn es nur ein Artwork gibt
     * oder der Vergleich nicht eindeutig ist.
     */
    suspend fun best(photo: FloatArray, prints: List<JSONObject>): Match? = coroutineScope {
        val groups = prints
            .filter { it.optString("art_url").let { u -> u.isNotBlank() && u != "null" } }
            .groupBy { it.optString("illustration_id").ifBlank { it.optString("art_url") } }
        if (groups.size < 2) return@coroutineScope null
        val reps = groups.values.map { it.last() }.take(10)          // je Artwork ein Druck (der neueste)
        val scored = reps.map { p -> async { artSignature(p.optString("art_url"))?.let { p to similarity(photo, it) } } }
            .awaitAll().filterNotNull().sortedByDescending { it.second }
        if (scored.isEmpty()) return@coroutineScope null
        val (bestPrint, bestScore) = scored[0]
        val margin = bestScore - (scored.getOrNull(1)?.second ?: -1f)
        if (bestScore < 0.35f || margin < 0.08f) return@coroutineScope null
        Match(bestPrint, bestScore, margin)
    }
}
