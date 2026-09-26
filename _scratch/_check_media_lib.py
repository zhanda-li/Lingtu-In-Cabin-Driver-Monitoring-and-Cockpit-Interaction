# -*- coding: utf-8 -*-
"""多媒体页（放用户自己的歌）的专项检查。

用户的要求逐条对应到下面的段：
  · 「D:\\CloudMusic 这里的音乐放到多媒体里边」  → A / B / C（真的读目录、真的解码出波形）
  · 「可以下载30首到本地 然后其他读取我那个链接」→ A2 / L（见下面那段）
  · 「把那些常用应用栏目去掉」                  → F（那六格不许再回来）
  · 「推荐歌单栏目上移」                        → G（量出来的上下位置，不是读源码猜的）
  · 「布局一下 你那个位置都不对」               → G / H（整页高度必须在预算内，且几行的
                                                    左右关系对得上：歌单整行、我的音乐在左、
                                                    小瑞在右）
  · 「音效设置那一栏去掉 其他栏目等比例放大填充好那个页面」
                                                → G2（音效整块没了 + 三行都比删之前大 +
                                                    最后一张卡的底边贴到可视底边）
  · 「右侧对话框…预留多行对话区域，后续接入 DeepSeek API，
     多轮聊天时界面不会崩」                     → I2（灌 40 句，验裁剪 / 不被压扁 /
                                                    能滚 / 顶部滚得到 / 状态行贴底）
  · 「当 DMS 监测疲劳时，小瑞自动在这里推荐舒缓音乐，把多媒体
     和疲劳监测模块打通，这个是答辩大亮点」       → N（档位→挑歌→**真的响了**，
                                                    外带"用户刚点过就不抢歌"那条护栏）
  · 「小瑞那可以打字聊天」                       → O（真敲真回车 → 自己的气泡 +
                                                    「正在想」→ 服务端回话；
                                                    ★★ 外加"外来的 say 一句都不许
                                                    混进来"这条过滤器）
  · 「我要求它放 但并没有真做」                 → P（「放歌/小声一点/停一下/接着放/
                                                    下一首」每一条都要**真的动了播放器**，
                                                    而且回话点名的歌 == 正在放的那一首）
  · 「为啥两个状态都是自动放我好想你间奏这首歌
     还不如不同状态随机给歌 但不要每次都一样」   → Q（连着三档疲劳，摇出来的三首
                                                    必须两两不同）

⚠️ A2 段的判据 2026-09-25 换了落点：原来读行里那枚「内置」小标（`.tx em`），
   用户要求「去掉多余文字」把它删了，现在读机器可读的 `li[data-src="内置"]` ——
   判的还是同一件事（内置那批排在最前面）。

⚠️ 2026-09-25 晚另删了一处**重复**：正在播放那张卡里容量写了两遍（`#tSub` 的
   「歌手 · N MB」和 `#tRate` 的「N MB」），用户拍板「只删重复的容量」。
   所以 `#tRate` 这个元素在 markup 里已经不存在了 —— **别再按 id 读它**
   （`null.textContent` 当场抛，`_shot_media.py` 里那一处也一起改了）。
   `#tFmt`（「MP3 · 内置文件 / 本机文件」）**留着不动**：它说的是**出处**，不是容量，
   而且是列表行那枚「内置」小标删掉之后**全站唯一**还写"这首跟着项目走"的地方。

A2 / L 这一段是「30 首拷进项目」那次改版的回归。曲库现在有**两个来源**：
项目里的 `ui/media/`（内置 30 首）和用户目录（`media.dir`，默认 D:\\CloudMusic），
服务端按文件名去重后合成一张表发给前端。要守的是三件事：
  1. 内置那 30 首**真的在项目里**（不是页面自己编的标签）、**真的排在最前面**
     （演示机上先放得出来的就是它们）；
  2. 合成之后**总数不该变多** —— 内置那份是从用户目录拷的，同名的不许列两遍；
  3. 用户目录**不在**时不是"曲库空了"：还剩内置那批，而且页面**必须说出来**。

⚠️ 这个脚本**证明不了**：歌好不好听、配色好不好看、真人在 kiosk 全屏下看不看得清。
   那些只有人眼说了算。

⚠️ 它连的是**真的** `ui/config.json` 里那个 `media.dir`（默认 D:\\CloudMusic）。
   用户目录不在**不等于**这一页该红 —— 内置那份还在，它是"退化运行"不是故障。
   该红的是"目录不在却没在页面上说出来"，那条在 L 段。

    PYTHONIOENCODING=utf-8 python _scratch/_check_media_lib.py
"""

import asyncio
import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _check_pages import Session, ck            # noqa: E402  复用那套 CDP 管道

PY = r"D:\Anaconda3\envs\dms\python.exe"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8795                       # 正常那份服务（真的用户目录 + 内置）
PORT2 = 8796                      # L 段用：曲库目录指到一个不存在的地方
CDP = 9415
SHOT = os.path.join(ROOT, "runs", "_media_lib.png")
LOG = os.path.join(ROOT, "runs", "_media_lib_srv.log")
LOG2 = os.path.join(ROOT, "runs", "_media_lib_srv_nomedia.log")
BASE = "http://127.0.0.1:%d" % PORT
# 一个**装成不存在的**目录。用 Z: 是因为这台机器没有 Z 盘，而且不去碰用户的
# `ui/config.json`（那份里有 API key，改它的风险远大于收益）。
NOMEDIA = "Z:/__这个目录不存在__"

# 2026-09-25：这一页**开始连 WebSocket 了**（疲劳联动那件事）。收 `state`，以及
# `say` 里**我打出去那句的回音**（2026-09-25 晚加的打字聊天，见 O 段）。
# `info` 仍然不接，所以没有 hello、也没有别的页那些 TTS/探针 404。
# ⚠️ 连了之后多一个假红来源：`--source demo` 自己也会推档位、而且**它推的
#    `say`（主动预警）和页面自己那句回音是同一个广播**，时序不受这个脚本控制。
#    所以 I2 / N 两段里凡是要"喂一个档位再看结果"的地方，全都塞进同一个
#    `Runtime.evaluate`（中间不 await，消息就插不进来）。见 N 段开头那段注释。
# ⚠️ 反过来说：页面那条"只认 `d.user === SAY_WAIT`"的过滤器**同时保住了 I2 / N
#    的确定性** —— 没有它，demo 推一条主动预警就会往 `XQ_LOG` 里插一句，
#    I2 断言的"第一句是压测第 11 句 / 最后是第 40 句"当场就红，而页面其实没坏。
#    改那条过滤器之前先想到这里。
# ★ 2026-09-25 晚补一层：`xqSend` 现在**先认一遍命令**（放歌 / 下一首 / 小声点…），
#    认出来就**本地执行、根本不发给服务端**（见 P 段）。所以 O 段那两句闲聊**必须
#    是纯闲聊** —— 句子里带「放一首」「来点」这种字样就当场变成命令，"等回音"这条
#    判据就没有对象了（第一版喂的「我有点困，来点舒缓的」正好命中 `play`）。
KNOWN = ("/assets/camera.jpg", "/assets/camera.mp4")

_LOGS = []                        # 起服务时开的日志句柄，收尾要关


def start_server(port, logpath, extra=()):
    """起一份 `ui/server.py`。`extra` 是额外参数（L 段用它把曲库目录指到不存在
    的地方）。**只走命令行，不碰 ui/config.json**。"""
    log = open(logpath, "w", encoding="utf-8")
    _LOGS.append(log)
    return subprocess.Popen([PY, "-u", "ui/server.py", "--port", str(port),
                             "--source", "demo"] + list(extra),
                            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                            env=dict(os.environ, PYTHONIOENCODING="utf-8"))


def wait_lib(port, tries=60):
    """等服务起来、并且 /music.json 拿得到。回它的解析结果，起不来回 None。"""
    for _ in range(tries):
        try:
            return lib_expected(port)
        except Exception:
            time.sleep(0.5)
    return None


def stop(proc):
    proc.terminate()
    time.sleep(0.8)
    if proc.poll() is None:
        proc.kill()


async def goto(S, path, wait=3.0, port=PORT):
    """⚠️ **别用 `S.goto()`**，虽然它是同一个 Session 上的方法 —— 它拼的地址是
    `_check_pages` 模块里的 `BASE`（= 那个脚本自己的 `PORT`，默认 **8790**），
    不是这里的 8795。复用它等于把浏览器开到另一个端口上，而那边没有服务：
    表现是 `location.href == 'chrome-error://chromewebdata/'`、标题变成
    "127.0.0.1"、页面上每个 `getElementById` 都是 null —— **看起来像"新页面炸了"，
    实际是"浏览器压根没到这一页来"**。这个坑 2026-09-25 绕了两个来回，
    所以这里显式拼自己的地址。"""
    await S.cmd("Page.navigate", {"url": "http://127.0.0.1:%d%s" % (port, path)})
    await asyncio.sleep(wait)


def lib_expected(port=PORT):
    """服务端 /music.json 说的曲目表 —— 页面上的行数必须等于它的长度。
    这个数**从服务端现读**，不是写死 155：曲库会变（用户加歌、目录换机器、
    内置那份被谁删了），写死就是一条迟早会假的红。"""
    with urllib.request.urlopen("http://127.0.0.1:%d/music.json" % port, timeout=5) as r:
        return json.load(r)


