# -*- coding: utf-8 -*-
"""把小瑞的**全部 43 张**立绘出一套"点一下换一张"用的图。

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch/_mk_xq_poses.py

产出两套（同一批 43 张，只有分辨率不同）：

    ui/web/assets/xq/s/p01.webp … p43.webp     H=288    左栏 / 座舱小槽 / 头像
    ui/web/assets/xq/l/p01.webp … p43.webp     H=1000   展示页那一格立绘位

★ 2026-09-25 用户原话：「左下那个应该小瑞图片能变化的太少了 我不是有40多张图片吗
  把那些出现小瑞的地方都变成可以变化的 并且形象要多一些 太少了」

在这之前"点一下换动作"只有 **5** 张（`xiaorui_rail_*.png` / `xiaorui_pose_*.png`，
由 `_mk_rail_poses.py` / `_mk_cover_poses.py` 出）。那两个脚本**被这份取代**，
连同它们那 10 张 png 一起删掉 —— 留着的后果是两套并存、点出来的东西不一样。

==========================================================================
一、这套图要解决的两件事
==========================================================================
**① 点一下换一张，人不能左右跳 / 不能忽高忽低。**
43 张源图的画幅不是一个尺寸（高 2155~2560、宽 1592~1760）。CSS 那一格是固定方框
+ `contain`，它按"宽和高谁先顶住"决定缩放 —— 直接拿 43 张原图去换，会出现
"有的按高顶住、有的按宽顶住"，每点一下人的高矮和左右位置都变。做法：

  1. **按高归一**。量出来的事实：角色在每张里都顶满画幅高（alpha 包围盒高 ÷
     画幅高 = 0.9948~1.0000，脚底线 = 0.9977~1.0000），所以按高缩 = 把人缩成一样高。
  2. **横向按 alpha 包围盒横心对齐到画布中线**。为什么是包围盒横心而不是
     "躯干重心"，见下面"二"。
  3. **补透明边到同一个画布**（`A = 0.73`）。补完之后 43 张的画幅尺寸**完全相等**，
     `contain` 怎么算都是同一套缩放，不可能再出现"按宽顶住"。

**② 左栏那一格不能变小。** 见"二"和"三"。

==========================================================================
二、画布宽高比 A = 0.73 —— 两个都是量出来的数
==========================================================================
**为什么不是"最宽那张"的 0.817。** 第一版取 `max(画幅宽/画幅高)` = 0.817（p43），
补出 235 宽。当时以为这样才对（"不能裁掉伸出去的胳膊"）。去看了一眼 p43 ——
它不是一个张开手臂的姿势，是一张**大头特写**（头占满画幅、没有身体），
所以画幅才显得宽。而 43 张里**只有它一张**超过 0.706：

    画幅宽高比   max 0.817（p43）· 次宽 0.706（p26）· 中位 0.679 · 最小 0.622

所以放不进画布的就那**一张**，让它按宽塞进去（缩到 89% 高、底边照样压在画布
底边）就行，代价是"一张大头特写比别的大头特写小一圈" —— 大头和全身本来就在
来回换，多这一档没人看得出来。

**A 的上限 0.743 是左栏那个框定死的。** 原来我以为左栏那一格只有 107x159
（`_mk_rail_poses.py` 的文件头就是这么写的），于是算出来"画布一宽、小瑞就矮"。
**那个数是错的。** 真的量了一遍 `index.html`（1638x843、DPR=1）：

    .rail-card   167.1 x 683.1  （左边 8.7）
    .rail-xr     144.8 x 194.75 （13.4rem）
    #railXrImg   131.9 x 196.8  ← 旧素材 193x288，按高顶住、**灌满整个高度**

框是 **144.8/194.75 = 0.743**，比旧素材的 0.670 宽。也就是说**画布只要不超过
0.743，小瑞就一直是满高（≈192 px），一像素都不亏** —— 宽的那部分画布只是
透明边，`contain` 会把它算进去然后再缩，人不变。

取 **0.73** 而不是顶到 0.743，是给"框宽高比哪台机器上都不一样"留 1.3% 的余量。

**横向锚点用包围盒横心，不用躯干重心**（这一条也是量出来的，我原来的直觉是反的）。
量的是"横心 / 画幅宽"这 43 个数的极差，再看它在 210 宽的画布上最多偏多少：

    包围盒横心   0.4991..0.5044   极差 0.0053   ->  最多偏 **0.55 px**
    躯干重心     0.4667..0.5070   极差 0.0404   ->  最多偏 **4.24 px**

躯干重心（bbox 中间 60% 那一带的 alpha 加权横心）本来是想"比包围盒稳"，因为它
是加权平均、不被一两个极端像素拽走。**实际相反**：3D 渲染的这个角色是侧身站
位的，躯干那一段的**剪影本身就不对称**（一侧是围巾、一侧是耳机），加权重心
跟着那个不对称跑；而画师显然是对着画幅中线摆的，所以**包围盒的两个极端
反而更听话**（43 张全落在中线 ±0.53%）。差 8 倍，用包围盒。

⚠️ 这条只在"这套图是同一个画师对着同一条中线摆的"时成立。`torso_cx()` 留在
   这份脚本里没删 —— 自证那一段把两个数**都**打出来，就是让人一眼看见差 8 倍。
   哪天图库换成一批中线乱摆的，两个数会一起变大，那时再谈用哪个。

==========================================================================
三、为什么是 webp 而不是 png；为什么大那套是 1000 高
==========================================================================
43 张 × 每张 3.7 MB 的源图。出 png 的话 H=288 那套 43×71.5 KB = 3.0 MB、
H=1000 那套 43×850 KB ≈ 30 MB；webp（q90、带 alpha）量下来 1.4 + 9.4 MB。

⚠️ **这套图比"平涂风"那批贵 4 倍**（同样 288 高，一张 33 KB vs 15 KB）：
   源图是微信下来的 PNG，里面**烤进去了 JPEG 的振铃**（量过：一张的不透明区
   263 万像素里有 **35.8 万种颜色**，平涂矢量图只会有几千种）。
   试过去噪和降质量，压不下来（q90→q75 只从 33.5 降到 28.7 KB），所以接受它。

大那套 1000 高是照展示页那一格立绘位定的：那格是 44rem x 46rem = 638x667 px
（窗口 1638 宽时），人画出来 667 px 高 —— 1000 给 DPR=1 留 1.5x。原来那套是
1200（1.8x），降到 1000 是为了 43 张的总量（1200 时约 10.8 MB）。

⚠️ **两套都是"点一下才下载一张"，不预加载**（见 live.js 里 `XQ.poseDeck` 的注释）：
   `/static/` 没有缓存头（server.py 的 `no_store`），预加载等于每翻一页重下 1.4 MB。
"""
import glob
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _xqkit import CARD, imread_u, load_full, on_card   # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSE_DIR = os.path.join(ROOT, "ui", "图片效果")
DST = os.path.join(ROOT, "ui", "web", "assets", "xq")

