package com.rdreh.voice

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import org.json.JSONObject
import java.util.Locale
import kotlin.concurrent.thread

class VoiceCaptureActivity : AppCompatActivity(), TextToSpeech.OnInitListener {
    private lateinit var statusView: TextView
    private var recognizer: SpeechRecognizer? = null
    private var tts: TextToSpeech? = null
    private var ttsReady = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        statusView = TextView(this).apply {
            text = "Listening..."
            textSize = 18f
            setPadding(48, 48, 48, 48)
        }
        setContentView(LinearLayout(this).apply { addView(statusView) })
        tts = TextToSpeech(this, this)

        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) {
            statusView.text = "Microphone permission required. Open rdreh-voice to grant."
            return
        }
        startListening()
    }

    override fun onInit(status: Int) {
        if (status == TextToSpeech.SUCCESS) {
            tts?.language = Locale.US
            tts?.setSpeechRate(1.08f)
            ttsReady = true
        }
    }

    private fun startListening() {
        BluetoothAudioHelper.enableBluetoothMic(this)
        recognizer = SpeechRecognizer.createSpeechRecognizer(this).apply {
            setRecognitionListener(object : RecognitionListener {
                override fun onReadyForSpeech(params: Bundle?) {
                    statusView.text = "Speak command..."
                }

                override fun onBeginningOfSpeech() {}
                override fun onRmsChanged(rmsdB: Float) {}
                override fun onBufferReceived(buffer: ByteArray?) {}
                override fun onEndOfSpeech() {
                    statusView.text = "Processing..."
                }

                override fun onError(error: Int) {
                    BluetoothAudioHelper.disableBluetoothMic(this@VoiceCaptureActivity)
                    statusView.text = "Speech error ($error)"
                }

                override fun onResults(results: Bundle) {
                    BluetoothAudioHelper.disableBluetoothMic(this@VoiceCaptureActivity)
                    val text = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                        ?.firstOrNull()
                        ?.trim()
                        .orEmpty()
                    if (text.isEmpty()) {
                        statusView.text = "Nothing heard."
                        return
                    }
                    statusView.text = "Heard: $text"
                    dispatchCommand(text)
                }

                override fun onPartialResults(partialResults: Bundle?) {}
                override fun onEvent(eventType: Int, params: Bundle?) {}
            })
        }
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, "en-US")
        }
        recognizer?.startListening(intent)
    }

    private fun dispatchCommand(transcript: String) {
        val url = Prefs.getUrl(this)
        val token = Prefs.getToken(this)
        thread {
            val res = runCatching {
                RdrApiClient.postJson(
                    url,
                    token,
                    "/api/command",
                    JSONObject().put("transcript", transcript).put("view_mode", "agents"),
                )
            }.getOrElse { JSONObject().put("error", it.message ?: "Request failed") }

            val spoken = res.optString("spoken", "").ifEmpty { res.optString("error", "Done.") }
            runOnUiThread {
                statusView.text = spoken
                if (ttsReady) {
                    tts?.speak(spoken, TextToSpeech.QUEUE_FLUSH, null, "cmd-reply")
                }
            }
        }
    }

    override fun onDestroy() {
        BluetoothAudioHelper.disableBluetoothMic(this)
        recognizer?.destroy()
        tts?.shutdown()
        super.onDestroy()
    }
}
