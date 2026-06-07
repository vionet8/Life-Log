"""
⑤ プロフィール生成ハンドラ
状態遷移: profile_purpose → profile_period → profile_generating → idle
          profile_purpose → profile_custom（その他の場合）→ profile_period → ...
"""
import asyncio
import logging
from datetime import datetime
from backend.models import database as db
from backend.services import line_service as line
from backend.services import claude_service as claude

logger = logging.getLogger(__name__)

PURPOSE_LABELS = [
    "🤖 別のAIに相談",
    "👥 誰かに説明",
    "🔍 自己分析",
    "💼 転職・副業",
    "✏️ その他",
]


# ─── バックグラウンド生成タスク ───────────────────────────────────────────────

async def _generate_and_deliver(
    user: dict,
    purpose: str,
    custom_purpose: str | None,
    period_label: str,
    entries: list,
    tasks: list,
) -> None:
    """バックグラウンドでプロフィールを生成し push で届ける。"""
    try:
        profile_text = await claude.generate_profile(
            purpose=purpose,
            custom_purpose=custom_purpose,
            period_label=period_label,
            entries=entries,
            tasks=tasks,
            persona=user.get("persona", "nagi"),
        )

        session = await db.get_session(user["id"])
        if session["state"] == "profile_generating":
            await db.reset_session(user["id"])

        purpose_display = custom_purpose if custom_purpose else purpose
        header = f"📋 プロフィール生成完了\n用途：{purpose_display}\n期間：{period_label}\n════════════════════════════\n\n"
        footer = "\n\n════════════════════════════\n💡 このメッセージを長押し→コピーで使えます"

        await line.push(
            user["id"],
            header + profile_text + footer,
        )

    except Exception as e:
        logger.error(f"Profile generation failed for user {user['id']}: {e}", exc_info=True)
        session = await db.get_session(user["id"])
        if session["state"] == "profile_generating":
            await db.reset_session(user["id"])
        await line.push(
            user["id"],
            "プロフィールの生成中にエラーが発生しました。\nもう一度「⚙️ 設定」→「📋 プロフィール生成」からお試しください 🙏",
        )


async def _kick_generation(reply_token: str, user: dict, purpose: str, custom_purpose: str | None) -> None:
    """用途が決まったら全期間データで生成を開始する。"""
    entries = await db.get_entries(user["id"])          # since=None → 全期間
    tasks = await db.get_todo_tasks(user["id"])

    thinking_msg = (
        f"わかった！\n「{custom_purpose or purpose}」用のプロフィールを作るね 📋\n\n少々お待ちください 🤔\n（生成中も他の操作はできます）"
        if user.get("persona", "nagi") == "nagi" else
        f"承知しました。\n「{custom_purpose or purpose}」用のプロフィールを生成中です 📋\n\nしばらくお待ちください 🤔\n（生成中も他の操作は可能です）"
    )

    await db.set_session(user["id"], "profile_generating")
    await line.reply(reply_token, thinking_msg)

    asyncio.create_task(
        _generate_and_deliver(user, purpose, custom_purpose, "全期間", entries, tasks)
    )


# ─── エントリーポイント ───────────────────────────────────────────────────────

async def start(reply_token: str, user: dict) -> None:
    """設定メニューから「プロフィール生成」を選んだとき。"""
    await db.set_session(user["id"], "profile_purpose")
    await line.reply(
        reply_token,
        "📋 プロフィール生成\n\n▼ どんな用途で使いますか？",
        PURPOSE_LABELS,
    )


async def handle(reply_token: str, user: dict, text: str, state: str, context: dict) -> None:

    # ── 用途選択 ─────────────────────────────────────────────────────────────
    if state == "profile_purpose":
        if text not in PURPOSE_LABELS:
            await line.reply(reply_token, "ボタンから選んでください 🙏", PURPOSE_LABELS)
            return

        if text == "✏️ その他":
            await db.set_session(user["id"], "profile_custom")
            ask = "どんな用途で使いますか？\n自由に教えてください ✏️" if user.get("persona", "nagi") == "nagi" else "用途を自由に入力してください。"
            await line.reply(reply_token, ask)
        else:
            # 用途確定 → 即生成開始（全期間固定）
            await _kick_generation(reply_token, user, text, None)

    # ── その他の用途を自由入力 → 即生成開始 ──────────────────────────────────
    elif state == "profile_custom":
        await _kick_generation(reply_token, user, "✏️ その他", text)

    # ── 生成中メッセージ ──────────────────────────────────────────────────────
    elif state == "profile_generating":
        wait_msg = (
            "まだプロフィールを作っているよ 🤔\nもうちょっと待ってね！"
            if user.get("persona", "nagi") == "nagi" else
            "プロフィールを生成中です 🤔\n完成次第お送りします。"
        )
        await line.reply(reply_token, wait_msg)
