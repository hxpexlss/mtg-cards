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
    fun nothingInFrame() {
        val r = CardTextParser.parse(listOf(line("Irgendwas", 0, 0, 50, 20)), card)
        assertNull(r.name)
    }

    @Test
    fun normalize() {
        assertEquals("lim dul s vault", CardTextParser.normalize("Lim-Dûl's Vault"))
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
