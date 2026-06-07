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
from backend.handlers import murmur, task, review, settings, profile

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

    return {"status": "ok"}


WELCOME_MESSAGE = """\
はじめまして！🌱 LifeBot です。

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

HELP_MESSAGE = """\
❓ LifeBot の使い方

────────────────
📝 つぶやく
 今の気持ちや出来事を記録
 AIが自然に深掘りしてくれる

💬 相談する
 仕事・人間関係・将来の悩みを相談
 ユウが整理して返してくれる

✅ タスク整理
 やること一覧を管理
 追加・完了・削除

📊 振り返り
 週・月・年のレポートをAIが生成

⚙️ 設定
 話す相手（ペルソナ）を変える
────────────────

話す相手はいつでも「⚙️ 設定」から変更できます。"""


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
            # 相談は murmur と同じフローで、ペルソナがユウの場合に特化した返答になる
            await murmur.start(reply_token, user)
        elif trigger == "task":
            await task.start(reply_token, user)
        elif trigger == "review":
            await review.start(reply_token, user)
        elif trigger == "settings":
            await settings.start(reply_token, user)
        elif trigger == "help":
            from backend.services import line_service as line
            await db.reset_session(user["id"])
            await line.reply(reply_token, HELP_MESSAGE)
        return

    # ─── 進行中の会話を継続 ─────────────────────────────────────────────────
    if state != "idle":
        prefix = state.split("_")[0]
        handler_module = STATE_PREFIX_MAP.get(prefix)
        if handler_module:
            await handler_module.handle(reply_token, user, text, state, context)
            return

    # ─── idle 状態でメニュー外のメッセージ ──────────────────────────────────
    from backend.services import line_service as line
    await line.reply(
        reply_token,
        "メニューから操作してください 😊\n\n"
        "📝 つぶやく　✅ タスク整理\n📊 振り返り　⚙️ 設定",
    )
