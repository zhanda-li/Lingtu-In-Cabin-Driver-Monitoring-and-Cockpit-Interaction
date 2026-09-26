# -*- coding: utf-8 -*-
"""给 Chery 那两张**白墨**图各做一张深色版（浅底上用）。

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch/_mk_chery_ink.py

## 为什么要第二张

`chery_logo.png` / `chery_mark.png` 是**白墨透明底**（从 ui/图片效果/8.png 抠的，
生成脚本 `_mk_logo.py`），当初全站都是深色底，白墨正好。
2026-09-23 开始刷 12.png 那套亮色调之后，白墨压在近白底上**等于消失** ——
nav 页左下角那个 CHERY 就是这么没的（截图上只剩一道几乎看不见的灰影）。

## 为什么这次只做"换色"、不重做抠图

量过：两张图的实心像素 RGB 唯一值分别只有 **1 个**（chery_mark，纯 255）和
**29 个**（chery_logo，227~255，是抠图时留下的一点点辉光渐变），
而且**都没有一个 alpha=255 的像素** —— 形状**全部**由 alpha 表达。

这就意味着换色是**无损**的：alpha 一个字节都不用动，只把 RGB 写成目标色即可。
所以这个脚本**不做任何阈值/连通域**那一套，它只是在重新上一色，
并且**逐像素断言 alpha 与原图完全相同** —— 形状漂了会当场报错，不会静默输出一张歪图。

    ⚠️ 这一点和 lingtu 标志**不一样**：那个是"深蓝外环 + 浅蓝飘带"的**双层**设计，
       换色得按亮度重新映射（见 _mk_mark_ink.py）。Chery 这些是单色白墨，
       直接刷一个色就对了 —— 别把两件事混起来。

## 目标色

取**浅色主题的 `--ink`（#0E2A4A）**，不是随手挑的深灰：这两个标志在页面上
和正文文字是同一层"墨"，用 `--ink` 就是"它跟字一个颜色"，
而且以后要是调 `--ink`，这里跟着重跑一遍就是一致的。
"""

import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ASSETS = Path("ui/web/assets")
INK = (14, 42, 74)          # #0E2A4A = style.css 里 html[data-theme="light"] 的 --ink
PAIRS = [("chery_logo.png", "chery_logo_ink.png"),
         ("chery_mark.png", "chery_mark_ink.png")]


def main():
    for src_name, dst_name in PAIRS:
        src = ASSETS / src_name
        dst = ASSETS / dst_name
        im = Image.open(src).convert("RGBA")
        a = np.asarray(im)
        alpha = a[..., 3].copy()

        out = np.zeros_like(a)
        out[..., 0], out[..., 1], out[..., 2] = INK
        out[..., 3] = alpha
        Image.fromarray(out, "RGBA").save(dst)

        # ★ 逐像素断言 alpha 没动 —— 换色只许改 RGB，形状是 alpha 说了算的。
        back = np.asarray(Image.open(dst).convert("RGBA"))
        diff = int(np.abs(back[..., 3].astype(int) - alpha.astype(int)).max())
        assert diff == 0, "%s 的 alpha 被改动了（最大差 %d）" % (dst_name, diff)
        # 颜色也必须真的是目标色（在有形状的地方）
        solid = alpha > 8
        if solid.any():
            got = back[..., :3][solid]
            assert (got == np.array(INK)).all(), "%s 颜色不是目标色" % dst_name

        print("  OK  %-22s -> %-26s %s  alpha 逐像素相同  %.1f KB"
              % (src_name, dst_name, Image.open(dst).size,
                 dst.stat().st_size / 1024))

    print("\n**两张深色版都写出来了**（浅色主题下由 CSS 二选一，"
          "和 lingtu 标志同一套 .on-dark / .on-light 机制）")


if __name__ == "__main__":
    main()
