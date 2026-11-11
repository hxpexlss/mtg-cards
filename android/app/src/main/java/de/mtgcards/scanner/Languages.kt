package de.mtgcards.scanner

/** Kartensprachen (Scryfall-Codes). "auto" = vom Kartenrand lesen, sonst Englisch. */
object Languages {
    val all = listOf(
        "auto" to "Automatisch (vom Kartenrand)",
        "en" to "Englisch",
        "de" to "Deutsch",
        "fr" to "Französisch",
        "it" to "Italienisch",
        "es" to "Spanisch",
        "pt" to "Portugiesisch",
        "ja" to "Japanisch",
        "ko" to "Koreanisch",
        "ru" to "Russisch",
        "zhs" to "Chinesisch (vereinfacht)",
        "zht" to "Chinesisch (traditionell)",
    )

    fun label(code: String) = all.firstOrNull { it.first == code }?.second ?: code

    fun short(code: String) = if (code == "auto") "A" else code.uppercase().take(3)
}
