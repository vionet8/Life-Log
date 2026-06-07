# セットアップガイド

## 1. Python 仮想環境の作成

```powershell
cd C:\Apps\Life_log
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 2. .env ファイルの作成

```powershell
copy .env.example .env
```

`.env` を開いて以下を設定（次のステップで取得します）：

```
LINE_CHANNEL_SECRET=（LINE Developers から取得）
LINE_CHANNEL_ACCESS_TOKEN=（LINE Developers から取得）
ANTHROPIC_API_KEY=（Anthropic Console から取得）
```

## 3. LINE Developers でチャンネルを作る

1. https://developers.line.biz にログイン
2. 「プロバイダーを作成」→ 名前を入力（例：LifeLog）
3. 「Messaging API チャンネルを作成」
   - チャンネル名：Life-Log & Focus
   - チャンネル説明：ジャーナリング・タスク管理Bot
4. チャンネル作成後:
   - 「Messaging API 設定」タブ
   - **Channel secret** をコピー → `.env` の `LINE_CHANNEL_SECRET` へ
   - 「チャンネルアクセストークン（長期）」を発行 → `.env` の `LINE_CHANNEL_ACCESS_TOKEN` へ
5. 「応答メッセージ」を**オフ**にする（Bot が返信するため）
6. 「Webhook の利用」を**オン**にする

## 4. Anthropic API キーを取得

1. https://console.anthropic.com → API Keys
2. キーを作成 → `.env` の `ANTHROPIC_API_KEY` へ

## 5. 開発サーバーを起動

```powershell
python run.py
```

`http://localhost:8001/health` で `{"status":"ok"}` が返れば成功。

## 6. ngrok で外部公開（開発時）

LINE の Webhook は HTTPS の URL が必要なので ngrok を使います。

```powershell
# ngrok をインストール済みの場合
ngrok http 8001
```

表示された `https://xxxx.ngrok-free.app` をコピーして  
LINE Developers → Messaging API 設定 → Webhook URL に貼り付け：

```
https://xxxx.ngrok-free.app/webhook
```

「検証」ボタンを押して ✅ になれば完了。

## 7. 動作確認

LINE アプリで作成した Bot を友だち追加し、  
「つぶやく」と送信してみてください。

---

## ディレクトリ構成

```
Life_log/
├── backend/
│   ├── __init__.py
│   ├── main.py          ← FastAPI アプリ
│   ├── webhook.py       ← LINE Webhook ルーター
│   ├── config.py        ← 環境変数
│   ├── handlers/
│   │   ├── murmur.py    ← ① つぶやき
│   │   ├── task.py      ← ② タスク整理
│   │   ├── review.py    ← ③ 振り返り
│   │   └── settings.py  ← ④ 設定
│   ├── models/
│   │   └── database.py  ← SQLite アクセス層
│   └── services/
│       ├── claude_service.py ← Claude API
│       └── line_service.py   ← LINE API ラッパー
├── docs/
│   ├── prototype_line_chat.md
│   ├── spec.md
│   └── setup_guide.md  ← このファイル
├── .env                 ← 作成する（git 管理外）
├── .env.example
├── requirements.txt
├── run.py
└── README.md
```
