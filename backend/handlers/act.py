"""
⑤ ACTジャーナリング ハンドラ

「第1弾の燃料（承認・獲得・拡大）」が効かなくなったとき、
「第2弾の燃料（どの方向へ、どんな態度で進むか＝価値）」に乗り換えるための
4ステップ・ジャーナル。詳細は docs/act_journaling.md を参照。

状態遷移:
  idle → act_prev（前回の1cmの行動の確認・未確認ログがある場合のみ）
       → act_accept  … ステップ1 アクセプタンス（今の状態を認める）
       → act_avoid   … ステップ2 体験の回避チェック（行動の動機を探る）
       → act_value   … ステップ3 価値の明確化（第2弾の燃料）
       → act_action  … ステップ4 コミット型アクション（1cmの行動）
       → act_confirm … タスク追加 / 取り消し
       → idle
"""
import logging
from backend.models import database as db
from backend.services import line_service as line
from backend.services import claude_service as claude

logger = logging.getLogger(__name__)

# ─── ボタン ───────────────────────────────────────────────────────────────────

PREV_LABELS = ["✅ やった", "🕒 まだ", "🔁 変えた"]

AVOID_LABELS = ["🛡️ 避けるため", "🧭 近づくため", "🤔 わからない"]
AVOID_KIND = {
    "🛡️ 避けるため":  "avoid",
    "🧭 近づくため":  "toward",
    "🤔 わからない":  "unknown",
}

# 価値の例（ソースの「誠実でありたい／好奇心を持ちたい／次世代に手渡したい／
# 自分を丁寧に扱いたい」より）。過去に選んだ価値があればそちらを優先して出す。
VALUE_SAMPLES = [
    "誠実でありたい",
    "好奇心を持ちたい",
    "次世代に手渡したい",
    "自分を丁寧に扱いたい",
]

ACTION_HELP_LABEL = "💡 思いつかない"
CONFIRM_LABELS = ["✅ タスクに追加", "✖️ しない", "↩️ 取り消す"]
UNDO_LABEL = "↩️ 取り消す"

# ─── ペルソナ別メッセージ ─────────────────────────────────────────────────────

_INTRO = {
    "yu":    "🧭 ACTジャーナル\n\n感情を消す時間じゃない。\n抱えたまま、どっちに進むかを決める時間だ。\n4つ聞く。順番に答えて。",
    "nagi":  "🧭 ACTジャーナル\n\nイヤな気持ちを消そうとしなくていいよ。\n持ったまま、どっちに進みたいかを一緒に見る時間😊\n4つ聞くね。",
    "mirai": "🧭 ACTジャーナル\n\n感情を消すためじゃなく、\n方向を確かめるための4つの問い。\nこの積み重ねが、後から効いてくる。",
}

_PREV_Q = {
    "yu":    "その前に。前回決めた1cmの行動、これだった。\n\n「{action}」\n\nどうなった？できてなくても問題ない。",
    "nagi":  "その前にちょっとだけ！\n前回の1cmの行動、これだったよ。\n\n「{action}」\n\nどうだった？できてなくても全然いいからね😊",
    "mirai": "その前に。前回のあなたが選んだ1cmの行動。\n\n「{action}」\n\nどうなった？できたかどうかは、実はそこまで重要じゃない。",
}

_PREV_ACK = {
    "✅ やった": {
        "yu":    "やったなら十分だ。方向は動いてる。",
        "nagi":  "やったんだ！その1cm、ちゃんと積まれてるよ😊",
        "mirai": "その1cmは、もう過去になって積み重なっている。",
    },
    "🕒 まだ": {
        "yu":    "まだならまだでいい。やらなかった理由は今は問わない。",
        "nagi":  "まだなんだね。それも記録のうちだから大丈夫😊",
        "mirai": "まだでいい。行動は、選び直せる場所にずっと置いてある。",
    },
    "🔁 変えた": {
        "yu":    "変えたなら、それも選択だ。",
        "nagi":  "変えたんだ。自分で選び直したってことだね！",
        "mirai": "変えたことも、方向を確かめた結果のひとつ。",
    },
}

