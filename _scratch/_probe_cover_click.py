# -*- coding: utf-8 -*-
"""两件小事，都用同一台测试 Edge 量（不动用户的 8765）：

  ① cover.html：**"观看品牌片"那颗键被小瑞的图盖住了**（`_check_clickable.py` 抓到）。
     这一支先量清楚谁压谁，然后**在页面里当场试一遍修法**再决定动不动文件 ——
     改 CSS 之前先证明那一句真的能把命中点抢回来。
  ② detail.html：有一颗 **真的 `button`**（121x68）中心点被 `div.ring` 盖住。
     这一支把它的 outerHTML 和"ring 在不在 deck host 里面"打出来，才能判断
     是"点了没反应"还是"点了换形象"。

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch\\_probe_cover_click.py
"""
import asyncio
import io
import json
import os
import subprocess
import sys
import time
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

PY = r"D:\Anaconda3\envs\dms\python.exe"
ROOT = os.path.dirname(_HERE)
PORT = "8806"
CDP = 9468
BASE = "http://127.0.0.1:%s" % PORT

_TMP = os.path.join(_HERE, "_tmp")
os.makedirs(_TMP, exist_ok=True)
os.environ["TMP"] = os.environ["TEMP"] = _TMP

sys.argv = [sys.argv[0], PORT]
import _check_pages as CP                          # noqa: E402

CP.PORT = PORT
CP.BASE = BASE
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# 谁在哪儿、谁压着谁；再对几个点做命中测试。
COVER = r"""(function(){
  function nm(e){
    if (!e) return null;
    return e.tagName.toLowerCase() + (e.id ? '#' + e.id : '')
      + (e.className && typeof e.className === 'string'
         ? '.' + e.className.split(' ').filter(Boolean).slice(0,2).join('.') : '');
  }
  function rc(e){
    if (!e) return null;
    const r = e.getBoundingClientRect();
    const cs = getComputedStyle(e);
    return {t:Math.round(r.top), l:Math.round(r.left),
            w:Math.round(r.width), h:Math.round(r.height),
            b:Math.round(r.bottom), r:Math.round(r.right),
            pos:cs.position, z:cs.zIndex, pe:cs.pointerEvents,
            ov:cs.overflow, tf:cs.transform.slice(0,24)};
  }
  const out = {vw:innerWidth, vh:innerHeight, els:{}, hits:{}};
  ['coverMascot','coverMascotImg','introOpen','goBtn'].forEach(function(id){
    out.els[id] = rc(document.getElementById(id));
  });
  out.els['.cover-foot'] = rc(document.querySelector('.cover-foot'));
  /* 封面正文那一列的左边界：按钮在页脚里，看它离小瑞多远 */
  out.els['.cover-r'] = rc(document.querySelector('.cover-r'));
  /* 命中测试：门口那颗键的中心 + 「进入座舱」的中心 + 它左边那一小截 */
  const probes = {'introOpen中心': document.getElementById('introOpen'),
                  'goBtn中心': document.getElementById('goBtn')};
  Object.keys(probes).forEach(function(k){
    const e = probes[k];
    if (!e) { out.hits[k] = null; return; }
    const r = e.getBoundingClientRect();
    out.hits[k] = nm(document.elementFromPoint(
      Math.round(r.left + r.width/2), Math.round(r.top + r.height/2)));
  });
  const go = document.getElementById('goBtn');
  if (go) {
    const r = go.getBoundingClientRect();
    /* 「进入座舱」左边缘往右 8px 那一点 —— 那一截按前面的量算是在小瑞的框里 */
    out.hits['goBtn左边缘+8'] = nm(document.elementFromPoint(
      Math.round(r.left + 8), Math.round(r.top + r.height/2)));
  }
  return JSON.stringify(out);
})()"""

