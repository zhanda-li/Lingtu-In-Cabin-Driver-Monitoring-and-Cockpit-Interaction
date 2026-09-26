# -*- coding: utf-8 -*-
"""从 ui/图片效果/11.png 的 IP 手册里抠出小瑞的 16 个姿态 -> ui/web/assets/xiaorui_*.png

10 个表情（表情延展 EXPRESSIONS，2 行 x5）+ 6 个动态动作（动态动作 ACTION POSES，2 行 x3）。

## ⚠️ 结局：只采纳了 10 格，「动态动作」那 6 格**抠不出来、没用**

表情格（浅蓝卡片底）10 格干净；动态动作格（**白/极淡蓝底**）6 格**全部失败** ——
下半身被掏成洞，贴到深色槽上就是身上破一个洞。已从 assets 删掉，live.js 的 ACTS
也只留 10 个。**这不是参数没调好**，是那 6 格上颜色通道里没有区分信息：
`_scratch/_probe_cheer.py` 实测身体 R-B 中位 **+0**、背景 **−1**，扫了四组阈值，
最好的一组仍把 **26% 的身体**判成背景。边缘/泛洪那条路同样堵死：原画是柔和喷绘，
格子内到处是弱边缘（Sobel 幅值中位 20，而角色占比才 35%），墙一闭就把整格封死
（`_scratch/_try_flood.py`，16 组参数前景占比全在 48~98%）。

**要补齐这 6 个动作，只能请美术从 3D 源导一张透明底的 PNG**，别再在 11.png 上试阈值。

## 逐格独立估底色（不能全图一个值）

每格底色略有差别，而且 11.png 版面密（60x60 的窗口会跨格，把邻格的画和字混进来）。
做法：每格取**四角 12x12 的补丁**求中位数当底色。取四角而不是整圈：
卡片上沿/下沿常被角色的头发尖、脚、飘带顶到，整圈中位数会被污染。

⚠️ **这个底色只用来打印日志**，不参与判定 —— 拿它当判据是前两代的死因（见下）。

## 「小瑞细节」= 抠图验收清单（用户点名的第二处）

11.png「细节展示 DETAILS」那一行给了六个必须一眼认得出的特征，抠完要逐格核：
    炯炯有神的大眼睛 / 渐变蓝发 / 发光耳机（∞ 会亮） / 柔软围巾 / 星星尾巴 / 胸前 LOGO
最容易丢的两处：**发光耳机的辉光**（低对比过渡区，阈值一高就削掉）、
**星星尾巴和围巾飘带末端**（全图最细的部件，最小连通块判据会吃掉）。
QA 图放大 3 倍贴深底，就是为看这两处。

    D:\Anaconda3\envs\dms\python.exe _scratch/_mk_xiaorui16.py
"""
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from scipy import ndimage

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SRC = Path("ui/图片效果/11.png")
DEST = Path("ui/web/assets")
QA = Path("_scratch/_sprite_probe")

# ============================ 抠图判据（改过三版，前两版都错，别重踩）============================
# 素材的**关键事实**：背景是**浅蓝卡片**，角色是**白身体**，两者都"亮 + 低彩度"。
# 所以"离底色多远"这条思路在这批图上**根本不成立**，前两版都死在这里、死法还不同：
#   第一版：全格取一个底色（四角中位数）+ THR=16 + `closing(5x5, iter=2)`。
#     卡片底色带**纵向渐变**（实测跨度 ~14，和 THR 同一个量级），格子顶部在阈值两侧
#     乱跳，再被那个接近 11x11 的等效核放大成**直角矩形** —— QA 图里的白色方块
#     （背景跳成前景）和黑色方洞（前景跳成背景）是**同一个原因的两个方向**。
#   第二版：改成逐行估底色。大部分格子修好了，但 `sleep` **整张卡片被留下**：
#     那一格角色大到顶住左右两边，"边缘色"取到的其实是角色自己，于是卡片反倒成了
#     "离底色很远"的前景。**只要还在估底色，就还有这一类失败模式。**
#   第三版（现在这版）：**不估底色**，改成逐像素判"这像不像那张浅蓝卡片"：
#         背景 = 很亮（最小通道 ≥ LIGHT_MIN）且偏蓝（R-B ≤ RB_MAX）
#     前景 = 上面那条的**取反**。
#     为什么成立：卡片是"白里透蓝"，R-B 恒为负（实测 -19 ~ -32）、且最小通道很高；
#     白身体是**暖白**（R-B 实测 +11，符号就分开了）；头发/围巾/眼睛是饱和蓝，
#     最小通道只有 70~200 那一档。三档在这两个轴上互不重叠。
#     ★ 它天然免疫渐变（没有参考色）、也不怕角色顶边（不看边缘）。
#     ★ 内部被误判成背景的小块（很淡的头发高光）由 `binary_fill_holes` 兜回来 ——
#       那些区域在角色**内部**，补洞能救；卡片在角色**外面**且连着窗口边框，救不回来，
#       这正是我们要的。
LIGHT_MIN = 205   # 背景的最小通道至少这么亮（卡片实测 212~254）
RB_MAX = 3        # 且 R-B 不超过它（卡片实测 -19 ~ -32，白身体 +11）
CORNER = 12       # 参考底色取四角多大一块，**只用于打印日志**，不参与判定

