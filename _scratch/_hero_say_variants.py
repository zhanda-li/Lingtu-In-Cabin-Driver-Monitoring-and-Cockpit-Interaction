# -*- coding: utf-8 -*-
"""「你好！我是小瑞～」这朵问候语到底摆哪儿 —— 出三档候选，各截一张，摆在一起看。

    MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' PYTHONIOENCODING=utf-8 \
        D:\\Anaconda3\\envs\\dms\\python.exe -u _scratch/_hero_say_variants.py [端口]

为什么这么干：用户 2026-09-25 晚说「**你好！我是小瑞那几个字下调 布局好一点
感觉不太好现在**」。一句话里有两个约束 —— **往下**（`top` 变大）和**别离人太远**
（上一轮的「放的离小瑞近一点」还在）。这两个是**打架的**：人现在钉在
`right:10.4rem; bottom:0`，头顶就在原来的气泡下面 15px —— 想再往下就得从
"头顶上方"挪到"脑袋旁边"。所以有三档不同取向，量着看，不靠猜。

⚠️ 视口跟 `_shot_index.py` / `_check_pages.py` 的 `Session` **一模一样**
   （`--window-size=1672,940`、不做 DPR 覆盖 -> 实际 1638x843），
   这样打出来的矩形和那两张截图**是同一套坐标**，可以指着截图说"就是这里"。
   （`_probe_dash_rects.py` 用的是 1672x940 覆盖值，和截图差 ~2%/10%，
   拿它的数去对截图会错位 —— 这次就是这么发现的两个视口不是一回事。）

⚠️ 改法是**往元素上写 inline style**，不动 `pages.css` —— 选完再写回文件。
⚠️ 收尾按**端口**收自己的 headless Edge（Session 自己管），绝不按镜像名杀。
"""
import asyncio
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _check_pages import Session          # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PORT = sys.argv[1] if len(sys.argv) > 1 else "8790"
CDP = 9432                                # 9431 是 _shot_index 的
SHOTS = Path(__file__).parent / "_shots"

# 三档。`right`/`top` 都按**面板**算（`.dash-say` 的定位父级是 `.dash-visual`）。
# ⚠️ 单位用 rem，和 pages.css 里一致（root 14.53px @1638x843）。
VARIANTS = [
    # A 头顶正上方、贴着头发 —— "往下"的最小改动（原 top:2.6rem -> 4.2rem，只降 23px）
    ("A_头顶上方", "right:7.4rem; top:4.2rem;"),
    # B 脑袋右边、和眼睛齐平 —— "下调"最多的一档，代价是那块底是闹市/塔楼（字容易糊）
    ("B_眼睛右侧", "right:3.2rem; top:9.2rem;"),
    # C 脑袋左上方那片天 —— 落在干净的亮天空上（对比度最好），也在原位置下方
    ("C_左上天空", "right:27.4rem; top:5.4rem;"),
]

RECTS = """JSON.stringify((() => {
  const R = (s) => { const e = document.querySelector(s); if (!e) return null;
    const r = e.getBoundingClientRect();
    return [+r.left.toFixed(1), +r.top.toFixed(1), +r.width.toFixed(1), +r.height.toFixed(1)]; };
  const inter = (a, b) => { if (!a || !b) return null;
    const ox = Math.min(a[0]+a[2], b[0]+b[2]) - Math.max(a[0], b[0]);
    const oy = Math.min(a[1]+a[3], b[1]+b[3]) - Math.max(a[1], b[1]);
    return (ox > 0 && oy > 0) ? +(ox*oy).toFixed(1) : 0; };
  const say = R('.dash-say'), fig = R('.dash-mascot'), copy = R('.dash-copy');
  return { say, fig, copy, panel: R('.dash-visual'),
           sayFig: inter(say, fig), sayCopy: inter(say, copy),
           root: getComputedStyle(document.documentElement).fontSize };
})())"""


async def main():
    SHOTS.mkdir(parents=True, exist_ok=True)
    async with Session(CDP) as S:
        await S.goto("/index.html", 4.0)
        out = {}
        for name, css in VARIANTS:
            await S.js("document.querySelector('.dash-say').style.cssText = %s"
                       % json.dumps(css))
            await asyncio.sleep(0.35)
            d = await S.js(RECTS)
            out[name] = d
            r = await S.cmd("Page.captureScreenshot", {"format": "png"})
            (SHOTS / ("say_%s.png" % name)).write_bytes(base64.b64decode(r["data"]))
        # 再截一张整屏（最后一档的样式留在页上，顺便看清整体）
        print("视口 root font-size = %s" % out[VARIANTS[0][0]]["root"])
        for name, _ in VARIANTS:
            d = out[name]
            print("\n── %s ──" % name)
            for k in ("panel", "copy", "fig", "say"):
                v = d.get(k)
                print("   %-6s %s" % (k, "——" if v is None
                                      else "x %7.1f  y %7.1f  宽 %6.1f 高 %6.1f" % tuple(v)))
            print("   气泡 x 小瑞图 相交 %.1f px²   气泡 x 文字块 相交 %.1f px²"
                  % (d["sayFig"] or -1, d["sayCopy"] or -1))
        print("\n截图：_scratch/_shots/say_<档名>.png")
    return 0


sys.exit(asyncio.run(main()))
