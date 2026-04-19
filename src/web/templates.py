"""全 HTML テンプレート文字列。"""

# ── HTML テンプレート ──────────────────────────────────────────────────────────

_BASE_STYLE = """
<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>x-keeper</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"
        rel="stylesheet"
        integrity="sha384-QWTKZyjpPEjISv5WaRU9OFeRpok6YctnYmDr5pNlyT2bRjXh0JMhjY6hW+ALEwIH"
        crossorigin="anonymous">
  <style>
    body { background: #f8f9fa; }
    .card { max-width: 680px; margin: 24px auto; border-radius: 12px; }
    .badge-set   { background-color: #198754; }
    .badge-unset { background-color: #dc3545; }
    details { border: 1px solid #dee2e6; border-radius: 6px; margin-bottom: 1rem; }
    summary { padding: .75rem 1rem; cursor: pointer; font-weight: 500; list-style: none; }
    summary::-webkit-details-marker { display: none; }
    summary::before { content: "▶ "; font-size: .75em; }
    details[open] summary::before { content: "▼ "; }
    details .details-body { padding: .75rem 1rem; border-top: 1px solid #dee2e6; }
  </style>
</head>
<body>
<nav class="navbar navbar-expand-sm navbar-dark bg-dark mb-3">
  <div class="container-fluid px-4">
    <span class="navbar-brand fw-bold">x-keeper</span>
    <div class="navbar-nav flex-row gap-3">
      <a class="nav-link" href="/?setup=1">セットアップ</a>
      <a class="nav-link" href="/gallery">ギャラリー</a>
      <a class="nav-link" href="/logs">ログ</a>
      <a class="nav-link" href="/queue">キュー</a>
    </div>
  </div>
</nav>
"""

_INDEX_HTML = (
    _BASE_STYLE
    + """
<div class="card shadow-sm">
  <div class="card-body p-4">
    <h4 class="card-title mb-1">x-keeper セットアップ</h4>
    <p class="text-muted mb-4">各種設定を行います。</p>

    <!-- 現在の設定状態 -->
    <h6 class="fw-bold">現在の設定状態</h6>
    <ul class="list-group mb-4">
      {% for key, val in status.items() %}
      <li class="list-group-item d-flex justify-content-between align-items-center">
        <code>{{ key }}</code>
        {% if val %}
        <span class="badge badge-set rounded-pill">設定済み</span>
        {% else %}
        <span class="badge badge-unset rounded-pill">未設定</span>
        {% endif %}
      </li>
      {% endfor %}
    </ul>

    {% if error %}
    <div class="alert alert-danger py-2 small">{{ error }}</div>
    {% endif %}

    <!-- Cookie ファイル設定 -->
    <h6 class="fw-bold">
      Cookie ファイル設定
      <span class="badge bg-secondary fw-normal ms-1">任意</span>
    </h6>
    <p class="small text-muted mb-3">
      鍵アカウントなど認証が必要なツイートの画像も取得したい場合に設定します。<br>
      ブラウザ拡張機能 <strong>Get cookies.txt LOCALLY</strong> などで
      x.com のクッキーを書き出し、<code>data/</code> フォルダに配置してください。
    </p>

    {% if cookies_saved %}
    <div class="alert alert-success py-2 small">Cookie ファイルのパスを保存しました。</div>
    {% endif %}

    <form method="post" action="/save-cookies">
      <div class="mb-3">
        <label class="form-label fw-semibold">Cookie ファイルのパス</label>
        <input type="text" class="form-control font-monospace"
               name="cookies_file"
               placeholder="./data/x.com_cookies.txt"
               value="{{ prefill.cookies_file }}">
        <div class="form-text">空のまま保存すると設定を削除します。</div>
      </div>
      <button type="submit" class="btn btn-outline-primary">保存する</button>
    </form>

    <hr class="my-4">

    <!-- Pixiv リフレッシュトークン設定 -->
    <h6 class="fw-bold">
      Pixiv リフレッシュトークン
      <span class="badge bg-secondary fw-normal ms-1">任意</span>
    </h6>
    <p class="small text-muted mb-3">
      Pixiv の画像をダウンロードするために必要です。
    </p>

    {% if pixiv_saved %}
    <div class="alert alert-success py-2 small">Pixiv リフレッシュトークンを保存しました。</div>
    {% endif %}
    {% if pixiv_error %}
    <div class="alert alert-danger py-2 small">{{ pixiv_error }}</div>
    {% endif %}

    {% if pixiv_auth_url %}
    <div class="alert alert-info small mb-3">
      <strong>手順:</strong>
      <ol class="mb-2 ps-3 mt-1">
        <li>F12 → <strong>[Network]</strong> タブを開く（まだなら）</li>
        <li>別タブで Pixiv のログインページが開いています。ログインする</li>
        <li>Network タブに <code>callback?state=...</code> という行が表示されたらクリック</li>
        <li>Request URL 内の <code>code=</code> の値をコピーして下に貼り付ける</li>
      </ol>
      <span class="text-muted">コード値だけでも、URL ごとでも OK。コードはログインから <strong>30 秒</strong>で失効します。</span>
    </div>
    <div class="mb-3">
      <a href="{{ pixiv_auth_url }}" target="_blank" class="btn btn-sm btn-outline-secondary">
        ログインページをもう一度開く
      </a>
    </div>
    <form method="post" action="/pixiv-oauth/exchange">
      <div class="input-group">
        <input type="text" class="form-control font-monospace"
               name="code" required autofocus
               placeholder="code の値、または callback?state=...&code=... の URL">
        <button type="submit" class="btn btn-primary">取得して保存</button>
      </div>
    </form>
    <div class="mt-2">
      <a href="/pixiv-oauth/cancel" class="small text-muted">← キャンセル</a>
    </div>
    {% else %}
    <button type="button" class="btn btn-outline-danger mb-3"
            onclick="startPixivOAuth(this)">
      Pixiv でログインしてトークンを取得
    </button>
    <script>
    async function startPixivOAuth(btn) {
      btn.disabled = true;
      btn.textContent = '認証 URL を生成中...';
      try {
        const res = await fetch('/pixiv-oauth/start');
        const data = await res.json();
        window.open(data.auth_url, '_blank');
        window.location.href = '/';
      } catch (e) {
        btn.textContent = 'エラーが発生しました。再試行してください。';
        btn.disabled = false;
      }
    }
    </script>

    <details class="mt-2">
      <summary class="small text-muted">手動でトークンを直接入力する</summary>
      <div class="details-body">
        <form method="post" action="/save-pixiv-token">
          <div class="input-group mt-2">
            <input type="password" class="form-control font-monospace"
                   name="pixiv_token"
                   placeholder="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
                   value="{{ prefill.pixiv_token }}">
            <button type="submit" class="btn btn-outline-secondary">保存する</button>
          </div>
          <div class="form-text">空のまま保存すると設定を削除します。</div>
        </form>
      </div>
    </details>
    {% endif %}

    <hr class="my-4">

    <!-- キュー設定 -->
    <h6 class="fw-bold">
      キュー設定
      <span class="badge bg-secondary fw-normal ms-1">任意</span>
    </h6>
    <p class="small text-muted mb-3">
      ポーリング間隔とギャラリー表示を調整します。変更はサーバーの再起動後に反映されます。
    </p>

    {% if bot_config_saved %}
    <div class="alert alert-success py-2 small">設定を保存しました。</div>
    {% endif %}

    <form method="post" action="/save-bot-config">
      <div class="mb-3">
        <label class="form-label fw-semibold">API キューポーリング間隔 (秒)</label>
        <input type="number" class="form-control" name="retry_poll_interval"
               min="5" max="300" value="{{ prefill.retry_poll_interval }}">
        <div class="form-text">
          Chrome 拡張・Android アプリから投入された URL をサーバーが処理する間隔。<br>
          推奨: <code>30</code>（デフォルト）
        </div>
      </div>
      <div class="mb-3">
        <label class="form-label fw-semibold">ギャラリー初期表示サムネイル数</label>
        <input type="number" class="form-control" name="gallery_thumb_count"
               min="1" max="500" value="{{ prefill.gallery_thumb_count }}">
        <div class="form-text">
          ギャラリートップページで先読みするサムネイルの件数。<br>
          推奨: <code>50</code>（デフォルト）
        </div>
      </div>
      <button type="submit" class="btn btn-outline-primary">保存する</button>
    </form>

    <hr class="my-4">
    <h6 class="fw-bold">パッケージ更新</h6>
    <p class="small text-muted mb-3">gallery-dl を最新バージョンに更新します。</p>
    <button type="button" class="btn btn-outline-secondary" onclick="updatePackages(this)">
      gallery-dl を更新する
    </button>
    <div id="update-result" class="mt-2 small"></div>
    <script>
    async function updatePackages(btn) {
      btn.disabled = true;
      btn.textContent = '更新中...';
      document.getElementById('update-result').textContent = '';
      try {
        const res = await fetch('/api/update', {method: 'POST'});
        const data = await res.json();
        if (data.already_up_to_date) {
          document.getElementById('update-result').innerHTML = '<span class="text-success">最新バージョンです</span>';
        } else if (data.version) {
          document.getElementById('update-result').innerHTML = `<span class="text-success">gallery-dl ${data.version} に更新しました</span>`;
        } else if (!data.ok) {
          document.getElementById('update-result').innerHTML = `<span class="text-danger">エラー: ${data.error || data.output}</span>`;
        } else {
          document.getElementById('update-result').innerHTML = '<span class="text-success">更新完了</span>';
        }
      } catch (e) {
        document.getElementById('update-result').innerHTML = `<span class="text-danger">通信エラー: ${e}</span>`;
      } finally {
        btn.textContent = 'gallery-dl を更新する';
        btn.disabled = false;
      }
    }
    </script>
  </div>
</div>
</body></html>
"""
)

