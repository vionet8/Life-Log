import os
from dotenv import load_dotenv

load_dotenv()

LINE_CHANNEL_SECRET: str = os.environ["LINE_CHANNEL_SECRET"]
LINE_CHANNEL_ACCESS_TOKEN: str = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
ANTHROPIC_API_KEY: str = os.environ["ANTHROPIC_API_KEY"]
TURSO_URL:        str = os.environ["TURSO_URL"]
TURSO_AUTH_TOKEN: str = os.environ["TURSO_AUTH_TOKEN"]
APP_ENV: str = os.getenv("APP_ENV", "development")

# ペルソナ別リッチメニューID（setup_rich_menus.py で生成後に .env へ設定）
RICH_MENU_YU:    str = os.getenv("RICH_MENU_YU", "")
RICH_MENU_NAGI:  str = os.getenv("RICH_MENU_NAGI", "")
RICH_MENU_MIRAI: str = os.getenv("RICH_MENU_MIRAI", "")