# 当场试修：给两颗键加 position:relative + z-index，再看命中点回来了没有。
FIX_TRY = r"""(function(){
  const out = {};
  ['introOpen','goBtn'].forEach(function(id){
    const e = document.getElementById(id);
    if (!e) return;
    e.style.position = 'relative';
    e.style.zIndex = '3';
  });
  function nm(e){
    if (!e) return null;
    return e.tagName.toLowerCase() + (e.id ? '#' + e.id : '')
      + (e.className && typeof e.className === 'string'
         ? '.' + e.className.split(' ').filter(Boolean).slice(0,2).join('.') : '');
  }
  ['introOpen','goBtn'].forEach(function(id){
    const e = document.getElementById(id);
    if (!e) return;
    const r = e.getBoundingClientRect();
    out[id] = nm(document.elementFromPoint(
      Math.round(r.left + r.width/2), Math.round(r.top + r.height/2)));
  });
  const go = document.getElementById('goBtn');
  if (go) {
    const r = go.getBoundingClientRect();
    out['goBtn左边缘+8'] = nm(document.elementFromPoint(
      Math.round(r.left + 8), Math.round(r.top + r.height/2)));
  }
  return JSON.stringify(out);
})()"""

DETAIL = r"""(function(){
  function nm(e){
    if (!e) return null;
    return e.tagName.toLowerCase() + (e.id ? '#' + e.id : '')
      + (e.className && typeof e.className === 'string'
         ? '.' + e.className.split(' ').filter(Boolean).slice(0,2).join('.') : '');
  }
  /* 找那颗"中心被盖住"的真按钮 */
  const out = {found: []};
  document.querySelectorAll('button').forEach(function(b){
    const r = b.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return;
    const x = Math.round(r.left + r.width/2), y = Math.round(r.top + r.height/2);
    const hit = document.elementFromPoint(x, y);
    if (!hit || hit === b || b.contains(hit) || hit.contains(b)) return;
    /* 命中它的那一层，往上爬到顶，看有没有挂 deck 手点的宿主 */
    const chain = [];
    for (let n = hit, k = 0; n && k < 8; n = n.parentElement, k++) {
      const cs = getComputedStyle(n);
      chain.push(nm(n) + (cs.cursor === 'pointer' ? '[cursor:pointer]' : ''));
    }
    out.found.push({
      btn: nm(b), text: (b.textContent || '').trim().slice(0, 30),
      html: b.outerHTML.replace(/\s+/g, ' ').slice(0, 180),
      at: [x, y], by: nm(hit), chain: chain,
      /* 这个按钮自己是不是 deck 的宿主（是的话"点不动"不影响换形象） */
      selfCursor: getComputedStyle(b).cursor,
    });
  });
  return JSON.stringify(out);
})()"""


def dump(title, obj):
    print("\n=== %s ===" % title)
    print(json.dumps(obj, ensure_ascii=False, indent=1))


async def main():
    log = open(os.path.join(ROOT, "runs", "_probe_cover_click_srv.log"), "w",
               encoding="utf-8")
    srv = subprocess.Popen([PY, "-u", "ui/server.py", "--port", PORT,
                            "--source", "demo"],
                           cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    try:
        up = False
        for _ in range(40):
            try:
                with urllib.request.urlopen(BASE + "/music.json", timeout=3):
                    up = True
                    break
            except Exception:                             # noqa: BLE001
                time.sleep(0.5)
        if not up:
            print("!! 服务没起来")
            return 1
        async with CP.Session(CDP) as S:
            await S.goto("/", 1.8)
            a = await S.js(COVER)
            dump("封面：修之前", a)
            b = await S.js(FIX_TRY)
            dump("封面：当场给两颗键加 position:relative + z-index:3 之后", b)

            await S.goto("/detail.html", 1.8)
            d = await S.js(DETAIL)
            dump("detail.html：中心点被盖住的真 button", d)
            print("\n控制台报错：%s" % (S.errs[:3] or "无"))
    finally:
        try:
            srv.terminate()
            time.sleep(0.8)
            if srv.poll() is None:
                srv.kill()
        finally:
            log.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
