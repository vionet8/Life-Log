"""
LINE リッチメニュー セットアップスクリプト
実行: .venv\Scripts\python.exe -m backend.setup_rich_menu

4ボタン構成（2×2グリッド）:
  [📝 つぶやく]   [✅ タスク整理]
  [📊 振り返り]   [⚙️  設定     ]
"""
import asyncio
import io
import json
import sys
import httpx
from PIL import Image, ImageDraw, ImageFont

from backend.config import LINE_CHANNEL_ACCESS_TOKEN

# ─── デザイン設定 ─────────────────────────────────────────────────────────────

W, H = 2500, 1686          # LINE リッチメニュー標準サイズ
CW, CH = W // 2, H // 2   # 各セルサイズ

BUTTONS = [
    # (行, 列, アイコン種別, ラベル, 送信テキスト, 背景色)
    (0, 0, "pen",      "つぶやく",   "つぶやく",   "#58B19F"),
    (0, 1, "check",    "タスク整理", "タスク整理", "#3C6382"),
    (1, 0, "chart",    "振り返り",   "振り返り",   "#6A89CC"),
    (1, 1, "gear",     "設定",       "設定",       "#82589F"),
]

# Windows 日本語フォントの候補
FONT_CANDIDATES = [
    "C:/Windows/Fonts/meiryo.ttc",
    "C:/Windows/Fonts/msgothic.ttc",
    "C:/Windows/Fonts/YuGothB.ttc",
    "C:/Windows/Fonts/yugothib.ttf",
]

LINE_API = "https://api.line.me/v2/bot"


# ─── アイコン描画（Pillow 図形） ──────────────────────────────────────────────