# 两套尺寸。288 那一档：左栏框是 144.8x194.75，按 0.73 顶高之后人画出来约 192 px，
# DPR=2 时 384 —— 288 略欠（0.75x），但那一格是装饰位，且这套图 4 倍贵（见"三"）。
SIZES = [("s", 288), ("l", 1000)]
# 方槽（头像）那一套：**从 `l` 那套裁头**，见 `head_crop()`。192 对 2.5rem 的圆
# （36 px、DPR=2 要 72）有 2.7x 余量，够它在任何一档上都不糊。
HEAD_OUT = 192
HEAD_FROM = "l"

# 画布宽高比。见"二"：三个数都是量出来的 —— 上限 0.743（左栏那个框）、
# 除 p43 外最宽 0.706、留 1.3% 余量。
A = 0.73
# 允许几张"按宽塞进画布"（= 会被缩小的）。超过这个数说明 A 定小了。
MAX_SQUEEZE = 2

# 躯干那一段取包围盒高的中间多少（只用于自证对照，不参与定位）。
TORSO_BAND = 0.60
# 每一套**画出来**有多高（屏上像素）。用于把"画布上偏几 px"折算成人眼看到的量。
#   s —— 左栏那一格（实测框 144.8x194.75，画布 0.73 按高顶住 => 高 194.75 里
#        可见约 192，`align-items:flex-end` + 那 2 px 的溢出被 overflow 裁掉）。
#   l —— 展示页那一格立绘位（44rem x 46rem = 638x667，人画出来 667）。
DISP = {"s": 192.0, "l": 667.0}
# 横向对齐的容差：锚点散得比这还开就说明"点一下人会左右跳"。
X_TOL_PX = 1.5
# 底边的容差（**画布上的**像素）。不是没压底边，是 alpha 阈值边缘：源图上
# 刚好 >32 的那一行，INTER_AREA 缩完可能变成 30 而被 `box()` 判成透明。
BOTTOM_TOL_PX = 3.0


