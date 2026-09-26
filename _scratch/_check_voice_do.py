# -*- coding: utf-8 -*-
"""「说了一件事 → **页面真的去做** → 按结果说那句话」——端到端验收。

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch\\_check_voice_do.py

用户报的是「你好小瑞给我放个音乐 它怎么不放」。根因不是麦克风也不是识别：
**整条语音链路只产文本**（`Reply.actions` 零消费者、`playCalm()` 只有三个 onclick）。
修法是新开一条**单播 + 等回执**的通道（`server.py` 的 `voice_do` / `handle()` 里的
`do_result` 分支 + `wake.js` 的 `ev === 'do'`）。这一份验的就是那条通道。

**没有浏览器**：这里**扮演页面那一侧** —— 收到 `ev:"do"` 就按剧本回一条
`{"type":"do_result", ...}`。所以它证明的是**协议和判据**，不是
"浏览器真的把歌放出来了"（后者在 `_scratch/_probe_music_click.py` 那类真浏览器
脚本里，两条合起来才算数）。

判据：
  A 命中的是 music 意图，而且**没走模型**（`heard` 里必须有「音乐」，
    `backend` 必须是 `scripted`；走模型那条是 `api`）。
  B 服务端**先发 `do`、再等回执、最后才组话**：`do` 必须排在 `reply` 前面，
    而且要带 `id`/`seq`。
  C 回执 `ok:true` → 念的是 `SCRIPT['music']` 里的话。
  D 回执 `ok:false, why:'blocked'` → 念的是 `ACT_FAIL['music']['blocked']`。
    （**这一条才是"不许说这就给您放"**：放不出来就得说实话。）
  E **迟到的回执不算数**：回一个**上一轮**的 `seq`，服务端必须丢掉它
    （日志里留一行），而且绝不能拿它去回答这一轮。
  F 答复照旧广播成 `say`（气泡要画、`silent` 要带），收尾回 idle。
  G **"问服务区"那两条拿不到数据的路**（点击按钮 / 打字走固定话术）不许把
    `{name}`/`{km}` 这种占位符念出来（2026-09-26 加，见下面那段注释）。
  H **"打开某一页 / 导航过去"真的命令页面去跳**（2026-09-26 加，用户原话
    「我让它导航我肯定真导航啊 直接跳转这些啊」）。真音频进 → 真识别 → 服务端
    **真发** `do`（`go:media` / `rest_stop`）→ 回执照实回 → 念的那句话出自
    `SCRIPT['go']` / `['rest_stop_here']`、`{page}` 已填、一个花括号都不剩；
    加上两张手抄表（`xiaorui.PAGES` ↔ `chrome.js` 的 `NAV`）的键/标签/目标文件
    三样对齐。**页面那一侧的 `location.href` 真跳没跳不在这里**（见 H 段注释）。
    ⚠️ H1（回执 `ok`，页面**真跳**）和 H2（回执 `here`，页面**留在原地**）的
    "念不念"是**相反**的：真跳的那一轮**不许**有 `ev:"reply"`（页面 180 ms 后就没了，
    念出来只有半句，那一句由新页面来要），留在原地的那一轮**必须**念出来。
    判据在服务端是**回执**（`ok` 且没有 `here`/`same`），**不是** intent。

★★ 2026-09-26 第二组：**用户报的「我让它导航咋不做」**。那一条和上面 A~H 不是
   同一件事 —— 上面量的是"发了命令页面做没做"，这一组量的是**那句话本身判不判得
   出动作**、以及**「要」这一声算不算数**（用户当时拍板的是「跳过去 + 问一句」）。
   ⚠️ **字母故意从 J 起**（J = jump）：A~H 已经被上面那 8 条占了，重号会让
      "J2 红了"这种话没法说清楚。

  J1 说「导航」→ 服务端**真发** `do id:rest_stop`，而且**这一轮不念话**（页面
     180 ms 后就跳走了，念出来只有半句；气泡照画，话出自 `SCRIPT['rest_stop']`）。
  J2 跳过去之后**活着的那一页**来要一句（`{"type":"ask","origin":…}`）→ 是一句
     **问句**、出自 `SCRIPT['ask_rest_stop']`、同时**挂上待确认** → 主人说「要的」
     （**不喊唤醒词**，就在追问窗口里）→ 服务端**再发一次** `do rest_stop` →
     这一页此刻就站在导航页上 → `here:true` → 话出自 `SCRIPT['rest_stop_here']`
     （**不是** `rest_stop` —— 那一句是"我这就把它调出来"，和屏幕不一致）。
  J3 没有待确认动作时说「要的」→ **一条 `do` 都不发**（「要」不是动作，是回答上一句）。
  J4 `ask` 带 `origin:null` → 说 `ACT_FAIL['nearby']['no_geo']` 里那一档的实话，
     而且**不挂**待确认（随后说「要的」同样不发 `do`）。
  J5 问完之后主人**换了话题** → 那件事当场作废（`take_pending` 取走即清），
     之后再喂「要的」也不发 `do`。
  F  **判据表**（纯静态，秒级）：`detect_action` / `is_affirm` 逐条算对 —— 第一行
     就是用户那句原话「给我导航」。**它不经过音频**，J1 才走音频；两句合起来
     才等于"那句话真的通了"（合成音认不出「给我导航」，见 `_make_wake_wavs.py`）。
  ⚠️ J1~J5 里的「要的」都是**真音频**（`runs/wake_samples/pos_affirm.wav`），
     而且**真的按生产节拍等**（10.5 s 静音收口）。所以这一段挂钟上很贵。
  ⚠️ 每一段喂「要的」之前都先问一次状态、断言它在 `follow`/`listen`：
     不在那一档的话 `take_pending` 会**因为状态不对**吐空串，于是"没有 do"这条
     绿是**假的**（判的是"麦克风没开"，不是"提议被顶掉了"）。

🔴 **第一遍跑，7 条里 5 条红，逮到一个真 bug（已经修了）**：`voice_pcm` 当时是
   **在读循环里直接 `await voice_events(...)`** 的，而 `voice_do` 要等页面的回执，
   页面的回执又只能由**同一个读循环**派发 —— 循环等待，1.5 s 必然超时。
   症状很难看：歌**真的放出来了**，小瑞却念「我没收到播放的回执，可能没放上」。
   修法是 `server.py` 的 `voice_enqueue` + `_voice_pump`（队列 + 一个常驻协程，
   保住串行、换掉"谁在等"）。**这一份就是它的看门狗**：C 段那三条一旦再红，
   先去看那儿。
   另外那 2 条红是**这份脚本自己的判据落后**，不是产品的：① whisper 真的会吐繁体
   （「給我放客音樂」），意图那一判据必须繁简归一后再看；② 服务端**故意**不在收到
   `voice_spoken` 时回 `idle`（那条只有看门狗收尾才发），所以"回 idle"要问
   `voice_status` 里的 `ear.state`，不能等事件。

⚠️ 服务是**本脚本自己起的**（不是让你先手动起一个）：这样 A 段那条日志才读得到，
   而且不会串到别的 `_check_*` 正在用的端口上。
⚠️ 音频按 **100 ms 一片、按真实时间节拍**喂（`await asyncio.sleep(0.1)`）：
   服务端有几处机制是**按挂钟**算的（`debounce_s`/`GUARD_S`），一次性灌进去
   它们全都还没过期，第一片之后的音频会被整片吞掉（`ui/voice/kws.py` 第 2 条纪律）。
⚠️ 两轮之间**必须真等** `GUARD_S`（0.4 s）：念完之后那段余音保护是挂钟计的，
   一到 idle 就立刻喂音频，唤醒词会正好落在保护窗口里 —— 表现是"第二次叫不醒"。
   `_check_voice_ws.py` 的 D 段记了同一个坑。
"""

