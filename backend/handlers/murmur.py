"""
① つぶやきハンドラ
状態遷移:
  idle → murmur_location → murmur_weather → murmur_text（お題提示）
                                           → murmur_score（夜間のみ）
                                           → murmur_followup → idle
"""
import re
import random
from datetime import datetime
from backend.models import database as db
from backend.services import line_service as line
from backend.services import claude_service as claude

LOCATION_LABELS = ["🏠 自宅", "🏢 職場", "☕ カフェ", "🚃 移動中", "📍 その他"]
WEATHER_LABELS = ["☀️ 晴れ", "☁️ 曇り", "☔ 雨", "🌀 低気圧"]
SCORE_LABELS = ["20", "30", "40", "50", "60", "70", "80", "90", "100"]

# ─── ペルソナ別メッセージ ─────────────────────────────────────────────────────

_WEATHER_Q = {
    "yu":    "今日の天気は？",
    "nagi":  "天気はどうだった？☀️",
    "mirai": "今日の空の様子を教えて。",
}

_TOPIC_INTRO = {
    "yu":    "今日のお題：\n「{topic}」\n\n気持ちや出来事、自由に書いて。{note}",
    "nagi":  "今日はこれについて話してほしいな💡\n「{topic}」\n\nなんでもいいよ、自由に😊",
    "mirai": "今日の記録テーマ：\n「{topic}」\n\n書き残しておこう。{note}",
}

_SCORE_Q = {
    "yu":    "今日は何点？（20〜100）\n正直な数字を出してみて。",
    "nagi":  "今日って何点くらいだった？（20〜100）\n直感でいいよ！",
    "mirai": "今日の点数を残しておこう。（20〜100）\nその数字が後で意味を持つかも。",
}

_SELECT_PLEASE = {
    "yu":    "ボタンから選んで。",
    "nagi":  "ボタンで選んでね😊",
    "mirai": "ボタンから選んでください。",
}

_TASK_ADDED = {
    "yu":    "タスクリストに追加した。",
    "nagi":  "タスクリストに追加したよ📋",
    "mirai": "タスクとして記録した。未来の自分が確認するよ。",
}

_TASK_SKIP = {
    "yu":    "了解。また何かあれば。",
    "nagi":  "了解😊 またいつでも話しかけてね！",
    "mirai": "了解。また来てね。",
}

TASK_PATTERN = re.compile(r"[□\[\s]*(?:todo|TODO)[^\n]*|□\s*[^\n]+", re.IGNORECASE)


# ─── 時間帯 ───────────────────────────────────────────────────────────────────

def _is_night() -> bool:
    hour = datetime.now().hour
    return hour >= 18 or hour < 5


def _time_of_day() -> str:
    hour = datetime.now().hour
    if hour >= 18 or hour < 5:
        return "night"
    elif hour < 11:
        return "morning"
    else:
        return "afternoon"


# ─── ペルソナ別挨拶 ───────────────────────────────────────────────────────────

def _greeting(persona: str) -> str:
    tod = _time_of_day()
    if persona == "yu":
        msgs = {
            "night":     "おつかれ。今日どんな感じだった？\n\nまず今いる場所を教えて。",
            "morning":   "おはよう。今日どんな1日にする？\n\nまず今いる場所を教えて。",
            "afternoon": "よ。今どんな感じ？\n\nまず今いる場所を教えて。",
        }
    elif persona == "mirai":
        msgs = {
            "night":     "今日も来てくれたね🌙\n今日の記録、未来の自分が見るかもしれない。\n\nまず今いる場所から教えてもらえる？",
            "morning":   "今日という1日が始まったね☀️\n今日の自分の記録、残していこう。\n\nまず今いる場所から教えてもらえる？",
            "afternoon": "今日も来てくれたね🌤️\n\nまず今いる場所から教えてもらえる？",
        }
    else:  # nagi（デフォルト）
        msgs = {
            "night":     "おつかれー！今日もよく頑張ったね🌙\n\nまず、今どこにいるの？",
            "morning":   "おはよう☀️ 今日も始まりだね！\n\nまず、今どこにいるの？",
            "afternoon": "こんにちは🌤️ どんな感じ？\n\nまず、今どこにいるの？",
        }
    return msgs[tod]


# ─── つぶやきお題 ──────────────────────────────────────────────────────────────

_TOPIC_POOL = [
    "今日いちばん気になったことは？",
    "最近、ちょっと変わったと思うことはある？",
    "最近モヤっとしていることはある？",
    "今の自分に点数をつけるなら何点？その理由は？",
    "最近、誰かに感謝したことは？",
    "やりたいけど、まだやっていないことは？",
    "最近、ふと思い出したことは？",
    "今週、自分を一言で表すなら？",
    "最近うまくいっていることは？",
    "いま一番頭にあることを、一言で言うと？",
    "最近、誰かの言葉が刺さったことはある？",
    "今日、いちばん使ったエネルギーは何に？",
    "最近、直感が当たったと思う場面はあった？",
    "今日の自分に一言声をかけるなら？",
]

