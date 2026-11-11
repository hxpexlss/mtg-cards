package de.mtgcards.scanner

import java.text.Normalizer

/** Eine erkannte Textzeile mit Bounding-Box (Bildkoordinaten). */
data class OcrLine(val text: String, val left: Int, val top: Int, val right: Int, val bottom: Int) {
    val cx get() = (left + right) / 2f
    val cy get() = (top + bottom) / 2f
}

data class Region(val left: Float, val top: Float, val right: Float, val bottom: Float) {
    fun contains(x: Float, y: Float) = x in left..right && y in top..bottom
}

data class ScanResult(val name: String?, val setCode: String?, val collectorNumber: String?)

/**
 * Wertet OCR-Text einer Magic-Karte aus.
 *  - Name: oberste Textzeile im Namensbereich (oberer Rand der Karte)
 *  - Set-Code + Sammlernummer: unten links (z.B. "123/280 R" und "DMU • EN"), best effort
 */
object CardTextParser {
    private val CN_SLASH = Regex("""\b0*(\d{1,4}[a-z]?)\s*/\s*\d{1,4}\b""")
    private val CN_RARITY_BEFORE = Regex("""(?:^|\s)[CURMSLTP]\s+0*(\d{1,4}[a-z]?)\b""")
    private val CN_RARITY_AFTER = Regex("""(?:^|\s)0*(\d{1,4}[a-z]?)\s+[CURMSLTP](?:\s|$)""")
    private val SET_LANG = Regex(
        """\b([A-Z0-9]{3,5})\s*[•·*.\-]?\s*(EN|DE|FR|IT|ES|PT|JA|JP|KO|RU|ZHS|ZHT|CS|CT|PH)\b"""
    )

    fun parse(lines: List<OcrLine>, card: Region): ScanResult {
        val w = card.right - card.left
        val h = card.bottom - card.top
        if (w <= 0 || h <= 0) return ScanResult(null, null, null)

        val nameRegion = Region(card.left - 0.04f * w, card.top - 0.05f * h, card.left + 0.88f * w, card.top + 0.16f * h)
        val name = lines
            .filter { nameRegion.contains(it.cx, it.cy) }
            .sortedBy { it.top }
            .map { cleanName(it.text) }
            .firstOrNull { n -> n.count { it.isLetter() } >= 3 }

        val bottomRegion = Region(card.left - 0.04f * w, card.bottom - 0.13f * h, card.left + 0.65f * w, card.bottom + 0.05f * h)
        val bottom = lines.filter { bottomRegion.contains(it.cx, it.cy) }.joinToString("\n") { it.text }

        val cn = CN_SLASH.find(bottom)?.groupValues?.get(1)
            ?: CN_RARITY_BEFORE.find(bottom)?.groupValues?.get(1)
            ?: CN_RARITY_AFTER.find(bottom)?.groupValues?.get(1)
        val set = SET_LANG.find(bottom.uppercase())?.groupValues?.get(1)?.takeIf { it.any(Char::isLetter) }

        return ScanResult(name?.takeIf { it.isNotBlank() }, set, cn)
    }

    /** Entfernt Mana-Symbole/OCR-Müll: behält nur Wörter, die überwiegend aus Buchstaben bestehen. */
    fun cleanName(raw: String): String {
        val tokens = raw.replace('’', '\'').replace('`', '\'')
            .split(Regex("\\s+"))
            .map { t -> t.trim { c -> !(c.isLetterOrDigit() || c == '\'') } }
            .filter { t ->
                t.isNotEmpty() && (
                    t.all { it.isLetter() || it == '\'' || it == '-' } ||   // normales Wort
                        t.all { it.isDigit() || it == ',' }                  // Zahl, z.B. "100,000"
                    )
            }
        return tokens.joinToString(" ").trim()
    }

    /** Vergleichsschlüssel (ohne Akzente, Satzzeichen, Groß/Klein). */
    fun normalize(s: String): String {
        val n = Normalizer.normalize(s, Normalizer.Form.NFD).replace(Regex("\\p{M}+"), "")
        return n.lowercase().replace(Regex("[^a-z0-9]+"), " ").trim()
    }
}

/** Levenshtein-Ähnlichkeit 0..1 (1 = identisch). */
fun similarity(a: String, b: String): Double {
    if (a == b) return 1.0
    if (a.isEmpty() || b.isEmpty()) return 0.0
    var prev = IntArray(b.length + 1) { it }
    var cur = IntArray(b.length + 1)
    for (i in 1..a.length) {
        cur[0] = i
        for (j in 1..b.length) {
            val cost = if (a[i - 1] == b[j - 1]) 0 else 1
            cur[j] = minOf(cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        }
        val t = prev; prev = cur; cur = t
    }
    return 1.0 - prev[b.length].toDouble() / maxOf(a.length, b.length)
}

/**
 * Bestätigt einen erkannten Namen, sobald ein ähnliches Ergebnis in einem der letzten Frames
 * vorkam. Kleine OCR-Abweichungen ("Atraxa Praetors Voice" / "Atraxa Praetors' Voioe")
 * verhindern die Erkennung dadurch nicht mehr.
 */
class CandidateVoter(private val window: Int = 3, private val threshold: Double = 0.8) {
    private val recent = ArrayDeque<String>()

    fun reset() = recent.clear()

    fun offer(key: String): Boolean {
        val confirmed = recent.any { similarity(it, key) >= threshold }
        recent.addLast(key)
        while (recent.size > window) recent.removeFirst()
        return confirmed
    }
}
