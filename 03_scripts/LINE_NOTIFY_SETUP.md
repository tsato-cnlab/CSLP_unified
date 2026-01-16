# LINE Messaging API 通知設定ガイド

バッチ最適化の完了をLINEで通知する機能の設定方法です。

## 1. LINE Messaging APIの設定

### 手順

#### ステップ1: LINE Developersコンソールにアクセス

1. **LINE Developersにアクセス**
   - https://developers.line.biz/ を開く

2. **ログイン**
   - LINEアカウントでログイン
   - 初めての場合は開発者登録が必要

#### ステップ2: プロバイダーを作成

1. **プロバイダーを作成**
   - コンソールで「作成」ボタンをクリック
   - プロバイダー名を入力（例: `eMATES Notification`）

#### ステップ3: Messaging APIチャネルを作成

1. **新規チャネル作成**
   - 「Messaging API」を選択

2. **チャネル情報を入力**
   - **チャネル名**: `eMATES最適化通知Bot`
   - **チャネル説明**: `最適化バッチ実行の完了通知`
   - **大業種**: 任意
   - **小業種**: 任意
   - 利用規約に同意

3. **作成完了**
   - チャネルが作成されます

#### ステップ4: チャネルアクセストークンを取得

1. **Messaging API設定タブ**を開く

2. **チャネルアクセストークン（長期）**
   - 「発行」ボタンをクリック
   - トークンが表示されるので**必ずコピー**してください
   - このトークンは再表示できません！

#### ステップ5: ボットと友だちになる

1. **QRコードをスキャン**
   - Messaging API設定タブにあるQRコードをスキャン
   - または「友だち追加」ボタンからBotを追加

2. **自動応答を無効化**（推奨）
   - LINE Official Account Managerを開く
   - 「設定」→「応答設定」
   - 「応答メッセージ」を無効に
   - 「あいさつメッセージ」も無効に（任意）

#### ステップ6: ユーザーIDを取得

方法は2つあります：

**方法A: 簡単な方法（おすすめ）**

ボットに何かメッセージを送って、Webhook経由でユーザーIDを取得します。
簡単なPythonスクリプトを使います：

```python
# get_user_id.py
from flask import Flask, request
import json

app = Flask(__name__)

@app.route("/webhook", methods=['POST'])
def webhook():
    data = request.get_json()
    print("="*60)
    print("Webhook受信:")
    print(json.dumps(data, indent=2, ensure_ascii=False))
    if 'events' in data and len(data['events']) > 0:
        user_id = data['events'][0]['source']['userId']
        print(f"\n✅ あなたのユーザーID: {user_id}")
    print("="*60)
    return 'OK'

if __name__ == "__main__":
    app.run(port=5000)
```

1. Flaskをインストール: `pip install flask`
2. スクリプトを実行: `python get_user_id.py`
3. ngrokで公開: `ngrok http 5000`（ngrokのインストールが必要）
4. ngrokのURLをLINE DevelopersのWebhook URLに設定
5. ボットにメッセージを送信
6. ターミナルにユーザーIDが表示されます

**方法B: APIで取得**

```python
import requests
import os

access_token = "あなたのチャネルアクセストークン"

# ボットにメッセージを送った後、しばらく待ってから実行
# 注: この方法は複雑なので、方法Aを推奨
```

## 2. 環境変数の設定

取得した**チャネルアクセストークン**と**ユーザーID**を環境変数に設定します。

### Linux/Mac

#### 方法1: 一時的に設定（推奨: テスト用）

```bash
export LINE_CHANNEL_ACCESS_TOKEN="あなたのチャネルアクセストークン"
export LINE_USER_ID="あなたのユーザーID"
```

この方法は現在のターミナルセッションでのみ有効です。

#### 方法2: 恒久的に設定

**Bash の場合:**
```bash
echo 'export LINE_CHANNEL_ACCESS_TOKEN="あなたのチャネルアクセストークン"' >> ~/.bashrc
echo 'export LINE_USER_ID="あなたのユーザーID"' >> ~/.bashrc
source ~/.bashrc
```

**Zsh の場合:**
```bash
echo 'export LINE_CHANNEL_ACCESS_TOKEN="あなたのチャネルアクセストークン"' >> ~/.zshrc
echo 'export LINE_USER_ID="あなたのユーザーID"' >> ~/.zshrc
source ~/.zshrc
```

### Windows

#### PowerShell

**一時的に設定:**
```powershell
$env:LINE_CHANNEL_ACCESS_TOKEN="あなたのチャネルアクセストークン"
$env:LINE_USER_ID="あなたのユーザーID"
```

**恒久的に設定:**
```powershell
[System.Environment]::SetEnvironmentVariable("LINE_CHANNEL_ACCESS_TOKEN", "あなたのチャネルアクセストークン", "User")
[System.Environment]::SetEnvironmentVariable("LINE_USER_ID", "あなたのユーザーID", "User")
```

