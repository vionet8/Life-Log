"""
② タスク整理ハンドラ
状態遷移: idle → task_action → task_add_input → task_add_confirm → idle
                             → task_complete_input → idle
                             → task_delete_input  → idle
"""
from backend.models import database as db
from backend.services import line_service as line

ACTION_LABELS = ["➕ タスクを追加", "✅ 完了にする", "🗑️ 削除する"]


def _format_task_list(tasks: list[dict]) -> str:
    if not tasks:
        return "現在、未完了のタスクはありません 🎉"
    lines = [f"{i + 1}️⃣ {t['body']}" for i, t in enumerate(tasks)]
    return "\n".join(lines)


# ─── エントリーポイント ───────────────────────────────────────────────────────

async def start(reply_token: str, user: dict) -> None:
    """リッチメニュー「タスク整理」タップ時。"""
    tasks = await db.get_todo_tasks(user["id"])
    count = len(tasks)

    if count == 0:
        header = "📋 現在のタスクリスト\n────────────────\n未完了タスクはありません 🎉\n────────────────"
    else:
        task_lines = _format_task_list(tasks)
        header = (
            f"📋 現在のタスクリスト\n────────────────\n"
            f"{task_lines}\n────────────────\n"
            f"{count}件 未完了\n\n▼ 操作を選んでください"
        )

    await db.set_session(user["id"], "task_action", {"tasks": [t["id"] for t in tasks]})
    await line.reply(reply_token, header, ACTION_LABELS)


async def handle(reply_token: str, user: dict, text: str, state: str, context: dict) -> None:
    """タスク関連の状態を処理する。"""

    # ── 操作選択 ─────────────────────────────────────────────────────────────
    if state == "task_action":
        if text == "➕ タスクを追加":
            await db.set_session(user["id"], "task_add_input", context)
            await line.reply(
                reply_token,
                "次は何をしますか？\n\n複数ある場合は改行して入力してください。\n"
                "（例）\n  請求書を送る\n  Aさんに返信する\n  本を1章読む",
            )

        elif text == "✅ 完了にする":
            tasks = await db.get_todo_tasks(user["id"])
            if not tasks:
                await db.reset_session(user["id"])
                await line.reply(reply_token, "完了できるタスクがありません 😊")
                return
            task_lines = _format_task_list(tasks)
            await db.set_session(user["id"], "task_complete_input", {"tasks": [t["id"] for t in tasks]})
            await line.reply(
                reply_token,
                f"どのタスクを完了にしますか？\n番号で答えてください（複数可、スペース区切り）。\n\n{task_lines}",
            )

        elif text == "🗑️ 削除する":
            tasks = await db.get_todo_tasks(user["id"])
            if not tasks:
                await db.reset_session(user["id"])
                await line.reply(reply_token, "削除できるタスクがありません 😊")
                return
            task_lines = _format_task_list(tasks)
            await db.set_session(user["id"], "task_delete_input", {"tasks": [t["id"] for t in tasks]})
            await line.reply(
                reply_token,
                f"どのタスクを削除しますか？\n番号で答えてください（複数可、スペース区切り）。\n\n{task_lines}",
            )

        else:
            await line.reply(reply_token, "ボタンから選んでください 🙏", ACTION_LABELS)

    # ── タスク追加入力 ────────────────────────────────────────────────────────
    elif state == "task_add_input":
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if not lines:
            await line.reply(reply_token, "タスクの内容を入力してください。")
            return
        context["pending_tasks"] = lines
        await db.set_session(user["id"], "task_add_confirm", context)
        bullet = "\n".join(f"  ・{l}" for l in lines)
        await line.reply(
            reply_token,
            f"以下を追加しますか？\n\n{bullet}",
            ["✅ 追加する", "✏️ 修正する", "✖️ キャンセル"],
        )

    # ── タスク追加確認 ────────────────────────────────────────────────────────
    elif state == "task_add_confirm":
        pending = context.get("pending_tasks", [])
        if text == "✅ 追加する":
            await db.create_tasks(user["id"], pending)
            await db.reset_session(user["id"])
            total = await db.get_todo_tasks(user["id"])
            await line.reply(
                reply_token,
                f"📋 タスクを{len(pending)}件追加しました ✅\n\n現在の未完了タスク：{len(total)}件",
            )
        elif text == "✏️ 修正する":
            await db.set_session(user["id"], "task_add_input", {})
            await line.reply(reply_token, "もう一度入力してください。\n（改行区切りで複数入力できます）")
        else:
            await db.reset_session(user["id"])
            await line.reply(reply_token, "キャンセルしました。")

    # ── 完了番号入力 ──────────────────────────────────────────────────────────
    elif state == "task_complete_input":
        task_ids = context.get("tasks", [])
        selected = _parse_numbers(text, len(task_ids))
        if not selected:
            await line.reply(reply_token, "有効な番号を入力してください（例：1 3）")
            return
        target_ids = [task_ids[i - 1] for i in selected if 1 <= i <= len(task_ids)]
        done_bodies = await db.complete_tasks(user["id"], target_ids)
        remaining = await db.get_todo_tasks(user["id"])
        done_list = "\n".join(f"  ✔ {b}" for b in done_bodies)
        await db.reset_session(user["id"])
        await line.reply(
            reply_token,
            f"✅ 完了しました！\n\n{done_list}\n\n残り {len(remaining)}件。お疲れ様です 💪",
        )

    # ── 削除番号入力 ──────────────────────────────────────────────────────────
    elif state == "task_delete_input":
        task_ids = context.get("tasks", [])
        selected = _parse_numbers(text, len(task_ids))
        if not selected:
            await line.reply(reply_token, "有効な番号を入力してください（例：1 3）")
            return
        target_ids = [task_ids[i - 1] for i in selected if 1 <= i <= len(task_ids)]
        deleted_bodies = await db.delete_tasks(user["id"], target_ids)
        remaining = await db.get_todo_tasks(user["id"])
        del_list = "\n".join(f"  🗑️ {b}" for b in deleted_bodies)
        await db.reset_session(user["id"])
        await line.reply(
            reply_token,
            f"🗑️ 削除しました。\n\n{del_list}\n\n残り {len(remaining)}件。",
        )


# ─── ユーティリティ ───────────────────────────────────────────────────────────

def _parse_numbers(text: str, max_n: int) -> list[int]:
    """「1 3 5」や「1,3,5」のような入力を整数リストに変換。"""
    import re
    tokens = re.split(r"[\s,、]+", text.strip())
    result = []
    for t in tokens:
        if t.isdigit():
            n = int(t)
            if 1 <= n <= max_n:
                result.append(n)
    return result
