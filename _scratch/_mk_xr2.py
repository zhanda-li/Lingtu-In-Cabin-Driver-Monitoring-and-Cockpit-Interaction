# -*- coding: utf-8 -*-
"""从 `ui/图片效果/小瑞.jpg`（4 个全身姿势）和 `小瑞表情.jpg`（6 个表情）里
抠出**透明底**的小瑞素材。

    D:\Anaconda3\envs\dms\python.exe _scratch\_mk_xr2.py            # 出图
    D:\Anaconda3\envs\dms\python.exe _scratch\_mk_xr2.py --probe    # 只看数，不落盘

⚠️ **这里最大的坑是「白底上的白身体」**：小瑞本体就是白的，背景也是白的，
   所以**不能按亮度抠**（`g < 240` 那种）—— 那会把身体抠没、只剩眼睛和蓝头发。
   用的是 `cv2.grabCut`：它按**颜色分布**分类，白身体和白背景虽然都是白，
   但身体边缘那圈软阴影/描边把两者分开了，所以能分开。
   兜底方案是「从四角漫水填充」（`--flood`），两个都跑，比较前景占比。

⚠️ **棋盘格那几张（小瑞细节4~10）不能用来出素材**：它们的"透明底"是**画上去的**
   棋盘格像素，不是 alpha 通道（.jpg 存不了 alpha）。要抠就得先把棋盘格去掉，
   而棋盘格的灰方块和小瑞身体的灰阴影同色，抠出来一定脏。当**风格参考**看就好。

⚠️ cv2.imread 在 Windows 上**读不了中文路径**（按 ANSI 码页解析），必须走
   `imdecode(np.fromfile(...))`。这个坑在 `ui/图片效果/` 这个目录上必踩。

⚠️ 每张脸/每个姿势**单独一列**，用小瑞自己那个白边当间隙切开即可，不需要
   `cv2.connectedComponentsWithStats` 再合并 —— 相邻两个姿势会**粘成一个连通域**
   （实测 4 个姿势粘成了 2 块），那是分不开的，得靠**投影**找缝。
"""
import os
import sys
import numpy as np
import cv2

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "ui", "图片效果")
OUT = os.path.join(ROOT, "_scratch", "_xr_cut")
PROBE = "--probe" in sys.argv
FLOOD = "--flood" in sys.argv
WMART = 0.93          # 底部 7% 是「豆包AI生成」水印，一律先切掉


def imread_u(p):
    """cv2.imread 读不了中文路径。"""
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)


def bgmask(im, dthr=16, sthr=18):
    """「这一块不是背景」的二值图。

    ⚠️ **不能用固定阈值** `g < 232` 之类：`小瑞.jpg` 的背景是**从上到下由白渐到
       浅灰的地面**，底部整片都低于任何合理阈值 —— 实测那样算 2278 列里只剩 85 列
       是空的，四个姿势粘成一段、投影切格当场失效。
    正解是**逐行中位数当背景模型**：背景沿**行**方向几乎恒定（只有竖直渐变），
    所以每一行的中位数就是那一行的背景色，减掉它就把渐变消掉了，只剩"和背景不一样"
    的像素。判别用「比背景暗」**或**「有色」（小瑞是蓝的，背景是中性灰）。
    """
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY).astype(np.float32)
    bg = np.median(g, axis=1, keepdims=True)
    sp = (im.max(axis=2).astype(np.float32) - im.min(axis=2).astype(np.float32))
    m = (((bg - g) > dthr) | (sp > sthr)).astype(np.uint8)
    return cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))


