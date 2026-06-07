"""
② タスク整理ハンドラ
状態遷移: idle → task_action → task_add_input → task_add_confirm → idle
                             → task_complete_input → idle
                             → task_delete_input  → idle
"""
from backend.models import database as db
from backend.services import line_service as line

ACTION_LABELS = ["➕ タスクを追加", "✅ 完了にする", "🗑️ 削除する"]

# ─── ペルソナ別メッセージ ─────────────────────────────────────────────────────

_NO_TASKS = {
    "yu":    "未完了タスクはゼロ。いい状態だよ。",
    "nagi":  "タスクは何もないよ🎉 すっきりしてるね！",
    "mirai": "タスクゼロ。今この瞬間、身軽でいられてる。",
}

_ADD_PROMPT = {
    "yu":    "何を追加する？\n改行で複数いける。\n例）\n  資料まとめる\n  Aさんに返信",
    "nagi":  "何を追加したい？😊\n複数あれば改行して入力してね。\n例）\n  資料まとめる\n  Aさんに返信",
    "mirai": "タスクを入力して。\n改行で複数追加できる。\n例）\n  資料まとめる\n  Aさんに返信",
}

_ADDED_MSG = {
    "yu":    "追加した。",
    "nagi":  "追加したよ📋",
    "mirai": "記録した。ひとつずつ、着実に。",
}

_DONE_MSG = {
    "yu":    "完了。着実に前進してる。",
    "nagi":  "やったね！お疲れ様💪",
    "mirai": "完了。未来の自分が感謝するよ。",
}

_DELETED_MSG = {
    "yu":    "削除した。",
    "nagi":  "消したよ🗑️",
    "mirai": "手放した。それも大事な決断だよ。",
}

_CANCEL_MSG = {
    "yu":    "キャンセルした。",
    "nagi":  "キャンセルしたよ😊",
    "mirai": "キャンセル。またいつでも。",
}

_NO_COMPLETE = {
    "yu":    "完了できるタスクがない。",
    "nagi":  "完了できるタスクがないよ😊",
    "mirai": "完了できるタスクはまだない。",
}

_NO_DELETE = {
    "yu":    "削除できるタスクがない。",
    "nagi":  "削除できるタスクがないよ😊",
    "mirai": "削除できるタスクはまだない。",
}

_INVALID_NUM = {
    "yu":    "有効な番号を入れて（例：1 3）",
    "nagi":  "番号で答えてね（例：1 3）",
    "mirai": "有効な番号を入力して（例：1 3）",
}

_REDO_INPUT = {
    "yu":    "もう一度入力して。（改行で複数OK）",
    "nagi":  "もう一度書いてね😊（改行で複数OK）",
    "mirai": "もう一度入力して。（改行で複数OK）",
}


def _format_task_list(tasks: list[dict]) -> str:
    if not tasks:
        return "現在、未完了のタスクはありません 🎉"
    lines = [f"{i + 1}️⃣ {t['body']}" for i, t in enumerate(tasks)]
    return "\n".join(lines)


# ─── エントリーポイント ───────────────────────────────────────────────────────

async def start(reply_token: str, user: dict) -> None:
    """リッチメニュー「タスク整理」タップ時。"""
    persona = user.get("persona", "nagi")
    tasks = await db.get_todo_tasks(user["id"])
    count = len(tasks)

    if count == 0:
        no_task = _NO_TASKS.get(persona, _NO_TASKS["nagi"])
        header = f"📋 タスクリスト\n────────────────\n{no_task}\n────────────────"
    else:
        task_lines = _format_task_list(tasks)
        header = (
            f"📋 タスクリスト\n────────────────\n"
            f"{task_lines}\n────────────────\n"
            f"{count}件 未完了"
        )

    await db.set_session(user["id"], "task_action", {"tasks": [t["id"] for t in tasks]})
    await line.reply(reply_token, header, ACTION_LABELS)