def edge_fill(bgr, alpha):
    """角色不透明部分的平均色（BGR）—— 拿去填画布的空白处，见 `save_webp` 的注释。"""
    m = alpha > 32
    if not m.any():
        return np.zeros(3, np.uint8)
    return np.round(bgr[m].mean(axis=0)).astype(np.uint8)


def save_webp(rgba, path):
    """把 RGBA 落成 webp。

    ⚠️⚠️ **这一段是 2026-09-25 一次真事故的现场，别"简化"它。**

    原来那一行是：

        cv2.imencode(".webp", rgba[..., ::-1], [cv2.IMWRITE_WEBP_QUALITY, 90])

    `[..., ::-1]` 在 **4 通道**数组上翻的是四个通道，得到 (A,B,G,R)；
    而 `cv2.imencode` 按 **(B,G,R,A)** 解 —— 于是**写进文件的**
    红/绿/蓝是原图的 (绿,蓝,α)、alpha 是原图的**红**。屏幕上就是
    "小瑞变成一团白"（用户原话：「为啥 小瑞形象变成纯白了 根本不对了」），
    因为亮部（红通道高的地方）才是"不透明"的。

    为什么当时没发现：`runs/_xq_poses.png` 那张自证图是拿**内存里的**
    RGBA（`on_card()` 压到卡片底上）画的 —— 内存里一直是对的，
    **只有写出去的文件是错的**。所以自证图越好看，越说明不了盘上的东西对不对。

    正解就是 `_xqkit.tight()` 注释里写的那句：4 通道别走 `[..., ::-1]`，
    要么显式换 R/B，要么整个交给 PIL。这里用显式换序（保持 cv2 的
    quality 语义和原来一样，字节数才不会变一档）。

    ⚠️ 光"修好这一行"不够 —— **落盘之后一定要读回来量一遍**（见
       `verify_written`）。这一行错了两版、自证图两次都说好，靠的就是那条。 """
    cv2.imencode(".webp", rgba[..., [2, 1, 0, 3]],
                 [cv2.IMWRITE_WEBP_QUALITY, 90])[1].tofile(path)


