package de.mtgcards.scanner

import android.content.Context

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

    fun saveServer(ctx: Context, url: String, token: String) {
        sp(ctx).edit().putString("server_url", url).putString("token", token.trim().uppercase()).apply()
    }

    fun setAutoAdd(ctx: Context, value: Boolean) {
        sp(ctx).edit().putBoolean("auto_add", value).apply()
    }
}
