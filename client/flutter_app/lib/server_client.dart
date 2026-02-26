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
}
