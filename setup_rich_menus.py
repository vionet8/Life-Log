"""
LINE リッチメニュー作成スクリプト
実行: .venv\Scripts\python.exe setup_rich_menus.py

完了後、出力されたIDを .env に追記してください：
  RICH_MENU_YU=richmenu-xxxxx
  RICH_MENU_NAGI=richmenu-xxxxx
  RICH_MENU_MIRAI=richmenu-xxxxx
"""
import asyncio
import json
import httpx
from dotenv import load_dotenv
import os

load_dotenv()
TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
BASE = "https://api.line.me/v2/bot"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

# ── リッチメニューの共通定義（2行×3列）──────────────────────────────────────
# 画像サイズ: 2500×843（1行）or 2500×1686（2行）
# ここでは 2500×843 の1行2ボタンが3列 = 実際は2行3列で2500×1686を想定
# 各エリアは実際の画像サイズに合わせて調整してください

W, H = 2500, 1686  # 2行3列の標準サイズ
BW, BH = W // 3, H // 2  # ボタン1個のサイズ

AREAS = [
    # 1行目
    {"bounds": {"x": 0,        "y": 0,  "width": BW, "height": BH}, "action": {"type": "message", "text": "つぶやく"}},
    {"bounds": {"x": BW,       "y": 0,  "width": BW, "height": BH}, "action": {"type": "message", "text": "相談する"}},
    {"bounds": {"x": BW*2,     "y": 0,  "width": BW, "height": BH}, "action": {"type": "message", "text": "タスク整理"}},
    # 2行目
    {"bounds": {"x": 0,        "y": BH, "width": BW, "height": BH}, "action": {"type": "message", "text": "振り返り"}},
    {"bounds": {"x": BW,       "y": BH, "width": BW, "height": BH}, "action": {"type": "message", "text": "設定"}},
    {"bounds": {"x": BW*2,     "y": BH, "width": BW, "height": BH}, "action": {"type": "message", "text": "ヘルプ"}},
]


def _menu_body(name: str) -> dict:
    return {
        "size": {"width": W, "height": H},
        "selected": True,
        "name": name,
        "chatBarText": "メニュー",
        "areas": AREAS,
    }


async def create_menu(name: str, image_path: str | None = None) -> str:
    """リッチメニューを作成し、IDを返す。"""
    async with httpx.AsyncClient() as client:
        # メニュー定義を作成
        resp = await client.post(
            f"{BASE}/richmenu",
            headers=HEADERS,
            content=json.dumps(_menu_body(name)),
        )
        resp.raise_for_status()
        menu_id = resp.json()["richMenuId"]
        print(f"  Created: {menu_id}")

        # 画像をアップロード（ある場合）
        if image_path and os.path.exists(image_path):
            with open(image_path, "rb") as f:
                img_data = f.read()
            img_resp = await client.post(
                f"https://api-data.line.me/v2/bot/richmenu/{menu_id}/content",
                headers={
                    "Authorization": f"Bearer {TOKEN}",
                    "Content-Type": "image/png",
                },
                content=img_data,
            )
            if img_resp.status_code == 200:
                print(f"  Image uploaded: {image_path}")
            else:
                print(f"  Image upload failed ({img_resp.status_code}): {img_resp.text}")
                print("  ※ 画像サイズが LINE の要件（幅800px以上）を満たしているか確認してください")
        else:
            print(f"  No image (skipped). Set image later in LINE Developers console.")

        return menu_id


async def main():
    print("=== LifeBot リッチメニュー作成 ===\n")

    static_dir = os.path.join(os.path.dirname(__file__), "static")

    personas = [
        ("LifeBot_ユウ",   os.path.join(static_dir, "richmenu_yu.png"),    "RICH_MENU_YU"),
        ("LifeBot_ナギ",   os.path.join(static_dir, "richmenu_nagi.png"),   "RICH_MENU_NAGI"),
        ("LifeBot_ミライ", os.path.join(static_dir, "richmenu_mirai.png"),  "RICH_MENU_MIRAI"),
    ]

    results = {}
    for name, img_path, env_key in personas:
        print(f"[{name}]")
        menu_id = await create_menu(name, img_path)
        results[env_key] = menu_id
        print()

    print("=== 完了 ===")
    print(".env に以下を追記してください:\n")
    for key, val in results.items():
        print(f"{key}={val}")
    print()
    print("追記後はサーバーを再起動してください。")


if __name__ == "__main__":
    asyncio.run(main())