_DAY_TOPICS: dict[tuple[int, str], str] = {
    (0, "morning"):   "今週はどんな1週間にしたいですか？",
    (0, "afternoon"): "週のはじまり、調子はどうですか？",
    (2, "afternoon"): "今週の折り返し、ここまでどうですか？",
    (4, "afternoon"): "今週を振り返って、ひとことは？",
    (4, "night"):     "今週を振り返って、ひとことは？",
    (6, "afternoon"): "先週、自分の中で何か変わったことはありますか？",
    (6, "night"):     "来週に向けて、ひとつ決めるとしたら？",
}


def _strip_label(label: str) -> str:
    parts = label.split(" ", 1)
    return parts[1] if len(parts) > 1 else label


async def _get_topic(user_id: str, current_location: str, current_weather: str) -> str:
    """
    Tier 1. 前回（別日）スコアが低い（≤60）
    Tier 2. 別日エントリーと場所 or 天気が一致（自宅・同日はスキップ）
    Tier 3. 曜日・時間帯
    Tier 4. ランダムプール

    ※ 同日エントリーは「当たり前」なので比較対象にしない
    """
    last = await db.get_last_entries(user_id, limit=5)
    today_str = datetime.now().strftime("%Y-%m-%d")

    # 今日以外の直近エントリーだけ比較対象にする
    prev_entries = [e for e in last if e.get("created_at", "")[:10] != today_str]

    # Tier 1: 前回（別日）スコアが低かった
    if prev_entries and prev_entries[0].get("score") is not None and prev_entries[0]["score"] <= 60:
        score = prev_entries[0]["score"]
        return f"前回{score}点だったけど、今はどんな感じ？"

    # Tier 2: 別日と場所・天気が一致
    if prev_entries:
        prev = prev_entries[0]
        prev_loc     = prev.get("location", "")
        prev_weather = prev.get("weather", "")

        if current_location and current_location == prev_loc and current_location != "🏠 自宅":
            name = _strip_label(current_location)
            return f"{name}が続いていますね。前回からの気持ちの変化はありますか？"

        if current_weather and current_weather == prev_weather:
            name = _strip_label(current_weather)
            return f"{name}が続いていますね。気分に変化はありますか？"

    # Tier 3: 曜日・時間帯
    day_topic = _DAY_TOPICS.get((datetime.now().weekday(), _time_of_day()))
    if day_topic:
        return day_topic

    # Tier 4: ランダム
    return random.choice(_TOPIC_POOL)


# ─── タスク抽出 ───────────────────────────────────────────────────────────────

def _extract_task_candidates(text: str) -> list[str]:
    candidates = []
    for line_text in text.splitlines():
        stripped = line_text.strip()
        if re.search(r"□|(?:todo)", stripped, re.IGNORECASE):
            clean = re.sub(r"^[□\s]+|(?:todo\s*[:：]?\s*)", "", stripped, flags=re.IGNORECASE).strip()
            if clean:
                candidates.append(clean)
    return candidates


# ─── エントリーポイント ───────────────────────────────────────────────────────

async def start(reply_token: str, user: dict) -> None:
    persona = user.get("persona", "nagi")
    await db.set_session(user["id"], "murmur_location")
    await line.reply(reply_token, _greeting(persona), LOCATION_LABELS)


