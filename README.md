# Life-Log & Focus 📔

> 高い知覚推理力を持つユーザーのための「外部脳」  
> 認知負荷を最小に抑えつつ、日々の思考を構造化・メタ認知するジャーナリング×タスク管理システム

## プロジェクト理念

- **認知リソースの解放** — 即時書き出しでワーキングメモリーのパンクを防ぐ
- **心理的安全性** — 生の位置情報を扱わず「主観的ラベル」に変換
- **メタ認知の自動化** — AIが構造的フィードバックで思考バイアスや行動パターンを可視化

## 機能

| # | 機能 | 概要 |
|---|------|------|
| ① | つぶやき | 場所・天気・夜間は点数を記録。タスクキーワード自動検知 |
| ② | タスク整理 | 未完了一覧・追加・完了・削除 |
| ③ | 振り返り | 週/月/年サマリー + 事実/データ分析/AIの気づき |
| ④ | 設定 | 口調選択（優しいモード / 丁寧モード） |

## ディレクトリ構成（予定）

```
Life_log/
├── README.md
├── docs/
│   └── prototype_line_chat.md   # LINEトーク画面プロトタイプ
├── backend/
│   ├── main.py                  # FastAPI エントリポイント
│   ├── webhook.py               # LINE Messaging API Webhook
│   ├── handlers/
│   │   ├── murmur.py            # ① つぶやきハンドラ
│   │   ├── task.py              # ② タスク整理ハンドラ
│   │   ├── review.py            # ③ 振り返りハンドラ
│   │   └── settings.py          # ④ 設定ハンドラ
│   ├── models/
│   │   └── database.py          # SQLite スキーマ
│   ├── services/
│   │   ├── claude_service.py    # Claude API 呼び出し
│   │   └── line_service.py      # LINE API ラッパー
│   └── config.py                # 環境変数
├── .env.example
└── requirements.txt
```

## 技術スタック

- **Bot プラットフォーム**: LINE Messaging API
- **バックエンド**: FastAPI (Python)
- **DB**: Turso (libsql)
- **AI**: Claude API (claude-sonnet-4-6)
- **ホスティング**: Render

## フェーズ

1. ✅ **Phase 0** — LINEプロトタイプ（テキスト）
2. ✅ **Phase 1** — バックエンド基盤（FastAPI + Turso + Webhook）
3. ✅ **Phase 2** — つぶやき機能 実装
4. ✅ **Phase 3** — タスク整理 実装
5. ✅ **Phase 4** — 振り返り + Claude API 連携
6. ✅ **Phase 5** — デプロイ（Render）

## Renderへのデプロイ

このリポジトリには `render.yaml`（Render Blueprint）が含まれているので、Renderダッシュボードから
「New +」→「Blueprint」で本リポジトリを選択すれば、下記の設定が自動で適用されます。

```
Build Command: pip install -r requirements.txt
Start Command: uvicorn backend.main:app --host 0.0.0.0 --port $PORT
Health Check Path: /health
```

Blueprintを使わず手動でWeb Serviceを作成する場合も、上記のBuild/Start Commandをそのまま設定してください。

### 環境変数

Renderの Environment に以下を設定します（`.env.example` 参照）。

| 変数名 | 必須 | 取得先 |
|--------|------|--------|
| `LINE_CHANNEL_SECRET` | ✅ | LINE Developers → Messaging API |
| `LINE_CHANNEL_ACCESS_TOKEN` | ✅ | LINE Developers → Messaging API |
| `ANTHROPIC_API_KEY` | ✅ | Anthropic Console |
| `TURSO_URL` | ✅ | Turso ダッシュボード |
| `TURSO_AUTH_TOKEN` | ✅ | Turso ダッシュボード |
| `ADMIN_KEY` | 任意 | 自分で設定（管理ページ用） |
| `RICH_MENU_YU` / `RICH_MENU_NAGI` / `RICH_MENU_MIRAI` | 任意 | `setup_rich_menus.py` 実行後に設定 |

デプロイ後、LINE Developers の Webhook URL を `https://<Renderのドメイン>/webhook` に更新してください。

### スリープ対策

無料プランはアクセスが一定時間ないとスリープします。LINE Webhookの応答遅延を防ぐため、
[UptimeRobot](https://uptimerobot.com/) などで `https://<Renderのドメイン>/health` を
5分間隔程度で定期的に叩き、起こしておくことを推奨します。
