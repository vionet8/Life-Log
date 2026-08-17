"""
Turso (libSQL) データベース初期化とアクセス層
libsql-client (HTTP ネイティブ async) を使用
"""
import json
from datetime import datetime, timezone, timedelta
from typing import Optional

_JST = timezone(timedelta(hours=9))

import libsql_client
from backend.config import TURSO_URL, TURSO_AUTH_TOKEN


# ─── クライアント（シングルトン） ──────────────────────────────────────────────

_client: libsql_client.Client | None = None


def _normalize_url(url: str) -> str:
    """libsql:// or スキームなし → https:// に統一"""
    url = url.strip()
    if url.startswith("libsql://"):
        return "https://" + url[len("libsql://"):]
    if "://" not in url:
        return "https://" + url
    return url


def _get_client() -> libsql_client.Client:
    global _client
    if _client is None:
        _client = libsql_client.create_client(
            url=_normalize_url(TURSO_URL),
            auth_token=TURSO_AUTH_TOKEN,
        )
    return _client


def _now() -> str:
    return datetime.now(_JST).strftime("%Y-%m-%d %H:%M:%S")


def S(sql: str, args: list | None = None) -> libsql_client.Statement:
    """Statement ショートハンド"""
    return libsql_client.Statement(sql, args or [])


# ─── スキーマ ─────────────────────────────────────────────────────────────────