_GALLERY_INDEX_HTML = (
    _BASE_STYLE
    + """
{% macro thumb_item(f) %}
<div class="col media-item" data-name="{{ f.name }}">
  <button class="del-btn" data-path="{{ f.path }}" title="削除">🗑</button>
  {% if f.type == "image" %}
  <img src="/thumb/{{ f.path }}" loading="lazy" class="rounded media-thumb"
       style="width:100%;aspect-ratio:1/1;object-fit:cover"
       data-src="/media/{{ f.path }}" data-type="image" data-caption="{{ f.name }}"
       data-path="{{ f.path }}" alt="{{ f.name }}">
  {% elif f.type == "video" %}
  <div class="position-relative media-thumb"
       data-src="/media/{{ f.path }}" data-type="video" data-caption="{{ f.name }}"
       data-path="{{ f.path }}"
       style="aspect-ratio:16/9;background:#000;border-radius:.375rem;overflow:hidden">
    <video muted preload="metadata"
           style="width:100%;height:100%;object-fit:cover;pointer-events:none">
      <source src="/media/{{ f.path }}">
    </video>
    <div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center">
      <span style="font-size:2.5rem;opacity:.8">▶</span>
    </div>
  </div>
  {% elif f.type == "audio" %}
  <div class="p-2 bg-white rounded border">
    <div class="small text-muted text-truncate mb-1" title="{{ f.name }}">{{ f.name }}</div>
    <audio controls style="width:100%"><source src="/media/{{ f.path }}"></audio>
  </div>
  {% else %}
  <div class="p-2 bg-white rounded border">
    <a href="/media/{{ f.path }}" target="_blank"
       class="small text-truncate d-block" title="{{ f.name }}">{{ f.name }}</a>
  </div>
  {% endif %}
</div>
{% endmacro %}
<style>
  .media-thumb { cursor:pointer; transition: opacity .15s; }
  .media-thumb:hover { opacity:.8; }
  .col.media-item { position:relative; }
  .del-btn {
    position:absolute; top:.3rem; right:.3rem; z-index:20;
    background:rgba(220,53,69,.85); color:#fff; border:none;
    border-radius:50%; width:1.7rem; height:1.7rem;
    font-size:.85rem; cursor:pointer; opacity:0;
    transition: opacity .15s; display:flex; align-items:center; justify-content:center;
    line-height:1;
  }
  .col.media-item:hover .del-btn { opacity:1; }
  .col.media-item.deleting { opacity:0; transform:scale(.88); transition: opacity .25s, transform .25s; }
  /* アコーディオン上書き */
  #accordion-list .date-accordion { margin-bottom:0; border-radius:8px; overflow:hidden; }
  .date-accordion > summary {
    background:#f1f3f5; display:flex;
    justify-content:space-between; align-items:center;
  }
  .date-accordion .date-body { padding:.75rem; }
  /* 複数選択 */
  .media-item.selected .media-thumb { outline:3px solid #1d9bf0; outline-offset:-3px; border-radius:.375rem; }
  .media-item.sel-hover  { background:rgba(29,155,240,.06); border-radius:.375rem; }
  #select-toolbar {
    display:none; position:sticky; top:0; z-index:200;
    background:#1e3a5f; border:1px solid #1d9bf0; border-radius:8px;
    padding:8px 16px; margin-bottom:12px; gap:12px; align-items:center;
  }
  #select-toolbar.active { display:flex; }
  #select-rect {
    position:fixed; pointer-events:none; z-index:499;
    border:2px solid #1d9bf0; background:rgba(29,155,240,.12); display:none;
  }
  /* ライトボックス取得元リンク */
  #lb-source { margin-top:4px; min-height:18px; }
  /* ライトボックス */
  #lb-backdrop {
    display:none; position:fixed; inset:0; background:rgba(0,0,0,.88);
    z-index:1050; align-items:center; justify-content:center; flex-direction:column;
  }
  #lb-backdrop.active { display:flex; }
  #lb-content { display:flex; align-items:center; justify-content:center; }
  #lb-caption { color:#ccc; font-size:.8rem; margin-top:.5rem; max-width:92vw;
                overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  #lb-close  { position:fixed; top:1rem; right:1.25rem; font-size:2rem;
               color:#fff; cursor:pointer; line-height:1; z-index:1060; }
  #lb-delete { position:fixed; top:1rem; right:3.25rem; font-size:1.5rem;
               color:#f88; cursor:pointer; line-height:1; z-index:1060; }
  #lb-prev, #lb-next {
    position:fixed; top:50%; transform:translateY(-50%);
    font-size:2.5rem; color:#fff; cursor:pointer; z-index:1060;
    padding:.25rem .75rem; user-select:none;
  }
  #lb-prev { left:.5rem; }
  #lb-next { right:.5rem; }
  #lb-hint { position:fixed; bottom:1rem; left:50%; transform:translateX(-50%);
             color:#aaa; font-size:.75rem; pointer-events:none; z-index:1060; }
  /* カレンダー */
  #cal-grid { display:grid; grid-template-columns:repeat(7,1fr); gap:3px; margin-bottom:1rem; }
  .cal-head { text-align:center; font-size:.7rem; font-weight:600;
              color:#666; padding:2px 0; }
  .cal-day {
    text-align:center; font-size:.78rem; padding:4px 2px;
    border-radius:6px; cursor:default; min-height:42px;
    display:flex; flex-direction:column; align-items:center; justify-content:center; gap:1px;
  }
  .cal-day.has-media { cursor:pointer; background:#e8f4fd; }
  .cal-day.has-media:hover { background:#bde3fa; }
  .cal-day.today { font-weight:700; color:#1d9bf0; }
  .cal-badge { font-size:.65rem; background:#1d9bf0; color:#fff;
               border-radius:10px; padding:0 5px; line-height:1.5; }
  #search-results-wrap { display:none; }
  #search-results-wrap.active { display:block; }
</style>

<!-- 複数選択ツールバー (Ctrl+クリックまたはドラッグ選択時に表示) -->
<div id="select-toolbar">
  <span id="select-count" style="color:#90cdf4;font-weight:600"></span>
  <button id="btn-delete-selected" class="btn btn-sm btn-danger">まとめて削除</button>
  <button id="btn-clear-selection" class="btn btn-sm btn-outline-secondary ms-auto">選択解除</button>
</div>
<!-- ドラッグ選択矩形 -->
<div id="select-rect"></div>

<div class="container" style="max-width:1200px">
  <!-- 月ナビ + 並び替え -->
  <div class="d-flex align-items-center gap-3 mb-3 flex-wrap">
    <button id="btn-prev" class="btn btn-sm btn-outline-secondary"
            data-year="{{ prev_year }}" data-month="{{ prev_month }}">‹</button>
    <h5 class="mb-0" id="month-label">{{ year }}年{{ month }}月</h5>
    <button id="btn-next" class="btn btn-sm btn-outline-secondary"
            data-year="{{ next_year }}" data-month="{{ next_month }}">›</button>
    <button id="btn-today" class="btn btn-sm btn-outline-primary ms-1"
            data-year="{{ now_year }}" data-month="{{ now_month }}">今月</button>
    <span class="text-muted small" id="date-count">{{ dates|length }} 日分</span>
    <div class="ms-auto btn-group btn-group-sm" role="group" aria-label="並び順">
      <button id="btn-sort-new" class="btn {{ 'btn-primary' if sort == 'new' else 'btn-outline-secondary' }}"
              data-sort="new">新 → 古</button>
      <button id="btn-sort-old" class="btn {{ 'btn-primary' if sort == 'old' else 'btn-outline-secondary' }}"
              data-sort="old">古 → 新</button>
    </div>
  </div>

  <!-- カレンダーグリッド -->
  <div id="cal-grid" class="mb-3">
    <div class="cal-head">日</div><div class="cal-head">月</div>
    <div class="cal-head">火</div><div class="cal-head">水</div>
    <div class="cal-head">木</div><div class="cal-head">金</div>
    <div class="cal-head">土</div>
  </div>

  <!-- AJAX検索 -->
  <form id="search-form" class="d-flex gap-2 mb-3">
    <input id="search-q" type="text" name="q" class="form-control form-control-sm"
           placeholder="ファイル名で全日付を横断検索">
    <button type="submit" class="btn btn-sm btn-primary text-nowrap">検索</button>
    <button type="button" id="btn-search-clear" class="btn btn-sm btn-outline-secondary text-nowrap" style="display:none">✕ クリア</button>
  </form>

  <!-- 検索結果 (インプレース) -->
  <div id="search-results-wrap">
    <p class="text-muted small mb-2" id="search-label"></p>
    <div id="search-results"></div>
  </div>

  <!-- 月別アコーディオン -->
  <div id="accordion-wrap">
    {% if not dates %}
    <p class="text-muted">この月のメディアはありません。</p>
    {% else %}
    <div id="accordion-list" class="d-flex flex-column gap-2">
      {% for d in dates %}
      <details {% if d.preloaded %}open{% endif %}
               class="date-accordion" data-date="{{ d.name }}"
               data-loaded="{{ 'true' if d.preloaded else 'false' }}">
        <summary>
          <span class="fw-semibold font-monospace">{{ d.name }}</span>
          <span class="badge bg-secondary rounded-pill">{{ d.count }} ファイル</span>
        </summary>
        <div class="date-body">
          {% if d.preloaded and d.files %}
          <div class="row row-cols-2 row-cols-sm-3 row-cols-md-4 row-cols-lg-5 g-2">
            {% for f in d.files %}{{ thumb_item(f) }}{% endfor %}
          </div>
          {% elif d.preloaded %}
          <p class="text-muted small m-0">ファイルがありません。</p>
          {% else %}
          <div class="lazy-body text-center py-3" data-date="{{ d.name }}" data-sort="{{ sort }}">
            <div class="spinner-border spinner-border-sm text-secondary" role="status">
              <span class="visually-hidden">読み込み中...</span>
            </div>
          </div>
          {% endif %}
        </div>
      </details>
      {% endfor %}
    </div>
    <div id="scroll-sentinel" style="height:1px;margin-top:40px"></div>
    {% endif %}
  </div>
</div>

<!-- ライトボックス -->
<div id="lb-backdrop">
  <span id="lb-close"  title="閉じる (Esc)">✕</span>
  <span id="lb-delete" title="削除 (Del)">🗑</span>
  <span id="lb-prev"   title="前へ (←)">‹</span>
  <span id="lb-next"   title="次へ (→)">›</span>
  <div id="lb-content"></div>
  <div id="lb-caption"></div>
  <div id="lb-source"></div>
  <div id="lb-hint">ホイール / ピンチ: ズーム　ダブルクリック: リセット　Del: 削除</div>
</div>

<script>
(function () {
  const backdrop = document.getElementById('lb-backdrop');
  const content  = document.getElementById('lb-content');
  const caption  = document.getElementById('lb-caption');
  const lbSource = document.getElementById('lb-source');
  let cur = 0;

  // ── ズーム状態 ────────────────────────────────────────────────────────────
  let scale = 1, tx = 0, ty = 0;
  let dragging = false, didDrag = false;
  let drag0 = { x: 0, y: 0, tx: 0, ty: 0 };
  let pinch0 = { dist: 0, scale: 0 };
  let closeCancelled = false;

  function mediaEl() { return content.querySelector('img, video'); }

  function applyTransform() {
    const el = mediaEl();
    if (!el) return;
    el.style.transform = `translate(${tx}px,${ty}px) scale(${scale})`;
    if (el.tagName === 'IMG')
      el.style.cursor = scale > 1 ? (dragging ? 'grabbing' : 'grab') : '';
  }

  function resetZoom() {
    scale = 1; tx = 0; ty = 0;
    const el = mediaEl();
    if (el) { el.style.transform = ''; el.style.cursor = ''; }
  }

  // ── サムネイル一覧 (動的取得) ──────────────────────────────────────────────
  function visibleThumbs() {
    return Array.from(document.querySelectorAll('.media-thumb'))
      .filter(el => el.closest('.media-item').style.display !== 'none');
  }

  // ── ライトボックス開閉 ────────────────────────────────────────────────────

  /** ファイル名から元投稿 URL を推定する。対応しない場合は null を返す。 */
  function sourceUrl(filename) {
    // X/Twitter ファイル名テンプレート: username-tweetid-01.ext
    const mx = (filename || '').match(/-(\\d{10,20})-\\d{2,}\\.\\w+$/);
    if (mx) return `https://x.com/i/web/status/${mx[1]}`;
    // Pixiv ファイル名 (gallery-dl デフォルト): ARTWORKID_p0.ext
    const mp = (filename || '').match(/^(\\d{5,12})(?:_p\\d+)?\\./);
    if (mp) return `https://www.pixiv.net/artworks/${mp[1]}`;
    return null;
  }

  function open(idx) {
    const vt = visibleThumbs();
    if (!vt.length) return;
    cur = ((idx % vt.length) + vt.length) % vt.length;
    const el = vt[cur];
    caption.textContent = el.dataset.caption || '';
    const url = sourceUrl(el.dataset.caption);
    lbSource.innerHTML = url
      ? `<a href="${url}" target="_blank" rel="noopener"
             style="color:#60a5fa;font-size:.75rem;text-decoration:none">🔗 元ポストを開く</a>`
      : '';
    content.innerHTML = '';
    scale = 1; tx = 0; ty = 0;
    if (el.dataset.type === 'image') {
      const img = document.createElement('img');
      img.src = el.dataset.src;
      img.style.cssText = 'max-width:92vw;max-height:84vh;object-fit:contain;border-radius:4px;display:block;transform-origin:center';
      content.appendChild(img);
    } else {
      const v = document.createElement('video');
      v.controls = true; v.autoplay = true;
      v.style.cssText = 'max-width:92vw;max-height:84vh;border-radius:4px;display:block';
      const s = document.createElement('source');
      s.src = el.dataset.src; v.appendChild(s);
      content.appendChild(v);
    }
    backdrop.classList.add('active');
    document.body.style.overflow = 'hidden';
  }

  function close() {
    content.innerHTML = '';
    backdrop.classList.remove('active');
    document.body.style.overflow = '';
    scale = 1; tx = 0; ty = 0;
  }

  function move(delta) {
    const vt = visibleThumbs();
    if (!vt.length) return;
    open(cur + delta);
  }

  // ── 削除 ──────────────────────────────────────────────────────────────────
  async function deleteOne(path) {
    const res = await fetch('/delete-media', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: 'path=' + encodeURIComponent(path),
    });
    return res.ok;
  }

  async function deleteFile(path, onSuccess) {
    const name = path.split('/').pop();
    if (!confirm(`「${name}」を削除しますか？\nこの操作は取り消せません。`)) return;
    try {
      if (!await deleteOne(path)) { alert('削除に失敗しました'); return; }
      onSuccess();
    } catch (e) {
      alert('削除に失敗しました: ' + e);
    }
  }

  // ── 複数選択 ──────────────────────────────────────────────────────────────
  const selectedPaths = new Set();

  function updateToolbar() {
    const toolbar   = document.getElementById('select-toolbar');
    const countEl   = document.getElementById('select-count');
    if (!toolbar || !countEl) return;
    if (selectedPaths.size > 0) {
      toolbar.classList.add('active');
      countEl.textContent = `${selectedPaths.size} 件選択中`;
    } else {
      toolbar.classList.remove('active');
    }
  }

  function toggleSelect(item) {
    const thumb = item.querySelector('.media-thumb');
    if (!thumb) return;
    if (item.classList.contains('selected')) {
      item.classList.remove('selected');
      selectedPaths.delete(thumb.dataset.path);
    } else {
      item.classList.add('selected');
      selectedPaths.add(thumb.dataset.path);
    }
    updateToolbar();
  }

  function clearSelection() {
    document.querySelectorAll('.media-item.selected').forEach(el => el.classList.remove('selected'));
    selectedPaths.clear();
    updateToolbar();
  }

  document.getElementById('btn-delete-selected')?.addEventListener('click', async () => {
    const paths = [...selectedPaths];
    if (!paths.length) return;
    if (!confirm(`${paths.length} 件をまとめて削除しますか？\nこの操作は取り消せません。`)) return;
    for (const path of paths) {
      try {
        if (!await deleteOne(path)) continue;
        const item = document.querySelector(`.media-thumb[data-path="${CSS.escape(path)}"]`)
                     ?.closest('.media-item');
        if (item) { item.classList.add('deleting'); setTimeout(() => item.remove(), 280); }
      } catch { /* ネットワークエラーはスキップ */ }
    }
    clearSelection();
  });

  document.getElementById('btn-clear-selection')?.addEventListener('click', clearSelection);

  // ── ドラッグ選択 ──────────────────────────────────────────────────────────
  const selectRectEl = document.getElementById('select-rect');
  let dragSel = { triggered: false, x0: 0, y0: 0 };

  document.addEventListener('mousedown', e => {
    if (backdrop.classList.contains('active')) return;
    if (e.ctrlKey || e.metaKey) return;
    if (e.target.closest('.del-btn, #select-toolbar, #lb-backdrop')) return;
    if (!e.target.closest('#accordion-list')) return;
    // ブラウザの画像ネイティブドラッグを抑制してカスタム矩形選択のみ動作させる
    e.preventDefault();
    dragSel = { triggered: false, x0: e.clientX, y0: e.clientY };
  });

  document.addEventListener('mousemove', e => {
    if (!dragSel.x0 && !dragSel.y0) return;
    const dx = e.clientX - dragSel.x0, dy = e.clientY - dragSel.y0;
    if (!dragSel.triggered && Math.hypot(dx, dy) > 5) {
      dragSel.triggered = true;
      selectRectEl.style.display = 'block';
    }
    if (!dragSel.triggered) return;
    const x = Math.min(e.clientX, dragSel.x0), y = Math.min(e.clientY, dragSel.y0);
    const w = Math.abs(dx), h = Math.abs(dy);
    Object.assign(selectRectEl.style, {
      left: x + 'px', top: y + 'px', width: w + 'px', height: h + 'px',
    });
    const rect = { left: x, top: y, right: x + w, bottom: y + h };
    document.querySelectorAll('.media-item').forEach(item => {
      const r = item.getBoundingClientRect();
      const inside = r.left < rect.right && r.right > rect.left
                  && r.top  < rect.bottom && r.bottom > rect.top;
      item.classList.toggle('sel-hover', inside);
    });
  });

  document.addEventListener('mouseup', e => {
    if (!dragSel.triggered) { dragSel = { triggered: false, x0: 0, y0: 0 }; return; }
    selectRectEl.style.display = 'none';
    document.querySelectorAll('.media-item.sel-hover').forEach(item => {
      item.classList.remove('sel-hover');
      toggleSelect(item);
    });
    dragSel = { triggered: false, x0: 0, y0: 0 };
  });

  // ── イベント委譲 (動的コンテンツ対応) ────────────────────────────────────
  document.addEventListener('click', e => {
    // 削除ボタンを先にチェック
    const btn = e.target.closest('.del-btn');
    if (btn) {
      e.stopPropagation();
      const item = btn.closest('.media-item');
      deleteFile(btn.dataset.path, () => {
        item.classList.add('deleting');
        setTimeout(() => item.remove(), 280);
      });
      return;
    }
    // Ctrl+クリック: 選択トグル (ライトボックスは開かない)
    if (e.ctrlKey || e.metaKey) {
      const item = e.target.closest('.media-item');
      if (item) { e.preventDefault(); toggleSelect(item); }
      return;
    }
    // ドラッグ後はクリックを無視する
    if (dragSel.triggered) return;
    // サムネイルクリック → ライトボックス
    const thumb = e.target.closest('.media-thumb');
    if (thumb) {
      const vt = visibleThumbs();
      open(vt.indexOf(thumb));
    }
  });

  document.getElementById('lb-close').addEventListener('click', close);
  document.getElementById('lb-prev').addEventListener('click', () => move(-1));
  document.getElementById('lb-next').addEventListener('click', () => move(1));

  // ライトボックス削除
  document.getElementById('lb-delete').addEventListener('click', () => {
    const vt = visibleThumbs();
    if (!vt.length) return;
    const el = vt[cur];
    const item = el.closest('.media-item');
    deleteFile(el.dataset.path, () => {
      close();
      item.classList.add('deleting');
      setTimeout(() => item.remove(), 280);
    });
  });

  backdrop.addEventListener('click', e => {
    if (closeCancelled) { closeCancelled = false; return; }
    if (e.target === backdrop) close();
  });

  document.addEventListener('keydown', e => {
    if (!backdrop.classList.contains('active')) return;
    if (e.key === 'Escape') close();
    if (e.key === 'ArrowLeft')  move(-1);
    if (e.key === 'ArrowRight') move(1);
    if (e.key === '0') resetZoom();
    if (e.key === 'Delete') document.getElementById('lb-delete').click();
  });

  // ── ホイールズーム ────────────────────────────────────────────────────────
  backdrop.addEventListener('wheel', e => {
    const el = mediaEl();
    if (!el || el.tagName === 'VIDEO') return;
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    scale = Math.max(1, Math.min(10, scale * factor));
    if (scale < 1.01) { scale = 1; tx = 0; ty = 0; }
    applyTransform();
  }, { passive: false });

  // ── ドラッグパン ──────────────────────────────────────────────────────────
  content.addEventListener('mousedown', e => {
    if (scale <= 1 || !mediaEl()) return;
    dragging = true; didDrag = false;
    drag0 = { x: e.clientX, y: e.clientY, tx, ty };
    applyTransform();
    e.preventDefault();
  });

  document.addEventListener('mousemove', e => {
    if (!dragging) return;
    const dx = e.clientX - drag0.x, dy = e.clientY - drag0.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) didDrag = true;
    tx = drag0.tx + dx; ty = drag0.ty + dy;
    applyTransform();
  });

  document.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    if (didDrag) closeCancelled = true;
    applyTransform();
  });

  content.addEventListener('dblclick', e => {
    if (scale === 1) return;
    resetZoom(); e.stopPropagation();
  });

  // ── ピンチズーム ──────────────────────────────────────────────────────────
  backdrop.addEventListener('touchstart', e => {
    if (e.touches.length === 2) {
      pinch0.dist = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY
      );
      pinch0.scale = scale;
      e.preventDefault();
    }
  }, { passive: false });

  backdrop.addEventListener('touchmove', e => {
    if (e.touches.length !== 2) return;
    e.preventDefault();
    const dist = Math.hypot(
      e.touches[0].clientX - e.touches[1].clientX,
      e.touches[0].clientY - e.touches[1].clientY
    );
    scale = Math.max(1, Math.min(10, pinch0.scale * (dist / pinch0.dist)));
    if (scale < 1.01) { scale = 1; tx = 0; ty = 0; }
    applyTransform();
  }, { passive: false });

  // ── アコーディオン: 手動展開時に遅延読み込み ──────────────────────────────
  async function loadDate(accordion) {
    if (accordion.dataset.loaded === 'true') return;
    accordion.dataset.loaded = 'true';
    const body = accordion.querySelector('.lazy-body');
    if (!body) return;
    const date = body.dataset.date;
    const sort = body.dataset.sort || curSort;
    try {
      const res = await fetch(`/gallery/thumbs/${date}?sort=${sort}`);
      const html = await res.text();
      body.innerHTML = html;
      body.classList.remove('lazy-body');
    } catch {
      body.textContent = '読み込みに失敗しました';
    }
  }

  function setupAccordionListeners() {
    document.querySelectorAll('.date-accordion').forEach(acc => {
      acc.addEventListener('toggle', () => {
        if (acc.open) loadDate(acc);
      });
    });
  }
  setupAccordionListeners();

  // ── 無限スクロール (IntersectionObserver) ────────────────────────────────
  let scrollObserver = null;
  function setupInfiniteScroll() {
    if (scrollObserver) scrollObserver.disconnect();
    const sentinel = document.getElementById('scroll-sentinel');
    if (!sentinel) return;
    scrollObserver = new IntersectionObserver(entries => {
      if (!entries[0].isIntersecting) return;
      const next = document.querySelector('.date-accordion[data-loaded="false"]');
      if (!next) { scrollObserver.disconnect(); return; }
      next.open = true;
      loadDate(next);
    }, { rootMargin: '200px' });
    scrollObserver.observe(sentinel);
  }
  setupInfiniteScroll();

  // ── カレンダー描画 ────────────────────────────────────────────────────────
  async function buildCalendar(year, month) {
    const grid = document.getElementById('cal-grid');
    if (!grid) return;
    // 既存の曜日ヘッダ以外を削除
    Array.from(grid.children).forEach((el, i) => { if (i >= 7) el.remove(); });
    let counts = {};
    try {
      const res = await fetch(`/api/gallery/calendar?year=${year}&month=${month}`);
      counts = await res.json();
    } catch {}
    const today = new Date();
    const firstDay = new Date(year, month - 1, 1).getDay(); // 0=日
    const daysInMonth = new Date(year, month, 0).getDate();
    // 空白セル
    for (let i = 0; i < firstDay; i++) {
      const el = document.createElement('div'); el.className = 'cal-day';
      grid.appendChild(el);
    }
    for (let d = 1; d <= daysInMonth; d++) {
      const dateStr = `${String(year).padStart(4,'0')}-${String(month).padStart(2,'0')}-${String(d).padStart(2,'0')}`;
      const count = counts[dateStr];
      const el = document.createElement('div');
      el.className = 'cal-day' + (count ? ' has-media' : '');
      if (today.getFullYear() === year && today.getMonth() + 1 === month && today.getDate() === d)
        el.classList.add('today');
      el.innerHTML = `<span>${d}</span>` + (count ? `<span class="cal-badge">${count}</span>` : '');
      if (count) {
        el.title = `${dateStr}: ${count} ファイル`;
        el.addEventListener('click', () => {
          const acc = document.querySelector(`.date-accordion[data-date="${dateStr}"]`);
          if (!acc) return;
          acc.open = true;
          loadDate(acc);
          acc.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
      }
      grid.appendChild(el);
    }
  }

  // 現在の年月・ソートを JS 変数として保持
  let curYear  = {{ year }};
  let curMonth = {{ month }};
  let curSort  = '{{ sort }}';

  // 初期カレンダー描画
  buildCalendar(curYear, curMonth);

  // ── 月切り替え + ソート: AJAX で更新 ─────────────────────────────────────
  function updateSortButtons(sort) {
    document.getElementById('btn-sort-new').className =
      'btn btn-sm ' + (sort === 'new' ? 'btn-primary' : 'btn-outline-secondary');
    document.getElementById('btn-sort-old').className =
      'btn btn-sm ' + (sort === 'old' ? 'btn-primary' : 'btn-outline-secondary');
  }

  function updateNavButtons(year, month) {
    const prevM = month === 1 ? {y: year-1, m: 12} : {y: year, m: month-1};
    const nextM = month === 12 ? {y: year+1, m: 1} : {y: year, m: month+1};
    const btnPrev = document.getElementById('btn-prev');
    const btnNext = document.getElementById('btn-next');
    if (btnPrev) { btnPrev.dataset.year = prevM.y; btnPrev.dataset.month = prevM.m; }
    if (btnNext) { btnNext.dataset.year = nextM.y; btnNext.dataset.month = nextM.m; }
  }

  async function switchMonth(year, month, sort, pushState = true) {
    const accordionWrap = document.getElementById('accordion-wrap');
    if (accordionWrap) accordionWrap.innerHTML = '<div class="text-center py-4"><div class="spinner-border text-secondary" role="status"></div></div>';
    try {
      const res = await fetch(`/gallery/fragment?year=${year}&month=${month}&sort=${sort}`);
      const data = await res.json();
      if (accordionWrap) accordionWrap.innerHTML = data.accordion_html;
      // ラベル更新
      const label = document.getElementById('month-label');
      if (label) label.textContent = `${year}年${month}月`;
      const count = document.getElementById('date-count');
      if (count) count.textContent = `${data.count} 日分`;
      // ナビボタンのdata属性更新
      updateNavButtons(year, month);
      updateSortButtons(sort);
      // カレンダー再描画
      buildCalendar(year, month);
      // アコーディオン遅延読み込みイベント再登録
      document.querySelectorAll('.date-accordion').forEach(acc => {
        acc.addEventListener('toggle', () => { if (acc.open) loadDate(acc); });
      });
      // 無限スクロール再設定
      setupInfiniteScroll();
      curYear = year; curMonth = month; curSort = sort;
      if (pushState) {
        const url = `/gallery?year=${year}&month=${month}&sort=${sort}`;
        history.pushState({ year, month, sort }, '', url);
      }
    } catch (e) {
      if (accordionWrap) accordionWrap.innerHTML = '<p class="text-danger">読み込みに失敗しました: ' + e + '</p>';
    }
  }

  // 月ナビボタン
  document.getElementById('btn-prev')?.addEventListener('click', e => {
    const btn = e.currentTarget;
    switchMonth(+btn.dataset.year, +btn.dataset.month, curSort);
  });
  document.getElementById('btn-next')?.addEventListener('click', e => {
    const btn = e.currentTarget;
    switchMonth(+btn.dataset.year, +btn.dataset.month, curSort);
  });
  document.getElementById('btn-today')?.addEventListener('click', e => {
    const btn = e.currentTarget;
    switchMonth(+btn.dataset.year, +btn.dataset.month, curSort);
  });

  // ソートボタン
  document.getElementById('btn-sort-new')?.addEventListener('click', () => switchMonth(curYear, curMonth, 'new'));
  document.getElementById('btn-sort-old')?.addEventListener('click', () => switchMonth(curYear, curMonth, 'old'));

  // ブラウザ戻る/進む
  window.addEventListener('popstate', e => {
    if (!e.state) return;
    switchMonth(e.state.year, e.state.month, e.state.sort, false);
  });

  // ── AJAX 検索 ─────────────────────────────────────────────────────────────
  const searchForm   = document.getElementById('search-form');
  const searchQ      = document.getElementById('search-q');
  const resultsWrap  = document.getElementById('search-results-wrap');
  const resultsEl    = document.getElementById('search-results');
  const searchLabel  = document.getElementById('search-label');
  const clearBtn     = document.getElementById('btn-search-clear');
  const accordionWrap = document.getElementById('accordion-wrap');

  function showResults(html, q) {
    resultsEl.innerHTML = html;
    searchLabel.textContent = `🔍 "${q}" の検索結果`;
    resultsWrap.classList.add('active');
    if (accordionWrap) accordionWrap.style.display = 'none';
    clearBtn.style.display = '';
  }

  function clearSearch() {
    resultsWrap.classList.remove('active');
    resultsEl.innerHTML = '';
    searchLabel.textContent = '';
    if (accordionWrap) accordionWrap.style.display = '';
    clearBtn.style.display = 'none';
    searchQ.value = '';
  }

  searchForm.addEventListener('submit', async e => {
    e.preventDefault();
    const q = searchQ.value.trim();
    if (!q) { clearSearch(); return; }
    try {
      const res = await fetch(`/gallery/search?q=${encodeURIComponent(q)}&fragment=1`);
      const html = await res.text();
      showResults(html, q);
    } catch (err) {
      resultsEl.textContent = '検索に失敗しました: ' + err;
      resultsWrap.classList.add('active');
    }
  });

  clearBtn.addEventListener('click', clearSearch);

})();
</script>
</body></html>
"""
)

