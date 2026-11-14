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
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 共有インテント (ACTION_SEND / ACTION_VIEW) を処理する透明 Activity。
 *
 * Flutter を起動せずネイティブだけでサーバーへ送信する。
 * 設定 (サーバー URL / API トークン) は Flutter の shared_preferences と同じ
 * SharedPreferences ファイル `FlutterSharedPreferences` の `flutter.` 付きキーから読む。
 * キー名は lib/queue_store.dart と共有している (変更時は両方直すこと)。
 */
class ShareActivity : Activity() {

    companion object {
        private const val PREFS_NAME = "FlutterSharedPreferences"
        private const val KEY_SERVER_URL = "flutter.xkeeper_server_url"
        private const val KEY_API_TOKEN = "flutter.xkeeper_api_token"
        private const val KEY_OFFLINE_QUEUE = "flutter.xkeeper_offline_queue"
        private const val KEY_LAST_RESULT = "flutter.xkeeper_last_result"

        private const val CONNECT_TIMEOUT_MS = 5_000
        private const val READ_TIMEOUT_MS = 10_000

        /** サーバーが受け付けるドメイン (src/patterns.py の API_URL_PATTERN と同期)。先頭ほど優先。 */
        private val SUPPORTED_URL_PATTERNS = listOf(
            Regex("""^https?://(?:twitter\.com|x\.com)/[A-Za-z0-9_]+/(?:status/\d+|media)"""),
            Regex("""^https?://(?:www\.)?pixiv\.net/(?:en/)?artworks/\d+"""),
            Regex("""^https?://(?:i\.)?imgur\.com/[A-Za-z0-9/_\-\.]+"""),
            Regex("""^https?://(?:www\.)?youtube\.com/(?:watch|shorts/[A-Za-z0-9_-]+)"""),
            Regex("""^https?://youtu\.be/[A-Za-z0-9_-]+"""),
            Regex("""^https?://(?:www\.)?tiktok\.com/(?:@[^/\s]+/video/\d+|t/[A-Za-z0-9]+)"""),
            Regex("""^https?://(?:www\.)?nicovideo\.jp/watch/[A-Za-z0-9]+"""),
        )

        private val URL_RE = Regex("""https?://[^\s<>"'`]+""")

        /** URL 末尾に付きがちな句読点・閉じ括弧。 */
        private const val TRAILING_JUNK = ".,;:!?)]}>,。「」『』（）【】…'\"`"

        /** 二重実行ガード (共有メニューの連打対策)。 */
        @Volatile private var sending = false
    }

    private data class SendResult(val ok: Boolean, val message: String)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        if (sending) {
            toast("前回の送信を処理中です")
            finish()
            return
        }

        val incoming = intent
        val text = incoming?.getStringExtra(Intent.EXTRA_TEXT) ?: incoming?.dataString
        if (text.isNullOrBlank()) {
            toast("共有テキストが空です")
            finish()
            return
        }

        val urls = extractSupportedUrls(text)
        if (urls.isEmpty()) {
            val reason = if (extractUrls(text).isEmpty()) {
                "URL が見つかりません"
            } else {
                "対応していない URL です (X/Pixiv/Imgur/YouTube/TikTok/ニコニコ)"
            }
            toast(reason)
            finish()
            return
        }

        val prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
        val serverUrl = normalizeServerUrl(prefs.getString(KEY_SERVER_URL, null))
        if (serverUrl == null) {
            // 送信先が無いので URL を失わないようキューに退避し、設定画面へ誘導する
            saveOffline(prefs, urls)
            persistLastResult(prefs, "サーバー URL 未設定。設定後にアプリを開いて再送してください")
            toast("サーバー URL 未設定。アプリで設定してください")
            startActivity(
                Intent(this, MainActivity::class.java)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            )
            finish()
            return
        }

        val token = prefs.getString(KEY_API_TOKEN, null)?.trim()?.takeIf { it.isNotEmpty() }

