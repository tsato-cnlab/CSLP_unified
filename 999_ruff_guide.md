# Ruff 使い方ガイド

## 目次
1. [Ruffとは](#ruffとは)
2. [インストール](#インストール)
3. [基本的な使い方](#基本的な使い方)
4. [チェックルール](#チェックルール)
5. [自動修正](#自動修正)
6. [設定ファイル](#設定ファイル)
7. [実用例](#実用例)
8. [VS Code統合](#vs-code統合)

---

## Ruffとは

Ruffは**極めて高速なPythonリンター・フォーマッター**です。
- FlakeB、Black、isort、pyupgradeなど多数のツールの機能を統合
- Rustで実装され、既存ツールの10-100倍高速
- 700以上のルールをサポート

---

## インストール

### uvを使用（推奨）
```bash
uv pip install ruff
```

### pipを使用
```bash
pip install ruff
```

### システムワイドにインストール
```bash
# Ubuntu/Debian
sudo snap install ruff

# macOS
brew install ruff
```

---

## 基本的な使い方

### ファイルのチェック
```bash
# 単一ファイル
ruff check file.py

# 複数ファイル
ruff check file1.py file2.py

# ディレクトリ全体
ruff check .

# 特定のディレクトリ
ruff check src/
```

### フォーマット（Blackスタイル）
```bash
# ファイルをフォーマット
ruff format file.py

# ディレクトリをフォーマット
ruff format .

# チェックのみ（変更しない）
ruff format --check .
```

### 詳細な出力
```bash
# 詳細な説明付き
ruff check file.py --output-format=full

# 簡潔な出力
ruff check file.py --output-format=concise

# JSON形式
ruff check file.py --output-format=json

# GitHub Actions形式
ruff check file.py --output-format=github
```

---

## チェックルール

### 主要なルールカテゴリ

| コード | カテゴリ | 説明 |
|--------|---------|------|
| **E** | pycodestyle errors | PEP 8エラー（構文エラーなど） |
| **W** | pycodestyle warnings | PEP 8警告 |
| **F** | Pyflakes | 論理エラー（未使用変数、未定義名など） |
| **I** | isort | import文のソート |
| **N** | pep8-naming | 命名規則 |
| **D** | pydocstyle | docstring |
| **UP** | pyupgrade | Python構文の最新化 |
| **B** | flake8-bugbear | バグの可能性 |
| **C4** | flake8-comprehensions | 内包表記の最適化 |
| **SIM** | flake8-simplify | コードの簡素化 |
| **RUF** | Ruff固有 | Ruff独自のルール |

### 特定ルールを選択してチェック
```bash
# F（Pyflakes）のみ
ruff check file.py --select F

# E（エラー）とW（警告）のみ
ruff check file.py --select E,W

# F, E, W, Iをチェック
ruff check file.py --select F,E,W,I

# 全ルールをチェック
ruff check file.py --select ALL
```

### 特定ルールを除外
```bash
# E501（行の長さ）を無視
ruff check file.py --ignore E501

# 複数ルールを無視
ruff check file.py --ignore E501,W503
```

### よく使うルールの組み合わせ
```bash
# 基本的なチェック（推奨）
ruff check file.py --select F,E,W,I

# 厳密なチェック
ruff check file.py --select F,E,W,I,N,D,UP

# バグ検出重視
ruff check file.py --select F,B,C4,SIM
```

---

## 自動修正

### 修正可能な問題を自動修正
```bash
# 自動修正を実行
ruff check file.py --fix

# 修正可能な問題のみ表示（実行しない）
ruff check file.py --diff

# unsafe修正も含める
ruff check file.py --fix --unsafe-fixes
```

### よくある自動修正
- **F401**: 未使用import削除
- **I001**: import文のソート
- **F541**: 不要なf-string修正
- **E501**: 長い行の自動分割（format使用時）
- **UP**: Python構文の最新化

```bash
# 未使用importとソートのみ修正
ruff check file.py --fix --select F401,I001

# 全修正可能な問題を修正
ruff check file.py --fix --select ALL
```

---

## 設定ファイル

### pyproject.toml（推奨）
```toml
[tool.ruff]
# 行の最大長
line-length = 88

# Python バージョン
target-version = "py310"

# 除外するファイル
exclude = [
    ".git",
    ".venv",
    "__pycache__",
    "build",
    "dist",
]

[tool.ruff.lint]
# 有効にするルール
select = [
    "E",    # pycodestyle errors
    "W",    # pycodestyle warnings
    "F",    # Pyflakes
    "I",    # isort
    "N",    # pep8-naming
    "UP",   # pyupgrade
    "B",    # flake8-bugbear
    "C4",   # flake8-comprehensions
    "SIM",  # flake8-simplify
]

# 無視するルール
ignore = [
    "E501",  # 行が長すぎる（formatterが処理）
    "E402",  # モジュールレベルのimportがファイル先頭にない
]

# ファイル別の設定
[tool.ruff.lint.per-file-ignores]
"__init__.py" = ["F401"]  # __init__.pyでは未使用importを許可
"test_*.py" = ["D"]       # テストファイルではdocstringチェックなし

[tool.ruff.format]
# 文字列の引用符
quote-style = "double"

# インデント
indent-style = "space"

# 行末のカンマ
skip-magic-trailing-comma = false
```

### ruff.toml
```toml
# pyproject.tomlがない場合はruff.toml

line-length = 100
target-version = "py310"

[lint]
select = ["E", "W", "F", "I"]
ignore = ["E501"]

[format]
quote-style = "double"
```

### .ruff.toml（プロジェクトルート）
```toml
# シンプルな設定
line-length = 88
select = ["E", "F", "W", "I"]
```

---

## 実用例

### 1. プロジェクト全体のチェック
```bash
# プロジェクトのチェック
cd /home/oums/Desktop/emates
source .venv/bin/activate

# 基本チェック
ruff check .

# 修正可能な問題を自動修正
ruff check . --fix

# フォーマット
ruff format .
```

### 2. 段階的な導入
```bash
# ステップ1: 重大なエラーのみ
ruff check . --select F

# ステップ2: 未使用importを削除
ruff check . --fix --select F401

# ステップ3: import順序を修正
ruff check . --fix --select I

# ステップ4: 全エラーをチェック
ruff check . --select E,F,W
```

### 3. CI/CDでの使用
```bash
# 失敗時に終了コードを返す
ruff check . --exit-non-zero-on-fix

# GitHub Actionsで使用
ruff check . --output-format=github
```

### 4. pre-commitフック
```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.1.9
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
```

---

## VS Code統合

### 拡張機能のインストール
```
1. VS Codeの拡張機能タブを開く
2. "Ruff" で検索
3. "Ruff" (Astral Software) をインストール
```

### settings.json設定
```json
{
  // Ruffをデフォルトフォーマッターに設定
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.formatOnSave": true,
    "editor.codeActionsOnSave": {
      "source.fixAll": true,
      "source.organizeImports": true
    }
  },

  // Ruff設定
  "ruff.enable": true,
  "ruff.lint.enable": true,
  "ruff.format.enable": true,
  "ruff.lint.args": [
    "--select=E,F,W,I"
  ],

  // 他のリンターを無効化
  "python.linting.enabled": false,
  "python.linting.pylintEnabled": false,
  "python.linting.flake8Enabled": false
}
```

---

## 実践的なワークフロー

### 新しいプロジェクトでの導入
```bash
# 1. インストール
uv pip install ruff

# 2. 設定ファイル作成
cat > pyproject.toml << 'EOF'
[tool.ruff]
line-length = 88
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "W", "I"]
ignore = ["E501"]
EOF

# 3. チェック実行
ruff check .

# 4. 自動修正
ruff check . --fix

# 5. フォーマット
ruff format .
```

### 既存プロジェクトへの導入
```bash
# 1. 現状チェック
ruff check . --select F,E,W > ruff_report.txt

# 2. 簡単な修正から
ruff check . --fix --select F401,I001

# 3. 段階的に厳しく
ruff check . --fix --select F
ruff check . --fix --select F,E
ruff check . --fix --select F,E,W

# 4. 最終的にフォーマット
ruff format .
```

---

## トラブルシューティング

### ruffが見つからない
```bash
# 仮想環境内で実行
source .venv/bin/activate
which ruff

# パスを確認
echo $PATH

# 直接実行
python -m ruff check file.py
```

### 特定のエラーを無視
```python
# ファイル全体で無視
# ruff: noqa

# 特定の行で無視
import unused_module  # noqa: F401

# 複数ルールを無視
x = 1  # noqa: F841, E501
```

### 設定が反映されない
```bash
# 設定ファイルを確認
ruff check --show-files

# 設定を表示
ruff check --show-settings

# キャッシュをクリア
ruff clean
```

---

## よく使うコマンド一覧

```bash
# 基本チェック
ruff check file.py

# 自動修正
ruff check file.py --fix

# フォーマット
ruff format file.py

# 特定ルールのみ
ruff check file.py --select F,E,W,I

# ルール説明を表示
ruff rule F401

# 全ルール一覧
ruff linter

# 設定を表示
ruff check --show-settings

# キャッシュクリア
ruff clean
```

---

## 参考リンク

- 公式ドキュメント: https://docs.astral.sh/ruff/
- GitHub: https://github.com/astral-sh/ruff
- ルール一覧: https://docs.astral.sh/ruff/rules/
- VS Code拡張: https://marketplace.visualstudio.com/items?itemName=charliermarsh.ruff

---

## クイックリファレンス

### 必須コマンド
```bash
# チェック
ruff check .

# 修正
ruff check . --fix

# フォーマット
ruff format .
```

### 推奨設定（pyproject.toml）
```toml
[tool.ruff]
line-length = 88
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP"]
ignore = ["E501"]
```

### よくあるエラーと対処
- **F401**: 未使用import → `--fix`で自動削除
- **E501**: 行が長い → `ruff format`で自動修正
- **I001**: import順序 → `--fix`で自動ソート
- **F841**: 未使用変数 → 変数名を`_`で始める

---

最終更新: 2025年12月13日
