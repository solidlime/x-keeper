/// x-keeper サーバーとの HTTP 通信クライアント。
///
/// サーバーが `API_TOKEN` を設定している場合は `X-API-Token` ヘッダを付ける。
/// (未設定のサーバーは無認証でも通るので、トークン空ならヘッダ自体を送らない)
library;

import 'dart:convert';
import 'package:http/http.dart' as http;

import 'url_utils.dart';

/// /api/queue への送信結果
class QueueResult {
  const QueueResult({required this.accepted, required this.rejected});
  final List<String> accepted;
  final List<String> rejected;
}

/// 疎通確認の結果。[message] は失敗理由 (成功時は空)。
class HealthResult {
  const HealthResult({required this.ok, this.message = ''});
  final bool ok;
  final String message;
}

class ServerClient {
  ServerClient(String serverUrl, [String apiToken = ''])
      : serverUrl = normalizeServerUrl(serverUrl),
        apiToken = normalizeApiToken(apiToken);

  final String serverUrl;
  final String apiToken;

  static const _timeout = Duration(seconds: 8);

  bool get hasServer => serverUrl.isNotEmpty;

  Uri _uri(String path) => Uri.parse('$serverUrl/api/$path');

  Map<String, String> _headers({bool json = false}) => {
        if (json) 'Content-Type': 'application/json',
        if (apiToken.isNotEmpty) 'X-API-Token': apiToken,
      };

  /// サーバーへの疎通確認。接続できれば ok=true を返す。
  Future<HealthResult> health() async {
    if (!hasServer) {
      return const HealthResult(ok: false, message: 'サーバー URL が未設定です');
    }
    try {
      final res = await http.get(_uri('health'), headers: _headers()).timeout(_timeout);
      if (res.statusCode == 200) return const HealthResult(ok: true);
      if (res.statusCode == 401 || res.statusCode == 403) {
        return HealthResult(
          ok: false,
          message: 'サーバーは応答していますが認証エラー (HTTP ${res.statusCode})。API トークンを確認してください',
        );
      }
      return HealthResult(ok: false, message: 'HTTP ${res.statusCode}');
    } catch (e) {
      return HealthResult(ok: false, message: '接続失敗: $e');
    }
  }

  /// URL をダウンロードキューに投入する。
  ///
  /// 成功すれば [QueueResult] を返す。失敗した場合は例外をスローする。
  Future<QueueResult> queueUrls(List<String> urls) async {
    if (!hasServer) throw Exception('サーバー URL が未設定です');

    final res = await http
        .post(
          _uri('queue'),
          headers: _headers(json: true),
          body: jsonEncode({'urls': urls}),
        )
        .timeout(_timeout);

    if (res.statusCode != 202 && res.statusCode != 200) {
      throw Exception(_errorText(res.statusCode, res.body));
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
        .get(_uri('history/export'), headers: _headers())
        .timeout(const Duration(seconds: 10));

    if (res.statusCode != 200) throw Exception(_errorText(res.statusCode, res.body));
    return res.body;
  }

  /// ダウンロード済み tweet ID 数を返す。
  Future<int> fetchHistoryCount() async {
    final res = await http.get(_uri('history/count'), headers: _headers()).timeout(_timeout);

    if (res.statusCode != 200) throw Exception(_errorText(res.statusCode, res.body));
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    return (data['count'] as num).toInt();
  }

  /// サーバーの処理待ちキュー一覧を取得する。
  ///
  /// 各アイテムは {"url": "..."} 形式のマップ。失敗した場合は例外をスローする。
  Future<List<Map<String, dynamic>>> fetchApiQueue() async {
    final res = await http.get(_uri('queue/status'), headers: _headers()).timeout(_timeout);
    if (res.statusCode != 200) throw Exception(_errorText(res.statusCode, res.body));
    final data = jsonDecode(res.body) as List;
    return data.cast<Map<String, dynamic>>();
  }

  /// サーバーの処理待ちキューから指定 URL の 1 件を削除する。
  Future<void> deleteApiQueueItem(String url) async {
    final res = await http
        .delete(
          _uri('queue/item'),
          headers: _headers(json: true),
          body: jsonEncode({'url': url}),
        )
        .timeout(_timeout);
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw Exception(_errorText(res.statusCode, res.body));
    }
  }

  /// サーバーの処理待ちキューを全件削除する。
  Future<void> clearApiQueue() async {
    final res = await http.post(_uri('queue/clear'), headers: _headers()).timeout(_timeout);
    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw Exception(_errorText(res.statusCode, res.body));
    }
  }

  /// サーバーの最近の処理ログ (最新 5 件) を取得する。
  ///
  /// 各エントリは {"urls": [...], "status": "success"|"failure",
  ///   "file_count": N, "error": "...", "ts": "ISO8601"} 形式。
  Future<List<Map<String, dynamic>>> fetchRecentLogs() async {
    final res = await http.get(_uri('logs/recent'), headers: _headers()).timeout(_timeout);
    if (res.statusCode != 200) throw Exception(_errorText(res.statusCode, res.body));
    final data = jsonDecode(res.body) as List;
    return data.cast<Map<String, dynamic>>();
  }

  /// TwitterMediaHarvest 互換フォーマットの tweet ID をインポートする。
  ///
  /// 成功した場合はインポートされた件数を返す。失敗した場合は例外をスローする。
  Future<int> importHistory(String jsonData) async {
    final res = await http
        .post(_uri('history/import'), headers: _headers(json: true), body: jsonData)
        .timeout(const Duration(seconds: 10));

    if (res.statusCode != 200) throw Exception(_errorText(res.statusCode, res.body));
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    return (data['imported'] as num).toInt();
  }

  String _errorText(int status, String body) {
    if (status == 401 || status == 403) return 'API トークンが拒否されました (HTTP $status)';
    final trimmed = body.length > 200 ? '${body.substring(0, 200)}…' : body;
    return 'HTTP $status: $trimmed';
  }
}
