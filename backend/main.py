"""
FastAPI エントリーポイント
"""
import logging
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Form
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from backend.models.database import (
    init_db, _get_client,
    get_ambassador_applicants, get_ambassadors,
    approve_ambassador, reject_ambassador,
)
from backend.config import ADMIN_KEY
from backend.webhook import router as webhook_router

STATIC_DIR = Path(__file__).parent.parent / "static"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 起動時: DB 初期化
    logger.info("Initializing database...")
    await init_db()
    logger.info("Database ready.")
    yield
    # シャットダウン時: Turso クライアントを閉じる
    try:
        await _get_client().close()
    except Exception:
        pass


app = FastAPI(
    title="Life-Log & Focus API",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(webhook_router)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def root() -> dict:
    return {"status": "ok", "app": "Life-Log & Focus"}


@app.get("/lp")
async def lp():
    return FileResponse(str(STATIC_DIR / "lp.html"))


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "app": "Life-Log & Focus"}


# ─── 管理ページ ───────────────────────────────────────────────────────────────

def _admin_check(key: str) -> bool:
    return bool(ADMIN_KEY) and key == ADMIN_KEY


def _admin_html(key: str, applicants: list, ambassadors: list) -> str:
    def _row(u, action_html):
        expires = u.get("plan_expires_at") or "永続"
        applied = u.get("ambassador_applied_at") or "-"
        return (
            f"<tr><td>{u['display_name']}</td><td><code>{u['id'][:12]}…</code></td>"
            f"<td>{u.get('persona','')}</td><td>{applied}</td><td>{expires}</td>"
            f"<td>{action_html}</td></tr>"
        )

    def _approve_form(u):
        return (
            f'<form method="post" action="/admin/ambassador/approve" style="display:inline">'
            f'<input type="hidden" name="key" value="{key}">'
            f'<input type="hidden" name="user_id" value="{u["id"]}">'
            f'<button name="months" value="6">6ヶ月</button> '
            f'<button name="months" value="0">永続</button>'
            f'</form>'
            f' <form method="post" action="/admin/ambassador/reject" style="display:inline">'
            f'<input type="hidden" name="key" value="{key}">'
            f'<input type="hidden" name="user_id" value="{u["id"]}">'
            f'<button style="color:red">却下</button></form>'
        )

    def _revoke_form(u):
        return (
            f'<form method="post" action="/admin/ambassador/reject" style="display:inline">'
            f'<input type="hidden" name="key" value="{key}">'
            f'<input type="hidden" name="user_id" value="{u["id"]}">'
            f'<button style="color:red">取消</button></form>'
        )

    pending_rows = "".join(_row(u, _approve_form(u)) for u in applicants) or "<tr><td colspan='6'>なし</td></tr>"
    ambassador_rows = "".join(_row(u, _revoke_form(u)) for u in ambassadors) or "<tr><td colspan='6'>なし</td></tr>"

    table_style = "border-collapse:collapse;width:100%;margin-bottom:2rem"
    th_style = "border:1px solid #ccc;padding:6px 10px;background:#f5f5f5;text-align:left"
    td_style = "border:1px solid #ccc;padding:6px 10px"

    return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<title>Life-Log アンバサダー管理</title>
<style>body{{font-family:sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem}}
table{{border-collapse:collapse;width:100%;margin-bottom:2rem}}
th,td{{border:1px solid #ccc;padding:6px 10px;text-align:left}}
th{{background:#f5f5f5}}button{{cursor:pointer;padding:3px 10px}}</style>
</head><body>
<h1>🏅 アンバサダー管理</h1>
<h2>申請中（{len(applicants)}件）</h2>
<table><tr><th>名前</th><th>ID</th><th>ペルソナ</th><th>申請日時</th><th>有効期限</th><th>操作</th></tr>
{pending_rows}</table>
<h2>アンバサダー（{len(ambassadors)}件）</h2>
<table><tr><th>名前</th><th>ID</th><th>ペルソナ</th><th>申請日時</th><th>有効期限</th><th>操作</th></tr>
{ambassador_rows}</table>
</body></html>"""


@app.get("/admin/ambassador", response_class=HTMLResponse)
async def admin_ambassador_page(key: str = ""):
    if not _admin_check(key):
        return HTMLResponse("Unauthorized", status_code=401)
    applicants = await get_ambassador_applicants()
    ambassadors = await get_ambassadors()
    return _admin_html(key, applicants, ambassadors)


@app.post("/admin/ambassador/approve")
async def admin_approve(key: str = Form(...), user_id: str = Form(...), months: int = Form(...)):
    if not _admin_check(key):
        return HTMLResponse("Unauthorized", status_code=401)
    await approve_ambassador(user_id, months)
    return RedirectResponse(f"/admin/ambassador?key={key}", status_code=303)


@app.post("/admin/ambassador/reject")
async def admin_reject(key: str = Form(...), user_id: str = Form(...)):
    if not _admin_check(key):
        return HTMLResponse("Unauthorized", status_code=401)
    await reject_ambassador(user_id)
    return RedirectResponse(f"/admin/ambassador?key={key}", status_code=303)
