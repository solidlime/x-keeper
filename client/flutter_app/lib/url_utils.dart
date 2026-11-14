/// 共有テキストからの URL 抽出とサーバー URL の正規化。
///
/// パターンはサーバー側 `src/patterns.py` の `API_URL_PATTERN` と同期させること。
/// ShareActivity.kt にも同じ正規表現がある (Kotlin 側は Flutter を起動しないため)。
library;

/// 対応ドメイン。並び順が優先順位 (先頭ほど優先)。
const supportedUrlPatterns = <String>[
  // X (Twitter)
  r'^https?://(?:twitter\.com|x\.com)/[A-Za-z0-9_]+/(?:status/\d+|media)',
  // Pixiv
  r'^https?://(?:www\.)?pixiv\.net/(?:en/)?artworks/\d+',
  // Imgur
  r'^https?://(?:i\.)?imgur\.com/[A-Za-z0-9/_\-\.]+',
  // YouTube
  r'^https?://(?:www\.)?youtube\.com/(?:watch|shorts/[A-Za-z0-9_-]+)',
  r'^https?://youtu\.be/[A-Za-z0-9_-]+',
  // TikTok
  r'^https?://(?:www\.)?tiktok\.com/(?:@[^/\s]+/video/\d+|t/[A-Za-z0-9]+)',
  // ニコニコ動画
  r'^https?://(?:www\.)?nicovideo\.jp/watch/[A-Za-z0-9]+',
];

final List<RegExp> _supportedRes = supportedUrlPatterns.map(RegExp.new).toList();

/// テキスト中の URL 候補 (対応ドメインかは問わない)。
final RegExp _urlRe = RegExp(r'''https?://[^\s<>"'`]+''');

/// URL 末尾に付きがちな句読点・閉じ括弧。
const _trailingJunk = '.,;:!?)]}>,。「」『』（）【】…\'"`';

/// 1 つ以上の対応 URL かどうか。
bool isSupportedUrl(String url) => _supportedRes.any((re) => re.hasMatch(url));

/// テキストから URL をすべて抽出する (重複除去・末尾句読点トリム済み)。
List<String> extractUrls(String text) {
  final out = <String>[];
  for (final m in _urlRe.allMatches(text)) {
    final url = _trimTrailingJunk(m[0]!);
    if (url.length > 'https://'.length && !out.contains(url)) out.add(url);
  }
  return out;
}

/// テキストから対応 URL を優先順位付きで抽出する。
///
/// 例: ツイート URL と YouTube URL が混在していれば X が先頭に来る。
List<String> extractSupportedUrls(String text) {
  final candidates = extractUrls(text).where(isSupportedUrl).toList();
  if (candidates.length <= 1) return candidates;

  final ordered = <String>[];
  for (final re in _supportedRes) {
    for (final url in candidates) {
      if (re.hasMatch(url) && !ordered.contains(url)) ordered.add(url);
    }
  }
  return ordered;
}

/// ユーザー入力のサーバー URL を正規化する。
///
/// - スキーム省略時は `http://` を補う
/// - 末尾スラッシュを除去
/// - http/https 以外やホスト欠落は空文字を返す (呼び出し側でエラー表示)
String normalizeServerUrl(String input) {
  var v = input.trim();
  if (v.isEmpty) return '';
  if (!RegExp(r'^[A-Za-z][A-Za-z0-9+.\-]*://').hasMatch(v)) v = 'http://$v';

  final uri = Uri.tryParse(v);
  if (uri == null || uri.host.isEmpty) return '';
  if (uri.scheme != 'http' && uri.scheme != 'https') return '';
  return v.replaceAll(RegExp(r'/+$'), '');
}

/// 認証トークンを正規化する (空白除去・空なら空文字)。
String normalizeApiToken(String? input) => (input ?? '').trim();

String _trimTrailingJunk(String url) {
  var end = url.length;
  while (end > 0 && _trailingJunk.contains(url[end - 1])) {
    end--;
  }
  return url.substring(0, end);
}
