import 'package:flutter_test/flutter_test.dart';
import 'package:xkeeper_client/url_utils.dart';

void main() {
  group('normalizeServerUrl', () {
    test('末尾スラッシュを除去する', () {
      expect(normalizeServerUrl('http://100.124.53.50:5000/'),
          'http://100.124.53.50:5000');
    });

    test('スキーム省略時は http:// を補う', () {
      expect(normalizeServerUrl(' 100.124.53.50:5000 '),
          'http://100.124.53.50:5000');
    });

    test('https を保持する', () {
      expect(normalizeServerUrl('https://example.ts.net///'),
          'https://example.ts.net');
    });

    test('未対応スキームは空文字', () {
      expect(normalizeServerUrl('ftp://example.com'), '');
    });

    test('空入力は空文字', () {
      expect(normalizeServerUrl('   '), '');
    });
  });

  group('extractUrls', () {
    test('本文に埋もれた URL を拾う', () {
      expect(
        extractUrls('見てこれ https://x.com/user/status/123?s=20 すごい'),
        ['https://x.com/user/status/123?s=20'],
      );
    });

    test('末尾の句読点をトリムする', () {
      expect(
        extractUrls('https://x.com/a/status/1。'),
        ['https://x.com/a/status/1'],
      );
      expect(
        extractUrls('(https://x.com/a/status/2)'),
        ['https://x.com/a/status/2'],
      );
    });

    test('重複を除去する', () {
      expect(
        extractUrls('https://x.com/a/status/1 https://x.com/a/status/1'),
        ['https://x.com/a/status/1'],
      );
    });
  });

  group('extractSupportedUrls', () {
    test('非対応ドメインを除外する', () {
      expect(extractSupportedUrls('https://example.com/foo'), isEmpty);
    });

    test('X を YouTube より優先する', () {
      expect(
        extractSupportedUrls(
            'https://youtu.be/abcdefghijk then https://x.com/u/status/99'),
        ['https://x.com/u/status/99', 'https://youtu.be/abcdefghijk'],
      );
    });

    test('複数 URL をすべて返す', () {
      final urls = extractSupportedUrls(
        'https://x.com/u/status/1 https://www.pixiv.net/artworks/123 '
        'https://i.imgur.com/abc.png',
      );
      expect(urls, hasLength(3));
      expect(urls.first, 'https://x.com/u/status/1');
    });

    test('サーバー対応ドメインを認識する', () {
      for (final url in [
        'https://x.com/u/status/1',
        'https://twitter.com/u/media',
        'https://www.pixiv.net/en/artworks/42',
        'https://i.imgur.com/a.png',
        'https://www.youtube.com/watch?v=x',
        'https://youtube.com/shorts/abc',
        'https://youtu.be/abc',
        'https://www.tiktok.com/@u/video/123',
        'https://www.nicovideo.jp/watch/sm123',
      ]) {
        expect(isSupportedUrl(url), isTrue, reason: url);
      }
    });
  });
}
