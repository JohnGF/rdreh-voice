package com.rdreh.voice

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.os.IBinder
import android.speech.tts.TextToSpeech
import android.support.v4.media.session.MediaSessionCompat
import android.support.v4.media.session.PlaybackStateCompat
import android.view.KeyEvent
import androidx.core.app.NotificationCompat
import androidx.core.app.RemoteInput
import org.json.JSONObject
import java.util.Locale
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

class RdrVoiceService : Service(), TextToSpeech.OnInitListener {
    companion object {
        const val CHANNEL_SERVICE = "rdreh_service"
        const val CHANNEL_ALERTS = "rdreh_alerts"
        const val SERVICE_NOTIF_ID = 1001
        val isRunning = AtomicBoolean(false)
    }

    private var tts: TextToSpeech? = null
    private var ttsReady = false
    private lateinit var mediaSession: MediaSessionCompat
    private val prevStates = mutableMapOf<Int, String>()
    private var initialized = false

    override fun onCreate() {
        super.onCreate()
        isRunning.set(true)
        createChannels()
        tts = TextToSpeech(this, this)
        setupMediaSession()
        startForeground(SERVICE_NOTIF_ID, buildServiceNotification("Connecting to rdreh-voice..."))
        startSseLoop()
    }

    override fun onDestroy() {
        isRunning.set(false)
        mediaSession.release()
        tts?.shutdown()
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onInit(status: Int) {
        if (status == TextToSpeech.SUCCESS) {
            tts?.language = Locale.US
            tts?.setSpeechRate(1.08f)
            ttsReady = true
        }
    }

    private fun setupMediaSession() {
        mediaSession = MediaSessionCompat(this, "rdreh-voice-ptt").apply {
            setCallback(object : MediaSessionCompat.Callback() {
                override fun onMediaButtonEvent(mediaButtonEvent: Intent): Boolean {
                    val ev = mediaButtonEvent.getParcelableExtra<KeyEvent>(Intent.EXTRA_KEY_EVENT)
                    if (ev != null && ev.action == KeyEvent.ACTION_DOWN) {
                        when (ev.keyCode) {
                            KeyEvent.KEYCODE_HEADSETHOOK,
                            KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE,
                            KeyEvent.KEYCODE_MEDIA_PLAY -> {
                                launchVoiceCapture()
                                return true
                            }
                        }
                    }
                    return super.onMediaButtonEvent(mediaButtonEvent)
                }

                override fun onPlay() {
                    launchVoiceCapture()
                }
            })
            setPlaybackState(
                PlaybackStateCompat.Builder()
                    .setActions(PlaybackStateCompat.ACTION_PLAY or PlaybackStateCompat.ACTION_PLAY_PAUSE)
                    .setState(PlaybackStateCompat.STATE_PAUSED, 0L, 1.0f)
                    .build()
            )
            isActive = true
        }
    }

    private fun launchVoiceCapture() {
        val intent = Intent(this, VoiceCaptureActivity::class.java).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        }
        startActivity(intent)
    }

    private fun startSseLoop() {
        thread(name = "rdreh-sse") {
            while (isRunning.get()) {
                val url = Prefs.getUrl(this)
                val token = Prefs.getToken(this)
                try {
                    RdrApiClient.streamEvents(url, token, { isRunning.get() }) { state ->
                        handleStateUpdate(url, token, state)
                    }
                } catch (_: Exception) {
                    updateServiceNotification("Disconnected — retrying...")
                }
                if (isRunning.get()) {
                    try {
                        Thread.sleep(3000)
                    } catch (_: InterruptedException) {
                        break
                    }
                }
            }
        }
    }

