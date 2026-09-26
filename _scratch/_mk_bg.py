# -*- coding: utf-8 -*-
"""把 `ui/图片效果/` 里那两张场景图装成界面用的底图。

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch/_mk_bg.py

产出三张：

    ui/web/assets/bg_scene.jpg    1920 宽 q88  —— **封面**整幅底图（原色，不洗白）
                                                源 = `背景.png`
    ui/web/assets/bg_wash.jpg     1280 宽 q80  —— **座舱内**那几页的底图
                                                 （先重模糊再压，配合 CSS 的白色蒙版）
                                                 源 = 同一张 `背景.png`
    ui/web/assets/home_scene.jpg  1920 宽 q88  —— **首页主视觉那张圆角面板**（原色）
                                                 源 = `首页背景.png`

★ 2026-09-25 第十二次改版又加了**三张分区底图**（见 `SRC_3`），源图都是 2848x1600：

    ui/web/assets/media_playing.jpg 1600 宽 q86 —— 多媒体页「正在播放」卡
    ui/web/assets/media_music.jpg   1600 宽 q86 —— 多媒体页「我的音乐」卡
    ui/web/assets/cam_off.jpg       1400 宽 q86 —— 驾驶监测页**未接入摄像头**的取景框
    （`cam_off` 给 1400 是因为那个框是**竖的**，`cover` 左右各切一半，给宽了白给）

★ 2026-09-25 第十三次改版再加**两张**（见 `SRC_4`），源图一张 2304x1728、一张 2048x1184：

    ui/web/assets/detail_xq.jpg     1200 宽 q86 —— 驾驶监测页「小瑞 · 智能陪伴」卡（`.mon-xq`）
    ui/web/assets/rail_bg.jpg        340 宽 q82 —— **左栏那张导航卡**（`.rail-card`）
    ⚠️ 左栏那张下面 `emit_fit()` 里有一整段"为什么要先裁成竖条"的账，**动手前先看**：
       它是**横图**（1.84:1）而左栏是**1:4 的竖条**，不裁就要出到 2500 宽才不虚，
       而每一页都在下载它。

★ 为什么 `bg_scene` 和 `bg_wash` 要分成两张：用户原话是「把刚打开浏览器 没进入座舱前的
  背景变成背景.png图」，**只点名了封面**。座舱内那四页（首页/驾驶监测/多媒体/设置）参考图上
  也有同一片城市，但被洗得很淡 —— 白卡片压在上面要读得清。同一张原图直接铺上去，卡片
  周围那一圈会花得没法看。所以座舱那张**先模糊再洗白**，观感是"有一层城市纹理"，
  而不是"一张照片"。

★ 为什么 `home_scene` 是**第三张**而不是复用 `bg_scene`：2026-09-24 用户又给了一张
  `首页背景.png`，原话是「首页中间那部分展示的地方 灵途智行 与您图片那一部分……
  并且把背景图换成…首页背景.png」——他说的"背景图"指的是**首页主视觉那一小块**
  （`pages.css` 的 `.dash-visual`），和封面整页那张是两回事，所以要各出一张。

★★ 2026-09-25 新增：**水印裁切**。见 `wm_crop()` 上面那一大段 —— 这是这一轮新冒出来的活，
   **不裁的话两张源图右下角那行「豆包AI生成」会被烤进三个产品素材里**。

⚠️ 源图是整幅场景（不是可平铺贴图），所以 CSS 那边固定用 `center/cover`，不要用 repeat。
⚠️ cv2 在 Windows 上读不了中文路径 —— 走 `imdecode(np.fromfile(...))`。
"""
import os
import sys

import cv2
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_COVER = os.path.join(ROOT, "ui", "图片效果", "背景.png")
SRC_HOME = os.path.join(ROOT, "ui", "图片效果", "首页背景.png")
DST = os.path.join(ROOT, "ui", "web", "assets")
# 2026-09-25 第十二次改版：用户点名「换到对应地方」的三张，名字里就写着去处，
# 所以这里按**去处**起变量名，别再按源图名。（(源文件名, 输出名, 宽, 质量)）
SRC_3 = [
    ("多媒体部分正在播放部分背景图.png", "media_playing.jpg", 1600, 86),
    ("多媒体页我的音乐部分背景图.png", "media_music.jpg", 1600, 86),
    ("驾驶检测 未接入摄像头时背景图.png", "cam_off.jpg", 1400, 86),
    # ★ 2026-09-25 深夜追加：「正在播放」那张封面里的音乐标志（`media.html` 的
    #   `#art`）。它是**2048x2048**、而且水印字号比别的都大一倍（见 `WM_SIZE_3`）。
    #   给 640 是因为 `14rem` 在 1672x940 下只有 209px，2x 屏 418px —— 640 够。
    ("多媒体音乐标志.png", "media_logo.jpg", 640, 86),
    # ★ 2026-09-25 深夜追加：「小瑞 · 音乐推荐」那张卡（`.mp-xq`）。
    #   给 **1400**（比同页那两张 1600 小）是量出来的：这张卡实测 488x352，
    #   比例 1.38:1，而源图裁完是 1600x845（1.89:1）—— `cover` 到 1.38:1 时
    #   高度先顶满，宽度按 scale=352/845=0.417 渲染成 666px，**左右各裁掉 89px**
    #   （各占 13%）。也就是说屏上只用到源图中间 73% 的宽度。
    #   2x 屏下这一格要 976 设备像素宽，976/0.73 = 1337 —— 1400 刚够，1600 白给。
    ("多媒体页小瑞·音乐推荐部分背景.png", "media_xq.jpg", 1400, 86),
]

