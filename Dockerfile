# eMATES最適化プロジェクト用Dockerfile
FROM python:3.12-slim

# 作業ディレクトリ設定
WORKDIR /app

# システムの依存関係をインストール
RUN apt-get update && apt-get install -y \
    build-essential \
    python3-dev \
    libfreetype6-dev \
    libpng-dev \
    python3-tk \
    fonts-ipafont \
    fonts-ipaexfont \
    sqlite3 \
    libsqlite3-dev \
    git \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Python依存関係をコピー
COPY requirements_cross_platform.txt .

# Python パッケージをインストール
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements_cross_platform.txt

# Jupyter Notebook用の設定
RUN pip install jupyter notebook ipywidgets

# プロジェクトファイルをコピー
COPY . .

# Jupyter Notebookのポート
EXPOSE 8888

# 日本語フォント設定のための環境変数
ENV LANG=ja_JP.UTF-8
ENV LC_ALL=ja_JP.UTF-8

# デフォルトコマンド
CMD ["jupyter", "notebook", "--ip=0.0.0.0", "--port=8888", "--no-browser", "--allow-root", "--NotebookApp.token=''"]