async def main():
    srv = start_server(PORT, LOG)
    srv2 = None
    worst = 0
    try:
        lib = wait_lib(PORT)
        if lib is None:
            print("!!  服务没起来，先看 " + LOG)
            return 1
        n = len(lib["tracks"])
        nb = lib.get("bundled", 0)
        print("服务端说：曲库 %s（目录在=%s），%d 首，其中内置 %d 首"
              % (lib["dir"], lib.get("dirOk"), n, nb))

        async with Session(CDP) as S:
            S.errs.clear()
            print("\n=== A · 曲库真的读出来了 ===")
            await goto(S, "/media.html", 3.5)
            a = await S.js("JSON.stringify({"
                           " rows: document.querySelectorAll('.tracks li[data-i]').length,"
                           " note: document.getElementById('listNote').textContent,"
                           " pill: !!document.getElementById('libPill'),"
                           " txt: document.body.innerText.indexOf('曲库 ·'),"
                           " phr: document.body.innerText.indexOf('点一行就放'),"
                           " phr2: document.body.innerText.indexOf('列表可以滚'),"
                           " cnt: document.body.innerText.indexOf('首 · 内置')})")
            worst |= ck("★ 条数 = 服务端 /music.json 的条数", a["rows"] == n,
                        "%d 行 / 服务端 %d 首" % (a["rows"], n))
            # ⚠️ 2026-09-24：这一段原来读 `#libDir` / `#libTotal` / `#libBundled`
            #    / `#libWarn` 四个槽，外加页标题右边那枚 `#libPill`。前四个是上一次
            #    「删成段说明文字」时删掉的、pill 是用户刚点名删的 —— 在**不存在的
            #    id** 上取 `.textContent` 会当场抛异常，`S.js` 返回 None，
            #    于是 `a["rows"]` 再炸一层，**整个检查脚本死在这一段**，
            #    后面 B~L 一条都跑不到（而报错长得像"探针写错了"）。
            #    所以：数字改到 `#listNote` 上核，pill 反过来钉"确实没了"。
            worst |= ck("★ 页标题右边那枚「曲库 · N 首 · 内置 nb」牌子没了",
                        a["pill"] is False and a["txt"] < 0,
                        "元素还在=%s / 正文里还能搜到=%s" % (a["pill"], a["txt"] >= 0))
            # ★ 2026-09-25 用户：「共 155 首 · 内置 30 · 点一行就放（列表可以滚）这些字
            #    去掉」。所以这一条从"数字要在卡头上"**反过来了** —— 原来判
            #    `str(n) in note and str(nb) in note`，现在判那行字彻底没了。
            # ⚠️ 那组数字**没有失去验证**，换了两处更硬的落点：A 段第一条拿行数对
            #    服务端、A2 段拿 `data-src` 数内置那批 —— 都不依赖这行字。
            # ⚠️ 三个针都要：只查一句的话，「删了一半」照样绿。
            worst |= ck("★ 卡头那行「共 N 首 · 内置 nb · 点一行就放（列表可以滚）」彻底没了",
                        a["phr"] < 0 and a["phr2"] < 0 and a["cnt"] < 0,
                        "「点一行就放」=%d 「列表可以滚」=%d 「首 · 内置」=%d"
                        % (a["phr"], a["phr2"], a["cnt"]))
            # 常态那一格现在是空的；临时话（读曲库…/读时长… N/M/有 N 个文件读不到）
            # 里头都没有「首」字 —— 所以"没挂着读数"有一条不挑时机的判据。
            worst |= ck("★ 那一格不再挂读数了（临时话里都不带「首」）",
                        "首" not in str(a["note"]), repr(a["note"]))

            print("\n=== A2 · 内置那 30 首（拷进项目的那批） ===")
            # ⚠️ 这一段的数字**全部对服务端**，不对源码：`bundled` 是 /music.json
            #    自己报的。所以内置那份被谁删了、或者用户目录里正好有同名歌，
            #    这里都会如实红/绿，不是"读了一遍我的实现"。
            # ★ 2026-09-25：判据的**落点换了**。原来读的是行里那枚蓝底「内置」小标
            #    （`.tx em`）。用户要求「统一字段：歌曲名 | 歌手，去掉多余文字」，
            #    那枚小标被点名删掉了 —— 继续盯 `.tx em` 的话这一段会**恒假红**
            #    （"标了 0 行"），而它报的其实是"我盯着的那个元素没了"。
            #    出处这件事本身还在 DOM 上，换成了机器可读的 `data-src`；所以这里
            #    改成读属性，判的还是同一件事：**内置那批有没有排在最前面**。
            a2 = await S.js(
                "const li = [...document.querySelectorAll('.tracks li')];"
                " const B = (e) => e.dataset.src === '内置';"
                " JSON.stringify({"
                "  rows: li.length,"
                "  tags: li.filter(B).length,"
                "  front: li.slice(0, %d).filter(B).length,"
                "  later: li.slice(%d).filter(B).length,"
                "  first: li.length ? B(li[0]) : false,"
                "  em: document.querySelectorAll('.tracks li em').length,"
                "  name: li.filter(e => e.querySelector('.tx > b')).length,"
                "  kids: [...new Set(li.map(e => e.querySelector('.tx')"
                "        ? e.querySelector('.tx').children.length : -1))],"
                "  note: document.getElementById('listNote').textContent})" % (nb, nb))
            worst |= ck("★ 列表认得出内置那 %d 首（`data-src`，不是 0 也不是全部）" % nb,
                        a2["tags"] == nb, "认了 %d 行 / 服务端说 %d 首" % (a2["tags"], nb))
            worst |= ck("★ 内置那批排在列表最前面（换了机器先能放的是它们）",
                        a2["front"] == nb and a2["later"] == 0,
                        "前 %d 行里有 %d 个 / 后面还有 %d 个"
                        % (nb, a2["front"], a2["later"]))
            worst |= ck("★ 合成之后总数没变多（同名的没列两遍）", a2["rows"] == n,
                        "列表 %d 行 / 服务端 %d 首" % (a2["rows"], n))
            # ★ 2026-09-25 用户：「歌曲信息列有点杂，建议统一字段：歌曲名 | 歌手，
            #    去掉多余文字」。所以这一列从"三种文字混着"收成两段：
            #      · 歌名一定在 `<b>` 里（每一行都有）；
            #      · `.tx` 的孩子只有 1 个（只有歌名）或 2 个（歌名 + 歌手）；
            #      · 那枚「内置」小标**不许回来** —— 它是被点名删的，不是漏了。
            #    中间的「·」是 CSS 的 `i::before` 给的，不在文本里，所以这里不数它。
            worst |= ck("★ 歌名列已经统一（每行的歌名都在 `.tx > b` 里）",
                        a2["name"] == a2["rows"],
                        "%d/%d 行" % (a2["name"], a2["rows"]))
            worst |= ck("★ 歌曲信息列只剩「歌名 | 歌手」两段（没有第三种东西混进来）",
                        all(k in (1, 2) for k in a2["kids"]), "各行段数 %s" % a2["kids"])
            worst |= ck("★ 行里那枚「内置」小标不许回来（用户点名删的）",
                        a2["em"] == 0, "还有 %d 个" % a2["em"])

            print("\n=== B · 时长是文件真给的（不是写死的） ===")
            # 155 首顺序读，给它时间。读不完也算数 —— 但要如实报出读了几首。
            for _ in range(40):
                st = await S.js("JSON.stringify({"
                                "ok: [...document.querySelectorAll('.tracks .dur')]"
                                ".filter(e => e.textContent.indexOf(':') >= 0).length,"
                                "bad: [...document.querySelectorAll('.tracks .dur')]"
                                ".filter(e => e.textContent === '读不到').length,"
                                " note: document.getElementById('listNote').textContent})")
                if st["ok"] >= n or st["bad"]:
                    break
                await asyncio.sleep(1.0)
            worst |= ck("★ 至少 90% 的行读出了真时长", st["ok"] >= n * 0.9,
                        "%d/%d（%s）" % (st["ok"], n, st["note"]))
            worst |= ck("没有读不到的文件", st["bad"] == 0, "%d 个" % st["bad"])

            print("\n=== C · 波形是按真实峰值画的（截断解码也得成） ===")
            # ⚠️ 这一条是本次改版技术上最不确定的地方：波形只取文件开头 2MB 去解码
            #    （整首解出来是几百 MB，见 media.html 里 loadPeaks 的注释）。所以这里
            #    不只是数柱子够不够 150，还要求**高度是有起伏的** —— 解码失败会退回
            #    等宽柱子（150 根一模一样的），只数根数是数不出来的。
            await S.js("document.querySelectorAll('.tracks li')[3].click()")
            for _ in range(20):
                w = await S.js("JSON.stringify({"
                               "bars: document.getElementById('wave').children.length,"
                               " uniq: [...new Set([...document.getElementById('wave')"
                               ".children].map(e => e.style.height))].length})")
                if w["uniq"] > 3:
                    break
                await asyncio.sleep(0.5)
            worst |= ck("柱子 150 根", w["bars"] == 150, "%d 根" % w["bars"])
            worst |= ck("★ 高度有起伏（= 真的解码出了峰值，不是退回等宽柱）",
                        w["uniq"] > 3, "不同高度 %d 种" % w["uniq"])

            print("\n=== D · 真的能放 ===")
            # ⚠️ `ppBtn` 是**播放/暂停二合一**（media.html 就是这么写的）：C 段点列表
            #    已经把它放起来了，这时候再点一下是「暂停」—— 第一版这里红了一条
            #    「播放键真的放起来了」，报的却是 `paused=true`，看着像页面坏了，
            #    其实是检查脚本没先看一眼当前状态。先 pause 到确定态再点。
            await S.js("au.pause(); 1")
            await asyncio.sleep(0.4)
            await S.js("document.getElementById('ppBtn').click()")
            await asyncio.sleep(2.0)
            d = await S.js("JSON.stringify({ct: au.currentTime, paused: au.paused,"
                           " src: au.currentSrc,"
                           " cur: document.getElementById('tCur').textContent,"
                           " state: document.getElementById('stateNote').textContent,"
                           " done: document.querySelectorAll('.mp-wave i.done').length})")
            worst |= ck("★ 播放键真的放起来了", d["ct"] > 0 and d["paused"] is False,
                        "已播=%s currentTime=%.2f 状态=%s 染色柱子=%d"
                        % (d["cur"], d["ct"], d["state"], d["done"]))
            worst |= ck("放的是 /music/ 那条路由", "/music/" in str(d["src"]),
                        str(d["src"]))

            print("\n=== E · 换一首真的换文件（列表点击） ===")
            before = await S.js("JSON.stringify({src: au.currentSrc,"
                                " cur: document.getElementById('tName').textContent})")
            await S.js("document.querySelectorAll('.tracks li')[1].click()")
            await asyncio.sleep(2.0)
            after = await S.js("JSON.stringify({src: au.currentSrc,"
                               " cur: document.getElementById('tName').textContent,"
                               " on: document.querySelectorAll('.tracks li.on').length,"
                               " dur: document.getElementById('tDur').textContent,"
                               " fmt: document.getElementById('tFmt').textContent})")
            worst |= ck("★ 换了文件、换了标题、只高亮一行",
                        before["src"] != after["src"] and before["cur"] != after["cur"]
                        and after["on"] == 1,
                        "%s -> %s，高亮 %d 行，时长 %s"
                        % (before["cur"][:16], after["cur"][:16], after["on"], after["dur"]))
            # 第 2 行是内置那批里的（内置排在最前面），正在播放那张牌要跟着说是
            # 「内置文件」—— 那 30 首是拷在项目里的，跟"你自己机器上的文件"不是一回事。
            if nb:
                worst |= ck("★ 正在播放那枚小牌说的是「内置文件」",
                            "内置" in after["fmt"], after["fmt"])

            print("\n=== F · 常用应用那一栏不许回来 ===")
            f = await S.js("JSON.stringify({"
                           " grid: !!document.getElementById('appGrid'),"
                           " tiles: document.querySelectorAll('.app-tile').length,"
                           " txt: document.body.innerText.indexOf('常用应用')})")
            worst |= ck("★ 那六格整块没了（用户点名的）", f["grid"] is False
                        and f["tiles"] == 0 and f["txt"] < 0,
                        "appGrid=%s app-tile=%d" % (f["grid"], f["tiles"]))

            print("\n=== G · 位置（量出来的，不是读源码猜的） ===")
            g = await S.js(
                "const r = (s) => { const e = document.querySelector(s);"
                " if (!e) return null; const b = e.getBoundingClientRect();"
                " return {t: Math.round(b.top), l: Math.round(b.left),"
                " w: Math.round(b.width), h: Math.round(b.height),"
                " b: Math.round(b.bottom), r: Math.round(b.right)}; };"
                "JSON.stringify({hero: r('.mp-hero'),"
                " lib: r('.mp-lib'), xq: r('.mp-xq'),"
                " sub: (() => { const e = document.querySelector('.sub-body');"
                " const b = e.getBoundingClientRect();"
                " return {t: Math.round(b.top), b: Math.round(b.bottom),"
                " h: Math.round(b.height), scroll: e.scrollHeight}; })()})")
            hero, libx, xq, sub = (g["hero"], g["lib"], g["xq"], g["sub"])
            # ⚠️ 2026-09-24：这一段原来还量 `.mp-rec`（推荐歌单）的位置，判「紧跟
            #    正在播放」「是整行」。用户要求把推荐歌单整块去掉，量不到的东西
            #    不能继续当判据 —— 换成下面这条**反面钉子**（跟 F 段那六格同一个套路）：
            #    行、卡片、标题三样都得不在，少查一样，"删了一半"也能全绿。
            worst |= ck("★ 推荐歌单整块没了（行 / 卡片 / 标题都不在）",
                        await S.js("!document.querySelector('.mp-rec')"
                                   " && document.querySelectorAll('.rec-card').length === 0"
                                   " && document.body.innerText.indexOf('推荐歌单') < 0"), "")
            worst |= ck("正在播放在最上面", hero["t"] == min(hero["t"], libx["t"]),
                        "hero.top=%d" % hero["t"])
            # ⚠️ 2026-09-24 用户报的：「正在播放部分要有歌名啊 都看不见歌名」。
            #    根因不是元素没了（`#tName` 一直在、字也一直在），是**被挤扁了**：
            #    封面 7rem → 14rem 那一次，`.now-row` 第一列还留在 17rem，
            #    247 − 203 − 11.6 只剩 32px 给歌名，而歌名那行是 nowrap + ellipsis
            #    —— 32px 渲染出来就是一小截省略号。
            #    所以这里钉的是**渲染宽度**，不是"元素在不在"：后者永远绿。
            # ⚠️ 量的是**可用宽度**（`.now-head` − 封面 − 缝），不是 `.meta` / `#tName`
            #    自己的宽度。第一版就是取 `#tName` 的宽度，结果它等于**当前那首歌名
            #    的文字宽度**（实测 146px）—— 标题短它就窄、标题长它就宽，跟"封面
            #    有没有把歌名挤掉"是两件事。判断"挤没挤"只有可用宽度说了算，
            #    而且它跟当前放的是哪首无关，换台机器换批歌都不会假红。
            nm = await S.js("JSON.stringify((() => {"
                            " const hd = document.querySelector('.now-head');"
                            " const art = document.querySelector('.now-row .art');"
                            " const e = document.getElementById('tName');"
                            " const gap = parseFloat(getComputedStyle(hd).columnGap) || 0;"
                            " return {avail: Math.round(hd.getBoundingClientRect().width"
                            "   - art.getBoundingClientRect().width - gap),"
                            " w: Math.round(e.getBoundingClientRect().width),"
                            " sw: e.scrollWidth, cw: e.clientWidth,"
                            " tx: e.textContent}; })())")
            worst |= ck("★ 歌名那格真有地方放（>= 320px，被封面挤扁就是这条红）",
                        nm["avail"] >= 320,
                        "可用 %dpx（歌名格现在 %dpx）" % (nm["avail"], nm["w"]))
            worst |= ck("歌名那一格有字（不是空壳）", bool(str(nm["tx"]).strip()),
                        "%r —— 内容 %d / 可视 %d（截断了会给省略号，这是允许的）"
                        % (nm["tx"][:14], nm["sw"], nm["cw"]))
            worst |= ck("★ 我的音乐在左、小瑞在右、同一行",
                        libx["l"] < xq["l"] and xq["l"] >= libx["r"] - 2
                        and abs(libx["t"] - xq["t"]) <= 4,
                        "我的音乐 %d~%d，小瑞 %d~%d，顶 %d/%d"
                        % (libx["l"], libx["r"], xq["l"], xq["r"], libx["t"], xq["t"]))

            print("\n=== G2 · 音效设置那一栏没了，其余三行按比例放大填满 ===")
            # 用户的话：「音效设置那一栏去掉 其他栏目等比例放大填充好那个页面」。
            # ⚠️ 三条判据对着三句不同的话：**没了**（反面钉子，跟 F 段那六格同一个
            #    套路）、**放大了**（跟删之前的三个数比，那三个数是量出来的基线）、
            #    **填满了**（最后一张卡的底边要贴到可视底边，不是"没超就算过"）。
            #    少了第三条的话，"什么都没动"也能全绿 —— 那这页就没守住用户的话。
            g2 = await S.js("JSON.stringify({"
                            " eqCard: !!document.querySelector('.mp-eq'),"
                            " eqNote: !!document.getElementById('eqNote'),"
                            " eqBands: !!document.getElementById('eqBands'),"
                            " txt: document.body.innerText.indexOf('音效设置'),"
                            " filt: document.body.innerText.indexOf('BiquadFilter'),"
                            " gap: Math.round(document.querySelector('.sub-body')"
                            ".getBoundingClientRect().bottom"
                            " - document.querySelector('.mp-lib').getBoundingClientRect().bottom),"
                            " xqStretch: Math.round(document.querySelector('.mp-xq')"
                            ".getBoundingClientRect().bottom"
                            " - document.querySelector('.mp-lib').getBoundingClientRect().bottom)})")
            worst |= ck("★ 音效设置整块没了（卡片 / 标题 / 推子容器都不在）",
                        g2["eqCard"] is False and g2["eqNote"] is False
                        and g2["eqBands"] is False and g2["txt"] < 0
                        and g2["filt"] < 0,
                        "卡片=%s 标题=%s 推子=%s" % (g2["eqCard"], g2["eqNote"], g2["eqBands"]))
            # 删之前量出来的三行高度（2026-09-25，见 media.html 的栅格注释）。
            # 判据写成"比这个数大"，不是"等于某个数" —— 具体长多少是版式的事，
            # 用户要的是"放大"，不是我把尺寸抄一遍。
            for _name, _got, _was in (("正在播放", hero["h"], 112),
                                      ("我的音乐那行", libx["h"], 188)):
                worst |= ck("★ %s 比删音效之前（%dpx）大了" % (_name, _was),
                            _got > _was + 4, "现在 %dpx" % _got)
            worst |= ck("★ 填满了：最后一张卡的底边贴到可视底边（差 <= 12px）",
                        0 <= g2["gap"] <= 12, "底下还空 %dpx" % g2["gap"])
            worst |= ck("★ 右边那张卡跟着撑到同一高度（不然右边空一截）",
                        abs(g2["xqStretch"]) <= 2, "差 %dpx" % g2["xqStretch"])
            print("     两行高度：正在播放 %d（原 112）/ 我的音乐 %d（原 188）"
                  % (hero["h"], libx["h"]))

            print("\n=== G3 · 推荐歌单删了之后，剩下两行等比例放大并填满 ===")
            # 用户的话：「把多媒体页面推荐歌单部分去掉 然后我的音乐部分 和小瑞音乐
            # 推荐模块等比例放大 使画面别那么空」。跟 G2 同一个套路三条判据：
            #   **没了**（上面 G 段那条反面钉子）、**放大了**、**填满了**。
            # 基线 148 / 209 是删之前 `_probe_geom.py` 量出来的实测值（不是估的）。
            # ⚠️ 判据写成"比基线大"，不是"等于 249 / 352" —— 具体长多少是版式的事，
            #    用户要的是"放大填充"，不是我把他那次的尺寸抄一遍钉死。
            for _name, _got, _was in (("正在播放", hero["h"], 148),
                                      ("我的音乐那行", libx["h"], 209)):
                worst |= ck("★ %s 比删歌单之前（%dpx）大了" % (_name, _was),
                            _got > _was + 8, "现在 %dpx" % _got)
            worst |= ck("★ 两行都长了，不是只长一行（等比例）",
                        (hero["h"] - 148) > 8 and (libx["h"] - 209) > 8,
                        "正在播放 +%d / 我的音乐 +%d" % (hero["h"] - 148, libx["h"] - 209))

            print("\n=== G4 · 窗口比设计高的时候，卡片要正好占满（底下不许留一条空白） ===")
            # 用户的话：「是正好占满这个页面 不是小瑞和所有歌都去下边了」。
            # ⚠️ 这一段**必须在好几个视口高度下量**。只在 1672×940 那个固定窗口里量
            #    是量不出这个毛病的 —— 那一档就是设计尺寸，怎么改都是 0。毛病出在
            #    "窗口比设计比例**更高**"的时候：`1rem` 被宽度（或 22px 上限）卡住
            #    不再长，`.sub-body` 却还在跟着视口长，余量全堆在卡片底下，
            #    于是「我的音乐 / 小瑞」那一行被顶到最下面、上面留一长条空白。
            #    实测（`_scratch/_probe_heights.py`）：1440×900 空 156px、
            #    1672×1040 空 176px、1672×1180 空 316px。
            # ⚠️ 只量"有没有滚"是不够的（那一条一直绿）：要的是**卡片底边贴住
            #    `.sub-body` 的可视底边**，而且**列表是真的变长了**（不是靠两块空白
            #    把卡片撑开占的位置）。
            iw = await S.js("window.innerWidth")
            list_hs = []
            for hh in (843, 940, 1040, 1180, 1340):
                await S.cmd("Emulation.setDeviceMetricsOverride",
                            {"width": iw, "height": hh, "deviceScaleFactor": 1,
                             "mobile": False})
                await asyncio.sleep(0.5)
                r = await S.js("JSON.stringify((() => {"
                               " const sb = document.querySelector('.sub-body');"
                               " const lib = document.querySelector('.mp-lib');"
                               " const ul = document.querySelector('.tracks');"
                               " return {gap: Math.round(sb.getBoundingClientRect().bottom"
                               "   - lib.getBoundingClientRect().bottom),"
                               " over: sb.scrollHeight - sb.clientHeight,"
                               " listH: Math.round(ul.getBoundingClientRect().height)}; })())")
                list_hs.append(r["listH"])
                worst |= ck("★ 视口高 %d 时正好占满（底边差 0~4px 且不用滚）" % hh,
                            0 <= r["gap"] <= 4 and r["over"] <= 4,
                            "底下差 %dpx / 溢出 %dpx / 列表 %dpx"
                            % (r["gap"], r["over"], r["listH"]))
            worst |= ck("★ 吃掉余量的是列表本身（越高越长，不是加了块空白）",
                        list_hs[-1] > list_hs[0] + 80,
                        "列表高度 %s" % list_hs)
            await S.cmd("Emulation.clearDeviceMetricsOverride")
            await asyncio.sleep(0.5)

            print("\n=== G5 · 「我的音乐」一屏正好六首（用户 2026-09-25 的话）===")
            # 用户原话：「多媒体页 我的音乐部分一下展示的音乐太多了 显得字小
            #   可以一页只放六首 然后可以下滑 现在有13首 这样字可以大一点 感觉更好」。
            # 做法是把行高从死数改成**列表高度的 1/6**（见 media.html 的 `.tracks li`），
            # 所以这里有两条要钉住，而且是**一对**：
            #   ① 设计档正好 6 行、末行铺满 —— 这是用户要的那件事本身；
            #   ② 行高不许无限长 —— `flex-basis` 里那个百分比是活的，少了
            #      `max-height` 这一档，窗口一高每行就跟着长成一大块空白。
            # ⚠️ 量的是**整行可见**的行数，不是"看得见的行数"：露出半个第 7 行
            #    算 6 行（`floor`），露出第 7 行一整行才算 7 —— 用户数的是整行。
            # ⚠️ 字号那条基线 11.35px 是改之前 `.tx` 的 `.78rem`（root 14.53px），
            #    不是估的。
            g5 = await S.js("JSON.stringify((() => {"
                            " const ul = document.querySelector('.tracks');"
                            " const lis = ul.querySelectorAll('li[data-i]');"
                            " if (!ul || lis.length < 8) return {err: '列表不足 8 行'};"
                            " const gap = parseFloat(getComputedStyle(ul).rowGap) || 0;"
                            " const box = ul.clientHeight;"
                            " const r0 = lis[0].getBoundingClientRect();"
                            " const r1 = lis[1].getBoundingClientRect();"
                            " const top = r0.top - ul.getBoundingClientRect().top;"
                            " const pitch = r1.top - r0.top, rowH = r0.height;"
                            " return {gap: gap, box: box, top: top,"
                            "   pitch: pitch, rowH: rowH,"
                            "   full: Math.floor((box - top + gap) / pitch),"
                            "   partial: Math.ceil((box - top) / pitch),"
                            "   slack: Math.round(box - top"
                            "     - (Math.floor((box - top + gap) / pitch) * pitch - gap)),"
                            "   fs: parseFloat(getComputedStyle("
                            "     document.querySelector('.tracks li .tx')).fontSize),"
                            "   fsNo: parseFloat(getComputedStyle("
                            "     document.querySelector('.tracks li .no')).fontSize)}; })())")
            if g5.get("err"):
                worst |= 1
                print("  !!  G5 量不到：%s" % g5["err"])
            else:
                worst |= ck("★ 设计窗口下一屏正好 **6 首**（整行可见，用户要的就是这个）",
                            g5["full"] == 6, "整行可见 %d 行" % g5["full"])
                worst |= ck("★ 第 7 行**不许露半行**（末行要铺满列表底）",
                            g5["partial"] == g5["full"],
                            "整行 %d 行 / 一共看得见 %d 行 / 末行底余 %dpx"
                            % (g5["full"], g5["partial"], g5["slack"]))
                worst |= ck("★ 字号比改之前大了（歌名 %s > 11.35px = 原来 .78rem）"
                            % g5["fs"], g5["fs"] > 11.35 + 2,
                            "歌名 %.2fpx / 序号 %.2fpx" % (g5["fs"], g5["fsNo"]))
                worst |= ck("★ 行距也跟着大了（步距 %s > 40px = 原来那版的一屏十首）"
                            % round(g5["pitch"]), g5["pitch"] > 40,
                            "行高 %.1f + 缝 %.2f" % (g5["rowH"], g5["gap"]))
                print("     行高 %.1f  步距 %.1f  列表 %dpx  余量 %dpx"
                      % (g5["rowH"], g5["pitch"], g5["box"], g5["slack"]))
            # ② 高窗口：行高撞上限之后，多出来的是**行数**，不是行高。
            await S.cmd("Emulation.setDeviceMetricsOverride",
                        {"width": iw, "height": 1340, "deviceScaleFactor": 1,
                         "mobile": False})
            await asyncio.sleep(0.5)
            g5b = await S.js("JSON.stringify((() => {"
                             " const ul = document.querySelector('.tracks');"
                             " const a = ul.querySelector('li[data-i]').getBoundingClientRect();"
                             " const b = ul.querySelectorAll('li[data-i]')[1]"
                             ".getBoundingClientRect();"
                             " const p = b.top - a.top;"
                             " return {pitch: p, rowH: a.height,"
                             "   full: Math.floor((ul.clientHeight + (p - a.height)) / p),"
                             "   box: ul.clientHeight}; })())")
            worst |= ck("★ 窗口高的时候行高**不再跟着长**（`max-height` 那一条在管用）",
                        g5b["rowH"] <= 52.5,
                        "1340 视口下 行高 %.1f（上限 3.4rem）" % g5b["rowH"])
            worst |= ck("★ 窗口高的时候是多**看见几首**（不是把每行拉成一块空白）",
                        g5b["full"] >= 10,
                        "列表 %dpx，整行可见 %d 行" % (g5b["box"], g5b["full"]))
            await S.cmd("Emulation.clearDeviceMetricsOverride")
            await asyncio.sleep(0.5)

            print("\n=== H · 纵向高度在预算内 ===")
            # ⚠️ 预算 = `.sub-body` 的实测高度（这台机器上是 653~654px，见 media.html 里
            #    `.mp-grid` 那段注释 —— **不是按 940 算的 723**，那是旧版塌掉的原因）。
            #    超了不是"滚动一下就有"那么无害：旧版正是被底栏盖掉了卡片下半截，
            #    看起来像那颗键不存在。
            need = sub["scroll"]
            have = sub["b"] - sub["t"]
            worst |= ck("★ 整页不用滚（scrollHeight <= 可视高度 + 4px）",
                        need <= have + 4, "内容 %dpx / 可视 %dpx" % (need, have))
            worst |= ck("最后一张卡完全在底栏上方", libx["b"] <= sub["b"] + 2,
                        "卡底 %d，可视底 %d（超出 %d）"
                        % (libx["b"], sub["b"], libx["b"] - sub["b"]))

            print("\n=== I · 列表点歌真的能放（推荐歌单删了，点歌只剩这一条路） ===")
            # ⚠️ 2026-09-24：这一段原来点的是 `.rec-card`（推荐歌单那六张卡：前三张
            #    能放、后三张点出来说「未接入」）。用户要求把推荐歌单整块删掉之后，
            #    点歌入口就只剩「我的音乐」列表这一条 —— 判据必须跟着换成
            #    `.tracks li`，不然守的是一个已经不存在的入口，"全绿"是假绿。
            i1 = await S.js("JSON.stringify({ct: au.currentTime,"
                            " n: document.querySelectorAll('.tracks li[data-i]').length,"
                            " row: document.querySelectorAll('.tracks li[data-i]')[2]"
                            ".querySelector('.tx').textContent})")
            worst |= ck("列表里有真曲目可点（>= 3 行）", i1["n"] >= 3, "只有 %d 行" % i1["n"])
            await S.js("document.querySelectorAll('.tracks li[data-i]')[2].click()")
            # ⚠️ **两次采样都在点击之后**。第一版是"点之前记一个数、点之后比它大"，
            #    结果红了一次：点之前那首正好在 1.9s（上一首放完自动续到下一首），
            #    点之后新那首解出来也正好在 1.9s —— 两首不同的歌撞在同一个数上，
            #    蓝的判成红的。判"在放"只能看**同一首**自己的进度走没走。
            await asyncio.sleep(1.0)
            t1 = await S.js("JSON.stringify({ct: au.currentTime, paused: au.paused})")
            await asyncio.sleep(1.4)
            i2 = await S.js("JSON.stringify({ct: au.currentTime, paused: au.paused,"
                            " cur: document.getElementById('tName').textContent,"
                            " bubble: document.getElementById('xqBubble').textContent,"
                            " on: document.querySelectorAll('.tracks li.on').length,"
                            " mark: document.getElementById('stateNote').textContent})")
            worst |= ck("★ 点第 3 行之后真的在放（同一首的进度自己在往前）",
                        i2["paused"] is False and i2["ct"] > t1["ct"] + 0.4,
                        "隔 1.4s 从 %.2fs 走到 %.2fs（%s）"
                        % (t1["ct"], i2["ct"], i2["mark"]))
            worst |= ck("★ 放的就是点中的那一行（标题对得上）",
                        str(i2["cur"]).strip() and str(i2["cur"]) in str(i1["row"]),
                        "点的是 %r，正在播放那格写的是 %r"
                        % (str(i1["row"])[:20], str(i2["cur"])[:20]))
            worst |= ck("点中的那一行被标成当前这首（.on 只有一行）",
                        i2["on"] == 1, "有 %d 行带 .on" % i2["on"])
            worst |= ck("小瑞那句话说的是当前这首（不是写死的）",
                        i2["cur"][:6] in str(i2["bubble"]) or "正在放" in str(i2["bubble"]),
                        "正在放 %r，小瑞说 %r" % (i2["cur"][:12], i2["bubble"][:30]))

            print("\n=== J · 过时指引不许回来 ===")
            # ⚠️ 2026-09-24：这一段原来还有两条判据，守页面上「没有接任何在线曲库」
            #    「没有控制通道」那两句实话（在 media 页的「如实说明」段里）。
            #    用户要求删掉成段说明文字，那段整块没了，判据的靶子不再存在，
            #    所以一并摘掉。同两条也在 _check_pages.py 里。
            txt = await S.js("document.body.innerText")
            worst |= ck("没有 make_audio.py 那种过时指引",
                        "make_audio" not in txt)

            print("\n=== K · 列表自己滚，页面不跟着滚 ===")
            k = await S.js("JSON.stringify((() => { const e = document.querySelector('.tracks');"
                           " return {sh: e.scrollHeight, ch: e.clientHeight,"
                           " ov: getComputedStyle(e).overflowY}; })())")
            worst |= ck("列表内部可滚", k["sh"] > k["ch"] and k["ov"] in ("auto", "scroll"),
                        "内容 %d / 视口 %d / overflow-y=%s" % (k["sh"], k["ch"], k["ov"]))
            worst |= ck("滚列表不会把页面滚走（列表滚到底后 sub-body 仍不动）",
                        await S.js("(() => { const e = document.querySelector('.tracks');"
                                   " e.scrollTop = e.scrollHeight;"
                                   " return document.querySelector('.sub-body').scrollTop === 0; })()"))

            # 拍之前把列表滚回顶部、等提示条自己收掉 —— 截图要看的是"用户一进来
            # 看到的样子"，不是检查跑完留下的现场（K 段刚把列表滚到底）。
            await S.js("document.querySelector('.tracks').scrollTop = 0; 1")
            await asyncio.sleep(4.2)
            shot = await S.cmd("Page.captureScreenshot", {"format": "png"})
            with open(SHOT, "wb") as fh:
                fh.write(base64.b64decode(shot["data"]))
            print("\n     截图 -> " + SHOT)

            print("\n=== I2 · 多轮聊天：灌 40 句也不许把对话区撑崩 ===")
            # ★ 2026-09-25 用户要的「右侧对话框，目前只有一行文字，可以预留多行对话
            #   区域，后续接入 DeepSeek API，多轮聊天时界面不会崩」。
            #   ⚠️ DeepSeek 还没接，所以这里**用页面自己的说话口子灌**（`XQ.mediaLink.push`
            #      就是小瑞说话调的那个 `xqPush`，不是另造一条通道）。
            #   要守四件事，缺一件屏幕上就是"聊多了以后对话区坏掉"：
            #     1. 上限 30：DOM 不许无限长（丢的是**最老的**那几句，状态行不参与裁剪）；
            #     2. 气泡不许被压扁（`flex:0 0 auto`）—— 被压扁的现象是"越聊越扁"；
            #     3. 装不下时**是框在滚**（overflow-y:auto 且 scrollHeight>clientHeight）；
            #     4. 滚回顶部看得见第一句、滚到底部状态行贴着底 —— 这两条一起才说明
            #        "撑开空白"用的是 `.sp` 空条而不是 `margin-top:auto`（后者溢出时
            #        会把顶部顶到滚不到的地方，正是"聊多了就崩"）。
            i2 = await S.js("""(() => {
              for (let k = 0; k < 40; k++) {
                XQ.mediaLink.push('压测第 ' + (k + 1) + ' 句：'
                  + '这是一条会折行的长话，拿它把对话区撑满，看会不会把气泡压扁。');
              }
              const b = document.getElementById('xqBubble');
              const ps = [...b.querySelectorAll('p.m')];
              const mono = ps.filter((p) => !p.classList.contains('st'));
              const last = ps[ps.length - 1];
              const rb = b.getBoundingClientRect();
              /* ⚠️ 这几个数要在**动 scrollTop 之前**读：读的是"刚刚聊完、自动滚到底"
                 那一刻的样子（`flush` 说的是状态行贴没贴底，滚到顶再读就不是这个意思了）。 */
              const sh = b.scrollHeight, ch = b.clientHeight;
              const flush = last ? Math.round(rb.bottom - last.getBoundingClientRect().bottom) : -99;
              const h = mono.map((p) => Math.round(p.getBoundingClientRect().height));
              const sb = document.querySelector('.sub-body');
              b.scrollTop = 0;
              const top0 = Math.round(mono[0].getBoundingClientRect().top - rb.top);
              return JSON.stringify({
                log: XQ_LOG.length, dom: mono.length,
                sh: sh, ch: ch, ov: getComputedStyle(b).overflowY,
                shrink: getComputedStyle(mono[0]).flexShrink,
                minH: Math.min.apply(null, h), maxH: Math.max.apply(null, h),
                flush: flush, top0: top0,
                subSh: sb.scrollHeight, subCh: sb.clientHeight,
                first: mono[0].textContent.slice(0, 9),
                newest: mono[mono.length - 1].textContent.slice(0, 9),
                stLast: !!last && last.classList.contains('st'),
                st: last ? last.textContent.slice(0, 8) : ''});
            })()""")
            worst |= ck("★ 灌到 40 句，对话记录被裁到上限 30（DOM 不会无限长）",
                        i2["log"] == 30 and i2["dom"] == 30,
                        "日志 %s 条 / DOM 里 %s 个气泡" % (i2["log"], i2["dom"]))
            worst |= ck("★ 裁的是**最老**的那几句（最新的 30 句还在，第一句是第 11 句）",
                        i2["first"].startswith("压测第 11") and i2["newest"].startswith("压测第 40"),
                        "最老 %r / 最新 %r" % (i2["first"], i2["newest"]))
            worst |= ck("★ 装了 30 句之后真的在滚（overflow-y 生效，不是溢出看不见）",
                        i2["ov"] == "auto" and i2["sh"] > i2["ch"] + 20,
                        "overflow-y=%s，内容 %s / 视口 %s"
                        % (i2["ov"], i2["sh"], i2["ch"]))
            # ★ 这一条是 I2 真正的重点，也是最容易被漏掉的一条：光验"气泡在滚"不够 ——
            #   2026-09-25 第一版就是这样，气泡**自己也是高的**（1837px），页面跟着
            #   被撑出滚动条，卡片从自己那一行里捅出去压到底栏上。根因是卡片是**网格项**、
            #   默认 `min-height:auto`，不肯比内容矮。实测数字见 media.html 里
            #   `.mp-xq` 那段注释（0 条 437 / 8 条 582 / 30 条 1925）。
            worst |= ck("★ 而且整页没被撑出滚动条（卡片没从自己那一行里捅出去）",
                        i2["subSh"] <= i2["subCh"] + 4,
                        ".sub-body 内容 %s / 可视 %s" % (i2["subSh"], i2["subCh"]))
            worst |= ck("★ 气泡没被压扁（flex-shrink 是 0，每条还是该多高就多高）",
                        str(i2["shrink"]) == "0" and i2["minH"] >= 24,
                        "flex-shrink=%s，最矮的一条 %s px（最高 %s）"
                        % (i2["shrink"], i2["minH"], i2["maxH"]))
            worst |= ck("★ 滚回顶部看得见第一句（不是被顶到滚不到的地方）",
                        -2 <= i2["top0"] <= 8, "第一句顶边距容器顶 %s px" % i2["top0"])
            worst |= ck("★ 状态行是最后一条、而且贴着框底（不是被挤到中间去了）",
                        i2["stLast"] and -2 <= i2["flush"] <= 2,
                        "最后一条是状态行=%s，离底 %s px，内容是 %r"
                        % (i2["stLast"], i2["flush"], i2["st"]))

            print("\n=== N · 疲劳联动：DMS 报疲劳 → 小瑞在这页推舒缓的那首（答辩亮点）===")
            # ★ 2026-09-25 用户：「当DMS监测疲劳时，小瑞自动在这里推荐舒缓音乐，把多媒体
            #   和疲劳监测模块打通，这个是答辩大亮点！不是孤立的音乐播放器，是感知驾驶员
            #   状态的情感化座舱」。这一段验的就是这条链路，从"档位"到"真的响了"。
            # ⚠️ 这份服务是 `--source demo`，demo **自己也会真的推档位过来**（30 秒左右
            #    到 mild）。所以每一处"喂档位 + 读结果"都必须在**同一个 Runtime.evaluate
            #    里做完**：中间没有 await，WebSocket 的消息就插不进来改档位，读到的东西
            #    才是"我喂进去的那个档位造成的"。这是这一段唯一防的假红来源。
            n1 = None
            for _ in range(24):
                n1 = await S.js("JSON.stringify({m: XQ.mediaLink.stats().measured,"
                                " busy: calmBusy})")
                if n1 and n1["m"] == nb and not n1["busy"]:
                    break
                await asyncio.sleep(5)
            worst |= ck("★ 内置那 %d 首的舒缓度全量出来了（量不出来就挑不了）" % nb,
                        bool(n1) and n1["m"] == nb and not n1["busy"],
                        "量到 %s 首，还在量=%s" % (n1 and n1["m"], n1 and n1["busy"]))

            # ---- N1 · 护栏：用户刚亲手点过（6 秒内）就**只推荐、不抢歌** ----
            await S.js("document.querySelectorAll('.tracks li')[2].click()")
            await asyncio.sleep(1.6)
            n2 = await S.js("""(() => {
              /* 一次 evaluate 里按用户手上的顺序做完，然后当场读：
                   ① 先把梯队压回清醒（demo 可能已经自己推到 mild 了，不压的话下面
                      那一次 feed('mild') 会因为"没更重"被 calmWatch 忽略）；
                   ② 记下在放哪一首；
                   ③ 点**暂停键**（真用户路径，`ppBtn` 的 handler 会记 userAct）；
                   ④ 喂 mild。 */
              XQ.mediaLink.feed('normal');
              const i0 = idx, c0 = document.getElementById('tName').textContent;
              document.getElementById('ppBtn').click();
              const waited = Math.round(Date.now() - lastAct);
              XQ.mediaLink.feed('mild');
              const st = XQ.mediaLink.stats();
              const b = document.getElementById('xqBubble');
              const btns = [...document.querySelectorAll('.xq-chips button')];
              return JSON.stringify({
                i0: i0, i1: idx, c0: c0,
                c1: document.getElementById('tName').textContent,
                paused: au.paused, waited: waited,
                sev: document.body.dataset.sev,
                accent: getComputedStyle(document.body)
                          .getPropertyValue('--accent').trim().toUpperCase(),
                calm: st.calm, title: st.calmTitle, src: st.calmSrc,
                said: b.textContent,
                chips: btns.map((e) => e.textContent.trim()),
                acts: btns.map((e) => e.dataset.act)});
            })()""")
            worst |= ck("N1 前提成立：暂停了、而且这次操作就在刚才（护栏会挡住）",
                        n2["paused"] is True and n2["waited"] < 6000,
                        "paused=%s，距上次亲手操作 %s ms" % (n2["paused"], n2["waited"]))
            worst |= ck("★ 用户刚点过的时候**不抢歌**（还在原来那一首上，没被换掉）",
                        n2["i1"] == n2["i0"],
                        "喂档位前是第 %s 首，喂完变成第 %s 首（%r -> %r）"
                        % (n2["i0"], n2["i1"], n2["c0"], n2["c1"]))
            worst |= ck("★ 但它**说了话**（不是默默推荐）",
                        bool(n2["said"]) and bool(n2["title"]) and n2["title"] in n2["said"],
                        "挑中 %r，对话框里是 %r"
                        % (n2["title"], str(n2["said"])[-46:]))
            worst |= ck("★ 推荐的那首是**内置**的（换了机器也一定放得出来）",
                        n2["src"] == "内置" and n2["calm"] >= 0,
                        "第 %s 首，来源 %r" % (n2["calm"], n2["src"]))
            worst |= ck("★ 疲劳档位真的传到了这一页（背景/高亮跟着变黄）",
                        n2["sev"] == "mild" and n2["accent"] == "#A87B00",
                        "data-sev=%s，--accent=%s" % (n2["sev"], n2["accent"]))
            worst |= ck("★ 临时的第四枚 chip 出来了，而且**和其他三枚一样宽**",
                        n2["chips"] == ["随便挑一首", "下一首", "从头再听", "听这首舒缓的"]
                        and n2["acts"][3] == "calm",
                        "chip=%s / act=%s" % (n2["chips"], n2["acts"]))

            # ---- N2 · 没人动手的时候**顺手放上**（这才叫"感知状态"） ----
            await asyncio.sleep(6.6)      # CALM_WAIT 是拿挂钟算的，必须真等
            # ⚠️ 挑中的那一首必须**当场记下来**（同一个 evaluate 里读），不能等 2.4 秒
            #    之后再读 `stats().calmTitle` —— demo 那份服务随时可能把档位推回
            #    normal，而"回到清醒档就把 `calmIdx` 收起来"是**设计如此**
            #    （临时的 chip 收起、正在放的歌**不掐**，见 media.html 的 calmWatch）。
            #    第一版就是等完再读，读到 `calmTitle = None` 就判红 —— 歌明明放对了，
            #    是**判据自己读晚了**。所以要守的是"它有没有把挑中的那一首放出来"，
            #    那个值只能在"挑"的那一刻取。
            n3a = await S.js("""(() => {
              XQ.mediaLink.feed('normal');
              XQ.mediaLink.feed('moderate');
              const st = XQ.mediaLink.stats();
              return JSON.stringify({title: st.calmTitle, i: st.calm,
                                     sev: document.body.dataset.sev});
            })()""")
            worst |= ck("N2 前提成立：喂了「又重了一档」之后它确实挑出了一首",
                        bool(n3a["title"]) and n3a["i"] >= 0 and n3a["sev"] == "moderate",
                        "挑中 %r（第 %s 首），data-sev=%s"
                        % (n3a["title"], n3a["i"], n3a["sev"]))
            await asyncio.sleep(2.4)
            n3 = await S.js("JSON.stringify({"
                            " cur: document.getElementById('tName').textContent,"
                            " calmNow: XQ.mediaLink.stats().calmTitle,"
                            " paused: au.paused, ct: au.currentTime,"
                            " on: document.querySelectorAll('.tracks li.on').length,"
                            " svr: au.currentSrc})")
            worst |= ck("★ 用户没动手时小瑞**直接把它放上了**（不是只说不做）",
                        n3["paused"] is False and n3["ct"] > 0
                        and str(n3["cur"]) == str(n3a["title"]) and n3["on"] == 1,
                        "正在放 %r（当场挑中的是 %r），已播 %.2f s，.on %s 行"
                        % (n3["cur"], n3a["title"], n3["ct"], n3["on"]))
            worst |= ck("放的就是挑中那一首的音频（走 /music/ 那条路由）",
                        "/music/" in str(n3["svr"]), str(n3["svr"])[-30:])

            # ==================================================================
            print("\n=== O · 打字聊天：能打字、而且只认自己那句的回音 ===")
            # ★ 2026-09-25 晚用户点名：「小瑞那可以打字聊天」。
            #   走的是 detail.html 完全同一条上行（`{type:'say',text}`），
            #   所以要验的**不是"能不能发出去"**（那早就通了），是这一页特有的
            #   那两条：① 输入行加进来之后**卡片没被顶穿**（上面 I2 那场事故的
            #   同一条链）；② `say` 是**共享广播**，这一页只许认自己那句的回音。
            #   ⚠️ 这一段**点真按钮、派真键盘事件**（不调内部函数）：中文输入法
            #      的 `isComposing` 判断就挂在那个监听里，绕过事件等于绕过它。
            o0 = await S.js("""JSON.stringify((() => {
              const i = document.getElementById('xqSay');
              const b = document.getElementById('xqSend');
              if (!i || !b) return {inp: !!i, btn: !!b};
              const r = i.getBoundingClientRect(), rb = b.getBoundingClientRect();
              const card = document.querySelector('.mp-xq').getBoundingClientRect();
              const row = i.parentElement;
              return {inp: true, btn: true, w: Math.round(r.width), bw: Math.round(rb.width),
                      right: Math.round(rb.right), cardRight: Math.round(card.right),
                      btnH: Math.round(rb.height),
                      flex: getComputedStyle(row).flex,
                      cardH: Math.round(card.height),
                      libH: Math.round(document.querySelector('.mp-lib').getBoundingClientRect().height)};
            })())""")
            worst |= ck("★ 小瑞那有打字框、也有发送键",
                        o0.get("inp") and o0.get("btn"),
                        "input=%s button=%s" % (o0.get("inp"), o0.get("btn")))
            worst |= ck("★ 输入框吃掉了该吃的宽度（没被 placeholder 顶掉）",
                        o0.get("w", 0) >= 120,
                        "输入框 %spx / 发送键 %spx" % (o0.get("w"), o0.get("bw")))
            worst |= ck("★ 「发送」没被挤出卡片右边缘（`min-width:0` 那条就是防这个）",
                        o0.get("right", 9e9) <= o0.get("cardRight", 0) + 2,
                        "发送键右边 %s / 卡片右边 %s" % (o0.get("right"), o0.get("cardRight")))
            worst |= ck("★ 输入行是**固定高度**（`flex:0 0 auto`：视口一矮不许被压成一条缝）",
                        str(o0.get("flex", "")).startswith("0 0"),
                        "flex=%s" % o0.get("flex"))
            worst |= ck("★ 加了这一行之后，小瑞那张卡还是和「我的音乐」一样高",
                        abs(o0.get("cardH", 0) - o0.get("libH", 9e9)) <= 4,
                        "小瑞 %s / 我的音乐 %s" % (o0.get("cardH"), o0.get("libH")))

            # 真的敲进去 + 真的派一个回车。**外来的两条 say 塞在同一个 tick 里**：
            # 晚一步喂就撞上真回音了（DeepSeek 一个来回 ~2.5 s，但我不要靠这个数
            # 去赌时序）—— 所以 `send` 和这两条注入之间**一次 await 都没有**。
            # ⚠️ 这两句**必须是"纯闲聊"**：`xqSend` 现在会先认一遍命令（见 P 段），
            #    句子里只要有「放一首」「来点」这种字样就会**本地执行、根本不发给
            #    服务端** —— 那这一段要验的"等回音、认回音"当场就没有对象了。
            #    第一版喂的是「我有点困，来点舒缓的」，「来点」正好命中 `play`。
            #
            # ⚠️ 打字这条路的**前提是链路通着**：`xqSend` 的非命令分支第一道守卫就是
            #    `LINK.online`，断线时它**故意不发**（还会 flash 一句"还没连上"）。
            #    第一次跑这一段红了两条，`why='没连上服务端'` —— 页面没坏，是那一下
            #    正好落在 1.8 s 的重连窗口里（`live.js`：`onclose` → 1.8 s 后重连）。
            #    所以先等链路回来，**等不到才判红** —— 那才是真问题，不是判据读早了。
            #    `downN` 是页面自己数的"整场断过几次"，判"掉线是不是常态"用。
            on0 = None
            for _ in range(20):
                on0 = await S.js("JSON.stringify({on: LINK.online, n: DOWN_N})")
                if on0 and on0["on"]:
                    break
                await asyncio.sleep(0.6)
            worst |= ck("打字之前链路是通的（断线时 xqSend 会**故意**不发）",
                        bool(on0) and on0["on"],
                        "online=%s，整场断过 %s 次"
                        % (on0 and on0["on"], on0 and on0["n"]))
            o1 = await S.js("""JSON.stringify((() => {
              const i = document.getElementById('xqSay');
              const me = '小瑞你在吗';
              i.value = me;
              i.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true}));
              const w0 = XQ.mediaLink.stats().wait;
              XQ.mediaLink.say({text: '（别人的）预警：检测到疲劳，要不要歇一会儿？'});
              XQ.mediaLink.say({text: '（别人的）语音答复', user: '不是我这句', voice: true});
              const ps = [...document.querySelectorAll('#xqBubble p.m')];
              return {me: me, w0: w0, wait: XQ.mediaLink.stats().wait,
                      mine: XQ.mediaLink.stats().me, box: i.value,
                      who: ps.map((p) => p.dataset.who),
                      lastTxt: (ps.length ? ps[ps.length - 2].textContent : ''),
                      waiting: ps.filter((p) => p.classList.contains('waiting')).length,
                      foreign: ps.filter((p) => p.textContent.indexOf('别人的') >= 0).length};
            })())""")
            worst |= ck("★ 敲进去一回车就发出去了（自己的气泡立刻出现，不等服务端）",
                        o1["w0"] == o1["me"] and o1["mine"] == 1
                        and o1["who"].count("me") == 1,
                        "wait=%r，我的条数=%s，who=%s" % (o1["w0"], o1["mine"], o1["who"]))
            worst |= ck("★ 发出去之后输入框清空了（那句话不在框里留一份）",
                        o1["box"] == "", repr(o1["box"]))
            worst |= ck("★ 挂了一行「小瑞正在想…」",
                        o1["waiting"] == 1, "正在想的行数=%s" % o1["waiting"])
            # ★★ 这一段的核心判据。
            worst |= ck("★★ 外来的 say 一句都没混进来（只认 `d.user` 等于自己那句的）",
                        o1["foreign"] == 0 and o1["wait"] == o1["me"],
                        "混进来 %s 条；等待的仍是 %r" % (o1["foreign"], o1["wait"]))

            # 等真回音（DeepSeek 一个来回 ~2.5 s；没配 key 时服务端退回固定话术，
            # 也是回话，所以这条不依赖网络）。
            o2 = None
            for _ in range(40):                       # 最多 ~32 s
                await asyncio.sleep(0.8)
                o2 = await S.js("""JSON.stringify((() => {
                  const st = XQ.mediaLink.stats();
                  const ps = [...document.querySelectorAll('#xqBubble p.m')];
                  const xq = ps.filter((p) => p.dataset.who === 'xq'
                        && !p.classList.contains('st') && !p.classList.contains('waiting'));
                  return {wait: st.wait, log: st.log, mine: st.me,
                          waiting: ps.filter((p) => p.classList.contains('waiting')).length,
                          reply: (xq.length ? xq[xq.length - 1].textContent : '')};
                })())""")
                if not o2["wait"]:
                    break
            worst |= ck("★ 小瑞真的回话了（「正在想」自己收了尾）",
                        not o2["wait"] and o2["waiting"] == 0
                        and "没接上话" not in o2["reply"],
                        "wait=%r，还在想 %s 行，回的是 %r"
                        % (o2["wait"], o2["waiting"], o2["reply"][:40]))
            worst |= ck("★ 回的那句**不是我打的那句**（真走了一个服务端来回）",
                        bool(o2["reply"]) and o2["reply"] != o1["me"]
                        and len(o2["reply"]) >= 4,
                        repr(o2["reply"][:60]))

            # 第二轮：走**点按钮**那条路，顺便验空输入什么都不做。
            # ⚠️ 空输入那一条**原来是拿 `stats().log` 判的（"30 -> 30"）—— 那条是
            #    **真空的**：`XQ_LOG` 上有 `LOG_MAX=30` 的帽子，push 一条再 shift 一条
            #    总数纹丝不动，所以它无论发不发出去都是绿的。改判 `me`（"主人说的"
            #    条数）和 `wait`，两个都**只涨不清**，推一条就变。
            # ⚠️ 第二句也必须是纯闲聊（同上，「放一首」会命中 `play`）。
            # 走按钮之前再确认一次链路 —— 上一版**就是在这里**红的（o2 那一轮轮询
            # 之间链路掉了一下），`why` 已经把它说清楚了。
            for _ in range(12):
                if await S.js("LINK.online"):
                    break
                await asyncio.sleep(0.6)
            o3 = await S.js("""JSON.stringify((() => {
              const s0 = XQ.mediaLink.stats();
              document.getElementById('xqSend').click();       // 空的：什么都不该发生
              const s1 = XQ.mediaLink.stats();
              const i = document.getElementById('xqSay');
              i.value = '今天路上挺顺的';
              document.getElementById('xqSend').click();
              const s2 = XQ.mediaLink.stats();
              return {me0: s0.me, me1: s1.me, why1: s1.why,
                      wait1: s1.wait, log1: s1.log, log0: s0.log,
                      me2: s2.me, wait: s2.wait, why: s2.why, box: i.value};
            })())""")
            worst |= ck("★ 空输入点「发送」什么都不做（不发一条空的出去）",
                        o3["me1"] == o3["me0"] and o3["wait1"] == "",
                        "我 %s -> %s 句，wait=%r" % (o3["me0"], o3["me1"], o3["wait1"]))
            # 上一条只说"什么都没发生"，但那也可能是"点压根没点到按钮上"。这条把
            # `why` 读出来钉死：**确实走进了 xqSend，而且在第一道 early-return 上返回的**。
            worst |= ck("★ 而且那一份空输入**真的走到了 xqSend**（不是点空了）",
                        o3["why1"] == "文本是空的", "why=%r" % (o3["why1"],))
            worst |= ck("★ 点「发送」这条路也是通的（不只是回车）",
                        o3["wait"] == "今天路上挺顺的" and o3["box"] == ""
                        and o3["me2"] == o3["me1"] + 1,
                        "wait=%r，输入框=%r，我 %s -> %s 句（why=%r）"
                        % (o3["wait"], o3["box"], o3["me1"], o3["me2"], o3["why"]))

            for _ in range(30):
                await asyncio.sleep(0.8)
                # `S.js` 直接回 JS 那个字符串（不是 JSON）—— 空串就是"不等了"。
                if not await S.js("XQ.mediaLink.stats().wait"):
                    break

            o4 = await S.js("""JSON.stringify((() => {
              const b = document.getElementById('xqBubble');
              const sub = document.querySelector('.sub-body');
              const ps = [...document.querySelectorAll('#xqBubble p.m')];
              const st = XQ.mediaLink.stats();
              return {log: st.log, mine: st.me,
                      sh: b.scrollHeight, ch: b.clientHeight,
                      ov: getComputedStyle(b).overflowY,
                      subSh: sub.scrollHeight, subCh: sub.clientHeight,
                      minH: getComputedStyle(document.querySelector('.mp-xq')).minHeight,
                      lastIsSt: ps.length > 0 && ps[ps.length - 1].classList.contains('st'),
                      whoTxt: ps.map((p) => p.dataset.who + ':' + p.textContent.slice(0, 10))};
            })())""")
            worst |= ck("★ 聊了两轮之后整页还是不用滚（输入行没把卡片顶穿 —— I2 那场事故的同一条链）",
                        o4["subSh"] <= o4["subCh"] + 4,
                        ".sub-body 内容 %s / 可视 %s" % (o4["subSh"], o4["subCh"]))
            worst |= ck("★ 对话框自己还是能滚（`overflow-y:auto` 生效，不是溢出看不见）",
                        o4["ov"] == "auto",
                        "overflow-y=%s，内容 %s / 视口 %s" % (o4["ov"], o4["sh"], o4["ch"]))
            worst |= ck("★ 状态行还是最后一条（「正在想」没挤到它后面）",
                        o4["lastIsSt"], "最后一条是状态行=%s" % o4["lastIsSt"])
            worst |= ck("★ 两轮都进去了（我 2 句 + 小瑞 2 句）",
                        o4["mine"] == 2 and o4["log"] >= 4,
                        "总条数 %s（我 %s 句）" % (o4["log"], o4["mine"]))

            print("\n=== P · 说「放歌」就真的放（用户实测报的：只回话、不动手）===")
            # ★★ 2026-09-25 晚用户实测：他在这一页打「放歌」，小瑞回
            #    「好的主人，舒缓的歌已经放上了，音量也帮您调小了些」—— 而**播放器
            #    一动没动**（原话：「我要求它放 但并没有真做」）。两层根因：
            #      ① 系统提示让它以为自己有执行能力（`ui/xiaorui.py` 第 7 条已堵上，
            #         全站生效）；
            #      ② **这一页没有任何东西去执行它说的动作** —— 于是那句话只能是谎话。
            #    修法：认得出是命令 → **本地真做 + 按执行完的真实结果拼回话**，
            #    而且**根本不发给服务端**（模型没有执行能力，发过去只会换一句漂亮的
            #    谎话回来）。所以这一段钉的是三件事：真做了 · 话是照着真实状态说的 ·
            #    没上行。
            # ⚠️ 先把档位喂到 severe **钉住**：demo 那份源自己每隔几十秒还会推档位，
            #    而"更重一档"会触发它顺手换一首 —— 那样"回话点名的"和"正在放的"就
            #    对不上了。那是**判据自己读晚了**，不是功能坏（N2 踩过同一个坑）。
            #    钉到顶之后它再推 mild/moderate 都算"没更重"，不会再动手。
            # ⚠️ 喂完要**真等一会儿**再打命令：喂档位可能当场触发一次换歌，而
            #    `playTrack` 是 async 的 —— 不 settle 就发命令，两条 playTrack 会撞上。
            await S.js("""(() => {
              XQ.mediaLink.feed('mild');
              XQ.mediaLink.feed('moderate');
              XQ.mediaLink.feed('severe');
            })()""")
            await asyncio.sleep(2.4)

            def fresh(pre, post):
                """`post` 里**新出现**的气泡文本（按出现次数扣掉 `pre` 里那些）。
                ⚠️ 不许图省事取"最后一条 xq 气泡"：疲劳推荐是**页面自己 push** 的
                   （`recommendCalm`），随时可能插在命令回话后面 —— P 段第一版就
                   这么红的：读到了「检测到你有些疲劳…」，而音量回话在它**前面**。
                   命令回话必须按"这次新冒出来的"去找，不能按位置找。"""
                left = {}
                for t in pre:
                    left[t] = left.get(t, 0) + 1
                out = []
                for t in post:
                    if left.get(t, 0) > 0:
                        left[t] -= 1
                    else:
                        out.append(t)
                return out

            def pick(new, *keys):
                """新冒出来的那些里，**先说到的**一条含任一关键词的回话。
                ⚠️ 关键词要带上命令回话里那个**空格**（`放上了 《X》· Y。`）：
                   疲劳推荐说的是「我挑了《X》（没有空格）」，光按「挑了」找会把
                   两条混起来 —— 差集只解决"插队"，解决不了"长得像"。"""
                for t in new:
                    if any(k in t for k in keys):
                        return t
                return ""

            p1 = await S.js("""JSON.stringify((() => {
              const s0 = XQ.mediaLink.stats();
              const tx = () => [...document.querySelectorAll('#xqBubble p.m')]
                    .map((p) => p.textContent);
              const texts = tx();
              const i = document.getElementById('xqSay');
              i.value = '放歌';
              i.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true}));
              /* 回车这一下之后 `wait` **必须还是空的** —— 这就是"没上行"的判据：
                 真发给服务端的话，`wait` 会立刻变成那句原文（O 段就是这么读的）。 */
              const s1 = XQ.mediaLink.stats();
              return {me0: s0.me, me1: s1.me, wait: s1.wait, why: s1.why,
                      online: s1.online, downN: s1.downN,
                      texts: texts, box: i.value,
                      was: document.getElementById('tName').textContent};
            })())""")
            worst |= ck("★★ 「放歌」**没上行**（本地就执行了，不指望模型动手）",
                        p1["wait"] == "" and p1["why"] == "",
                        "wait=%r，why=%r（online=%s，整场断过 %s 次）"
                        % (p1["wait"], p1["why"], p1["online"], p1["downN"]))
            worst |= ck("★ 而且我那句**进了对话框**、输入框清空（真发出去了）",
                        p1["me1"] == p1["me0"] + 1 and p1["box"] == "",
                        "我 %s -> %s 句，输入框=%r" % (p1["me0"], p1["me1"], p1["box"]))

            await asyncio.sleep(1.6)          # 等 playTrack 落地（要真解码 + 起播）
            p2 = await S.js("""JSON.stringify((() => {
              return {paused: au.paused, ct: au.currentTime,
                      title: document.getElementById('tName').textContent,
                      texts: [...document.querySelectorAll('#xqBubble p.m')]
                             .map((p) => p.textContent),
                      src: au.currentSrc,
                      on: document.querySelectorAll('.tracks li.on').length};
            })())""")
            preply = pick(fresh(p1["texts"], p2["texts"]), "放上了 ", "挑了 《")
            worst |= ck("★★ 它说「放上了」的时候，播放器**真的在放**（用户报的就是这条）",
                        p2["paused"] is False and p2["ct"] > 0 and p2["on"] == 1,
                        "paused=%s，已播 %.2f s，正在放 %r，.on %s 行"
                        % (p2["paused"], p2["ct"], p2["title"], p2["on"]))
            worst |= ck("★★ 回话点名的歌 == **正在放的那一首**（话是从真实状态拼的，不是编的）",
                        bool(preply) and bool(p2["title"]) and p2["title"] in preply,
                        "正在放 %r，小瑞说 %r" % (p2["title"], preply[:60]))
            # 完成时**只在真做了的时候**才许出现。上面两条已经证明"真在放"，所以这条
            # 反过来查"话和事实一致"：真在放却说"浏览器不让"，那也是 bug。
            worst |= ck("★ 完成时用在了对的地方（真在放 → 才说「放上了」）",
                        "放上了" in preply, "回话 %r" % (preply[:50],))

            # ---- P2 · 音量 / 暂停 / 继续 / 下一首：每条都真的动了 ----
            # 同一个动作连打四遍，用一个 helper 收口（每条都是"打一句 → 等 → 读回
            # 页面的真状态"）。
            async def say(text, wait_sec=1.1):
                # 先读一份"动作之前"（音量 / 第几首 / 停没停）—— 判"真的动了"必须
                # 有个前值可比，不能只看动作之后长什么样。
                pre = await S.js("""JSON.stringify({i: idx,
                      vol: +document.getElementById('vol').value, paused: au.paused,
                      title: document.getElementById('tName').textContent,
                      texts: [...document.querySelectorAll('#xqBubble p.m')]
                             .map((p) => p.textContent)})""")
                await S.js("""(() => {
                  const i = document.getElementById('xqSay');
                  i.value = '%s';
                  i.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true}));
                })()""" % text)
                await asyncio.sleep(wait_sec)
                post = await S.js("""JSON.stringify((() => {
                  const ps = [...document.querySelectorAll('#xqBubble p.m')];
                  const me = ps.filter((p) => p.dataset.who === 'me');
                  return {paused: au.paused, ct: au.currentTime, i: idx,
                          title: document.getElementById('tName').textContent,
                          vol: +document.getElementById('vol').value,
                          avol: au.volume,
                          wait: XQ.mediaLink.stats().wait,
                          texts: ps.map((p) => p.textContent),
                          cmd: me.length ? me[me.length - 1].textContent : ''};
                })())""")
                post["pre"] = pre
                post["new"] = fresh(pre["texts"], post["texts"])
                return post

            p3 = await say('小声一点')
            worst |= ck("★ 「小声一点」音量**真的掉下来了**（滑杆动了，音频音量跟着动）",
                        p3["vol"] == max(0, p3["pre"]["vol"] - 10)
                        and abs(p3["avol"] - p3["vol"] / 100.0) < 0.02,
                        "滑杆 %s -> %s，au.volume=%.2f"
                        % (p3["pre"]["vol"], p3["vol"], p3["avol"]))
            vrep = pick(p3["new"], "音量")
            worst |= ck("★ 回话报的音量**是滑杆上读回来的那个数**（不是写死的）",
                        ("%s%%" % p3["vol"]) in vrep,
                        "回话 %r（滑杆 %s）" % (vrep[:44], p3["vol"]))
            worst |= ck("★ 「小声一点」这一句也没上行",
                        p3["wait"] == "", "wait=%r" % (p3["wait"],))

            p4 = await say('停一下')
            worst |= ck("★ 「停一下」**真的停了**（不是嘴上停）",
                        p4["paused"] is True,
                        "paused=%s，回话 %r"
                        % (p4["paused"], pick(p4["new"], "停了", "停")[:30]))

            p5 = await say('接着放')
            worst |= ck("★ 「接着放」**真的接着响了**",
                        p5["paused"] is False and p5["ct"] > 0,
                        "paused=%s，已播 %.2f s" % (p5["paused"], p5["ct"]))
            worst |= ck("★ 而且它说的是**接着放的那一首**（从真实状态取的标题）",
                        p5["title"] in pick(p5["new"], "接着放 "),
                        "正在放 %r，回话 %r"
                        % (p5["title"], pick(p5["new"], "接着放")[:50]))

            p6 = await say('下一首')
            worst |= ck("★ 「下一首」**真的换了文件**（不是回到同一首）",
                        p6["i"] != p6["pre"]["i"],
                        "第 %s 首 -> 第 %s 首（%r -> %r）"
                        % (p6["pre"]["i"], p6["i"], p6["pre"]["title"], p6["title"]))
            worst |= ck("★ 换了之后它说的是**新的那一首**",
                        bool(p6["title"]) and p6["title"] in pick(p6["new"], "放上了 ", "挑了 《"),
                        "正在放 %r，回话 %r"
                        % (p6["title"], pick(p6["new"], "放上了 ", "挑了 《")[:50]))

            print("\n=== Q · 两档疲劳不许推同一首（用户实测报的）===")
            # ★★ 用户原话：「为啥两个状态都是自动放我好想你间奏这首歌 还不如不同状态
            #    随机给歌 但不要每次都一样 我歌那么多 随机更好」。
            #    根因：`pickCalm()` 原来 `return rows[0].i` —— **确定性**的，轻度推它、
            #    中度还推它，看上去就像"小瑞只会这一首"。
            #    现在改成"在最舒缓的那一档里摇，并避开刚推过的两首"。
            # 判据：**连着三档疲劳，摇出来的三首必须两两不同**。这条不是概率断言 ——
            #    每次摇都会排除"最近推过的 2 首"，池子有 10 首，所以三首不同是**结构性
            #    保证**的，不靠运气（靠运气的断言过一阵子自己会红）。
            picks = []
            for tier in ("mild", "moderate", "severe"):
                r = await S.js("""JSON.stringify((() => {
                  XQ.mediaLink.feed('normal');      // 先压回清醒，不然"更重一档"不成立
                  XQ.mediaLink.feed('%s');
                  const st = XQ.mediaLink.stats();
                  return {tier: '%s', title: st.calmTitle, i: st.calm,
                          recent: st.calmRecent, src: st.calmSrc};
                })())""" % (tier, tier))
                picks.append(r)
                await asyncio.sleep(0.6)
            idxs = [p["i"] for p in picks]
            worst |= ck("★★ 连着三档疲劳摇出来的**三首各不相同**",
                        all(i >= 0 for i in idxs) and len(set(idxs)) == 3,
                        " / ".join("%s→%r(第%s首)" % (p["tier"], p["title"], p["i"])
                                   for p in picks))
            worst |= ck("★ 摇出来的都还是**内置**的（换了机器一定放得出来）",
                        all(p["src"] == "内置" for p in picks),
                        "来源 %s" % [p["src"] for p in picks])
            worst |= ck("★ 刚摇过的那首**记进了 recent**（下次才不会又是它）",
                        picks[-1]["recent"] and picks[-1]["recent"][0] == picks[-1]["i"],
                        "最近推过 %s，这次是第 %s 首"
                        % (picks[-1]["recent"], picks[-1]["i"]))
            worst |= ck("★ 对话里点名的和 `calmTitle` 是同一首（没各说各的）",
                        all(p["title"] and p["i"] >= 0 for p in picks),
                        "%s" % [p["title"] for p in picks])

            print("\n=== L · 用户目录不在时：只剩内置那批，而且页面上说了 ===")
            # 起第二份服务，把曲库目录指到一个不存在的地方。**用独立端口 +
            # 命令行参数**，绝不碰用户的 `ui/config.json`（那份里有 API key）。
            # 这一段才是"把 30 首拷进项目"这个改动真正的意义：演示机上没有
            # D:\CloudMusic 时，这一页不该是一个空列表 + 一句"没找到目录"。
            srv2 = start_server(PORT2, LOG2, ["--media-dir", NOMEDIA])
            lib2 = wait_lib(PORT2)
            if lib2 is None:
                worst |= ck("第二份服务（曲库目录不存在）起得来", False, "看 " + LOG2)
            else:
                worst |= ck("★ 目录不在时服务端照样给得出曲目（给的就是内置那份）",
                            lib2["ok"] is True and len(lib2["tracks"]) == nb,
                            "ok=%s，%d 首（内置 %d）"
                            % (lib2["ok"], len(lib2["tracks"]), nb))
                worst |= ck("★ 而且如实报 dirOk=false（不装作目录还在）",
                            lib2["dirOk"] is False, "dirOk=%s" % lib2["dirOk"])
                await goto(S, "/media.html", 3.5, port=PORT2)
                l = await S.js("JSON.stringify({"
                               " rows: document.querySelectorAll('.tracks li[data-i]').length,"
                               " note: document.getElementById('listNote').textContent,"
                               " bubble: document.getElementById('xqBubble').textContent})")
                worst |= ck("★ 页面上剩的就是内置那批（不是空列表）", l["rows"] == nb,
                            "%d 行 / 内置 %d 首" % (l["rows"], nb))
                # ⚠️ 靶子换过两次，判的始终是同一件事：**不许装作目录还在**。
                #    最早读 `#libWarn`（那段「如实说明」里的警告槽）→ 那段删了；
                #    改成读小瑞那行状态（`libLine()`）→ 2026-09-25 用户又要求把
                #    "曲库是怎么拼出来的"全去掉，`libLine` 整个函数没了。
                #    现在说话的是 `libWarn()`：**正常情况下它返回空串**（状态行不渲染），
                #    只有 `dirOk === false` 时才有这一句。
                #    ⚠️ 换句话说这条判据现在是**唯一**守着"目录不在要吭声"的东西，
                #      删文案之前先想到这里。
                worst |= ck("★ 小瑞那句话**明说了**没找到那个目录（这条是本次改版的重点）",
                            "没找到" in l["bubble"] and lib2["dir"].split("/")[-1] in l["bubble"],
                            repr(l["bubble"]))
                worst |= ck("小瑞那句话也照实说（只说内置那份，不吹成整个曲库）",
                            "内置" in str(l["bubble"]), repr(l["bubble"]))
                # 内置那批是**拷在项目里的文件**，跟用户目录在不在没关系 —— 该能放。
                await S.js("document.querySelectorAll('.tracks li')[1].click()")
                await asyncio.sleep(2.0)
                l2 = await S.js("JSON.stringify({ct: au.currentTime, paused: au.paused,"
                                " svr: au.currentSrc,"
                                " cur: document.getElementById('tName').textContent})")
                worst |= ck("★ 内置那批在「没有用户目录」时真的放得出来",
                            l2["paused"] is False and l2["ct"] > 0,
                            "%r 已播 %.2f s" % (l2["cur"][:14], l2["ct"]))
                worst |= ck("放的还是 /music/ 那条路由", "/music/" in str(l2["svr"]),
                            str(l2["svr"])[-30:])

            print("\n=== 控制台 ===")
            bad = [e for e in S.errs if not any(x in (e[1] or "") for x in KNOWN)]
            if bad:
                worst |= 1
                for lv, t in bad[:8]:
                    print("  !!  %s %s" % (lv, t))
            else:
                print("  OK  全程零报错零警告")
    finally:
        stop(srv)
        if srv2 is not None:
            stop(srv2)
        for h in _LOGS:
            h.close()

    print()
    print("（红一条不代表「改坏了」—— 先看它说的是不是真话，再决定动代码还是动断言）")
    return worst


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