_STEP1_Q = {
    "yu":    "【1/4】アクセプタンス\n\n今、心の中に何がある？\n名前のない不安、虚しさ、焦り、痛み。何でもいい。\n\n解決しなくていい。「〜と感じている」と実況するつもりで書いて。",
    "nagi":  "【1/4】アクセプタンス\n\n今、心の中にどんな気持ちがある？\nモヤモヤでも虚しさでも焦りでも、なんでもいいよ。\n\n消さなくていいから、「〜と感じてる」って書いてみて😊",
    "mirai": "【1/4】アクセプタンス\n\n今、心の中にどんな感情がある？\n名前のない不安、虚しさ、痛み。そのままでいい。\n\n「〜と感じている」と、観察するように書いてみて。",
}

_STEP2_Q = {
    "yu":    "【2/4】体験の回避チェック\n\n最近の行動は、避けたいもの（失敗・暇・無価値感）から離れるため？\nそれとも大切なものに近づくため？\n\nどっちに近い？言葉で書いてもいい。",
    "nagi":  "【2/4】体験の回避チェック\n\n最近の行動ってさ、避けたいもの（失敗とか暇とか無価値感とか）から離れるため？\nそれとも大切なものに近づくため？\n\nどっちに近いか選んでみて。言葉で書いてもOK！",
    "mirai": "【2/4】体験の回避チェック\n\n最近の行動は、何かから離れるためのもの？\nそれとも、何かに近づくためのもの？\n\nどちらに近いか選んで。言葉にしてもいい。",
}

_STEP3_Q = {
    "yu":    "【3/4】価値の明確化\n\n達成して終わる目標じゃなく、進み続ける方向の話だ。\n\n今、目の前の仕事や人との関わりに、どんな態度で向かいたい？",
    "nagi":  "【3/4】価値の明確化\n\n「何を手に入れるか」じゃなくて「どっちに向かうか」の話！\n\n今、目の前のことや人に、どんな態度で関わりたい？",
    "mirai": "【3/4】価値の明確化\n\n目標は達成したら終わる。価値は、進み続けられる方向。\n\n今、目の前のことに、どんな態度で関わりたい？",
}

_STEP4_Q = {
    "yu":    "【4/4】コミット型アクション\n\n「{value}」の方向に1cmだけ近づくとしたら、今日は何を選ぶ？\n\n小さいほどいい。完成させなくていい。",
    "nagi":  "【4/4】コミット型アクション\n\n「{value}」の方向に1cmだけ近づくとしたら、今日なにする？\n\n小さければ小さいほどいいよ。3割だけ手をつける、とかでも😊",
    "mirai": "【4/4】コミット型アクション\n\n「{value}」の方向に1cmだけ近づくとしたら、今この瞬間、何を選ぶ？\n\n大きな変化はいらない。小さいほど続く。",
}

_ACTION_SUGGEST_INTRO = {
    "yu":    "じゃあ候補を出す。この中から選んでも、これを見て自分で決めてもいい。",
    "nagi":  "じゃあ候補を出すね！この中から選んでも、見て思いついたのを書いてもいいよ😊",
    "mirai": "候補を置いておく。選んでも、これを手がかりに自分で決めてもいい。",
}

_TASK_Q = {
    "yu":    "この1cm、タスクに入れておく？",
    "nagi":  "この1cm、タスクに入れておく？😊",
    "mirai": "この1cm、タスクとして残しておく？",
}

_TASK_ADDED = {
    "yu":    "タスクに追加した。次に来たとき、どうなったか聞く。",
    "nagi":  "タスクに追加したよ📋 次に来たとき、どうなったか聞くね！",
    "mirai": "タスクとして残した。次に来たとき、結果を一緒に見よう。",
}

_CLOSE = {
    "yu":    "記録した。また方向を見失ったら来て。",
    "nagi":  "記録したよ😊 また迷ったらいつでも来てね！",
    "mirai": "記録した。この1cmが、後の自分の足場になる。",
}

