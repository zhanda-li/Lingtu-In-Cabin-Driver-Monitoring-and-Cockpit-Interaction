# -*- coding: utf-8 -*-
"""每张卡的**自然高度** —— 布局该不该撑、撑多少，先量再决定。

⚠️ 必须在**同一行内**比：`.three` 是 `align-items:start`，所以现在量到的就是
   各卡内容自己的高度。量完再把 `align-items` 改成 stretch，高度会变成行内最大值。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _check_pages as CP

PORT = sys.argv[1] if len(sys.argv) > 1 else "8765"
CDP = int(sys.argv[2]) if len(sys.argv) > 2 else 9506
CP.PORT = PORT
CP.BASE = "http://127.0.0.1:%s" % PORT

JS = """(function(){
  const out=[];
  for(const sec of document.querySelectorAll('.mon-sec')){
    const g=sec.querySelector('.three, .bottom3');
    if(!g) continue;
    const cs=getComputedStyle(g);
    out.push({sec:sec.id, grid:g.className, cols:cs.gridTemplateColumns,
              align:cs.alignItems, gap:cs.gap});
    const b=g.getBoundingClientRect();
    for(const card of g.children){
      const r=card.getBoundingClientRect();
      out.push({t:(card.querySelector('h3')||{}).textContent||'(无标题)',
                x:Math.round(r.x-b.x), w:Math.round(r.width), h:Math.round(r.height)});
    }
  }
  return JSON.stringify(out);
})()"""


async def main():
    async with CP.Session(CDP) as S:
        await S.goto("/monitor.html")
        await asyncio.sleep(2.6)
        rows = await S.js(JS)
        for r in rows:
            if "sec" in r:
                print("\n== %s   (.%s)  align=%s gap=%s"
                      % (r["sec"], r["grid"], r["align"], r["gap"]))
                print("   列宽 %s" % r["cols"])
            else:
                print("   h=%4d  w=%4d  x=%4d  %s"
                      % (r["h"], r["w"], r["x"], r["t"]))
        print("\nerrs:", S.errs[:6])


asyncio.run(main())