# ★ 2026-09-25（第十三次改版）：用户又给了两张，原话「`…图片效果\`驾驶监测页 小瑞智能陪伴
#   部分背景图.png 还有整体左栏背景图.png 都换上」（第一条消息把"换上"打成了"换算"，
#   紧接着补了一句「换上」）。文件名就是去处：
#     `驾驶监测页 小瑞智能陪伴部分背景图.png` -> detail.html 的「小瑞 · 智能陪伴」卡
#     `整体左栏背景图.png`                   -> 全站左栏那张导航卡
#   `ratio` 那一栏 = 出图前先把源图裁成的宽高比（`None` = 保持源图比例）。
#     · detail_xq 保持源比例：那**是一张画好的"玻璃面板"**（圆角描边 + 光晕 + 太阳
#       和光斑），`cover` 只会上下各切一点，框还在。宽高比的事下面 `main()` 里另有一段账。
#     · rail_bg 必须裁：横图喂竖条，理由全在 `emit_fit()` 上面那一段。
#   ⚠️ 白纱（压多少白）**不在这里**，在 CSS 里；这里只负责把量出来的数打出来
#      （`veil_report`），那个数怎么读写在 `main()` 第 6 段。
SRC_4 = [
    ("驾驶监测页 小瑞智能陪伴部分背景图.png", "detail_xq.jpg", 1200, 86, None,  "center"),
    # ⚠️ 这张是 `"std"`（按方差挑竖条）不是 `"center"` —— 理由在 `emit_fit` 上面
    #    那一大段里，一句话版：正中间恰好是整幅图最白的一段，按 center 裁出来的
    #    左栏几乎看不出换过（量出来 p05=231 中位=246）。
    ("整体左栏背景图.png",                   "rail_bg.jpg",    340, 82, 0.22, "std"),
]

# ---------------------------------------------------------------- 水印检测参数
# ⚠️ 这些数**是量出来的，不是拍的**，依据全部留在 `_scratch/_wm_probe.py` 里。
#    2026-09-25 实测：`背景.png` 和 `首页背景.png` **都是 2656x1536**，水印都落在
#    **同一处** —— 文字 x≈2378..2625、y=1455..1503（49 行）。
#
# ★ 第一版探针的教训（别再走一遍）：拿"整行 vs 横向中位核 K=61"在**整幅宽度**上算残差，
#   搜索区里**每一行都报警**（2%~29%）—— 不是水印大，是这张图本来就满是城市纹理。
#   **判据的分辨力来自"窗口开得对不对"，不是来自阈值。** 所以现在把窗口收到水印
#   实际所在的那一小块（位置是先把右下角带标尺渲染出来用眼睛读的，
#   见 `runs/_wm_corner.png`），再用 2D 中位核把背景抹掉、只留笔画。
#
# ★ `WM_FRAC = 0.15` 也是量出来的：斜向光带最高只到 **9.2%**，水印最低 **19%**，
#   0.15 正好落在这道空档里。用 0.02 会把光带一起收进来 —— `min(hot)` 落到 y=1380，
#   裁掉 10% 都裁不干净（残余 54.91%）。
WM_WIN_X = (2330, 2660)   # 绝对像素，**为 2656x1536 量的**（见下面的尺寸断言）
WM_WIN_Y = (1380, 1536)
WM_GK = 51                # 2D 中位核：要**宽于笔画**（笔宽约 15px），窄于画面大块结构
WM_THR = 25               # 水印是浅色叠加，和背景差 30~60 灰阶
WM_FRAC = 0.15            # 一行里超过这个占比就算"这一行压着水印"
WM_MARGIN = 12            # 裁到水印上方再留几行 —— 盖住字形顶部的抗锯齿渗出
WM_SIZE = (2656, 1536)    # 上面那几个绝对坐标就是按这个尺寸量的

# ★ 2026-09-25（第十二次改版）：用户又给了**三张**背景图（下面 `SRC_*3` 那三张），
#   它们**都是 2848x1600**，和上面那两张不是同一个尺寸，所以窗口要另量一份。
#   ⚠️ 窗口的**相对位置**一样（右下角那行「豆包AI生成」），但**不能按比例缩放
#      那两个绝对坐标** —— 水印字号不一定跟着图缩放（上一版的教训就写在
#      `wm_crop` 的那个断言里）。这里是把右下角渲染出来看了之后另起的窗口
#      （`runs/_new_bgs_corner.png`），而且**留给检测器自己量行号**：
#      窗口只规定"去哪儿找"，具体裁到哪一行由 `wm_crop` 现算并自检。
WM_WIN_X_2 = (2350, 2848)
WM_WIN_Y_2 = (1400, 1600)
WM_SIZE_2 = (2848, 1600)
# 尺寸 -> 窗口。`wm_crop` 只认这个表，表里没有的尺寸**当场停**（见那个断言）。
# ★ 2026-09-25 深夜再加一档：`多媒体音乐标志.png` 是 **2048x2048**，而且这一张的
#   水印和前面五张**都不一样大** —— 它的「豆包AI生成」字高约 120px（前面那些
#   只有 50px 上下），x 从 1620 一直排到画面右边缘、最后一个「成」字**被图边切掉**。
#   ⚠️ 这正是那个断言存在的理由：按比例从 2656 或 2848 缩放窗口，字会**上半截
#      留在画面里**，而且裁完之后没人会发现（水印是浅色叠加，缩到 640 宽之后
#      几乎看不见）。窗口是在 `runs/_music_logo_corner.png`（1:1 带标尺）上读出来的。
WM_WIN_X_3 = (1600, 2048)
WM_WIN_Y_3 = (1860, 2048)
WM_SIZE_3 = (2048, 2048)
# ★ 2026-09-25（第十三次改版）再加两档。这两张的尺寸**又不一样**（2304x1728 / 2048x1184），
#   所以窗口还是另量一份 —— 用的是 `_scratch/_wm_probe2.py`（那个脚本是这一轮为它们写的：
#   先把右下角 1:1 带标尺渲染出来用眼睛读字的位置，再拿几个候选窗口跑逐行剖面，
#   挑"贴着字、且字上方的行明显不超阈值"的那个）。
#   ⚠️ 窗口宽**故意比水印本身宽**（600 / 400，字实际只占 ~540 / ~340）：窗口里
#      除了字还有干净的背景，逐行占比才有分母，`WM_FRAC` 那道空档才在。窗口收到跟
#      字一样宽的话，每一行都接近 100%，阈值就失去分辨力了。
#   ⚠️ y 只开到图底（不要留白）：`wm_crop` 的窗口是**逐行**统计的，窗口下沿之外
#      的行根本不参与，"水印下面还有多少干净行"这件事本来也不影响裁剪。
WM_WIN_X_4 = (1660, 2260)      # 字实际 x≈1690..2230（字高 ~105px，比别张的都大）
WM_WIN_Y_4 = (1400, 1728)
WM_SIZE_4 = (2304, 1728)
WM_WIN_X_5 = (1630, 2030)      # 字实际 x≈1655..1995（字高 ~55px）
WM_WIN_Y_5 = (950, 1184)
WM_SIZE_5 = (2048, 1184)
WM_WINDOWS = {
    WM_SIZE: (WM_WIN_X, WM_WIN_Y),
    WM_SIZE_2: (WM_WIN_X_2, WM_WIN_Y_2),
    WM_SIZE_3: (WM_WIN_X_3, WM_WIN_Y_3),
    WM_SIZE_4: (WM_WIN_X_4, WM_WIN_Y_4),
    WM_SIZE_5: (WM_WIN_X_5, WM_WIN_Y_5),
}


