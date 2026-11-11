package de.mtgcards.scanner

import android.content.Context

object Prefs {
    private fun sp(ctx: Context) = ctx.getSharedPreferences("mtgcards", Context.MODE_PRIVATE)

    fun serverUrl(ctx: Context): String = sp(ctx).getString("server_url", "") ?: ""
    fun token(ctx: Context): String = sp(ctx).getString("token", "") ?: ""
    fun autoAdd(ctx: Context): Boolean = sp(ctx).getBoolean("auto_add", false)

    fun saveServer(ctx: Context, url: String, token: String) {
        sp(ctx).edit().putString("server_url", url).putString("token", token.trim().uppercase()).apply()
    }

    fun setAutoAdd(ctx: Context, value: Boolean) {
        sp(ctx).edit().putBoolean("auto_add", value).apply()
    }
}
