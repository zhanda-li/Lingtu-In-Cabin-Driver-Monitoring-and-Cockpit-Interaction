"""从 ui/图片效果/10.png 抠出小瑞（原创角色）的 8 个界面资产。

**取代 `_mk_mascot.py`**（那份是从 7.png 抠雪宝的，那些常量全是雪宝的构图，
一个都不能照搬；但**它踩过的坑这里全都要接着踩**，见下）。

## 为什么不能"白色 -> 透明"

小瑞**本体就是白的**，设定图的底是**浅紫白渐变**。按亮度抠会把他自己挖空 ——
和雪宝那次的坑一模一样，`_mk_mascot.py` 的 docstring 里写着。

实测的关键（`_probe_sheet.py` 探的，不是猜的）：**不能用单一色偏轴**。
  底色 b-r = +14（偏紫蓝）    小瑞的白身子 b-r = **-14**（r 反而高）    蓝头发 b-r = +120
底色正好夹在他两种区域中间 —— 任何一条"色偏阈值"都会切掉他要不然就是切不掉背景。
所以用**到局部背景的 RGB 向量距离**，两个方向都算偏离。

## 背景怎么估

设定图的底是平滑渐变（左上浅紫 217,229,247 → 右下近白），**全图一个常量背景不行**。
做法：降采样 4 倍 → 每通道 15×15 中值（等价原图 60×60 窗口）→ 升回来。
降采样是必须的：原图 1254² 上直接跑 51×51 中值滤波是 4×10⁹ 量级，要几分钟。

## 阈值 12

8 有余晕、12 干净、18 开始在**白额头**上打洞、26 把脸挖空。白本体的上限很窄，
所以换构图就必须重标一次，不能照搬（`_probe_sprite.py` 里那张对比图是这么来的）。

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch/_mk_xiaorui.py

产出 ui/web/assets/xiaorui_*.png + _scratch/_sprite_probe/qa_3x.png（3 倍放大贴深底，
**边缘干不干净只能靠这张看**）。
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SRC = Path("ui/图片效果/10.png")
DEST = Path("ui/web/assets")
QA = Path("_scratch/_sprite_probe")
THR = 12
STRONG_D = 90     # "这行有实体"的判据，用来砍掉脚下的地面投影（详见 cut() 里那段）
GRAD_G = 22       # 底部横带里"这里有边界"的亮度梯度阈值（实测取值，见 cut()）
BAND_FROM = 0.85  # 只有下面这 15% 的行做梯度收窄

# 各图的取景窗（含留白）。坐标**实测**自 _probe_sheet.py 打出来的连通块 bbox：
#   #1 主形象 x[50..661] y[28..654]
#   #46 打招呼 x[85..225] y[703..878]    #47 开心   x[278..413] y[704..878]
#   #49 感动   x[467..603] y[705..878]   #45 眨眼   x[667..804] y[699..879]
#   #44 出发   x[884..1027] y[693..854]  #48 疑问   x[1072..1198] y[704..877]
# 每个方向各留 ~14 px 余量。⚠️ 下边界压在 890：动作名（打招呼/开心…）实测在
# y[930..948]，留 40 px 余量就不会把字切进来。
# ⚠️ 主形象窗的**下边界压在 655**，这条很关键：主形象 bbox 下沿是 y=654，
# 而「表情 / 动作延展」那行标题实测在 y[655..685] —— **两者上下紧挨着，一格不差**。
# 我一开始写到 669，结果标题的左半截（x 36~181）被当成分量抠进来，主形象底下挂了
# 一条白影。分开它们的**不是 y 而是 x**（标题在 x[28..181]，主形象的脚在 x≥247），
# 所以"只留最大连通块"也能兜住，但窗先收窄更直接。
HERO_WIN = (36, 14, 676, 655)
ACT_Y = (688, 890)
ACT_COLS = [(70, 240), (263, 428), (452, 618), (652, 819), (869, 1042), (1057, 1213)]
ACT_NAMES = ["hello", "happy", "moved", "wink", "go", "ask"]



def background(rgb):
    """降采样 + 大窗口中值估出的背景图（同尺寸）。"""
    h, w, _ = rgb.shape
    # ⚠️ PIL 不收 float32（`Cannot handle this data type: (1,1,3), <f4>`）——
    # 降采样这一步本来就要转回 8 位，反正背景估的是低频，量化误差无所谓。
    small = np.asarray(Image.fromarray(rgb.astype(np.uint8)).resize(
        (w // 4, h // 4), Image.BOX)).astype(np.float32)
    bg = np.dstack([ndimage.median_filter(small[..., c], size=15) for c in range(3)])
    return np.asarray(Image.fromarray(bg.astype(np.uint8)).resize((w, h), Image.BILINEAR)
                      ).astype(np.float32)


def matte(sub, bg):
    """到局部背景的 RGB 距离 > THR 的就是他，再补洞、去噪。返回 (掩码, 距离)。

    `binary_fill_holes` 是关键：深色描边围住的**白色内部**（肚子、额头高光）
    距离背景很近，不补的话身上全是洞。
    """
    d = np.sqrt(((sub - bg) ** 2).sum(2))
    m = d > THR
    m = ndimage.binary_closing(m, np.ones((5, 5), bool), iterations=2)
    m = ndimage.binary_fill_holes(m)
    m = ndimage.binary_opening(m, np.ones((3, 3), bool))
    return m, d


def cut(rgb, bg, win, label):
    """在 win 里抠出主体，返回 (RGBA 图, alpha 掩码, 主体 bbox)。"""
    x0, y0, x1, y1 = win
    sub = rgb[y0:y1, x0:x1]
    m, d = matte(sub, bg[y0:y1, x0:x1])
    # 亮度梯度（sobel）。先高斯平滑一下再求导，否则 3D 渲染的噪点也算成"边界"。
    lum = ndimage.gaussian_filter((sub * [0.299, 0.587, 0.114]).sum(2), 1.0)
    grad = np.hypot(ndimage.sobel(lum, 0), ndimage.sobel(lum, 1))

    lab, n = ndimage.label(m, structure=np.ones((3, 3)))
    if not n:
        raise SystemExit("%s：窗里什么都没抠到，阈值 %d 太高了？" % (label, THR))
    sz = ndimage.sum(m, lab, range(1, n + 1))
    big = int(np.argmax(sz)) + 1

    # ★ **只留最大连通块**，别的一律丢掉。
    #
    # 我先写成"留住所有 >120 px 的块"，想的是别把出发的拖尾丢了 —— **那是错的**，
    # 一跑就露馅（出发那格抠出来脑袋右边挂着半颗金色小星星、脚下一条白影）。
    # 实测：拖尾本来就是连在身上的（同一块），而下面这些东西都是**独立的小块**，
    # 留着就是脏点：
    #   · 设定图给每个小人脚下画的**白色投影椭圆** —— 贴到深色座舱底上就是一道白抹痕
    #   · 格子边界附近**邻格/装饰的碎片** —— 出发那格右边半颗金星（只抠到一半，
    #     看着像坏了）
    #   · 主形象下面那行「表情 / 动作延展」标题的左半截（见 HERO_WIN 的注释）
    # 所以"最大块"这一条同时干掉了这三种。丢掉的块数打出来，跑的时候能看见。
    m = lab == big

    # ★★ **去掉脚下的"地面投影"** —— 这一步花了最久，把走过的弯路写下来。
    #
    # 设定图给每个小人脚下都画了一片**浅蓝的接触阴影**，和脚是连着的（所以"只留
    # 最大块"拦不住）。浅底设定图上那是正常的；贴到深色座舱底上就是一块**浅色脏印**。
    # 实测：主形象在封面渲染成 180 px 时**很明显**（对照 _cover_mock.png）。
    #
    # ⚠️ **别再用亮度/阈值这条路了，走不通的**：脚上白靴子的 d 中位数是 **14.5**，
    # 投影是 **18~30** —— **投影比脚还"实"**。任何"调高阈值"都会先把脚砍掉。
    # 也试过全图梯度当判据，投影是去掉了，但背景噪声也一起进来，而且角色的细部件
    # （飘带尖、耳环）掉 20~40% 面积。这些都实测过，脚本 `_probe_shadow.py` 里有记录。
    #
    # ✅ 走通的是**只在最底下那条横带里**用梯度收窄：
    #   实体有明确边界 -> 该处亮度梯度大；投影是软过渡 -> 梯度小。
    #   上面 85% 一律不动（飘带、发冠、耳环全在那里，一收就掉），
    #   只收底部 **15%** —— 那一段角色只有腿和脚，又粗又没有细部件。
    # 实测底部 14 行掩码的最左边界：G=10 -> x293、G=14 -> 302、G=18 -> 318、
    # G=22 -> **323**，而脚本身在 x=324。所以 §G=22 正好收到脚边，面积只掉 2.4%。
    solid = grad > GRAD_G
    yb = int(m.shape[0] * BAND_FROM)
    band = slice(yb, None)
    m[band] &= (solid[band] | (d[band] > STRONG_D))
    m = ndimage.binary_closing(m, np.ones((5, 5), bool), iterations=2)
    m = ndimage.binary_fill_holes(m)      # 收窄后腿肚子可能被掏空，这里补回来

    # 再把**完全在脚以下**的那几行整行砍掉。判据是"这一行有没有实体"：
    #   投影行 d_max 23~62，实体行 d_max 90~292（脚底有深色折缝），中间空得很开。
    # 实测砍掉的行数：主形象 10，打招呼 1，开心 1，眨眼 2，感动/出发/疑问 0
    # （出发底部是蓝色拖尾、d 很大，所以一行不砍 —— 这条不会误伤它）。
    strong = (d > STRONG_D) & m
    rows = np.where(strong.any(axis=1))[0]
    # ⚠️ 砍掉的行数要拿**主体的下沿**算，不能拿 m.shape[0] —— 那是**窗口**高度，
    # 窗口底下还空着一截。第一版减错了被减数，明明只砍 10 行却报成 14。
    bottom_before = int(np.where(m)[0].max()) + 1
    y_cut = int(rows.max()) + 1 if rows.size else bottom_before
    trimmed = max(0, bottom_before - y_cut)
    if trimmed > 0:
        m[y_cut:] = False

    ys, xs = np.where(m)
    bx0, bx1, by0, by1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    m = m[by0:by1, bx0:bx1]

    # 内部做实、只在边缘羽化：直接用 m 当 alpha 会让内部大片半透明，
    # 贴到深色底上就是一块斑驳的灰（艺术字那次踩过，`_logo_cut.py` 有记）。
    al = np.clip(ndimage.gaussian_filter(m.astype(np.float32), 0.9) * 1.35, 0, 1)
    out = np.dstack([rgb[y0 + by0:y0 + by1, x0 + bx0:x0 + bx1].astype(np.uint8),
                     (al * 255).astype(np.uint8)])
    print("  %-8s 窗 %-22s -> %dx%d  bbox x%-3d y%-3d（窗内）  连通块 %d，丢 %d，砍掉投影 %d 行"
          % (label, "%d,%d-%d,%d" % win, bx1 - bx0, by1 - by0, bx0, by0,
             n, n - 1, trimmed))
    return Image.fromarray(out, "RGBA"), al, (bx0, by0, bx1, by1)


# ---------------------------------------------------------------------------
im = Image.open(SRC).convert("RGB")
rgb = np.asarray(im).astype(np.float32)
print("原图 %dx%d" % (im.width, im.height))

bg = background(rgb)

print("\n抠图：")
hero, hero_al, _ = cut(rgb, bg, HERO_WIN, "hero")
hero.save(DEST / "xiaorui_hero.png")

# 打一行行宽 profile。⚠️ **这张表读不出头像的取景框**（别指望它）：飘带在 y 上
# 和头是重叠的，y=340 起 x 左端从 158 一路甩到 11，那是飘带不是头。所以头像的框
# 是看**网格图**定的，见下面那段。这张表留着是为了核对"哪几行开始是飘带"。
print("\nhero 的行宽 profile（每 20 行一个点）：")
for y in range(0, hero_al.shape[0], 20):
    row = hero_al[y] > 0.5
    w = int(row.sum())
    if w:
        xs = np.where(row)[0]
        print("   y=%-4d 宽 %-4d x[%d..%d]" % (y, w, xs.min(), xs.max()))

for name, win in zip(ACT_NAMES, [(x0, ACT_Y[0], x1, ACT_Y[1]) for x0, x1 in ACT_COLS]):
    img, _, _ = cut(rgb, bg, win, name)
    # ⚠️ `/` 的右边必须是完整字符串：`DEST / "x_%s.png" % name` 会先算 `DEST / "x_%s.png"`
    # 得到 Path，再拿 Path 去 `% name`，报 "unsupported operand type(s) for %"。
    img.save(DEST / ("xiaorui_%s.png" % name))

# ---------------------------------------------------------------------------
# 再出一张**方**的头像版，给 6 个静态小方槽（2.2~4.6rem）。
#
# **为什么不能直接拿主形象去方槽里缩**：主形象是 612x613，方槽最小只有
# 2.2rem(28px)，整身缩进去脸上的五官就糊成一团了；而且好多槽是圆的
# （border-radius:50%），整身塞进圆里只剩一条。所以头像**必须单独裁一张**
# 脸占大比例的。这个坑 `_mk_mascot.py` 当年也踩过，注释在它那份里。
#
# 取景框是**看着网格图定的**（`_probe` 阶段打的 hero_grid.png，50px 一格），
# 不是目测猜的 —— 主形象的行宽 profile 读不出头的边界，因为**飘带在 y 上和头
# 重叠**（y=340 起 x 左端从 158 一路甩到 11，那是飘带不是头）。
# 定下来的 box：x 200..600、y 40..440，边长 400。这个框：
#   · 两条**智能耳环**都在（右耳环到 x=612，600 只切掉最外一点点）—— 那是这个
#     角色的标志件，切没了就不认得是他了
#   · 脸不在正中而是**偏右**：他头是侧着的，所以框也跟着偏右
#   · 发冠尖端（y 0~40 那根细丝）不要了，留着反而显得头顶被削平
# 对照图（4 个候选并排）在 _head_cands.png。
HEAD_SIDE, HEAD_X, HEAD_Y = 400, 200, 40
head = hero.crop((HEAD_X, HEAD_Y, HEAD_X + HEAD_SIDE, HEAD_Y + HEAD_SIDE))
head.save(DEST / "xiaorui_head.png")
print("\n头像 %s  %s  （从主形象 x%d,%d 起裁 %d 见方）"
      % ("xiaorui_head.png", head.size, HEAD_X, HEAD_Y, HEAD_SIDE))

# ---------------------------------------------------------------------------
# 3 倍放大贴深底 —— 边缘干不干净、脸上有没有洞，**只能靠这张看**。
BAR = np.array([10, 18, 28], np.float32)
tiles = []
for p in sorted(DEST.glob("xiaorui_*.png")):
    if p.stem == "xiaorui_head":
        continue
    a = np.asarray(Image.open(p).convert("RGBA")).astype(np.float32)
    k = max(1, int(np.ceil(300 / a.shape[0])))          # 高度都拉到 ~300 再看
    big = a if k == 1 else np.asarray(
        Image.open(p).convert("RGBA").resize((a.shape[1] * k, a.shape[0] * k),
                                             Image.LANCZOS)).astype(np.float32)
    al = big[..., 3:4] / 255.0
    tiles.append(big[..., :3] * al + BAR * (1 - al))

wsum = sum(t.shape[1] for t in tiles)
hmax = max(t.shape[0] for t in tiles)
sheet = np.tile(BAR, (hmax, wsum, 1))
x = 0
for t in tiles:
    sheet[:t.shape[0], x:x + t.shape[1]] = t
    x += t.shape[1]
Image.fromarray(sheet.astype(np.uint8)).save(QA / "qa_3x.png")
print("\nQA 放大图 -> %s  （从左到右按文件名）" % (QA / "qa_3x.png"))
for p in sorted(DEST.glob("xiaorui_*.png")):
    print("   %-22s %s  %4d KB" % (p.name, Image.open(p).size, p.stat().st_size // 1024))
