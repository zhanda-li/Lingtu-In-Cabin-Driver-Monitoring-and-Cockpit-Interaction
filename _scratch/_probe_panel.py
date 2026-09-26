"""临时探针：量右侧 `.status` 卡的剩余高度（加板块之前先看还有没有地方）。

    python _scratch/_probe_panel.py 8797

`.status{ overflow:hidden }` —— 装不下就**直接裁掉**，不报错、不滚动，
底部那行运行日志会无声消失。所以动手加板块之前必须先知道余量。

用完即弃（几何断言最终收在 `_check_grade.py` 的 F 段里）。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _check_pages import Session                    # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CDP = 9461

PROBE = r"""
JSON.stringify((() => {
  const st = document.querySelector('.status');
  const box = (e) => +e.getBoundingClientRect().height.toFixed(1);
  const kids = [...st.children].map((e) => ({
    cls: e.className, id: e.id || '',
    h: box(e), hidden: e.hidden || false,
  }));
  const rows = [...document.querySelectorAll('.status .row')].map((e) => ({
    k: (e.querySelector('.k') || {}).textContent || '?', h: box(e),
  }));
  const p4r = [...document.querySelectorAll('.status .p4-row')].map((e) => ({
    t: (e.querySelector('span') || {}).textContent || '?', h: box(e),
    lines: Math.round(box(e) / parseFloat(getComputedStyle(e).lineHeight || 1)),
  }));
  const cs = getComputedStyle(st);
  const vals = (sel) => [...document.querySelectorAll(sel + ' .p4-row')]
    .map((r) => ((r.querySelector('span') || {}).textContent || '?') + ' '
                + ((r.querySelector('b') || {}).textContent || '?')
                + ' w=' + ((r.querySelector('i') || {style: {}}).style.width || '-'));
  return {
    vw: innerWidth, vh: innerHeight,
    fs: getComputedStyle(document.documentElement).fontSize,
    client: st.clientHeight, scroll: st.scrollHeight,
    pad: cs.paddingTop + '/' + cs.paddingBottom, gap: cs.rowGap,
    kids: kids, rows: rows, p4r: p4r,
    p4v: vals('#p4'), p5v: vals('#p5'),
    footText: (document.getElementById('statusFoot').textContent || '').slice(0, 40),
  };
})())
"""


async def main(port):
    async with Session(CDP) as S:
        for w, h in ((None, None), (1920, 1080), (1024, 768)):
            if w:
                await S.cmd("Emulation.setDeviceMetricsOverride",
                            {"width": w, "height": h, "deviceScaleFactor": 1,
                             "mobile": False})
            else:
                await S.cmd("Emulation.clearDeviceMetricsOverride")
            for key in ("normal", "severe"):
                await S.goto(f"/index.html?sev={key}", 3.0)
                d = await S.js(PROBE)      # S.js 自己 json.loads，给回来就是 dict
                print("=" * 70)
                print("?sev=%-7s 视口 %dx%d  root=%s  client=%d scroll=%d  **余量 %d px**"
                      % (key, d["vw"], d["vh"], d["fs"], d["client"], d["scroll"],
                         d["client"] - d["scroll"]))
                print("   padding %s  gap %s" % (d["pad"], d["gap"]))
                for k in d["kids"]:
                    print("   %-26s %7.1f  %s"
                          % ((k["id"] or k["cls"])[:26], k["h"],
                             "HIDDEN" if k["hidden"] else ""))
                print("   rows: " + " | ".join("%s %.0f" % (r["k"], r["h"])
                                               for r in d["rows"]))
                print("   p4:   " + " | ".join("%s %.0f" % (r["t"], r["h"])
                                               for r in d["p4r"]))
                for tag in ("p5v", "p4v"):
                    print("   %s: %s" % (tag, " | ".join(d[tag])))
                print("   foot: %s" % d["footText"])
        print("=" * 70)
        print("console errors: %s" % (S.errs[:3] or "none"))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 8797)))
