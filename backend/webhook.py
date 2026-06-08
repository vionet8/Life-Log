"""
LINE Messaging API Webhook ルーター
全メッセージをここで受け取り、状態に応じたハンドラへ振り分ける
"""
import hashlib
import hmac
import base64
import logging
from fastapi import APIRouter, Header, HTTPException, Request
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    AudioMessageContent,
    ImageMessageContent,
    StickerMessageContent,
    FollowEvent,
)
from linebot.v3 import WebhookParser
from backend.config import LINE_CHANNEL_SECRET
from backend.models import database as db
from backend.handlers import murmur, task, review, settings, profile, consult

logger = logging.getLogger(__name__)
router = APIRouter()
parser = WebhookParser(LINE_CHANNEL_SECRET)

# リッチメニューのキーワード → ハンドラ起動マッピング
MENU_TRIGGERS = {
    "つぶやく":      "murmur",
    "📝 つぶやく":   "murmur",
    "相談する":      "consult",
    "💬 相談する":   "consult",
    "タスク整理":    "task",
    "✅ タスク整理": "task",
    "振り返り":      "review",
    "📊 振り返り":   "review",
    "設定":          "settings",
    "⚙️ 設定":      "settings",
    "ヘルプ":        "help",
    "❓ ヘルプ":     "help",
}

# 状態プレフィックス → ハンドラモジュールのマッピング
STATE_PREFIX_MAP = {
    "murmur":      murmur,
    "consult":     consult,
    "task":        task,
    "review":      review,
    "settings":    settings,
    "profile":     profile,
    "onboarding":  settings,   # onboarding_persona は settings ハンドラで処理
}