        sending = true
        // 送信中は finish しない (プロセスを生かして結果を受け取る)
        CoroutineScope(Dispatchers.IO).launch {
            val result = runCatching { postUrls(serverUrl, token, urls) }
                .getOrElse { SendResult(false, "送信失敗: ${it.message ?: it.javaClass.simpleName}") }
            sending = false
            if (result.ok) {
                removeOffline(prefs, urls)
            } else {
                // 失敗時も URL を失わない。次回アプリ起動時に再送される
                saveOffline(prefs, urls)
            }
            persistLastResult(prefs, result.message)
            runOnUiThread {
                toast(result.message)
                finish()
            }
        }
    }

    // ── 送信 ─────────────────────────────────────────────────────────────────

    private fun postUrls(baseUrl: String, token: String?, urls: List<String>): SendResult {
        var conn: HttpURLConnection? = null
        return try {
            val payload = JSONObject().put("urls", JSONArray(urls)).toString()
            // normalizeServerUrl が http/https を保証しているのでキャストは成立する
            val urlConn = (URL("$baseUrl/api/queue").openConnection() as? HttpURLConnection)
                ?: return SendResult(false, "サーバー URL のスキームが不正です")
            urlConn.apply {
                requestMethod = "POST"
                connectTimeout = CONNECT_TIMEOUT_MS
                readTimeout = READ_TIMEOUT_MS
                doOutput = true
                useCaches = false
                setRequestProperty("Content-Type", "application/json")
                setRequestProperty("Accept", "application/json")
                if (token != null) setRequestProperty("X-API-Token", token)
            }
            conn = urlConn
            urlConn.outputStream.use { it.write(payload.toByteArray(Charsets.UTF_8)) }

            val code = urlConn.responseCode
            val body = readBody(urlConn, code)
            when {
                code == 202 || code == 200 -> {
                    val accepted = runCatching {
                        JSONObject(body).optJSONArray("accepted")?.length() ?: urls.size
                    }.getOrDefault(urls.size)
                    SendResult(true, "送信完了: ${accepted} 件")
                }
                code == 401 || code == 403 ->
                    SendResult(false, "認証エラー (HTTP $code)。API トークンを確認してください")
                code == 400 ->
                    SendResult(false, "サーバーが URL を拒否しました (HTTP 400)")
                code == 404 ->
                    SendResult(false, "エンドポイントが見つかりません (HTTP 404)。URL を確認してください")
                code in 500..599 ->
                    SendResult(false, "サーバーエラー (HTTP $code)")
                else ->
                    SendResult(false, "送信失敗 (HTTP $code)")
            }
        } catch (e: IOException) {
            SendResult(false, "接続失敗: ${e.message ?: "ネットワークエラー"}")
        } catch (e: Exception) {
            SendResult(false, "送信失敗: ${e.message ?: e.javaClass.simpleName}")
        } finally {
            conn?.disconnect()
        }
    }

    private fun readBody(conn: HttpURLConnection, code: Int): String = runCatching {
        val stream = if (code in 200..299) conn.inputStream else conn.errorStream ?: return ""
        stream.bufferedReader().use { it.readText() }
    }.getOrDefault("")

    // ── URL 抽出 / 正規化 (lib/url_utils.dart と同一ロジック) ───────────────

    /** テキスト中の URL をすべて抽出する (重複除去・末尾句読点トリム済み)。 */
    private fun extractUrls(text: String): List<String> {
        val out = linkedSetOf<String>()
        for (m in URL_RE.findAll(text)) {
            var url = m.value
            while (url.isNotEmpty() && TRAILING_JUNK.contains(url.last())) {
                url = url.dropLast(1)
            }
            if (url.length > "https://".length) out.add(url)
        }
        return out.toList()
    }

    /** 対応 URL のみを優先順位順に返す。 */
    private fun extractSupportedUrls(text: String): List<String> {
        val candidates = extractUrls(text)
        val ordered = linkedSetOf<String>()
        for (pattern in SUPPORTED_URL_PATTERNS) {
            for (url in candidates) {
                if (pattern.containsMatchIn(url)) ordered.add(url)
            }
        }
        return ordered.toList()
    }

    /** スキーム補完・検証・末尾スラッシュ除去。不正なら null。 */
    private fun normalizeServerUrl(raw: String?): String? {
        var v = raw?.trim().orEmpty()
        if (v.isEmpty()) return null
        if (!SCHEME_RE.containsMatchIn(v)) v = "http://$v"
        val uri = runCatching { android.net.Uri.parse(v) }.getOrNull() ?: return null
        val scheme = uri.scheme?.lowercase()
        if (scheme != "http" && scheme != "https") return null
        if (uri.host.isNullOrEmpty()) return null
        return v.trimEnd('/')
    }

    // ── SharedPreferences ────────────────────────────────────────────────────

    /** Flutter の shared_preferences (JSON 配列) 互換でオフラインキューに追加する。 */
    private fun saveOffline(prefs: android.content.SharedPreferences, urls: List<String>) {
        val arr = runCatching {
            JSONArray(prefs.getString(KEY_OFFLINE_QUEUE, "[]") ?: "[]")
        }.getOrDefault(JSONArray())
        val existing = (0 until arr.length()).mapNotNull { arr.optString(it) }
        for (url in urls) {
            if (url !in existing) arr.put(url)
        }
        prefs.edit().putString(KEY_OFFLINE_QUEUE, arr.toString()).apply()
    }

    /** 送信成功した URL をオフラインキューから除く。 */
    private fun removeOffline(prefs: android.content.SharedPreferences, urls: List<String>) {
        val raw = prefs.getString(KEY_OFFLINE_QUEUE, null) ?: return
        val arr = runCatching { JSONArray(raw) }.getOrNull() ?: return
        val kept = JSONArray()
        var changed = false
        for (i in 0 until arr.length()) {
            val url = arr.optString(i)
            if (url in urls) changed = true else kept.put(url)
        }
        if (changed) prefs.edit().putString(KEY_OFFLINE_QUEUE, kept.toString()).apply()
    }

    private fun persistLastResult(prefs: android.content.SharedPreferences, message: String) {
        val ts = SimpleDateFormat("MM-dd HH:mm", Locale.getDefault()).format(Date())
        prefs.edit().putString(KEY_LAST_RESULT, "$ts $message").apply()
    }

    private fun toast(msg: String) =
        Toast.makeText(applicationContext, msg, Toast.LENGTH_LONG).show()
}

private val SCHEME_RE = Regex("""^[A-Za-z][A-Za-z0-9+.\-]*://""")
