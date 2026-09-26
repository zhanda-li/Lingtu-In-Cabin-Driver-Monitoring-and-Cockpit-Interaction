# -*- coding: utf-8 -*-
"""把 14.png（同济大学汽车与能源学院院徽）做成顶栏能用的两张 PNG。

    D:\Anaconda3\envs\dms\python.exe _scratch/_mk_tongji.py

## 为什么要这个脚本，而不是直接 <img src="14.png"> 了事

三条，都是硬的：

1. **源图没进 web 根**。`ui/图片效果/` 不在 `/static` 路由下（那是素材原图目录，
   进过 git 的是 `ui/web/assets/` 那一份）。顶栏的图必须走 `/static/assets/`。
2. **2685x580 是原尺寸，太大**。显示高度只有 2.45rem（≈37px CSS，DPR=2 时 73.5px），
   按 300px 高输出已经留了 4 倍余量。原图直接上等于让浏览器每次下采样 400KB。
3. **要两张**（深色主题一张、浅色主题一张），和 lingtu 标志 / CHERY 那三组
   同一个机制（`html .on-light` / `html[data-theme="light"] .on-dark`，
   见 style.css 里那段全局说明）。

## 形状完全由 alpha 表达 —— 所以这次只重上色，不重抠

量过源图（`_probe` 那段结论写在这儿，免得下一个人再去量一遍）：

    alpha 1..64    90022 像素   RGB 均值 (242.8, 241.9, 241.2)
    alpha 64..192  14578 像素   RGB 均值 ( 31.8,  25.7,  24.3)
    alpha 192..254 89881 像素   RGB 均值 ( 33.4,  24.5,  22.4)
    alpha 255     281932 像素   RGB 均值 ( 34.5,  24.1,  21.4)

**边缘像素的 RGB 是近白的** —— 这说明源图是从"墨压在白底上"导出的
（半透明处 RGB 已经朝白偏了，那是导出时留下的背景残影，不是形状信息）。
形状信息**只在 alpha 里**。所以：

- 直接把 RGB 覆盖成目标色、alpha 一个字节不动 —— 边缘**反而比原图更干净**
  （原图那些近白的半透明像素压在深色底上会发灰）；**这不是"有损换色"，
  是把导出时混进去的白底残影洗掉。**
  这一点和 `_mk_chery_ink.py` 不同：那里源图 RGB 已经只有 1~29 个唯一值，
  换色是**逐字节无损**的；这里源图 RGB 是脏的，所以照抄不了它那句
  「逐像素断言 alpha 与原图完全相同」之外的任何结论 —— 断言照做，
  理由不同。
- 缩放在 **alpha 单通道**上做，不在 RGBA 上做。RGBA 直接 LANCZOS 会把
  近白的边缘像素和实心墨混起来，描边发灰；只缩 alpha 再用同一个 alpha
  配纯色，边缘永远是"目标色 × 覆盖率"。
  （顺带也就避开了 straight-alpha 图像缩放的经典坑：PIL 的 RGBA resize
  不预乘，直接缩会在边缘混进背景色。）

## 目标色

- 浅色版 `tongji_logo_ink.png`：**`--ink` = #0E2A4A**，和 `.brand-logo` 那两张
  深色版同一个取色理由（"它跟字一个颜色"，见 `_mk_chery_ink.py`）。
- 深色版 `tongji_logo.png`：**纯白**。和 `chery_mark.png` 一样是白墨。

⚠️ 命名沿用全库的约定：**不带后缀的那张是"深色主题用的"**，
带 `_ink` 的是"浅色主题用的"。别按"哪张更常显"去命名。
"""

import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "ui" / "图片效果" / "14.png"
OUT = ROOT / "ui" / "web" / "assets"

# 输出高度。显示高度 2.45rem（= .lingtu-mark 的高度，见 style.css），
# DPR=2 时 73.5px —— 300px 是 4 倍余量，再大就是白给的体积。
OUT_H = 300
WHITE = (255, 255, 255)
INK = (0x0E, 0x2A, 0x4A)          # 浅色主题的 --ink，见 style.css


def main() -> int:
    im = Image.open(SRC).convert("RGBA")
    a = np.array(im)
    alpha = a[..., 3]

    w, h = im.size
    scale = OUT_H / h
    out_w = int(round(w * scale))
    print(f"源图 {w}x{h}  宽高比 {w/h:.4f}")
    print(f"输出 {out_w}x{OUT_H}  （高 {OUT_H}px = 显示 2.45rem 的 {OUT_H/73.5:.1f} 倍余量）")

    # 只缩 alpha：见模块开头第 2 条理由
    al = Image.fromarray(alpha, mode="L").resize((out_w, OUT_H), Image.LANCZOS)
    al = np.array(al)
    print(f"  alpha 覆盖：不透明 {100*(al==255).mean():.1f}%  "
          f"完全透明 {100*(al==0).mean():.1f}%")

    made = {}
    for name, rgb in [("tongji_logo.png", WHITE), ("tongji_logo_ink.png", INK)]:
        out = np.zeros((OUT_H, out_w, 4), np.uint8)
        out[..., 0], out[..., 1], out[..., 2] = rgb
        out[..., 3] = al
        p = OUT / name
        Image.fromarray(out, mode="RGBA").save(p, optimize=True)
        made[name] = np.array(Image.open(p).convert("RGBA"))[..., 3]
        print(f"  {name:24s} {p.stat().st_size/1024:6.1f} KB  RGB={rgb}")

    # 两张的 alpha 必须**逐字节相同** —— 否则切主题时标志会跳（形状动了），
    # 而这件事在截图上是看不出来的（只是"好像有点不一样"）。
    # 这是 _mk_mark_ink.py 立的规矩，照做。
    d = int(np.abs(made["tongji_logo.png"].astype(int)
                   - made["tongji_logo_ink.png"].astype(int)).max())
    print(f"\n两张 alpha 最大逐像素差 = {d}  {'OK' if d == 0 else '!! 形状漂了，切主题会跳'}")
    return 0 if d == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