def imread_u(p, flag=cv2.IMREAD_UNCHANGED):
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), flag)


def wm_crop(im, name):
    """裁掉右下角那行「豆包AI生成」。**返回裁好的图**，并把量到的东西全打出来。

    为什么要裁而不是抹：水印底下是斜向光带，涂抹/修复会把那几道光带糊断，
    而裁掉的是**画面最底下 6%**（`center/cover` 下几乎看不出来）。仓库里
    `_scratch/_mk_xr2.py:37` 的 `WMART = 0.93` 就是这个先例。
    """
    H, W = im.shape[:2]
    if (W, H) not in WM_WINDOWS:
        raise SystemExit(
            "源图 %s 是 %dx%d，`WM_WINDOWS` 里没有这个尺寸 —— "
            "**重新量一遍**（把 `_scratch/_wm_probe.py` 的窗口改成新尺寸的右下角，"
            "先渲染出来用眼睛看），别直接把坐标缩放过来。表里现有：%s"
            % (name, W, H, sorted(WM_WINDOWS)))

    x0, x1 = WM_WINDOWS[(W, H)][0]
    y0, y1 = WM_WINDOWS[(W, H)][1]
    g = cv2.cvtColor(im[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    res = (np.abs(g.astype(np.int16) - cv2.medianBlur(g, WM_GK).astype(np.int16)) > WM_THR)
    prof = res.mean(axis=1)                      # 窗口内逐行的异常占比

    hot = [y0 + i for i, v in enumerate(prof) if v > WM_FRAC]
    if not hot:
        # ⚠️ 找不到**不能**当成"没有水印"就放过去：很可能是水印换位置/换样式了。
        #    宁可当场停，也不要静默地把水印烤进素材。
        raise SystemExit(
            "%s：窗口 x %s y %s 里没找到水印（最高一行才 %.2f%%，阈值 %.2f）—— "
            "**别把它当成'这次没有水印'**，先渲染右下角看一眼水印是不是挪窝了。"
            # ⚠️ 这里要报**这张图实际用的那个窗口**（`(x0,x1)`/`(y0,y1)`），
            #    不能写 `WM_WIN_X`/`WM_WIN_Y` —— 那两个全局量只属于 2656x1536 那一档，
            #    报出来的坐标会把"该去哪看"指到图上完全无关的地方（老版就是这么错的）。
            % (name, (x0, x1), (y0, y1), prof.max() * 100, WM_FRAC))

    top, bot = min(hot), max(hot)
    cut = top - WM_MARGIN
    kept_max = prof[:cut - y0].max() * 100       # 留下的那些行，最高一行多少
    drop_max = prof[cut - y0:].max() * 100       # 扔掉的那些行，最高一行多少
    print("  %s 水印行 y %d..%d（高 %d）" % (name, top, bot, bot - top + 1))
    print("     窗口 x %s y %s · 异常总占比 %.2f%% · 阈值 %.2f"
          % ((x0, x1), (y0, y1), res.mean() * 100, WM_FRAC))
    print("     裁到 y<%d（保留高 %d = %.2f%%）" % (cut, cut, cut * 100.0 / H))
    print("     留下的行最高 %.2f%%（必须 ≤ %.2f）· 扔掉的行最高 %.2f%%（必须 > %.2f）"
          % (kept_max, WM_FRAC * 100, drop_max, WM_FRAC * 100))
    assert kept_max <= WM_FRAC * 100, "裁完之后还有行超阈值，说明水印顶边没盖住"
    assert drop_max > WM_FRAC * 100, "扔掉的行里没有水印，说明裁多了"
    return im[:cut]


def emit(im, name, width, quality, blur=0.0):
    """缩到 width 宽、（可选）高斯模糊、按 quality 压成 JPEG 落盘。"""
    sc = float(width) / im.shape[1]
    out = cv2.resize(im, (width, int(round(im.shape[0] * sc))),
                     interpolation=cv2.INTER_AREA)
    if blur:
        # 模糊半径按**缩小后**的尺寸算：先在原尺寸上模糊再缩，等于白花算力，
        # 而且 sigma 会被缩放的插值吃掉一截，观感反而更"糊得不均匀"。
        out = cv2.GaussianBlur(out, (0, 0), blur)
    p = os.path.join(DST, name)
    cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, quality])[1].tofile(p)
    print("  %-18s %4dx%-4d %7.1f KB" % (name, out.shape[1], out.shape[0],
                                         os.path.getsize(p) / 1024))
    return out