def verify_written(rgba, path, tol=6.0):
    """把刚落盘的 webp **读回来**，比 **alpha>32 那些像素**的逐通道均值。

    判据是**均值**不是逐像素：q=90 是有损的，振铃重的源图上个别像素差 30
    很正常，卡最大值只会天天误报。而通道写反这种事故是**整幅**错位 ——
    均值会差几十，一眼就分得出来（那次 alpha 覆盖率 0.383 -> 0.462）。

    ⚠️ 只比 alpha>32 的区域，是**实测逼出来的**：全幅比的话透明区会拖后腿 ——
       webp 在完全透明的像素上不保证还回什么 RGB（第一版比出来 R/G/B 各差 11.1，
       而 alpha 一模一样；那 11 正好等于"透明区占 46% × 透明区被填成 ~24"）。
       通道写反那种事故在**不透明区**一样看得出来，不必拉上透明区。
    """
    got = imread_u(path)                       # cv2 读回来是 BGRA
    if got is None or got.ndim != 3 or got.shape[2] != 4:
        raise SystemExit("%s 读不回来 / 不是 4 通道。" % path)
    a = np.dstack([got[..., 2], got[..., 1], got[..., 0], got[..., 3]])  # -> RGBA
    m = rgba[..., 3] > 32
    if m.sum() < 100:
        raise SystemExit("%s 里角色只有 %d 个不透明像素？" % (path, m.sum()))
    d = (a[m].astype(np.float32).mean(axis=0)
         - rgba[m].astype(np.float32).mean(axis=0))
    if (np.abs(d) > tol).any():
        raise SystemExit(
            "%s 写盘后和内存里**对不上**：R/G/B/A 均值各差 %s（在不透明区上量的）"
            " —— 八成是通道顺序又写反了（见 save_webp 的注释）。"
            % (os.path.basename(path), np.round(d, 1).tolist()))
    if abs((got[..., 3] > 32).mean() - m.mean()) > 0.01:
        raise SystemExit("%s 的 alpha 覆盖率和内存里差得太多 —— 掩膜写歪了。" % path)


def box(a):
    """alpha 包围盒 (y0, y1, x0, x1)，右下开区间。"""
    ys, xs = np.where(a > 32)
    return int(ys.min()), int(ys.max()) + 1, int(xs.min()), int(xs.max()) + 1


def bbox_cx(a):
    """包围盒横心（图坐标系）。**定位就用它**，理由见文件头"二"。"""
    _, _, x0, x1 = box(a)
    return (x0 + x1) / 2.0


def torso_cx(a):
    """躯干重心（图坐标系）。**只用于自证对照**，不参与定位 —— 量出来它比
    包围盒横心散 8 倍（0.0404 vs 0.0053 的画幅宽极差），理由见文件头"二"。

    ⚠️ 返回值是**图坐标系**里的位置，不是"该挪多少"。第一版这里返回
       `cw/2 - cx`（位移量），调用处又按"居中之后再加这个位移"算
       `x0 = (CW-nw)/2 + dx` —— **两套坐标系混了**，居中量被算了两次。
       对满宽的姿势 x0 刚好顶到边界被夹住、于是右对齐，重心偏了 13.8 px
       （自证那段量出来的）。位移量的正确写法只有 `x0 = CW/2 - cx` 一种。
    """
    y0, y1, _, _ = box(a)
    h = y1 - y0
    yb0 = int(round(y0 + h * (1 - TORSO_BAND) / 2.0))
    yb1 = int(round(y1 - h * (1 - TORSO_BAND) / 2.0))
    cols = a[yb0:yb1].astype(np.float32).sum(axis=0)
    tot = float(cols.sum())
    return float((cols * np.arange(a.shape[1])).sum() / tot) if tot > 0 else a.shape[1] / 2.0