_THUMBS_FRAGMENT_HTML = """
{% if not files %}
<p class="text-muted small m-0">ファイルがありません。</p>
{% else %}
<div class="row row-cols-2 row-cols-sm-3 row-cols-md-4 row-cols-lg-5 g-2">
  {% for f in files %}
  <div class="col media-item" data-name="{{ f.name }}">
    <button class="del-btn" data-path="{{ f.path }}" title="削除">🗑</button>
    {% if f.type == "image" %}
    <img src="/thumb/{{ f.path }}" loading="lazy" class="rounded media-thumb"
         style="width:100%;aspect-ratio:1/1;object-fit:cover"
         data-src="/media/{{ f.path }}" data-type="image" data-caption="{{ f.name }}"
         data-path="{{ f.path }}" alt="{{ f.name }}">
    {% elif f.type == "video" %}
    <div class="position-relative media-thumb"
         data-src="/media/{{ f.path }}" data-type="video" data-caption="{{ f.name }}"
         data-path="{{ f.path }}"
         style="aspect-ratio:16/9;background:#000;border-radius:.375rem;overflow:hidden">
      <video muted preload="metadata"
             style="width:100%;height:100%;object-fit:cover;pointer-events:none">
        <source src="/media/{{ f.path }}">
      </video>
      <div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center">
        <span style="font-size:2.5rem;opacity:.8">▶</span>
      </div>
    </div>
    {% elif f.type == "audio" %}
    <div class="p-2 bg-white rounded border">
      <div class="small text-muted text-truncate mb-1" title="{{ f.name }}">{{ f.name }}</div>
      <audio controls style="width:100%"><source src="/media/{{ f.path }}"></audio>
    </div>
    {% else %}
    <div class="p-2 bg-white rounded border">
      <a href="/media/{{ f.path }}" target="_blank"
         class="small text-truncate d-block" title="{{ f.name }}">{{ f.name }}</a>
    </div>
    {% endif %}
  </div>
  {% endfor %}
</div>
{% endif %}
"""

