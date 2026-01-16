# Docker環境 セットアップガイド

このガイドでは、Docker初心者向けにeMATESプロジェクトの開発環境の構築方法を説明します。

---

## 📋 目次

1. [Dockerとは？](#1-dockerとは)
2. [事前準備](#2-事前準備)
3. [基本的な使い方](#3-基本的な使い方)
4. [よく使うコマンド](#4-よく使うコマンド)
5. [トラブルシューティング](#5-トラブルシューティング)

---

## 1. Dockerとは？

Dockerは、アプリケーションを「コンテナ」という独立した環境で実行する技術です。

**メリット：**
- 🖥️ Windows、Mac、Linuxで同じ環境を再現可能
- 📦 依存関係の管理が簡単
- 🔄 環境を壊しても簡単にやり直せる

---

## 2. 事前準備

### 2.1 Docker Desktopのインストール

#### Windows の場合

1. [Docker Desktop for Windows](https://docs.docker.com/desktop/install/windows-install/) からインストーラをダウンロード
2. ダウンロードした `Docker Desktop Installer.exe` を実行
3. インストール完了後、PCを再起動
4. Docker Desktopを起動（システムトレイにクジラのアイコンが表示されます）

> ⚠️ **注意**: Windows 10/11 Pro、Enterprise、Educationの場合はHyper-Vを有効化してください。
> Homeエディションの場合はWSL2が必要です。

#### Linux（Ubuntu）の場合

ターミナルで以下のコマンドを実行：

```bash
# 古いバージョンを削除
sudo apt-get remove docker docker-engine docker.io containerd runc

# 必要なパッケージをインストール
sudo apt-get update
sudo apt-get install ca-certificates curl gnupg

# Docker公式GPGキーを追加
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# リポジトリを追加
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Dockerをインストール
sudo apt-get update
sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# sudoなしで実行できるように設定（オプション）
sudo usermod -aG docker $USER
newgrp docker
```

### 2.2 インストール確認

ターミナル（Windows: PowerShell、Linux: Terminal）を開いて以下を実行：

```bash
docker --version
docker compose version
```

バージョンが表示されればインストール成功です！

---

## 3. 基本的な使い方

### 3.1 プロジェクトディレクトリに移動

```bash
cd /path/to/emates
```

Windowsの場合：
```powershell
cd C:\path\to\emates
```

### 3.2 初回セットアップ（イメージのビルド）

初めて使う場合、Dockerイメージをビルドします：

```bash
docker compose build
```

> 📝 初回は依存関係のダウンロードに時間がかかります（5〜10分程度）

### 3.3 Jupyter Notebookを起動

```bash
docker compose up emates
```

起動後、ブラウザで以下のURLにアクセス：
- http://localhost:8888

**停止するには**: `Ctrl + C` を押す

### 3.4 バックグラウンドで起動

ターミナルを閉じても動作し続けるようにする場合：

```bash
docker compose up -d emates
```

**バックグラウンドで起動した場合の停止方法**:
```bash
docker compose down
```

### 3.5 開発用シェル（bash）に入る

Pythonスクリプトを直接実行したい場合：

```bash
docker compose run --rm emates-dev
```

コンテナ内のシェルが起動します。ここで以下のようにPythonを実行できます：

```bash
# コンテナ内で実行
uv run python cs_optim_prob.py
```

**終了するには**: `exit` と入力するか `Ctrl + D` を押す

---

## 4. よく使うコマンド

### 起動・停止

| コマンド | 説明 |
|---------|------|
| `docker compose up emates` | Jupyter Notebookを起動 |
| `docker compose up -d emates` | バックグラウンドで起動 |
| `docker compose down` | 全てのコンテナを停止 |
| `docker compose restart` | 再起動 |

### 開発・デバッグ

| コマンド | 説明 |
|---------|------|
| `docker compose run --rm emates-dev` | bashシェルに入る |
| `docker compose logs emates` | ログを表示 |
| `docker compose logs -f emates` | ログをリアルタイムで表示 |

### メンテナンス

| コマンド | 説明 |
|---------|------|
| `docker compose build` | イメージをビルド |
| `docker compose build --no-cache` | キャッシュなしでビルド（問題発生時） |
| `docker compose ps` | 実行中のコンテナ一覧 |
| `docker system prune` | 不要なデータを削除（容量節約） |

---

## 5. トラブルシューティング

### ❌ エラー: "docker: command not found"

**原因**: Dockerがインストールされていない、またはPATHが通っていない

**解決策**:
1. Docker Desktopを再インストール
2. ターミナルを再起動

---

### ❌ エラー: "Cannot connect to the Docker daemon"

**原因**: Dockerデーモンが起動していない

**解決策**:
- **Windows**: Docker Desktopアプリを起動
- **Linux**: `sudo systemctl start docker` を実行

---

### ❌ エラー: "port is already allocated"

**原因**: ポート8888が別のアプリケーションで使用中

**解決策**:
1. 使用中のアプリを終了
2. または `docker-compose.yml` のポート番号を変更
   ```yaml
   ports:
     - "8889:8888"  # 左側の数字を変更
   ```

---

### ❌ ビルドが途中で失敗する

**解決策**:
```bash
# キャッシュを無効にして再ビルド
docker compose build --no-cache

# それでも失敗する場合、全てをクリーンアップ
docker system prune -a
docker compose build
```

---

### ❌ 日本語が文字化けする

**解決策**: 既に`docker-compose.yml`で日本語環境変数を設定済みですが、問題が続く場合：
```bash
# コンテナ内で確認
docker compose run --rm emates-dev
echo $LANG  # ja_JP.UTF-8 と表示されるはず
```

---

## 📁 プロジェクト構成（参考）

```
emates/
├── Dockerfile           # Dockerイメージの設定
├── docker-compose.yml   # Docker Compose設定
├── .dockerignore        # Dockerビルド時に除外するファイル
├── pyproject.toml       # Pythonプロジェクト設定
├── uv.lock              # 依存関係のロックファイル
├── src/                 # ソースコード
├── data/                # データファイル
└── output/              # 出力ファイル
```

---

## 🔗 参考リンク

- [Docker公式ドキュメント](https://docs.docker.com/)
- [Docker Compose リファレンス](https://docs.docker.com/compose/reference/)
- [uv ドキュメント](https://docs.astral.sh/uv/)

---

## 💡 ワンポイントアドバイス

- **初めて使う場合**: まず `docker compose build` → `docker compose up emates` の順で実行
- **日常的な使用**: `docker compose up emates` だけでOK
- **困ったら**: `docker compose down` → `docker compose up emates` で再起動

---

作成日: 2025年12月10日
