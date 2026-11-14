import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:xkeeper_client/main.dart';
import 'package:xkeeper_client/queue_store.dart';

void main() {
  testWidgets('起動時に接続状態カードと設定ボタンが表示される', (tester) async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();

    await tester.pumpWidget(XKeeperApp(store: QueueStore(prefs)));
    await tester.pump();

    expect(find.text('x-keeper'), findsOneWidget);
    expect(find.byIcon(Icons.settings_outlined), findsOneWidget);
    expect(find.text('未接続'), findsOneWidget);
    expect(find.text('http://localhost:8989'), findsOneWidget);
  });

  testWidgets('API トークンが空なら認証ヘッダを送らない設定になる', (tester) async {
    SharedPreferences.setMockInitialValues({
      'xkeeper_server_url': 'http://host:5000/',
      'xkeeper_api_token': '',
    });
    final prefs = await SharedPreferences.getInstance();
    final store = QueueStore(prefs);

    expect(store.serverUrl, 'http://host:5000');
    expect(store.apiToken, '');
  });
}