import asyncio
import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(ROOT / "ui"))
sys.path.insert(0, str(ROOT / "ui" / "voice"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import asr                                               # noqa: E402
import xiaorui                                           # noqa: E402
from kws import SR                                       # noqa: E402

PY = r"D:\Anaconda3\envs\dms\python.exe"
PORT = "8809"
URL = "ws://127.0.0.1:%s/ws" % PORT
LOG = ROOT / "runs" / "_check_voice_do_srv.log"
SAMPLE = ROOT / "runs" / "wake_samples" / "pos_music.wav"
CHUNK = 1600                                             # 100 ms

OK_LINES = {ln for lines in xiaorui.SCRIPT["music"].values() for ln in lines}
FAIL_BLOCKED = xiaorui.ACT_FAIL["music"]["blocked"]
FAIL_TIMEOUT = xiaorui.ACT_FAIL["music"]["timeout"]
REST_LINES = {ln for lines in xiaorui.SCRIPT["rest_stop"].values() for ln in lines}
HERE_LINES = {ln for lines in xiaorui.SCRIPT["rest_stop_here"].values() for ln in lines}
NEARBY_LINES = {ln for lines in xiaorui.SCRIPT["nearby"].values() for ln in lines}
GO_LINES = {ln for lines in xiaorui.SCRIPT["go"].values() for ln in lines}
GO_SAME_LINES = {ln for lines in xiaorui.SCRIPT["go_same"].values() for ln in lines}
# ★★ 2026-09-26：跳过去之后**刚加载的那一页**来要的那句问话（A3），以及
#    "页面手上没有起点"时的那句实话（`ACT_FAIL['nearby']['no_geo']`，**分档**，
#    所以是一组句子不是一个）。两句都是 `ScriptedAgent.ask_reply` 挑的。
ASK_LINES = {ln for lines in xiaorui.SCRIPT["ask_rest_stop"].values() for ln in lines}
NO_GEO_LINES = set(xiaorui.ACT_FAIL["nearby"]["no_geo"].values())
# 「**模板**表」= 句子里带占位符、必须有人填满了才能念的那几张。
#   · `nearby`  —— `{name}/{km}/{tail}`，只有 `_nearby_reply` 填得满
#   · `go` / `go_same` —— `{page}`，只有 `_go_reply` 填得满
# G 段扫花括号时必须把它们排除掉，否则那一段会把"模板里有占位符"当成错误报红
# （2026-09-26 加 `go`/`go_same` 时差点踩到：这三张表**本来就该有**占位符）。
# ⚠️ 排除不是放行：H 段专门验这三张表**填完之后**一个花括号都不剩。
TEMPLATE_TABLES = ("nearby", "go", "go_same")
NO_DATA_TABLES = [k for k in xiaorui.SCRIPT if k not in TEMPLATE_TABLES]


def nav_entries():
    """`ui/web/chrome.js` 的 `const NAV = [...]` → [(键, 标签, 文件名)]。

    为什么要从**网页那边**抠：`wake.js` 跳页时拿的目标文件是 `XQ.NAV` 给的，
    而判"跳到哪一页"的是服务端 `xiaorui.PAGES` 的键。两边是**两份手抄的表**，
    抄错了的症状是——跳到不存在的文件 = 浏览器一张白页，看起来和"这页本来就没做"
    一模一样。所以要有一处把两边摆在一起比。
    """
    src = (ROOT / "ui" / "web" / "chrome.js").read_text(encoding="utf-8")
    i = src.index("const NAV = [")
    j = src.index("\n];", i)
    return [m.groups() for m in re.finditer(
        r"\[\s*'([A-Za-z_]+)'\s*,\s*'([^']*)'\s*,\s*'([^']+)'", src[i:j])]

FAILS = []


class _St:
    """最小的假状态，只给 `ScriptedAgent.reply()` 真正会碰的那两个字段：
    `_pick(intent, state.severity, …)` 读 `severity`，
    `emotion_for(state)` 读 `severity` **和** `state.level`。
    ⚠️ 我第一版只给了 `severity`（注释还写着"只读它"），当场被 `AttributeError`
       打回来 —— 假状态要么给全，要么别造；注释别替被测代码下结论。"""
    severity = "moderate"
    level = 2


def ck(name, ok, note=""):
    print("  %s %-40s %s" % ("OK  " if ok else "!!  ", name, note))
    if not ok:
        FAILS.append(name)
    return 0 if ok else 1


def short(v, n=50) -> str:
    """把**可能是 None** 的值安全地截短打印。

    ⚠️⚠️ 别写成 `(x or {}).get("text")[:50]` —— 那条判据**不成立**时这个值正好是
       `None`，切片当场抛 `TypeError`：红结果变成崩溃，整个脚本从那儿断掉，
       后面的段一条都不跑（实测就这么断过一次，见文件头那段"读输出行"）。
       一段检查脚本最不该有的性质就是"只有全绿才跑得完"。
    """
    return ("%r" % (v,))[:n]


def pcm(path) -> np.ndarray:
    return asr.wav_bytes_to_float32(path.read_bytes(), want_sr=SR)


def frames(x):
    for i in range(0, len(x), CHUNK):
        yield x[i:i + CHUNK]


async def send_audio(ws, x, silence_s=10.5):
    """按真实节拍喂一段音频，末尾补静音 —— 收口**只**靠静音判。

    ⚠️ 默认 10.5 s 是按生产值来的（2026-09-26 用户拍板：「语音结束的标志是我中途
       10s 没有发出声音」，见 `ui/voice/asr_stream.py`）。别为了跑得快改小：
       改小了就是「用测试的阈值迁就代码」，谁把 10 调回去这份脚本也照样全绿。
       这一段是**真按 0.1 s 一片实时喂**的，所以补多少静音就真的多花多少挂钟时间。
    """
    tail = np.zeros(int(silence_s * SR), np.float32)
    for ch in frames(np.concatenate([x, tail])):
        pcm16 = (np.clip(ch, -1, 1) * 32767).astype("<i2").tobytes()
        await ws.send_json({"type": "pcm", "seq": 1,
                            "b64": base64.b64encode(pcm16).decode("ascii")})
        await asyncio.sleep(0.1)


async def main():
    import aiohttp
    worst = 0
    evs = []                       # voice 事件（按顺序）
    says = []
    box = {}

    log = open(LOG, "w", encoding="utf-8")
    srv = subprocess.Popen([PY, "-u", "ui/server.py", "--port", PORT,
                            "--source", "demo"],
                           cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    try:
        for _ in range(60):
            try:
                with urllib.request.urlopen("http://127.0.0.1:%s/music.json"
                                            % PORT, timeout=3):
                    break
            except Exception:                            # noqa: BLE001
                time.sleep(0.5)
        if not SAMPLE.exists():
            raise RuntimeError("没有样本 %s —— 先跑 _scratch/_make_wake_wavs.py"
                               % SAMPLE)

        async with aiohttp.ClientSession() as sess:
            async with sess.ws_connect(URL, max_msg_size=0) as ws:

                async def pump():
                    try:
                        async for m in ws:
                            if m.type != aiohttp.WSMsgType.TEXT:
                                continue
                            d = json.loads(m.data)
                            if d.get("type") == "voice":
                                evs.append(d["data"])
                                print("      ← %s" % json.dumps(
                                    {k: v for k, v in d["data"].items()
                                     if k in ("ev", "word", "text", "why", "id",
                                              "seq", "backend")},
                                    ensure_ascii=False)[:160])
                            elif d.get("type") == "say":
                                says.append(d["data"])
                            elif d.get("type") == "hello":
                                box["hello"] = d["data"]
                    except Exception as e:               # noqa: BLE001
                        print("      !! 收消息的任务挂了：%s: %s（后面的判据都不可信了）"
                              % (type(e).__name__, e))

                async def wait_ev(kind, timeout=60.0):
                    t0 = asyncio.get_event_loop().time()
                    while asyncio.get_event_loop().time() - t0 < timeout:
                        hit = next((e for e in evs if e.get("ev") == kind), None)
                        if hit is not None:
                            return hit
                        await asyncio.sleep(0.2)
                    return None

                async def wait_say(pred, timeout=60.0):
                    """等一条**广播**（`type:"say"`，不是 `voice` 事件）。

                    ★★ 2026-09-26：跳页那一轮（`go:` / `rest_stop`）服务端只发 `say`
                       气泡、**不发 `ev:"reply"`**（`voice_say(jump=True)`，理由见那儿
                       的注释：页面 180 ms 后就没了，念出来只剩半句）。所以"按回执
                       挑的是哪句话"这件事，在那两轮里**只能从 `say` 上看**。
                    ⚠️ 原来这里等的是 `ev:"reply"` —— 那一版会把每一轮白等 30 s 超时，
                       而且判红的理由("text=''")看着像产品坏了，其实是判据过时。
                    """
                    t0 = asyncio.get_event_loop().time()
                    while asyncio.get_event_loop().time() - t0 < timeout:
                        hit = next((s for s in says if pred(s)), None)
                        if hit is not None:
                            return hit
                        await asyncio.sleep(0.2)
                    return None

                async def ear_now():
                    """现问一句 `voice_status`，回来的是 `ear` 那一份（`VoiceLoop.status`）。

                    ⚠️ 每次都要清掉旧的 `status` 再问：上一个答案是**上一轮**的，
                       拿它当数会把这一轮的判据接到上一轮的状态上去。
                    """
                    evs[:] = [e for e in evs if e.get("ev") != "status"]
                    await ws.send_json({"type": "voice_status"})
                    await asyncio.sleep(0.35)
                    return next(((e.get("ear") or {}) for e in evs
                                 if e.get("ev") == "status"), None)

                async def to_idle(timeout=12.0):
                    """念完之后，**服务端的状态机是不是真的收干净了**。

                    ⚠️⚠️ 判据是 `voice_status` 里的 `ear.state`，**不是**等服务端发一条
                       `ev:"idle"`。服务端**故意**不在收到 `voice_spoken` 时回 `idle`：
                       那条 `idle` 只有**看门狗自己收尾**时才发（见 `_voice_watchdog`），
                       而页面也不需要它 —— `wake.js` 在 `reply` 到达时就把 `busy` 清了、
                       `idle` 只用来 flash 一句 `why`。
                       第一版这里等的恰恰是事件，于是"念完了"这条回执照样把看门狗
                       取消了，它等的 `idle` **永远不会来** —— 自己把自己等死。
                       （`_check_voice_ws.py` 的 D 段用的就是 `voice_status` 这一条。）
                    ⚠️ 2026-09-26：念完之后进的是**追问窗口**（状态 `follow`，
                       见 `ui/voice/loop.py` 的 FOLLOW），不再是 `idle` —— 只认 `idle`
                       的话这里每一轮都要等窗口超时（8 s）才收工。
                    ★★ 2026-09-26 又加了一条：这条回执**必须带轮次号**，而且必须带
                       **对的那个**。服务端那两道卫兵（轮次 + 状态还停在 `speak`）
                       是跟着"掐断"一起加的：`speechSynthesis.cancel()` 也会触发
                       `onend`，一条上一轮的迟来回执会把刚打开的 LISTEN 推回追问窗口。
                       所以这里**先把轮次问出来再回执** —— 假页面要和真页面做同一件事
                       （`wake.js` 的 `XQ.wake.round` 也是从 `ev:"reply"` 里拿的），
                       自己编一个数就是在测一个真实浏览器不会走的分支。
                    """
                    ea = await ear_now() or {}
                    await ws.send_json({"type": "voice_spoken",
                                        "round": ea.get("round")})
                    st = "?"
                    t0 = asyncio.get_event_loop().time()
                    while asyncio.get_event_loop().time() - t0 < timeout:
                        # 每次现问一句，别拿旧的答案当数（上一个 status 是上一轮的）
                        ea = await ear_now() or {}
                        st = ea.get("state") or "?"
                        if st in ("idle", "follow"):     # 两档都算"收干净了"
                            return True, st
                    return False, st

                t = asyncio.create_task(pump())
                await asyncio.sleep(0.6)

                # -------------------------------------------------- 开麦
                print("\n=== 0 voice_start → ready ===")
                await ws.send_json({"type": "voice_start"})
                rdy = await wait_ev("ready", timeout=40)
                worst += ck("回了 ready", rdy is not None,
                            json.dumps((rdy or {}).get("voice", {}),
                                       ensure_ascii=False)[:110])

                # -------------------------------------------------- 第一轮：放成了
                print("\n=== A/B/C 第一轮：说「给我放个音乐」，回执照实说「放上了」 ===")
                evs.clear()
                says.clear()
                await send_audio(ws, pcm(SAMPLE))
                do = await wait_ev("do", timeout=60)
                heard = next((e.get("text") or "" for e in evs
                              if e.get("ev") == "heard"), "")
                order = [e.get("ev") for e in evs]
                print("      事件顺序：%s" % " → ".join(order))
                worst += ck("整句识别出来了", bool(heard), "heard=%r" % heard)
                # ⚠️ 少了「音乐」这两个字，`detect_intent` 就不会命中 music，
                #    下面每一条都会失败 —— 那种"红"是样本/识别的锅，不是产品的。
                #    所以这一条单独判，并且把 heard 原样打出来。
                # ⚠️⚠️ **必须是繁简归一之后再看**（`xiaorui.zh_t2s`）：whisper 这条
                #    路**真的会吐繁体** —— 第一版这里直接找「音乐」，而实测 heard 是
                #    「你好小瑞給我放客音樂」（给→給、乐→樂），于是判红；可同一刻
                #    服务端**已经发了 `do`**（意图命中了，靠的正是 `zh_t2s`）。
                #    也就是说：这条红是**判据比被测代码落后一步**，不是产品坏了。
                worst += ck("★ 识别到的就是 music 意图（繁简归一后含「音乐」）",
                            "音乐" in xiaorui.zh_t2s(heard), "heard=%r" % heard)
                worst += ck("★ 服务端发了 ev:'do'（让页面去做）", do is not None,
                            json.dumps(do, ensure_ascii=False)[:110] if do else "没等到")
                if do:
                    worst += ck("do 的 id 是 music", do.get("id") == "music",
                                "id=%r" % do.get("id"))
                    worst += ck("do 带了轮次号 seq", isinstance(do.get("seq"), int),
                                "seq=%r" % do.get("seq"))
                    # B：次序 —— do 必须在 reply 前面（先做、再按结果说）
                    rep0 = next((e for e in evs if e.get("ev") == "reply"), None)
                    idx = order.index("do")
                    worst += ck("★ do 排在 reply 前面（先做再组话）",
                                "reply" not in order[:idx],
                                "reply 现在%s" % ("已经在了（组话走在了前面）"
                                                  if rep0 else "还没来"))
                    # 回执：这里扮演页面那一侧
                    await ws.send_json({"type": "do_result", "id": "music",
                                        "seq": do.get("seq"), "ok": True,
                                        "why": "", "file": "CloudMusic/x.mp3",
                                        "title": "舒缓音乐"})
                rep = await wait_ev("reply", timeout=30)
                txt = (rep or {}).get("text") or ""
                worst += ck("有 reply", rep is not None, "%r" % txt[:60])
                worst += ck("★ 念的是 SCRIPT['music'] 里的话", txt in OK_LINES,
                            "text=%r" % txt)
                worst += ck("★ 没走模型（backend=scripted）",
                            (rep or {}).get("backend") == "scripted",
                            "backend=%r" % (rep or {}).get("backend"))
                worst += ck("reply 带上了原话（气泡要显示「我问了什么」）",
                            (rep or {}).get("user") == heard,
                            "user=%r" % (rep or {}).get("user"))
                vs = [s for s in says if s.get("voice") is True]
                worst += ck("答复也广播成 say 了（气泡要画）", bool(vs),
                            "%d 条 / 共 %d 条 say" % (len(vs), len(says)))
                if vs:
                    worst += ck("say 上带 silent+user（页面靠它不重复念）",
                                vs[-1].get("silent") is True and bool(vs[-1].get("user")),
                                "silent=%s user=%r" % (vs[-1].get("silent"),
                                                       vs[-1].get("user")))
                ok_i, st_i = await to_idle()
                worst += ck("念完收尾回了 idle（状态机，不是事件）", ok_i,
                            "state=%r" % st_i)
                await asyncio.sleep(0.6)          # GUARD_S，见文件头

                # -------------------------------------------------- 第二轮
                print("\n=== D/E 第二轮：回执说「放不出来」+ 一条迟到的回执 ===")
                evs.clear()
                says.clear()
                await send_audio(ws, pcm(SAMPLE))
                do2 = await wait_ev("do", timeout=60)
                worst += ck("第二次也叫醒了（还发了 do）", do2 is not None,
                            "seq=%r" % (do2 or {}).get("seq"))
                if do2:
                    n = len((open(LOG, encoding="utf-8", errors="replace")
                             .read()).splitlines())
                    # ① **迟到的**：报上一轮的 seq —— 必须被丢掉
                    await ws.send_json({"type": "do_result", "id": "music",
                                        "seq": (do2.get("seq") or 0) - 1,
                                        "ok": True, "why": ""})
                    # ② 这一轮真正的回执：失败
                    await ws.send_json({"type": "do_result", "id": "music",
                                        "seq": do2.get("seq"), "ok": False,
                                        "why": "blocked"})
                    rep2 = await wait_ev("reply", timeout=30)
                    txt2 = (rep2 or {}).get("text") or ""
                    worst += ck("★ 放不出来时念的是 ACT_FAIL 那句（不撒谎）",
                                txt2 == FAIL_BLOCKED,
                                "text=%r" % txt2)
                    worst += ck("**不是**「这就给您放」那一句",
                                txt2 not in OK_LINES, "text=%r" % txt2)
                    worst += ck("也不是超时那一句（正确的回执被收下了）",
                                txt2 != FAIL_TIMEOUT, "text=%r" % txt2)
                    await asyncio.sleep(0.4)
                    tail = open(LOG, encoding="utf-8",
                                errors="replace").read().splitlines()[n:]
                    dropped = [l for l in tail if "丢掉一条迟到的 do_result" in l]
                    worst += ck("★ 迟到的回执被丢掉并且留下了一行日志",
                                bool(dropped), (dropped[0][:90] if dropped
                                                else "日志里没有那一行"))
                    ok_i, st_i = await to_idle()
                    worst += ck("念完收尾回了 idle（状态机，不是事件）", ok_i,
                                "state=%r" % st_i)

                # ------------------------------- 第三轮：问服务区那两条"没数据"的路
                print("\n=== G 「问服务区」两条**拿不到数据**的路：不许把占位符念出来 ===")
                # 2026-09-26：`SCRIPT["nearby"]` 是**模板**（`{name}/{km}/{tail}`），
                # 只有 `_nearby_reply` 填得满它。可"问服务区"还有两条路**没有数据**：
                # 页面上那颗按钮（点击）和打字走固定话术那一趟。两条原来都直接
                # `_pick("nearby")`，于是气泡里印出来的是没填过的占位符 ——
                # 「主人，最近的是{name}，还有 {km}。要我导过去吗？」。
                # 这一段的判据就是"这四句里一个字的花括号都不许有"，外加"两条路
                # 走的确实是 `rest_stop` 那张表"。⚠️ 语音那条路（有真数据）在上面
                # A~F 段里，仍然是模板，没被这一段动过。
                bad = [(k, ln) for k in NO_DATA_TABLES
                       for ln in [x for ls in xiaorui.SCRIPT[k].values() for x in ls]
                       if "{" in ln or "}" in ln]
                worst += ck("★ 没有数据的表里一个占位符都没有", not bad,
                            "%d 条带花括号 %s" % (len(bad),
                                                 ("例：%r" % bad[0]) if bad else ""))
                r = xiaorui.ScriptedAgent().reply(_St(), "附近有服务区吗", 0.0)
                worst += ck("★ 打字问服务区走 rest_stop 那张表",
                            r.text in REST_LINES, "text=%r" % r.text)
                worst += ck("★ 而且念的不是 nearby 的模板",
                            r.text not in NEARBY_LINES, "text=%r" % r.text)
                for aid in ("rest_stop", "nearby"):
                    says.clear()
                    await ws.send_json({"type": "action", "id": aid})
                    got = None
                    for _ in range(40):
                        got = next((s for s in says
                                    if s.get("action_done") == aid), None)
                        if got:
                            break
                        await asyncio.sleep(0.2)
                    t3 = (got or {}).get("text") or ""
                    worst += ck("★ 点「%s」回的话没有占位符" % aid,
                                bool(t3) and "{" not in t3 and "}" not in t3
                                and t3 in REST_LINES, "text=%r" % t3)
                await asyncio.sleep(0.3)

                # ------------------------------- 第四/五轮：打开某一页、导航过去
                print("\n=== H 「打开某一页 / 导航过去」：服务端**真**让页面去跳 ===")
                # 用户原话：「它可以对这个网页所有东西进行操控 比如我让它导航它肯定真
                #   导航啊 直接跳转这些啊 我让它干嘛肯定干嘛啊」。这一段量的就是那句
                #   "真的让它去跳"：**真音频进 → 真识别 → 服务端真发 `do`**，走的是
                #   `voice_answer` → `voice_do` → `wake.js` 的 `ev:"do"` 那条路。
                #
                # 🔴 **这里验不到"浏览器真的跳过去了"**，别把这一段当成那个：
                #   扮演页面的这一侧是 Python，它收到 `do` 只会**按剧本回一条回执**
                #   （真跳要 `location.href`，而且一跳这条 WebSocket 就断了、后面的
                #   判据全都无从谈起）。所以两边合起来才算数 ——
                #     · 这一段：服务端**发没发**这条命令、按回执挑的**是哪句话**；
                #     · `_probe_nav_jump.py`（真浏览器、真 `elementFromPoint`、真
                #       `location.pathname`）：`navTarget`/`samePage` 判得对不对、
                #       页面是不是真开到了 `nav.html`。
                #   ⚠️ 也就是 `same`（"你就在这一页上"）那一条**在这里是假的**：
                #      我们的假页面永远回它被要求回的那个回执。它由上面那份脚本和
                #      H3 段的**静态比表**兜着，别以为这里覆盖了。
                ok_i, st_i = await to_idle()
                await asyncio.sleep(0.6)                  # GUARD_S，见文件头

                async def jump_round(wav, extra, jumps=True):
                    """喂一句命令音频，按剧本把回执发回去，收回服务端发的东西。

                    `jumps=True` —— 页面**真的要跳走**（回执 `ok` 且没有 `here`/`same`）：
                    服务端只画气泡、**不发 `ev:"reply"`**，那一句由跳过去之后活着的那一页说
                    （`voice_ask`，J 段验的就是它）。所以这一档等的是**气泡**不是回话。

                    `jumps=False` —— 页面**留在原地**（`here`/`same`/`ok:false`）：它照常念，
                    念完照样回一条 `voice_spoken`（真页面就是这么干的），所以这一档等的是
                    **`ev:"reply"`**、并且收尾时要替它把回执发回去。

                    返回 `(do, heard, say, reply)`：`do` 是服务端发的那条 `ev:"do"`，
                    `say` 是气泡广播，`reply` 是 `ev:"reply"` —— 两档各有一条是空的
                    （**空的那条就是要验的那条**，别改成一律 None）。
                    """
                    evs.clear()
                    says.clear()
                    await send_audio(ws, pcm(ROOT / "runs" / "wake_samples"
                                             / (wav + ".wav")))
                    d = await wait_ev("do", timeout=60)
                    hd = next((e.get("text") or "" for e in evs
                               if e.get("ev") == "heard"), "")
                    if d:
                        body = {"type": "do_result", "id": d.get("id"),
                                "seq": d.get("seq")}
                        body.update(extra)
                        await ws.send_json(body)
                    if jumps:
                        rep = await wait_say(lambda s: s.get("voice") is True,
                                             timeout=30)
                        if rep:
                            # ⚠️ 这里**不调 `to_idle()`**：这一轮服务端当场就把状态机
                            #    收回 IDLE 了（`voice_say(jump=True)` 那一支），根本没有
                            #    "念完了"这回事。照老样子回一条 `voice_spoken`，轮次卫兵
                            #    会把它丢掉并往**真服务器**的日志里灌一行噪音 —— 而那份
                            #    日志（`runs/_check_voice_do_srv.log`）正是查问题时唯一的线索。
                            await asyncio.sleep(0.6)
                        return d, hd, rep, next((e for e in evs
                                                 if e.get("ev") == "reply"), None)
                    # 页面没跳：它真的会念（走 SPEAK + 看门狗），念完回执把状态放回
                    # 追问窗口。不替它回执的话，看门狗要等 6.0 + 字数*0.35 s 才收尾，
                    # 后面几段全卡在 SPEAK 上 —— 那是**脚本**没扮演好，不是产品坏。
                    rep_ev = await wait_ev("reply", timeout=30)
                    await to_idle()
                    return d, hd, None, rep_ev

                # ---- H1 「打开多媒体」：go:<键> 那一支（**页面真跳**）
                d, heard, rep, _ = await jump_round("pos_goto_media", {"ok": True})
                txt = (rep or {}).get("text") or ""
                print("      识别：%r → 服务端发的 id=%r" % (heard, (d or {}).get("id")))
                worst += ck("识别到了「多媒体」（繁简归一后）",
                            "多媒体" in xiaorui.zh_t2s(heard), "heard=%r" % heard)
                worst += ck("★ 服务端真发了 do，id 是 go:media",
                            (d or {}).get("id") == "go:media",
                            "id=%r" % (d or {}).get("id"))
                worst += ck("do 带了轮次号 seq", isinstance((d or {}).get("seq"), int),
                            "seq=%r" % (d or {}).get("seq"))
                worst += ck("★ 回执 ok → 气泡里是 SCRIPT['go'] 的话，且 {page} 已填成「多媒体」",
                            txt in {ln.format(page=xiaorui.PAGES["media"])
                                    for ln in GO_LINES}, "text=%r" % txt)
                worst += ck("★ 一个占位符都没漏在嘴上",
                            "{" not in txt and "}" not in txt, "text=%r" % txt)
                worst += ck("★ 没说成「你就在这一页上」（这一轮页面回的是真跳了）",
                            txt not in GO_SAME_LINES, "text=%r" % txt)
                worst += ck("没走模型（backend=scripted）",
                            (rep or {}).get("backend") == "scripted",
                            "backend=%r" % (rep or {}).get("backend"))
                # ★★ 2026-09-26：**这一轮必须不念话**。跳页那两轮要是照旧发
                #    `ev:"reply"`，页面念到一半就被 `location.href` 掐成半句，
                #    而"念完了"的回执永远不会来（`speechSynthesis` 随 document 没了）
                #    —— 看门狗到点收尾，追问窗口也就开不了。所以那一句交给跳过去
                #    之后活着的那一页说（`voice_ask`，J 段验的就是它）。
                worst += ck("★★ 这一轮**没有** ev:'reply'（念出来只有半句，得由新页面说）",
                            next((e for e in evs if e.get("ev") == "reply"), None) is None,
                            "事件：%s" % [e.get("ev") for e in evs])

                # ---- H2 「我要去休息区」：rest_stop 那一支 + `here` 回执（**页面没跳**）
                #
                # ⚠️ 这一档**必须念**，而且这一条断言 2026-09-26 晚些时候**翻过面**：
                #    原来是"这一轮也没有 ev:'reply'"（H1 那条的另一半），因为服务端那会儿
                #    把这支也当"反正要跳"处理 —— 于是主人已经站在导航页上说了「要」、
                #    服务端就地查了、回执也对，屏上却**一个字都没有**（J2 段逮到的就是它）。
                #    现在判据是**回执**（`ok` 且没有 `here`/`same` 才叫"要跳"），
                #    `here` 这一档照常念 `SCRIPT['rest_stop_here']`。
                d, heard, _, rep_ev = await jump_round("pos_rest_stop",
                                                       {"ok": True, "here": True},
                                                       jumps=False)
                txt = (rep_ev or {}).get("text") or ""
                print("      识别：%r → 服务端发的 id=%r" % (heard, (d or {}).get("id")))
                worst += ck("识别到了「休息区」（繁简归一后）",
                            "休息区" in xiaorui.zh_t2s(heard), "heard=%r" % heard)
                worst += ck("★ 服务端真发了 do，id 是 rest_stop",
                            (d or {}).get("id") == "rest_stop",
                            "id=%r" % (d or {}).get("id"))
                worst += ck("★★ here 回执 → **念出来**的是 SCRIPT['rest_stop_here']"
                            "（这一页没跳，屏上有话）",
                            txt in HERE_LINES, "text=%r" % txt)
                worst += ck("★ 没说成「我这就把它调出来」（那和屏幕不一致）",
                            txt not in REST_LINES, "text=%r" % txt)
                worst += ck("一个占位符都没漏在嘴上",
                            "{" not in txt and "}" not in txt, "text=%r" % txt)

                # ---- H3 静态：两张手抄的表 + 占位符填得满 + 回执→话术的映射
                #
                # 为什么这几条**不收音频**：它们量的东西和音频无关，而且贵。
                # ⚠️ 收音频的只有 H1/H2 两轮（每轮 ~10 s 静音 + 音频，挂钟上很贵）。
                #    `same` / `no_target` / 没见过的 `why` 这三档在这里直接调
                #    `act_reply` —— 服务端那条路已经把回执原样递给它了（H1/H2 证明了
                #    这一点），所以这里量的是**映射本身**，不是回路。
                print("\n=== H3 静态：左栏两张表对齐 / 占位符填得满 / 失败档不许沉默 ===")
                navs = nav_entries()
                worst += ck("从 chrome.js 抠出了左栏那张表", len(navs) >= 4,
                            "%d 项：%s" % (len(navs),
                                          " ".join("%s=%s" % (k, f) for k, _, f in navs)))
                worst += ck("★ 两边的键一模一样（少一个 = 有一页喊不动）",
                            [k for k, _, _ in navs] == list(xiaorui.PAGES),
                            "chrome.js=%s  xiaorui.PAGES=%s"
                            % ([k for k, _, _ in navs], list(xiaorui.PAGES)))
                worst += ck("★ 两边的标签也一模一样（喊错页名会让人以为它没听懂）",
                            [t for _, t, _ in navs] == list(xiaorui.PAGES.values()),
                            "%s vs %s" % ([t for _, t, _ in navs],
                                          list(xiaorui.PAGES.values())))
                missing = [f for _, _, f in navs if not (ROOT / "ui" / "web" / f).exists()]
                worst += ck("★ 目标文件都在磁盘上（缺了 = 跳过去是一张白页）",
                            not missing, "缺：%s" % missing)
                # 每一页都得填得满：`format` 不认得的占位符会**抛**（`{pages}` → KeyError），
                # 填漏一个就是把 `{page}` 念给主人听。所以对**每一个**页名各来一遍，
                # 连"这句话里到底有没有出现页名"一起看（有一句漏写 `{page}` 也当场红）。
                gofmt = []
                for tname, lines in (("go", GO_LINES), ("go_same", GO_SAME_LINES)):
                    for ln in sorted(lines):
                        for pg in xiaorui.PAGES.values():
                            try:
                                s2 = ln.format(page=pg)
                            except (KeyError, IndexError, ValueError):
                                gofmt.append((tname, ln, pg))
                                continue
                            if "{" in s2 or "}" in s2 or pg not in s2:
                                gofmt.append((tname, ln, pg))
                worst += ck("★ go/go_same 的每一句对每一个页名都填得满、而且念得出页名",
                            not gofmt, ("例：%r" % (gofmt[0],)) if gofmt else "")
                bad2 = [(k, ln) for k in NO_DATA_TABLES
                        for ln in [x for ls in xiaorui.SCRIPT[k].values() for x in ls]
                        if "{" in ln or "}" in ln]
                worst += ck("★ 不是模板的那些表一个字的花括号都没有", not bad2,
                            ("例：%r" % (bad2[0],)) if bad2 else "")
                sa = xiaorui.ScriptedAgent()
                # ① 就在这一页上 → `go_same`（不能还说"这就打开"）
                r = sa.act_reply(_St(), "go:media", {"ok": True, "same": True}, 0.0)
                worst += ck("★ same:true → 走 go_same 那张表",
                            r.text in {ln.format(page="多媒体") for ln in GO_SAME_LINES},
                            "text=%r" % r.text)
                # ② 页面说找不到这一页 → 照实说，**不许**编一个页名
                r = sa.act_reply(_St(), "go:media", {"ok": False, "why": "no_target"}, 0.0)
                worst += ck("★ no_target → ACT_FAIL['go']['no_target']",
                            r.text == xiaorui.ACT_FAIL["go"]["no_target"],
                            "text=%r" % r.text)
                # ③ 认不出的键：不许糊一句"这就打开"，也不许抛异常
                r = sa.act_reply(_St(), "go:不存在", {"ok": True}, 0.0)
                worst += ck("★ 不认识的页键 → 照实说找不到（不编页名）",
                            r.text == xiaorui.ACT_FAIL["go"]["no_target"],
                            "text=%r" % r.text)
                # ④ 没见过的失败原因 → 落到 `_unknown`，不许空串也不许抛
                r = sa.act_reply(_St(), "rest_stop", {"ok": False, "why": "没见过的原因"}, 0.0)
                worst += ck("★ 没见过的 why → 落到 _unknown（有话说，不空）",
                            r.text == xiaorui.ACT_FAIL["rest_stop"]["_unknown"],
                            "text=%r" % r.text)
                # ⑤ 超时那一档也是实话
                r = sa.act_reply(_St(), "rest_stop", {"ok": False, "why": "timeout"}, 0.0)
                worst += ck("★ 超时 → 说的是「没收到回执」，不是「已经打开了」",
                            r.text == xiaorui.ACT_FAIL["rest_stop"]["timeout"],
                            "text=%r" % r.text)

                # =========================================== F 判据表（纯静态，秒级）
                #
                # ★★ 2026-09-26：用户报的那句话就写在这张表的第一行 ——
                #    「我让它导航咋不做」。原来 `detect_action('给我导航')` 回**空串**
                #    （`NAV_CMD` 只在服务区分支里被读，而那句话里没有「服务区」），
                #    于是它落进模型那一支：模型现编了一句"要不要我帮您导航到最近的
                #    服务区？"，**服务端一次动作都没发起**；主人应了一声「要」，
                #    又落进模型一次。屏幕上从头到尾什么都没发生。
                #
                # ⚠️ 这张表**不许删条目**。每一条都是一次"主人说了它却不动"的事故
                #    （或者是差一点就误动的边界 —— 「带我去吃饭」那一组）。
                # ⚠️ 它**不经过音频**：真正"真音频→真识别→真发 do"那半条在 J1~J5 段。
                #    两句合起来才算数（合成音认不出「给我导航」，见 J1 段和
                #    `_make_wake_wavs.py` 里那条注释）。
                print("\n=== F 判据表：哪些话**真的**判成了动作（纯静态） ===")
                table = [
                    # —— 用户的原话（这一行是整件事的起点）
                    ("给我导航", "rest_stop"),
                    ("导航", "rest_stop"),
                    ("我要导航", "rest_stop"),
                    # —— 「打开某一页」：句子里有**页名**时主人要的是那一页，
                    #    不能因为句里出现「导航」两个字就变成"导航过去"
                    ("打开导航页", "go:navi"),
                    ("打开多媒体", "go:media"),
                    ("地图", ""),          # 光有页名没有动词 —— 照旧什么都不做
                    # —— 服务区（① 那一支没动，只是被 ② 让开了位置）
                    ("导航到最近的服务区", "rest_stop"),
                    ("我要去服务区", "rest_stop"),
                    ("带我去服务区", "rest_stop"),
                    ("附近有服务区吗", "nearby"),
                    ("导航还有多远", ""),   # 问句不跳（ASK_WORDS 拦着）
                    # —— 别的意图照旧
                    ("给我放个音乐", "music"),
                    ("我状态怎么样", ""),
                    # —— 🔴 **边界**：泛泛的"带我去 X / 我要去 X"**不能**跳导航页。
                    #    这几条是我自己写完 `NAV_STRONG` 之后回头发现的：第一版把
                    #    「带我」「我要去」也放了进去，于是「带我去吃饭」判成了
                    #    `rest_stop` —— 而"跳导航页"是最没礼貌的坏法。所以
                    #    `NAV_STRONG` 收窄成只有"导航"类硬词，这几条留在这儿看着。
                    ("带我去吃饭", ""),
                    ("我要去睡觉", ""),
                    ("领我去厕所", ""),
                    # —— 「要」本身**不是动作**：它的意义在"回答上一句"，由
                    #    `take_pending` 认（J2~J5 段）。判成动作就错了。
                    ("要", ""),
                    ("好", ""),
                    ("你好小瑞", ""),
                ]
                badF = [(t, w, xiaorui.detect_action(t)) for t, w in table
                        if xiaorui.detect_action(t) != w]
                worst += ck("★ 判据表逐条算对（含用户那句原话「给我导航」）",
                            not badF, ("例：%r" % (badF[0],)) if badF
                            else "%d 条" % len(table))
                aff = [("要", True), ("要的", True), ("好的", True), ("嗯嗯。", True),
                       ("行吧", True), ("好的我知道了", False), ("那就要吧", False),
                       ("", False)]
                badA = [(t, w, xiaorui.is_affirm(t)) for t, w in aff
                        if xiaorui.is_affirm(t) != w]
                worst += ck("★ `is_affirm` 只认**整句相等**（「好的我知道了」不算）",
                            not badA, ("例：%r" % (badA[0],)) if badA
                            else "%d 条" % len(aff))

                # ============================ J1/J2 跳过去（不念）→ 页面来要 → 说「要的」
                #
                # 这一段的形状就是用户拍板的「跳过去 + 问一句」：
                #   J1 主人说「导航」→ 服务端发 `do rest_stop` → 页面回执
                #      → **这一轮不念话**（页面 180 ms 后就没了，念出来只有半句）
                #   J2 刚跳过去的那一页发 `{"type":"ask"}` → 小瑞问一句（**问句**），
                #      并且**挂上待确认** → 主人说「要的」→ 服务端再发一次 `do`
                #      → 这一页此刻就站在导航页上 → 就地查 → `here:true` → 那句话
                print("\n=== J1 说「导航」→ 真发 do，而且**这一轮不念**（跳页会把话掐断）===")
                ok_i, st_i = await to_idle()
                await asyncio.sleep(0.6)                  # GUARD_S，见文件头
                evs.clear()
                says.clear()
                await send_audio(ws, pcm(ROOT / "runs" / "wake_samples"
                                         / "pos_goto_nav.wav"))
                dA = await wait_ev("do", timeout=60)
                heardA = next((e.get("text") or "" for e in evs
                               if e.get("ev") == "heard"), "")
                print("      识别：%r → 服务端发的 id=%r" % (heardA,
                                                          (dA or {}).get("id")))
                worst += ck("识别到了「导航」（繁简归一后）",
                            "导航" in xiaorui.zh_t2s(heardA), "heard=%r" % heardA)
                worst += ck("★ 服务端真发了 do，id 是 rest_stop（原话那句现在真的动了）",
                            (dA or {}).get("id") == "rest_stop",
                            "id=%r" % (dA or {}).get("id"))
                if dA:
                    await ws.send_json({"type": "do_result", "id": dA.get("id"),
                                        "seq": dA.get("seq"), "ok": True})
                await asyncio.sleep(1.2)                  # 等它把这一轮收尾
                repA = next((e for e in evs if e.get("ev") == "reply"), None)
                worst += ck("★ **这一轮没有 ev:'reply'**（页面马上要跳，念出来只有半句）",
                            repA is None,
                            "text=%s" % short((repA or {}).get("text")))
                vsA = [s for s in says if s.get("voice") is True]
                worst += ck("★ 但气泡照画（`say` 广播还在，话出自 SCRIPT['rest_stop']）",
                            bool(vsA) and (vsA[-1].get("text") in REST_LINES),
                            "text=%s" % short((vsA[-1].get("text") if vsA else "")))
                eaA = await ear_now() or {}
                worst += ck("★ 状态机当场收干净（没有 SPEAK 等一个永远不来的回执）",
                            eaA.get("state") == "idle", "state=%r" % eaA.get("state"))

                # -------------------------------------------------- J2 跳过去之后问那一句
                print("\n=== J2 刚跳过来的那一页来要一句话 → 小瑞问 → 主人说「要的」→ 真查 ===")
                evs.clear()
                says.clear()
                # 扮演"刚跳过来的那一页"：`origin` 是它此刻**手上真有的起点**。
                await ws.send_json({"type": "ask", "id": "rest_stop",
                                    "origin": {"lat": 30.5, "lng": 114.3,
                                               "manual": True}})
                repB = await wait_ev("reply", timeout=30)
                txtB = (repB or {}).get("text") or ""
                print("      小瑞问：%r" % txtB)
                worst += ck("★ 念的是 SCRIPT['ask_rest_stop'] 那句",
                            txtB in ASK_LINES, "text=%r" % txtB)
                worst += ck("★ 而且它**是个问句**（主人得能应一声）",
                            ("？" in txtB) or ("?" in txtB), "text=%r" % txtB)
                worst += ck("一个占位符都没漏在嘴上",
                            "{" not in txtB and "}" not in txtB, "text=%r" % txtB)
                worst += ck("没走模型（backend=scripted）",
                            (repB or {}).get("backend") == "scripted",
                            "backend=%r" % (repB or {}).get("backend"))
                ok_i, st_i = await to_idle()
                worst += ck("念完进了追问窗口（这时主人才答得上「要的」）",
                            st_i == "follow", "state=%r" % st_i)
                await asyncio.sleep(0.6)
                # ---- 主人应一声「要的」：**不喊唤醒词**，就在追问窗口里说
                evs.clear()
                says.clear()
                eaB = await ear_now() or {}
                worst += ck("★ 喂「要的」之前状态真的是 follow/listen（否则下面那条绿是假的）",
                            eaB.get("state") in ("follow", "listen"),
                            "state=%r" % eaB.get("state"))
                await send_audio(ws, pcm(ROOT / "runs" / "wake_samples"
                                         / "pos_affirm.wav"))
                dB = await wait_ev("do", timeout=60)
                heardB = next((e.get("text") or "" for e in evs
                               if e.get("ev") == "heard"), "")
                print("      识别：%r → 服务端发的 id=%r" % (heardB,
                                                          (dB or {}).get("id")))
                worst += ck("★ 认出来的确实是那句同意（繁简归一后能过 is_affirm）",
                            xiaorui.is_affirm(xiaorui.zh_t2s(heardB)),
                            "heard=%r" % heardB)
                worst += ck("★ 「要的」真的又发了一次 do，id 是 rest_stop",
                            (dB or {}).get("id") == "rest_stop",
                            "id=%r" % (dB or {}).get("id"))
                worst += ck("do 带了轮次号 seq", isinstance((dB or {}).get("seq"), int),
                            "seq=%r" % (dB or {}).get("seq"))
                if dB:
                    # 这一页此刻**就站在导航页上**（`originNow()` 非空）→ 就地查
                    await ws.send_json({"type": "do_result", "id": dB.get("id"),
                                        "seq": dB.get("seq"), "ok": True,
                                        "here": True})
                repB2 = await wait_ev("reply", timeout=30)
                txtB2 = (repB2 or {}).get("text") or ""
                print("      小瑞：%r" % txtB2)
                worst += ck("★ here 回执 → 念的是 SCRIPT['rest_stop_here']（就地查）",
                            txtB2 in HERE_LINES, "text=%r" % txtB2)
                worst += ck("★ 没说成「我这就把它调出来」（那和屏幕不一致）",
                            txtB2 not in REST_LINES, "text=%r" % txtB2)
                await to_idle()
                await asyncio.sleep(0.6)

                # ------------------------------------------- J3 没有待确认动作时说「要的」
                print("\n=== J3 没有待确认动作时说「要的」→ **不许**发 do（落回模型）===")
                evs.clear()
                says.clear()
                eaC = await ear_now() or {}
                worst += ck("喂「要的」之前状态真的是 follow/listen（否则下面那条绿是假的）",
                            eaC.get("state") in ("follow", "listen"),
                            "state=%r" % eaC.get("state"))
                await send_audio(ws, pcm(ROOT / "runs" / "wake_samples"
                                         / "pos_affirm.wav"))
                repC = await wait_ev("reply", timeout=40)
                doc = next((e for e in evs if e.get("ev") == "do"), None)
                worst += ck("★ 一条 do 都没发（「要」不是动作，是回答上一句）",
                            doc is None,
                            "id=%r" % ((doc or {}).get("id")))
                worst += ck("而且确实答了一句（走的是模型那一路，没哑掉）",
                            repC is not None, "text=%s" % short((repC or {}).get("text")))
                await to_idle()
                await asyncio.sleep(0.6)

                # ------------------------------- J4 跳过去但**起点拿不到** → 说实话、不挂
                print("\n=== J4 页面报 origin:null → 说实话（不挂待确认）===")
                evs.clear()
                says.clear()
                await ws.send_json({"type": "ask", "id": "rest_stop",
                                    "origin": None})
                repD = await wait_ev("reply", timeout=30)
                txtD = (repD or {}).get("text") or ""
                print("      小瑞：%r" % txtD)
                worst += ck("★ 念的是 ACT_FAIL['nearby']['no_geo']（分档的一句实话）",
                            txtD in NO_GEO_LINES, "text=%r" % txtD)
                worst += ck("★ **不是**那句问句（答应了也查不到，那就成了话和事不一致）",
                            txtD not in ASK_LINES, "text=%r" % txtD)
                worst += ck("一个占位符都没漏在嘴上",
                            "{" not in txtD and "}" not in txtD, "text=%r" % txtD)
                await to_idle()
                await asyncio.sleep(0.6)
                evs.clear()
                says.clear()
                eaD = await ear_now() or {}
                worst += ck("喂「要的」之前状态真的是 follow/listen",
                            eaD.get("state") in ("follow", "listen"),
                            "state=%r" % eaD.get("state"))
                await send_audio(ws, pcm(ROOT / "runs" / "wake_samples"
                                         / "pos_affirm.wav"))
                # ⚠️ 这一段没有 `do` 可等（**要等的就是"它不来"**）：
                #    等一个 `reply` 收尾，再看这一轮里有没有 `do`。
                #    （别为了"等一个不会来的东西"去写 sleep —— 那既慢又不可靠，
                #      而且这一轮的 `reply` 本来就必须来：那一句是走模型/固定话术的。）
                repD2 = await wait_ev("reply", timeout=40)
                dD = next((e for e in evs if e.get("ev") == "do"), None)
                worst += ck("★ 这才**没有** do（那一档没挂待确认，说「要的」也不该动）",
                            dD is None, "id=%r" % ((dD or {}).get("id")))
                worst += ck("而且答了一句（没哑掉）", repD2 is not None,
                            "text=%s" % short((repD2 or {}).get("text")))
                await to_idle()
                await asyncio.sleep(0.6)

                # ------------------------------------- J5 问完之后**换了话题** → 提议作废
                print("\n=== J5 问完那句之后主人说别的 → 待确认被顶掉 ===")
                evs.clear()
                says.clear()
                await ws.send_json({"type": "ask", "id": "rest_stop",
                                    "origin": {"lat": 30.5, "lng": 114.3,
                                               "manual": True}})
                repE = await wait_ev("reply", timeout=30)
                worst += ck("★ 又问了一句（同 J2 段，这一轮才有东西可作废）",
                            ((repE or {}).get("text") or "") in ASK_LINES,
                            "text=%s" % short((repE or {}).get("text")))
                ok_i, st_i = await to_idle()
                await asyncio.sleep(0.6)
                # ① 主人换了话题（这句话本身不碰任何意图）
                evs.clear()
                says.clear()
                await send_audio(ws, pcm(ROOT / "runs" / "wake_samples"
                                         / "pos_other_topic.wav"))
                repE2 = await wait_ev("reply", timeout=40)
                worst += ck("换的话题答上了（这一轮走的是模型那一路）",
                            repE2 is not None,
                            "text=%s" % short((repE2 or {}).get("text")))
                await to_idle()
                await asyncio.sleep(0.6)
                # ② 现在再说「要的」—— 提议已经被顶掉，**不许**发 do
                evs.clear()
                says.clear()
                eaE = await ear_now() or {}
                worst += ck("喂「要的」之前状态真的是 follow/listen（否则下面那条绿是假的）",
                            eaE.get("state") in ("follow", "listen"),
                            "state=%r" % eaE.get("state"))
                await send_audio(ws, pcm(ROOT / "runs" / "wake_samples"
                                         / "pos_affirm.wav"))
                repE3 = await wait_ev("reply", timeout=40)
                dE = next((e for e in evs if e.get("ev") == "do"), None)
                worst += ck("★ 主人换了话题之后，那件事就作废了（没有 do）",
                            dE is None, "id=%r" % ((dE or {}).get("id")))
                worst += ck("而且答了一句（没哑掉）", repE3 is not None,
                            "text=%s" % short((repE3 or {}).get("text")))
                await to_idle()

                t.cancel()
    finally:
        srv.terminate()
        time.sleep(0.8)
        if srv.poll() is None:
            srv.kill()
        log.close()

    print("\n" + "=" * 74)
    if worst:
        print("❌ %d 条不对（%s）" % (worst, "、".join(FAILS)))
        return 1
    print("✅ 全对 —— 「让它做 → 等回执 → 按结果说」这条通道是通的，"
          "而且做不成的时候说的不是「这就给您放」。")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