async def handle(reply_token: str, user: dict, text: str, state: str, context: dict) -> None:
    persona = user.get("persona", "nagi")

    # ── 場所選択 ─────────────────────────────────────────────────────────────
    if state == "murmur_location":
        if text not in LOCATION_LABELS:
            await line.reply(reply_token, "ボタンから選んでください 🙏", LOCATION_LABELS)
            return
        context["location"] = text
        await db.set_session(user["id"], "murmur_weather", context)
        await line.reply(reply_token, _WEATHER_Q.get(persona, _WEATHER_Q["nagi"]), WEATHER_LABELS)

    # ── 天気選択 → お題提示 ───────────────────────────────────────────────────
    elif state == "murmur_weather":
        if text not in WEATHER_LABELS:
            await line.reply(reply_token, "ボタンから選んでください 🙏", WEATHER_LABELS)
            return
        context["weather"] = text
        await db.set_session(user["id"], "murmur_text", context)

        topic = await _get_topic(
            user["id"],
            context.get("location", ""),
            context.get("weather", ""),
        )
        note = "（気にせず自由に書いてもOK！）" if persona == "nagi" else "（自由に書いてもOK）"
        tmpl = _TOPIC_INTRO.get(persona, _TOPIC_INTRO["nagi"])
        await line.reply(reply_token, tmpl.format(topic=topic, note=note))

    # ── テキスト入力 ──────────────────────────────────────────────────────────
    elif state == "murmur_text":
        context["body"] = text
        if _is_night():
            await db.set_session(user["id"], "murmur_score", context)
            await line.reply(reply_token, _SCORE_Q.get(persona, _SCORE_Q["nagi"]), SCORE_LABELS)
        else:
            await _save_and_respond(reply_token, user, context)

    # ── 点数選択（夜間） ──────────────────────────────────────────────────────
    elif state == "murmur_score":
        if text not in SCORE_LABELS:
            await line.reply(reply_token, "ボタンから選んでください 🙏", SCORE_LABELS)
            return
        context["score"] = int(text)
        await _save_and_respond(reply_token, user, context)

    # ── フォローアップ ────────────────────────────────────────────────────────
    elif state == "murmur_followup":
        if text == "↩️ 取り消す":
            entry_id = context.get("last_entry_id")
            if entry_id:
                await db.delete_entry_by_id(user["id"], entry_id)
            await db.reset_session(user["id"])
            _UNDO_MSG = {
                "yu":    "取り消した。",
                "nagi":  "取り消したよ😊 なかったことにしよう！",
                "mirai": "取り消した。また書きたくなったらいつでも。",
            }
            await line.reply(reply_token, _UNDO_MSG.get(persona, _UNDO_MSG["nagi"]))
            return
        original_body = context.get("original_body", "")
        ai_reply = await claude.analyze_followup_response(original_body, text, persona)
        await db.reset_session(user["id"])
        close_word = {
            "nagi":  "またいつでも話しかけてね 😊",
            "yu":    "また何かあれば。",
            "mirai": "今日も記録できたね。また来てね。",
        }.get(persona, "またいつでも 📝")
        await line.reply(reply_token, f"{ai_reply}\n\n{close_word}")

    # ── タスク検知の確認 ──────────────────────────────────────────────────────
    elif state == "murmur_task_confirm":
        candidates = context.get("task_candidates", [])
        if text == "↩️ 取り消す":
            entry_id = context.get("last_entry_id")
            if entry_id:
                await db.delete_entry_by_id(user["id"], entry_id)
            await db.reset_session(user["id"])
            _UNDO_MSG = {
                "yu":    "取り消した。",
                "nagi":  "取り消したよ😊 なかったことにしよう！",
                "mirai": "取り消した。また書きたくなったらいつでも。",
            }
            await line.reply(reply_token, _UNDO_MSG.get(persona, _UNDO_MSG["nagi"]))
        elif text == "✅ 追加する":
            await db.create_tasks(user["id"], candidates)
            await db.reset_session(user["id"])
            await line.reply(reply_token, _TASK_ADDED.get(persona, _TASK_ADDED["nagi"]))
        else:
            await db.reset_session(user["id"])
            await line.reply(reply_token, _TASK_SKIP.get(persona, _TASK_SKIP["nagi"]))


# ─── 保存 & レスポンス ────────────────────────────────────────────────────────

async def _save_and_respond(reply_token: str, user: dict, context: dict) -> None:
    persona = user.get("persona", "nagi")

    entry_id = await db.create_entry(
        user_id=user["id"],
        body=context.get("body", ""),
        location=context.get("location"),
        weather=context.get("weather"),
        score=context.get("score"),
        score_reason=context.get("score_reason"),
    )

    now = datetime.now().strftime("%m/%d %H:%M")
    body = context.get("body", "")
    location = context.get("location", "")
    weather = context.get("weather", "")
    score = context.get("score")

    saved_msg = (
        f"✅ 保存しました（{now}）\n\n"
        f"────────────────\n"
        f"📌 つぶやき\n「{body}」\n"
        f"📍 {location} ／ {weather}"
    )
    if score is not None:
        saved_msg += f" ／ 🌡️ {score}点"
    saved_msg += "\n────────────────"

    ai_comment = await claude.analyze_murmur_response(body, persona)

    candidates = _extract_task_candidates(body)
    if candidates:
        candidate_text = "\n".join(f"  ・{c}" for c in candidates)
        task_prompt = (
            f"{saved_msg}\n\n{ai_comment}\n\n"
            f"💡 タスクっぽい項目を見つけました！\n\n{candidate_text}\n\n"
            f"タスクリストに追加しますか？"
        )
        await db.set_session(user["id"], "murmur_task_confirm", {"task_candidates": candidates, "last_entry_id": entry_id})
        await line.reply(reply_token, task_prompt, ["✅ 追加する", "✖️ しない", "↩️ 取り消す"])
    else:
        await db.set_session(user["id"], "murmur_followup", {"original_body": body, "last_entry_id": entry_id})
        await line.reply(reply_token, f"{saved_msg}\n\n{ai_comment}", ["↩️ 取り消す"])