def split_cells(mask, ncol, nrow, min_sep_frac=0.55):
    """把整张图切成 ncol x nrow 格，返回 [(x0,x1,y0,y1)]（行优先）。

    ⚠️ **为什么不是"找空列"**：`小瑞.jpg` 那四个姿势是**挨着的**（没有一整列是空的），
       所以切不开。改成**找投影的谷底**：把每列的前景计数平滑一下，
       在 [5%,95%] 里挑 ncol-1 个**最深**的局部极小当边界，并要求彼此至少隔
       `总宽/ncol * min_sep_frac`，免得两个谷底挤在一起。
       实测四个姿势的谷底落在 x=558 / 1072 / 1591（间距 514/519），很规整。
    """
    h, w = mask.shape

    def bounds(proj, n_want, total):
        if n_want <= 1:
            return []
        k = max(5, total // 40) | 1
        cs = np.convolve(proj.astype(np.float32), np.ones(k) / k, "same")
        lo, hi = int(total * 0.05), int(total * 0.95)
        sep = int(total / n_want * min_sep_frac)
        loc = [x for x in range(lo + 1, hi) if cs[x] <= cs[x - 1] and cs[x] <= cs[x + 1]]
        loc.sort(key=lambda x: cs[x])              # 最深的谷底排前面
        pick = []
        for x in loc:
            if all(abs(x - p) >= sep for p in pick):
                pick.append(x)
                if len(pick) == n_want - 1:
                    break
        if len(pick) != n_want - 1:
            raise SystemExit("投影切格失败：只找到 %d 个谷底，要 %d 个"
                             % (len(pick), n_want - 1))
        return sorted(pick)

    xs = [0] + bounds(mask.sum(axis=0), ncol, w) + [w]
    ys = [0] + bounds(mask.sum(axis=1), nrow, h) + [h]
    return [(xs[c], xs[c + 1], ys[r], ys[r + 1])
            for r in range(nrow) for c in range(ncol)]


def cut_grabcut(bgr):
    """grabCut 取前景 alpha。返回 0/255 的 mask。"""
    h, w = bgr.shape[:2]
    m = np.zeros((h, w), np.uint8)
    rect = (max(2, int(w * 0.02)), max(2, int(h * 0.02)),
            max(4, int(w * 0.96)), max(4, int(h * 0.96)))
    bgm = np.zeros((1, 65), np.float64)
    fgm = np.zeros((1, 65), np.float64)
    cv2.grabCut(bgr, m, rect, bgm, fgm, 4, cv2.GC_INIT_WITH_RECT)
    return np.where((m == cv2.GC_FGD) | (m == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)


def cut_flood(bgr, tol=9):
    """兜底：从四角漫水填背景，填不到的算前景。"""
    h, w = bgr.shape[:2]
    ff = bgr.copy()
    m = np.zeros((h + 2, w + 2), np.uint8)
    for seed in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
        if m[seed[1] + 1, seed[0] + 1] == 0:
            cv2.floodFill(ff, m, seed, (0, 0, 0),
                          (tol,) * 3, (tol,) * 3,
                          cv2.FLOODFILL_MASK_ONLY | cv2.FLOODFILL_FIXED_RANGE | (255 << 8))
    return np.where(m[1:-1, 1:-1] == 0, 255, 0).astype(np.uint8)


def clean(mask, min_area_frac=0.004):
    """去小碎块 + 填内部孔洞 + 收 1px 毛边。"""
    n, lab, stats, _ = cv2.connectedComponentsWithStats((mask > 0).astype(np.uint8), 8)
    if n > 1:
        keep = 1 + int(np.argmax(stats[1:, 4]))
        mask = np.where(lab == keep, 255, 0).astype(np.uint8)
    # 填洞：把 mask 反相的连通域里"碰不到边界"的那些补回来
    inv = (mask == 0).astype(np.uint8)
    n2, lab2 = cv2.connectedComponents(inv, 4)
    edge = set(np.unique(np.concatenate([lab2[0, :], lab2[-1, :], lab2[:, 0], lab2[:, -1]])))
    for i in range(1, n2):
        if i not in edge:
            mask[lab2 == i] = 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,
                            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    return mask


def trim(mask, pad=6):
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    x0, x1 = xs.min(), xs.max() + 1
    y0, y1 = ys.min(), ys.max() + 1
    return x0, x1, y0, y1


def cut_one(bgr):
    m = cut_flood(bgr) if FLOOD else cut_grabcut(bgr)
    m = clean(m)
    t = trim(m)
    if t is None:
        return None, 0.0
    x0, x1, y0, y1 = t
    bgr = bgr[y0:y1, x0:x1]
    m = m[y0:y1, x0:x1]
    # 羽化 1px：硬边贴到浅色 UI 上会有锯齿
    a = cv2.GaussianBlur(m, (3, 3), 0.6).astype(np.float32) / 255.0
    rgba = np.dstack([bgr, (np.clip(a, 0, 1) * 255).astype(np.uint8)])
    return rgba, float((m > 0).mean())


def resize_h(rgba, h):
    sc = h / rgba.shape[0]
    return cv2.resize(rgba, (max(1, int(round(rgba.shape[1] * sc))), h),
                      interpolation=cv2.INTER_AREA)


def sheet(items, cols, h, path):
    """拼一张对照图，压在**洋红底**上 —— 没抠干净的地方一眼就看得见。"""
    ims = [resize_h(a, h) for a, _ in items]
    cw = max(i.shape[1] for i in ims) + 16
    rows = (len(ims) + cols - 1) // cols
    W, H = cw * cols, (h + 16) * rows
    out = np.full((H, W, 3), (255, 0, 255), np.uint8)
    for k, im in enumerate(ims):
        r, c = divmod(k, cols)
        y, x = r * (h + 16) + 8, c * cw + (cw - im.shape[1]) // 2
        a = im[:, :, 3:4].astype(np.float32) / 255.0
        bg = out[y:y + im.shape[0], x:x + im.shape[1]].astype(np.float32)
        out[y:y + im.shape[0], x:x + im.shape[1]] = (
            im[:, :, :3].astype(np.float32) * a + bg * (1 - a)).astype(np.uint8)
    cv2.imencode(".png", out)[1].tofile(path)
    return out.shape[:2]


def main():
    os.makedirs(OUT, exist_ok=True)
    jobs = [
        ("小瑞.jpg", 4, 1, "body", 640, 4),
        ("小瑞表情.jpg", 3, 2, "face", 460, 3),
    ]
    for fn, nc, nr, tag, H, sheetcols in jobs:
        im = imread_u(os.path.join(SRC, fn))
        h = im.shape[0]
        im = im[:int(h * WMART)]                       # 切掉水印带
        cells = split_cells(bgmask(im), nc, nr)
        print("%s  %dx%d  ->  %d 格" % (fn, im.shape[1], im.shape[0], len(cells)))
        got = []
        for k, (x0, x1, y0, y1) in enumerate(cells):
            pad = 10
            x0, y0 = max(0, x0 - pad), max(0, y0 - pad)
            x1, y1 = min(im.shape[1], x1 + pad), min(im.shape[0], y1 + pad)
            rgba, frac = cut_one(im[y0:y1, x0:x1])
            if rgba is None:
                print("   #%d  空" % (k + 1))
                continue
            name = "xr_%s_%d.png" % (tag, k + 1)
            print("   #%d  %-14s %4dx%-4d  前景占比 %.1f%%"
                  % (k + 1, name, rgba.shape[1], rgba.shape[0], frac * 100))
            got.append((rgba, name))
            if not PROBE:
                cv2.imencode(".png", resize_h(rgba, H))[1].tofile(os.path.join(OUT, name))
        sh = os.path.join(ROOT, "runs", "_xr_%s_sheet.png" % tag)
        print("   对照图 %s  %s" % (sheet(got, sheetcols, 300, sh), sh))


main()
