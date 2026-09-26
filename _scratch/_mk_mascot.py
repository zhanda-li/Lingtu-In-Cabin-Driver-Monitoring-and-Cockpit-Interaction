"""⚠️ **已被 `_scratch/_mk_xiaorui.py` 取代（2026-09-23）** —— 那份从 10.png 抠
用户自己的原创角色「小瑞」，产物是 `ui/web/assets/xiaorui_*.png`（8 张：
hero / head / 六个动作）。本脚本**不再产生界面上任何一张图**，留着只有两个理由：

  1. `7.png`（雪宝那版）还在盘上，这个脚本记录了那一版的构图常量；
  2. **它踩过的坑这里全踩过一遍**（白底白角色不能按亮度抠、只保留最大连通域、
     羽化不能拿原始偏离度当 alpha），新脚本是照着这些结论写的，别删证据。

真要用它跑出图来，产物是 `ui/web/assets/xiaoqi{,_head}.png` —— 那两个名字已经
不在 `.gitignore` 里了，但**界面上没有任何代码再引用它们**。

-----------------------------------------------------------------------------
从 ui/图片效果/7.png 抠出小奇形象（白底 -> 透明）。

**为什么要抠**：7.png 是不透明白底。直接贴进深色座舱界面会是一块白方块。
主体本身是白/浅蓝的，所以不能简单"白色->透明"——那会把他自己也挖空。
判据用两条一起：
  1. 亮：min(r,g,b) >= 246
  2. 中性：max-min <= 6（背景是纯灰白；他身上有蓝调，b 比 r 高十几）
只有**从边框连通**的这类像素才算背景，内部高光不会被误挖。

剩下两类残留要单独处理（都实测过坐标，不是猜的）：

  * **树枝围出来的白**（y 18~170）——封闭区域，边框连通法够不着，会留成两块
    白色"叶子"。做法：对 y<178 范围内的封闭白块直接挖掉。
    ⚠️ **不能全图挖**：他的额头和身体高光也是纯白（y 185~317 实测有块），
    全图挖会在脸上打洞。178 这条线是看着 y=185 那块定的。

  * **底部 Disney / FROZEN II 版权行**（x 154~255, y 772~807）——那是迪士尼的
    商标，不能跟着进作品集。它和脚**在 x 方向重叠**（左脚左缘实测 x≈212），
    所以"抹掉那个矩形"会切到脚。改成**在 y=768 直接裁掉**：身体圆球下缘实测
    在 y 766~774，裁掉 6 px 看不出来，换来版权行和底座一起消失。
"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage

SRC = Path("ui/图片效果/7.png")
OUT = Path("ui/web/assets/xiaoqi.png")
CUT_Y = 768          # 版权行上沿之下、身体下缘之上（见上面注释）
TWIG_Y = 178         # 这个高度以上的封闭白块算树枝空隙

im = Image.open(SRC).convert("RGB")
a = np.asarray(im).astype(np.int16)
lo, hi = a.min(axis=2), a.max(axis=2)
cand = (lo >= 246) & ((hi - lo) <= 6)

lab, n = ndimage.label(cand)
# 1) 与边框连通的 = 背景
border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])))
border.discard(0)
bg = np.isin(lab, list(border)) if border else np.zeros_like(cand)
# 2) 顶部封闭的白 = 树枝空隙
twig = np.zeros_like(cand)
twig[:TWIG_Y] = cand[:TWIG_Y] & ~bg[:TWIG_Y]

fg = ~bg & ~twig
fg[CUT_Y:] = False          # 版权行 + 底座

lab2, n2 = ndimage.label(fg, structure=np.ones((3, 3)))
sizes = ndimage.sum(fg, lab2, range(1, n2 + 1))
keep = int(np.argmax(sizes)) + 1
fg = lab2 == keep
print(f"连通块 {n2} 个，留最大的（{int(sizes.max())} px），丢 {int(sizes.sum() - sizes.max())} px")

ys, xs = np.where(fg)
y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
print(f"主体 bbox ({x0},{y0})-({x1},{y1})  原图 {im.width}x{im.height}")

alpha = (fg[y0:y1, x0:x1] * 255).astype(np.uint8)
img = Image.fromarray(np.dstack([a[y0:y1, x0:x1].astype(np.uint8), alpha]), "RGBA")
img.putalpha(img.getchannel("A").filter(ImageFilter.GaussianBlur(0.6)))

img.save(OUT)
print(f"写出 {OUT}  {img.size}  {OUT.stat().st_size / 1024:.0f} KB")

# ---------------------------------------------------------------------------
# 再出一张**方**的头像版。
#
# **为什么需要**：整身是 290x756（1:2.6 的竖图）。界面里头像位、手机端 hero、
# 封面右边的光晕都是**接近正方**的槽，`object-fit:contain` 把竖图塞进方槽，
# 宽度只剩槽的 1/2.6 —— 小奇在头像里缩成一条，基本看不清脸。三个页面各自
# 用 workaround 绕过（05 自己裁头、09/10 干脆不用真图退回内置 SVG），
# 结果是**同一个角色在作品集里长成两个样**，这比图不好看严重。
#
# 正解是出资源的时候就按用途给两张：竖的给立绘位，方的给头像位。
#
# 头的范围是**实测**的（对 alpha 逐行数宽度，见当时打印的 profile）：
#   y 0~155   树枝（细，宽 5~80 px）
#   y 155~480 头（y=240 最宽 244 px —— 那是连胡萝卜鼻子一起）
#   y ~470    脖子，宽度掉到最低 113
#   y 490+    身体
# 所以头取 y=140 起（带一点树枝，不然认不出是他），到 480 收，用来定头的横向范围。
HEAD_TOP, HEAD_BOT = 140, 480
sub = np.asarray(img)[HEAD_TOP:HEAD_BOT]
al = sub[:, :, 3] > 16
xs_h = np.where(al.any(axis=0))[0]
hx0, hx1 = int(xs_h.min()), int(xs_h.max()) + 1

# 方边长**不能超过图宽**：整身只有 290 宽，而头+脖子有 340 高，取 340 就只能
# 靠 PIL 越界补透明 —— 补出来的右侧空条会把脸挤到左边，圆头像框里一眼就歪。
# 所以边长封顶到图宽，纵向以**脸**（不是整条头+脖子）为中心取。
side = min(max(hx1 - hx0, HEAD_BOT - HEAD_TOP), img.width)
FACE_CY = 268          # 实测：y=240 是最宽处（连胡萝卜鼻子），眼睛在它上方一点
by0 = max(0, min(FACE_CY - side // 2, img.height - side))
bx0 = max(0, min((hx0 + hx1) // 2 - side // 2, img.width - side))
head = img.crop((bx0, by0, bx0 + side, by0 + side))

# 输出就是正方形，槽位（多半是圆的 border-radius）直接 contain/cover 都行，
# 不用每个槽各写一遍 object-position 去补正。
HEAD_OUT = Path("ui/web/assets/xiaoqi_head.png")
head.save(HEAD_OUT)
print(f"写出 {HEAD_OUT}  {head.size}  {HEAD_OUT.stat().st_size / 1024:.0f} KB"
      f"  （头 bbox x {hx0}~{hx1}，方边长 {side}，左上角 ({bx0},{by0})）")