その後、PowerShellを再起動してください。

## 3. 動作確認

### 簡単なテスト

```bash
# Python環境をアクティベート
source .venv/bin/activate  # Linux/Mac
# または
.venv\Scripts\activate  # Windows

# テストスクリプトを実行
python -c "
import os
import requests

access_token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
user_id = os.environ.get('LINE_USER_ID')

if not access_token or not user_id:
    print('❌ 環境変数が設定されていません')
    print(f'ACCESS_TOKEN: {\"設定済み\" if access_token else \"未設定\"}')
    print(f'USER_ID: {\"設定済み\" if user_id else \"未設定\"}')
else:
    url = 'https://api.line.me/v2/bot/message/push'
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }
    data = {
        'to': user_id,
        'messages': [
            {
                'type': 'text',
                'text': 'テスト通知: eMATES最適化システムからの通知'
            }
        ]
    }
    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 200:
        print('✅ 通知送信成功！LINEを確認してください')
    else:
        print(f'❌ エラー: {response.status_code}')
        print(f'レスポンス: {response.text}')
"
```

LINEに通知が届けば設定完了です！

## 4. バッチ実行時の利用

通常通りスクリプトを実行するだけで、完了時に自動的に通知が送られます：

```bash
python scripts/run_multiple_weights.py --base-config unified_config.json
```

### 通知内容の例

```
🔔 最適化バッチ実行完了
終了時刻: 2025-12-16 23:45:30
経過時間: 12時間34分56秒
実行数: 11
成功: 11
失敗: 0
```

## トラブルシューティング

### 通知が届かない場合

1. **環境変数の確認**
   ```bash
   echo $LINE_CHANNEL_ACCESS_TOKEN  # Linux/Mac
   echo $LINE_USER_ID  # Linux/Mac

   echo $env:LINE_CHANNEL_ACCESS_TOKEN  # Windows PowerShell
   echo $env:LINE_USER_ID  # Windows PowerShell
   ```
   両方の値が表示されるか確認

2. **チャネルアクセストークンの有効性確認**
   - LINE Developersコンソールでチャネルが有効になっているか確認
   - トークンが正しくコピーされているか確認

3. **ボットと友だちになっているか確認**
   - LINEアプリでボットが友だちリストにあるか確認
   - ブロックしていないか確認

4. **ユーザーIDが正しいか確認**
   - ユーザーIDは`U`で始まる長い文字列（例: `Uxxxxxxxxxxxxxxxxxxxxxxxxxxxx`）
   - グループに送る場合はグループID（`C`で始まる）

5. **APIレスポンスを確認**
   ```python
   # 詳細なエラー情報を表示
   response = requests.post(url, headers=headers, json=data)
   print(f"Status: {response.status_code}")
   print(f"Response: {response.text}")
   ```

### よくあるエラー

#### `400 Bad Request`
- ユーザーIDが間違っている
- JSON形式が正しくない

#### `401 Unauthorized`
- チャネルアクセストークンが間違っている
- トークンの有効期限が切れている

#### `403 Forbidden`
- ボットがブロックされている
- ユーザーが友だち追加していない

### トークンが漏洩した場合

1. LINE Developersコンソールにアクセス
2. チャネル設定から「チャネルアクセストークンを再発行」
3. 新しいトークンを取得
4. 環境変数を新しいトークンに更新

## セキュリティ注意事項

- **チャネルアクセストークンとユーザーIDを他人に教えない**でください
- **GitやGitHubにコミットしない**でください
- 環境変数として設定し、コードに直接書かないでください
- 定期的にトークンを再発行することを推奨します
- `.env`ファイルを使う場合は必ず`.gitignore`に追加してください

## 通知を無効にする場合

環境変数を設定しなければ、通知機能は自動的に無効になります：

```bash
unset LINE_CHANNEL_ACCESS_TOKEN  # Linux/Mac
unset LINE_USER_ID  # Linux/Mac

Remove-Item Env:LINE_CHANNEL_ACCESS_TOKEN  # Windows PowerShell
Remove-Item Env:LINE_USER_ID  # Windows PowerShell
```

## グループに通知を送る場合

1. ボットをグループに追加
2. グループIDを取得（方法はユーザーID取得と同じ）
3. `LINE_USER_ID`環境変数にグループIDを設定

グループIDは`C`で始まります（例: `Cxxxxxxxxxxxxxxxxxxxxxxxxxxxx`）

## 参考リンク

- [LINE Developers](https://developers.line.biz/)
- [Messaging API リファレンス](https://developers.line.biz/ja/reference/messaging-api/)
- [Push APIドキュメント](https://developers.line.biz/ja/reference/messaging-api/#send-push-message)
