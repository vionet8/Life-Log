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
| ⑤ | ACTジャーナル | 感情を消さずに「価値（進む方向）」と「1cmの行動」を決める4ステップ |

## ディレクトリ構成（予定）

```
Life_log/
├── README.md
├── docs/
│   ├── prototype_line_chat.md   # LINEトーク画面プロトタイプ
│   └── act_journaling.md        # ⑤ ACTジャーナルの背景・設計
├── backend/
│   ├── main.py                  # FastAPI エントリポイント
│   ├── webhook.py               # LINE Messaging API Webhook
│   ├── handlers/
│   │   ├── murmur.py            # ① つぶやきハンドラ
│   │   ├── task.py              # ② タスク整理ハンドラ
│   │   ├── review.py            # ③ 振り返りハンドラ
│   │   ├── settings.py          # ④ 設定ハンドラ
│   │   └── act.py               # ⑤ ACTジャーナルハンドラ
│   ├── models/
│   │   └── database.py          # SQLite スキーマ
│   ├── services/
│   │   ├── claude_service.py    # Claude API 呼び出し
│   │   ├── review_stats.py      # 振り返り用の決定論的統計エンジン
│   │   └── line_service.py      # LINE API ラッパー
│   └── config.py                # 環境変数
├── scripts/
│   ├── test_review_quality.py   # 振り返りレポートの品質検証
│   └── test_act_flow.py         # ACTジャーナルの状態遷移テスト
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
7. ✅ **Phase 6** — ACTジャーナル（価値と1cmの行動）実装

## ACTジャーナル

「承認・獲得・拡大」が動力源にならなくなったときのために、
**感情を消さずに抱えたまま、大切な方向へ進む** ための4ステップを用意しています。

1. **アクセプタンス** — 今ある感情を、解決せずそのまま観察する
2. **体験の回避チェック** — その行動は「避けるため」か「近づくため」か
3. **価値の明確化** — 目標ではなく、進み続けたい方向・態度を決める
4. **コミット型アクション** — その方向に1cmだけ近づく最小の行動を1つ選ぶ

次回の開始時に前回の1cmの行動の結果を確認し、振り返りレポートには
「選ばれた価値」と「1cmの行動の実行率」が反映されます。

起動はテキストで `ACTジャーナル`（`ACT` / `アクトジャーナル` でも可）。
背景と設計は [docs/act_journaling.md](docs/act_journaling.md) を参照してください。

動作確認：

```
python -m scripts.test_act_flow
```

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
