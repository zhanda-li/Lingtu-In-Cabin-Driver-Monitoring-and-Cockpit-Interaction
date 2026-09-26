"""从 ui/图片效果/8.png 做出界面要用的奇瑞标。

8.png 是**竖排**深灰标（椭圆在上、"CHERY" 在下），而参考图的顶栏是**横排**白标。
所以要拆开重排。

同时把它从"深灰画在白底上"转成"白色画在透明上"：
  8.png 没有 alpha 通道（实测 mode=RGB，亮度 239~255 是背景），所以
  alpha = 把亮度按 [ink..bg] 归一化后取反 —— 这样反锯齿边自然保留，
  而且**白色 + alpha** 比"保留原深灰"好用：要深色时 CSS 一句 invert(1) 就行。

输出两份：
  chery_logo.png  横排锁定版（椭圆 + CHERY），顶栏用
  chery_mark.png  只有椭圆，手机/小尺寸处用
"""
from pathlib import Path

import numpy as np
from PIL import Image

SRC = Path("ui/图片效果/8.png")
OUTDIR = Path("ui/web/assets")
BG, INK = 245.0, 45.0          # 实测：背景 239~255，墨色约 45
GAP_RATIO = 0.55               # 椭圆右缘到 "C" 左缘的空隙，按椭圆高取比例

src = Image.open(SRC).convert("RGB")
a = np.asarray(src).astype(np.float32)
lum = a.mean(axis=2)
alpha = np.clip((BG - lum) * 255.0 / (BG - INK), 0, 255)

ink = alpha > 24
rows = ink.sum(axis=1)
# 找行方向的空白带 -> 把椭圆和字标切开
bands, run = [], 0
for i, v in enumerate(rows):
    if v <= 2:
        run += 1
    else:
        if run > 6:
            bands.append((i - run, i - 1))
        run = 0
print("行空白带:", bands)
# ⚠️ 第一段空带是**上边距**（实测 (0,80)），不是椭圆和字标之间的那道。
#   要挑的是"上下都有墨"的那一段。挑错了就会切出一张空图（第一次就这么崩的）。
inner = [b for b in bands if b[0] > 0 and b[1] < a.shape[0] - 1]
if not inner:
    raise SystemExit("8.png 里找不到椭圆与字标之间的空白带，布局变了")
cut = inner[0][0]
print(f"椭圆在第 0~{cut - 1} 行，字标在第 {inner[0][1] + 1}~ 行")


def crop_ink(y0, y1):
    m = ink[y0:y1]
    cs = np.where(m.sum(axis=0) > 0)[0]
    rs = np.where(m.sum(axis=1) > 0)[0]
    yy0, yy1 = y0 + rs.min(), y0 + rs.max() + 1
    xx0, xx1 = cs.min(), cs.max() + 1
    rgb = np.full((yy1 - yy0, xx1 - xx0, 3), 255, np.uint8)
    return Image.fromarray(np.dstack([rgb, alpha[yy0:yy1, xx0:xx1].astype(np.uint8)]), "RGBA")


mark = crop_ink(0, cut)
word = crop_ink(cut, a.shape[0])
print(f"椭圆 {mark.size}  字标 {word.size}")

mark.save(OUTDIR / "chery_mark.png")


def trim(img):
    b = img.getchannel("A").point(lambda v: 255 if v > 16 else 0).getbbox()
    return img.crop(b)


mark, word = trim(mark), trim(word)
# 横排：字标按参考图的比例缩到椭圆高的 0.56 左右，再垂直居中对齐
# （参考图顶栏实测：椭圆 ~30 px 高、CHERY ~22 px，比例 0.73；
#   但那是已经缩过的小图，这里按视觉重心取 0.62 —— 实测看着最像。）
target_h = max(8, int(round(mark.height * 0.62)))
word = word.resize((max(1, round(word.width * target_h / word.height)), target_h),
                   Image.LANCZOS)
gap = int(round(mark.height * GAP_RATIO))
W = mark.width + gap + word.width
H = max(mark.height, word.height)
canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
canvas.paste(mark, (0, (H - mark.height) // 2), mark)
canvas.paste(word, (mark.width + gap, (H - word.height) // 2), word)
canvas.save(OUTDIR / "chery_logo.png")
print(f"写出 chery_logo.png {canvas.size}  "
      f"{(OUTDIR / 'chery_logo.png').stat().st_size / 1024:.1f} KB   "
      f"chery_mark.png {mark.size}  "
      f"{(OUTDIR / 'chery_mark.png').stat().st_size / 1024:.1f} KB")