_ACCORDION_FRAGMENT_HTML = """
{% if not dates %}
<p class="text-muted">この月のメディアはありません。</p>
{% else %}
<div id="accordion-list" class="d-flex flex-column gap-2">
  {% for d in dates %}
  <details {% if d.preloaded %}open{% endif %}
           class="date-accordion" data-date="{{ d.name }}"
           data-loaded="{{ 'true' if d.preloaded else 'false' }}">
    <summary>
      <span class="fw-semibold font-monospace">{{ d.name }}</span>
      <span class="badge bg-secondary rounded-pill">{{ d.count }} ファイル</span>
    </summary>
    <div class="date-body">
      {% if d.preloaded and d.files %}
      <div class="row row-cols-2 row-cols-sm-3 row-cols-md-4 row-cols-lg-5 g-2">
        {% for f in d.files %}
        <div class="col media-item" data-name="{{ f.name }}">
          <button class="del-btn" data-path="{{ f.path }}" title="削除">🗑</button>
          {% if f.type == "image" %}
          <img src="/thumb/{{ f.path }}" loading="lazy" class="rounded media-thumb"
               style="width:100%;aspect-ratio:1/1;object-fit:cover"
               data-src="/media/{{ f.path }}" data-type="image" data-caption="{{ f.name }}"
               data-path="{{ f.path }}" alt="{{ f.name }}">
          {% elif f.type == "video" %}
          <div class="position-relative media-thumb"
               data-src="/media/{{ f.path }}" data-type="video" data-caption="{{ f.name }}"
               data-path="{{ f.path }}"
               style="aspect-ratio:16/9;background:#000;border-radius:.375rem;overflow:hidden">
            <video muted preload="metadata"
                   style="width:100%;height:100%;object-fit:cover;pointer-events:none">
              <source src="/media/{{ f.path }}">
            </video>
            <div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center">
              <span style="font-size:2.5rem;opacity:.8">▶</span>
            </div>
          </div>
          {% elif f.type == "audio" %}
          <div class="p-2 bg-white rounded border">
            <div class="small text-muted text-truncate mb-1" title="{{ f.name }}">{{ f.name }}</div>
            <audio controls style="width:100%"><source src="/media/{{ f.path }}"></audio>
          </div>
          {% else %}
          <div class="p-2 bg-white rounded border">
            <a href="/media/{{ f.path }}" target="_blank"
               class="small text-truncate d-block" title="{{ f.name }}">{{ f.name }}</a>
          </div>
          {% endif %}
        </div>
        {% endfor %}
      </div>
      {% elif d.preloaded %}
      <p class="text-muted small m-0">ファイルがありません。</p>
      {% else %}
      <div class="lazy-body text-center py-3" data-date="{{ d.name }}" data-sort="{{ sort }}">
        <div class="spinner-border spinner-border-sm text-secondary" role="status">
          <span class="visually-hidden">読み込み中...</span>
        </div>
      </div>
      {% endif %}
    </div>
  </details>
  {% endfor %}
</div>
<div id="scroll-sentinel" style="height:1px;margin-top:40px"></div>
{% endif %}
"""

