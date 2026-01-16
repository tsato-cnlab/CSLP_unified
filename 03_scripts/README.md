# 複数failure_weight自動実行スクリプト

## 概要

複数のfailure_weight値で最適化を自動的に連続実行するスクリプトです。

## 使用方法

### 基本的な使い方

```bash
# デフォルト（0.0〜1.0を0.1刻み）で実行
python scripts/run_multiple_weights.py --base-config unified_config.json

# カスタムweightで実行
python scripts/run_multiple_weights.py --base-config unified_config.json --weights 0.0 0.3 0.5 1.0

# 既に実行済みのweightをスキップ
python scripts/run_multiple_weights.py --base-config unified_config.json --skip-existing
```

### オプション

- `--base-config`: ベースとなる設定JSONファイル（必須）
- `--weights`: 実行するfailure_weightのリスト（デフォルト: 0.0〜1.0を0.1刻み）
- `--skip-existing`: 既に結果が存在する場合はスキップ

## LINE通知の設定

バッチ処理完了時にLINEで通知を受け取ることができます。

### 1. LINE Messaging APIチャネルの作成

1. [LINE Developers](https://developers.line.biz/)にアクセス
2. ログイン後、プロバイダーとMessaging APIチャネルを作成
3. **チャネルアクセストークン（長期）**を発行
4. QRコードでボットを友だち追加
5. **ユーザーID**を取得（詳細は[LINE_NOTIFY_SETUP.md](LINE_NOTIFY_SETUP.md)参照）

### 2. 環境変数の設定

#### Linux/Mac

```bash
# 一時的に設定（現在のターミナルセッションのみ）
export LINE_CHANNEL_ACCESS_TOKEN="あなたのチャネルアクセストークン"
export LINE_USER_ID="あなたのユーザーID"

# 恒久的に設定（~/.bashrc または ~/.zshrc に追加）
echo 'export LINE_CHANNEL_ACCESS_TOKEN="あなたのチャネルアクセストークン"' >> ~/.bashrc
echo 'export LINE_USER_ID="あなたのユーザーID"' >> ~/.bashrc
source ~/.bashrc
```

#### Windows (PowerShell)

```powershell
# 一時的に設定
$env:LINE_CHANNEL_ACCESS_TOKEN="あなたのチャネルアクセストークン"
$env:LINE_USER_ID="あなたのユーザーID"

# 恒久的に設定
[System.Environment]::SetEnvironmentVariable("LINE_CHANNEL_ACCESS_TOKEN", "あなたのチャネルアクセストークン", "User")
[System.Environment]::SetEnvironmentVariable("LINE_USER_ID", "あなたのユーザーID", "User")
```

### 3. 実行

通常通り実行すると、完了時に通知が送られます：

```bash
python scripts/run_multiple_weights.py --base-config unified_config.json
```

通知には以下の情報が含まれます：
- 終了時刻
- 経過時間
- 実行数
- 成功数
- 失敗数

### LINE通知なしで実行

環境変数を設定しない場合、通知機能は自動的に無効になり、通常通り実行されます。

詳細な設定方法は [LINE_NOTIFY_SETUP.md](LINE_NOTIFY_SETUP.md) を参照してください。

## 動作

1. ベース設定ファイルを読み込み
2. 各weightごとに：
   - `failure_weight`を指定値に変更
   - 実験名を`<元の名前>_P<weight*100>`に変更（例: `unified_P10`）
   - 一時設定ファイルを作成
   - `cs_optim_unified.py`を実行
   - 完了後、一時ファイルを削除
3. 全体の実行結果をサマリー表示

## 実行例

```bash
# 例1: デフォルト実行
python scripts/run_multiple_weights.py --base-config unified_config.json

# 実行されるweight: 0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0
# 生成される実験名: unified_P00, unified_P10, unified_P20, ...

# 例2: カスタムweight
python scripts/run_multiple_weights.py --base-config unified_config.json --weights 0.0 0.25 0.5 0.75 1.0

# 実行されるweight: 0.0, 0.25, 0.5, 0.75, 1.0
# 生成される実験名: unified_P00, unified_P25, unified_P50, unified_P75, unified_P100

# 例3: スキップ機能
python scripts/run_multiple_weights.py --base-config unified_config.json --skip-existing

# 既にbest_result.jsonが存在するweightはスキップ
```

## 出力

### 実行中の出力

```
============================================================
🔄 複数weight最適化バッチ実行
============================================================
📁 ベース設定: unified_config.json
📊 実行するweight: [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
🔢 実行数: 11
============================================================

############################################################
# 進捗: 1/11
############################################################

============================================================
🚀 最適化開始: failure_weight = 0.00
📝 設定ファイル: temp_config_P00.json
📊 実験名: unified_P00
============================================================

...（最適化実行）...

✅ 完了: failure_weight = 0.00
```

### 最終サマリー

```
============================================================
📊 実行結果サマリー
============================================================
  P=0.00: ✅ 成功
  P=0.10: ✅ 成功
  P=0.20: ✅ 成功
  P=0.30: ✅ 成功
  P=0.40: ✅ 成功
  P=0.50: ✅ 成功
  P=0.60: ✅ 成功
  P=0.70: ✅ 成功
  P=0.80: ✅ 成功
  P=0.90: ✅ 成功
  P=1.00: ✅ 成功

成功: 11/11
============================================================
```

## 中断と再開

- **中断**: Ctrl+C で中断可能
- **再開**: `--skip-existing`オプションで既に完了したweightをスキップして再開

```bash
# 中断した後、再開
python scripts/run_multiple_weights.py --base-config unified_config.json --skip-existing
```

## 注意事項

- 各最適化は順次実行されます（並列実行ではありません）
- 1つのweightで数時間かかる場合があります
- 全11個実行すると数日かかる可能性があります
- 実行中は定期的に進捗を確認することを推奨

## トラブルシューティング

### エラーが発生した場合

スクリプトは個別のweightでエラーが発生しても続行します。最後のサマリーでエラーの有無を確認できます。

### 一時ファイルが残る場合

通常は自動削除されますが、異常終了時に残る場合があります：

```bash
rm temp_config_P*.json
```

## 関連ファイル

- `cs_optim_unified.py`: 最適化メインスクリプト
- `unified_config.json`: ベース設定ファイル
- `/srv/samba/share/output/`: 結果出力ディレクトリ
