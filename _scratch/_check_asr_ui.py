"""语音输入 · 浏览器侧验收（headless Edge + CDP）。

    python _scratch/_check_asr_ui.py 8790     # 端口要和起着的那份服务一致

判据：
  A **没有麦克风时不假装** —— 点了麦克风必须说实话：`state='failed'`、按钮**不置灰**、
    toast 里是"为什么听不见 + 怎么装"，而且**绝不能**出现「听到：…」那种假成功。
  B ★ 探测到浏览器那条路不行，就**干脆利落地退**。两条子判据分工明确：
      · 桩发 `onerror{audio-capture}`（headless 的真实情况）→ 必须**立刻**退，
        不许等满 first_ms 那个窗口（等到就是在白等，用户多等一秒）；
      · 桩**什么事件都不发**（kiosk 里 API 在、永远没反应）→ 必须**正好等到窗口**再退。
      两条一起才说明"是那个探测窗口在起作用"，单独一条都可能是别的原因造成的。
  C ★ 双路 XOR —— 两条路都用桩手工 `_deliver`，断言**恰好交付一次**（过期的 token
    也要被丢掉）。判据取 `XQ.flash` 被调的次数：交付成功才会 flash「听到：…」，
    第二次在 `_done === tok` 那一条就 return 了、根本走不到 flash。
  D 旧文案必须消失（「本项目没有 ASR」「点了发一句示例」「按住说话」）——
    这一条就是"说没做就得真没做"那条硬规矩的自动执行者，和 `_check_tts.py` 里
    `saysNoTTS` 同构。

⚠️ 这个脚本**证明不了**的两件事，别拿它冒充：
  1. 识别准不准 —— headless 里没有麦克风，`getUserMedia` 那条真路**一次都没走过**，
     这里走通的只有"失败"那一支。真对着麦克风说才算数。
  2. `cam` 模式下（推理把 CPU 占满）识别还能不能按时出结果。答辩现场大概率就是
     cam 模式，而这个脚本跑的是 demo。

★ 2026-09-25：A / B / C 三段原来是打在 `/index.html` 上的，**已改指
  `/detail.html`** —— 对话栏第五次改版把麦克风按钮、`#sayInput`、`#bubbles`
  整块搬去驾驶监测页了，首页上这三样一个都没有。改之前的表现**不是报红而是崩**
  （`document.getElementById('mic')` 是 null，`.click()` 当场 TypeError，
  异步函数 reject，`js_await` 回来的东西里没有 `toast` 这个键，
  第 176 行 `r["toast"]` 抛 KeyError）——「脚本崩了」和「页面坏了」长得不一样，
  但都很容易被当成后者去查。`chat.html` / `settings.html` 那两段（D 段后半）
  本来就在对的页上，没动。

⚠️ 它 `from _check_pages import Session`，而那个文件是**在 import 时**用 `sys.argv[1]`
   算 BASE 的 —— 所以传进来的那个端口必须就是服务的端口，否则所有 goto 都会打到
   另一个端口上（表现是页面一直空白、断言全红，看起来像代码坏了）。
"""

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _check_pages import Session, ck          # noqa: E402

# ⚠️ 必须用 `addScriptToEvaluateOnNewDocument` 装，**不能**等页面加载完再 `Runtime.evaluate`
# —— `XQ.asr.SR` 虽然是在"用的时候"才读 window（live.js:710 那个 getter 就是为这个
# 留的口子），但页面脚本一跑完 `XQ.asr.bind()` 就把按钮的 onclick 接上了，
# 而那之前 hello 已经来过一轮。在文档开始前装，才是"浏览器从来就只有这个桩"。
# 模式走 URL 参数：document-start 的脚本能读到 location.search。
STUB_SR = """
(function () {
  var mode = new URLSearchParams(location.search).get('srcmode') || 'audiocapture';
  function SR() { this.__m = mode; }
  SR.prototype.start = function () {
    var self = this;
    if (self.__m === 'audiocapture') {
      setTimeout(function () { if (self.onerror) self.onerror({ error: 'audio-capture' }); }, 30);
    }
    /* 'silent'：**一个事件都不发** —— 模拟 kiosk 里 API 在、但永远没反应 */
  };
  SR.prototype.stop = function () {};
  SR.prototype.abort = function () {};
  window.SpeechRecognition = SR;
  window.webkitSpeechRecognition = SR;
  window.__XQ_SR_STUB = 1;
})();
"""

# 点一下麦克风，然后在页面里等它落定，把"花了多久 + 最后落在哪"一起带回来。
# ⚠️ 用页面自己的 `performance.now()` 测，不用 python 的 sleep：要判的正是
# "它到底是立刻退的，还是等满了 first_ms 那个窗口" —— 那个窗口是页面里的定时器，
# 拿外面的墙上时间去猜会把它埋掉。
CLICK_AND_SETTLE = """
(async () => {
  const t0 = performance.now();
  XQ.flash('');
  document.getElementById('mic').click();
  while (performance.now() - t0 < 2500 && XQ.asr.state !== 'failed') {
    await new Promise(r => setTimeout(r, 20));
  }
  const b = document.getElementById('mic');
  return JSON.stringify({
    ms: Math.round(performance.now() - t0),
    state: XQ.asr.state,
    on: XQ.asr.on,
    dead: XQ.asr.browserDead,
    disabled: !!b.disabled,
    toast: document.getElementById('toast').textContent || '',
    lastText: XQ.asr.lastText,
  });
})()
"""

