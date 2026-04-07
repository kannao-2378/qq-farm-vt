"""从 assets/cao2.png 生成 assets/app_icon.ico。需 Pillow。"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

_ROOT = Path(__file__).resolve().parent.parent
ASSETS = _ROOT / "assets"
SRC = ASSETS / "cao2.png"
OUT = ASSETS / "app_icon.ico"

_ICO_SIZES = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def _trim_rgba(im: Image.Image) -> Image.Image:
    im = im.convert("RGBA")
    a = im.split()[3]
    bbox = a.getbbox()
    if bbox is None:
        return im
    return im.crop(bbox)


def _rgba_on_transparent_square(im: Image.Image) -> Image.Image:
    im = im.convert("RGBA")
    w, h = im.size
    side = max(w, h)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    x = (side - w) // 2
    y = (side - h) // 2
    canvas.paste(im, (x, y), im)
    return canvas


def main() -> None:
    if not SRC.is_file():
        raise SystemExit(f"缺少源图: {SRC}")
    trimmed = _trim_rgba(Image.open(SRC))
    square = _rgba_on_transparent_square(trimmed)
    square.save(OUT, format="ICO", sizes=_ICO_SIZES)
    print("Wrote", OUT, "from", SRC, "final size", square.size, "mode", square.mode)


if __name__ == "__main__":
    main()
