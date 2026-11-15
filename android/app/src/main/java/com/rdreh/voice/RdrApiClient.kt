package com.rdreh.voice

import org.json.JSONObject
import java.io.BufferedReader
import java.io.File
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL

object RdrApiClient {
    fun getJson(baseUrl: String, token: String, path: String): JSONObject {
        val conn = (URL("$baseUrl$path").openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 5000
            readTimeout = 8000
            if (token.isNotEmpty()) setRequestProperty("Authorization", "Bearer $token")
        }
        return readJson(conn)
    }

    fun postJson(baseUrl: String, token: String, path: String, body: JSONObject): JSONObject {
        val conn = (URL("$baseUrl$path").openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 5000
            readTimeout = 10000
            doOutput = true
            setRequestProperty("Content-Type", "application/json")
            if (token.isNotEmpty()) setRequestProperty("Authorization", "Bearer $token")
        }
        conn.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
        return readJson(conn)
    }

    fun streamEvents(
        baseUrl: String,
        token: String,
        isRunning: () -> Boolean,
        onPanes: (JSONObject) -> Unit,
    ) {
        val conn = (URL("$baseUrl/api/events").openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 5000
            readTimeout = 30000
            setRequestProperty("Accept", "text/event-stream")
            if (token.isNotEmpty()) setRequestProperty("Authorization", "Bearer $token")
        }
        try {
            BufferedReader(InputStreamReader(conn.inputStream, Charsets.UTF_8)).use { reader ->
                var eventName = ""
                val dataBuf = StringBuilder()
                while (isRunning()) {
                    val line = reader.readLine() ?: break
                    when {
                        line.startsWith("event:") -> eventName = line.substring(6).trim()
                        line.startsWith("data:") -> {
                            if (dataBuf.isNotEmpty()) dataBuf.append('\n')
                            dataBuf.append(line.substring(5).trim())
                        }
                        line.isEmpty() -> {
                            if (eventName == "panes" && dataBuf.isNotEmpty()) {
                                runCatching { JSONObject(dataBuf.toString()) }.onSuccess(onPanes)
                            }
                            eventName = ""
                            dataBuf.clear()
                        }
                    }
                }
            }
        } finally {
            conn.disconnect()
        }
    }

    private fun readJson(conn: HttpURLConnection): JSONObject {
        return try {
            val stream = if (conn.responseCode in 200..299) conn.inputStream else conn.errorStream
            val text = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() } ?: "{}"
            JSONObject(text)
        } finally {
            conn.disconnect()
        }
    }

    fun downloadFile(baseUrl: String, token: String, path: String, dest: File) {
        val conn = (URL("$baseUrl$path").openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 5000
            readTimeout = 30000
            if (token.isNotEmpty()) setRequestProperty("Authorization", "Bearer $token")
        }
        try {
            if (conn.responseCode !in 200..299) {
                throw IllegalStateException("HTTP ${conn.responseCode}")
            }
            dest.parentFile?.mkdirs()
            conn.inputStream.use { input ->
                dest.outputStream().use { output -> input.copyTo(output) }
            }
        } finally {
            conn.disconnect()
        }
    }
}