    private fun handleStateUpdate(url: String, token: String, state: JSONObject) {
        if (!state.optBoolean("ok", false)) return
        val counts = state.optJSONObject("counts")
        val busy = counts?.optInt("busy", 0) ?: 0
        val finished = counts?.optInt("finished", 0) ?: 0
        val total = counts?.optInt("total", 0) ?: 0
        updateServiceNotification("$total agents · $busy working · $finished done")

        val panes = state.optJSONArray("panes") ?: return
        val newlyFinished = mutableListOf<JSONObject>()
        for (i in 0 until panes.length()) {
            val p = panes.getJSONObject(i)
            val id = p.optInt("id", -1)
            val st = p.optString("state", "")
            if (id >= 0) {
                val prev = prevStates[id]
                if (initialized && prev == "working" && st == "idle") {
                    newlyFinished.add(p)
                }
                prevStates[id] = st
            }
        }
        initialized = true

        for (p in newlyFinished) {
            val paneId = p.optInt("id", -1)
            val agentNum = if (p.has("agent_num") && !p.isNull("agent_num")) p.optInt("agent_num") else paneId
            val jobLabel = p.optString("job_label", "")
            val tail = runCatching {
                RdrApiClient.getJson(url, token, "/api/tail?pane=$paneId&lines=40")
            }.getOrNull()
            val spoken = tail?.optString("spoken", "")?.takeIf { it.isNotEmpty() }
                ?: "Agent $agentNum finished."
            val kind = tail?.optString("kind", "finished") ?: "finished"
            val title = if (jobLabel.isNotEmpty()) "Agent $agentNum · $jobLabel" else "Agent $agentNum"

            if (Prefs.getAutoRead(this) && ttsReady) {
                val prefix = if (kind == "question") "$title needs action. " else "$title finished. "
                tts?.speak(prefix + spoken, TextToSpeech.QUEUE_FLUSH, null, "pane-$paneId")
            }
            postAlertNotification(paneId, title, spoken)
        }
    }

    private fun postAlertNotification(paneId: Int, title: String, body: String) {
        val notifId = 2000 + paneId
        val approveIntent = PendingIntent.getBroadcast(
            this,
            notifId * 10 + 1,
            Intent(this, NotificationActionReceiver::class.java).apply {
                action = NotificationActionReceiver.ACTION_APPROVE
                putExtra(NotificationActionReceiver.EXTRA_PANE_ID, paneId)
                putExtra(NotificationActionReceiver.EXTRA_NOTIF_ID, notifId)
            },
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val rejectIntent = PendingIntent.getBroadcast(
            this,
            notifId * 10 + 2,
            Intent(this, NotificationActionReceiver::class.java).apply {
                action = NotificationActionReceiver.ACTION_REJECT
                putExtra(NotificationActionReceiver.EXTRA_PANE_ID, paneId)
                putExtra(NotificationActionReceiver.EXTRA_NOTIF_ID, notifId)
            },
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val remoteInput = RemoteInput.Builder(NotificationActionReceiver.KEY_REPLY_TEXT)
            .setLabel("Reply to $title")
            .build()
        val replyIntent = PendingIntent.getBroadcast(
            this,
            notifId * 10 + 3,
            Intent(this, NotificationActionReceiver::class.java).apply {
                action = NotificationActionReceiver.ACTION_REPLY
                putExtra(NotificationActionReceiver.EXTRA_PANE_ID, paneId)
                putExtra(NotificationActionReceiver.EXTRA_NOTIF_ID, notifId)
            },
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE,
        )
        val replyAction = NotificationCompat.Action.Builder(
            android.R.drawable.ic_btn_speak_now,
            "Reply",
            replyIntent,
        ).addRemoteInput(remoteInput).build()

        val notif = NotificationCompat.Builder(this, CHANNEL_ALERTS)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .addAction(android.R.drawable.checkbox_on_background, "Approve", approveIntent)
            .addAction(android.R.drawable.ic_delete, "Reject", rejectIntent)
            .addAction(replyAction)
            .build()

        val nm = getSystemService(NotificationManager::class.java)
        nm.notify(notifId, notif)
    }

    private fun buildServiceNotification(text: String): Notification {
        val openIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE,
        )
        return NotificationCompat.Builder(this, CHANNEL_SERVICE)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle("rdreh-voice")
            .setContentText(text)
            .setContentIntent(openIntent)
            .setOngoing(true)
            .build()
    }

    private fun updateServiceNotification(text: String) {
        val nm = getSystemService(NotificationManager::class.java)
        nm.notify(SERVICE_NOTIF_ID, buildServiceNotification(text))
    }

    private fun createChannels() {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_SERVICE, "rdreh Monitor", NotificationManager.IMPORTANCE_LOW)
        )
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_ALERTS, "Agent Alerts", NotificationManager.IMPORTANCE_HIGH)
        )
    }
}
