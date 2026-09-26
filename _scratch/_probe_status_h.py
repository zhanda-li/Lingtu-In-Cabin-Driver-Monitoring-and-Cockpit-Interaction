# -*- coding: utf-8 -*-
"""量一下总览页「驾驶员状态」卡的**高度账**：卡片多高、里面各块各占多少、溢出多少。

    D:\Anaconda3\envs\dms\python.exe _scratch/_probe_status_h.py 8790

为什么要量：`#statusFoot`（安全通道 / 演示锁定那一行）在重度档被卡底裁掉了。
它被裁掉**不只是少一行字** —— 钉档演示时「演示锁定 · 演示数据（非真人）」也写在
那里，看不见就等于把"锁定的稿"当成"实时判决"看。所以要精确知道差多少像素，
而不是靠看着截图猜「大概少一点」。
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _check_pages import Session          # noqa: E402

JS = r"""
(() => {
  const out = {};
  const box = (sel) => {
    const e = document.querySelector(sel);
    if (!e) return null;
    const r = e.getBoundingClientRect();
    const cs = getComputedStyle(e);
    return {h: +r.height.toFixed(1), top: +r.top.toFixed(1), bot: +r.bottom.toFixed(1),
            hidden: e.hidden, disp: cs.display,
            mt: cs.marginTop, pt: cs.paddingTop};
  };
  const card = document.querySelector('.main.dash .status');
  if (card) {
    const r = card.getBoundingClientRect();
    out.card = {h: +r.height.toFixed(1), top: +r.top.toFixed(1), bot: +r.bottom.toFixed(1),
                clientH: card.clientHeight, scrollH: card.scrollHeight,
                over: card.scrollHeight - card.clientHeight};
  }
  out.alarms = box('#alarms');
  out.hero   = box('.main.dash .status .hero');
  out.rows   = box('.main.dash .status .rows');
  out.ntiles = box('.main.dash .ntiles');
  out.nnote  = box('.main.dash .ntiles-note');
  out.foot   = box('#statusFoot');
  out.footTxt = (document.getElementById('statusFoot') || {}).textContent || '';
  out.rootFs = getComputedStyle(document.documentElement).fontSize;
  return out;
})()
"""


async def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8790
    vw, vh = 1672, 940
    if len(sys.argv) > 3 and "x" in sys.argv[3]:
        vw, vh = (int(x) for x in sys.argv[3].split("x"))
    # ⚠️ 调试端口自动挑一个空的。上一次 9481 上留了一个**杀不掉的僵尸 Edge**
    #    （`taskkill /F` 回「没有此操作的实例」，但 netstat 里它还在 LISTENING），
    #    固定端口就再也起不来了。挑空端口比去清那个僵尸便宜。
    cdp = 9481
    while cdp < 9521 and Session.port_busy(cdp):
        cdp += 1
    async with Session(cdp) as S:
        await S.cmd("Emulation.setDeviceMetricsOverride",
                    {"width": vw, "height": vh, "deviceScaleFactor": 2,
                     "mobile": False})
        await S.goto(sys.argv[2] if len(sys.argv) > 2 else "/index.html", 3.0)
        r = await S.js(JS)
        print("root font-size =", r["rootFs"])
        c = r["card"]
        print("卡片 .status : 高 %.1f  顶 %.1f  底 %.1f   clientH=%d scrollH=%d  溢出 %d px"
              % (c["h"], c["top"], c["bot"], c["clientH"], c["scrollH"], c["over"]))
        for k in ("alarms", "hero", "rows", "ntiles", "nnote", "foot"):
            v = r[k]
            if v is None:
                print("  %-7s (不在本页)" % k)
                continue
            print("  %-7s 高 %6.1f  顶 %6.1f  底 %6.1f  hidden=%s disp=%s mt=%s pt=%s"
                  % (k, v["h"], v["top"], v["bot"], v["hidden"], v["disp"], v["mt"], v["pt"]))
        if r["foot"]:
            print("  卡片底 vs 脚注底: %.1f -> %.1f  (=%+.1f)"
                  % (c["bot"], r["foot"]["bot"], r["foot"]["bot"] - c["bot"]))
        print("  脚注全文:", r["footTxt"][:160])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
