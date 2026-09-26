"""生成界面的图片资产（目前只有背景一张）。

**为什么要有这个脚本**

界面背景是一张实拍照片（黄昏山路），本项目自己生成不出来。参考图放在
`ui/图片效果/`，那是用户自己的素材，从里面裁一块出来用是正当的，而且
色调和构图跟参考图天然一致 —— 比我自己调一个渐变更接近"做到类似这种效果"。

跑一次就行：

    python ui/make_assets.py

产出 `ui/web/assets/bg.jpg`（1920x1080）。**这一步不是必需的**：
`web/style.css` 在图片缺失时会退回纯渐变背景，界面不会因为少这张图起不来。

换成你自己的照片：直接把任意图片存成 `ui/web/assets/bg.jpg` 覆盖即可，
CSS 那边不用动。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "ui" / "图片效果"
OUT = ROOT / "ui" / "web" / "assets" / "bg.jpg"

# 裁哪一块：5.png 右下角那片湖面 + 盘山公路。这是参考图里唯一一块
# 既干净（没有卡片/文字压在上面）又横向够宽的照片区域。
CROP_SRC = "5.png"
CROP_BOX = (1290, 420, 1672, 700)     # left, top, right, bottom

W, H = 1920, 1080


def build() -> int:
    try:
        from PIL import Image, ImageEnhance, ImageFilter
    except ImportError:
        print("没装 Pillow（pip install pillow），跳过。界面会用纯渐变背景。")
        return 1

    src = SRC_DIR / CROP_SRC
    if not src.exists():
        print(f"找不到 {src}，跳过。")
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    im = Image.open(src).convert("RGB").crop(CROP_BOX)

    # 1) 按宽度放大到 1920，再从中间竖裁到 1080（cover）。
    #    **不左右镜像补齐**：试过，山路镜像之后接缝处会合成一个奇怪的"Y"字路口，
    #    一眼就看出是拼的。竖裁只损失上下各 164 px，构图没事。
    scale = W / im.width
    im = im.resize((W, max(H, round(im.height * scale))), Image.LANCZOS)
    top = max(0, (im.height - H) // 2)
    canvas = im.crop((0, top, W, top + H))

    # 2) 压暗 + 降饱和：背景是**垫底**的，卡片要压得住它。
    #    这一步放进图片里而不是 CSS，是为了在弱显卡上少一层实时滤镜。
    canvas = ImageEnhance.Brightness(canvas).enhance(0.60)
    canvas = ImageEnhance.Color(canvas).enhance(0.80)
    canvas = canvas.filter(ImageFilter.GaussianBlur(1.2))

    canvas.save(OUT, "JPEG", quality=88, optimize=True)
    print(f"写好了：{OUT.relative_to(ROOT)}  ({W}x{H}, {OUT.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(build())
