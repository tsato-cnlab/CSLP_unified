#!/bin/bash
# eMATES最適化プロジェクト - Ubuntu/Debian環境セットアップ

set -e  # エラー時に停止

echo "=== eMATES最適化プロジェクト環境セットアップ開始 ==="

# システムアップデート
echo "システムをアップデート中..."
sudo apt-get update
sudo apt-get upgrade -y

# 必要なシステムパッケージをインストール
echo "システムパッケージをインストール中..."
sudo apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    build-essential \
    libfreetype6-dev \
    libpng-dev \
    python3-tk \
    fonts-ipafont \
    fonts-ipaexfont \
    sqlite3 \
    libsqlite3-dev \
    git \
    curl \
    wget

# 仮想環境作成
echo "Python仮想環境を作成中..."
python3 -m venv venv_emates

# 仮想環境をアクティブ化
echo "仮想環境をアクティブ化中..."
source venv_emates/bin/activate

# pipをアップグレード
echo "pipをアップグレード中..."
pip install --upgrade pip

# requirements.txtからパッケージをインストール
if [ -f "requirements_cross_platform.txt" ]; then
    echo "Pythonパッケージをインストール中..."
    pip install -r requirements_cross_platform.txt
else
    echo "警告: requirements_cross_platform.txt が見つかりません"
    echo "手動でパッケージをインストールしてください"
fi

# Jupyter Notebookをインストール（含まれていない場合）
echo "Jupyter Notebookをインストール中..."
pip install jupyter notebook ipywidgets

# 日本語フォントの確認
echo "日本語フォントの確認中..."
python3 -c "
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

# 利用可能な日本語フォントを確認
fonts = [f.name for f in fm.fontManager.ttflist if 'IPA' in f.name or 'Noto' in f.name]
if fonts:
    print('利用可能な日本語フォント:', fonts)
else:
    print('日本語フォントが見つかりません。追加インストールが必要な可能性があります。')
"

echo ""
echo "=== セットアップ完了 ==="
echo "仮想環境をアクティブ化するには:"
echo "  source venv_emates/bin/activate"
echo ""
echo "Jupyter Notebookを起動するには:"
echo "  source venv_emates/bin/activate"
echo "  jupyter notebook"
echo ""
