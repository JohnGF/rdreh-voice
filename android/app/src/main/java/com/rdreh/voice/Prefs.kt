package com.rdreh.voice

import android.content.Context

object Prefs {
    private const val NAME = "rdreh_voice_prefs"
    private const val KEY_URL = "server_url"
    private const val KEY_TOKEN = "auth_token"
    private const val KEY_AUTO_READ = "auto_read"

    fun getUrl(ctx: Context): String =
        ctx.getSharedPreferences(NAME, Context.MODE_PRIVATE)
            .getString(KEY_URL, "http://10.0.0.100:8765")!!
            .trimEnd('/')

    fun getToken(ctx: Context): String =
        ctx.getSharedPreferences(NAME, Context.MODE_PRIVATE)
            .getString(KEY_TOKEN, "")!!
            .trim()

    fun getAutoRead(ctx: Context): Boolean =
        ctx.getSharedPreferences(NAME, Context.MODE_PRIVATE)
            .getBoolean(KEY_AUTO_READ, true)

    fun save(ctx: Context, url: String, token: String, autoRead: Boolean) {
        ctx.getSharedPreferences(NAME, Context.MODE_PRIVATE).edit()
            .putString(KEY_URL, url.trim().trimEnd('/'))
            .putString(KEY_TOKEN, token.trim())
            .putBoolean(KEY_AUTO_READ, autoRead)
            .apply()
    }
}
