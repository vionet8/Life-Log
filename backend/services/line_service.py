"""
LINE Messaging API ラッパー
"""
import logging
import httpx
from linebot.v3.messaging import (
    AsyncApiClient,
    AsyncMessagingApi,
    Configuration,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage,
    QuickReply,
    QuickReplyItem,
    MessageAction,
)
from backend.config import LINE_CHANNEL_ACCESS_TOKEN, RICH_MENU_YU, RICH_MENU_NAGI, RICH_MENU_MIRAI

logger = logging.getLogger(__name__)
_configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)

_PERSONA_MENU_MAP = {
    "yu":    lambda: RICH_MENU_YU,
    "nagi":  lambda: RICH_MENU_NAGI,
    "mirai": lambda: RICH_MENU_MIRAI,
}


async def reply(reply_token: str, text: str, quick_replies: list[str] | None = None) -> None:
    """テキストメッセージを返信する。quick_replies があればクイックリプライを添付。"""
    messages_payload = []

    qr = None
    if quick_replies:
        items = [
            QuickReplyItem(action=MessageAction(label=label, text=label))
            for label in quick_replies
        ]
        qr = QuickReply(items=items)

    messages_payload.append(TextMessage(text=text, quick_reply=qr))

    async with AsyncApiClient(_configuration) as api_client:
        api = AsyncMessagingApi(api_client)
        await api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=messages_payload,
            )
        )


async def reply_multi(reply_token: str, texts: list[str]) -> None:
    """複数テキストメッセージを返信する（最大5件）。"""
    async with AsyncApiClient(_configuration) as api_client:
        api = AsyncMessagingApi(api_client)
        await api.reply_message(
            ReplyMessageRequest(
                reply_token=reply_token,
                messages=[TextMessage(text=t) for t in texts[:5]],
            )
        )


async def set_persona_rich_menu(user_id: str, persona: str) -> None:
    """ペルソナに対応したリッチメニューをユーザーに紐付ける。IDが未設定なら何もしない。"""
    getter = _PERSONA_MENU_MAP.get(persona)
    if not getter:
        return
    rich_menu_id = getter()
    if not rich_menu_id:
        logger.info(f"Rich menu ID for persona '{persona}' not configured. Skipping.")
        return
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://api.line.me/v2/bot/user/{user_id}/richmenu/{rich_menu_id}",
                headers={"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"},
                timeout=10.0,
            )
            resp.raise_for_status()
        logger.info(f"Rich menu '{rich_menu_id}' linked to user {user_id}")
    except Exception as e:
        logger.warning(f"Failed to link rich menu for user {user_id}: {e}")


async def push(user_id: str, text: str, quick_replies: list[str] | None = None) -> None:
    """プッシュメッセージを送信する（reply_token 不要）。振り返りなど処理完了後の通知に使用。"""
    qr = None
    if quick_replies:
        items = [
            QuickReplyItem(action=MessageAction(label=label, text=label))
            for label in quick_replies
        ]
        qr = QuickReply(items=items)

    async with AsyncApiClient(_configuration) as api_client:
        api = AsyncMessagingApi(api_client)
        await api.push_message(
            PushMessageRequest(
                to=user_id,
                messages=[TextMessage(text=text, quick_reply=qr)],
            )
        )
