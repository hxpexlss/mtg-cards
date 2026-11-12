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

data class CodeResult(val setCode: String?, val collectorNumber: String?, val lang: String?, val raw: String = "",
                      /** Kartenanzahl der Edition aus "123/249" (alte Rahmen 2003–2014). */
                      val total: String? = null)

/** Hinweise vom unteren Rand alter Karten: Künstler ("Illus. …") und Jahr ("© 1995 Wizards …"). */
data class OldCardHints(val artist: String?, val year: String?)

data class ScanResult(
    val name: String?,
    val setCode: String?,
    val collectorNumber: String?,
    /** Weitere Namenskandidaten (z.B. bei Showcase-/randlosen Karten), werden vom Server nacheinander probiert. */
    val alternatives: List<String> = emptyList(),
    /** Sprachcode vom Kartenrand (z.B. "DMU • DE" -> "de"), falls lesbar. */
    val lang: String? = null,
    /** Alte Karten: Kartenanzahl der Edition ("123/249"), Künstler und Copyright-Jahr. */
    val total: String? = null,
    val artist: String? = null,
    val year: String? = null,
)

/**
 * Wertet OCR-Text einer Magic-Karte aus.
 *  - Name: oberste Textzeile im Namensbereich (oberer Rand der Karte)
 *  - Set-Code + Sammlernummer: unten links (z.B. "123/280 R" und "DMU • EN"), best effort
 */
object CardTextParser {
    private val CN_SLASH = Regex("""\b0*(\d{1,4}[a-z]?)\s*/\s*0*(\d{1,4})\b""")
    private val ILLUS = Regex("""(?i)\billus(?:trated)?\.?\s*(?:by\s+)?(?:[©@]\s*\d{4}\s*)?([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ.'\- &]{2,40})""")
    private val YEAR = Regex("""(?:[©@]|\([cC]\)|\bC)\s*(?:(?:19|20)\d{2}\s*[-–]\s*)?((?:199|20[0-3])\d)\b""")
    private val CN_RARITY_BEFORE = Regex("""(?:^|\s)[CURMSLTP]\s+0*(\d{1,4}[a-z]?)\b""")
    private val CN_RARITY_AFTER = Regex("""(?:^|\s)0*(\d{1,4}[a-z]?)\s+[CURMSLTP](?:\s|$)""")
    /** Neue Kartenrahmen: Nummer mit führender Null, z.B. "0077" (ohne "/Gesamtzahl"). */
    private val CN_PADDED = Regex("""(?:^|\s)(0\d{2,3}[a-z]?)(?:\s|$)""")
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

        // Erweiterter Bereich (oberes Drittel + Typzeilen-Höhe bei Showcase-Rahmen): größte Schrift zuerst
        val wideRegion = Region(card.left - 0.04f * w, card.top - 0.05f * h, card.right + 0.04f * w, card.top + 0.30f * h)
        val alternatives = lines
            .filter { wideRegion.contains(it.cx, it.cy) }
            .sortedByDescending { it.bottom - it.top }
            .map { cleanName(it.text) }
            .filter { n -> n.count { it.isLetter() } >= 3 && n != name }
            .distinct()
            .take(3)

        val bottomRegion = Region(card.left - 0.04f * w, card.bottom - 0.13f * h, card.left + 0.65f * w, card.bottom + 0.05f * h)
        val code = collectorInfo(lines.filter { bottomRegion.contains(it.cx, it.cy) })
        val set = code.setCode
        val cn = code.collectorNumber
        val lang = code.lang

        // Alte Karten: Künstler + Jahr stehen zentriert am unteren Rand (ganze Breite)
        val footer = Region(card.left - 0.04f * w, card.bottom - 0.12f * h, card.right + 0.04f * w, card.bottom + 0.05f * h)
        val hints = oldCardHints(lines.filter { footer.contains(it.cx, it.cy) })