_GALLERY_DATE_HTML = (
    _BASE_STYLE
    + """
<style>
  .media-thumb { cursor:pointer; transition: opacity .15s; }
  .media-thumb:hover { opacity:.8; }
  /* 削除ボタン */
  .col.media-item { position:relative; }
  .del-btn {
    position:absolute; top:.3rem; right:.3rem; z-index:20;
    background:rgba(220,53,69,.85); color:#fff; border:none;
    border-radius:50%; width:1.7rem; height:1.7rem;
    font-size:.85rem; cursor:pointer; opacity:0;
    transition: opacity .15s; display:flex; align-items:center; justify-content:center;
    line-height:1;
  }
  .col.media-item:hover .del-btn { opacity:1; }
  .col.media-item.deleting { opacity:0; transform:scale(.88); transition: opacity .25s, transform .25s; }
  /* 複数選択 */
  .media-item.selected .media-thumb { outline:3px solid #1d9bf0; outline-offset:-3px; border-radius:.375rem; }
  .media-item.sel-hover  { background:rgba(29,155,240,.06); border-radius:.375rem; }
  #select-toolbar {
    display:none; position:sticky; top:0; z-index:200;
    background:#1e3a5f; border:1px solid #1d9bf0; border-radius:8px;
    padding:8px 16px; margin-bottom:12px; gap:12px; align-items:center;
  }
  #select-toolbar.active { display:flex; }
  #select-rect {
    position:fixed; pointer-events:none; z-index:499;
    border:2px solid #1d9bf0; background:rgba(29,155,240,.12); display:none;
  }
  /* ライトボックス取得元リンク */
  #lb-source { margin-top:4px; min-height:18px; }
  /* ライトボックス */
  #lb-backdrop {
    display:none; position:fixed; inset:0; background:rgba(0,0,0,.88);
    z-index:1050; align-items:center; justify-content:center; flex-direction:column;
  }
  #lb-backdrop.active { display:flex; }
  #lb-content { display:flex; align-items:center; justify-content:center; }
  #lb-caption { color:#ccc; font-size:.8rem; margin-top:.5rem; max-width:92vw;
                overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  #lb-close  { position:fixed; top:1rem; right:1.25rem; font-size:2rem;
               color:#fff; cursor:pointer; line-height:1; z-index:1060; }
  #lb-delete { position:fixed; top:1rem; right:3.25rem; font-size:1.5rem;
               color:#f88; cursor:pointer; line-height:1; z-index:1060; }
  #lb-prev, #lb-next {
    position:fixed; top:50%; transform:translateY(-50%);
    font-size:2.5rem; color:#fff; cursor:pointer; z-index:1060;
    padding:.25rem .75rem; user-select:none;
  }
  #lb-prev { left:.5rem; }
  #lb-next { right:.5rem; }
  #lb-hint { position:fixed; bottom:1rem; left:50%; transform:translateX(-50%);
             color:#aaa; font-size:.75rem; pointer-events:none; z-index:1060; }
</style>

<!-- 複数選択ツールバー -->
<div id="select-toolbar">
  <span id="select-count" style="color:#90cdf4;font-weight:600"></span>
  <button id="btn-delete-selected" class="btn btn-sm btn-danger">まとめて削除</button>
  <button id="btn-clear-selection" class="btn btn-sm btn-outline-secondary ms-auto">選択解除</button>
</div>
<!-- ドラッグ選択矩形 -->
<div id="select-rect"></div>

<div class="container" style="max-width:1200px">
  <div class="d-flex align-items-center gap-3 mb-3">
    <a href="/gallery" class="btn btn-sm btn-outline-secondary">← 戻る</a>
    <h5 class="mb-0 font-monospace">{{ date }}</h5>
    <span class="text-muted small">{{ files|length }} ファイル</span>
    <input type="text" id="file-search" class="form-control form-control-sm ms-auto"
           style="max-width:220px" placeholder="ファイル名で絞り込み">
  </div>
  {% if not files %}
  <p class="text-muted">ファイルがありません。</p>
  {% else %}
  <div class="row row-cols-2 row-cols-sm-3 row-cols-md-4 row-cols-lg-5 g-2" id="file-grid">
    {% for f in files %}
    <div class="col media-item" data-name="{{ f.name }}">
      <button class="del-btn" data-path="{{ f.path }}" title="削除">🗑</button>
      {% if f.type == "image" %}
      <img src="/thumb/{{ f.path }}" loading="lazy" class="rounded media-thumb"
           style="width:100%;aspect-ratio:1/1;object-fit:cover"
           data-src="/media/{{ f.path }}" data-type="image" data-caption="{{ f.name }}"
           data-path="{{ f.path }}" alt="{{ f.name }}">
      {% elif f.type == "video" %}
      <div class="position-relative media-thumb"
           data-src="/media/{{ f.path }}" data-type="video" data-caption="{{ f.name }}"
           data-path="{{ f.path }}"
           style="aspect-ratio:16/9;background:#000;border-radius:.375rem;overflow:hidden">
        <video muted preload="metadata"
               style="width:100%;height:100%;object-fit:cover;pointer-events:none">
          <source src="/media/{{ f.path }}">
        </video>
        <div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center">
          <span style="font-size:2.5rem;opacity:.8">▶</span>
        </div>
      </div>
      {% elif f.type == "audio" %}
      <div class="p-2 bg-white rounded border">
        <div class="small text-muted text-truncate mb-1" title="{{ f.name }}">{{ f.name }}</div>
        <audio controls style="width:100%"><source src="/media/{{ f.path }}"></audio>
      </div>
      {% else %}
      <div class="p-2 bg-white rounded border">
        <a href="/media/{{ f.path }}" target="_blank"
           class="small text-truncate d-block" title="{{ f.name }}">{{ f.name }}</a>
      </div>
      {% endif %}
    </div>
    {% endfor %}
  </div>
  {% endif %}
</div>

<!-- ライトボックス -->
<div id="lb-backdrop">
  <span id="lb-close"  title="閉じる (Esc)">✕</span>
  <span id="lb-delete" title="削除 (Del)">🗑</span>
  <span id="lb-prev"   title="前へ (←)">‹</span>
  <span id="lb-next"   title="次へ (→)">›</span>
  <div id="lb-content"></div>
  <div id="lb-caption"></div>
  <div id="lb-source"></div>
  <div id="lb-hint">ホイール / ピンチ: ズーム　ダブルクリック: リセット　Del: 削除</div>
</div>

<script>
(function () {
  const thumbs   = Array.from(document.querySelectorAll('.media-thumb'));
  const backdrop = document.getElementById('lb-backdrop');
  const content  = document.getElementById('lb-content');
  const caption  = document.getElementById('lb-caption');
  const lbSource = document.getElementById('lb-source');
  let cur = 0;

  // ── ズーム状態 ────────────────────────────────────────────────────────────
  let scale = 1, tx = 0, ty = 0;
  let dragging = false, didDrag = false;
  let drag0 = { x: 0, y: 0, tx: 0, ty: 0 };
  let pinch0 = { dist: 0, scale: 0 };
  let closeCancelled = false;

  function mediaEl() { return content.querySelector('img, video'); }

  function applyTransform() {
    const el = mediaEl();
    if (!el) return;
    el.style.transform = `translate(${tx}px,${ty}px) scale(${scale})`;
    if (el.tagName === 'IMG')
      el.style.cursor = scale > 1 ? (dragging ? 'grabbing' : 'grab') : '';
  }

  function resetZoom() {
    scale = 1; tx = 0; ty = 0;
    const el = mediaEl();
    if (el) { el.style.transform = ''; el.style.cursor = ''; }
  }

  // ── ナビゲーション ────────────────────────────────────────────────────────
  function visibleThumbs() {
    return thumbs.filter(el => el.closest('.media-item').style.display !== 'none');
  }

  /** ファイル名から元投稿 URL を推定する。対応しない場合は null を返す。 */
  function sourceUrl(filename) {
    // X/Twitter ファイル名テンプレート: username-tweetid-01.ext
    const mx = (filename || '').match(/-(\\d{10,20})-\\d{2,}\\.\\w+$/);
    if (mx) return `https://x.com/i/web/status/${mx[1]}`;
    // Pixiv ファイル名 (gallery-dl デフォルト): ARTWORKID_p0.ext
    const mp = (filename || '').match(/^(\\d{5,12})(?:_p\\d+)?\\./);
    if (mp) return `https://www.pixiv.net/artworks/${mp[1]}`;
    return null;
  }

  function open(idx) {
    const vt = visibleThumbs();
    if (!vt.length) return;
    cur = ((idx % vt.length) + vt.length) % vt.length;
    const el = vt[cur];
    caption.textContent = el.dataset.caption || '';
    const url = sourceUrl(el.dataset.caption);
    lbSource.innerHTML = url
      ? `<a href="${url}" target="_blank" rel="noopener"
             style="color:#60a5fa;font-size:.75rem;text-decoration:none">🔗 元ポストを開く</a>`
      : '';
    content.innerHTML = '';
    scale = 1; tx = 0; ty = 0;
    if (el.dataset.type === 'image') {
      const img = document.createElement('img');
      img.src = el.dataset.src;
      img.style.cssText = 'max-width:92vw;max-height:84vh;object-fit:contain;border-radius:4px;display:block;transform-origin:center';
      content.appendChild(img);
    } else {
      const v = document.createElement('video');
      v.controls = true; v.autoplay = true;
      v.style.cssText = 'max-width:92vw;max-height:84vh;border-radius:4px;display:block';
      const s = document.createElement('source');
      s.src = el.dataset.src; v.appendChild(s);
      content.appendChild(v);
    }
    backdrop.classList.add('active');
    document.body.style.overflow = 'hidden';
  }

  function close() {
    content.innerHTML = '';
    backdrop.classList.remove('active');
    document.body.style.overflow = '';
    scale = 1; tx = 0; ty = 0;
  }

  function move(delta) { open(cur + delta); }

  // ── 削除 ──────────────────────────────────────────────────────────────────
  async function deleteOne(path) {
    const res = await fetch('/delete-media', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: 'path=' + encodeURIComponent(path),
    });
    return res.ok;
  }

  async function deleteFile(path, onSuccess) {
    const name = path.split('/').pop();
    if (!confirm(`「${name}」を削除しますか？\nこの操作は取り消せません。`)) return;
    try {
      if (!await deleteOne(path)) { alert('削除に失敗しました'); return; }
      onSuccess();
    } catch (e) {
      alert('削除に失敗しました: ' + e);
    }
  }

  // ── 複数選択 ──────────────────────────────────────────────────────────────
  const selectedPaths = new Set();

  function updateToolbar() {
    const toolbar = document.getElementById('select-toolbar');
    const countEl = document.getElementById('select-count');
    if (!toolbar || !countEl) return;
    if (selectedPaths.size > 0) {
      toolbar.classList.add('active');
      countEl.textContent = `${selectedPaths.size} 件選択中`;
    } else {
      toolbar.classList.remove('active');
    }
  }

  function toggleSelect(item) {
    const thumb = item.querySelector('.media-thumb');
    if (!thumb) return;
    if (item.classList.contains('selected')) {
      item.classList.remove('selected');
      selectedPaths.delete(thumb.dataset.path);
    } else {
      item.classList.add('selected');
      selectedPaths.add(thumb.dataset.path);
    }
    updateToolbar();
  }

  function clearSelection() {
    document.querySelectorAll('.media-item.selected').forEach(el => el.classList.remove('selected'));
    selectedPaths.clear();
    updateToolbar();
  }

  document.getElementById('btn-delete-selected')?.addEventListener('click', async () => {
    const paths = [...selectedPaths];
    if (!paths.length) return;
    if (!confirm(`${paths.length} 件をまとめて削除しますか？\nこの操作は取り消せません。`)) return;
    for (const path of paths) {
      try {
        if (!await deleteOne(path)) continue;
        const thumb = thumbs.find(t => t.dataset.path === path);
        if (thumb) {
          const idx = thumbs.indexOf(thumb);
          if (idx !== -1) thumbs.splice(idx, 1);
          const item = thumb.closest('.media-item');
          if (item) { item.classList.add('deleting'); setTimeout(() => item.remove(), 280); }
        }
      } catch { /* ネットワークエラーはスキップ */ }
    }
    clearSelection();
  });

  document.getElementById('btn-clear-selection')?.addEventListener('click', clearSelection);

  // ── ドラッグ選択 ──────────────────────────────────────────────────────────
  const selectRectEl = document.getElementById('select-rect');
  let dragSel = { triggered: false, x0: 0, y0: 0 };

  document.addEventListener('mousedown', e => {
    if (backdrop.classList.contains('active')) return;
    if (e.ctrlKey || e.metaKey) return;
    if (e.target.closest('.del-btn, #select-toolbar, #lb-backdrop')) return;
    if (!e.target.closest('#file-grid')) return;
    // ブラウザの画像ネイティブドラッグを抑制してカスタム矩形選択のみ動作させる
    e.preventDefault();
    dragSel = { triggered: false, x0: e.clientX, y0: e.clientY };
  });

  document.addEventListener('mousemove', e => {
    if (!dragSel.x0 && !dragSel.y0) return;
    const dx = e.clientX - dragSel.x0, dy = e.clientY - dragSel.y0;
    if (!dragSel.triggered && Math.hypot(dx, dy) > 5) {
      dragSel.triggered = true;
      selectRectEl.style.display = 'block';
    }
    if (!dragSel.triggered) return;
    const x = Math.min(e.clientX, dragSel.x0), y = Math.min(e.clientY, dragSel.y0);
    const w = Math.abs(dx), h = Math.abs(dy);
    Object.assign(selectRectEl.style, {
      left: x + 'px', top: y + 'px', width: w + 'px', height: h + 'px',
    });
    const rect = { left: x, top: y, right: x + w, bottom: y + h };
    document.querySelectorAll('.media-item').forEach(item => {
      const r = item.getBoundingClientRect();
      const inside = r.left < rect.right && r.right > rect.left
                  && r.top  < rect.bottom && r.bottom > rect.top;
      item.classList.toggle('sel-hover', inside);
    });
  });

  document.addEventListener('mouseup', () => {
    if (!dragSel.triggered) { dragSel = { triggered: false, x0: 0, y0: 0 }; return; }
    selectRectEl.style.display = 'none';
    document.querySelectorAll('.media-item.sel-hover').forEach(item => {
      item.classList.remove('sel-hover');
      toggleSelect(item);
    });
    dragSel = { triggered: false, x0: 0, y0: 0 };
  });

  // サムネイル削除ボタン
  document.querySelectorAll('.del-btn').forEach(btn => {
    btn.addEventListener('click', e => {
      e.stopPropagation();
      const item = btn.closest('.media-item');
      const thumb = item.querySelector('.media-thumb');
      deleteFile(btn.dataset.path, () => {
        if (thumb) {
          const idx = thumbs.indexOf(thumb);
          if (idx !== -1) thumbs.splice(idx, 1);
        }
        item.classList.add('deleting');
        setTimeout(() => item.remove(), 280);
      });
    });
  });

  thumbs.forEach(el => {
    el.addEventListener('click', e => {
      // Ctrl+クリックは選択トグル
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        toggleSelect(el.closest('.media-item'));
        return;
      }
      // ドラッグ後はクリックを無視する
      if (dragSel.triggered) return;
      open(visibleThumbs().indexOf(el));
    });
  });

  document.getElementById('lb-close').addEventListener('click', close);
  document.getElementById('lb-prev').addEventListener('click', () => move(-1));
  document.getElementById('lb-next').addEventListener('click', () => move(1));

  // ライトボックス削除ボタン
  document.getElementById('lb-delete').addEventListener('click', () => {
    const vt = visibleThumbs();
    if (!vt.length) return;
    const el = vt[cur];
    const path = el.dataset.path;
    const item = el.closest('.media-item');
    deleteFile(path, () => {
      const idx = thumbs.indexOf(el);
      if (idx !== -1) thumbs.splice(idx, 1);
      close();
      item.classList.add('deleting');
      setTimeout(() => item.remove(), 280);
    });
  });

  backdrop.addEventListener('click', e => {
    if (closeCancelled) { closeCancelled = false; return; }
    if (e.target === backdrop) close();
  });

  document.addEventListener('keydown', e => {
    if (!backdrop.classList.contains('active')) return;
    if (e.key === 'Escape') close();
    if (e.key === 'ArrowLeft')  move(-1);
    if (e.key === 'ArrowRight') move(1);
    if (e.key === '0') resetZoom();
    if (e.key === 'Delete') document.getElementById('lb-delete').click();
  });

  // ── ホイールズーム ────────────────────────────────────────────────────────
  backdrop.addEventListener('wheel', e => {
    const el = mediaEl();
    if (!el || el.tagName === 'VIDEO') return;
    e.preventDefault();
    const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    scale = Math.max(1, Math.min(10, scale * factor));
    if (scale < 1.01) { scale = 1; tx = 0; ty = 0; }
    applyTransform();
  }, { passive: false });

  // ── ドラッグパン ──────────────────────────────────────────────────────────
  content.addEventListener('mousedown', e => {
    if (scale <= 1 || !mediaEl()) return;
    dragging = true; didDrag = false;
    drag0 = { x: e.clientX, y: e.clientY, tx, ty };
    applyTransform();
    e.preventDefault();
  });

  document.addEventListener('mousemove', e => {
    if (!dragging) return;
    const dx = e.clientX - drag0.x, dy = e.clientY - drag0.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) didDrag = true;
    tx = drag0.tx + dx; ty = drag0.ty + dy;
    applyTransform();
  });

  document.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    if (didDrag) closeCancelled = true;
    applyTransform();
  });

  // ダブルクリックでズームリセット
  content.addEventListener('dblclick', e => {
    if (scale === 1) return;
    resetZoom(); e.stopPropagation();
  });

  // ── ピンチズーム ──────────────────────────────────────────────────────────
  backdrop.addEventListener('touchstart', e => {
    if (e.touches.length === 2) {
      pinch0.dist = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY
      );
      pinch0.scale = scale;
      e.preventDefault();
    }
  }, { passive: false });

  backdrop.addEventListener('touchmove', e => {
    if (e.touches.length !== 2) return;
    e.preventDefault();
    const dist = Math.hypot(
      e.touches[0].clientX - e.touches[1].clientX,
      e.touches[0].clientY - e.touches[1].clientY
    );
    scale = Math.max(1, Math.min(10, pinch0.scale * (dist / pinch0.dist)));
    if (scale < 1.01) { scale = 1; tx = 0; ty = 0; }
    applyTransform();
  }, { passive: false });

  // ── ファイル名フィルタ ────────────────────────────────────────────────────
  const searchEl = document.getElementById('file-search');
  if (searchEl) {
    searchEl.addEventListener('input', function () {
      const q = this.value.toLowerCase();
      document.querySelectorAll('.media-item').forEach(el => {
        el.style.display = el.dataset.name.toLowerCase().includes(q) ? '' : 'none';
      });
    });
  }
})();
</script>
</body></html>
"""
)