# 格子坐标：**实测**自 _probe_11.py 的连通块统计（129x143 的表情格 / 120x140 的动作格），
# 加油、庆祝两格的底色太接近白没被检出，按 导航/送爱心 的网格位置补。
#   (x0, y0, x1, y1, 名字)
CELLS = [
    # 表情延展 第 1 行
    (31, 743, 160, 886, "happy"),      # 开心
    (174, 743, 303, 886, "wink"),      # 眨眼
    (316, 743, 446, 886, "wow"),       # 惊讶
    (460, 743, 589, 888, "shy"),       # 害羞
    (605, 743, 735, 888, "angry"),     # 生气
    # 表情延展 第 2 行
    (31, 898, 160, 1040, "think"),     # 思考
    (174, 896, 303, 1040, "sad"),      # 委屈
    (316, 898, 450, 1040, "sleep"),    # 睡觉
    (460, 896, 590, 1023, "like"),     # 点赞
    (605, 896, 735, 1042, "heart"),    # 比心
    # 动态动作 第 1 行
    (785, 743, 904, 884, "wave"),      # 招手
    (938, 743, 1058, 881, "go"),       # 出发
    (1091, 743, 1211, 881, "navi"),    # 导航
    # 动态动作 第 2 行
    (785, 898, 904, 1038, "cheer"),    # 加油
    (938, 898, 1058, 1038, "celebrate"),  # 庆祝
    (1090, 898, 1210, 1042, "love"),   # 送爱心
]
CN = {"happy": "开心", "wink": "眨眼", "wow": "惊讶", "shy": "害羞", "angry": "生气",
      "think": "思考", "sad": "委屈", "sleep": "睡觉", "like": "点赞", "heart": "比心",
      "wave": "招手", "go": "出发", "navi": "导航", "cheer": "加油",
      "celebrate": "庆祝", "love": "送爱心"}


# 采纳名单 = 「表情延展」那 10 格。剩下 6 格照样切、但写到 `_rejected/`，不进 assets
# （原因和定量证据见文件头；`_scratch/_probe_cheer.py` / `_try_flood.py` 是判决书）。
KEEP = {"happy", "wink", "wow", "shy", "angry", "think", "sad", "sleep", "like", "heart"}
REJECT = QA / "_rejected"


def cell_bg(sub):
    """四角 12x12 的中位数。

    ⚠️ **它不参与判定**，只用来说日志里那句"参考底色(248,251,254)"，方便人工核对
       这批格子确实在同一个色系里。第一版拿它**当**底色用，16 张全坏（见文件头）。
    """
    c = CORNER
    h, w, _ = sub.shape
    patches = [sub[:c, :c], sub[:c, w - c:], sub[h - c:, :c], sub[h - c:, w - c:]]
    px = np.concatenate([p.reshape(-1, 3) for p in patches])
    return np.median(px, 0)


def cut(rgb, win, name):
    x0, y0, x1, y1 = win
    sub = rgb[y0:y1, x0:x1]
    ref = cell_bg(sub)                            # 只用于打印
    looks_like_card = (sub.min(2) >= LIGHT_MIN) & (sub[..., 0] - sub[..., 2] <= RB_MAX)
    m = ~looks_like_card                          # 判据正文见文件头那一段

    # ⚠️ 形态学**只能用小的**：第一版是 `closing(5x5, iterations=2)`，等效核接近
    #    11x11，把阈值抖动放大成了**直角矩形**。判据改对之后它不再必要。
    m = ndimage.binary_closing(m, np.ones((3, 3), bool))
    m = ndimage.binary_fill_holes(m)
    m = ndimage.binary_opening(m, np.ones((3, 3), bool))

    lab, n = ndimage.label(m, structure=np.ones((3, 3)))
    if not n:
        print("  %-10s !! 什么都没抠到（LIGHT_MIN=%d / RB_MAX=%d 判据在这格上不成立）"
              % (name, LIGHT_MIN, RB_MAX))
        return None
    sz = ndimage.sum(m, lab, range(1, n + 1))
    big = int(np.argmax(sz)) + 1
    m = lab == big
    dropped = n - 1

    ys, xs = np.where(m)
    bx0, bx1, by0, by1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    m = m[by0:by1, bx0:bx1]

    # 内部做实、只在边缘羽化。直接用 m 当 alpha 会让内部大片半透明，
    # 贴深色底上是一块斑驳的灰（艺术字那次踩过，_logo_cut.py 有记）。
    al = np.clip(ndimage.gaussian_filter(m.astype(np.float32), 0.9) * 1.35, 0, 1)
    out = np.dstack([rgb[y0 + by0:y0 + by1, x0 + bx0:x0 + bx1].astype(np.uint8),
                     (al * 255).astype(np.uint8)])
    img = Image.fromarray(out, "RGBA")
    # ⚠️ 动态动作那 6 格**不写进 assets**（抠出来是破的，见文件头）。切还是要切、
    #    写进 `_rejected/`，这样 QA 图上"好"和"坏"并排，一眼看得出判据在哪格失效。
    keep = name in KEEP
    (DEST if keep else REJECT).mkdir(parents=True, exist_ok=True)
    img.save((DEST if keep else REJECT) / ("xiaorui_%s.png" % name))
    print("  %-10s %-6s %dx%d  参考底色(%3d,%3d,%3d) 丢掉 %d 块  %s"
          % (name, CN[name], bx1 - bx0, by1 - by0,
             ref[0], ref[1], ref[2], dropped, "" if keep else "-> _rejected/（不采纳）"))
    return img


