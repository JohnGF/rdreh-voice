package com.rdreh.voice

import android.Manifest
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import kotlin.concurrent.thread

class MainActivity : AppCompatActivity() {
    private lateinit var urlInput: EditText
    private lateinit var tokenInput: EditText
    private lateinit var autoReadCheck: CheckBox
    private lateinit var statusText: TextView

    private val permLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(40, 64, 40, 40)
        }

        val title = TextView(this).apply {
            text = "rdreh-voice"
            textSize = 22f
        }
        urlInput = EditText(this).apply {
            hint = "Server URL (e.g. http://10.0.0.100:8765)"
            setText(Prefs.getUrl(this@MainActivity))
        }
        tokenInput = EditText(this).apply {
            hint = "RDR_VOICE_TOKEN (optional)"
            setText(Prefs.getToken(this@MainActivity))
        }
        autoReadCheck = CheckBox(this).apply {
            text = "Auto-read finished agents via TTS"
            isChecked = Prefs.getAutoRead(this@MainActivity)
        }
        statusText = TextView(this).apply {
            text = "Service: ${if (RdrVoiceService.isRunning.get()) "running" else "stopped"}"
            setPadding(0, 20, 0, 20)
        }

        val saveBtn = Button(this).apply {
            text = "Save & Test Connection"
            setOnClickListener {
                Prefs.save(
                    this@MainActivity,
                    urlInput.text.toString(),
                    tokenInput.text.toString(),
                    autoReadCheck.isChecked,
                )
                testConnection()
            }
        }
        val serviceBtn = Button(this).apply {
            text = "Start / Restart Monitor Service"
            setOnClickListener {
                Prefs.save(
                    this@MainActivity,
                    urlInput.text.toString(),
                    tokenInput.text.toString(),
                    autoReadCheck.isChecked,
                )
                val svc = Intent(this@MainActivity, RdrVoiceService::class.java)
                ContextCompat.startForegroundService(this@MainActivity, svc)
                statusText.text = "Monitor service started."
            }
        }
        val speakBtn = Button(this).apply {
            text = "Speak Voice Command"
            setOnClickListener {
                startActivity(Intent(this@MainActivity, VoiceCaptureActivity::class.java))
            }
        }
        val assistantBtn = Button(this).apply {
            text = "Default Assistant Settings"
            setOnClickListener {
                startActivity(Intent(Settings.ACTION_VOICE_INPUT_SETTINGS))
            }
        }

        listOf(title, urlInput, tokenInput, autoReadCheck, saveBtn, serviceBtn, speakBtn, assistantBtn, statusText)
            .forEach { root.addView(it) }

        setContentView(ScrollView(this).apply { addView(root) })
        requestRuntimePermissions()
    }

    private fun requestRuntimePermissions() {
        val perms = mutableListOf(Manifest.permission.RECORD_AUDIO)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            perms.add(Manifest.permission.BLUETOOTH_CONNECT)
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            perms.add(Manifest.permission.POST_NOTIFICATIONS)
        }
        permLauncher.launch(perms.toTypedArray())
    }

    private fun testConnection() {
        val url = Prefs.getUrl(this)
        val token = Prefs.getToken(this)
        statusText.text = "Testing $url..."
        thread {
            val msg = runCatching {
                val res = RdrApiClient.getJson(url, token, "/api/panes")
                if (res.optBoolean("ok", false)) {
                    val c = res.optJSONObject("counts")
                    val total = c?.optInt("total", 0) ?: 0
                    val busy = c?.optInt("busy", 0) ?: 0
                    val done = c?.optInt("finished", 0) ?: 0
                    "Connected: $total agents ($busy working, $done done)"
                } else {
                    "Error: ${res.optString("error", "unknown")}"
                }
            }.getOrElse { "Failed: ${it.message}" }
            runOnUiThread { statusText.text = msg }
        }
    }
}
