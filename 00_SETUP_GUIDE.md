# 開発環境セットアップガイド (uv版)

このプロジェクトでは、高速で信頼性の高いパッケージマネージャ **uv** を使用して環境管理を行っています。Windows と Linux の両方で全く同じ手順で環境を構築できます。

---

## 🚀 クイックスタート

```bash
# 1. uvをインストール
# (詳細な手順は後述)

# 2. 依存関係をインストール
uv sync

# 3. 実行
uv run python src/run_emates.py
```

---

## 1. uv のインストール

OSに合わせて以下のコマンドを実行し、`uv` をインストールしてください。

### Windows (PowerShell)
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### Linux (macOS共通)
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

> **Note**: インストール後、ターミナルを再起動してパスを通してください。

---

## 2. プロジェクトのセットアップ

リポジトリをクローンしたディレクトリで以下を実行します：

```bash
# 依存関係の同期（仮想環境 .venv が自動作成されます）
uv sync
```

これで環境構築は完了です！🎉
従来の `pip install -r requirements.txt` や `python -m venv` などの手順は一切不要です。

---

## 3. アプリケーションの実行

`uv` 環境下では、コマンドの前に `uv run` を付けるだけで、自動的に仮想環境内で実行されます。

### Pythonスクリプトの実行
```bash
# メインスクリプトの実行例
uv run python src/run_emates.py

# 最適化スクリプトの実行例
uv run python cs_optim_prob.py
```

### Jupyter Notebook の起動
```bash
# サーバーを起動
uv run jupyter notebook
```
ブラウザで `http://localhost:8888` が開きます。

---

## 4. 開発ツールの活用

### 新しいパッケージの追加
`pip install` の代わりに以下を使用します：

```bash
# パッケージを追加（例：pandas）
uv add pandas

# 開発用パッケージを追加（例：pytest）
uv add --dev pytest
```

### 依存関係の更新
```bash
# 全パッケージを最新互換バージョンに更新
uv lock --upgrade
uv sync
```

---

## 5. VSCode の推奨設定

VSCodeで開発する場合、`.vscode/settings.json` に以下の設定を入れておくと快適です（リポジトリの推奨設定として既に含まれています）：

- インタプリタパス: `.venv/bin/python` (Windowsなら `.venv\Scripts\python.exe`)
- フォーマッタ: Ruff (自動フォーマット)
- リンター: Pylance / Ruff

---

## ❓ よくある質問

### Q. `uv sync` でエラーが出る
A. `uv.lock` と `pyproject.toml` の整合性が取れていない可能性があります。以下を試してください：
```bash
# ロックファイルを再生成して同期
uv lock
uv sync
```

### Q. 従来の `source .venv/bin/activate` は必要？
A. **不要です。**
`uv run` を使えば、アクティベートなしで常に正しい環境で実行されます。
ただし、手動でアクティベートしたい場合は以下も可能です：
- **Linux/Mac**: `source .venv/bin/activate`
- **Windows**: `.venv\Scripts\activate`

### Q. Dockerは必要ないの？
A. 基本的には**不要**です。
`uv` がOS間の差異を吸収し、ロックファイルでバージョンを固定しているため、WindowsでもLinuxでも同じ動作が保証されます。OS固有のライブラリ依存問題が発生した場合のみDockerの使用を検討してください。

---

作成日: 2025年12月10日
