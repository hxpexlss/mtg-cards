package de.mtgcards.scanner

import android.content.Context

/** Token säubern: Leerzeichen (z.B. von der Tastatur nach "-" eingefügt) entfernen, Großbuchstaben. */
fun cleanToken(t: String) = t.uppercase().filter { it.isLetterOrDigit() || it == '-' }

object Prefs {
    private fun sp(ctx: Context) = ctx.getSharedPreferences("mtgcards", Context.MODE_PRIVATE)

    fun serverUrl(ctx: Context): String = sp(ctx).getString("server_url", "") ?: ""
    fun token(ctx: Context): String = sp(ctx).getString("token", "") ?: ""
    fun autoAdd(ctx: Context): Boolean = sp(ctx).getBoolean("auto_add", false)

    fun sound(ctx: Context): Boolean = sp(ctx).getBoolean("sound", true)
    fun setSound(ctx: Context, value: Boolean) {
        sp(ctx).edit().putBoolean("sound", value).apply()
    }

    fun pendingJson(ctx: Context): String = sp(ctx).getString("pending", "[]") ?: "[]"
    fun setPendingJson(ctx: Context, value: String) {
        sp(ctx).edit().putString("pending", value).apply()
    }

    fun fingerprint(ctx: Context): String = sp(ctx).getString("fingerprint", "") ?: ""

    fun saveServer(ctx: Context, url: String, token: String, fingerprint: String? = null) {
        val e = sp(ctx).edit().putString("server_url", url).putString("token", cleanToken(token))
        if (fingerprint != null) e.putString("fingerprint", fingerprint)
        e.apply()
    }

    fun scanLang(ctx: Context): String = sp(ctx).getString("scan_lang", "auto") ?: "auto"
    fun setScanLang(ctx: Context, value: String) {
        sp(ctx).edit().putString("scan_lang", value).apply()
    }

    /** Proxy-Modus beim Scannen: alle Karten bekommen den Tag "Proxies". */
    fun proxyMode(ctx: Context): Boolean = sp(ctx).getBoolean("proxy_mode", false)
    fun setProxyMode(ctx: Context, value: Boolean) {
        sp(ctx).edit().putBoolean("proxy_mode", value).apply()
    }

    /** Ziel-Deck beim Scannen (0 = keins). */
    fun scanDeckId(ctx: Context): Long = sp(ctx).getLong("scan_deck_id", 0L)
    fun scanDeckName(ctx: Context): String = sp(ctx).getString("scan_deck_name", "") ?: ""
    fun setScanDeck(ctx: Context, id: Long, name: String) {
        sp(ctx).edit().putLong("scan_deck_id", id).putString("scan_deck_name", name).apply()
    }

    fun defaultFoil(ctx: Context): Boolean = sp(ctx).getBoolean("default_foil", false)
    fun setDefaultFoil(ctx: Context, value: Boolean) {
        sp(ctx).edit().putBoolean("default_foil", value).apply()
    }

    /** Code-Modus: nur den unteren Kartenrand (Set-Code + Nummer) scannen. */
    fun codeMode(ctx: Context): Boolean = sp(ctx).getBoolean("code_mode", false)
    fun setCodeMode(ctx: Context, value: Boolean) {
        sp(ctx).edit().putBoolean("code_mode", value).apply()
    }

    /** Fest eingestellte Edition (leer = automatisch: zuletzt sicher erkannte Edition). */
    fun fixedSet(ctx: Context): String = sp(ctx).getString("fixed_set", "") ?: ""
    fun setFixedSet(ctx: Context, value: String) {
        sp(ctx).edit().putString("fixed_set", value.trim().uppercase()).apply()
    }

    fun lastSet(ctx: Context): String = sp(ctx).getString("last_set", "") ?: ""
    fun setLastSet(ctx: Context, value: String) {
        sp(ctx).edit().putString("last_set", value.trim().uppercase()).apply()
    }

    fun landscape(ctx: Context): Boolean = sp(ctx).getBoolean("landscape", false)
    fun setLandscape(ctx: Context, value: Boolean) {
        sp(ctx).edit().putBoolean("landscape", value).apply()
    }

    fun setAutoAdd(ctx: Context, value: Boolean) {
        sp(ctx).edit().putBoolean("auto_add", value).apply()
    }
}