# 「按方差挑竖条」那两条判据（只给 `band="std"` 用，见 `emit_fit`）:
#   · `BAND_TOP_FRAC`  = 竖条**上方**这一段的比例。左栏的版式是"四个入口占上部、
#     中段空白、立绘贴底"，量出来那四个入口到卡片 30% 上下，这里取 32% 留一点。
#   · `BAND_TOP_P05_MIN` = 那一段的 p05 灰阶下限。**这个数是推出来的**：
#     浅色主题的导航项字色是 `--ink-4: #33689E`（相对亮度 0.1307），
#     WCAG 正文线 4.5:1 反推 → 底色相对亮度 ≥ 0.7632 → 灰阶 **≥ 226**。
#     左栏压的是白纱 `.30`（CSS 里那个数，见 `style.css`），所以源图那一档要
#     `p05 × 0.7 + 76.5 ≥ 226` → `p05 ≥ 214`，取整 **215**。
#     ⚠️ 改白纱就得改这个数 —— 两者是绑在一起的，别只改一头。
BAND_TOP_FRAC = 0.32
BAND_TOP_P05_MIN = 215

# 「裁到面板本身」那一步用的框（只给带画框的源图用，见 `frame_crop()`）。
# 坐标是**裁过水印之后**那张图上的绝对像素，量法写在 `frame_crop` 的注释里。
# ⚠️ 不是比例、不许换算。换源图 = 重新量。
FRAME_CROPS = {
    "驾驶监测页 小瑞智能陪伴部分背景图.png": (157, 133, 2157, 1562),
}
BORDER_BAND = 24          # 自检时"边缘带"取多少列


