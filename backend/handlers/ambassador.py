"""
アンバサダー申請ハンドラ
ユーザーが「アンバサダー申請」と送ったときのフロー
"""
import logging
from backend.models import database as db
from backend.services import line_service as line

logger = logging.getLogger(__name__)

_APPLY_OK = {
    "yu":    "申請を受け付けた。審査後に連絡する。",
    "nagi":  "申請ありがとう！😊 審査してから連絡するね。",
    "mirai": "申請を受け取った。審査後に届けるよ。",
}

_ALREADY_APPLIED = {
    "yu":    "申請はすでに受け付けている。審査結果を待って。",
    "nagi":  "もう申請してくれてるよ😊 審査結果を待っててね！",
    "mirai": "申請はすでに届いてる。結果を待って。",
}

_ALREADY_AMBASSADOR = {
    "yu":    "もうアンバサダーだ。詳細レポートが使える。",
    "nagi":  "もうアンバサダーだよ！😊 詳細レポートが使えるよ！",
    "mirai": "すでにアンバサダー。詳細レポートが解放されてるよ。",
}


async def start(reply_token: str, user: dict) -> None:
    persona = user.get("persona", "nagi")

    if user.get("plan") == "ambassador":
        await line.reply(reply_token, _ALREADY_AMBASSADOR.get(persona, _ALREADY_AMBASSADOR["nagi"]))
        return

    if user.get("ambassador_applied_at"):
        await line.reply(reply_token, _ALREADY_APPLIED.get(persona, _ALREADY_APPLIED["nagi"]))
        return

    await db.apply_ambassador(user["id"])
    await line.reply(reply_token, _APPLY_OK.get(persona, _APPLY_OK["nagi"]))