# ① 两条路都用桩手工交付，看 flash 被调了几次。
# `XQ.asr._seq += 1` 这里是在**模拟一次点击**（真实点击走的也是那一处自增，
# 而且那是全文件唯一一处）—— 除此之外没有任何地方动它。
XOR_JS = """
(function () {
  const seen = [];
  const old = XQ.flash;
  XQ.flash = (t) => { seen.push(String(t)); };
  const out = {};
  try {
    XQ.asr.on = true;
    XQ.asr.state = 'listening';
    XQ.asr._done = 0;
    XQ.asr._seq += 1;
    const tok = XQ.asr._seq;
    out.a = XQ.asr._deliver(tok, '我有点困', '浏览器');
    out.b = XQ.asr._deliver(tok, '我有点困', '本机');
    out.c = XQ.asr._deliver(tok - 1, '上一句迟到的', '迟到');
    out.lastText = XQ.asr.lastText;
  } finally { XQ.flash = old; }
  return JSON.stringify({ out: out, flashes: seen });
})()
"""

# ③ 端到端：`_deliver` → app.js 自己的 submit → WS → 服务端广播 → 气泡。
# 上面那几条都停在页面内部，这一条才碰真实链路。
#
# ⚠️ 两个坑，第一版都踩了：
#   1. **文本必须和 XOR 那段不一样**。两段都用「我有点困」的话，XOR 里那次
#      `_deliver` 也会把同一句话发出去、也会长出气泡 —— 于是这条断言在
#      "端到端根本没通"的时候**照样能绿**（气泡是上一段留下的）。这里改成
#      「端到端探针」，全脚本只有这一处会产生它。
#   2. **不能只 sleep 一个固定秒数**。中间隔着服务端那一跳（模型后端
#      12 秒超时 + 失败降级到固定话术），1.6 秒在彩排里就真的不够，而且
#      回不回得来跟这一跳的快慢有关 —— 固定 sleep 的写法是这个项目里
#      反复踩过的"看起来在测延迟、其实在测运气"。
E2E_JS = """
(async () => {
  XQ.asr._seq += 1;
  XQ.asr._done = 0;
  XQ.asr._deliver(XQ.asr._seq, '端到端探针', '测试');
  const t0 = performance.now();
  const grab = () => [...document.querySelectorAll('#bubbles .b.me p')].map(p => p.textContent);
  while (performance.now() - t0 < 8000) {
    if (grab().some(t => (t || '').indexOf('端到端探针') >= 0)) {
      return JSON.stringify({ok: true, ms: Math.round(performance.now() - t0)});
    }
    await new Promise(r => setTimeout(r, 100));
  }
  return JSON.stringify({ok: false, me: grab(), online: !!(window.link && link.online)});
})()
"""

# ② 旧文案必须消失。查 outerHTML 而不是 innerText —— 那几句话还可能躺在
# `title=` 之类的属性里，innerText 看不见它们。
OLD_COPY_JS = """
JSON.stringify({
  bad: ['本项目没有 ASR', '点了发一句示例', '按住说话']
        .filter(s => document.documentElement.outerHTML.indexOf(s) >= 0),
  micTitle: (document.getElementById('mic') || {}).title || '',
  hasMic: !!document.getElementById('mic')
})
"""


async def js_await(S, expr, timeout=8.0):
    """本脚本专用：会等 promise 的 evaluate。`Session.js()` 不带 awaitPromise，
    而上面两段都要在页面里等一会儿。"""
    r = await asyncio.wait_for(S.cmd("Runtime.evaluate", {
        "expression": expr, "returnByValue": True, "awaitPromise": True}), timeout)
    res = r.get("result", {})
    v = res.get("value")
    # 和 Session.js 同一条规矩：以 [ / { 开头的字符串当 JSON 解，其余原样。
    return json.loads(v) if isinstance(v, str) and v.startswith(("{", "[")) else v


