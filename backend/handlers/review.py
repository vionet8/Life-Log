"""
③ 振り返りハンドラ
状態遷移: idle → review_period → review_generating → review_feedback → idle
                                  ↑ バックグラウンドでClause生成、完了後 push
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from backend.models import database as db
from backend.services import line_service as line
from backend.services import claude_service as claude

logger = logging.getLogger(__name__)

PERIOD_LABELS = ["📅 過去7日", "📆 過去1ヶ月", "🗓️ 過去3ヶ月"]
FEEDBACK_LABELS = ["👍 OK", "✏️ 修正したい"]

# ─── ペルソナ別メッセージ ─────────────────────────────────────────────────────

_PERIOD_PROMPT = {
    "yu":    "どの期間で振り返る？",
    "nagi":  "どの期間で振り返る？😊",
    "mirai": "振り返る期間を選んで。",
}

_THINKING = {
    "yu":    "{period_ja}のレポートを作ってる。\nちょっと待って。",
    "nagi":  "{period_ja}のレポートを作ってるよ 📊\nもうちょっと待っててね！",
    "mirai": "{period_ja}のレポートを生成中。\nしばらくそのままでいて。",
}

_WAIT = {
    "yu":    "まだ作ってる。\nできたらすぐ送る。",
    "nagi":  "まだ作ってるとこ😊\nできたらすぐ送るね！",
    "mirai": "生成中。\n完成したら届けるよ。",
}

_CLOSE_OK = {
    "yu":    "よし。また振り返りたいときはいつでも。",
    "nagi":  "よかった！またいつでも振り返ろうね 📊",
    "mirai": "記録に向き合えたね。また来てね。",
}

_CORRECTION_PROMPT = {
    "yu":    "どこが違った？具体的に教えて。",
    "nagi":  "どのあたりが違った？教えてね😊",
    "mirai": "どこが気になった？フィードバックをどうぞ。",
}

_CORRECTION_DONE = {
    "yu":    "了解。「{text}」ね。\n次回に活かす。",
    "nagi":  "ありがとう！「{text}」ね😊\n次のレポートに活かすよ！",
    "mirai": "「{text}」、受け取った。\n次の記録に反映するよ。",
}

_FEEDBACK_AGAIN = {
    "yu":    "レポートの確認をして。",
    "nagi":  "レポートの確認をお願いします🙏",
    "mirai": "レポートを確認して、ボタンで教えて。",
}

_ERROR = {
    "yu":    "レポート生成でエラーが出た。\nもう一度「振り返り」から試して。",
    "nagi":  "レポートの生成でエラーが出ちゃった😢\nもう一度「振り返り」から試してね🙏",
    "mirai": "生成中にエラーが発生した。\n「振り返り」からもう一度試して。",
}


_JST = timezone(timedelta(hours=9))


def _period_since(label: str) -> tuple[str, str]:
    """(since_date_str, period_label_ja) を返す。"""
    today = datetime.now(_JST)
    if label == "📅 過去7日":
        since = today - timedelta(days=7)
        return since.strftime("%Y-%m-%d"), f"過去7日間（{since.strftime('%m/%d')}〜{today.strftime('%m/%d')}）"
    elif label == "📆 過去1ヶ月":
        since = today - timedelta(days=30)
        return since.strftime("%Y-%m-%d"), f"過去1ヶ月（{since.strftime('%m/%d')}〜{today.strftime('%m/%d')}）"
    elif label == "🗓️ 過去3ヶ月":
        since = today - timedelta(days=90)
        return since.strftime("%Y-%m-%d"), f"過去3ヶ月（{since.strftime('%m/%d')}〜{today.strftime('%m/%d')}）"
    return None, "全期間"


# ─── バックグラウンド生成タスク ───────────────────────────────────────────────

async def _generate_and_deliver(
    user: dict,
    period_text: str,
    period_ja: str,
    entries: list,
) -> None:
    """
    Claude でレポートを生成し push で届ける。
    webhook とは独立して動作するため、生成中にユーザーが別操作をしても干渉しない。

    完了時のセッション状態を確認：
    - review_generating のまま → feedback 状態に移してボタン付きで push
    - 他の操作に移っている   → セッションを変えず、レポートだけ push（ボタンなし）
    """
    try:
        report = await claude.generate_review(
            period_label=f"{period_ja}（{len(entries)}件の記録）",
            entries=entries,
            persona=user.get("persona", "nagi"),
        )

        # 完了時点のセッションを確認
        session = await db.get_session(user["id"])

        if session["state"] == "review_generating":
            # 待機中のまま → 通常の feedback フローへ
            await db.set_session(user["id"], "review_feedback", {"period": period_text})
            await line.push(
                user["id"],
                f"📊 {period_ja} レポート\n════════════════════════════\n\n{report}",
                FEEDBACK_LABELS,
            )
        else:
            # 生成中に別の操作へ移った → セッションを壊さずレポートだけ届ける
            note = "（生成中に別の操作をされたため、確認ボタンは省略しています）"
            await line.push(
                user["id"],
                f"📊 {period_ja} レポート\n════════════════════════════\n\n{report}\n\n{note}",
            )

    except Exception as e:
        logger.error(f"Review generation failed for user {user['id']}: {e}", exc_info=True)
        # セッションが review_generating なら idle に戻す
        session = await db.get_session(user["id"])
        if session["state"] == "review_generating":
            await db.reset_session(user["id"])
        persona = user.get("persona", "nagi")
        await line.push(
            user["id"],
            _ERROR.get(persona, _ERROR["nagi"]),
        )


# ─── エントリーポイント ───────────────────────────────────────────────────────

async def start(reply_token: str, user: dict) -> None:
    """リッチメニュー「振り返り」タップ時。"""
    persona = user.get("persona", "nagi")
    await db.set_session(user["id"], "review_period")
    await line.reply(reply_token, _PERIOD_PROMPT.get(persona, _PERIOD_PROMPT["nagi"]), PERIOD_LABELS)


async def handle(reply_token: str, user: dict, text: str, state: str, context: dict) -> None:

    # ── 期間選択 ─────────────────────────────────────────────────────────────
    if state == "review_period":
        if text not in PERIOD_LABELS:
            await line.reply(reply_token, "ボタンから選んでください 🙏", PERIOD_LABELS)
            return

        persona = user.get("persona", "nagi")
        since, period_ja = _period_since(text)

        try:
            entries = await db.get_entries(user["id"], since=since)
        except Exception as e:
            logger.error(f"get_entries failed for user {user['id']}: {e}", exc_info=True)
            await db.reset_session(user["id"])
            await line.reply(reply_token, _ERROR.get(persona, _ERROR["nagi"]))
            return

        thinking_msg = _THINKING.get(persona, _THINKING["nagi"]).format(period_ja=period_ja)

        # ① セッションを generating に移して即座に返信
        await db.set_session(user["id"], "review_generating", {"period": text, "period_ja": period_ja})
        await line.reply(reply_token, thinking_msg)

        # ② バックグラウンドでレポート生成・配信（ここで return、webhook は解放される）
        asyncio.create_task(_generate_and_deliver(user, text, period_ja, entries))

    # ── 生成中（Claude 処理待ち） ─────────────────────────────────────────────
    elif state == "review_generating":
        # 生成中に別テキストが来た場合は待機を案内（メッセージは保持しない）
        persona = user.get("persona", "nagi")
        await line.reply(reply_token, _WAIT.get(persona, _WAIT["nagi"]))

    # ── フィードバック ────────────────────────────────────────────────────────
    elif state == "review_feedback":
        persona = user.get("persona", "nagi")
        if text == "✏️ 修正したい":
            await db.set_session(user["id"], "review_correction", context)
            await line.reply(reply_token, _CORRECTION_PROMPT.get(persona, _CORRECTION_PROMPT["nagi"]))
        elif text == "👍 OK":
            await db.reset_session(user["id"])
            await line.reply(reply_token, _CLOSE_OK.get(persona, _CLOSE_OK["nagi"]))
        else:
            # 期待するボタン以外 → ボタンを再提示（メッセージを飲み込まない）
            await line.reply(reply_token, _FEEDBACK_AGAIN.get(persona, _FEEDBACK_AGAIN["nagi"]), FEEDBACK_LABELS)

    # ── 修正リクエスト ────────────────────────────────────────────────────────
    elif state == "review_correction":
        persona = user.get("persona", "nagi")
        await db.reset_session(user["id"])
        await line.reply(
            reply_token,
            _CORRECTION_DONE.get(persona, _CORRECTION_DONE["nagi"]).format(text=text),
        )