        var primary = name?.takeIf { it.isNotBlank() } ?: alternatives.firstOrNull()
        // Emblem-Karten: oben steht nur "Emblem", der Planeswalker steht in der Typzeile ("Emblem — Chandra")
        val inCard = lines.filter { card.contains(it.cx, it.cy) }
        if (inCard.any { normalize(it.text) == "emblem" }) {
            primary = inCard.map { cleanName(it.text) }
                .firstOrNull { normalize(it).startsWith("emblem ") } ?: "Emblem"
        }
        return ScanResult(primary, set, cn, alternatives.filter { it != primary }, lang,
            code.total, hints.artist, hints.year)
    }

    /** "Illus. Christopher Rush" und "© 1993 Wizards of the Coast" vom unteren Rand alter Karten. */
    fun oldCardHints(lines: List<OcrLine>): OldCardHints {
        val text = lines.sortedBy { it.top }.joinToString("\n") { it.text }
        val artist = ILLUS.find(text)?.groupValues?.get(1)
            ?.substringBefore("©")?.substringBefore(" Wizards")?.substringBefore("  ")
            ?.trim(' ', '.', '-', '&')?.takeIf { it.count(Char::isLetter) >= 4 }
        val year = YEAR.find(text)?.groupValues?.get(1)
            ?: if (text.contains("Wizards", ignoreCase = true))
                Regex("""\b((?:199|20[0-3])\d)\b""").find(text)?.groupValues?.get(1) else null
        return OldCardHints(artist, year)
    }

    /**
     * Code-Modus: Nur der untere Kartenrand liegt im Rahmen (z.B. "0077 R" und "FDN • DE").
     * Gibt Set-Code, Sammlernummer und Sprache zurück (je null, wenn nicht lesbar).
     */
    fun parseCode(lines: List<OcrLine>, strip: Region): CodeResult {
        val padX = (strip.right - strip.left) * 0.06f
        val padY = (strip.bottom - strip.top) * 0.35f
        val area = Region(strip.left - padX, strip.top - padY, strip.right + padX, strip.bottom + padY)
        return collectorInfo(lines.filter { area.contains(it.cx, it.cy) })
    }

    /** Sprachcodes am Kartenrand -> Scryfall-Sprache ("" = bekannt, aber ohne eigene Sprache, z.B. PH). */
    private val LANGS = mapOf(
        "EN" to "en", "DE" to "de", "FR" to "fr", "IT" to "it", "ES" to "es", "SP" to "es", "PT" to "pt",
        "JA" to "ja", "JP" to "ja", "KO" to "ko", "KR" to "ko", "RU" to "ru", "ZHS" to "zhs", "ZHT" to "zht",
        "CS" to "zhs", "CT" to "zht", "PH" to "",
    )
    private val TOKEN = Regex("[A-Z0-9]+")

    /**
     * Set-Code, Sammlernummer und Sprache aus den Textzeilen am unteren Rand.
     * Tolerant gegenüber OCR-Fehlern: Trennzeichen statt "•" (".", "·", "*", "e" …), O/0 und I/1 in der Nummer.
     */
    fun collectorInfo(lines: List<OcrLine>): CodeResult {
        val text = lines.sortedBy { it.top }.joinToString("\n") { it.text }
        val upper = text.uppercase()

        // Set-Code + Sprache: Token-Paar "<SET> [Störzeichen] <SPRACHE>"
        var set: String? = null
        var lang: String? = null
        val tokens = TOKEN.findAll(upper).map { it.value }.toList()
        for (i in tokens.indices) {
            val code = LANGS[tokens[i]] ?: continue
            val prev = tokens.getOrNull(i - 1)?.let { p -> if (p.length == 1) tokens.getOrNull(i - 2) else p }
            if (prev != null && prev.length in 3..5 && prev.any(Char::isLetter) && prev !in LANGS) {
                set = prev
                lang = code.ifEmpty { null }
                break
            }
        }
        if (set == null) {
            val m = SET_LANG.find(upper)
            set = m?.groupValues?.get(1)?.takeIf { it.any(Char::isLetter) }
            lang = m?.groupValues?.get(2)?.let { LANGS[it]?.ifEmpty { null } }
        }

        val slash = CN_SLASH.find(text)
        val total = slash?.groupValues?.get(2)?.trimStart('0')?.takeIf { it.isNotEmpty() && it.length >= 2 }
        val cn = (slash?.groupValues?.get(1)
            ?: CN_RARITY_BEFORE.find(text)?.groupValues?.get(1)
            ?: CN_RARITY_AFTER.find(text)?.groupValues?.get(1)
            ?: CN_PADDED.find(text)?.groupValues?.get(1)
            ?: fuzzyNumber(text, set))
            ?.trimStart('0')?.ifEmpty { "0" }
        return CodeResult(set, cn, lang, text.replace("\n", " / ").trim(), total)
    }

    /** Nummer mit typischen Lesefehlern, z.B. "O077" -> "0077", "0l23" -> "0123". */
    private fun fuzzyNumber(text: String, set: String?): String? {
        for (raw in text.split(Regex("[\\s/]+"))) {
            val t = raw.trim { !it.isLetterOrDigit() }
            if (t.isEmpty() || t.equals(set, ignoreCase = true) || t.uppercase() in LANGS) continue
            val digitsBefore = t.count(Char::isDigit)
            val fixed = t.map { c ->
                when (c) {
                    'O', 'o', 'D', 'Q' -> '0'
                    'I', 'l', '|', 'i' -> '1'
                    'S' -> '5'
                    'B' -> '8'
                    else -> c
                }
            }.joinToString("")
            // nur Nummern mit führender Null (neue Rahmen) oder dreistellig – keine Jahreszahl wie "2024"
            val plausible = fixed.startsWith("0") || fixed.trimEnd { it.isLetter() }.length == 3
            if (digitsBefore >= 2 && plausible && Regex("""0?\d{2,4}[a-z]?""").matches(fixed)) return fixed
        }
        return null
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