def frame_crop(im, name):
    """把"源图四周那圈面板**外**的底色"裁掉，只留**画好的那个面板本身**。

    ## 为什么有这一步（用户原话）

      「驾驶监测 小瑞智能陪伴那部分背景边框和我实际边框感觉有矛盾 把背景边框和我
        的实际边框宽度弄成相等的吧 不然有两个边框」

      源图是一张**画好的玻璃面板**：面板自己带一圈描边（一条亮边 + 一条青色的线），
      面板四周还留着一圈底色。直接 `cover` 铺到卡片上，那圈描边就落在卡片**里面**
      百分之几的地方，和卡片自己的边（`--r-lg` 圆角 + 1px 白描边）并排 ——
      看起来就是"两个边框"。裁掉面板外那圈底色之后，面板的描边正好落在卡片边上，
      和卡片自己的边合成一条。

    ## 框是怎么量出来的

      `_scratch/_probe_frame.py` + `_probe_frame2.py`，两步：
        1. 列/行均值减掉自己的重度模糊（`sigma=40`）之后找局部极值 —— 描边在那里
           是个凹口。**第一版照搬水印那套"逐列残差占比"没量出来**：这圈描边是
           **柔的**（一条 10px 宽的渐变带），不是水印那种硬笔画，占比上不去，
           最高的列才 48%，判据全落空。教训写在 `_probe_frame.py` 的文件头。
        2. 再打**单独一行**（y=800，肯定不在圆角上）的原始灰阶剖面 + 把两条边
           放大 3 倍存成 PNG 看（`runs/_frame_left_x3.png` / `_frame_right_x3.png`）——
           左边缘的结构是 `底色 | 亮边 | 青色线 | 内阴影 | 面板内`，
           右边缘是 `面板内 | 亮边 | 青色线 | 深蓝底色`，
           所以"面板的外沿"取青色线**外侧**那一侧：左 x=157、右 x=2157。

      ⚠️ 这两个数**是量出来的绝对坐标，不许按比例缩放**（理由同 `WM_WINDOWS` 那条）。
      ⚠️ 上下那两条（y=133 / 1562）其实**永远看不见** —— 卡片是 2.65:1 的横条，
         `cover`/`100% auto` 之后只剩中间 53% 的高度，上下两条描边都在窗外。
         它们只影响**出图的比例**，而比例又决定 CSS 那边能不能用 `100% auto`
         （见下面那条断言和 `pages.css` 里的说明）。

    ## 裁完还得**回头看一次**（这一步别省）

      **"裁到面板上"和"描边落在卡片边上"是两件事**：这一步只保证前者，
      后者靠 CSS 的 `100% auto` + 卡片自己的宽度（这一段在 `pages.css` 里）。
      所以铺上去之后要复核：`_scratch/_shot_bgs4.py` 截图 →
      `_scratch/_probe_monxq_edge.py` 在截图上一行一行读灰阶
      （结果在 `runs/_monxq_edge_out.txt`）。**实测描边线的心离卡片外沿约 2 CSS px**，
      里头 1px 是 `background-origin: padding-box` 的账、1px 是这里故意留下的
      外圈高光那条亮边。`_probe_monxq_dom.py` 再问一遍 DOM 的 `background-size`
      —— 这一格 `cover` 和 `100% auto` **画面恰好一样**，光看截图分不出来。
    """
    if name not in FRAME_CROPS:
        return im
    H, W = im.shape[:2]
    x0, y0, x1, y1 = FRAME_CROPS[name]
    if not (0 <= x0 < x1 <= W and 0 <= y0 < y1 <= H):
        raise SystemExit(
            "%s 的 `FRAME_CROPS` 是 %s，但（裁过水印之后的）图只有 %dx%d —— "
            "**重新量一遍**（`_scratch/_probe_frame.py`），别按比例挪坐标。"
            % (name, FRAME_CROPS[name], W, H))
    out = im[y0:y1, x0:x1]
    h, w = out.shape[:2]
    # 自检：裁出来的左右两条边**必须真的压在描边上**。判据是"边缘带的局部起伏
    # 明显大于中间" —— 裁在描边上时那几列是亮的/暗的细线（起伏大），
    # 裁在面板内或面板外则是平滑区（起伏接近 0）。
    g = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY)
    res = np.abs(g.astype(np.int16) - cv2.medianBlur(g, WM_GK).astype(np.int16))
    bd = float(np.concatenate([res[:, :BORDER_BAND], res[:, -BORDER_BAND:]]).mean())
    mid = float(res[:, w // 2 - 100:w // 2 + 100].mean())
    print("     裁到面板本身 x %d..%d y %d..%d -> %dx%d（比例 %.4f）"
          % (x0, x1, y0, y1, w, h, w / float(h)))
    print("        边缘 %d 列的起伏 %.2f vs 中间 200 列 %.2f（前者必须更大 = 真的裁在描边上）"
          % (BORDER_BAND, bd, mid))
    assert bd > mid, "裁出来的边上没有描边 —— 裁歪了（裁进面板内或面板外了）"
    assert (w / float(h)) < 2.0, (
        "裁完的比例 %.2f 太宽 —— `pages.css` 那边用的是 `100% auto`（按宽度铺满，"
        "让描边永远压在卡片边上），那要求**出图比例小于卡片比例**（卡片实测 2.6461），"
        "否则图铺不满卡片高度、下面会露出空档。改这句之前先读 pages.css 那段。"
        % (w / float(h)))
    return out


def emit_fit(im, name, width, quality, ratio, band="center"):
    """先按目标**宽高比**裁掉两边、再交给 `emit()`。`ratio=None` = 不裁。

    为什么要这个函数（第十三次改版，左栏那张）：

      `整体左栏背景图.png` 是 **2048x1184（1.84:1 的横图）**，而它要去的地方
      —— 左栏那张导航卡 —— 实测 **167.14x683.14 CSS px，也就是 0.2447（1:4.09）**。
      直接铺 + `cover` 的话浏览器是**按高度**放大（横向那 13% 才用得上），
      2x 屏想让 1366 设备像素**不虚**，图就得出到 2500 宽 ≈ 150 KB ——
      而这张图**每一页的左栏都在下载它**（11 张页共用一个左栏、`/static/`
      又没有任何缓存头，见 `server.py` 的 `no_store` 那段），
      等于每次翻页白下 150 KB 去显示中间那 334 像素。裁成竖条之后 340 宽够用，
      一个像素不浪费。

      ⚠️ 这个裁法只在"源图是柔光渐变、没有主体"时成立 —— 这一张是。
         **换图之前先确认新图也是这样**：有主体（人、车、字、logo）的图裁掉两侧
         就是把主体裁掉了，那种图要么改调用、要么别裁。

    ★★ `band` 决定**从横图的哪一段切竖条**，这不是随手挑的：

      `"center"`（默认）—— 取正中间。适合"中间就是主体"的图。
      `"std"`          —— 扫一遍所有候选位置，取**灰度方差最大**的那一条，
                          也就是整幅图里明暗变化最丰富的一条（等于"取景时把镜头
                          对准最不空的那一块"）。判据是**方差**，不是"我挑了一张
                          好看的"，而且扫描结果每次都打出来，谁都能重跑复核。
                          ⚠️ 为什么 rail_bg 需要用这个：那张源图是"左下角一片蓝、
                             中上部一片白"的柔光渐变，**正中间恰好是最白的一段** ——
                             按 center 裁出来的左栏会几乎是一片白，等于没换
                             （`p05=231 中位=246`，量出来就是这样）。
                             用户上一轮报过一模一样的症状：「你换了吗 但是整体
                             显示出来还是太白 就是你背景没啥用」（见 `_check_bg.py`
                             开头）。所以这里**用方差挑**，让左栏真的看得见那张图。
                          ⚠️ 代价要认：这样挑出来的是图里最"花"的一段，可能更蓝、
                             和导航文字的对比度更低 —— 挑完**必须再看 `veil_report`
                             那几行**，按数字补白纱（左栏用的是 `.30`，见 CSS）。

    ⚠️ `ratio` 是**宽/高**。源图比目标还窄时只裁高度（横向那一条），
       这种情况在本仓库还没出现过，所以那条分支只是兜底、没有实测过。
    """
    if ratio:
        H, W = im.shape[:2]
        want_w = int(round(H * ratio))
        if want_w < W:
            if band == "std":
                # 每 8 像素试一个位置（候选之间必然重叠，够用了）；方差用灰度算。
                g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
                hb = int(round(H * BAND_TOP_FRAC))     # 上半段 = 导航四项那一段
                step, cands = 8, []
                for x0 in range(0, W - want_w + 1, step):
                    sl = g[:, x0:x0 + want_w]
                    cands.append((float(sl.std()),
                                  float(np.percentile(sl[:hb], 5)), x0))
                # ★ 两条判据，缺一不可：
                #   · **方差最大的那条优先** —— 它就是"明暗变化最丰富"的一段，
                #     铺到左栏上才看得出换了图（用户报过"还是太白/背景没啥用"）；
                #   · 但上半段的 p05 必须够白 —— 导航四项的字就压在那一段，
                #     左栏只有那一带有字（下面依次是空白和立绘），字底下的底
                #     过暗就直接把导航读没了。
                #   ⚠️ 这里**故意只看上半段**、不整条一起看：整条一起算的话，
                #      下方那片蓝（正落在立绘那一带的空白处）会把 p05 拉下来，
                #      于是判据会去挑一条上下全白的、等于又回到"看不出换了图"。
                #      也就是说：**这个下限是绑在版面布局上的**，左栏的版式一变
                #      （比如以后把入口挪到中间），这里的分段就得跟着改。
                ok = [c for c in cands if c[1] >= BAND_TOP_P05_MIN]
                pool = ok or cands
                pool.sort(reverse=True)
                picked = pool[0][2]
                # 报告只留**互相离得开**的候选（不然五条都是同一个蓝区域的邻位）
                top, shown = [], []
                for sd, pq, x0 in pool:
                    if all(abs(x0 - prev[2]) >= 200 for prev in top):
                        top.append((sd, pq, x0))
                    if len(top) == 6:
                        break
                for sd, pq, x0 in sorted(cands, reverse=True):
                    if all(abs(x0 - prev[2]) >= 200 for prev in shown):
                        shown.append((sd, pq, x0))
                    if len(shown) == 8:
                        break
                print("     竖条候选（%d 宽，按灰度方差从大到小；"
                      "上限 = 上方 %d%% 的 p05，要 ≥ %.0f）:"
                      % (want_w, int(BAND_TOP_FRAC * 100), BAND_TOP_P05_MIN))
                for sd, pq, x0 in sorted(shown, reverse=True):
                    mark = "  <- 选中" if x0 == picked else (
                        "" if pq >= BAND_TOP_P05_MIN else "  (上段太暗，落选)")
                    print("        x %4d..%-4d  方差 %5.1f  上段 p05 %5.1f%s"
                          % (x0, x0 + want_w, sd, pq, mark))
            else:
                picked = (W - want_w) // 2
            im = im[:, picked:picked + want_w]
            print("     裁成竖条 x %d..%d -> %dx%d（比例 %.4f，目标 %.4f）"
                  % (picked, picked + want_w, im.shape[1], im.shape[0],
                     im.shape[1] / float(im.shape[0]), ratio))
        else:
            want_h = int(round(W / ratio))
            y = max(0, (H - want_h) // 2)
            im = im[y:y + want_h]
            print("     裁成横条 y %d..%d -> %dx%d（比例 %.4f，目标 %.4f）"
                  % (y, y + want_h, im.shape[1], im.shape[0],
                     im.shape[1] / float(im.shape[0]), ratio))
    return emit(im, name, width, quality)


def _srgb_lum(gray):
    """0..255 灰阶 -> WCAG 相对亮度（0..1）。**不是** gray/255 —— sRGB 要先线性化。"""
    x = np.asarray(gray, dtype=np.float64) / 255.0
    x = np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)
    return x


def _hex_lum(rgb):
    """'#RRGGBB' -> WCAG 相对亮度。**按通道线性化之后再加权**，不是先把
    三个通道揉成一个灰阶值 —— 深蓝色揉成灰之后比它真实的亮度要亮，
    那样算出来的对比度会偏乐观（这一条正好是用来守"字够不够暗"的，不能乐观）。"""
    v = np.array([int(rgb[i:i + 2], 16) for i in (1, 3, 5)], dtype=np.float64) / 255.0
    v = np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)
    return float(0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2])


