/// オフラインキューとサーバー URL の永続ストア。
///
/// SharedPreferences を使い、以下を管理する:
/// - サーバー URL (デフォルト: http://localhost:8989)
/// - サーバー未接続時に蓄積した URL のキュー
library;

import 'dart:convert';
import 'package:shared_preferences/shared_preferences.dart';

const _kServerUrl    = 'xkeeper_server_url';
const _kOfflineQueue = 'xkeeper_offline_queue';
const kDefaultServer = 'http://localhost:8989';

class QueueStore {
  QueueStore(this._prefs);

  final SharedPreferences _prefs;

  // ── サーバー URL ───────────────────────────────────────────────────────────

  String get serverUrl {
    final v = _prefs.getString(_kServerUrl) ?? kDefaultServer;
    return v.isEmpty ? kDefaultServer : v.replaceAll(RegExp(r'/$'), '');
  }

  Future<void> setServerUrl(String url) =>
      _prefs.setString(_kServerUrl, url.trim().replaceAll(RegExp(r'/$'), ''));

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
