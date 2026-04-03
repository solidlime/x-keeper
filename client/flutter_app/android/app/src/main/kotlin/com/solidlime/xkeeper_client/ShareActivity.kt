package com.solidlime.xkeeper_client

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.widget.Toast
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

class ShareActivity : Activity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // ウィンドウに何も描画しない（setContentView 不要）

        val sharedText = intent?.getStringExtra(Intent.EXTRA_TEXT)?.trim()
        if (sharedText.isNullOrEmpty() || !isSupportedUrl(sharedText)) {
            toast("対応していない URL です")
            finish()
            return
        }

        val prefs = getSharedPreferences("FlutterSharedPreferences", MODE_PRIVATE)

        // 即座にオフラインキューへ保存（UI をブロックしない）
        saveOffline(prefs, sharedText)
        toast("キューに追加しました")
        finish()

        // Activity 終了後もバックグラウンドで送信を試みる
        // 失敗してもオフラインキューが残るため、次回 Flutter 起動時に再送される
        CoroutineScope(Dispatchers.IO).launch {
            val serverUrl = (prefs.getString("flutter.xkeeper_server_url", null)
                ?: "http://localhost:8989").trimEnd('/')
            sendUrl(serverUrl, sharedText)
        }
    }

    // --- ヘルパー ---

    private fun isSupportedUrl(url: String): Boolean =
        Regex("""^https?://(?:(?:twitter\.com|x\.com)/[A-Za-z0-9_]+/(?:status/\d+|media)|(?:www\.)?pixiv\.net/(?:en/)?artworks/\d+|(?:i\.)?imgur\.com/.+)""")
            .containsMatchIn(url)

    /** 成功時はメッセージ、失敗時は null を返す */
    private fun sendUrl(serverUrl: String, url: String): String? = runCatching {
        val conn = URL("$serverUrl/api/queue").openConnection() as HttpURLConnection
        conn.apply {
            requestMethod = "POST"
            setRequestProperty("Content-Type", "application/json")
            connectTimeout = 5_000
            readTimeout = 5_000
            doOutput = true
        }
        val body = JSONObject().put("urls", JSONArray().put(url)).toString()
        conn.outputStream.use { it.write(body.toByteArray()) }
        if (conn.responseCode == 202) "送信完了: 1 件" else null
    }.getOrNull()

    /** FlutterSharedPreferences 互換フォーマットでオフラインキューに追加 */
    private fun saveOffline(prefs: android.content.SharedPreferences, url: String) {
        val key = "flutter.xkeeper_offline_queue"
        val raw = prefs.getString(key, "[]") ?: "[]"
        val arr = JSONArray(raw)
        // 重複チェック
        for (i in 0 until arr.length()) {
            if (arr.getString(i) == url) return
        }
        arr.put(url)
        prefs.edit().putString(key, arr.toString()).apply()
    }

    private fun toast(msg: String) =
        Toast.makeText(applicationContext, msg, Toast.LENGTH_SHORT).show()
}
