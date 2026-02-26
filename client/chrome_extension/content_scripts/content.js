/**
 * x-keeper Chrome 拡張 — コンテンツスクリプト
 *
 * X (Twitter) / Pixiv のページに保存ボタンを注入する。
 * HTTP 通信はすべてサービスワーカーに委譲 (chrome.runtime.sendMessage)。
 */

'use strict';

// ── Toast ─────────────────────────────────────────────────────────────────────

function toast(msg, isError) {
  const el = document.createElement('div');
  const bg = isError ? '#ef4444' : '#1d9bf0';
  el.style.cssText = `position:fixed;bottom:20px;left:50%;transform:translateX(-50%);z-index:2147483647;padding:10px 18px;border-radius:8px;background:${bg};color:#fff;font-size:13px;font-weight:600;box-shadow:0 4px 12px rgba(0,0,0,.4);transition:opacity .3s;pointer-events:none;white-space:nowrap;`;
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 300); }, 2500);
}

// ── キュー送信 ────────────────────────────────────────────────────────────────

function queueUrl(url, btn) {
  if (btn) { btn.disabled = true; btn.style.opacity = '0.5'; }

  chrome.runtime.sendMessage({ type: 'QUEUE_URL', url }, (res) => {
    if (!res) {
      // サービスワーカーが応答しない (インストール直後など)
      toast('拡張機能を再読み込みしてください', true);
      if (btn) { btn.disabled = false; btn.style.opacity = '1'; }
      return;
    }
    if (res.ok) {
      toast('x-keeper にキューを追加しました ✓');
      if (btn) { btn.disabled = false; btn.style.opacity = '1'; btn.style.color = '#00ba7c'; }
    } else {
      toast('サーバー未接続。次回接続時に送信します', true);
      if (btn) { btn.disabled = false; btn.style.opacity = '1'; }
    }
  });
}

// ── フローティングボタン ──────────────────────────────────────────────────────

const FAB_ID = 'xkeeper-fab';

function setFloatingBtn(label, color, onClick) {
  document.getElementById(FAB_ID)?.remove();

  const btn = document.createElement('button');
  btn.id = FAB_ID;
  btn.style.cssText = `position:fixed;bottom:80px;right:16px;z-index:2147483646;display:inline-flex;align-items:center;gap:6px;padding:10px 16px;border:none;border-radius:9999px;background:${color};color:#fff;font-size:13px;font-weight:700;cursor:pointer;box-shadow:0 2px 12px rgba(0,0,0,.4);transition:opacity .15s,transform .15s;line-height:1;`;
  btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 16l-5-5 1.4-1.4 2.6 2.6V4h2v8.2l2.6-2.6L17 11l-5 5zm-6 4v-2h12v2H6z"/></svg><span>${label}</span>`;
  btn.addEventListener('mouseenter', () => { btn.style.opacity = '0.85'; btn.style.transform = 'scale(1.04)'; });
  btn.addEventListener('mouseleave', () => { btn.style.opacity = '1'; btn.style.transform = ''; });
  btn.addEventListener('click', (e) => { e.stopPropagation(); onClick(btn); });
  document.body.appendChild(btn);
}

function removeFloatingBtn() {
  document.getElementById(FAB_ID)?.remove();
}

// ── X (Twitter) ──────────────────────────────────────────────────────────────

/** article 内の /username/status/ID 形式リンクから tweet URL を取得する */
function tweetUrlFromArticle(article) {
  for (const a of article.querySelectorAll('a[href]')) {
    const href = a.getAttribute('href') || '';
    if (/^\/\w+\/status\/\d+$/.test(href)) return `https://x.com${href}`;
  }
  return null;
}

/** ツイートに画像または動画が含まれているか */
function hasMedia(article) {
  return !!(
    article.querySelector('[data-testid="tweetPhoto"]') ||
    article.querySelector('[data-testid="videoComponent"]') ||
    article.querySelector('[data-testid="videoPlayer"]') ||
    article.querySelector('img[src*="pbs.twimg.com/media/"]')
  );
}

