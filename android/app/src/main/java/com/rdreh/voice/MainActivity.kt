package com.rdreh.voice

import android.Manifest
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.speech.tts.TextToSpeech
import android.widget.Button
import android.widget.EditText
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.Locale
import kotlin.concurrent.thread

class MainActivity : AppCompatActivity(), TextToSpeech.OnInitListener {
    private lateinit var urlInput: EditText
    private lateinit var tokenInput: EditText
    private lateinit var speechModeBtn: Button
    private lateinit var updateBtn: Button
    private lateinit var statusText: TextView
    private lateinit var windowsRow: LinearLayout
    private lateinit var panesContainer: LinearLayout

    private var speechMode: String = Prefs.MODE_FULL
    private val refreshHandler = Handler(Looper.getMainLooper())
    @Volatile private var isRefreshing = false
    private val autoRefreshTask = object : Runnable {
        override fun run() {
            refreshPanes()
            refreshHandler.postDelayed(this, 3000L)
        }
    }
    private var selectedWindowIndex: Int? = -1 // -1 = Agents only (default), null = All windows
    private var lastState: JSONObject? = null
    private var lastTails: JSONObject = JSONObject()
    private val dismissedPromptFingerprints = mutableMapOf<Int, String>()
    private var tts: TextToSpeech? = null
    private var ttsReady = false

    private val permLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        tts = TextToSpeech(this, this)
        speechMode = Prefs.getSpeechMode(this)

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(36, 56, 36, 36)
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
        speechModeBtn = Button(this).apply {
            updateSpeechModeLabel(this)
            setOnClickListener {
                speechMode = when (speechMode) {
                    Prefs.MODE_FULL -> Prefs.MODE_BRIEF
                    Prefs.MODE_BRIEF -> Prefs.MODE_SILENT
                    else -> Prefs.MODE_FULL
                }
                Prefs.setSpeechMode(this@MainActivity, speechMode)
                updateSpeechModeLabel(this)
            }
        }
        statusText = TextView(this).apply {
            text = "Service: ${if (RdrVoiceService.isRunning.get()) "running" else "stopped"}"
            setPadding(0, 12, 0, 12)
        }

