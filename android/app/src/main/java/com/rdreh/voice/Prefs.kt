package com.rdreh.voice

import android.content.Context

object Prefs {
    private const val NAME = "rdreh_voice_prefs"
    private const val KEY_URL = "server_url"
    private const val KEY_TOKEN = "auth_token"
    private const val KEY_SPEECH_MODE = "speech_mode"
    private const val KEY_SAFETY_MODE = "safety_mode"
    private const val KEY_APK_SHA = "last_apk_sha"

    const val MODE_FULL = "full"
    const val MODE_BRIEF = "brief"
    const val MODE_SILENT = "silent"

    fun getUrl(ctx: Context): String =
        ctx.getSharedPreferences(NAME, Context.MODE_PRIVATE)
            .getString(KEY_URL, "http://10.0.0.100:8765")!!
            .trimEnd('/')

    fun getToken(ctx: Context): String =
        ctx.getSharedPreferences(NAME, Context.MODE_PRIVATE)
            .getString(KEY_TOKEN, "")!!
            .trim()

    fun getSpeechMode(ctx: Context): String =
        ctx.getSharedPreferences(NAME, Context.MODE_PRIVATE)
            .getString(KEY_SPEECH_MODE, MODE_FULL)!!

    fun setSpeechMode(ctx: Context, mode: String) {
        ctx.getSharedPreferences(NAME, Context.MODE_PRIVATE).edit()
            .putString(KEY_SPEECH_MODE, mode)
            .apply()
    }

    fun getSafetyMode(ctx: Context): Boolean =
        ctx.getSharedPreferences(NAME, Context.MODE_PRIVATE)
            .getBoolean(KEY_SAFETY_MODE, true)

    fun setSafetyMode(ctx: Context, enabled: Boolean) {
        ctx.getSharedPreferences(NAME, Context.MODE_PRIVATE).edit()
            .putBoolean(KEY_SAFETY_MODE, enabled)
            .apply()
    }

    fun getLastApkSha(ctx: Context): String =
        ctx.getSharedPreferences(NAME, Context.MODE_PRIVATE)
            .getString(KEY_APK_SHA, "")!!

    fun setLastApkSha(ctx: Context, sha: String) {
        ctx.getSharedPreferences(NAME, Context.MODE_PRIVATE).edit()
            .putString(KEY_APK_SHA, sha)
            .apply()
    }

    fun save(ctx: Context, url: String, token: String, speechMode: String) {
        ctx.getSharedPreferences(NAME, Context.MODE_PRIVATE).edit()
            .putString(KEY_URL, url.trim().trimEnd('/'))
            .putString(KEY_TOKEN, token.trim())
            .putString(KEY_SPEECH_MODE, speechMode)
            .apply()
    }
}
