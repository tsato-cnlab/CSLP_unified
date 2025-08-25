#!/bin/bash
# eMATES最適化プロジェクト - CentOS/RHEL環境セットアップ

set -e  # エラー時に停止

echo "=== eMATES最適化プロジェクト環境セットアップ開始 (CentOS/RHEL) ==="

# システムアップデート
echo "システムをアップデート中..."
sudo yum update -y

# EPELリポジトリを有効化
echo "EPELリポジトリを有効化中..."
sudo yum install -y epel-release

# 必要なシステムパッケージをインストール
echo "システムパッケージをインストール中..."
sudo yum install -y \
    python3 \
    python3-pip \
    python3-devel \
    gcc \
    gcc-c++ \
    make \
    freetype-devel \
    libpng-devel \
    tkinter \
    sqlite \
    sqlite-devel \
    git \
    curl \
    wget

# 日本語フォントのインストール（オプション）
echo "日本語フォントをインストール中..."
sudo yum install -y ipa-gothic-fonts ipa-mincho-fonts ipa-pgothic-fonts ipa-pmincho-fonts

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
fi

# Jupyter Notebookをインストール
echo "Jupyter Notebookをインストール中..."
pip install jupyter notebook ipywidgets

echo ""
echo "=== セットアップ完了 ==="
echo "仮想環境をアクティブ化するには:"
echo "  source venv_emates/bin/activate"
