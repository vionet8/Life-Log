"""
② 相談ハンドラ
状態遷移: consult_chat → (継続) → idle

つぶやきと違い：
- 日付・天気・場所は聞かない
- 会話終了時にサマリーをDBに保存（振り返りに反映）
- ペルソナが相手の気持ちを引き出し、着地まで導く
"""
import logging
from backend.models import database as db
from backend.services import line_service as line
from backend.services import claude_service as claude

logger = logging.getLogger(__name__)

END_MARKER = "[END]"  # Claudeが会話終了と判断したときに付けるマーカー

_OPENING = {
    "yu":    "今日はどうしたの？\n話してみて。一緒に整理しよう。",
    "nagi":  "今日はどうしたの？😊\nここにいるよ。",
    "mirai": "今日はどうしたの？\n何か頭にあること、話してみて。",
}

_CLOSE = {
    "yu":    "\n\n話してみてどうだった？\nまた何かあれば聞くよ。",
    "nagi":  "\n\n話してくれてありがとう😊\nまた何かあればいつでも。",
    "mirai": "\n\n話してくれてありがとう。\n未来の自分は、今日のこと覚えてるよ。",
}


async def start(reply_token: str, user: dict) -> None:
    persona = user.get("persona", "nagi")
    await db.set_session(user["id"], "consult_chat", {"messages": [], "turn": 0})
    await line.reply(reply_token, _OPENING.get(persona, _OPENING["nagi"]))


async def handle(reply_token: str, user: dict, text: str, state: str, context: dict) -> None:
    persona = user.get("persona", "nagi")
    history = context.get("messages", [])
    turn = context.get("turn", 0)

    # Claudeに相談メッセージを渡して返答を得る
    response = await claude.analyze_consult_message(text, history, persona)

    # [END]マーカーを検出（ユーザーには見せない）
    is_end = END_MARKER in response
    clean = response.replace(END_MARKER, "").strip()

    # 会話履歴を更新（直近10件だけ保持）
    history = history + [
        {"role": "user", "content": text},
        {"role": "assistant", "content": clean},
    ]
    if len(history) > 10:
        history = history[-10:]

    turn += 1

    if is_end:
        # 相談内容をClaudeがサマリー化して保存（振り返りに反映）
        if history:
            try:
                summary = await claude.summarize_consult(history)
                body = f"[相談] {summary}"
            except Exception:
                # サマリー生成失敗時はユーザー発言を結合して保存
                user_msgs = [m["content"] for m in history if m["role"] == "user"]
                body = "[相談] " + " / ".join(user_msgs)
            await db.create_entry(user["id"], body=body, entry_type="consult")
        # セッションをリセット
        await db.reset_session(user["id"])
        await line.reply(reply_token, clean)
    else:
        await db.set_session(user["id"], "consult_chat", {"messages": history, "turn": turn})
        await line.reply(reply_token, clean)