_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users (
        id           TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        tone         TEXT NOT NULL DEFAULT 'formal',
        persona      TEXT NOT NULL DEFAULT 'nagi',
        created_at   TEXT DEFAULT (datetime('now'))
    )""",
    """CREATE TABLE IF NOT EXISTS entries (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id      TEXT NOT NULL,
        body         TEXT NOT NULL,
        location     TEXT,
        weather      TEXT,
        score        INTEGER,
        score_reason TEXT,
        entry_type   TEXT NOT NULL DEFAULT 'murmur',
        created_at   TEXT DEFAULT (datetime('now'))
    )""",
    """CREATE TABLE IF NOT EXISTS tasks (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id      TEXT NOT NULL,
        body         TEXT NOT NULL,
        status       TEXT NOT NULL DEFAULT 'todo',
        created_at   TEXT DEFAULT (datetime('now')),
        completed_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS sessions (
        user_id    TEXT PRIMARY KEY,
        state      TEXT NOT NULL DEFAULT 'idle',
        context    TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT DEFAULT (datetime('now'))
    )""",
    # ACTジャーナリング（4ステップ）の構造化ログ
    #   acceptance : ステップ1 いま在る感情（消さずに認めたもの）
    #   avoidance  : ステップ2 行動の動機（避けるため / 近づくため）
    #   value_text : ステップ3 価値＝進みたい方向・態度
    #   action     : ステップ4 1cmの行動
    #   action_done: 0=未確認 / 1=やった / 2=やらなかった・変えた
    """CREATE TABLE IF NOT EXISTS act_logs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id     TEXT NOT NULL,
        entry_id    INTEGER,
        acceptance  TEXT NOT NULL DEFAULT '',
        avoidance   TEXT NOT NULL DEFAULT '',
        value_text  TEXT NOT NULL DEFAULT '',
        action      TEXT NOT NULL DEFAULT '',
        action_done INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT DEFAULT (datetime('now'))
    )""",
]


# ─── 初期化 ───────────────────────────────────────────────────────────────────

async def init_db() -> None:
    client = _get_client()
    await client.batch(_SCHEMA)
    # マイグレーション: persona 列
    try:
        await client.execute(
            "ALTER TABLE users ADD COLUMN persona TEXT NOT NULL DEFAULT 'nagi'"
        )
    except Exception:
        pass
    # マイグレーション: アンバサダープラン関連列
    for col_sql in [
        "ALTER TABLE users ADD COLUMN plan TEXT DEFAULT 'free'",
        "ALTER TABLE users ADD COLUMN plan_expires_at TEXT",
        "ALTER TABLE users ADD COLUMN ambassador_applied_at TEXT",
    ]:
        try:
            await client.execute(col_sql)
        except Exception:
            pass
    # マイグレーション: entry_type 列
    try:
        await client.execute(
            "ALTER TABLE entries ADD COLUMN entry_type TEXT DEFAULT 'murmur'"
        )
    except Exception:
        pass
    try:
        await client.execute(
            "UPDATE entries SET entry_type = 'murmur' WHERE entry_type IS NULL"
        )
    except Exception:
        pass


# ─── ユーザー ─────────────────────────────────────────────────────────────────

def _row_to_user(row) -> dict:
    def _get(key, default=None):
        try:
            return row[key]
        except Exception:
            return default
    return {
        "id":                     row["id"],
        "display_name":           row["display_name"],
        "tone":                   row["tone"],
        "persona":                row["persona"],
        "plan":                   _get("plan", "free") or "free",
        "plan_expires_at":        _get("plan_expires_at"),
        "ambassador_applied_at":  _get("ambassador_applied_at"),
        "created_at":             row["created_at"],
    }


def is_premium(user: dict) -> bool:
    """アンバサダープランが有効かどうかを返す"""
    if user.get("plan") != "ambassador":
        return False
    expires = user.get("plan_expires_at")
    if expires is None:
        return True  # 永続
    return _now() <= expires


async def get_or_create_user(user_id: str, display_name: str) -> dict:
    client = _get_client()
    rs = await client.execute(
        S("""SELECT id, display_name, tone, persona,
                    plan, plan_expires_at, ambassador_applied_at, created_at
             FROM users WHERE id = ?""",
          [user_id])
    )
    if rs.rows:
        return _row_to_user(rs.rows[0])

    await client.batch([
        S("INSERT INTO users (id, display_name) VALUES (?, ?)", [user_id, display_name]),
        S("INSERT INTO sessions (user_id) VALUES (?)", [user_id]),
    ])
    rs = await client.execute(
        S("""SELECT id, display_name, tone, persona,
                    plan, plan_expires_at, ambassador_applied_at, created_at
             FROM users WHERE id = ?""",
          [user_id])
    )
    return _row_to_user(rs.rows[0])


async def update_persona(user_id: str, persona: str) -> None:
    client = _get_client()
    await client.execute(S("UPDATE users SET persona = ? WHERE id = ?", [persona, user_id]))


# ─── アンバサダー管理 ─────────────────────────────────────────────────────────

async def apply_ambassador(user_id: str) -> None:
    """アンバサダー申請日時を記録する"""
    client = _get_client()
    await client.execute(
        S("UPDATE users SET ambassador_applied_at = ? WHERE id = ?", [_now(), user_id])
    )


async def approve_ambassador(user_id: str, months: int) -> None:
    """アンバサダーを承認する。months=0 は永続。"""
    client = _get_client()
    if months == 0:
        expires = None
    else:
        from datetime import datetime, timedelta
        expires_dt = datetime.now(_JST) + timedelta(days=months * 30)
        expires = expires_dt.strftime("%Y-%m-%d %H:%M:%S")
    await client.execute(
        S("UPDATE users SET plan = 'ambassador', plan_expires_at = ?, ambassador_applied_at = NULL WHERE id = ?",
          [expires, user_id])
    )


async def reject_ambassador(user_id: str) -> None:
    """申請を却下する（申請日時をクリア）"""
    client = _get_client()
    await client.execute(
        S("UPDATE users SET ambassador_applied_at = NULL WHERE id = ?", [user_id])
    )


async def get_ambassador_applicants() -> list[dict]:
    """承認待ちの申請一覧を返す"""
    client = _get_client()
    rs = await client.execute(
        S("""SELECT id, display_name, persona, plan, plan_expires_at,
                    ambassador_applied_at, created_at
             FROM users
             WHERE ambassador_applied_at IS NOT NULL AND plan = 'free'
             ORDER BY ambassador_applied_at ASC""")
    )
    return [_row_to_user(r) for r in rs.rows]


async def get_ambassadors() -> list[dict]:
    """承認済みアンバサダー一覧を返す"""
    client = _get_client()
    rs = await client.execute(
        S("""SELECT id, display_name, persona, plan, plan_expires_at,
                    ambassador_applied_at, created_at
             FROM users
             WHERE plan = 'ambassador'
             ORDER BY display_name ASC""")
    )
    return [_row_to_user(r) for r in rs.rows]


async def update_tone(user_id: str, tone: str) -> None:
    """後方互換のため残す（未使用）"""
    client = _get_client()
    await client.execute(S("UPDATE users SET tone = ? WHERE id = ?", [tone, user_id]))


# ─── セッション（会話ステート） ───────────────────────────────────────────────

async def get_session(user_id: str) -> dict:
    client = _get_client()
    rs = await client.execute(
        S("SELECT state, context FROM sessions WHERE user_id = ?", [user_id])
    )
    if not rs.rows:
        return {"state": "idle", "context": {}}
    row = rs.rows[0]
    return {"state": row["state"], "context": json.loads(row["context"])}


async def set_session(user_id: str, state: str, context: dict | None = None) -> None:
    ctx = json.dumps(context or {}, ensure_ascii=False)
    now = _now()
    client = _get_client()
    await client.execute(
        S("""
          INSERT INTO sessions (user_id, state, context, updated_at)
          VALUES (?, ?, ?, ?)
          ON CONFLICT(user_id) DO UPDATE SET
              state      = excluded.state,
              context    = excluded.context,
              updated_at = excluded.updated_at
          """,
          [user_id, state, ctx, now])
    )


async def reset_session(user_id: str) -> None:
    await set_session(user_id, "idle", {})


# ─── エントリー（つぶやき） ───────────────────────────────────────────────────

def _row_to_entry(row) -> dict:
    try:
        entry_type = row["entry_type"] or "murmur"
    except Exception:
        entry_type = "murmur"
    return {
        "id":           row["id"],
        "user_id":      row["user_id"],
        "body":         row["body"],
        "location":     row["location"],
        "weather":      row["weather"],
        "score":        row["score"],
        "score_reason": row["score_reason"],
        "entry_type":   entry_type,
        "created_at":   row["created_at"],
    }


async def create_entry(
    user_id: str,
    body: str,
    location: Optional[str] = None,
    weather: Optional[str] = None,
    score: Optional[int] = None,
    score_reason: Optional[str] = None,
    entry_type: str = "murmur",
) -> int:
    now = _now()
    client = _get_client()
    rs = await client.execute(
        S("""
          INSERT INTO entries
              (user_id, body, location, weather, score, score_reason, entry_type, created_at)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?)
          """,
          [user_id, body, location, weather, score, score_reason, entry_type, now])
    )
    return rs.last_insert_rowid


async def delete_entry_by_id(user_id: str, entry_id: int) -> bool:
    """指定エントリーを削除する。自分のエントリーのみ削除可。削除できたらTrue。"""
    client = _get_client()
    rs = await client.execute(
        S("SELECT id FROM entries WHERE id = ? AND user_id = ?", [entry_id, user_id])
    )
    if not rs.rows:
        return False
    await client.execute(S("DELETE FROM entries WHERE id = ?", [entry_id]))
    return True


async def get_last_entries(user_id: str, limit: int = 3) -> list[dict]:
    client = _get_client()
    try:
        rs = await client.execute(
            S("""
              SELECT id, user_id, body, location, weather, score, score_reason, entry_type, created_at
              FROM entries WHERE user_id = ? ORDER BY created_at DESC LIMIT ?
              """,
              [user_id, limit])
        )
    except Exception:
        # entry_type 列が存在しない旧スキーマへのフォールバック
        rs = await client.execute(
            S("""
              SELECT id, user_id, body, location, weather, score, score_reason, created_at
              FROM entries WHERE user_id = ? ORDER BY created_at DESC LIMIT ?
              """,
              [user_id, limit])
        )
    return [_row_to_entry(r) for r in rs.rows]


async def get_entries(user_id: str, since: Optional[str] = None) -> list[dict]:
    """since: ISO日付文字列 (YYYY-MM-DD)"""
    client = _get_client()
    try:
        if since:
            rs = await client.execute(
                S("""
                  SELECT id, user_id, body, location, weather, score, score_reason, entry_type, created_at
                  FROM entries WHERE user_id = ? AND created_at >= ? ORDER BY created_at DESC
                  """,
                  [user_id, since])
            )
        else:
            rs = await client.execute(
                S("""
                  SELECT id, user_id, body, location, weather, score, score_reason, entry_type, created_at
                  FROM entries WHERE user_id = ? ORDER BY created_at DESC LIMIT 100
                  """,
                  [user_id])
            )
    except Exception:
        # entry_type 列が存在しない旧スキーマへのフォールバック
        if since:
            rs = await client.execute(
                S("""
                  SELECT id, user_id, body, location, weather, score, score_reason, created_at
                  FROM entries WHERE user_id = ? AND created_at >= ? ORDER BY created_at DESC
                  """,
                  [user_id, since])
            )
        else:
            rs = await client.execute(
                S("""
                  SELECT id, user_id, body, location, weather, score, score_reason, created_at
                  FROM entries WHERE user_id = ? ORDER BY created_at DESC LIMIT 100
                  """,
                  [user_id])
            )
    return [_row_to_entry(r) for r in rs.rows]


# ─── ACTジャーナリング ────────────────────────────────────────────────────────

def _row_to_act_log(row) -> dict:
    return {
        "id":          row["id"],
        "user_id":     row["user_id"],
        "entry_id":    row["entry_id"],
        "acceptance":  row["acceptance"],
        "avoidance":   row["avoidance"],
        "value_text":  row["value_text"],
        "action":      row["action"],
        "action_done": row["action_done"],
        "created_at":  row["created_at"],
    }


_ACT_COLS = """id, user_id, entry_id, acceptance, avoidance,
               value_text, action, action_done, created_at"""


async def create_act_log(
    user_id: str,
    acceptance: str,
    avoidance: str,
    value_text: str,
    action: str,
    entry_id: Optional[int] = None,
) -> int:
    """ACTジャーナル1回分（4ステップ）を保存する。"""
    now = _now()
    client = _get_client()
    rs = await client.execute(
        S("""
          INSERT INTO act_logs
              (user_id, entry_id, acceptance, avoidance, value_text, action, created_at)
          VALUES (?, ?, ?, ?, ?, ?, ?)
          """,
          [user_id, entry_id, acceptance, avoidance, value_text, action, now])
    )
    return rs.last_insert_rowid


async def get_act_logs(user_id: str, since: Optional[str] = None, limit: int = 100) -> list[dict]:
    """since: ISO日付文字列 (YYYY-MM-DD)。新しい順に返す。"""
    client = _get_client()
    if since:
        rs = await client.execute(
            S(f"""SELECT {_ACT_COLS} FROM act_logs
                  WHERE user_id = ? AND created_at >= ?
                  ORDER BY created_at DESC LIMIT ?""",
              [user_id, since, limit])
        )
    else:
        rs = await client.execute(
            S(f"""SELECT {_ACT_COLS} FROM act_logs
                  WHERE user_id = ? ORDER BY created_at DESC LIMIT ?""",
              [user_id, limit])
        )
    return [_row_to_act_log(r) for r in rs.rows]


async def get_pending_act_log(user_id: str) -> dict | None:
    """
    まだ結果を確認していない「前回の1cmの行動」を返す。
    同日中の記録は対象外（まだ実行する時間があるため）。
    """
    today = datetime.now(_JST).strftime("%Y-%m-%d")
    client = _get_client()
    rs = await client.execute(
        S(f"""SELECT {_ACT_COLS} FROM act_logs
              WHERE user_id = ? AND action_done = 0 AND substr(created_at, 1, 10) < ?
              ORDER BY created_at DESC LIMIT 1""",
          [user_id, today])
    )
    return _row_to_act_log(rs.rows[0]) if rs.rows else None


async def set_act_action_done(user_id: str, log_id: int, done: int) -> None:
    """1cmの行動の結果を記録する。done: 1=やった / 2=やらなかった・変えた"""
    client = _get_client()
    await client.execute(
        S("UPDATE act_logs SET action_done = ? WHERE id = ? AND user_id = ?",
          [done, log_id, user_id])
    )


async def clear_pending_act_logs(user_id: str, before_id: int) -> None:
    """
    確認をスキップされた古い未確認ログを「確認済み扱い」にする。
    毎回いちばん古い1件を蒸し返さないための後始末。
    """
    client = _get_client()
    await client.execute(
        S("UPDATE act_logs SET action_done = 2 WHERE user_id = ? AND action_done = 0 AND id <= ?",
          [user_id, before_id])
    )


async def delete_act_log(user_id: str, log_id: int) -> bool:
    """指定ACTログを削除する。自分のログのみ削除可。"""
    client = _get_client()
    rs = await client.execute(
        S("SELECT id FROM act_logs WHERE id = ? AND user_id = ?", [log_id, user_id])
    )
    if not rs.rows:
        return False
    await client.execute(S("DELETE FROM act_logs WHERE id = ?", [log_id]))
    return True


async def get_recent_act_values(user_id: str, limit: int = 2) -> list[str]:
    """直近で選ばれた価値（重複なし）を新しい順に返す。"""
    client = _get_client()
    rs = await client.execute(
        S("""SELECT value_text, MAX(created_at) AS latest FROM act_logs
             WHERE user_id = ? AND value_text != ''
             GROUP BY value_text ORDER BY latest DESC LIMIT ?""",
          [user_id, limit])
    )
    return [r["value_text"] for r in rs.rows]


# ─── タスク ───────────────────────────────────────────────────────────────────

def _row_to_task(row) -> dict:
    return {
        "id":           row["id"],
        "user_id":      row["user_id"],
        "body":         row["body"],
        "status":       row["status"],
        "created_at":   row["created_at"],
        "completed_at": row["completed_at"],
    }


async def create_tasks(user_id: str, bodies: list[str]) -> list[int]:
    now = _now()
    client = _get_client()
    ids = []
    for body in bodies:
        rs = await client.execute(
            S("INSERT INTO tasks (user_id, body, created_at) VALUES (?, ?, ?)",
              [user_id, body, now])
        )
        ids.append(rs.last_insert_rowid)
    return ids


async def get_todo_tasks(user_id: str) -> list[dict]:
    client = _get_client()
    rs = await client.execute(
        S("""
          SELECT id, user_id, body, status, created_at, completed_at
          FROM tasks WHERE user_id = ? AND status = 'todo' ORDER BY created_at ASC
          """,
          [user_id])
    )
    return [_row_to_task(r) for r in rs.rows]


async def complete_tasks(user_id: str, task_ids: list[int]) -> list[str]:
    """完了処理。完了したタスク本文を返す。"""
    now = _now()
    client = _get_client()
    done_bodies = []
    for tid in task_ids:
        rs = await client.execute(
            S("SELECT body FROM tasks WHERE id = ? AND user_id = ? AND status = 'todo'",
              [tid, user_id])
        )
        if rs.rows:
            await client.execute(
                S("UPDATE tasks SET status='done', completed_at=? WHERE id = ?", [now, tid])
            )
            done_bodies.append(rs.rows[0]["body"])
    return done_bodies


async def delete_tasks(user_id: str, task_ids: list[int]) -> list[str]:
    """削除処理。削除したタスク本文を返す。"""
    client = _get_client()
    deleted_bodies = []
    for tid in task_ids:
        rs = await client.execute(
            S("SELECT body FROM tasks WHERE id = ? AND user_id = ? AND status = 'todo'",
              [tid, user_id])
        )
        if rs.rows:
            await client.execute(
                S("UPDATE tasks SET status='deleted' WHERE id = ?", [tid])
            )
            deleted_bodies.append(rs.rows[0]["body"])
    return deleted_bodies
