/// オフラインキュー・サーバー URL・API トークンの永続ストア。
///
/// SharedPreferences を使い、以下を管理する:
/// - サーバー URL (デフォルト: http://localhost:8989)
/// - API トークン (サーバーの API_TOKEN。空ならヘッダを送らない)
/// - サーバー未接続時に蓄積した URL のキュー
/// - 直近の共有送信結果 (ShareActivity.kt も同じキーに書く)
///
/// キー名は Android 側 (`FlutterSharedPreferences` の `flutter.` 付きキー) と
/// ShareActivity.kt で共有している。変更する場合は両方直すこと。
library;

import 'dart:convert';
import 'package:shared_preferences/shared_preferences.dart';

import 'url_utils.dart';

const _kServerUrl    = 'xkeeper_server_url';
const _kApiToken     = 'xkeeper_api_token';
const _kOfflineQueue = 'xkeeper_offline_queue';
const _kLastResult   = 'xkeeper_last_result';
const kDefaultServer = 'http://localhost:8989';

class QueueStore {
  QueueStore(this._prefs);

  final SharedPreferences _prefs;

  /// ネイティブ側 (ShareActivity) が書いた値を読み直す。
  ///
  /// SharedPreferences はインスタンス内にキャッシュを持つため、
  /// 再開時やキュー操作前に呼ばないとネイティブの更新が見えない。
  Future<void> reload() => _prefs.reload();

  // ── サーバー URL ───────────────────────────────────────────────────────────

  String get serverUrl {
    final normalized = normalizeServerUrl(_prefs.getString(_kServerUrl) ?? '');
    return normalized.isEmpty ? kDefaultServer : normalized;
  }

  /// 保存された生の値 (未設定なら空文字)。設定画面の初期値用。
  String get rawServerUrl => _prefs.getString(_kServerUrl) ?? '';

  Future<void> setServerUrl(String url) =>
      _prefs.setString(_kServerUrl, normalizeServerUrl(url));

  // ── API トークン ───────────────────────────────────────────────────────────

  String get apiToken => normalizeApiToken(_prefs.getString(_kApiToken));

  Future<void> setApiToken(String token) =>
      _prefs.setString(_kApiToken, normalizeApiToken(token));

  // ── 直近の共有送信結果 ─────────────────────────────────────────────────────

  String get lastResult => _prefs.getString(_kLastResult) ?? '';

  Future<void> setLastResult(String result) =>
      _prefs.setString(_kLastResult, result);

  // ── オフラインキュー ────────────────────────────────────────────────────────

  List<String> get offlineQueue {
    try {
      final raw = _prefs.getString(_kOfflineQueue) ?? '[]';
      return List<String>.from(jsonDecode(raw) as List);
    } catch (_) {
      return [];
    }
  }

  Future<void> enqueue(String url) async {
    final q = offlineQueue;
    if (!q.contains(url)) {
      q.add(url);
      await _save(q);
    }
  }

  Future<void> remove(String url) async {
    final q = offlineQueue..remove(url);
    await _save(q);
  }

  Future<void> clear() => _prefs.setString(_kOfflineQueue, '[]');

  Future<void> _save(List<String> q) =>
      _prefs.setString(_kOfflineQueue, jsonEncode(q));
}