im = Image.open(SRC).convert("RGB")
rgb = np.asarray(im).astype(np.float32)
print("11.png %dx%d，抠 %d 格：" % (im.width, im.height, len(CELLS)))
made = []
for x0, y0, x1, y1, name in CELLS:
    r = cut(rgb, (x0, y0, x1, y1), name)
    if r is not None:
        made.append(r)

# 3 倍放大贴**棋盘格** —— 边缘干不干净、辉光和星星尾巴有没有丢，**只能靠这张看**。
#
# ⚠️ 三个坑（前两版都踩了，别重踩）：
#   1) **通道**：cv2.imwrite 按 BGR 解释数组，我喂的是 RGB —— 蓝色全变橙，
#      差点以为抠出来的小瑞是橙色的。写之前必须 RGB->BGR。
#   2) **槽位**：格子尺寸不一，直接把缩好的图贴进统一槽位，剩下的槽底会留成
#      深色矩形，看着像"身上被挖了个方洞"。必须先把每格**贴进统一大小的画布**再拼。
#   3) ★ **底色**：第一版贴的是深底 (10,18,28)（就是槽的实测色，看着最"贴近上线效果"）。
#      **这是个盲区**：白残留和深底一比就是亮的，看得见；但**白身体被抠掉**留下的洞
#      在深底上也是"暗的"，和"背景色"一模一样 —— 那一版就是这么把「动态动作 6 格
#      下半身被掏空」放过去的，图生成了却没人看出问题。
#      **棋盘格是唯一能同时看清"多出来的白"和"少掉的白"的底**，判据要能证伪才叫判据。
CHK = 12
BAR = np.array([64, 64, 64], np.float32)


def checker(h, w):
    yy, xx = np.mgrid[0:h, 0:w]
    on = (((yy // CHK) + (xx // CHK)) % 2 == 0)[..., None]
    return np.where(on, 205.0, 110.0).repeat(3, 2)
COLS = 8
bigs = []
for r in made:
    a = np.asarray(r).astype(np.float32)
    big = np.asarray(r.resize((a.shape[1] * 3, a.shape[0] * 3), Image.LANCZOS)
                     ).astype(np.float32)
    al = big[..., 3:4] / 255.0
    bigs.append(np.clip(big[..., :3] * al + checker(*big.shape[:2]) * (1 - al), 0, 255))
th, tw = max(t.shape[0] for t in bigs), max(t.shape[1] for t in bigs)
rows_n = (len(bigs) + COLS - 1) // COLS
sheet = np.tile(BAR, (rows_n * (th + 26), COLS * (tw + 12), 1)).astype(np.uint8)
for k, t in enumerate(bigs):
    r_, c_ = divmod(k, COLS)
    oy, ox = r_ * (th + 26) + 22, c_ * (tw + 12) + 6
    canvas = np.tile(BAR, (th, tw, 1)).astype(np.uint8)
    canvas[:t.shape[0], :t.shape[1]] = t.astype(np.uint8)
    sheet[oy:oy + th, ox:ox + tw] = cv2.cvtColor(canvas, cv2.COLOR_RGB2BGR)
    cv2.putText(sheet, "%s %s" % (CELLS[k][4], CN[CELLS[k][4]]),
                (ox + 4, oy - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                (140, 230, 255), 1, cv2.LINE_AA)
QA.mkdir(parents=True, exist_ok=True)
cv2.imwrite(str(QA / "qa16_3x.png"), sheet)
print("\nQA 放大图 -> %s  %dx%d  （%d 行 x %d 列，深底 3 倍）"
      % (QA / "qa16_3x.png", sheet.shape[1], sheet.shape[0], rows_n, COLS))
for x0, y0, x1, y1, name in CELLS:
    p = DEST / ("xiaorui_%s.png" % name)
    if p.exists():
        print("   %-24s %s  %4d KB" % (p.name, Image.open(p).size, p.stat().st_size // 1024))
