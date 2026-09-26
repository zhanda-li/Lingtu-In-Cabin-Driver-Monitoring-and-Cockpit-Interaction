# -*- coding: utf-8 -*-
"""查 `_check_mascot.py` K 段那条失败：`react('speak')` 演完没还回档位表情。

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch\\_probe_speak.py 8790

K 段的判据是"事件类动作演完要还回 slot.state（档位表情）"，实际拿到的是
`xiaorui_happy.png / xqHappy` —— 也就是它**又演了一次 happy**，而不是没还回去。
所以问题不是"还回逻辑坏了"，而是"**谁在窗口里又调了一次 react('speak')**"。

这个脚本把 `XQ.mascot.react` 包一层，记下每次调用的**时刻 + 事件名 + 调用栈**，
再把 K 段那段时序原样放一遍。这样能直接看到是 TTS 的 onstart 晚到、
还是别的地方在放。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _check_pages import Session          # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PORT = sys.argv[1] if len(sys.argv) > 1 else "8790"
CDP = 9433

TRACE = r"""
(function(){
  window.__t0 = Date.now();
  window.__log = [];
  if (window.__wrapped) return 'already';
  window.__wrapped = 1;
  const orig = XQ.mascot.react;
  XQ.mascot.react = function(ev){
    let st = '';
    try { st = (new Error().stack || '').split('\n').slice(2, 4).join(' | '); } catch(e){}
    window.__log.push({ t: Date.now() - window.__t0, ev: ev, st: st.slice(0, 260) });
    return orig.apply(this, arguments);
  };
  return 'wrapped';
})()
"""

# 把 react 的真身留一份，K 段要用它还原"事件源"（见 _check_mascot.py:387）
STASH = r"""
(function(){
  if (!window.__xqReact) window.__xqReact = XQ.mascot.react;
  return typeof window.__xqReact;
})()
"""

IMG = r"""
JSON.stringify((() => {
  const i = document.getElementById('tipImg');
  return { src: (i.getAttribute('src')||'').replace(/^.*\//, ''),
           act: i.dataset.act || null,
           clk: (i.className.match(/xq\w+/) || [null])[0] };
})())
"""


async def main():
    async with Session(CDP) as S:
        await S.goto("/chat.html", 3.2)
        print("  包 react:", await S.js(TRACE))
        print("  留住真身:", await S.js(STASH))
        # 把包裹后的 react 换回来，K 段才能自己掌控事件源
        await S.js("XQ.mascot.react = window.__xqReact; window.__t0 = Date.now();")

        print("\n  --- 复刻 K 段时序（相对时刻）---")
        await S.js("XQ.mascot.play('happy', {hold: 800})")
        print("  T+0.00  play('happy', hold=800)")
        r = await S.js("String(XQ.mascot.react('sev:mild'))")
        print("  T+0.00  react('sev:mild') ->", r)
        await asyncio.sleep(1.3)
        print("  T+1.30 ", await S.js(IMG))
        await S.js("XQ.mascot.react('speak')")
        print("  T+1.30  react('speak')")
        await asyncio.sleep(0.3)
        print("  T+1.60 ", await S.js(IMG))
        for k in range(6):
            await asyncio.sleep(0.5)
            print("  T+%.2f " % (1.6 + 0.5 * (k + 1)), await S.js(IMG))

        print("\n  --- react 调用账本 ---")
        for row in await S.js("JSON.stringify(window.__log)"):
            print("    +%-6s %-14s %s" % (row["t"], row["ev"], row["st"]))


if __name__ == "__main__":
    asyncio.run(main())