async def main():
    worst = 0
    async with Session(9412) as S:
        await S.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": STUB_SR})

        # ---------------------------------------------------------------- A
        print("\n=== A. 没有麦克风时不假装（桩：onerror audio-capture）===")
        await S.goto("/detail.html?srcmode=audiocapture", 2.6)
        worst |= ck("桩装上了（页面上只有这个假 SR）",
                    (await S.js("window.__XQ_SR_STUB === 1")) is True, "")
        r = await js_await(S, CLICK_AND_SETTLE)
        honest = bool(r["toast"]) and any(
            k in r["toast"] for k in ("install_asr", "麦克风", "麦克"))
        fake = ("听到" in r["toast"]) or ("谢谢" in r["toast"])
        worst |= ck("★ 没有麦克风时说实话（不是假成功）",
                    r["state"] == "failed" and honest and not fake,
                    f"state={r['state']} toast={r['toast'][:60]!r}")
        worst |= ck("按钮没被置灰（置灰了人就不知道为什么）",
                    r["disabled"] is False, f"disabled={r['disabled']}")
        worst |= ck("★ onerror 那条路立刻退，不等满探测窗口",
                    r["ms"] < 700, f"{r['ms']} ms（窗口是 900 ms）")
        worst |= ck("浏览器那条路被记成『试过，不行』", r["dead"] is True,
                    f"browserDead={r['dead']}")
        worst |= ck("失败时没有编出一段文本", r["lastText"] == "",
                    f"lastText={r['lastText']!r}")

        # ---------------------------------------------------------------- B
        print("\n=== B. 永远没反应的那条路：要等满窗口才退 ===")
        await S.goto("/detail.html?srcmode=silent", 2.6)
        r2 = await js_await(S, CLICK_AND_SETTLE)
        worst |= ck("★ 什么都不发时，正好等满探测窗口才退",
                    850 <= r2["ms"] < 2200, f"{r2['ms']} ms（窗口是 900 ms）")
        worst |= ck("退下来之后同样是说实话的失败",
                    r2["state"] == "failed" and "听到" not in r2["toast"],
                    f"state={r2['state']} toast={r2['toast'][:60]!r}")
        worst |= ck("它没有一直卡在 listening",
                    r2["on"] is False, f"on={r2['on']}")

        # ---------------------------------------------------------------- C
        print("\n=== C. 双路 XOR：恰好交付一次 ===")
        await S.goto("/detail.html", 2.6)

        # 先端到端（用只有这里会产生的文本），再做 XOR —— 反过来做的话，
        # XOR 那次交付会先把气泡打出来，把端到端这条弄成"永远绿"。
        e2e = await js_await(S, E2E_JS, timeout=12.0)
        worst |= ck("★ 端到端：页面自己的 submit 真的把它发出去了（气泡出现）",
                    e2e.get("ok") is True,
                    f"{e2e.get('ms')} ms" if e2e.get("ok")
                    else f"8 秒里没等到，我的气泡={e2e.get('me')} online={e2e.get('online')}")

        xor = await js_await(S, XOR_JS)
        o, flash = xor["out"], xor["flashes"]
        worst |= ck("先到的交付成功", o["a"] is True, "")
        worst |= ck("★ 后到的被 `_done === tok` 挡掉", o["b"] is False, "")
        worst |= ck("★ 上一次点击的迟到结果被 token 挡掉", o["c"] is False, "")
        worst |= ck("★ 只 flash 了一次（用户只听到一次）", len(flash) == 1,
                    f"{flash}")
        worst |= ck("交付的是识别原文", o["lastText"] == "我有点困", o["lastText"])

        # ---------------------------------------------------------------- D
        print("\n=== D. 旧文案必须消失 ===")
        d = await S.js(OLD_COPY_JS)
        worst |= ck("★ 三句旧文案一句都不在（说没做就得真没做）",
                    d["bad"] == [], f"还在的：{d['bad']}")
        worst |= ck("麦克风按钮的说明是新的",
                    d["micTitle"] == "点一下开始说话，再点一下结束", d["micTitle"])

        await S.goto("/chat.html", 2.4)
        d2 = await S.js(OLD_COPY_JS)
        bound = await S.js("JSON.stringify({bound: XQ.asr._btn === "
                           "document.getElementById('mic'),"
                           " fn: typeof XQ.asr._submit})")
        worst |= ck("对话页的旧文案也没了", d2["bad"] == [], f"还在的：{d2['bad']}")
        worst |= ck("对话页的麦克风真的绑上了 XQ.asr（不是假按钮）",
                    bound["bound"] is True and bound["fn"] == "function", str(bound))

        await S.goto("/settings.html", 2.4)
        st = await S.js("JSON.stringify({note: document.getElementById('asrNote')"
                        ".textContent, txt: document.getElementById('asrTxt')"
                        ".textContent})")
        worst |= ck("设置页那一行真的渲染了（不是『—』）",
                    st["note"] != "—" and st["txt"] != "—", str(st)[:150])
        worst |= ck("设置页如实说本机识别能不能用",
                    ("可用" in st["note"]) or ("只有浏览器" in st["note"]),
                    st["note"])

        # ---------------------------------------------------------------- 报错
        print("\n=== 控制台 ===")
        if S.errs:
            worst |= ck("控制台零报错", False, f"{len(S.errs)} 条")
            for lvl, t in S.errs[:10]:
                print(f"      [{lvl}] {t}")
        else:
            worst |= ck("控制台零报错", True, "")

    print()
    print("全绿。" if not worst else f"有 {worst} 条没过。")
    return 1 if worst else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
