# -*- coding: utf-8 -*-
"""生成 `ui/web/assets/skyline.svg` —— 远景城市天际线剪影（浅色主题背景用）。

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch/_mk_skyline.py

## 这是什么、不是什么

**是一张占位板**，不是最终成品。用户 2026-09-23 拍板「先不生成图，先改页面」，
而浅色主题**本来完全没有天际线** —— style.css 里 `html[data-theme="light"]`
那条把 `--bg-img` 设成了 `none`（因为仓库里那张 `bg.jpg` 是**夜景**，
压在近白底上没法看）。所以"远处朦胧虚化未来城市天际线"这一项当时是缺的。

拿 SVG 顶上的理由：
  · 它是**矢量的**，4K 投影下不会糊（这一页是要投到幕布上的）；
  · 它**可以被一行替换掉** —— 以后用 Seedream 出一张真背景板，
    把 `--bg-img` 指过去就行，这个文件删了即可，不用改版式；
  · 纯 CSS 堆 `linear-gradient` 做不出"楼高不一"的剪影（重复渐变是等宽的），
    真的会看出一条等宽的方块阵。

## 剪影怎么画的

楼是**按固定序列**摆的，不是随机的 —— 随机数会让每次重跑产出不同的图，
而这张图是要进仓库的，同一个脚本必须每次给出同一个字节。
宽度 22~74、高度 34~126（画布 1200x150），层高不一；
每栋之间留 4~14 的空隙，否则会连成一堵墙，看着不像天际线。

⚠️ 颜色**不写在这里**：SVG 里 fill 用的是 `currentColor` 的替代品 ——
   实际写的是一个中间调的蓝，**透明度由 CSS 控制**（`opacity` 压在那一层上）。
   这样调浓淡不用重跑脚本，改 CSS 一个数就行。
   之所以不用 `currentColor`：`background-image` 里的 SVG 是**独立文档**，
   拿不到页面的 currentColor。
"""

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEST = Path("ui/web/assets/skyline.svg")
W, H = 1200, 150               # 画布：1200 宽是为了够铺满，150 高是楼最高 126 + 余量
FILL = "#6FA3D2"               # 中调蓝。浓淡交给 CSS 的 opacity，不在这里调。
# ⚠️ 这个色**改过一次**：第一版是 #9FC4E8，对着截图看是"糊斑不是楼"。
#    原因不是浓度（那是 opacity 管的），是**色相离天空太近** ——
#    浅色主题那片天在楼那一段大约是 #C9E0F8，两者只差十几个色阶，
#    再叠上 `.tint` 的白色底带就没了。往深、往饱和挪一档才分得开。
#    以后要再调，调完必须重新截图看（改这一个数就够，CSS 不用动）。

# (宽, 高) 序列。**写死的**，理由见上面"按固定序列"。
# 高矮是错落的：每隔几栋来一个矮的（34~48），再挑几个尖顶（118~126）当塔。
BLOCKS = [
    (54, 78), (38, 112), (66, 56), (26, 96), (48, 130), (72, 70), (34, 104),
    (58, 44), (44, 88), (30, 122), (62, 62), (40, 98), (52, 76), (28, 36),
    (70, 110), (46, 68), (36, 92), (60, 50), (42, 118), (32, 84), (56, 72),
    (44, 100), (64, 42), (30, 108), (50, 66),
]
GAPS = [10, 6, 12, 5, 9, 14, 7, 11, 6, 8, 13, 5, 10, 7, 12, 6, 9, 5, 11, 8, 6, 13, 7, 10]


def main():
    rects, x = [], 0
    i = 0
    while x < W:
        w, h = BLOCKS[i % len(BLOCKS)]
        rects.append((x, H - h, w, h))
        x += w + GAPS[i % len(GAPS)]
        i += 1
    # 收尾：最后那栋如果探出画布，裁到 W —— 留半截楼在边上比留空白更难解释
    last_x, last_y, last_w, last_h = rects[-1]
    if last_x + last_w > W:
        rects[-1] = (last_x, last_y, W - last_x, last_h)

    body = "\n".join(
        '  <rect x="%d" y="%d" width="%d" height="%d"/>' % r for r in rects)
    svg = (
        '<!-- 由 _scratch/_mk_skyline.py 生成，**别手改** —— 重跑会覆盖。\n'
        '     远景城市天际线剪影，浅色主题封面背景用。填色只有一个（%s），\n'
        '     浓淡由 CSS 的 opacity 控制；"朦胧"由 CSS 的 blur() 做。\n'
        '     换真图（Seedream 出的背景板）时这个文件可以整个删掉。 -->\n'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d"\n'
        '     preserveAspectRatio="none" fill="%s">\n%s\n</svg>\n'
    ) % (FILL, W, H, FILL, body)

    DEST.write_text(svg, encoding="utf-8")
    print("写出 %s  %d 栋楼  %.1f KB"
          % (DEST, len(rects), DEST.stat().st_size / 1024))

    hs = [h for _, _, _, h in rects]
    print("  楼高 %d~%d（画布高 %d，最高那栋离顶 %d px）"
          % (min(hs), max(hs), H, H - max(hs)))
    print("\n**这是占位板，不是最终成品**：以后拿真背景板换掉时，"
          "改 style.css 里那两条 --bg-img / 背景层即可。")


if __name__ == "__main__":
    main()
