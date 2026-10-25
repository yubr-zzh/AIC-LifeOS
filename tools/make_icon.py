# -*- coding: utf-8 -*-
"""把 tools/assets/claude3.png 生成 Windows 多尺寸图标 tools/assets/lifeos.ico。

做法：先按短边居中裁剪成正方形（cover，保证小尺寸下图标占满画幅、不留白边），
再由 Pillow 一次性导出 16/24/32/48/64/128/256 多尺寸 .ico；
另外输出 icon_preview_256.png 供肉眼核对裁剪效果。

换封面图后，把新图覆盖为 tools/assets/claude3.png，再运行：
    .venv\\Scripts\\python.exe tools\\make_icon.py
"""
from pathlib import Path

from PIL import Image

ASSETS = Path(__file__).resolve().parent / "assets"
SRC = ASSETS / "claude3.png"
ICO = ASSETS / "lifeos.ico"
PREVIEW = ASSETS / "icon_preview_256.png"

SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def main() -> int:
    img = Image.open(SRC).convert("RGBA")
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    square = img.crop((left, top, left + side, top + side))
    print(f"原图 {w}x{h} -> 居中裁剪正方形 {side}x{side}（左{left} 上{top}）")

    square.save(ICO, format="ICO", sizes=SIZES)
    square.resize((256, 256), Image.LANCZOS).save(PREVIEW, format="PNG")
    print(f"已生成: {ICO}")
    print(f"预览图: {PREVIEW}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
