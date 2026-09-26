# -*- coding: utf-8 -*-
"""从 小瑞.mp4 做「会动的小瑞」循环动图 -> ui/web/assets/xiaorui_live.webp

素材：ui/图片效果/小瑞.mp4，1280x720 / 24fps / HEVC / 15.04s。
      可用窗口 f96~f121（t≈4.0~5.04s）—— 全身小瑞浮在仪表台上、f110 眨一次眼。
      f122 起他离开画面（判据：该区域「与背景板差异>40 的像素」从 87% 掉到 12.5%）。

🔴 为什么**不做逐像素抠像**（三招都实测过，都不干净，别再试第四遍）：
   1) 时间中位背景板：**证伪** —— 场景会变（背景板自身 std 10.1 灰度级，
      f100~f120 对它的差异 >40 占 87%）。
   2) 本帧局部背景（四边中位色）+ RGB 距离：他的**半透明飘带尾和自发光**在漏，
      背景的**亮散景**（左上白斑、左侧红绿光点）和**挡风玻璃亮带**被判成前景。
   3) 上一招 ∩ 他的包围盒空间先验：仍有左侧彩色散景、顶部亮带、飘带糊边。
   根因是这段背景**高动态范围且会移动**（散景+反光），角色本身还带自发光和半透明件。

✅ 现在用的办法：**他的亮身连通域**（亮度>190 的最大连通域，实测 189x246、面积约 11000，
   逐帧都稳）→ 膨胀把蓝发/耳机/围巾/星星尾巴一并吞进来 → 闭运算 + 填洞 → 高斯羽化。
   这样 alpha 在他身上是 1、背景是 0，而不是「椭圆里连背景一起留着」。

⚠️ 之前那版**椭圆羽化**已废弃：椭圆要装下他 191x249 的本体，实心核就得 ≥207x265，
   而椭圆半径要满足「盒角落在 r<=1」得 rx>=0.62w —— 那时羽化带会越过裁切窗边界，
   变成硬边；他离画面右缘只有 197px，放不下。实测实心核只有 168x206，**会削掉他四肢**。

⚠️ 产物**有 alpha**（RGBA 动图），别烘成深色底。
⚠️ 派生自豆包生成的视频。水印在 x1075~1280 / y650~690，裁切窗完全不含它（也不需要底部字幕）。
⚠️ 本脚本 stdout 会重定向成 GBK，**不要在其中打 emoji**（UnicodeEncodeError）。

Pillow 动画 WebP：save(save_all=True, append_images=..., loop=0)。
"""
import os
import sys
import cv2
import numpy as np
from PIL import Image
from scipy.ndimage import binary_fill_holes

SRC = r"ui/图片效果/小瑞.mp4"
OUT_ASSET = r"ui/web/assets/xiaorui_live.webp"
OUT_DEBUG = r"_scratch/_new_assets"

F0, F1 = 96, 122                 # 半开区间：96..121
BOX = (938, 60, 1200, 372)       # 左,上,右,下 -> 262x312（他 (966,81)-(1185,356)，四边都留了余量）
OUT_W = 200                      # 输出宽（8rem 槽 @DPR2 需 206px）
FPS = 12                         # 26 帧 / 12fps = 2.17s 一个循环，眨眼约 2.2s 一次（自然）
QUALITY = 82
TARGET_KB = 800
BODY_LUM = 190                   # 白身判据
DILATE = 15                      # 膨胀：把蓝发/耳机/围巾/星星尾巴吞进来
BLUR = 4.0                       # 羽化


def body_mask(bgr):
    """亮度>190 的最大连通域 = 他的白身。实测这个量逐帧都稳（189x246 / 面积 ~11000）。"""
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    m = (g > BODY_LUM).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    n, lab, st, cen = cv2.connectedComponentsWithStats(m, 8)
    if n <= 1:
        return None, None
    j = 1 + int(np.argmax(st[1:, 4]))
    if st[j][4] < 800:
        return None, None
    return (lab == j).astype(np.uint8), cen[j]