_LOGS_HTML = (
    _BASE_STYLE
    + """
<div class="container" style="max-width:960px">
  <div class="d-flex align-items-center gap-3 mb-3">
    <h5 class="mb-0">処理ログ</h5>
    <span class="text-muted small">最新 100 件</span>
  </div>
  {% if not entries %}
  <p class="text-muted">ログがまだありません。</p>
  {% else %}
  <div class="table-responsive">
    <table class="table table-sm table-hover align-middle">
      <thead class="table-light">
        <tr>
          <th class="text-nowrap">時刻</th>
          <th></th>
          <th>URL</th>
          <th class="text-end">詳細</th>
        </tr>
      </thead>
      <tbody>
        {% for e in entries %}
        <tr class="{{ 'table-success' if e.status == 'success' else 'table-danger' }} bg-opacity-50">
          <td class="text-nowrap small font-monospace">{{ e.ts }}</td>
          <td class="fs-5">{{ '✅' if e.status == 'success' else '❌' }}</td>
          <td class="small">
            {% for url in e.urls %}
            <div class="text-truncate" style="max-width:340px">
              <a href="{{ url }}" target="_blank" rel="noopener" class="text-decoration-none">{{ url }}</a>
            </div>
            {% endfor %}
          </td>
          <td class="small text-end text-nowrap">
            {% if e.status == 'success' %}
            <span class="text-success">{{ e.file_count }} ファイル</span>
            {% else %}
            <span class="text-danger" title="{{ e.error }}">{{ e.error[:60] }}{% if e.error|length > 60 %}…{% endif %}</span>
            {% endif %}
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}
</div>
</body></html>
"""
)

