package com.rdreh.voice

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.RemoteInput
import org.json.JSONObject
import kotlin.concurrent.thread

class NotificationActionReceiver : BroadcastReceiver() {
    companion object {
        const val ACTION_APPROVE = "com.rdreh.voice.ACTION_APPROVE"
        const val ACTION_REJECT = "com.rdreh.voice.ACTION_REJECT"
        const val ACTION_REPLY = "com.rdreh.voice.ACTION_REPLY"
        const val EXTRA_PANE_ID = "pane_id"
        const val EXTRA_NOTIF_ID = "notif_id"
        const val KEY_REPLY_TEXT = "reply_text"
    }

    override fun onReceive(context: Context, intent: Intent) {
        val paneId = intent.getIntExtra(EXTRA_PANE_ID, -1)
        val notifId = intent.getIntExtra(EXTRA_NOTIF_ID, -1)
        if (paneId < 0) return

        val textToSend: String? = when (intent.action) {
            ACTION_APPROVE -> "y"
            ACTION_REJECT -> "n"
            ACTION_REPLY -> RemoteInput.getResultsFromIntent(intent)
                ?.getCharSequence(KEY_REPLY_TEXT)
                ?.toString()
                ?.trim()
            else -> null
        }
        if (textToSend.isNullOrEmpty()) return

        val pending = goAsync()
        val url = Prefs.getUrl(context)
        val token = Prefs.getToken(context)
        thread {
            try {
                RdrApiClient.postJson(
                    url,
                    token,
                    "/api/send",
                    JSONObject().put("pane", paneId).put("text", textToSend).put("enter", true),
                )
                if (notifId >= 0) {
                    NotificationManagerCompat.from(context).cancel(notifId)
                }
            } catch (_: Exception) {
            } finally {
                pending.finish()
            }
        }
    }
}