def head_crop(rgba, out):
    """从一张已经摆好位的立绘里裁出一个**带头像**的方形。

    为什么需要这一套（`xq/h/`）：座舱里有好几个**方槽** —— 对话栏那个 2.5rem 圆头像
    （`#talkAvaImg`）、手机页四个 hero、设置页两处小图、聊天气泡头像。它们现在吃的是
    `assets/xiaorui_head.png`（**400x400 的方头像**）。把一张全身立绘塞进 33 px 的圆里
    是一团糊，比现在还差 —— 所以这些槽要的是"同一批 43 张里面，每张的**头**"。

    判据不是"截上面一块"：这个角色是 Q 版，头占包围盒高约 **55~70%**（量过 43 张，
    脖子位置 0.554~0.700），所以"上面 30%"连眼睛都放不下。做法是量出**头**在哪：

      1. 逐行统计 alpha 宽度、平滑一下（源图上有一圈抗锯齿毛边，不平滑会数出一堆假极小）；
      2. 在包围盒前 55% 里找**最宽的那一行** —— 那是脸颊/耳机那一带（量出来在
         0.29~0.53 之间，和"头最大"的直觉一致）；
      3. 从那一行往下找**最窄的那一行** —— 那是脖子（量出来 0.55~0.70，43 张全落在
         这个窄带里，说明这个量法是稳的）。找不到就退回 0.68（Q 版头的经验值）。

    ⚠️ 第 3 步**必须限在 0.70 以内**：不限的话它会一路找到脚 —— 脚比脖子窄。

    然后取"包围盒顶 ~ 脖子再往下一点"和"最宽那行的左右"里更大的那个边长，
    凑成正方形（外扩 6%），再居中到头的中心。**超出画布的部分补透明**（头在上方，
    方形往上会出去），所以裁的时候要按边界单独处理，不能直接切片。
    """
    a = rgba[..., 3]
    ys, xs = np.where(a > 32)
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    n = y1 - y0
    w = (a > 32)[y0:y1].sum(axis=1).astype(np.float32)
    k = max(3, int(n * 0.02)) | 1
    ws = cv2.GaussianBlur(w.reshape(-1, 1), (1, k), 0).ravel()
    lo, hi = int(n * 0.05), int(n * 0.55)
    hm = lo + int(np.argmax(ws[lo:hi]))
    nl, nr = hm, int(n * 0.70)
    nk = nl + int(np.argmin(ws[nl:nr])) if nr > nl + 2 else int(n * 0.68)
    hb = min(y1, y0 + nk + int(n * 0.03))          # 往下带一点，别切掉下巴
    # 头的左右：在 [包围盒顶, 下巴] 里最宽那一行
    band = (a > 32)[y0:hb]
    row = y0 + int(np.argmax(band.sum(axis=1)))
    cols = np.where((a > 32)[row])[0]
    hl, hr = int(cols.min()), int(cols.max()) + 1
    side = int(round(max(hb - y0, hr - hl) * 1.06))
    cx, cy = (hl + hr) // 2, (y0 + hb) // 2
    x0, y0c = cx - side // 2, cy - side // 2
    sq = np.zeros((side, side, 4), np.uint8)
    sx0, sy0 = max(0, x0), max(0, y0c)
    sx1, sy1 = min(rgba.shape[1], x0 + side), min(rgba.shape[0], y0c + side)
    if sx1 > sx0 and sy1 > sy0:                    # 头在画布上方，往上会出去
        sq[sy0 - y0c:sy1 - y0c, sx0 - x0:sx1 - x0] = rgba[sy0:sy1, sx0:sx1]
    return cv2.resize(sq, (out, out), interpolation=cv2.INTER_AREA)


