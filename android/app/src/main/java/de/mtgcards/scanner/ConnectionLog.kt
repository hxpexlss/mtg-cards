package de.mtgcards.scanner

import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Merkt sich die letzten Verbindungsfehler (für die Fehlersuche unter "Verbindung"). */
object ConnectionLog {
    private val fmt = SimpleDateFormat("dd.MM. HH:mm:ss", Locale.GERMANY)
    private val entries = ArrayDeque<String>()
    var lastOk: Long = 0L
        private set
    var retriesOk = 0
        private set

    @Synchronized
    fun error(path: String, message: String, attempts: Int) {
        entries.addFirst("${fmt.format(Date())}  ${path.substringBefore('?')}  –  $message (nach $attempts Versuchen)")
        while (entries.size > 20) entries.removeLast()
    }

    @Synchronized
    fun ok(attempt: Int) {
        lastOk = System.currentTimeMillis()
        if (attempt > 0) retriesOk++
    }

    @Synchronized
    fun summary(): String = buildString {
        append(if (lastOk > 0) "Letzte erfolgreiche Verbindung: ${fmt.format(Date(lastOk))}" else "Noch keine erfolgreiche Verbindung")
        if (retriesOk > 0) append("\n$retriesOk Anfragen erst im 2./3. Versuch erfolgreich")
        if (entries.isEmpty()) append("\nKeine Verbindungsfehler") else {
            append("\n\nLetzte Fehler:\n")
            append(entries.joinToString("\n"))
        }
    }

    @Synchronized
    fun clear() {
        entries.clear()
        retriesOk = 0
    }
}
