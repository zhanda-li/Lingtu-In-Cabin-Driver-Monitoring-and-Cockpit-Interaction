# -*- coding: utf-8 -*-
"""**哪一颗"能点的东西"其实点不动** —— 逐页量，不猜。

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch\\_check_clickable.py
    自己起服务（8805）和自己的 Edge（9467），**不碰用户那台 8765**。

★ 为什么要写这一支（用户 2026-09-25 报的）：
    原话先是一句「全屏后为啥我的展示页面那些都不能点了」，隔一会儿又补
    「我说的是跳转到展示页后 全屏点那些按键好像没用了」。
  「点不动」这个症状有一大类根因是**看不见的**：元素自己好好的、`display` 是
  `flex`、宽高都有、`cursor:pointer` 也在 —— 只是**它上面压着另一层东西**。
  人眼看得见那颗按钮，浏览器却把点击交给了上面那一层。这种问题在截图上看不出来
  （截图只有一层），翻代码也看不出来（CSS 里看不出"谁压谁"），
  **只有 `elementFromPoint` 说了算** —— 它就是浏览器拿来判定点击目标的那一次命中测试。

  🔴 已经抓到一例：cover.html 上新加的「观看品牌片」按钮，中心点
     (1274,733) 的 `elementFromPoint` 回的是 `IMG#coverMascotImg.mascot-img`
     —— 小瑞那张立绘把按钮盖住了。它的**父节点** `.mascot` 上挂着
     「点一下换个形象」的点击处理（`cover.html` 里 `XQ.poseDeck` 那段，
     注释写了"挂父节点面积更大也更好点"），而 `.cover-r .mascot` 是一个
     **44rem x 46rem** 的框 —— 这个框伸到页脚那一带去了。
     ⚠️ 这一例**不是 harness 的错**：`elementFromPoint` 与现实浏览器同一条判定路径，
       所以真人拿鼠标点那儿也是一样的结果。（这一支脚本的头一次跑还顺带证明了
       另一件事：CDP 真鼠标点击**必须先发 `mouseMoved`**，否则点击根本送不到——
       两个毛病长得一模一样，见 `_check_intro.py` 里 `real_click` 那段。）

★ 怎么算"点不动"：
    对每个"能点的"元素取**中心点**，`document.elementFromPoint(x,y)`，
    命中的不是它自己、不是它的子孙、也不是它的祖先 —— 就算被挡住了。
    ⚠️ 只看中心点，不看整块面积：中心点是"人最自然的落点"，也是最小可证伪的判据。
      边缘被挡住一点不算问题（圆角、阴影、装饰），**中心点被挡住才算**。
    ⚠️ "能点的"不能只认 `a`/`button`：这座舱里大量卡片是 `addEventListener`
      挂的、连 `onclick` 属性都没有（`_probe_mini_spot.py` 的注释里已经记过这条），
      所以 `cursor:pointer` 也是一条判据。

★ 两轮（第二轮才装左下角那条悬浮播放条）：
    第一轮 —— 页面本来的样子。
    第二轮 —— 先用 `sessionStorage` 塞一条存档把播放条**拉出来**（那条条只在
              "存着东西"的页面上才画），再看一遍。
              ⚠️ 塞的是一首不存在的歌（`__probe__.mp3`，会 404），所以这一轮
                 **不判"控制台零报错"** —— 那条 404 是我自己造的。这一支要的是
                 几何，不是播放。

⚠️ 本脚本**证明不了**的：座舱那几页的卡片是不是"点了有反应"（只证明"点击送得到"）。
   功能对不对要看各自的检查脚本。
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
PORT = "8805"
CDP = 9467
BASE = "http://127.0.0.1:%s" % PORT

_TMP = os.path.join(_HERE, "_tmp")
os.makedirs(_TMP, exist_ok=True)
os.environ["TMP"] = os.environ["TEMP"] = _TMP

sys.argv = [sys.argv[0], PORT]
import _check_pages as CP                          # noqa: E402

CP.PORT = PORT
CP.BASE = BASE
ck = CP.ck

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PAGES = ["cover.html", "index.html", "detail.html", "monitor.html", "media.html",
         "settings.html", "chat.html", "phone.html", "link.html", "flow.html",
         "voice.html", "about.html"]

# 把左下角那条悬浮播放条**从存档里拉出来**（它只在"存着东西"的页面上才画）。
PLANT = ("sessionStorage.setItem('xq.media.play', JSON.stringify("
         "{file:'__probe__.mp3', title:'__probe__', pos:0, playing:false,"
         " t:Date.now()}));'planted'")
CLEAR = "sessionStorage.removeItem('xq.media.play');'cleared'"

# 逐页跑的那一段。
SCAN = r"""(function(){
  function name(e){
    if (!e) return null;
    return e.tagName.toLowerCase()
      + (e.id ? '#' + e.id : '')
      + (e.className && typeof e.className === 'string'
          ? '.' + e.className.split(' ').filter(Boolean).slice(0, 2).join('.') : '');
  }
  function rect(e){
    const r = e.getBoundingClientRect();
    return {t: Math.round(r.top), l: Math.round(r.left),
            w: Math.round(r.width), h: Math.round(r.height)};
  }
  function usable(e){
    const cs = getComputedStyle(e);
    if (cs.display === 'none' || cs.visibility === 'hidden') return false;
    if (cs.pointerEvents === 'none') return false;
    const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }
  /* 元素**不透明**吗（0 也算透明）。半透明的控件照样能点，所以只有连算都算不出来的
     才排除 —— 这一条纯粹是防"整块空白盖在上面"那种。 */
  function opaque(e){
    const cs = getComputedStyle(e);
    const a = parseFloat(cs.opacity);
    return !(a === 0) && cs.visibility !== 'hidden';
  }
  const SEL = 'a,button,input,select,textarea,label,[onclick],[role="button"]';
  const seen = new Set();
  const targets = [];
  document.querySelectorAll(SEL).forEach(function(e){ targets.push(e); });
  /* cursor:pointer 也算（见文件头） */
  document.querySelectorAll('*').forEach(function(e){
    if (getComputedStyle(e).cursor === 'pointer') targets.push(e);
  });
  const bad = [];
  targets.forEach(function(e){
    if (seen.has(e)) return;
    seen.add(e);
    if (!usable(e)) return;
    const r = e.getBoundingClientRect();
    const x = Math.round(r.left + r.width / 2), y = Math.round(r.top + r.height / 2);
    if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) return;   // 视口外不算
    const hit = document.elementFromPoint(x, y);
    if (!hit) return;
    if (hit === e || e.contains(hit) || hit.contains(e)) return;
    if (!opaque(hit)) return;
    bad.push({what: name(e), at: [x, y], by: name(hit),
              tgt: rect(e), blk: rect(hit)});
  });
  return JSON.stringify({vw: innerWidth, vh: innerHeight, bad: bad});
})()"""

# 封面那一带单量一遍"谁压着谁"（`.mascot` 那个 44rem x 46rem 的框是主角）。
GEO = r"""(function(){
  const ids = ['coverMascot', 'coverMascotImg', 'coverMascotSvg',
               'introOpen', 'goBtn'];
  const out = {};
  ids.forEach(function(id){
    const e = document.getElementById(id);
    if (!e) { out[id] = null; return; }
    const r = e.getBoundingClientRect();
    const cs = getComputedStyle(e);
    out[id] = {
      t: Math.round(r.top), l: Math.round(r.left),
      w: Math.round(r.width), h: Math.round(r.height),
      pos: cs.position, z: cs.zIndex, pe: cs.pointerEvents, disp: cs.display,
    };
  });
  const foot = document.querySelector('.cover-foot');
  if (foot) {
    const r = foot.getBoundingClientRect();
    out['.cover-foot'] = {t: Math.round(r.top), l: Math.round(r.left),
                          w: Math.round(r.width), h: Math.round(r.height),
                          pos: getComputedStyle(foot).position,
                          z: getComputedStyle(foot).zIndex,
                          pe: getComputedStyle(foot).pointerEvents,
                          disp: getComputedStyle(foot).display};
  }
  return JSON.stringify({vw: innerWidth, vh: innerHeight, geo: out});
})()"""


def show(title, d):
    print("  %s  （视口 %sx%s）" % (title, d["vw"], d["vh"]))
    if not d["bad"]:
        print("      OK 没有一颗「能点的」中心点被别人盖住")
        return 0
    for b in d["bad"]:
        print("      !! %-34s 中心 %s 被 %s 盖住  它=%s 上面那个=%s"
              % (b["what"], b["at"], b["by"], b["tgt"], b["blk"]))
    return len(d["bad"])


async def main():
    log = open(os.path.join(ROOT, "runs", "_check_clickable_srv.log"), "w",
               encoding="utf-8")
    srv = subprocess.Popen([PY, "-u", "ui/server.py", "--port", PORT,
                            "--source", "demo"],
                           cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    worst = 0
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
            total_a = []
            total_b = []
            for rnd, (label, plant) in enumerate((("A. 页面本来的样子", CLEAR),
                                                  ("B. 拉出左下角那条播放条之后", PLANT))):
                print("\n=== %s ===" % label)
                for p in PAGES:
                    await S.goto("/" + p, 1.5)
                    await S.js(plant)
                    S.reqs = []
                    await S.goto("/" + p, 1.6)      # 再进一次，让存档在这一页生效
                    d = await S.js(SCAN)
                    if not d or "bad" not in d:
                        print("  !! %-14s 量不到（%s）" % (p, str(d)[:120]))
                        continue
                    n = show(p, d)
                    if n:
                        (total_a if rnd == 0 else total_b).append((p, n))
                if rnd == 1:
                    await S.js(CLEAR)

            print("\n=== 封面：谁压着谁（几何 + 层叠）===")
            await S.goto("/", 1.8)
            g = await S.js(GEO)
            print("  视口 %sx%s" % (g["vw"], g["vh"]))
            for k, v in (g["geo"] or {}).items():
                if v is None:
                    print("  %-16s 不在" % k)
                else:
                    print("  %-16s t=%-5s l=%-5s %sx%s  pos=%s z=%s "
                          "pointer-events=%s display=%s"
                          % (k, v["t"], v["l"], v["w"], v["h"], v["pos"],
                             v["z"], v.get("pe", "?"), v.get("disp", "?")))

            print("\n=== 判读 ===")
            worst |= ck("A ★★ 页面本来的样子：没有「点不动」的元素",
                        not total_a,
                        "挡住的页/条数：%s" % (total_a or "无"))
            # ⚠️ B 这一轮**故意**可能不干净：那条悬浮条是 `position:fixed z-index:40`，
            #    它本来就压在页面内容上（用户报的正是"挡住别的字"）。所以这里不是
            #    判"零遮挡"，而是把**它挡了谁**如实列出来 —— 真正的判据是
            #    "它已经能拖走了"（`_check_minibar.py`）。
            print("  B 这一轮（播放条已画出）挡住的：%s"
                  % (total_b or "无 —— 一条都没挡"))
            await S.js(CLEAR)
    finally:
        try:
            srv.terminate()
            time.sleep(0.8)
            if srv.poll() is None:
                srv.kill()
        finally:
            log.close()

    print("\nEXIT = %d  （0 = 全过）" % worst)
    return worst


if __name__ == "__main__":
    sys.exit(1 if asyncio.run(main()) else 0)