/** タイムラインのツイートカードにダウンロードボタンを追加する */
function addTweetCardBtn(article) {
  if (article.dataset.xk) return;
  if (!hasMedia(article)) return;
  const url = tweetUrlFromArticle(article);
  if (!url) return;

  // reply / like が含まれる group をアクションバーとして選択する
  let bar = null;
  for (const g of article.querySelectorAll('[role="group"]')) {
    if (g.querySelector('[data-testid="reply"]') || g.querySelector('[data-testid="like"]')) {
      bar = g; break;
    }
  }
  if (!bar) bar = article.querySelector('[role="group"]');
  if (!bar) return;

  article.dataset.xk = '1';

  const btn = document.createElement('button');
  btn.title = 'x-keeper で保存';
  btn.style.cssText = 'display:inline-flex;align-items:center;padding:0 8px;height:36px;border:none;border-radius:9999px;background:transparent;color:#71767b;cursor:pointer;gap:4px;transition:background .15s,color .15s;flex-shrink:0;';
  btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 16l-5-5 1.4-1.4 2.6 2.6V4h2v8.2l2.6-2.6L17 11l-5 5zm-6 4v-2h12v2H6z"/></svg>`;
  btn.addEventListener('mouseenter', () => { btn.style.background = 'rgba(29,155,240,.1)'; btn.style.color = '#1d9bf0'; });
  btn.addEventListener('mouseleave', () => { btn.style.background = 'transparent'; btn.style.color = '#71767b'; });
  btn.addEventListener('click', (e) => { e.stopPropagation(); e.preventDefault(); queueUrl(url, btn); });
  bar.appendChild(btn);
}

function onXNavigate() {
  const path = location.pathname;
  removeFloatingBtn();

  // /username/status/TWEETID
  const sm = path.match(/^\/([^/]+)\/status\/(\d+)/);
  if (sm) {
    setFloatingBtn('このツイートを保存', '#1d9bf0', (btn) =>
      queueUrl(`https://x.com/${sm[1]}/status/${sm[2]}`, btn)
    );
    return;
  }

  // /username/media
  const mm = path.match(/^\/([^/]+)\/media$/);
  if (mm) {
    setFloatingBtn('全メディアを保存', '#1d9bf0', (btn) =>
      queueUrl(`https://x.com/${mm[1]}/media`, btn)
    );
  }
}

function setupXTwitter() {
  // サービスワーカーからの NAVIGATE メッセージを受信して UI を更新する
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === 'NAVIGATE') onXNavigate();
  });

  // popstate (ブラウザ戻る/進む)
  window.addEventListener('popstate', onXNavigate);

  // タイムライン上のツイートカード監視
  new MutationObserver(() => {
    document.querySelectorAll('article[data-testid="tweet"]:not([data-xk])').forEach(addTweetCardBtn);
  }).observe(document.body, { childList: true, subtree: true });

  onXNavigate();
}

// ── Pixiv ─────────────────────────────────────────────────────────────────────

function onPixivNavigate() {
  removeFloatingBtn();
  if (!/\/artworks\/\d+/.test(location.pathname)) return;
  const url = location.href.split('?')[0];
  setFloatingBtn('x-keeper で保存', '#0096fa', (btn) => queueUrl(url, btn));
}

function setupPixiv() {
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === 'NAVIGATE') setTimeout(onPixivNavigate, 80);
  });
  window.addEventListener('popstate', onPixivNavigate);
  onPixivNavigate();
}

// ── 初期化 ────────────────────────────────────────────────────────────────────

(function init() {
  const host = location.hostname;
  if (host === 'x.com' || host === 'twitter.com') setupXTwitter();
  else if (host === 'www.pixiv.net') setupPixiv();
})();
