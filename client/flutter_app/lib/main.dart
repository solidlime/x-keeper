/// x-keeper クライアントアプリのエントリーポイント。
///
/// Android の共有インテントで URL を受け取り、x-keeper サーバーに
/// ダウンロードキューとして送信する。サーバー未接続時は次回起動まで
/// ローカルにキューイングする。
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:receive_sharing_intent/receive_sharing_intent.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'queue_store.dart';
import 'server_client.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final prefs = await SharedPreferences.getInstance();
  runApp(XKeeperApp(store: QueueStore(prefs)));
}

class XKeeperApp extends StatelessWidget {
  const XKeeperApp({super.key, required this.store});

  final QueueStore store;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'x-keeper',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF1d9bf0),
          brightness: Brightness.dark,
        ),
        useMaterial3: true,
      ),
      home: HomePage(store: store),
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// ホーム画面
// ─────────────────────────────────────────────────────────────────────────────

class HomePage extends StatefulWidget {
  const HomePage({super.key, required this.store});

  final QueueStore store;

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  late final ServerClient _client;
  late StreamSubscription _intentSub;

  bool _serverOnline = false;
  String _lastMessage = '';

  @override
  void initState() {
    super.initState();
    _client = ServerClient(widget.store.serverUrl);

    // アプリ起動後: 疎通確認 + オフラインキューのフラッシュ
    _checkAndFlush();

    // 起動に使用した共有インテントを処理 (アプリが停止していた場合)
    ReceiveSharingIntent.instance.getInitialMedia().then(_handleSharedMedia);

    // アプリ起動中に届いた共有インテントを監視
    _intentSub = ReceiveSharingIntent.instance.getMediaStream().listen(
      _handleSharedMedia,
      onError: (err) => debugPrint('[x-keeper] インテント受信エラー: $err'),
    );
  }

  @override
  void dispose() {
    _intentSub.cancel();
    super.dispose();
  }

  // ── 共有インテント処理 ───────────────────────────────────────────────────

  Future<void> _handleSharedMedia(List<SharedMediaFile> files) async {
    if (files.isEmpty) return;

    // テキスト共有から URL を抽出する
    final urls = files
        .where((f) => f.type == SharedMediaType.text || f.type == SharedMediaType.url)
        .map((f) => f.path.trim())
        .where(_isSupportedUrl)
        .toList();

    if (urls.isEmpty) {
      _setMessage('対応していない URL です');
      return;
    }

    await _sendUrls(urls);
  }

  // ── URL 送信 ─────────────────────────────────────────────────────────────

  Future<void> _sendUrls(List<String> urls) async {
    try {
      final result = await _client.queueUrls(urls);
      setState(() {
        _serverOnline = true;
        _lastMessage = '送信完了: ${result.accepted.length} 件';
      });
      // 送信成功時にオフラインキューもフラッシュ
      await _flushQueue();
    } catch (_) {
      // サーバー未接続 → オフラインキューに保存
      for (final url in urls) {
        await widget.store.enqueue(url);
      }
      setState(() {
        _serverOnline = false;
        _lastMessage = '未接続。${urls.length} 件をキューに保存しました';
      });
    }
  }

  Future<void> _flushQueue() async {
    final q = widget.store.offlineQueue;
    if (q.isEmpty) return;
    try {
      await _client.queueUrls(q);
      await widget.store.clear();
      debugPrint('[x-keeper] オフラインキューをフラッシュ: ${q.length} 件');
    } catch (_) {
      // まだ未接続 → キューはそのまま保持
    }
  }

  Future<void> _checkAndFlush() async {
    final online = await _client.health();
    setState(() => _serverOnline = online);
    if (online) await _flushQueue();
  }

  void _setMessage(String msg) => setState(() => _lastMessage = msg);

  // ── ビルド ───────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final q = widget.store.offlineQueue;
    final scheme = Theme.of(context).colorScheme;