def _ratio(l1, l2):
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def veil_report(im, name, inks, bands=None, veil=0.30):
    """报一张底图**挂上去之前**的亮度，以及压上白纱之后正文还读不读得出。

    `inks` 是"这张图上会出现的字色"的列表 `(标签, '#RRGGBB')`。
    这一整段存在的理由：白纱那个数（`.30` 还是别的）**必须是量出来的**，
    凭眼睛调的下场是"一张洗过一张没洗"（第十二次改版两张并排的教训）。

    判据就是 WCAG 对比度 `(L1+.05)/(L2+.05)`，和 `_cov_contrast.py` 用同一个公式。
      · 底色取 **p05**（最暗的那 5%）—— 取均值等于拿"平均情况"糊弄，
        字正好压在暗部才是最差情况；p05 是"只有 5% 的面积比它还暗"。
      · 4.5:1 是正文线，3.0:1 是大字线。这个仓库里卡片标题是 1.05rem 上下的
        小字，所以**按 4.5 看**。
    ⚠️ 这一条量的是**图**，不是屏幕：字压在卡片自己的填充上（`.xq-bubble`
       有 `rgba(accent,.16)`）的情况这里算不出来，那种要靠截图量
       （`_shot_bgs4.py` 的"生效的底图"那一段 + `_cov_contrast.py` 的 band()）。
    ⚠️ 统计范围是**整张出图**。`.mon-xq` 那个 `cover` 会上下各切掉一截、
        `.rail-card` 那个基本不切 —— 整张统计对前者偏保守（把看不见的部分也算进来），
        **保守方向是对的**，别为了"更准"去改成一个依赖 box 比例的窗口：
        box 比例会随窗口大小变，那样这个数就只在某一种窗口尺寸下成立了。

    ★ `bands` = `[(标签, 起, 止), ...]`（0~1 的竖向比例）是**补充**给"整张统计会
      冤枉它"的那种图用的：左栏那一格是 1:4.5 的竖条，上面 30% 是四个入口（有字）、
      下面一大片是空白和立绘（**没字**）—— 整张的 p05 落在下面那片蓝上，
      报出来的对比度看起来是 3.10:1，可那片蓝**根本不在字底下**。
      给了 `bands` 就逐段把 p05 和对比度打出来，让"到底哪一段够不够"是看得见的数，
      而不是一句"我保证蓝的在没字的地方"。
      ⚠️ 分段比例是**按布局量出来的**（见 `BAND_TOP_FRAC`），版式一改就得重量。
    """
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    p05, p50, p95 = (float(np.percentile(g, q)) for q in (5, 50, 95))
    print("     亮度（0..255 灰阶）p05=%.0f 中位=%.0f p95=%.0f" % (p05, p50, p95))
    if bands:
        H = g.shape[0]
        print("     分段（整张那个 p05 落在没字的地方时，看这几行）:")
        for lab, a, b in bands:
            seg = g[int(round(a * H)):int(round(b * H))]
            if not seg.size:
                continue
            q5 = float(np.percentile(seg, 5))
            # ⚠️ 这里必须**把白纱压上去再算**（`p05*(1-veil)+255*veil`）——
            #    直接拿源图的 p05 去算会低报，而这一行是拿来判"某一个数够不够"的。
            L = float(_srgb_lum(q5 * (1 - veil) + 255 * veil))
            print("       %-8s 占 %3d%%~%3d%%  p05 %5.1f · 白纱 %.2f 后 %s"
                  % (lab, int(a * 100), int(b * 100), q5, veil,
                     " ".join("%s %.2f:1" % (l2, _ratio(L, _hex_lum(c)))
                              for l2, c in inks)))
    for veil in (0.0, 0.20, 0.30, 0.40):
        # 白纱是"白 0.30 盖在上面"，在灰阶上就是往 255 拉 30%
        v = p05 * (1 - veil) + 255 * veil
        L_bg = float(_srgb_lum(v))
        row = " ".join("%s %.2f:1" % (lab, _ratio(L_bg, _hex_lum(rgb)))
                       for lab, rgb in inks)
        print("     白纱 %.2f -> 最暗处 %.0f · 对比度 %s" % (veil, v, row))
    print("     ⚠️ 「白纱 0.00」那行是**不压纱**的对照；选哪个数看上面哪一行过 4.5:1，"
          "别凭眼睛挑。")