async def handle(reply_token: str, user: dict, text: str, state: str, context: dict) -> None:
    """タスク関連の状態を処理する。"""
    persona = user.get("persona", "nagi")

    # ── 操作選択 ─────────────────────────────────────────────────────────────
    if state == "task_action":
        if text == "➕ タスクを追加":
            await db.set_session(user["id"], "task_add_input", context)
            await line.reply(reply_token, _ADD_PROMPT.get(persona, _ADD_PROMPT["nagi"]))

        elif text == "✅ 完了にする":
            tasks = await db.get_todo_tasks(user["id"])
            if not tasks:
                await db.reset_session(user["id"])
                await line.reply(reply_token, _NO_COMPLETE.get(persona, _NO_COMPLETE["nagi"]))
                return
            task_lines = _format_task_list(tasks)
            await db.set_session(user["id"], "task_complete_input", {"tasks": [t["id"] for t in tasks]})
            await line.reply(reply_token, f"どれを完了にする？\n番号で教えて（複数はスペース区切り）。\n\n{task_lines}")

        elif text == "🗑️ 削除する":
            tasks = await db.get_todo_tasks(user["id"])
            if not tasks:
                await db.reset_session(user["id"])
                await line.reply(reply_token, _NO_DELETE.get(persona, _NO_DELETE["nagi"]))
                return
            task_lines = _format_task_list(tasks)
            await db.set_session(user["id"], "task_delete_input", {"tasks": [t["id"] for t in tasks]})
            await line.reply(reply_token, f"どれを削除する？\n番号で教えて（複数はスペース区切り）。\n\n{task_lines}")

        else:
            await line.reply(reply_token, "ボタンから選んでね。", ACTION_LABELS)

    # ── タスク追加入力 ────────────────────────────────────────────────────────
    elif state == "task_add_input":
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        if not lines:
            await line.reply(reply_token, "タスクの内容を入力してください。")
            return
        context["pending_tasks"] = lines
        await db.set_session(user["id"], "task_add_confirm", context)
        bullet = "\n".join(f"  ・{l}" for l in lines)
        await line.reply(reply_token, f"これを追加する？\n\n{bullet}", ["✅ 追加する", "✏️ 修正する", "✖️ キャンセル"])

    # ── タスク追加確認 ────────────────────────────────────────────────────────
    elif state == "task_add_confirm":
        pending = context.get("pending_tasks", [])
        if text == "✅ 追加する":
            await db.create_tasks(user["id"], pending)
            await db.reset_session(user["id"])
            total = await db.get_todo_tasks(user["id"])
            msg = _ADDED_MSG.get(persona, _ADDED_MSG["nagi"])
            await line.reply_with_sticker(reply_token, f"📋 {len(pending)}件{msg}\n\n未完了：{len(total)}件", persona)
        elif text == "✏️ 修正する":
            await db.set_session(user["id"], "task_add_input", {})
            await line.reply(reply_token, _REDO_INPUT.get(persona, _REDO_INPUT["nagi"]))
        else:
            await db.reset_session(user["id"])
            await line.reply(reply_token, _CANCEL_MSG.get(persona, _CANCEL_MSG["nagi"]))

    # ── 完了番号入力 ──────────────────────────────────────────────────────────
    elif state == "task_complete_input":
        task_ids = context.get("tasks", [])
        selected = _parse_numbers(text, len(task_ids))
        if not selected:
            await line.reply(reply_token, _INVALID_NUM.get(persona, _INVALID_NUM["nagi"]))
            return
        target_ids = [task_ids[i - 1] for i in selected if 1 <= i <= len(task_ids)]
        done_bodies = await db.complete_tasks(user["id"], target_ids)
        remaining = await db.get_todo_tasks(user["id"])
        done_list = "\n".join(f"  ✔ {b}" for b in done_bodies)
        done_msg = _DONE_MSG.get(persona, _DONE_MSG["nagi"])
        await db.reset_session(user["id"])
        await line.reply_with_sticker(reply_token, f"✅ {done_list}\n\n{done_msg}\n残り {len(remaining)}件。", persona)

    # ── 削除番号入力 ──────────────────────────────────────────────────────────
    elif state == "task_delete_input":
        task_ids = context.get("tasks", [])
        selected = _parse_numbers(text, len(task_ids))
        if not selected:
            await line.reply(reply_token, _INVALID_NUM.get(persona, _INVALID_NUM["nagi"]))
            return
        target_ids = [task_ids[i - 1] for i in selected if 1 <= i <= len(task_ids)]
        deleted_bodies = await db.delete_tasks(user["id"], target_ids)
        remaining = await db.get_todo_tasks(user["id"])
        del_list = "\n".join(f"  🗑️ {b}" for b in deleted_bodies)
        del_msg = _DELETED_MSG.get(persona, _DELETED_MSG["nagi"])
        await db.reset_session(user["id"])
        await line.reply(reply_token, f"{del_list}\n\n{del_msg} 残り {len(remaining)}件。")


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