_QUEUE_HTML = (
    _BASE_STYLE
    + """
<div class="container" style="max-width:960px">

  {# ── 処理待ちキュー ─────────────────────────────────────────── #}
  <div class="d-flex align-items-center gap-3 mb-2">
    <h5 class="mb-0">処理待ちキュー</h5>
    <span class="text-muted small">{{ queue_items|length }} 件</span>
    {% if queue_items %}
    <button id="btn-clear-all" class="btn btn-sm btn-outline-danger ms-auto">全件クリア</button>
    {% endif %}
  </div>

  {% if not queue_items %}
  <p class="text-muted mb-4">処理待ちキューは空です。</p>
  {% else %}
  <div class="table-responsive mb-4">
    <table class="table table-sm align-middle" id="queue-table">
      <thead class="table-light">
        <tr>
          <th class="text-nowrap">追加時刻</th>
          <th>URL</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {% for item in queue_items %}
        <tr data-url="{{ item.url }}">
          <td class="text-nowrap small font-monospace">{{ item.queued_at }}</td>
          <td class="small">
            <a href="{{ item.url }}" target="_blank" rel="noopener"
               class="text-decoration-none text-truncate d-block" style="max-width:380px">{{ item.url }}</a>
          </td>
          <td class="text-end">
            <button class="btn btn-sm btn-outline-danger btn-del-item" data-url="{{ item.url }}">削除</button>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}

  {# ── 失敗リスト ─────────────────────────────────────────────── #}
  <div class="d-flex align-items-center gap-3 mb-2">
    <h5 class="mb-0">失敗リスト</h5>
    <span class="text-muted small">{{ failure_entries|length }} 件</span>
  </div>
  {% if not failure_entries %}
  <p class="text-muted">失敗した処理はありません。</p>
  {% else %}
  <div class="table-responsive">
    <table class="table table-sm align-middle">
      <thead class="table-light">
        <tr>
          <th class="text-nowrap">時刻</th>
          <th>URL</th>
          <th>エラー</th>
        </tr>
      </thead>
      <tbody>
        {% for e in failure_entries %}
        <tr>
          <td class="text-nowrap small font-monospace">{{ e.ts }}</td>
          <td class="small">
            {% for url in e.urls %}
            <div class="text-truncate" style="max-width:260px">
              <a href="{{ url }}" target="_blank" rel="noopener" class="text-decoration-none">{{ url }}</a>
            </div>
            {% endfor %}
          </td>
          <td class="small text-danger">
            <span title="{{ e.error }}">{{ e.error[:80] }}{% if e.error|length > 80 %}…{% endif %}</span>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}
</div>

<script>
// ── 処理待ちキュー操作 ────────────────────────────────────────────────
document.querySelectorAll('.btn-del-item').forEach(btn => {
  btn.addEventListener('click', async () => {
    const url = btn.dataset.url;
    btn.disabled = true;
    const res = await fetch('/api/queue/item', {
      method: 'DELETE',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url}),
    });
    if (res.ok) {
      btn.closest('tr').remove();
      const tbody = document.querySelector('#queue-table tbody');
      if (tbody && !tbody.querySelector('tr')) location.reload();
    } else {
      btn.disabled = false;
      alert('削除失敗');
    }
  });
});

const btnClearAll = document.getElementById('btn-clear-all');
if (btnClearAll) {
  btnClearAll.addEventListener('click', async () => {
    if (!confirm('処理待ちキューを全件削除しますか？')) return;
    btnClearAll.disabled = true;
    await fetch('/api/queue/clear', {method: 'POST'});
    location.reload();
  });
}
</script>
</body></html>
"""
)

_FAILURES_HTML = (
    _BASE_STYLE
    + """
<div class="container" style="max-width:960px">
  <div class="d-flex align-items-center gap-3 mb-3">
    <h5 class="mb-0">失敗リスト</h5>
    <span class="text-muted small">{{ entries|length }} 件</span>
  </div>
  {% if not entries %}
  <p class="text-muted">失敗した処理はありません。</p>
  {% else %}
  <div class="table-responsive">
    <table class="table table-sm align-middle">
      <thead class="table-light">
        <tr>
          <th class="text-nowrap">時刻</th>
          <th>URL</th>
          <th>エラー</th>
        </tr>
      </thead>
      <tbody>
        {% for e in entries %}
        <tr>
          <td class="text-nowrap small font-monospace">{{ e.ts }}</td>
          <td class="small">
            {% for url in e.urls %}
            <div class="text-truncate" style="max-width:260px">
              <a href="{{ url }}" target="_blank" rel="noopener" class="text-decoration-none">{{ url }}</a>
            </div>
            {% endfor %}
          </td>
          <td class="small text-danger">
            <span title="{{ e.error }}">{{ e.error[:80] }}{% if e.error|length > 80 %}…{% endif %}</span>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% endif %}
</div>
</body></html>
"""
)
