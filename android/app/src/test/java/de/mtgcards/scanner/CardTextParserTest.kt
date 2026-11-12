package de.mtgcards.scanner

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class CardTextParserTest {
    // Karte belegt im Bild x 100..730, y 200..1080
    private val card = Region(100f, 200f, 730f, 1080f)

    private fun line(text: String, l: Int, t: Int, r: Int, b: Int) = OcrLine(text, l, t, r, b)

    @Test
    fun picksNameAndCollectorInfo() {
        val lines = listOf(
            line("Atraxa, Praetors' Voice", 130, 225, 560, 255),
            line("{G}{W}{U}{B}", 590, 225, 710, 255),
            line("Legendary Creature — Phyrexian Angel Horror", 130, 690, 650, 715),
            line("Flying, vigilance, deathtouch, lifelink", 130, 760, 690, 785),
            line("028/351 M", 120, 1015, 260, 1035),
            line("C16 • EN Victor Adame Minguez", 120, 1040, 480, 1060),
        )
        val r = CardTextParser.parse(lines, card)
        assertEquals("Atraxa Praetors' Voice", r.name)
        assertEquals("28", r.collectorNumber)
        assertEquals("C16", r.setCode)
    }

    @Test
    fun newCollectorFormatAndGermanName() {
        val lines = listOf(
            line("Krenko, Tin Street-Boss", 125, 222, 520, 252).copy(text = "Krenko, Boss der Blechstraße 2R"),
            line("R 0123", 120, 1012, 220, 1032),
            line("DMU • DE", 120, 1038, 240, 1058),
        )
        val r = CardTextParser.parse(lines, card)
        assertEquals("Krenko Boss der Blechstraße", r.name)
        assertEquals("123", r.collectorNumber)
        assertEquals("DMU", r.setCode)
        assertEquals("de", r.lang)
    }

    @Test
    fun showcaseNameLowerUsesAlternatives() {
        // Name nicht im üblichen Bereich, sondern etwas tiefer (z.B. Showcase-Rahmen)
        val lines = listOf(
            line("Sheoldred, the Apocalypse", 150, 390, 600, 440),
            line("Phyrexian Praetor", 150, 450, 400, 470),
        )
        val r = CardTextParser.parse(lines, card)
        assertEquals("Sheoldred the Apocalypse", r.name)
        assertEquals(listOf("Phyrexian Praetor"), r.alternatives)
    }

    @Test
    fun codeModeStrip() {
        // Nur der untere Rand im Streifen-Rahmen (x 50..700, y 400..540)
        val strip = Region(50f, 400f, 700f, 540f)
        val lines = listOf(
            line("0077 C", 70, 410, 200, 450),
            line("FDN • DE  Jane Doe", 70, 470, 420, 510),
            line("© 2024 Wizards", 500, 900, 700, 930),          // außerhalb
        )
        val r = CardTextParser.parseCode(lines, strip)
        assertEquals("FDN", r.setCode)
        assertEquals("77", r.collectorNumber)
        assertEquals("de", r.lang)
        val old = CardTextParser.parseCode(listOf(line("123/280 R", 70, 410, 200, 450),
            line("MH3 • EN", 70, 470, 200, 510)), strip)
        assertEquals("123", old.collectorNumber)
        assertEquals("MH3", old.setCode)
        assertNull(CardTextParser.parseCode(listOf(line("Irgendwas", 70, 410, 200, 450)), strip).setCode)

        // typische OCR-Fehler: Punkt als "e" gelesen, O statt 0
        val ocr = CardTextParser.parseCode(listOf(line("O077 C", 70, 410, 200, 450),
            line("FDN e DE  Anna de Vries", 70, 470, 420, 510)), strip)
        assertEquals("FDN", ocr.setCode)
        assertEquals("de", ocr.lang)
        assertEquals("77", ocr.collectorNumber)
        // Trennzeichen "·" und Nummer ohne Seltenheit
        val mid = CardTextParser.parseCode(listOf(line("0212", 70, 410, 200, 450),
            line("MH3 · EN", 70, 470, 200, 510)), strip)
        assertEquals(listOf("MH3", "212", "en"), listOf(mid.setCode, mid.collectorNumber, mid.lang))
    }

    @Test
    fun nothingInFrame() {
        val r = CardTextParser.parse(listOf(line("Irgendwas", 0, 0, 50, 20)), card)
        assertNull(r.name)
    }

    @Test
    fun normalize() {
        assertEquals("lim dul s vault", CardTextParser.normalize("Lim-Dûl's Vault"))
    }

    @Test
    fun oldCardNumberWithSetSize() {
        val lines = listOf(
            line("Lightning Bolt", 130, 225, 400, 255),
            line("146/249 C", 120, 1015, 260, 1035),
            line("Illus. Christopher Moeller", 300, 1040, 560, 1058),
        )
        val r = CardTextParser.parse(lines, card)
        assertEquals("146", r.collectorNumber)
        assertEquals("249", r.total)
        assertNull(r.setCode)
        assertEquals("Christopher Moeller", r.artist)
    }

    @Test
    fun veryOldCardArtistAndYear() {
        val lines = listOf(
            line("Lightning Bolt", 130, 225, 400, 255),
            line("Illus. Christopher Rush", 300, 1020, 560, 1038),
            line("© 1993-1995 Wizards of the Coast, Inc.", 250, 1042, 600, 1060),
        )
        val r = CardTextParser.parse(lines, card)
        assertEquals("Christopher Rush", r.artist)
        assertEquals("1995", r.year)
        assertNull(r.total)
    }

    @Test
    fun emblemUsesTypeLine() {
        val lines = listOf(
            line("Emblem", 300, 225, 520, 255),
            line("Emblem — Chandra", 130, 700, 450, 725),
            line("Whenever you cast a spell, this emblem deals 5 damage", 130, 760, 690, 785),
        )
        assertEquals("Emblem Chandra", CardTextParser.parse(lines, card).name)
    }
}

class CandidateVoterTest {
    @Test
    fun similarReadingsConfirm() {
        val v = CandidateVoter()
        assertEquals(false, v.offer("atraxa praetors voice"))
        assertEquals(true, v.offer("atraxa praetors voioe"))
    }

    @Test
    fun differentCardsDoNotConfirm() {
        val v = CandidateVoter()
        assertEquals(false, v.offer("sol ring"))
        assertEquals(false, v.offer("arcane signet"))
        assertEquals(true, v.offer("arcane signet"))
    }

    @Test
    fun similarityValues() {
        assertEquals(1.0, similarity("abc", "abc"), 0.0)
        assertEquals(0.75, similarity("abcd", "abce"), 0.001)
    }
}
