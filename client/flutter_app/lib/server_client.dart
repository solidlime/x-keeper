/// x-keeper サーバーとの HTTP 通信クライアント。
library;

import 'dart:convert';
import 'package:http/http.dart' as http;

/// /api/queue への送信結果
class QueueResult {
  const QueueResult({required this.accepted, required this.rejected});
  final List<String> accepted;
  final List<String> rejected;
}

class ServerClient {
  ServerClient(this.serverUrl);

  final String serverUrl;

  static const _timeout = Duration(seconds: 5);

  /// サーバーへの疎通確認。接続できれば true を返す。
  Future<bool> health() async {
    try {
      final res = await http
          .get(Uri.parse('$serverUrl/api/health'))
          .timeout(_timeout);
      return res.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  /// URL をダウンロードキューに投入する。
  ///
  /// 成功すれば [QueueResult] を返す。失敗した場合は例外をスローする。
  Future<QueueResult> queueUrls(List<String> urls) async {
    final res = await http
        .post(
          Uri.parse('$serverUrl/api/queue'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode({'urls': urls}),
        )
        .timeout(_timeout);

    if (res.statusCode != 202) {
      throw Exception('HTTP ${res.statusCode}: ${res.body}');
    }

    final data = jsonDecode(res.body) as Map<String, dynamic>;
    return QueueResult(
      accepted: List<String>.from(data['accepted'] as List? ?? []),
      rejected: List<String>.from(data['rejected'] as List? ?? []),
    );
  }

  /// ダウンロード履歴を TwitterMediaHarvest 互換フォーマットでエクスポートする。
  Future<String> exportHistory() async {
    final res = await http
        .get(Uri.parse('$serverUrl/api/history/export'))
        .timeout(const Duration(seconds: 10));

    if (res.statusCode != 200) {
      throw Exception('HTTP ${res.statusCode}');
    }
    return res.body;
  }

  /// ダウンロード済み tweet ID 数を返す。
  Future<int> fetchHistoryCount() async {
    final res = await http
        .get(Uri.parse('$serverUrl/api/history/count'))
        .timeout(_timeout);

    if (res.statusCode != 200) {
      throw Exception('HTTP ${res.statusCode}');
    }
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    return (data['count'] as num).toInt();
  }

  /// サーバーの処理待ちキュー一覧を取得する。
  ///
  /// 各アイテムは {"url": "..."} 形式のマップ。失敗した場合は例外をスローする。
  Future<List<Map<String, dynamic>>> fetchApiQueue() async {
    final res = await http
        .get(Uri.parse('$serverUrl/api/queue/status'))
        .timeout(_timeout);
    if (res.statusCode != 200) throw Exception('HTTP ${res.statusCode}');
    final data = jsonDecode(res.body) as List;
    return data.cast<Map<String, dynamic>>();
  }

  /// サーバーの処理待ちキューから指定 URL の 1 件を削除する。
  Future<void> deleteApiQueueItem(String url) async {
    final res = await http
        .delete(
          Uri.parse('$serverUrl/api/queue/item'),
          headers: {'Content-Type': 'application/json'},
          body: jsonEncode({'url': url}),
        )
        .timeout(_timeout);
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw Exception('HTTP ${res.statusCode}: ${res.body}');
    }
  }

  /// サーバーの処理待ちキューを全件削除する。
  Future<void> clearApiQueue() async {
    final res = await http
        .post(Uri.parse('$serverUrl/api/queue/clear'))
        .timeout(_timeout);
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw Exception('HTTP ${res.statusCode}: ${res.body}');
    }
  }

  /// サーバーの最近の処理ログ (最新 5 件) を取得する。
  ///
  /// 各エントリは {"urls": [...], "status": "success"|"failure",
  ///   "file_count": N, "error": "...", "ts": "ISO8601"} 形式。
  Future<List<Map<String, dynamic>>> fetchRecentLogs() async {
    final res = await http
        .get(Uri.parse('$serverUrl/api/logs/recent'))
        .timeout(_timeout);
    if (res.statusCode != 200) throw Exception('HTTP ${res.statusCode}');
    final data = jsonDecode(res.body) as List;
    return data.cast<Map<String, dynamic>>();
  }

  /// TwitterMediaHarvest 互換フォーマットの tweet ID をインポートする。
  ///
  /// 成功した場合はインポートされた件数を返す。失敗した場合は例外をスローする。
  Future<int> importHistory(String jsonData) async {
    final res = await http
        .post(
          Uri.parse('$serverUrl/api/history/import'),
          headers: {'Content-Type': 'application/json'},
          body: jsonData,
        )
        .timeout(const Duration(seconds: 10));

    if (res.statusCode != 200) {
      throw Exception('HTTP ${res.statusCode}: ${res.body}');
    }
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    return (data['imported'] as num).toInt();
  }
}