def _verify_signature(body: bytes, signature: str) -> bool:
    hash_digest = hmac.new(
        LINE_CHANNEL_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()
    expected = base64.b64encode(hash_digest).decode("utf-8")
    return hmac.compare_digest(expected, signature)


@router.post("/webhook")
async def webhook(
    request: Request,
    x_line_signature: str = Header(...),
) -> dict:
    body = await request.body()

    # 署名検証
    if not _verify_signature(body, x_line_signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        events = parser.parse(body.decode("utf-8"), x_line_signature)
    except Exception as e:
        logger.error(f"Webhook parse error: {e}")
        raise HTTPException(status_code=400, detail="Parse error")

    for event in events:
        try:
            await _dispatch(event)
        except Exception as e:
            logger.error(f"Event dispatch error: {e}", exc_info=True)
            # 何らかのエラーでユーザーへの返信が途切れた場合、push で最低限通知する
            try:
                if isinstance(event, MessageEvent) and hasattr(event.source, "user_id"):
                    from backend.services import line_service as line
                    await line.push(
                        event.source.user_id,
                        "ごめん、ちょっとうまくいかなかったみたい🙏\nもう一度話しかけてみて。",
                    )
            except Exception:
                pass  # push も失敗したら諦める

    return {"status": "ok"}


WELCOME_MESSAGE = """\
はじめまして！🌱 LifeLog Bot です。

3人のAIが、あなたの毎日の記録と
思考の整理をサポートします。

────────────────
🧠 ユウ（整理・助言）
☕ ナギ（傾聴・深掘り）
🔮 ミライ（振り返り・成長）
────────────────

まず、誰と話したいか選んでください！"""

ONBOARDING_PERSONA_LABELS = [
    "🧠 ユウ（整理・助言）",
    "☕ ナギ（傾聴・深掘り）",
    "🔮 ミライ（振り返り・成長）",
]

_HELP_MESSAGE = {
    "yu": """\
❓ 使い方

📝 つぶやく
 今日あったこと、思ったこと、なんでもいい。
 「大したことないかな」は気にしなくていい。
 書いたら俺なりに返す。

💬 相談する
 頭の中が整理できない、ひっかかることがある、
 そんなとき話しかけて。

✅ タスク整理
 やること管理。メモ代わりに使っていい。

📊 振り返り
 週・月・年の記録をレポートにする。

⚙️ 設定
 話す相手を変えたいとき。""",

    "nagi": """\
❓ 使い方

📝 つぶやく
 なんでも書いていいよ！
 「今日疲れた」でも「おいしいもの食べた」でも。
 書いてくれたら読んで返すね😊

💬 相談する
 なんか気になってること、誰かに話したいとき。
 ここで話して。

✅ タスク整理
 やること管理。メモ代わりにも使えるよ！

📊 振り返り
 週・月・年の記録をまとめてレポートにするよ。

⚙️ 設定
 話す相手を変えたいとき。""",

    "mirai": """\
❓ 使い方

📝 つぶやく
 今感じていること、気になっていること、何でも。
 些細なことでいい。積み重なると未来が変わる。

💬 相談する
 迷っていること、頭の中がぐるぐるしているとき。
 一緒に整理しよう。

✅ タスク整理
 やること管理。未来の自分への申し送りとして。

📊 振り返り
 週・月・年の記録をレポートにする。

⚙️ 設定
 話す相手を変えたいとき。""",
}

_IDLE_NUDGE = {
    "yu":    "何かあった？\n「つぶやく」か「相談する」から話しかけて。",
    "nagi":  "何か書きたいことあった？😊\n「つぶやく」から記録できるよ！",
    "mirai": "今、何か伝えたいことがある？\n「つぶやく」から始めてみて。",
}


async def _dispatch(event) -> None:
    # フォロー（友だち追加）→ ウェルカム + ペルソナ選択
    if isinstance(event, FollowEvent):
        user_id = event.source.user_id
        await db.get_or_create_user(user_id, "ユーザー")
        await db.set_session(user_id, "onboarding_persona")
        from backend.services import line_service as line
        await line.reply(event.reply_token, WELCOME_MESSAGE, ONBOARDING_PERSONA_LABELS)
        return

    if not isinstance(event, MessageEvent):
        return

    # テキスト以外のメッセージ（音声・画像・スタンプ）は案内を返す
    if not isinstance(event.message, TextMessageContent):
        from backend.services import line_service as line
        if isinstance(event.message, AudioMessageContent):
            msg = "音声メッセージはまだ対応していないんだ 🙏\nテキストで送ってもらえると嬉しいな！"
        elif isinstance(event.message, ImageMessageContent):
            msg = "画像はまだ受け取れないんだ 🙏\nテキストで教えてもらえると！"
        elif isinstance(event.message, StickerMessageContent):
            msg = "スタンプありがとう😊\nテキストで話しかけてくれたら返事するね！"
        else:
            msg = "このメッセージ形式には対応していません 🙏\nテキストで入力してください。"
        await line.reply(event.reply_token, msg)
        return

    reply_token = event.reply_token
    user_id = event.source.user_id
    text = event.message.text.strip()

    # ユーザー取得 or 作成
    user = await db.get_or_create_user(user_id, "ユーザー")

    # 現在のセッション状態を取得
    session = await db.get_session(user_id)
    state = session["state"]
    context = session["context"]

    # ─── リッチメニューキーワード（常に最優先） ─────────────────────────────
    if text in MENU_TRIGGERS:
        trigger = MENU_TRIGGERS[text]
        if trigger == "murmur":
            await murmur.start(reply_token, user)
        elif trigger == "consult":
            await consult.start(reply_token, user)
        elif trigger == "task":
            await task.start(reply_token, user)
        elif trigger == "review":
            await review.start(reply_token, user)
        elif trigger == "settings":
            await settings.start(reply_token, user)
        elif trigger == "help":
            from backend.services import line_service as line
            persona = user.get("persona", "nagi")
            await db.set_session(user["id"], "help_confirm")
            _HELP_OPEN = {
                "yu":    "どうした？\nアプリの使い方、説明しようか？",
                "nagi":  "どうしたの？😊\nアプリの説明、聞いてみる？",
                "mirai": "どうしたの？\nアプリについて知りたい？",
            }
            await line.reply(reply_token, _HELP_OPEN.get(persona, _HELP_OPEN["nagi"]), ["はい", "いらない"])
        return

    # ─── ヘルプ確認 ──────────────────────────────────────────────────────────
    if state == "help_confirm":
        from backend.services import line_service as line
        persona = user.get("persona", "nagi")
        await db.reset_session(user["id"])
        if text == "はい":
            await line.reply(reply_token, _HELP_MESSAGE.get(persona, _HELP_MESSAGE["nagi"]))
        else:
            _HELP_NO = {
                "yu":    "了解。何かあれば声かけて。",
                "nagi":  "そっか！何かあったらいつでもね😊",
                "mirai": "わかった。また来てね。",
            }
            await line.reply(reply_token, _HELP_NO.get(persona, _HELP_NO["nagi"]))
        return

    # ─── 進行中の会話を継続 ─────────────────────────────────────────────────
    if state != "idle":
        prefix = state.split("_")[0]
        handler_module = STATE_PREFIX_MAP.get(prefix)
        if handler_module:
            await handler_module.handle(reply_token, user, text, state, context)
            return

    # ─── idle 状態でメニュー外のメッセージ → 温かく誘導 ────────────────────
    from backend.services import line_service as line
    persona = user.get("persona", "nagi")
    await line.reply(
        reply_token,
        _IDLE_NUDGE.get(persona, _IDLE_NUDGE["nagi"]),
        ["📝 つぶやく", "💬 相談する"],
    )
