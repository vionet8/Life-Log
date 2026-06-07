"""
リッチメニュー画像をリサイズ→LINEにアップロードするスクリプト
実行: .venv\Scripts\python.exe upload_richmenu_images.py
"""
import os
import io
import httpx
from PIL import Image
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
HEADERS_AUTH = {"Authorization": f"Bearer {TOKEN}"}

TARGET_W, TARGET_H = 2500, 1686  # LINE 推奨サイズ（2行3列）

MENUS = [
    ("richmenu_yu",    os.getenv("RICH_MENU_YU")),
    ("richmenu_nagi",  os.getenv("RICH_MENU_NAGI")),
    ("richmenu_mirai", os.getenv("RICH_MENU_MIRAI")),
]


def resize_to_fill(img: Image.Image, w: int, h: int) -> Image.Image:
    """余白なしで w×h に引き伸ばして全面を埋める（crop-to-fill）。"""
    # アスペクト比を保ちながら「はみ出す側」に合わせてスケール
    ratio = max(w / img.width, h / img.height)
    new_size = (int(img.width * ratio), int(img.height * ratio))
    resized = img.resize(new_size, Image.LANCZOS)
    # 中央でクロップ
    left = (new_size[0] - w) // 2
    top  = (new_size[1] - h) // 2
    return resized.crop((left, top, left + w, top + h)).convert("RGB")


def main():
    for name, menu_id in MENUS:
        if not menu_id:
            print(f"[{name}] SKIP: メニューIDが .env に未設定")
            continue

        src = f"static/{name}.png"
        if not os.path.exists(src):
            print(f"[{name}] SKIP: {src} が見つかりません")
            continue

        print(f"[{name}] リサイズ中 → {TARGET_W}×{TARGET_H}...")
        img = Image.open(src)
        resized = resize_to_fill(img, TARGET_W, TARGET_H)

        buf = io.BytesIO()
        resized.save(buf, format="JPEG", quality=90)
        buf.seek(0)
        img_bytes = buf.read()

        print(f"[{name}] LINE にアップロード中... ({len(img_bytes)//1024} KB)")
        resp = httpx.post(
            f"https://api-data.line.me/v2/bot/richmenu/{menu_id}/content",
            headers={**HEADERS_AUTH, "Content-Type": "image/jpeg"},
            content=img_bytes,
            timeout=30,
        )

        if resp.status_code == 200:
            print(f"[{name}] OK: upload success")
        else:
            print(f"[{name}] FAIL ({resp.status_code}): {resp.text}")

    print("\n完了。LINEアプリで確認してください。")


if __name__ == "__main__":
    main()
