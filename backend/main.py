"""
FastAPI エントリーポイント
"""
import logging
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from backend.models.database import init_db, _get_client
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


@app.get("/lp")
async def lp():
    return FileResponse(str(STATIC_DIR / "lp.html"))


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "app": "Life-Log & Focus"}
