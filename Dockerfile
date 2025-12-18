# eMATES最適化プロジェクト用Dockerfile (uv対応)
FROM python:3.12-slim

# uvのインストール
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# 環境変数設定（uvのキャッシュ最適化）
ENV UV_COMPILE_BYTECODE=0
ENV UV_LINK_MODE=copy

# システムの依存関係をインストール
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libfreetype6-dev \
    libpng-dev \
    fonts-ipafont \
    fonts-ipaexfont \
    sqlite3 \
    libsqlite3-dev \
    && rm -rf /var/lib/apt/lists/*

# プロジェクト設定をコピー（uv.lockも含める）
COPY pyproject.toml uv.lock .python-version ./

# uvで依存関係をインストール（frozenモードでロックファイルを使用）
RUN uv sync --frozen --no-dev --no-install-project

# プロジェクトファイルをコピー
COPY . .

# 日本語環境設定
ENV LANG=ja_JP.UTF-8
ENV LC_ALL=ja_JP.UTF-8

# Jupyter用ポート
EXPOSE 8888

# uvの仮想環境を使用してJupyterを起動
CMD ["uv", "run", "jupyter", "notebook", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root", "--NotebookApp.token=''"]