_UNDO = {
    "yu":    "取り消した。",
    "nagi":  "取り消したよ😊 なかったことにしよう！",
    "mirai": "取り消した。また書きたくなったらいつでも。",
}

_ERROR = {
    "yu":    "保存でエラーが出た。もう一度「ACTジャーナル」から試して。",
    "nagi":  "保存でエラーが出ちゃった😢 もう一度「ACTジャーナル」から試してね🙏",
    "mirai": "保存中にエラーが発生した。もう一度「ACTジャーナル」から試して。",
}

_TOO_SHORT = {
    "yu":    "もう少しだけ言葉にしてみて。一言でいい。",
    "nagi":  "もうちょっとだけ言葉にしてみて！一言でいいから😊",
    "mirai": "もう少しだけ言葉にしてみて。短くていい。",
}


def _p(table: dict, persona: str) -> str:
    return table.get(persona, table["nagi"])


# ─── エントリーポイント ───────────────────────────────────────────────────────

async def start(reply_token: str, user: dict) -> None:
    persona = user.get("persona", "nagi")

    # 前回の1cmの行動が未確認なら、まずその結果から聞く
    pending = None
    try:
        pending = await db.get_pending_act_log(user["id"])
    except Exception:
        logger.exception("get_pending_act_log failed; skipping the follow-up step")

    if pending:
        await db.set_session(user["id"], "act_prev", {"prev_log_id": pending["id"]})
        msg = _p(_INTRO, persona) + "\n\n" + _p(_PREV_Q, persona).format(action=pending["action"])
        await line.reply(reply_token, msg, PREV_LABELS)
        return

    await db.set_session(user["id"], "act_accept", {})
    await line.reply(reply_token, _p(_INTRO, persona) + "\n\n" + _p(_STEP1_Q, persona))


async def handle(reply_token: str, user: dict, text: str, state: str, context: dict) -> None:
    persona = user.get("persona", "nagi")

    # ── 前回の1cmの行動の確認 ────────────────────────────────────────────────
    if state == "act_prev":
        prev_id = context.get("prev_log_id")
        done = 1 if text == "✅ やった" else 2
        if prev_id:
            try:
                await db.set_act_action_done(user["id"], prev_id, done)
                # これより古い未確認ログも蒸し返さないよう確認済みにする
                await db.clear_pending_act_logs(user["id"], prev_id)
            except Exception:
                logger.exception("failed to record previous ACT action result")

        ack_table = _PREV_ACK.get(text)
        ack = _p(ack_table, persona) if ack_table else _p(_PREV_ACK["🔁 変えた"], persona)

        await db.set_session(user["id"], "act_accept", {})
        await line.reply(reply_token, f"{ack}\n\n{_p(_STEP1_Q, persona)}")

    # ── ステップ1 アクセプタンス ─────────────────────────────────────────────
    elif state == "act_accept":
        if not text:
            await line.reply(reply_token, _p(_TOO_SHORT, persona))
            return
        context["acceptance"] = text
        await db.set_session(user["id"], "act_avoid", context)
        await line.reply(reply_token, _p(_STEP2_Q, persona), AVOID_LABELS)

    # ── ステップ2 体験の回避チェック ─────────────────────────────────────────
    elif state == "act_avoid":
        context["avoidance"] = text
        context["avoid_kind"] = AVOID_KIND.get(text, "unknown")
        await db.set_session(user["id"], "act_value", context)

        # 過去に選んだ価値を優先して提示（続けるほど自分の言葉に寄っていく）
        try:
            recent = await db.get_recent_act_values(user["id"], limit=2)
        except Exception:
            logger.exception("get_recent_act_values failed; falling back to samples")
            recent = []
        choices = recent + [v for v in VALUE_SAMPLES if v not in recent]
        await line.reply(reply_token, _p(_STEP3_Q, persona), choices[:4])

    # ── ステップ3 価値の明確化 ───────────────────────────────────────────────
    elif state == "act_value":
        if not text:
            await line.reply(reply_token, _p(_TOO_SHORT, persona))
            return
        context["value_text"] = text
        await db.set_session(user["id"], "act_action", context)
        await line.reply(
            reply_token,
            _p(_STEP4_Q, persona).format(value=text),
            [ACTION_HELP_LABEL],
        )

    # ── ステップ4 コミット型アクション ───────────────────────────────────────
    elif state == "act_action":
        # 「思いつかない」→ 価値の方向に沿った最小の行動を提案して選んでもらう
        if text == ACTION_HELP_LABEL:
            suggestions = await claude.suggest_act_actions(
                context.get("value_text", ""),
                context.get("acceptance", ""),
                persona,
            )
            listed = "\n".join(f"・{s}" for s in suggestions)
            await line.reply(
                reply_token,
                f"{_p(_ACTION_SUGGEST_INTRO, persona)}\n\n{listed}",
                suggestions,
            )
            return

        if not text:
            await line.reply(reply_token, _p(_TOO_SHORT, persona), [ACTION_HELP_LABEL])
            return

        context["action"] = text
        await _save_and_respond(reply_token, user, context)

    # ── タスク追加の確認 ─────────────────────────────────────────────────────
    elif state == "act_confirm":
        if text == UNDO_LABEL:
            entry_id = context.get("entry_id")
            log_id = context.get("log_id")
            if entry_id:
                await db.delete_entry_by_id(user["id"], entry_id)
            if log_id:
                await db.delete_act_log(user["id"], log_id)
            await db.reset_session(user["id"])
            await line.reply(reply_token, _p(_UNDO, persona))
        elif text == "✅ タスクに追加":
            action = context.get("action", "")
            if action:
                await db.create_tasks(user["id"], [action])
            await db.reset_session(user["id"])
            await line.reply(reply_token, _p(_TASK_ADDED, persona))
        else:
            await db.reset_session(user["id"])
            await line.reply(reply_token, _p(_CLOSE, persona))


