"""
④ 設定ハンドラ
状態遷移: idle → settings_menu → settings_persona → idle
                               → profile_purpose（profile ハンドラへ）
"""
from backend.models import database as db
from backend.services import line_service as line

PERSONA_LABELS = [
    "🧠 ユウ（整理・助言）",
    "☕ ナギ（傾聴・深掘り）",
    "🔮 ミライ（振り返り・成長）",
]

PERSONA_MAP = {
    "🧠 ユウ（整理・助言）":    "yu",
    "☕ ナギ（傾聴・深掘り）":   "nagi",
    "🔮 ミライ（振り返り・成長）": "mirai",
}

PERSONA_NAME = {"yu": "ユウ", "nagi": "ナギ", "mirai": "ミライ"}

PERSONA_GREETING = {
    "yu":    "ユウに変更したよ。何でも言って、整理するから。",
    "nagi":  "ナギになったよ。なんでも聞かせてね！",
    "mirai": "ミライになったよ。未来の自分の視点で一緒に考えよう。",
}

MENU_LABELS = ["🤝 話す相手を変える", "📋 プロフィール生成"]


async def start(reply_token: str, user: dict) -> None:
    await db.set_session(user["id"], "settings_menu")
    current = PERSONA_NAME.get(user.get("persona", "nagi"), "ナギ")
    await line.reply(
        reply_token,
        f"⚙️ 設定メニュー\n（現在の相棒：{current}）\n\n▼ なにをしますか？",
        MENU_LABELS,
    )


async def handle(reply_token: str, user: dict, text: str, state: str, context: dict) -> None:

    # ── トップメニュー ────────────────────────────────────────────────────────
    if state == "settings_menu":
        if text == "🤝 話す相手を変える":
            current = PERSONA_NAME.get(user.get("persona", "nagi"), "ナギ")
            await db.set_session(user["id"], "settings_persona")
            await line.reply(
                reply_token,
                f"▼ 話す相手を選んでください\n（現在：{current}）",
                PERSONA_LABELS,
            )
        elif text == "📋 プロフィール生成":
            from backend.handlers import profile as profile_handler
            await profile_handler.start(reply_token, user)
        else:
            await line.reply(reply_token, "ボタンから選んでください 🙏", MENU_LABELS)

    # ── ペルソナ選択 ──────────────────────────────────────────────────────────
    elif state == "settings_persona":
        if text not in PERSONA_LABELS:
            await line.reply(reply_token, "ボタンから選んでください 🙏", PERSONA_LABELS)
            return
        new_persona = PERSONA_MAP[text]
        await db.update_persona(user["id"], new_persona)
        await db.reset_session(user["id"])
        # リッチメニューを切り替え
        await line.set_persona_rich_menu(user["id"], new_persona)
        greeting = PERSONA_GREETING.get(new_persona, "相棒を変更したよ！")
        await line.reply(reply_token, f"✅ {greeting}")

    # ── オンボーディング：初回ペルソナ選択 ────────────────────────────────────
    elif state == "onboarding_persona":
        if text not in PERSONA_LABELS:
            await line.reply(reply_token, "ボタンから選んでください 🙏", PERSONA_LABELS)
            return
        new_persona = PERSONA_MAP[text]
        await db.update_persona(user["id"], new_persona)
        await db.reset_session(user["id"])
        await line.set_persona_rich_menu(user["id"], new_persona)
        name = PERSONA_NAME[new_persona]
        _ONBOARD_MSG = {
            "yu": f"ユウだ。よろしく。\n\n「つぶやく」は何でもいい。\n今日あったこと、思ったこと、モヤモヤ、なんでも。\n書いたら俺なりに返す。\n\n「相談する」はひっかかることを一緒に整理したいとき。\nまず気軽に話しかけてみて。",
            "nagi": f"ナギだよ、よろしく！😊\n\n「つぶやく」はなんでもいいからね！\n「今日疲れた」でも「なんかもやもや」でも全然OK。\n書いてくれたら読んで返すよ。\n\n「相談する」は誰かに話したいことがあるとき。\nまず話しかけてみて！",
            "mirai": f"ミライだよ。よろしく。\n\n「つぶやく」は些細なことでいい。\n今日感じたこと、気になったこと、なんでも。\n積み重なると未来が変わる。\n\n「相談する」は頭の中がぐるぐるしているとき。\nまず話してみて。",
        }
        await line.reply(reply_token, _ONBOARD_MSG.get(new_persona, _ONBOARD_MSG["nagi"]))
