# ────────────────────────────────────────────────────────────────────────────
# ビルドステージ: 依存ライブラリをインストール
# ────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# pip のキャッシュを活用するため requirements.txt を先にコピーする
COPY requirements.txt .

RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ────────────────────────────────────────────────────────────────────────────
# 実行ステージ: アプリケーション本体のみ含む軽量イメージ
# ────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# セキュリティのため非 root ユーザーで実行する
RUN groupadd --gid 1000 appgroup \
    && useradd --uid 1000 --gid appgroup --no-create-home appuser

WORKDIR /app

# ビルドステージでインストールしたライブラリをコピー
COPY --from=builder /install /usr/local

# アプリケーションのソースコードをコピー
COPY src/ ./src/

# 画像保存先ディレクトリを作成して権限を付与
RUN mkdir -p /data/images && chown -R appuser:appgroup /data/images

USER appuser

# ヘルスチェック: プロセスが生きているかを確認
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD pgrep -f "python -m src.main" || exit 1

CMD ["python", "-m", "src.main"]