# ─── 保存 & レスポンス ────────────────────────────────────────────────────────

def _format_body(context: dict) -> str:
    """振り返りレポートから読める形でエントリー本文を組み立てる。"""
    return (
        "[ACT] "
        f"感情「{context.get('acceptance', '')}」／ "
        f"動機「{context.get('avoidance', '')}」／ "
        f"価値「{context.get('value_text', '')}」／ "
        f"1cmの行動「{context.get('action', '')}」"
    )


async def _save_and_respond(reply_token: str, user: dict, context: dict) -> None:
    persona = user.get("persona", "nagi")

    try:
        # ① 振り返りレポート用のエントリー
        entry_id = await db.create_entry(
            user_id=user["id"],
            body=_format_body(context),
            entry_type="act",
        )
        # ② 構造化ログ（価値の推移・1cmの行動の実行状況を追える形で）
        log_id = await db.create_act_log(
            user_id=user["id"],
            acceptance=context.get("acceptance", ""),
            avoidance=context.get("avoidance", ""),
            value_text=context.get("value_text", ""),
            action=context.get("action", ""),
            entry_id=entry_id,
        )
    except Exception:
        logger.exception("failed to save ACT journal")
        await db.reset_session(user["id"])
        await line.reply(reply_token, _p(_ERROR, persona))
        return

    saved_msg = (
        "✅ 記録しました\n"
        "────────────────\n"
        f"1️⃣ 感情：{context.get('acceptance', '')}\n"
        f"2️⃣ 動機：{context.get('avoidance', '')}\n"
        f"3️⃣ 価値：{context.get('value_text', '')}\n"
        f"4️⃣ 1cm：{context.get('action', '')}\n"
        "────────────────"
    )

    try:
        comment = await claude.analyze_act_journal(context, persona)
    except Exception:
        logger.exception("analyze_act_journal failed; sending the record without a comment")
        comment = ""

    body = f"{saved_msg}\n\n{comment}".strip()

    await db.set_session(
        user["id"],
        "act_confirm",
        {"entry_id": entry_id, "log_id": log_id, "action": context.get("action", "")},
    )
    await line.reply(reply_token, f"{body}\n\n{_p(_TASK_Q, persona)}", CONFIRM_LABELS)
