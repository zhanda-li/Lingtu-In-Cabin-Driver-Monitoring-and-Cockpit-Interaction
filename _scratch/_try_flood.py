# -*- coding: utf-8 -*-
"""v5 候选：**闭合轮廓 + 四边泛洪**。只对 `cheer` 跑，扫 (EDGE, WALL) 网格出对照图。

    python _scratch/_try_flood.py

为什么换思路：v4 的「像不像浅蓝卡片」是**逐像素**判据，在 `cheer` 那格上实测
分不开 —— 身体 R-B 中位 +0、背景 −1，最好的一条规则也还有 26% 的身体被判成背景。
**白色身体贴在白色背景上，颜色通道里没有信息**，再怎么调参都没用。

还有信息的地方是**轮廓**：身体和背景交界处哪怕只差 8~20 个灰阶，Sobel 也看得见；
而背景内部是平的，没有边缘。所以改成几何思路：
    1. 求边缘（逐通道 Sobel 取最大，色度边缘也算 —— 白→淡蓝的亮度差很小）
    2. **膨胀**把轮廓焊成墙（补上描边的缺口，这是「闭合」的关键）
    3. 从四条边泛洪；淹不到的地方 = 角色内部
    4. 取最大连通块 + 补洞

⚠️ 这方法有**两个反向的失败模式**，所以必须扫参数看图，不能只看一次结果：
    墙太厚 / 边缘太密 → 整个格子被封死 → 泛洪淹不进去 → 前景 = 全图
    墙太薄 / 边缘太少 → 从缺口漏进去 → 身体被掏空（这是 v1~v4 的老毛病）
"""
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).parent))
from _mk_xiaorui16 import CELLS, CN, SRC   # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OUT = Path(__file__).parent / "_sprite_probe"

NAME = "cheer"


def mag_of(sub):
    """逐通道 Sobel 取最大幅值 —— 色度边缘也算，不看灰度把白→淡蓝抹平。"""
    f = sub.astype(np.float32)
    best = None
    for c in range(3):
        gx = cv2.Sobel(f[..., c], cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(f[..., c], cv2.CV_32F, 0, 1, ksize=3)
        m = np.hypot(gx, gy)
        best = m if best is None else np.maximum(best, m)
    return best


def flood_mask(sub, edge_thr, wall, min_area=200):
    mag = mag_of(sub)
    wall_m = ndimage.binary_dilation(mag > edge_thr, np.ones((3, 3), bool),
                                     iterations=wall)
    lab, n = ndimage.label(~wall_m, structure=np.ones((3, 3)))
    if n == 0:
        return np.ones(sub.shape[:2], bool), 0.0
    border = set(lab[0, :].tolist()) | set(lab[-1, :].tolist()) \
        | set(lab[:, 0].tolist()) | set(lab[:, -1].tolist())
    border.discard(0)
    outside = np.isin(lab, list(border))
    m = ~outside
    m = ndimage.binary_fill_holes(m)
    m = ndimage.binary_opening(m, np.ones((3, 3), bool))
    l2, n2 = ndimage.label(m, structure=np.ones((3, 3)))
    if n2 == 0:
        return m, 0.0
    sz = ndimage.sum(m, l2, range(1, n2 + 1))
    m = l2 == (int(np.argmax(sz)) + 1)
    return m, m.mean()


def main():
    win = next(c for c in CELLS if c[4] == NAME)
    x0, y0, x1, y1, _ = win
    sub = np.asarray(Image.open(SRC).convert("RGB").crop((x0, y0, x1, y1)))
    mag = mag_of(sub)
    print("%s %s 格 %dx%d" % (NAME, CN[NAME], sub.shape[1], sub.shape[0]))
    print("边缘幅值：中位 %.1f  90%% %.1f  99%% %.1f  最大 %.1f"
          % (np.median(mag), np.percentile(mag, 90), np.percentile(mag, 99), mag.max()))

    EDGES = [12, 20, 30, 45]
    WALLS = [1, 2, 3, 4]
    SCALE = 3
    tiles = []
    for e in EDGES:
        row = []
        for w in WALLS:
            m, frac = flood_mask(sub, e, w)
            al = np.clip(ndimage.gaussian_filter(m.astype(np.float32), 0.9) * 1.35, 0, 1)
            bg = np.full(sub.shape, 40, np.uint8)
            over = np.clip(sub.astype(np.float32) * al[..., None]
                           + bg * (1 - al[..., None]), 0, 255).astype(np.uint8)
            t = cv2.resize(cv2.cvtColor(over, cv2.COLOR_RGB2BGR), None,
                           fx=SCALE, fy=SCALE, interpolation=cv2.INTER_NEAREST)
            cv2.putText(t, "e%d w%d  %.0f%%" % (e, w, frac * 100), (6, 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (140, 230, 255), 1, cv2.LINE_AA)
            print("   e=%-3d w=%d  前景占 %.1f%%" % (e, w, frac * 100))
            row.append(t)
        tiles.append(np.hstack(row))
    sheet = np.vstack(tiles)
    p = OUT / "try_flood_cheer.png"
    cv2.imwrite(str(p), sheet)
    print("\n-> %s  %dx%d  （%d 行=EDGE，%d 列=WALL）"
          % (p, sheet.shape[1], sheet.shape[0], len(EDGES), len(WALLS)))
    print("   左边那列 %dx%d 是源图（%s 格）" % (sub.shape[1], sub.shape[0], NAME))


if __name__ == "__main__":
    main()