    return Scaffold(
      appBar: AppBar(
        title: const Text('x-keeper', style: TextStyle(fontWeight: FontWeight.bold)),
        actions: [
          IconButton(
            icon: const Icon(Icons.settings_outlined),
            tooltip: 'サーバー設定',
            onPressed: () => _openSettings(),
          ),
        ],
      ),
      body: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // 接続状態カード
            _StatusCard(online: _serverOnline, serverUrl: widget.store.serverUrl),
            const SizedBox(height: 16),

            // メッセージ
            if (_lastMessage.isNotEmpty)
              Card(
                color: scheme.surfaceContainerHigh,
                child: Padding(
                  padding: const EdgeInsets.all(14),
                  child: Text(_lastMessage, style: const TextStyle(fontSize: 14)),
                ),
              ),

            if (_lastMessage.isNotEmpty) const SizedBox(height: 16),

            // オフラインキュー
            if (q.isNotEmpty) ...[
              _QueueCard(
                queue: q,
                onFlush: () async {
                  await _checkAndFlush();
                  _setMessage(_serverOnline ? 'オフラインキューを送信しました' : 'サーバー未接続');
                },
                onClear: () async {
                  await widget.store.clear();
                  setState(() {});
                },
              ),
              const SizedBox(height: 16),
            ],

            // 使い方説明
            Expanded(
              child: _HelpCard(),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _openSettings() async {
    final updated = await Navigator.push<bool>(
      context,
      MaterialPageRoute(builder: (_) => SettingsPage(store: widget.store)),
    );
    if (updated == true) {
      // サーバー URL が変わったので再接続
      setState(() => _client = ServerClient(widget.store.serverUrl));
      await _checkAndFlush();
    }
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// 設定画面
// ─────────────────────────────────────────────────────────────────────────────

class SettingsPage extends StatefulWidget {
  const SettingsPage({super.key, required this.store});

  final QueueStore store;

  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  late final TextEditingController _urlCtrl;
  bool? _testResult;
  bool _testing = false;

  @override
  void initState() {
    super.initState();
    _urlCtrl = TextEditingController(text: widget.store.serverUrl);
  }

  @override
  void dispose() {
    _urlCtrl.dispose();
    super.dispose();
  }

  Future<void> _testConnection() async {
    setState(() { _testing = true; _testResult = null; });
    final ok = await ServerClient(_urlCtrl.text.trim()).health();
    setState(() { _testing = false; _testResult = ok; });
  }

  Future<void> _save() async {
    await widget.store.setServerUrl(_urlCtrl.text.trim());
    if (mounted) Navigator.pop(context, true);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('サーバー設定')),
      body: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text(
              'x-keeper サーバーの URL を入力してください。',
              style: TextStyle(fontSize: 14),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _urlCtrl,
              keyboardType: TextInputType.url,
              autocorrect: false,
              decoration: const InputDecoration(
                labelText: 'サーバー URL',
                hintText: 'http://192.168.1.10:8989',
                border: OutlineInputBorder(),
                prefixIcon: Icon(Icons.dns_outlined),
              ),
            ),
            const SizedBox(height: 12),

            // 接続テストボタン
            OutlinedButton.icon(
              onPressed: _testing ? null : _testConnection,
              icon: _testing
                  ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.wifi_tethering_outlined),
              label: const Text('接続テスト'),
            ),

            if (_testResult != null) ...[
              const SizedBox(height: 8),
              Row(
                children: [
                  Icon(
                    _testResult! ? Icons.check_circle : Icons.error_outline,
                    color: _testResult! ? Colors.green : Colors.red,
                    size: 18,
                  ),
                  const SizedBox(width: 6),
                  Text(
                    _testResult! ? '接続成功 ✓' : '接続できませんでした',
                    style: TextStyle(color: _testResult! ? Colors.green : Colors.red),
                  ),
                ],
              ),
            ],

            const SizedBox(height: 20),
            FilledButton.icon(
              onPressed: _save,
              icon: const Icon(Icons.save_outlined),
              label: const Text('保存'),
            ),
          ],
        ),
      ),
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// 小コンポーネント
// ─────────────────────────────────────────────────────────────────────────────

class _StatusCard extends StatelessWidget {
  const _StatusCard({required this.online, required this.serverUrl});

  final bool online;
  final String serverUrl;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: ListTile(
        leading: CircleAvatar(
          backgroundColor: online ? Colors.green : Colors.grey,
          child: Icon(
            online ? Icons.link : Icons.link_off,
            color: Colors.white,
            size: 20,
          ),
        ),
        title: Text(online ? '接続中' : '未接続', style: const TextStyle(fontWeight: FontWeight.bold)),
        subtitle: Text(serverUrl, style: const TextStyle(fontSize: 12)),
      ),
    );
  }
}

class _QueueCard extends StatelessWidget {
  const _QueueCard({required this.queue, required this.onFlush, required this.onClear});

  final List<String> queue;
  final VoidCallback onFlush;
  final VoidCallback onClear;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('オフラインキュー (${queue.length} 件)', style: const TextStyle(fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            ...queue.take(3).map((u) => Text(u, style: const TextStyle(fontSize: 11), maxLines: 1, overflow: TextOverflow.ellipsis)),
            if (queue.length > 3) Text('… 他 ${queue.length - 3} 件'),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: FilledButton.icon(
                    onPressed: onFlush,
                    icon: const Icon(Icons.send, size: 16),
                    label: const Text('今すぐ送信'),
                  ),
                ),
                const SizedBox(width: 8),
                TextButton(onPressed: onClear, child: const Text('クリア')),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _HelpCard extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: const [
            Text('使い方', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 15)),
            SizedBox(height: 10),
            Text('1. x-keeper サーバーを起動する', style: TextStyle(fontSize: 13)),
            SizedBox(height: 6),
            Text('2. X (Twitter) / Pixiv のブラウザで\n   共有ボタン → x-keeper を選択', style: TextStyle(fontSize: 13)),
            SizedBox(height: 6),
            Text('3. サーバーが自動的にダウンロードする', style: TextStyle(fontSize: 13)),
            SizedBox(height: 6),
            Text('※ 未接続時はキューに保存し、\n   次回接続時に自動送信します', style: TextStyle(fontSize: 12, color: Colors.grey)),
          ],
        ),
      ),
    );
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// URL バリデーション
// ─────────────────────────────────────────────────────────────────────────────

/// X/Pixiv/Imgur の URL かどうか判定する
bool _isSupportedUrl(String url) {
  return RegExp(
    r'^https?://(?:'
    r'(?:twitter\.com|x\.com)/[A-Za-z0-9_]+/(?:status/\d+|media)'
    r'|(?:www\.)?pixiv\.net/(?:en/)?artworks/\d+'
    r'|(?:i\.)?imgur\.com/.+'
    r')',
  ).hasMatch(url);
}
