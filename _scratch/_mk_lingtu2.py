# -*- coding: utf-8 -*-
"""把 `ui/图片效果/灵途智行标志.png` 做成顶栏左上角那个品牌图（**整张，不裁**）。

    D:\Anaconda3\envs\dms\python.exe _scratch/_mk_lingtu2.py

产出两张（**几何/alpha 逐像素相同**，切主题时不会跳）：

    ui/web/assets/lingtu_lockup.png       深色主题用：原图
    ui/web/assets/lingtu_lockup_ink.png   浅色主题用：★ **也是原图，一个像素不改**

★★ 2026-09-25 用户拍板：**整张原图直接贴，不管看不看得见**。
   问过、选项摆清楚了，用户选了最"严格"的那条 —— 这是我的返工第 **二** 次，
   别再自作聪明往回填色。背景（为什么会有这个问题）见下面那段 ⚠️。

★ 2026-09-24 晚**重写**（用户原话：「我给了灵途智行的标志 直接整张图替换所有
左上角出现灵途智行标的部分」）。上一版只从这张图里**切出那个 G**，剩下的
「灵途智行」四个字用 HTML 文字（`.lingtu-txt b/em`）在顶栏里排两行。
现在整张 lockup（G + 灵途智行 + 与你同行 + 那几道细线）**当成一张图直接放上去**，
`.lingtu-txt` 那两行字连同它的 CSS 一起删掉 —— 字在图里，再排一遍就是同一句话
写两遍，而且字体和间距再也对不上原图。

⚠️ 因此那张图的 alt **必须写**（`灵途智行 · 与你同行`）：原来留空是因为旁边
   就有真文字、读屏软件再念一遍是同义重复；现在**图就是名字本身**，留空等于
   把品牌名从无障碍树里整个抹掉。

⚠️ 为什么会冒出"浅色要不要上色"这个问题（**量过的事实，别再重做一遍**）：
   这张素材是**给深色底做的** —— 实测「灵途智行」那半个文字区 **93% 是纯白**
   （sat 中位 0.000、亮度 255），只有一圈很淡的蓝描边；G 的左弧也有一半是纯白。
   而顶栏实测底色是 `#F9FAF8`，近白。所以原图直接放上去，
   **字和 G 的白弧会整片消失，只剩一道蓝飘带**（合成图见 `runs/_orig_on_topbar.png`）。
   ★ 用户知情后仍然选了「原图直接贴」——**这是拍板，不是疏漏**，不要再"修好"它。
   ⚠️ 中间那两版（① 按饱和度挑像素填蓝 ② 按区域整块铺渐变 + 文字实心蓝）
      用户都打回来了：原话「颜色不对啊」「**不是蓝色的啊**……严格按照我的标志弄上去」。
      它们把白字填成实心蓝、把 G 的白弧填掉，**标志的形状就不成立了**。
      教训：这类活儿的判据是"像不像用户那张图"，不是"在浅底上够不够清楚"。

⚠️ cv2 在 Windows 上读不了中文路径，必须 `imdecode(np.fromfile(...))`。
"""
import os
import sys
import numpy as np
import cv2

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "ui", "图片效果", "灵途智行标志.png")
DST = os.path.join(ROOT, "ui", "web", "assets")

# 顶栏 6rem 高（现场 940px 高 -> 根字号 14.93px -> 顶栏 89.6px），
# 这张图在屏上是 `.lingtu-lockup` 的 2.9rem ≈ 43px 高。
# 出图 320px = 屏上的 7.4 倍，4K 现场也够；再大只是白占体积。
OUT_H = 320

# ⚠️ 这里原来有三个"浅色版填色"常量（TEXT_BLUE / G_DEEP / G_LIGHT），
#    **2026-09-25 用户拍板后整个删掉** —— 浅色版不再上色，两个测出来的颜色
#    参数没有任何调用方了，留着只会让人以为还能调。别再凭记忆加回来。


def imread_u(p, flag=cv2.IMREAD_UNCHANGED):
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), flag)