def _draw_pen(draw: ImageDraw.Draw, cx: int, cy: int, s: int) -> None:
    """鉛筆アイコン（つぶやく）"""
    import math
    angle = math.radians(45)
    hw = int(s * 0.18)
    hl = int(s * 0.65)
    tip = int(s * 0.15)
    cos_a, sin_a = math.cos(angle), math.sin(angle)

    # 本体（平行四辺形）
    pts = [
        (cx + int((-hw) * cos_a - (-hl // 2) * sin_a),
         cy + int((-hw) * sin_a + (-hl // 2) * cos_a)),
        (cx + int(( hw) * cos_a - (-hl // 2) * sin_a),
         cy + int(( hw) * sin_a + (-hl // 2) * cos_a)),
        (cx + int(( hw) * cos_a - ( hl // 2) * sin_a),
         cy + int(( hw) * sin_a + ( hl // 2) * cos_a)),
        (cx + int((-hw) * cos_a - ( hl // 2) * sin_a),
         cy + int((-hw) * sin_a + ( hl // 2) * cos_a)),
    ]
    draw.polygon(pts, fill="white")

    # 先端（三角形）
    tip_pts = [
        pts[2], pts[3],
        (cx + int(0 * cos_a - (hl // 2 + tip) * sin_a),
         cy + int(0 * sin_a + (hl // 2 + tip) * cos_a)),
    ]
    draw.polygon(tip_pts, fill="white")


def _draw_check(draw: ImageDraw.Draw, cx: int, cy: int, s: int) -> None:
    """チェックマークアイコン（タスク整理）"""
    lw = max(s // 8, 8)
    # チェックマーク（V字を傾けた形）
    p1 = (cx - s // 2, cy)
    p2 = (cx - s // 8, cy + s // 3)
    p3 = (cx + s // 2, cy - s // 3)
    draw.line([p1, p2, p3], fill="white", width=lw, joint="curve")


def _draw_chart(draw: ImageDraw.Draw, cx: int, cy: int, s: int) -> None:
    """棒グラフアイコン（振り返り）"""
    bar_w = s // 5
    gap = s // 10
    heights = [s * 4 // 10, s * 7 // 10, s * 5 // 10]
    total_w = bar_w * 3 + gap * 2
    start_x = cx - total_w // 2
    base_y = cy + s // 3

    for i, h in enumerate(heights):
        bx = start_x + i * (bar_w + gap)
        draw.rounded_rectangle(
            [bx, base_y - h, bx + bar_w, base_y],
            radius=bar_w // 4,
            fill="white",
        )


def _draw_gear(draw: ImageDraw.Draw, cx: int, cy: int, s: int) -> None:
    """歯車アイコン（設定）"""
    import math
    r_outer = s // 2
    r_inner = int(s * 0.32)
    r_hole  = int(s * 0.16)
    teeth = 8

    pts = []
    for i in range(teeth * 2):
        angle = math.radians(i * 360 / (teeth * 2) - 90)
        r = r_outer if i % 2 == 0 else r_inner
        pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))

    draw.polygon(pts, fill="white")
    # 中心穴
    draw.ellipse(
        [cx - r_hole, cy - r_hole, cx + r_hole, cy + r_hole],
        fill=None, outline=None,
    )
    # 穴を背景色で塗りつぶすため、後で上書きする（色は呼び出し元から渡す）
    return r_hole  # 穴のサイズを返す


ICON_FUNCS = {
    "pen":   _draw_pen,
    "check": _draw_check,
    "chart": _draw_chart,
    "gear":  _draw_gear,
}


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            pass
    return ImageFont.load_default()


def create_image() -> bytes:
    img = Image.new("RGB", (W, H), color="#ECEFF1")
    draw = ImageDraw.Draw(img)

    font = _load_font(110)
    GAP = 8

    for row, col, icon, label, _, color in BUTTONS:
        x0 = col * CW + GAP
        y0 = row * CH + GAP
        x1 = x0 + CW - GAP * 2
        y1 = y0 + CH - GAP * 2

        # 背景
        draw.rounded_rectangle([x0, y0, x1, y1], radius=40, fill=color)

        # アイコン中心（上半分の中央）
        icx = x0 + (CW) // 2
        icy = y0 + CH // 2 - 100
        icon_size = 220

        icon_fn = ICON_FUNCS.get(icon)
        if icon_fn:
            result = icon_fn(draw, icx, icy, icon_size)
            # 歯車の穴を背景色で塗りつぶす
            if icon == "gear" and isinstance(result, int):
                r = result
                draw.ellipse([icx - r, icy - r, icx + r, icy + r], fill=color)

        # ラベル
        l_bbox = draw.textbbox((0, 0), label, font=font)
        lw = l_bbox[2] - l_bbox[0]
        lx = x0 + (CW - lw) // 2
        ly = y0 + CH // 2 + 80
        draw.text((lx, ly), label, font=font, fill="white")

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ─── LINE API ─────────────────────────────────────────────────────────────────

HEADERS = {
    "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
}

RICH_MENU_BODY = {
    "size": {"width": W, "height": H},
    "selected": True,
    "name": "Life-Log メインメニュー",
    "chatBarText": "メニュー",
    "areas": [
        {
            "bounds": {"x": 0,  "y": 0,  "width": CW, "height": CH},
            "action": {"type": "message", "text": "つぶやく"},
        },
        {
            "bounds": {"x": CW, "y": 0,  "width": CW, "height": CH},
            "action": {"type": "message", "text": "タスク整理"},
        },
        {
            "bounds": {"x": 0,  "y": CH, "width": CW, "height": CH},
            "action": {"type": "message", "text": "振り返り"},
        },
        {
            "bounds": {"x": CW, "y": CH, "width": CW, "height": CH},
            "action": {"type": "message", "text": "設定"},
        },
    ],
}


async def setup() -> None:
    async with httpx.AsyncClient(timeout=30) as client:

        # 1. 既存のリッチメニューを削除
        print("既存のリッチメニューを確認中...")
        res = await client.get(f"{LINE_API}/richmenu/list", headers=HEADERS)
        existing = res.json().get("richmenus", [])
        for rm in existing:
            rm_id = rm["richMenuId"]
            await client.delete(f"{LINE_API}/richmenu/{rm_id}", headers=HEADERS)
            print(f"  削除: {rm_id}")

        # 2. リッチメニュー定義を作成
        print("リッチメニューを作成中...")
        res = await client.post(
            f"{LINE_API}/richmenu",
            headers={**HEADERS, "Content-Type": "application/json"},
            content=json.dumps(RICH_MENU_BODY),
        )
        res.raise_for_status()
        rich_menu_id = res.json()["richMenuId"]
        print(f"  作成完了: {rich_menu_id}")

        # 3. 画像を生成してアップロード
        print("メニュー画像を生成中...")
        image_bytes = create_image()
        print(f"  画像サイズ: {len(image_bytes) // 1024} KB")

        print("画像をアップロード中...")
        res = await client.post(
            f"https://api-data.line.me/v2/bot/richmenu/{rich_menu_id}/content",
            headers={**HEADERS, "Content-Type": "image/png"},
            content=image_bytes,
        )
        res.raise_for_status()
        print("  アップロード完了")

        # 4. 全ユーザーにデフォルト設定
        print("デフォルトメニューとして設定中...")
        res = await client.post(
            f"{LINE_API}/user/all/richmenu/{rich_menu_id}",
            headers=HEADERS,
        )
        res.raise_for_status()
        print("  設定完了")

        print("\n[OK] リッチメニューのセットアップが完了しました！")
        print("     LINEアプリのトーク画面下部にボタンが表示されます。")


if __name__ == "__main__":
    asyncio.run(setup())