def silhouette(m):
    """白身 -> 整只小瑞的轮廓。膨胀吞掉蓝部件，闭运算连成一片，再填内部洞。

    ⚠️ 填洞**必须**用 binary_fill_holes（从边界泛洪判"外面"）或等价物。
    我第一版拿「轮廓的包围盒」去填，等于把他整块外接矩形填实了 ——
    alpha>0.5 占 73.6%（≈包围盒满格），出来是个实心块而不是他的轮廓。
    """
    s = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                                (2 * DILATE + 1, 2 * DILATE + 1)))
    s = cv2.morphologyEx(s, cv2.MORPH_CLOSE, np.ones((21, 21), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(s, 8)
    if n > 1:
        j = 1 + int(np.argmax(st[1:, 4]))
        s = (lab == j).astype(np.uint8)
    s = binary_fill_holes(s.astype(bool)).astype(np.uint8)
    return cv2.GaussianBlur(s.astype(np.float32), (0, 0), BLUR)


def main():
    cap = cv2.VideoCapture(SRC)
    if not cap.isOpened():
        sys.exit("打不开 " + SRC)
    x0, y0, x1, y1 = BOX
    W, H = x1 - x0, y1 - y0

    got = []                                     # [(idx, frame, centroid|None)]
    for i in range(F0, F1):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, f = cap.read()
        if not ok:
            sys.exit("取不到 f%d" % i)
        c = f[y0:y1, x0:x1].copy()
        bm, cen = body_mask(c)
        got.append((i, c, None if bm is None else cen))
    cap.release()

    bad = [i for i, _, cen in got if cen is None]
    if bad:
        # 他在这个窗口末尾退场：那些帧根本没有本体可抠，直接丢掉，
        # 留着只会在循环里闪一下空白。
        print("丢掉 %d 帧（没测到白身，人已经在退场）: %s"
              % (len(bad), ",".join("f%d" % i for i in bad)))
    got = [(i, c, cen) for i, c, cen in got if cen is not None]
    if len(got) < 8:
        sys.exit("可用帧只剩 %d，窗口选错了" % len(got))
    print("可用 %d 帧 f%d~f%d" % (len(got), got[0][0], got[-1][0]))

    # 消掉整段的漂移，否则循环接回时会跳一下
    cc = np.array([cen for _, _, cen in got], np.float32)
    ref = cc.mean(0)
    print("白身质心漂移 %.1f,%.1f px -> 逐帧平移消除"
          % (np.ptp(cc[:, 0]), np.ptp(cc[:, 1])))

    frames, stats, sils = [], [], []
    for k, (i, c, cen) in enumerate(got):
        sh = ref - cen
        M = np.float32([[1, 0, sh[0]], [0, 1, sh[1]]])
        c2 = cv2.warpAffine(c, M, (W, H), flags=cv2.INTER_LINEAR,
                            borderMode=cv2.BORDER_REPLICATE)
        bm, _ = body_mask(c2)
        if bm is None:
            sys.exit("f%d 平移后反而丢了白身，逻辑有问题" % i)
        al = silhouette(bm)
        sils.append(al > 0.5)
        ys, xs = np.where(al > 0.5)
        stats.append((i, len(ys), xs.max() - xs.min() + 1, ys.max() - ys.min() + 1,
                      xs.min(), ys.min()))
        rgba = np.dstack([cv2.cvtColor(c2, cv2.COLOR_BGR2RGB),
                          (np.clip(al, 0, 1) * 255).astype(np.uint8)])
        im = Image.fromarray(rgba, "RGBA")
        th = max(1, int(round(H * OUT_W / W)))
        frames.append(im.resize((OUT_W, th), Image.LANCZOS))

    for k in (0, len(stats) // 2, len(stats) - 1):
        i, n, bw, bh, bx, by = stats[k]
        edge = "  <== 贴到裁切窗边了" if (bx <= 1 or by <= 1) else ""
        print("  f%d 轮廓 %dx%d @(%d,%d)  alpha>.5 占 %4.1f%%%s"
              % (i, bw, bh, bx, by, 100.0 * n / (W * H), edge))

    # 首尾轮廓重合度：低的话循环接回去会"弹"一下
    a, b = sils[0], sils[-1]
    iou = (a & b).sum() / float((a | b).sum())
    print("首尾轮廓 IoU = %.3f（>0.9 正循环看不出来；低就该改 ping-pong）" % iou)

    os.makedirs(os.path.dirname(OUT_ASSET), exist_ok=True)
    frames[0].save(OUT_ASSET, "WEBP", save_all=True, append_images=frames[1:],
                   duration=int(round(1000 / FPS)), loop=0, quality=QUALITY,
                   method=6)

    # 静帧：给 prefers-reduced-motion 用。
    # ⚠️ CSS 关不掉 <img> 里的动画 WebP（CSS 只能关 CSS 动画），只能靠 JS 换图。
    # 用**同一段素材的第 0 帧**而不是别的静态图 —— 换过去时看不出跳变。
    # 计划里原本写的是退回 xiaorui_hello.png，那是另一个姿势，会突兀地换脸。
    frames[0].save(os.path.splitext(OUT_ASSET)[0] + "_still.png")
    print("写出 %s_still.png（reduced-motion 降级用）"
          % os.path.splitext(OUT_ASSET)[0])
    kb = os.path.getsize(OUT_ASSET) / 1024
    print("写出 %s  %dx%d  %d 帧  %.1f KB"
          % (OUT_ASSET, frames[0].width, frames[0].height, len(frames), kb))
    if kb > TARGET_KB:
        print("[warn] 超过目标 %d KB —— 降 quality 或减帧，不要降尺寸" % TARGET_KB)

    ui = np.array([24, 14, 8], np.float32)
    tiles = []
    for k in range(0, len(frames), max(1, len(frames) // 6)):
        a = np.asarray(frames[k]).astype(np.float32)
        al = a[..., 3:4] / 255.0
        comp = (a[..., :3] * al + ui * (1 - al)).astype(np.uint8)
        cv2.putText(comp, "f%d" % stats[k][0], (5, 16), cv2.FONT_HERSHEY_SIMPLEX,
                    0.45, (120, 220, 255), 1, cv2.LINE_AA)
        tiles.append(cv2.cvtColor(comp, cv2.COLOR_RGB2BGR))
    sep = np.full((tiles[0].shape[0], 5, 3), 255, np.uint8)
    row = []
    for t in tiles:
        row += [t, sep]
    out = np.hstack(row[:-1])
    os.makedirs(OUT_DEBUG, exist_ok=True)
    cv2.imwrite(os.path.join(OUT_DEBUG, "loop_frames.png"), out)
    print("对照图 loop_frames.png %dx%d" % (out.shape[1], out.shape[0]))


if __name__ == "__main__":
    main()
