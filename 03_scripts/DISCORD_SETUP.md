# Discord Webhook 通知設定ガイド

シミュレーション完了をDiscordで通知する機能の設定方法です。**セットアップは1分で完了**します。

## セットアップ手順

### ステップ1: Discord Webhookを作成（30秒）

1. **Discordサーバーを開く**
   - 通知を受け取りたいサーバーを開く
   - 個人用サーバーがない場合は新規作成（右下の`+`ボタン → サーバーを作成）

2. **通知用チャンネルを選択**
   - 既存のチャンネルを使用するか、新しいチャンネルを作成
   - 例: `#シミュレーション通知`

3. **Webhookを作成**
   - チャンネル名の横の⚙️（歯車アイコン）をクリック → 「連携サービス」
   - 「ウェブフック」タブを選択
   - 「新しいウェブフック」をクリック
   - Webhook名を設定（例: `eMATES通知Bot`）
   - アイコンも設定可能（任意）
   - **「ウェブフックURLをコピー」をクリック**

### ステップ2: 環境変数を設定（30秒）

#### Linux/Mac

```bash
# ターミナルで実行
export DISCORD_WEBHOOK_URL="ここにコピーしたWebhook URLを貼り付け"
```

**恒久的に設定する場合**（推奨）:

```bash
# Bashの場合
echo 'export DISCORD_WEBHOOK_URL="ここにWebhook URL"' >> ~/.bashrc
source ~/.bashrc

# Zshの場合
echo 'export DISCORD_WEBHOOK_URL="ここにWebhook URL"' >> ~/.zshrc
source ~/.zshrc
```

#### Windows (PowerShell)

```powershell
# 一時的に設定
$env:DISCORD_WEBHOOK_URL="ここにWebhook URL"

# 恒久的に設定
[System.Environment]::SetEnvironmentVariable("DISCORD_WEBHOOK_URL", "ここにWebhook URL", "User")
```

### ステップ3: 動作確認（10秒）

```bash
# プロジェクトディレクトリで実行
python 03_scripts/notify_helper.py
```

成功すると、Discordの通知チャンネルに以下のようなメッセージが届きます：

```
🔔 テスト通知
notify_helper.pyからのテスト通知です

送信元: notify_helper.py
ステータス: 正常
```

## 使用方法

### 自動通知（bashスクリプト実行時）

通常通りbashスクリプトを実行するだけで、完了時に自動的にDiscord通知が送られます：

```bash
bash 03_scripts/01_exe_optimize.bash
```

### 手動通知（CLI経由）

```bash
# 成功時の通知
python 03_scripts/send_notification.py \
    --status success \
    --elapsed 7200 \
    --total 6 \
    --success 6

# エラー時の通知
python 03_scripts/send_notification.py \
    --status error \
    --elapsed 3600 \
    --total 6 \
    --success 4 \
    --failed-weights 0.4 0.6
```

## 通知の見た目

### 成功時

Discordに**緑色のEmbed**が表示されます：

```
┌─────────────────────────────────────┐
│ ✅ 最適化バッチ実行完了              │ ← 緑色
├─────────────────────────────────────┤
│ 全てのシミュレーションが正常に      │
│ 完了しました                         │
│                                      │
│ ⏱️ 実行時間    📊 実行数           │
│ 2時間15分30秒   6                   │
│                                      │
│ ✅ 成功        ❌ 失敗              │
│ 6              0                     │
│                                      │
│ 2026-02-01 14:30:00                 │
└─────────────────────────────────────┘
```

### エラー時

Discordに**赤色のEmbed**が表示されます：

```
┌─────────────────────────────────────┐
│ ❌ 最適化バッチ実行完了（エラーあり）│ ← 赤色
├─────────────────────────────────────┤
│ 一部のシミュレーションでエラーが    │
│ 発生しました                         │
│ 失敗したweight: 0.40, 0.60          │
│                                      │
│ ⏱️ 実行時間    📊 実行数           │
│ 1時間5分12秒    6                   │
│                                      │
│ ✅ 成功        ❌ 失敗              │
│ 4              2                     │
│                                      │
│ 2026-02-01 14:30:00                 │
└─────────────────────────────────────┘
```

## トラブルシューティング

### 通知が届かない

1. **環境変数の確認**
   ```bash
   echo $DISCORD_WEBHOOK_URL  # Linux/Mac
   echo $env:DISCORD_WEBHOOK_URL  # Windows PowerShell
   ```
   - URLが正しく表示されるか確認
   - `https://discord.com/api/webhooks/...` の形式になっているか確認

2. **Webhook URLの有効性確認**
   - Discord → サーバー設定 → 連携サービス → ウェブフック
   - 作成したWebhookがリストにあるか確認
   - 削除されていないか確認

3. **手動テスト**
   ```bash
   python 03_scripts/notify_helper.py
   ```
   - エラーメッセージを確認

### エラーメッセージの意味

#### `⚠️ Discord通知の送信に失敗`
- ネットワーク接続を確認
- Webhook URLが正しいか確認
- Webhookが削除されていないか確認

#### `ℹ️ Discord通知は設定されていません`
- 環境変数 `DISCORD_WEBHOOK_URL` が設定されていない
- ステップ2を再度実行

### Webhook URLが漏洩した場合

1. Discord → サーバー設定 → 連携サービス → ウェブフック
2. 漏洩したWebhookの「削除」ボタンをクリック
3. 新しいWebhookを作成
4. 環境変数を新しいURLに更新

## セキュリティ注意事項

- ✅ **Webhook URLは環境変数で管理**（コードに直接書かない）
- ✅ **`.gitignore`に環境変数ファイルを追加**（Gitにコミットしない）
- ✅ **Webhook URLは他人に教えない**
- ⚠️ **漏洩した場合は即座に削除して再作成**

## 通知を無効にする場合

環境変数を削除するだけで通知が無効になります：

```bash
# Linux/Mac
unset DISCORD_WEBHOOK_URL

# Windows PowerShell
Remove-Item Env:DISCORD_WEBHOOK_URL
```

## よくある質問

### Q: 個人用サーバーとは？

A: 自分専用のDiscordサーバーです。友達を招待する必要はありません。

### Q: スマホでも通知を受け取れる？

A: はい！Discordアプリをインストールしてログインすれば、プッシュ通知を受け取れます。

### Q: 複数のマシンから同じWebhookを使える？

A: はい！同じ環境変数を設定すれば、複数のマシンから同じチャンネルに通知できます。

### Q: LINE Notifyが廃止されていなかったら？

A: LINE Notifyは2025年3月末でサービスを終了しました。Discordの方が簡単で機能も豊富なので、Discord推奨です。

### Q: Slackでも使える？

A: いいえ、このスクリプトはDiscord専用です。Slackを使いたい場合はコードの修正が必要です。

## 参考リンク

- [Discord Developer Portal](https://discord.com/developers/docs/intro)
- [Webhook Documentation](https://discord.com/developers/docs/resources/webhook)
- [Embed Formatting](https://discord.com/developers/docs/resources/channel#embed-object)

---

**問題が解決しない場合**:

エラーメッセージ全文と実行環境（OS、Pythonバージョン）を添えて開発者に連絡してください。
