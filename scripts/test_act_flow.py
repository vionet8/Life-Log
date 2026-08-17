"""
ACTジャーナリング（⑤）の状態遷移を検証するスクリプト。

LINE / Turso / Claude API には接続せず、DB・送信・AI呼び出しを差し替えて
ハンドラの状態遷移と保存内容だけを確認する。

実行: python -m scripts.test_act_flow
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# backend.config は環境変数必須のため、未設定ならダミーを入れて import 可能にする
for _key in (
    "LINE_CHANNEL_SECRET", "LINE_CHANNEL_ACCESS_TOKEN",
    "ANTHROPIC_API_KEY", "TURSO_URL", "TURSO_AUTH_TOKEN",
):
    os.environ.setdefault(_key, "dummy")

from backend.models import database as db          # noqa: E402
from backend.services import line_service as line  # noqa: E402
from backend.services import claude_service as claude  # noqa: E402
from backend.services import review_stats          # noqa: E402
from backend.handlers import act                   # noqa: E402


# ─── 検証ヘルパー ─────────────────────────────────────────────────────────────

_failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    mark = "✅" if ok else "❌"
    print(f"  {mark} {label}" + (f"  … {detail}" if detail and not ok else ""))
    if not ok:
        _failures.append(label)


# ─── インメモリのフェイクDB ───────────────────────────────────────────────────

class FakeDB:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.sessions: dict[str, dict] = {}
        self.entries: list[dict] = []
        self.act_logs: list[dict] = []
        self.tasks: list[str] = []
        self._entry_seq = 0
        self._log_seq = 0

    # -- sessions --
    async def get_session(self, user_id):
        return self.sessions.get(user_id, {"state": "idle", "context": {}})

    async def set_session(self, user_id, state, context=None):
        self.sessions[user_id] = {"state": state, "context": context or {}}

    async def reset_session(self, user_id):
        await self.set_session(user_id, "idle", {})

    # -- entries --
    async def create_entry(self, user_id, body, location=None, weather=None,
                           score=None, score_reason=None, entry_type="murmur"):
        self._entry_seq += 1
        self.entries.append({
            "id": self._entry_seq, "user_id": user_id, "body": body,
            "entry_type": entry_type, "created_at": "2026-08-17 21:00:00",
        })
        return self._entry_seq

    async def delete_entry_by_id(self, user_id, entry_id):
        before = len(self.entries)
        self.entries = [e for e in self.entries
                        if not (e["id"] == entry_id and e["user_id"] == user_id)]
        return len(self.entries) < before

    # -- act_logs --
    async def create_act_log(self, user_id, acceptance, avoidance, value_text,
                             action, entry_id=None):
        self._log_seq += 1
        self.act_logs.append({
            "id": self._log_seq, "user_id": user_id, "entry_id": entry_id,
            "acceptance": acceptance, "avoidance": avoidance,
            "value_text": value_text, "action": action,
            "action_done": 0, "created_at": "2026-08-17 21:00:00",
        })
        return self._log_seq

    async def get_pending_act_log(self, user_id):
        pending = [log for log in self.act_logs
                   if log["user_id"] == user_id and log["action_done"] == 0]
        return pending[-1] if pending else None

    async def set_act_action_done(self, user_id, log_id, done):
        for log in self.act_logs:
            if log["id"] == log_id and log["user_id"] == user_id:
                log["action_done"] = done

    async def clear_pending_act_logs(self, user_id, before_id):
        for log in self.act_logs:
            if log["user_id"] == user_id and log["action_done"] == 0 and log["id"] <= before_id:
                log["action_done"] = 2

    async def delete_act_log(self, user_id, log_id):
        before = len(self.act_logs)
        self.act_logs = [log for log in self.act_logs
                         if not (log["id"] == log_id and log["user_id"] == user_id)]
        return len(self.act_logs) < before

    async def get_recent_act_values(self, user_id, limit=2):
        seen: list[str] = []
        for log in reversed(self.act_logs):
            v = log["value_text"]
            if log["user_id"] == user_id and v and v not in seen:
                seen.append(v)
        return seen[:limit]

    # -- tasks --
    async def create_tasks(self, user_id, bodies):
        self.tasks.extend(bodies)
        return list(range(len(bodies)))


class FakeLine:
    def __init__(self) -> None:
        self.sent: list[tuple[str, list[str]]] = []

    async def reply(self, reply_token, text, quick_replies=None):
        self.sent.append((text, quick_replies or []))

    @property
    def last_text(self) -> str:
        return self.sent[-1][0] if self.sent else ""

    @property
    def last_quick(self) -> list[str]:
        return self.sent[-1][1] if self.sent else []


FAKE_SUGGESTIONS = ["家族に短い連絡を入れる", "3割だけ手をつける", "依頼を1つ断る"]


async def fake_analyze_act_journal(log, persona="nagi"):
    return f"（AIコメント／価値:{log.get('value_text')}）"


async def fake_suggest_act_actions(value_text, acceptance="", persona="nagi"):
    return list(FAKE_SUGGESTIONS)


# ─── 差し替え ─────────────────────────────────────────────────────────────────

fake_db = FakeDB()
fake_line = FakeLine()

for _name in (
    "get_session", "set_session", "reset_session",
    "create_entry", "delete_entry_by_id",
    "create_act_log", "get_pending_act_log", "set_act_action_done",
    "clear_pending_act_logs", "delete_act_log", "get_recent_act_values",
    "create_tasks",
):
    setattr(db, _name, getattr(fake_db, _name))

line.reply = fake_line.reply
claude.analyze_act_journal = fake_analyze_act_journal
claude.suggest_act_actions = fake_suggest_act_actions

USER = {"id": "U_test", "persona": "nagi", "display_name": "テスト"}


async def send(text: str) -> None:
    """ユーザー発話を1つ流し込む（webhook と同じ振り分けをたどる）。"""
    session = await fake_db.get_session(USER["id"])
    await act.handle("token", USER, text, session["state"], session["context"])


async def state() -> str:
    return (await fake_db.get_session(USER["id"]))["state"]


# ─── シナリオ ─────────────────────────────────────────────────────────────────

async def scenario_full_flow() -> None:
    print("\n① 初回フロー（4ステップ → タスク追加）")
    fake_db.reset()

    await act.start("token", USER)
    check("開始で act_accept に入る", await state() == "act_accept", await state())
    check("ステップ1の問いが出る", "【1/4】" in fake_line.last_text, fake_line.last_text)

    await send("焦りと虚しさが同時にある感じ")
    check("ステップ2へ進む", await state() == "act_avoid", await state())
    check("動機の選択肢が出る", fake_line.last_quick == act.AVOID_LABELS, str(fake_line.last_quick))

    await send("🛡️ 避けるため")
    check("ステップ3へ進む", await state() == "act_value", await state())
    check("価値の候補が4件出る", len(fake_line.last_quick) == 4, str(fake_line.last_quick))

    await send("誠実でありたい")
    check("ステップ4へ進む", await state() == "act_action", await state())
    check("価値が問いに埋め込まれる", "誠実でありたい" in fake_line.last_text, fake_line.last_text)

    await send("引き受けたくない依頼を1つ断る")
    check("保存後 act_confirm へ", await state() == "act_confirm", await state())
    check("エントリーが1件保存される", len(fake_db.entries) == 1, str(fake_db.entries))
    check("entry_type が act", fake_db.entries[0]["entry_type"] == "act",
          fake_db.entries[0]["entry_type"])
    check("本文に4ステップが含まれる",
          all(w in fake_db.entries[0]["body"]
              for w in ("[ACT]", "焦りと虚しさ", "誠実でありたい", "依頼を1つ断る")),
          fake_db.entries[0]["body"])

    log = fake_db.act_logs[0]
    check("ACTログの4項目が揃う",
          log["acceptance"] == "焦りと虚しさが同時にある感じ"
          and log["avoidance"] == "🛡️ 避けるため"
          and log["value_text"] == "誠実でありたい"
          and log["action"] == "引き受けたくない依頼を1つ断る",
          str(log))
    check("ACTログがエントリーと紐づく", log["entry_id"] == fake_db.entries[0]["id"], str(log))
    check("AIコメントが添えられる", "AIコメント" in fake_line.last_text, fake_line.last_text)

    await send("✅ タスクに追加")
    check("タスクに1cmの行動が入る",
          fake_db.tasks == ["引き受けたくない依頼を1つ断る"], str(fake_db.tasks))
    check("idle に戻る", await state() == "idle", await state())


async def scenario_prev_action() -> None:
    print("\n② 2回目以降（前回の1cmの行動の確認）")
    # ①の状態（未確認ログ1件）を引き継いで開始する
    await act.start("token", USER)
    check("act_prev に入る", await state() == "act_prev", await state())
    check("前回の行動が提示される",
          "引き受けたくない依頼を1つ断る" in fake_line.last_text, fake_line.last_text)
    check("結果ボタンが出る", fake_line.last_quick == act.PREV_LABELS, str(fake_line.last_quick))

    await send("✅ やった")
    check("実行済みとして記録される", fake_db.act_logs[0]["action_done"] == 1,
          str(fake_db.act_logs[0]))
    check("そのままステップ1へ", await state() == "act_accept", await state())
    check("未確認ログは残らない",
          await fake_db.get_pending_act_log(USER["id"]) is None)

    # 過去の価値が候補の先頭に出るか
    await send("なんとなく落ち着かない")
    await send("🧭 近づくため")
    check("前回の価値が候補の先頭に出る",
          fake_line.last_quick[0] == "誠実でありたい", str(fake_line.last_quick))


async def scenario_suggestion_and_undo() -> None:
    print("\n③ 「思いつかない」→ 候補提示 → 取り消し")
    await send("自分を丁寧に扱いたい")
    check("ステップ4に入る", await state() == "act_action", await state())

    await send(act.ACTION_HELP_LABEL)
    check("候補提示後も act_action のまま", await state() == "act_action", await state())
    check("候補がクイックリプライで出る", fake_line.last_quick == FAKE_SUGGESTIONS,
          str(fake_line.last_quick))

    entries_before = len(fake_db.entries)
    await send(FAKE_SUGGESTIONS[1])
    check("候補を選んで保存できる", len(fake_db.entries) == entries_before + 1,
          str(len(fake_db.entries)))
    check("act_confirm へ", await state() == "act_confirm", await state())

    logs_before = len(fake_db.act_logs)
    await send(act.UNDO_LABEL)
    check("取り消しでエントリーが消える", len(fake_db.entries) == entries_before,
          str(len(fake_db.entries)))
    check("取り消しでACTログも消える", len(fake_db.act_logs) == logs_before - 1,
          str(len(fake_db.act_logs)))
    check("idle に戻る", await state() == "idle", await state())


def scenario_stats() -> None:
    print("\n④ 振り返り用の統計（compute_act_stats）")
    logs = [
        {"value_text": "誠実でありたい", "avoidance": "🛡️ 避けるため",  "action_done": 1},
        {"value_text": "誠実でありたい", "avoidance": "🧭 近づくため",  "action_done": 2},
        {"value_text": "自分を丁寧に扱いたい", "avoidance": "🛡️ 避けるため", "action_done": 1},
        {"value_text": "自分を丁寧に扱いたい", "avoidance": "自分でもよく分からない", "action_done": 0},
    ]
    stats = review_stats.compute_act_stats(logs)
    check("件数を数える", stats["act_count"] == 4, str(stats["act_count"]))
    check("価値の登場回数を数える",
          stats["value_counts"] == {"誠実でありたい": 2, "自分を丁寧に扱いたい": 2},
          str(stats["value_counts"]))
    check("動機の内訳は選択肢のみ数える",
          stats["avoid_counts"] == {"避けるため": 2, "近づくため": 1},
          str(stats["avoid_counts"]))
    check("未確認の行動は実行率の分母から外す",
          stats["action_total"] == 3 and stats["action_done"] == 2
          and stats["action_done_rate"] == 67,
          str(stats))

    facts = review_stats.act_stats_to_facts(stats)
    check("事実テキストに件数と価値が出る",
          "ACTジャーナル記録: 4件" in facts and "「誠実でありたい」2回" in facts, facts)
    check("記録が無ければ空文字",
          review_stats.act_stats_to_facts(review_stats.compute_act_stats([])) == "")


def scenario_routing() -> None:
    print("\n⑤ webhook のルーティング")
    from backend import webhook

    for keyword in ("ACTジャーナル", "🧭 ACTジャーナル", "アクトジャーナル", "ACT"):
        check(f"「{keyword}」で起動する", webhook.MENU_TRIGGERS.get(keyword) == "act")

    for st in ("act_prev", "act_accept", "act_avoid", "act_value", "act_action", "act_confirm"):
        check(f"{st} が act ハンドラへ渡る",
              webhook.STATE_PREFIX_MAP.get(st.split("_")[0]) is act)


async def main() -> None:
    print("═" * 60)
    print("ACTジャーナリング 状態遷移テスト")
    print("═" * 60)

    await scenario_full_flow()
    await scenario_prev_action()
    await scenario_suggestion_and_undo()
    scenario_stats()
    scenario_routing()

    print("\n" + "═" * 60)
    if _failures:
        print(f"❌ {len(_failures)}件 失敗")
        for f in _failures:
            print(f"   - {f}")
        sys.exit(1)
    print("✅ すべて通過")


if __name__ == "__main__":
    asyncio.run(main())