def main():
    lg = imread_u(SRC)
    if lg is None or lg.shape[2] != 4:
        raise SystemExit("读不到 %s，或者它不是带 alpha 的 PNG" % SRC)
    print("源图 %dx%d" % (lg.shape[1], lg.shape[0]))

    # ---- 1. 裁掉透明边（**只裁边，不切内容**）-----------------------------
    # ⚠️ 上一版是在这里按列投影找"标志和文字之间那道空列缝"把文字切掉的。
    #    现在**文字要留着**，所以那一段整个删了 —— 别看着"少了一段"就往回加。
    #    实测整张 lockup 是一块**连通**的构图（那几道细线从左贯到右），
    #    列投影上根本没有空缝可切，这也是"整张用"的另一个理由。
    ys, xs = np.nonzero(lg[:, :, 3] > 8)
    lg = lg[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    print("裁到内容 %dx%d  宽高比 %.3f" % (lg.shape[1], lg.shape[0],
                                          lg.shape[1] / lg.shape[0]))

    bgr = lg[:, :, :3].astype(np.float32)
    alpha = lg[:, :, 3].astype(np.float32)

    # ---- 2. 浅色主题那一张：**原图，一个像素不改** ------------------------
    # ★ 2026-09-25 用户拍板。这里先后写过两版填色，都被打回来了，所以现在
    #   这一行**就是**"浅色版"。别再往回加任何 `nan_to_num`/`clip`/填色：
    #   浅色顶栏上白字会淡掉是**已知代价，用户明确接受**（原话「不管看不看得见」）。
    ink = bgr

    # ---- 3. 缩放 + 落盘 ---------------------------------------------------
    def pack(rgb_bgr, h):
        sc = h / rgb_bgr.shape[0]
        wpx = max(1, int(round(rgb_bgr.shape[1] * sc)))
        c = cv2.resize(rgb_bgr, (wpx, h), interpolation=cv2.INTER_AREA)
        a = cv2.resize(alpha, (wpx, h), interpolation=cv2.INTER_AREA)
        return np.dstack([c, a]).astype(np.uint8)

    dark = pack(bgr, OUT_H)
    light = pack(ink, OUT_H)

    # ⚠️ 两张的 alpha 必须逐像素相同 —— 不然切主题时整组的**轮廓会跳**。
    #    这条是 `.on-dark`/`.on-light` 那套机制留下来的硬约束，别省。
    #    现在两张内容已经**完全相同**，这个断言自然是恒真的；但还是留着 ——
    #    哪天有人给浅色版加回填色，第一道拦住他的就是这一行。
    d = int(np.abs(dark[:, :, 3].astype(int) - light[:, :, 3].astype(int)).max())
    assert d == 0, "两张图 alpha 不一致（max diff = %d），切主题会跳" % d
    print("alpha 逐像素一致 ✓  max diff = 0")

    os.makedirs(DST, exist_ok=True)
    for name, arr in [("lingtu_lockup.png", dark), ("lingtu_lockup_ink.png", light)]:
        p = os.path.join(DST, name)
        cv2.imencode(".png", arr)[1].tofile(p)
        print("  %-24s %4dx%-4d  %6.1f KB" % (name, arr.shape[1], arr.shape[0],
                                              os.path.getsize(p) / 1024))

    # ---- 4. 对照图（两种主题的底色各压一次，看的就是屏上那一眼）-----------
    # ⚠️ 右半张（浅色底）现在就是**白字淡掉的那一眼**，不是 bug、是用户拍板的
    #    结果。留着它的用处正是这个：下次谁觉得"浅底上看着不清楚"，先看这张图，
    #    别再去改 _mk_lingtu2 的填色。
    bw, bh = light.shape[1], light.shape[0]
    strip = np.full((bh + 30, bw * 2 + 24, 3), 255, np.uint8)
    for i, (arr, bg) in enumerate([(dark, (34, 22, 14)), (light, (246, 244, 250))]):
        a = arr[:, :, 3:4].astype(np.float32) / 255.0
        bgf = np.array(bg, np.float32)
        tile = (arr[:, :, :3].astype(np.float32) * a + bgf * (1 - a)).astype(np.uint8)
        x = i * (bw + 24)
        strip[30:30 + bh, x:x + bw] = tile
        cv2.putText(strip, ("on-dark (深色顶栏)" if i == 0
                            else "on-light (浅色顶栏)").encode(),
                    (x + 6, 20), cv2.FONT_HERSHEY_SIMPLEX, .5, (0, 0, 0), 1, cv2.LINE_AA)
    p = os.path.join(ROOT, "runs", "_lingtu_lockup_pair.png")
    cv2.imencode(".png", strip)[1].tofile(p)
    print("对照图 -> %s" % p)


main()
