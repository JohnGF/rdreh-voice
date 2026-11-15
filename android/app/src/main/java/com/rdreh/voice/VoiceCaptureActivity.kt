package com.rdreh.voice

import android.Manifest
import android.animation.ObjectAnimator
import android.animation.ValueAnimator
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import org.json.JSONObject
import java.util.Locale
import kotlin.concurrent.thread

class VoiceCaptureActivity : AppCompatActivity(), TextToSpeech.OnInitListener {
    private lateinit var pulseDot: View
    private lateinit var levelBar: View
    private lateinit var statusView: TextView
    private var pulseAnim: ObjectAnimator? = null
    private var recognizer: SpeechRecognizer? = null
    private var tts: TextToSpeech? = null
    private var ttsReady = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        pulseDot = View(this).apply {
            background = GradientDrawable().apply {
                shape = GradientDrawable.OVAL
                setColor(Color.parseColor("#38BDF8"))
            }
            layoutParams = LinearLayout.LayoutParams(48, 48).apply {
                gravity = Gravity.CENTER_HORIZONTAL
                bottomMargin = 20
            }
        }

        levelBar = View(this).apply {
            background = GradientDrawable().apply {
                cornerRadius = 12f
                setColor(Color.parseColor("#22C55E"))
            }
            layoutParams = LinearLayout.LayoutParams(240, 14).apply {
                gravity = Gravity.CENTER_HORIZONTAL
                bottomMargin = 24
            }
            scaleX = 0.2f
        }

        statusView = TextView(this).apply {
            text = "Starting mic..."
            textSize = 18f
            gravity = Gravity.CENTER
            setPadding(24, 8, 24, 24)
        }

        val closeBtn = Button(this).apply {
            text = "Close"
            setOnClickListener { finish() }
        }

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(48, 48, 48, 36)
            addView(pulseDot)
            addView(levelBar)
            addView(statusView)
            addView(closeBtn)
        }
        setContentView(root)

        tts = TextToSpeech(this, this)
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) {
            statusView.text = "Microphone permission required. Open rdreh-voice to grant."
            return
        }
        startPulseAnimation()
        startListening()
    }

    private fun startPulseAnimation() {
        pulseAnim = ObjectAnimator.ofFloat(pulseDot, View.ALPHA, 1f, 0.25f).apply {
            duration = 550
            repeatCount = ValueAnimator.INFINITE
            repeatMode = ValueAnimator.REVERSE
            start()
        }
    }

    private fun stopPulseAnimation(colorHex: String) {
        pulseAnim?.cancel()
        pulseDot.alpha = 1f
        (pulseDot.background as? GradientDrawable)?.setColor(Color.parseColor(colorHex))
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
                    (pulseDot.background as? GradientDrawable)?.setColor(Color.parseColor("#22C55E"))
                    statusView.text = "Listening — speak now"
                }

                override fun onBeginningOfSpeech() {
                    statusView.text = "Hearing you..."
                }

                override fun onRmsChanged(rmsdB: Float) {
                    val norm = ((rmsdB + 2f) / 12f).coerceIn(0.15f, 1.0f)
                    levelBar.scaleX = norm
                }

                override fun onBufferReceived(buffer: ByteArray?) {}
                override fun onEndOfSpeech() {
                    levelBar.scaleX = 0.2f
                    (pulseDot.background as? GradientDrawable)?.setColor(Color.parseColor("#FBBF24"))
                    statusView.text = "Processing..."
                }

                override fun onError(error: Int) {
                    stopPulseAnimation("#EF4444")
                    BluetoothAudioHelper.disableBluetoothMic(this@VoiceCaptureActivity)
                    statusView.text = "Speech error ($error)"
                }

                override fun onResults(results: Bundle) {
                    stopPulseAnimation("#38BDF8")
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

                override fun onPartialResults(partialResults: Bundle?) {
                    val partial = partialResults?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                        ?.firstOrNull()
                        ?.trim()
                    if (!partial.isNullOrEmpty()) {
                        statusView.text = partial
                    }
                }

                override fun onEvent(eventType: Int, params: Bundle?) {}
            })
        }
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, "en-US")
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
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
        pulseAnim?.cancel()
        BluetoothAudioHelper.disableBluetoothMic(this)
        recognizer?.destroy()
        tts?.shutdown()
        super.onDestroy()
    }
}