def main():
    FS = sorted(glob.glob(os.path.join(POSE_DIR, "微信图片_*.png")))
    print("姿势库 %d 张" % len(FS))
    if len(FS) < 40:
        raise SystemExit("只找到 %d 张 —— 图库不在盘上？" % len(FS))

    # ---- 1. 读全幅，量三条不变量 ------------------------------------------
    # 这三条是"按高归一"能成立的前提。哪天图库换了一批风格不一致的图，
    # 这里先炸，而不是等到页面上看着人忽高忽低才发现。
    raw, hh, gr, ar_box = [], [], [], []
    for p in FS:
        b, a = load_full(p)
        y0, y1, _, _ = box(a)
        fh, fw = a.shape[0], a.shape[1]
        hh.append((y1 - y0) / float(fh))
        gr.append(y1 / float(fh))
        ar_box.append(fw / float(fh))
        raw.append((b, a))
    print("画幅：高 %d..%d · 宽高比 %.3f..%.3f"
          % (min(x[1].shape[0] for x in raw), max(x[1].shape[0] for x in raw),
             min(ar_box), max(ar_box)))
    print("角色：占画幅高 %.4f..%.4f（该 ≈1.0）· 脚底线/画幅高 %.4f..%.4f（该 ≈1.0）"
          % (min(hh), max(hh), min(gr), max(gr)))
    if min(hh) < 0.98:
        raise SystemExit("有图角色**没顶满画幅高**（最小 %.4f）—— 按高归一会让它"
                         "比别人矮，先把这张挑出来看。" % min(hh))
    if max(gr) - min(gr) > 0.004:
        raise SystemExit("脚底线不齐（极差 %.4f）—— 按高归一会让人忽高忽低。"
                         % (max(gr) - min(gr)))

    # ---- 2. 逐张：缩到画布 -> 横心居中 -> 底边压在画布底边 -------------------
    out, squeeze = {}, []
    for tag, H in SIZES:
        CW = int(round(H * A))
        tiles, anch = [], []
        for i, (b, a) in enumerate(raw):
            fh, fw = a.shape[0], a.shape[1]
            # 同时不超过画布的高和宽 —— 两个都顶不住的那张（p43）按宽塞
            s = min(H / float(fh), CW / float(fw))
            nw = max(1, int(round(fw * s)))
            nh = max(1, int(round(fh * s)))
            rb = cv2.resize(b, (nw, nh), interpolation=cv2.INTER_AREA)
            ra = cv2.resize(a, (nw, nh), interpolation=cv2.INTER_AREA)
            if tag == "s" and nh < H - 1:      # 这张是按宽塞进来的
                squeeze.append((i + 1, nh / float(H)))
            # 横心对到画布中线。⚠️ 只有这一种写法（见 torso_cx 的注释）。
            x0 = max(0, min(CW - nw, int(round(CW / 2.0 - bbox_cx(ra)))))
            _, y1, _, _ = box(ra)
            y0 = max(0, min(H - nh, H - y1))   # 角色底边压在画布底边
            # 画布的**空白部分填角色自己的平均色**（不是黑）。根因见 save_webp 的
            # 注释：webp 是 YUV420，相邻 2x2 的色度互相平均，透明区填 0（黑）
            # 会在白角色边上拖出一圈淡灰边 —— 而这批图的主体正是白 + 浅蓝。
            cb = np.full((H, CW, 3), edge_fill(rb, ra), np.uint8)
            ca = np.zeros((H, CW), np.uint8)
            cb[y0:y0 + nh, x0:x0 + nw] = rb
            ca[y0:y0 + nh, x0:x0 + nw] = ra
            rgba = cv2.cvtColor(np.dstack([cb, ca]), cv2.COLOR_BGRA2RGBA)
            tiles.append((i, rgba))
            anch.append((x0 + bbox_cx(ra)) / CW)
        out[tag] = (CW, tiles, anch)

    print("\n画布 %d 宽（= %.2f x 高）· 按宽塞进画布的有 %d 张：%s"
          % (int(round(288 * A)), A, len(squeeze),
             "、".join("p%02d 到 %.0f%% 高" % (n, r * 100) for n, r in squeeze)
             or "无"))
    if len(squeeze) > MAX_SQUEEZE:
        raise SystemExit("有 %d 张塞不进画布（上限 %d）—— A=%.2f 定小了，"
                         "要么调大 A、要么把它们从库里去掉。"
                         % (len(squeeze), MAX_SQUEEZE, A))

    # ---- 3. 落盘（外加从 `l` 那套裁一套方头像） ------------------------------
    head = [(i, head_crop(rgba, HEAD_OUT))
            for i, rgba in out[HEAD_FROM][1]]
    out["h"] = (HEAD_OUT, head, None)
    total = {}
    for tag, H in SIZES + [("h", HEAD_OUT)]:
        CW, tiles, _ = out[tag]
        d = os.path.join(DST, tag)
        os.makedirs(d, exist_ok=True)
        tot = 0
        for i, rgba in tiles:
            p = os.path.join(d, "p%02d.webp" % (i + 1))
            save_webp(rgba, p)
            tot += os.path.getsize(p)
            verify_written(rgba, p)           # ← 读回来量一遍，见它的注释
        total[tag] = tot
        print("  xq/%s/  %d 张  %dx%d  合计 %.2f MB（平均 %.1f KB/张，"
              "点一下只下这一张）"
              % (tag, len(tiles), CW, H, tot / 1048576.0, tot / 1024.0 / len(tiles)))
    # 上限按"这套图本来就有多大"卡，不是按愿望卡 —— 源图烤了 JPEG 振铃，
    # 同样尺寸比平涂风贵 4 倍（见"三"）。卡在这里是防"哪天有人把质量调到 100、
    # 或者把 H 调大一档"，不是防这套图本身。
    if total["s"] > 2.0 * 1048576:
        raise SystemExit("小那套 %.2f MB 太大了 —— 它是要在十页里被点的。"
                         % (total["s"] / 1048576.0))
    if total["l"] > 12 * 1048576:
        raise SystemExit("大那套 %.2f MB 太大了。" % (total["l"] / 1048576.0))
    if total["h"] > 1.2 * 1048576:
        raise SystemExit("头像那套 %.2f MB 太大了。" % (total["h"] / 1048576.0))

    # ---- 4. 自证：横向锚点 / 角色高度 / 底边 ---------------------------------
    # ⚠️ 底边那一条现在是**构造出来的**（上面 `y0 = H - y1` 直接压底边），
    #   所以它只当回归钉子用，不算发现。真正有内容的是**横向锚点**那一条。
    # ⚠️ 下面算锚点**故意不调 `bbox_cx()`**，自己重新求一遍包围盒：
    #   调它的话，`bbox_cx` 写错了这里跟着一起错，自证就成了自己跟自己对齐。
    print()
    for tag in ("s", "l"):
        CW, tiles, anch = out[tag]
        H = tiles[0][1].shape[0]
        cs, gr2, hgt = [], [], []
        for i, rgba in tiles:
            a = rgba[..., 3]
            ys, xs = np.where(a > 32)
            y0, y1, x0, x1 = int(ys.min()), int(ys.max()) + 1, int(xs.min()), int(xs.max()) + 1
            h = y1 - y0
            yb0 = int(round(y0 + h * (1 - TORSO_BAND) / 2.0))
            yb1 = int(round(y1 - h * (1 - TORSO_BAND) / 2.0))
            cols = a[yb0:yb1].astype(np.float32).sum(axis=0)
            cs.append(float((cols * np.arange(a.shape[1])).sum() / cols.sum()) / CW)
            gr2.append(y1 / float(a.shape[0]))
            hgt.append(h / float(a.shape[0]))
        nfull = sum(1 for x in hgt if x > 0.99)
        sp = max(anch) - min(anch)
        drawn = sp * CW * DISP[tag] / H
        print("  %s 套（画布 %dx%d，画出来 %d px 高）："
              % (tag, CW, H, int(DISP[tag])))
        print("      ★ 横心 %.4f..%.4f（极差 %.4f = 画布上 %.2f px、"
              "画出来 %.2f px）"
              % (min(anch), max(anch), sp, sp * CW, drawn))
        print("        （对照）躯干重心 %.4f..%.4f（极差 %.4f）—— 差 %.0f 倍，"
              "所以不用它"
              % (min(cs), max(cs), max(cs) - min(cs),
                 (max(cs) - min(cs)) / sp if sp > 1e-9 else 0))
        print("        角色高 %.4f..%.4f 画布高（%d 张满高 / 共 %d 张）· "
              "底边 %.4f..%.4f（画布上 %.1f px）"
              % (min(hgt), max(hgt), nfull, len(tiles), min(gr2), max(gr2),
                 (max(gr2) - min(gr2)) * H))
        if drawn > X_TOL_PX:
            raise SystemExit("横向锚点散得太开（画出来 %.2f px > %.1f）—— "
                             "点一下人会左右跳。" % (drawn, X_TOL_PX))
        if (max(gr2) - min(gr2)) * H > BOTTOM_TOL_PX:
            raise SystemExit("底边不齐（画布上 %.1f px）。"
                             % ((max(gr2) - min(gr2)) * H))
        if nfull != len(tiles) - len(squeeze):
            raise SystemExit("满高的有 %d 张，但按高归一应该有 %d 张。"
                             % (nfull, len(tiles) - len(squeeze)))

    # ---- 5. 核对图：43 张一屏看完（人眼那关） ------------------------------
    CW, tiles, _ = out["s"]
    cols, TH = 8, 190
    tw = max(1, int(round(CW * TH / float(tiles[0][1].shape[0]))))
    rows = (len(tiles) + cols - 1) // cols
    sheet = np.full((rows * (TH + 26) + 8, cols * (tw + 6) + 6, 3), 255, np.uint8)
    for k, (i, rgba) in enumerate(tiles):
        t = cv2.resize(on_card(rgba, CARD), (tw, TH), interpolation=cv2.INTER_AREA)
        r, cc = divmod(k, cols)
        y, x = 4 + r * (TH + 26), 3 + cc * (tw + 6)
        sheet[y + 22:y + 22 + TH, x:x + tw] = t[..., ::-1]
        cv2.line(sheet, (x + tw // 2, y + 22), (x + tw // 2, y + 22 + TH),
                 (0, 90, 220), 1)
        cv2.line(sheet, (x, y + 22 + TH - 1), (x + tw, y + 22 + TH - 1),
                 (0, 160, 0), 1)
        cv2.putText(sheet, ("p%02d" % (i + 1)).encode(), (x + 4, y + 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.46, (40, 40, 40), 1, cv2.LINE_AA)
    op = os.path.join(ROOT, "runs", "_xq_poses.png")
    cv2.imencode(".png", sheet)[1].tofile(op)
    # 方头像那套也来一张 —— 裁头是"量脖子在哪"推出来的，只能人眼看
    hair = out["h"][1]
    hcols, HT = 11, 130
    htw = hcols * (HT + 5) + 5
    hrows = (len(hair) + hcols - 1) // hcols
    hsheet = np.full((hrows * (HT + 24) + 6, htw, 3), 255, np.uint8)
    for k, (i, rgba) in enumerate(hair):
        t = cv2.resize(on_card(rgba, CARD), (HT, HT), interpolation=cv2.INTER_AREA)
        r, cc = divmod(k, hcols)
        y, x = 3 + r * (HT + 24), 3 + cc * (HT + 5)
        hsheet[y + 20:y + 20 + HT, x:x + HT] = t[..., ::-1]
        cv2.putText(hsheet, ("p%02d" % (i + 1)).encode(), (x + 3, y + 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (40, 40, 40), 1, cv2.LINE_AA)
        # 圆形裁切预览（方槽里有好几处是圆头像）+ 一个 33px 的"实际大小"
        cv2.circle(hsheet, (x + HT - 22, y + 20 + 22), 19, (0, 160, 0), 1)
        hsheet[y + 20 + HT - 36:y + 20 + HT - 4,
                x + HT - 36:x + HT - 4] = cv2.resize(
                    t, (32, 32), interpolation=cv2.INTER_AREA)[..., ::-1]
    hop = os.path.join(ROOT, "runs", "_xq_heads.png")
    cv2.imencode(".png", hsheet)[1].tofile(hop)
    print("\n核对图 -> %s" % op)
    print("  蓝线 = 画布中线（人都该压在线上）· 绿线 = 画布底边（人都该踩在线上）")
    print("  顺序 = 文件名排序，点一下换一张就走这个顺序。")
    print("核对图 -> %s" % hop)
    print("  43 个头像。每格右上那个**绿圈**是 38px 的圆形裁切预览、右下角那块")
    print("  是 **32px 实际大小** —— 头像槽最小就到这个尺寸，看不清就得改 `head_crop()`。")


main()