        val controlsRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            val saveBtn = Button(this@MainActivity).apply {
                text = "Save & Refresh"
                setOnClickListener {
                    Prefs.save(
                        this@MainActivity,
                        urlInput.text.toString(),
                        tokenInput.text.toString(),
                        speechMode,
                    )
                    refreshPanes()
                }
            }
            val serviceBtn = Button(this@MainActivity).apply {
                text = "Start Monitor"
                setOnClickListener {
                    Prefs.save(
                        this@MainActivity,
                        urlInput.text.toString(),
                        tokenInput.text.toString(),
                        speechMode,
                    )
                    val svc = Intent(this@MainActivity, RdrVoiceService::class.java)
                    ContextCompat.startForegroundService(this@MainActivity, svc)
                    statusText.text = "Monitor service started."
                }
            }
            addView(saveBtn)
            addView(serviceBtn)
        }

        val actionRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            val speakBtn = Button(this@MainActivity).apply {
                text = "Speak"
                setOnClickListener {
                    startActivity(Intent(this@MainActivity, VoiceCaptureActivity::class.java))
                }
            }
            val assistantBtn = Button(this@MainActivity).apply {
                text = "Assistant Settings"
                setOnClickListener {
                    startActivity(Intent(Settings.ACTION_VOICE_INPUT_SETTINGS))
                }
            }
            updateBtn = Button(this@MainActivity).apply {
                text = "Update App"
                setOnClickListener { installAppUpdate() }
            }
            addView(speakBtn)
            addView(assistantBtn)
            addView(updateBtn)
        }

        val winHeader = TextView(this).apply {
            text = "Windows"
            textSize = 16f
            setPadding(0, 20, 0, 8)
        }
        windowsRow = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        val windowsScroll = HorizontalScrollView(this).apply { addView(windowsRow) }

        val panesHeader = TextView(this).apply {
            text = "Panes"
            textSize = 16f
            setPadding(0, 20, 0, 8)
        }
        panesContainer = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }

        listOf(
            title,
            urlInput,
            tokenInput,
            speechModeBtn,
            controlsRow,
            actionRow,
            statusText,
            winHeader,
            windowsScroll,
            panesHeader,
            panesContainer,
        ).forEach { root.addView(it) }

        val scroll = ScrollView(this).apply {
            clipToPadding = false
            addView(root)
        }
        ViewCompat.setOnApplyWindowInsetsListener(scroll) { v, windowInsets ->
            val insets = windowInsets.getInsets(WindowInsetsCompat.Type.systemBars())
            v.setPadding(insets.left, insets.top, insets.right, insets.bottom + 48)
            windowInsets
        }
        setContentView(scroll)
        requestRuntimePermissions()
    }

    override fun onResume() {
        super.onResume()
        refreshHandler.removeCallbacks(autoRefreshTask)
        refreshHandler.post(autoRefreshTask)
        checkAppUpdate()
    }

    override fun onPause() {
        refreshHandler.removeCallbacks(autoRefreshTask)
        super.onPause()
    }

    override fun onDestroy() {
        tts?.shutdown()
        super.onDestroy()
    }

    override fun onInit(status: Int) {
        if (status == TextToSpeech.SUCCESS) {
            tts?.language = Locale.US
            tts?.setSpeechRate(1.08f)
            ttsReady = true
        }
    }

    private fun updateSpeechModeLabel(btn: Button) {
        btn.text = when (speechMode) {
            Prefs.MODE_BRIEF -> "Alerts: Brief (finish only)"
            Prefs.MODE_SILENT -> "Alerts: Silent (no TTS)"
            else -> "Alerts: Full (read output)"
        }
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

    private fun refreshPanes() {
        if (isRefreshing) return
        isRefreshing = true
        val url = Prefs.getUrl(this)
        val token = Prefs.getToken(this)
        thread {
            val res = runCatching { RdrApiClient.getJson(url, token, "/api/panes") }
                .getOrElse { JSONObject().put("ok", false).put("error", it.message ?: "Failed") }
            var tailsObj = JSONObject()
            if (res.optBoolean("ok", false)) {
                val panes = res.optJSONArray("panes") ?: JSONArray()
                val ids = (0 until panes.length()).map { panes.getJSONObject(it).optInt("id") }
                if (ids.isNotEmpty()) {
                    val tailsRes = runCatching {
                        RdrApiClient.getJson(url, token, "/api/tails?panes=${ids.joinToString(",")}&lines=30")
                    }.getOrNull()
                    if (tailsRes != null && tailsRes.optBoolean("ok", false)) {
                        tailsObj = tailsRes.optJSONObject("tails") ?: JSONObject()
                    }
                }
            }
            runOnUiThread {
                isRefreshing = false
                if (!res.optBoolean("ok", false)) {
                    statusText.text = "Error: ${res.optString("error", "offline")}"
                    return@runOnUiThread
                }
                lastState = res
                lastTails = tailsObj
                val c = res.optJSONObject("counts")
                val total = c?.optInt("total", 0) ?: 0
                val busy = c?.optInt("busy", 0) ?: 0
                val done = c?.optInt("finished", 0) ?: 0
                statusText.text = "Connected: $total agents ($busy working, $done done)"
                renderDashboard(res)
            }
        }
    }

    private fun renderDashboard(state: JSONObject) {
        windowsRow.removeAllViews()
        panesContainer.removeAllViews()

        val workspaces = state.optJSONArray("workspaces") ?: JSONArray()
        val panes = state.optJSONArray("panes") ?: JSONArray()
        val paneById = mutableMapOf<Int, JSONObject>()
        for (i in 0 until panes.length()) {
            val p = panes.getJSONObject(i)
            paneById[p.optInt("id")] = p
        }

        val agentsOnlyBtn = Button(this).apply {
            val agentCount = (0 until panes.length()).count { panes.getJSONObject(it).optBoolean("agent", false) }
            text = "Agents ($agentCount)"
            alpha = if (selectedWindowIndex == -1) 1.0f else 0.6f
            setOnClickListener {
                selectedWindowIndex = -1
                lastState?.let(::renderDashboard)
            }
        }
        windowsRow.addView(agentsOnlyBtn)

        val allBtn = Button(this).apply {
            text = "All (${panes.length()})"
            alpha = if (selectedWindowIndex == null) 1.0f else 0.6f
            setOnClickListener {
                selectedWindowIndex = null
                lastState?.let(::renderDashboard)
            }
        }
        windowsRow.addView(allBtn)

        for (i in 0 until workspaces.length()) {
            val ws = workspaces.getJSONObject(i)
            val idx = ws.optInt("index")
            val name = ws.optString("name", "win $idx")
            val wsPanes = ws.optJSONArray("panes") ?: JSONArray()
            var busyCount = 0
            for (j in 0 until wsPanes.length()) {
                val pObj = wsPanes.optJSONObject(j) ?: paneById[wsPanes.optInt(j)]
                if (pObj?.optString("state") == "working") busyCount++
            }
            val badge = if (busyCount > 0) "$busyCount busy" else "${wsPanes.length()} idle"
            val btn = Button(this).apply {
                text = "$idx: $name ($badge)"
                alpha = if (selectedWindowIndex == idx) 1.0f else 0.65f
                setOnClickListener {
                    selectedWindowIndex = idx
                    lastState?.let(::renderDashboard)
                }
            }
            windowsRow.addView(btn)
        }

        if (selectedWindowIndex == -1) {
            var shown = 0
            for (i in 0 until panes.length()) {
                val p = panes.getJSONObject(i)
                if (!p.optBoolean("agent", false)) continue
                panesContainer.addView(buildPaneCard(p))
                shown++
            }
            if (shown == 0) {
                panesContainer.addView(TextView(this).apply {
                    text = "No active agents detected."
                    setPadding(0, 16, 0, 16)
                })
            }
            return
        }

        for (i in 0 until workspaces.length()) {
            val ws = workspaces.getJSONObject(i)
            val idx = ws.optInt("index")
            if (selectedWindowIndex != null && selectedWindowIndex != idx) continue
            val name = ws.optString("name", "window $idx")
            val wsPanes = ws.optJSONArray("panes") ?: JSONArray()
            if (wsPanes.length() == 0) continue

            val groupHeader = TextView(this).apply {
                text = "Window $idx · $name"
                textSize = 15f
                setTextColor(Color.parseColor("#93C5FD"))
                setPadding(0, 16, 0, 6)
            }
            panesContainer.addView(groupHeader)

            for (j in 0 until wsPanes.length()) {
                val p = wsPanes.optJSONObject(j) ?: paneById[wsPanes.optInt(j)] ?: continue
                panesContainer.addView(buildPaneCard(p))
            }
        }
    }

    private fun buildPaneCard(p: JSONObject): LinearLayout {
        val paneId = p.optInt("id")
        val isAgent = p.optBoolean("agent", false)
        val agentNum = if (p.has("agent_num") && !p.isNull("agent_num")) p.optInt("agent_num") else null
        val state = p.optString("state", "idle")
        val job = p.optString("job_label", "").ifEmpty { p.optString("title", "pane $paneId") }
        val label = if (isAgent && agentNum != null) "Agent $agentNum · $job" else "Pane $paneId · $job"

        return LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(24, 18, 24, 18)
            setBackgroundColor(Color.parseColor("#1E293B"))
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT,
            ).apply {
                bottomMargin = 16
            }

            val header = TextView(this@MainActivity).apply {
                text = "$label  [${state.uppercase()}]"
                textSize = 14f
                setTextColor(
                    if (state == "working") Color.parseColor("#FBBF24") else Color.parseColor("#86EFAC")
                )
            }
            addView(header)

            val tailInfo = lastTails.optJSONObject(paneId.toString())
            val fullMsg = tailInfo?.optString("message", "")?.trim().orEmpty()
                .ifEmpty { tailInfo?.optString("spoken", "")?.trim().orEmpty() }
            val question = tailInfo?.optString("question", "")?.trim().orEmpty()
            val options = tailInfo?.optJSONArray("options")
            if (fullMsg.isNotEmpty()) {
                addView(TextView(this@MainActivity).apply {
                    text = fullMsg
                    textSize = 12f
                    setTextColor(Color.parseColor("#CBD5E1"))
                    setBackgroundColor(Color.parseColor("#0F172A"))
                    setPadding(14, 10, 14, 10)
                    setTextIsSelectable(true)
                })
            }
            val promptFingerprint = "$question\n${options?.toString().orEmpty()}"
            val hasPrompt = question.isNotEmpty() || (options != null && options.length() > 0)
            if (!hasPrompt) {
                dismissedPromptFingerprints.remove(paneId)
            }
            val isDismissed = hasPrompt && dismissedPromptFingerprints[paneId] == promptFingerprint
            if (!isDismissed && question.isNotEmpty() && question != fullMsg) {
                addView(TextView(this@MainActivity).apply {
                    text = question
                    textSize = 13f
                    setTextColor(Color.parseColor("#E2E8F0"))
                    setPadding(0, 8, 0, 6)
                })
            }
            if (!isDismissed && options != null && options.length() > 0) {
                for (k in 0 until options.length()) {
                    val opt = options.optJSONObject(k) ?: continue
                    val num = opt.optInt("num")
                    val optLabel = opt.optString("label", "")
                    addView(Button(this@MainActivity).apply {
                        text = "$num: $optLabel"
                        setOnClickListener { quickSend(paneId, num.toString()) }
                    })
                }
            }
            if (!isDismissed && hasPrompt) {
                addView(Button(this@MainActivity).apply {
                    text = if (options != null && options.length() > 0) "Dismiss Options" else "Dismiss"
                    textSize = 11f
                    setOnClickListener {
                        dismissedPromptFingerprints[paneId] = promptFingerprint
                        lastState?.let(::renderDashboard)
                    }
                })
            }

            val btns = LinearLayout(this@MainActivity).apply {
                orientation = LinearLayout.HORIZONTAL
                addView(Button(this@MainActivity).apply {
                    text = "Read"
                    setOnClickListener { readPane(paneId, label) }
                })
                addView(Button(this@MainActivity).apply {
                    text = "Yes"
                    setOnClickListener { quickSend(paneId, "y") }
                })
                addView(Button(this@MainActivity).apply {
                    text = "No"
                    setOnClickListener { quickSend(paneId, "n") }
                })
                addView(Button(this@MainActivity).apply {
                    text = "Msg"
                    setOnClickListener { promptAndSend(paneId, label) }
                })
            }
            val btns2 = LinearLayout(this@MainActivity).apply {
                orientation = LinearLayout.HORIZONTAL
                addView(Button(this@MainActivity).apply {
                    text = "Compact"
                    setOnClickListener { quickSend(paneId, "/compact") }
                })
                addView(Button(this@MainActivity).apply {
                    text = "Clear"
                    setOnClickListener { quickSend(paneId, "/clear") }
                })
            }
            addView(btns)
            addView(btns2)
        }
    }

    private fun promptAndSend(paneId: Int, label: String) {
        val input = EditText(this).apply { hint = "Type message for $label" }
        AlertDialog.Builder(this)
            .setTitle("Send to $label")
            .setView(input)
            .setPositiveButton("Send") { _, _ ->
                val msg = input.text.toString().trim()
                if (msg.isNotEmpty()) quickSend(paneId, msg)
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    private fun readPane(paneId: Int, label: String) {
        val url = Prefs.getUrl(this)
        val token = Prefs.getToken(this)
        thread {
            val tail = runCatching { RdrApiClient.getJson(url, token, "/api/tail?pane=$paneId&lines=40") }
                .getOrNull()
            val spoken = tail?.optString("spoken", "")?.ifEmpty { "No output." } ?: "Failed to read."
            runOnUiThread {
                statusText.text = "$label: $spoken"
                if (ttsReady && speechMode != Prefs.MODE_SILENT) {
                    val msg = if (speechMode == Prefs.MODE_BRIEF) "$label." else "$label. $spoken"
                    tts?.speak(msg, TextToSpeech.QUEUE_FLUSH, null, "manual-$paneId")
                }
            }
        }
    }

    private fun quickSend(paneId: Int, text: String) {
        val url = Prefs.getUrl(this)
        val token = Prefs.getToken(this)
        thread {
            runCatching {
                RdrApiClient.postJson(
                    url,
                    token,
                    "/api/send",
                    JSONObject().put("pane", paneId).put("text", text).put("enter", true),
                )
            }
            runOnUiThread {
                refreshPanes()
                refreshHandler.postDelayed({ refreshPanes() }, 600L)
                refreshHandler.postDelayed({ refreshPanes() }, 1600L)
            }
        }
    }

    private fun checkAppUpdate() {
        val url = Prefs.getUrl(this)
        val token = Prefs.getToken(this)
        thread {
            val res = runCatching { RdrApiClient.getJson(url, token, "/api/app/version") }.getOrNull()
            val available = res?.optBoolean("available", false) == true
            val sha = res?.optString("sha256", "").orEmpty()
            val known = Prefs.getLastApkSha(this)
            runOnUiThread {
                updateBtn.text = if (available && sha.isNotEmpty() && sha != known) {
                    "Update App (new)"
                } else {
                    "Update App"
                }
            }
        }
    }

    private fun installAppUpdate() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && !packageManager.canRequestPackageInstalls()) {
            statusText.text = "Allow 'Install unknown apps', then tap Update App again."
            startActivity(
                Intent(
                    Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                    Uri.parse("package:$packageName"),
                ),
            )
            return
        }
        val url = Prefs.getUrl(this)
        val token = Prefs.getToken(this)
        statusText.text = "Downloading update..."
        thread {
            val ver = runCatching { RdrApiClient.getJson(url, token, "/api/app/version") }.getOrNull()
            val sha = ver?.optString("sha256", "").orEmpty()
            val dest = File(cacheDir, "updates/rdreh-voice.apk")
            val result = runCatching {
                RdrApiClient.downloadFile(url, token, "/api/app/apk", dest)
            }
            runOnUiThread {
                if (result.isFailure) {
                    statusText.text = "Update failed: ${result.exceptionOrNull()?.message}"
                    return@runOnUiThread
                }
                if (sha.isNotEmpty()) {
                    Prefs.setLastApkSha(this, sha)
                }
                val uri = FileProvider.getUriForFile(this, "$packageName.fileprovider", dest)
                val installIntent = Intent(Intent.ACTION_VIEW).apply {
                    setDataAndType(uri, "application/vnd.android.package-archive")
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
                }
                startActivity(installIntent)
            }
        }
    }
}