def main():
    os.makedirs(DST, exist_ok=True)

    # ---- 1. 封面那一路（`背景.png`）：原色一张 + 洗白一张 -------------------
    im = imread_u(SRC_COVER, cv2.IMREAD_COLOR)
    if im is None:
        raise SystemExit("读不到 %s" % SRC_COVER)
    print("=== 背景.png  %dx%d ===" % (im.shape[1], im.shape[0]))
    im = wm_crop(im, "背景.png")
    emit(im, "bg_scene.jpg", 1920, 88)
    sm = emit(im, "bg_wash.jpg", 1280, 80, blur=7.0)

    # ---- 2. 首页主视觉那一路（`首页背景.png`）：原色一张 -------------------
    hm = imread_u(SRC_HOME, cv2.IMREAD_COLOR)
    if hm is None:
        raise SystemExit("读不到 %s" % SRC_HOME)
    print("=== 首页背景.png  %dx%d ===" % (hm.shape[1], hm.shape[0]))
    hm = wm_crop(hm, "首页背景.png")
    hoy = emit(hm, "home_scene.jpg", 1920, 88)

    # ---- 3. 对照图：座舱那张洗完白之后还剩多少 -----------------------------
    # 这里模拟的是 CSS 里那层蒙版（白色 0.78）。看得见城市轮廓、但白卡片压上去
    # 不打架，就是对的；如果连轮廓都没了，说明蒙版该调浅。
    for w, tag in [(0.72, "0.72"), (0.78, "0.78"), (0.84, "0.84")]:
        wash = (sm.astype(np.float32) * (1 - w) + 255 * w).astype(np.uint8)
        cv2.putText(wash, ("white " + tag).encode(), (16, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 0, 0), 2, cv2.LINE_AA)
        if w == 0.72:
            strip = wash
        else:
            strip = np.hstack([strip, wash])
    op = os.path.join(ROOT, "runs", "_bg_wash_levels.png")
    cv2.imencode(".png", strip)[1].tofile(op)
    print("对照图 -> %s  （左到右：白色 0.72 / 0.78 / 0.84）" % op)

    # ---- 4. 对照图：新的首页主视觉底图看一眼 -------------------------------
    cv2.imencode(".png", hoy)[1].tofile(os.path.join(ROOT, "runs", "_home_scene.png"))
    print("对照图 -> runs/_home_scene.png  （首页主视觉的新底图，1920 宽）")

    # ---- 5. 2026-09-25 第十二次改版：用户新给的三张分区底图 -----------------
    # 三张都是 2848x1600、都带水印，走同一条 `wm_crop`。分别落到：
    #   media_playing.jpg  多媒体页「正在播放」那张卡（`.mp-hero`）
    #   media_music.jpg    多媒体页「我的音乐」那张卡（`.mp-lib`）
    #   cam_off.jpg        驾驶监测页**未接入摄像头**时那个取景框（`#stageHost`）
    # ⚠️ 三张的用途差别很大，所以**宽度不统一**：前两张是宽卡（横向铺满，
    #    1600 宽够 2x 屏），`cam_off` 是**竖着的取景框**，`cover` 会左右各切掉一半，
    #    1600 宽喂它等于浪费，所以给 1400。
    print("=== __NEW_BGS__ 三张分区底图 ===")
    for fname, out, w, q in SRC_3:
        p = os.path.join(ROOT, "ui", "图片效果", fname)
        if not os.path.isfile(p):
            raise SystemExit("读不到 %s" % p)
        im3 = imread_u(p, cv2.IMREAD_COLOR)
        if im3 is None:
            raise SystemExit("cv2 解不开 %s" % p)
        print("=== %s  %dx%d ===" % (fname, im3.shape[1], im3.shape[0]))
        im3 = wm_crop(im3, fname)
        emit(im3, out, w, q)
        # 每张都留一份"裁完之后"的缩略全图，眼睛过一遍：既要看不到水印，
        # 又要确认裁掉的那一条没有伤到构图（`cam_off` 是竖构图，尤其要看）。
        th = im3.copy()
        th = cv2.resize(th, (560, int(round(th.shape[0] * 560.0 / th.shape[1]))),
                        interpolation=cv2.INTER_AREA)
        tp = os.path.join(ROOT, "runs", "_bgs3_" + out.replace(".jpg", ".png"))
        cv2.imencode(".png", th)[1].tofile(tp)
        print("     缩略 -> runs/_bgs3_%s" % out.replace(".jpg", ".png"))

    # ---- 6. 2026-09-25 第十三次改版：用户新给的两张 -------------------------
    #   detail_xq.jpg  驾驶监测页「小瑞 · 智能陪伴」卡（`.mon-xq`）
    #   rail_bg.jpg    **左栏那张导航卡**（`.rail-card`，全站每一页都有）
    #
    # ★★ 宽度的账（两张不一样，各有各的理由）：
    #   · `detail_xq` = 1200。`.mon-xq` 实测 **538.39x203.47 CSS px（比例 2.6461）**，
    #     2x 屏 = **1077 设备像素宽**。CSS 那边用的是 `100% auto`（**按宽度铺满**，
    #     不是 `cover` —— 理由写在 `pages.css` 那段：`cover` 在卡片变窄时会改成
    #     按高度铺，那两条描边就被裁到画面外，等于白裁面板那一步）。
    #     按宽度铺满 ⟹ 出图宽度对着 1077 给就行，1200 留一点余量。
    #     ⚠️ 代价说清楚：`100% auto` 之后画面上只剩面板**中间那 53% 高**，
    #        也就是说**上下两条描边看不见**（左右两条正好压在卡片边上，和卡片
    #        自己的边合成一条 —— 这正是用户要的）。这是"用户给的是一张画好的
    #        面板、而卡是 2.65:1 的横条"必然的结果，**不是 bug**；
    #        真要看效果就 `_shot_bgs4.py` 截图看，别看这个数推。
    #   · `rail_bg` = 340。左栏那一格 2x 屏要 **334 设备像素宽**，给 340 刚好。
    #     它**先被裁成 0.22 的竖条**（245px 宽），也就是说这 340 是**放上来的**
    #     （1.39x）。柔光渐变放大 1.39 倍看不出来，而且这一格的上下两头正好被
    #     四个入口和立绘压着 —— 但**换图之前要确认新图也经得起放大**。
    print("=== __NEW_BGS2__ 两张分区底图 ===")
    INKS = {
        # 这张卡上真正的字：(卡名 `.card-h h3` / 气泡正文 `.xq-bubble`)。两个都是
        # 浅色主题的深墨，值抄自 style.css 的 `html[data-theme="light"]` 那一段。
        "detail_xq.jpg": [("卡名", "#0E2A4A"), ("气泡", "#14406F")],
        # 左栏上真正的字只有导航项：普通项 `--ink-4`、选中项 `--accent`（浅色档）。
        "rail_bg.jpg": [("导航项", "#33689E"), ("选中项", "#1E7FD8")],
    }
    # 左栏那一格的分段（只给 rail_bg 用）—— **按版面布局量的**，不是平均切三段：
    #   上段 = 四个入口（唯一有字的带子）；中段 = 卡片中间那段空白；
    #   下段 = 立绘（`.rail-xr` 13.4rem 贴底，没有字）。
    # ⚠️ 比例是**竖条出图**上的比例，`cover` 之后上下各切掉 ~5.8%，
    #    所以"出图上 32%"落在"卡片上 30%"，和四个入口占卡片上部 30% 正好对上。
    BANDS = {"rail_bg.jpg": [("导航四项", 0.00, BAND_TOP_FRAC),
                             ("中段空白", BAND_TOP_FRAC, 0.62),
                             ("立绘", 0.62, 1.00)]}
    for fname, out, w, q, ratio, band in SRC_4:
        p = os.path.join(ROOT, "ui", "图片效果", fname)
        if not os.path.isfile(p):
            raise SystemExit("读不到 %s" % p)
        im4 = imread_u(p, cv2.IMREAD_COLOR)
        if im4 is None:
            raise SystemExit("cv2 解不开 %s" % p)
        print("=== %s  %dx%d ===" % (fname, im4.shape[1], im4.shape[0]))
        # ⚠️ 顺序不能反：**先裁水印**（它的窗口 y 1400..1728 是按原图量的），
        #    再裁面板框。反过来的话窗**口落到图外**，`wm_crop` 会因为窗口里一行
        #    都不超阈值而当场停（"没找到水印"），报的还是个看不懂的错。
        im4 = wm_crop(im4, fname)
        im4 = frame_crop(im4, fname)
        out4 = emit_fit(im4, out, w, q, ratio, band)
        veil_report(out4, out, INKS[out], BANDS.get(out))
        # 缩略图按**宽和高两个方向一起**夹（第 5 段只夹了宽）：这一轮有一张是
        # 340x1540 的竖条，只夹宽等于不缩，丢出来的 PNG 比例和屏上看到的还不一样。
        s = min(560.0 / out4.shape[1], 900.0 / out4.shape[0], 1.0)
        th = cv2.resize(out4, (max(1, int(out4.shape[1] * s)),
                               max(1, int(out4.shape[0] * s))),
                        interpolation=cv2.INTER_AREA)
        tp = os.path.join(ROOT, "runs", "_bgs4_" + out.replace(".jpg", ".png"))
        cv2.imencode(".png", th)[1].tofile(tp)
        print("     缩略 -> runs/_bgs4_%s" % out.replace(".jpg", ".png"))


main()
