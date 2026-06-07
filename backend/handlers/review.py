"""
③ 振り返りハンドラ
状態遷移: idle → review_period → review_generating → review_feedback → idle
                                  ↑ バックグラウンドでClause生成、完了後 push
"""
import asyncio
import logging
from datetime import datetime, timedelta
from backend.models import database as db
from backend.services import line_service as line
from backend.services import claude_service as claude

logger = logging.getLogger(__name__)

PERIOD_LABELS = ["📅 今週", "📆 今月", "🗓️ 今年"]
FEEDBACK_LABELS = ["👍 OK", "✏️ 修正したい"]


def _period_since(label: str) -> tuple[str, str]:
    """(since_date_str, period_label_ja) を返す。"""
    today = datetime.now()
    if label == "📅 今週":
        since = today - timedelta(days=today.weekday())
        return since.strftime("%Y-%m-%d"), f"{since.strftime('%m/%d')}〜{today.strftime('%m/%d')}"
    elif label == "📆 今月":
        since = today.replace(day=1)
        return since.strftime("%Y-%m-%d"), f"{today.strftime('%Y年%m月')}"
    elif label == "🗓️ 今年":
        since = today.replace(month=1, day=1)
        return since.strftime("%Y-%m-%d"), f"{today.strftime('%Y年')}"
    return None, "現時点まで"


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
        await line.push(
            user["id"],
            "レポートの生成中にエラーが発生しました。\nもう一度「📊 振り返り」からお試しください 🙏",
        )


# ─── エントリーポイント ───────────────────────────────────────────────────────

async def start(reply_token: str, user: dict) -> None:
    """リッチメニュー「振り返り」タップ時。"""
    await db.set_session(user["id"], "review_period")
    await line.reply(reply_token, "▼ 振り返りの期間を選んでください", PERIOD_LABELS)


async def handle(reply_token: str, user: dict, text: str, state: str, context: dict) -> None:

    # ── 期間選択 ─────────────────────────────────────────────────────────────
    if state == "review_period":
        if text not in PERIOD_LABELS:
            await line.reply(reply_token, "ボタンから選んでください 🙏", PERIOD_LABELS)
            return

        since, period_ja = _period_since(text)
        entries = await db.get_entries(user["id"], since=since)

        thinking_msg = (
            f"わかりました！\n{period_ja}のレポートを作っています...\n\n"
            "少々お待ちください 🤔\n（生成中も他の操作はできます）"
        ) if user.get("persona", "nagi") == "nagi" else (
            f"承知しました。\n{period_ja}のレポートを生成中です...\n\n"
            "しばらくお待ちください 🤔\n（生成中も他の操作は可能です）"
        )

        # ① セッションを generating に移して即座に返信
        await db.set_session(user["id"], "review_generating", {"period": text, "period_ja": period_ja})
        await line.reply(reply_token, thinking_msg)

        # ② バックグラウンドでレポート生成・配信（ここで return、webhook は解放される）
        asyncio.create_task(_generate_and_deliver(user, text, period_ja, entries))

    # ── 生成中（Claude 処理待ち） ─────────────────────────────────────────────
    elif state == "review_generating":
        # 生成中に別テキストが来た場合は待機を案内（メッセージは保持しない）
        wait_msg = (
            "まだレポートを作っているよ 🤔\n"
            "完成したらすぐ送るね！\n\n"
            "タスク追加などは下のメニューからどうぞ 😊"
        ) if user.get("persona", "nagi") == "nagi" else (
            "レポートを生成中です 🤔\n"
            "完成次第お送りします。\n\n"
            "他の操作は下のメニューからどうぞ。"
        )
        await line.reply(reply_token, wait_msg)

    # ── フィードバック ────────────────────────────────────────────────────────
    elif state == "review_feedback":
        if text == "✏️ 修正したい":
            await db.set_session(user["id"], "review_correction", context)
            await line.reply(
                reply_token,
                "どの部分が違和感ありましたか？\n具体的に教えていただけると修正します。",
            )
        elif text == "👍 OK":
            await db.reset_session(user["id"])
            close = "よかった！また振り返りたいときはいつでも 📊" if user.get("persona", "nagi") == "nagi" else "ありがとうございます！また振り返りたいときはいつでも 📊"
            await line.reply(reply_token, close)
        else:
            # 期待するボタン以外 → ボタンを再提示（メッセージを飲み込まない）
            await line.reply(
                reply_token,
                "レポートの確認をお願いします 🙏\n\n"
                "他の操作をしたい場合は、下のメニューから選んでください。",
                FEEDBACK_LABELS,
            )

    # ── 修正リクエスト ────────────────────────────────────────────────────────
    elif state == "review_correction":
        await db.reset_session(user["id"])
        await line.reply(
            reply_token,
            f"フィードバックありがとうございます。\n「{text}」ですね。\n"
            "次回のレポートに反映するよう心がけます 🙏\n\n（修正機能は今後のアップデートで対応予定です）",
        )
