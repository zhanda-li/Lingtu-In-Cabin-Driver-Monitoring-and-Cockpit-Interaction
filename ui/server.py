"""界面服务：读一个数据源 -> 每 1/hz 秒推一次状态 -> 浏览器画出来。

    python ui/server.py                     # 按 config.json（默认 demo）
    python ui/server.py --source replay:runs/session1.csv
    python ui/server.py --source live:runs/session1.csv
    python ui/server.py --source cam         # **界面自己开摄像头跑真模型**
    python ui/server.py --open               # 顺便用 Edge 全屏打开

── 数据源和摄像头的关系（改这块之前先读这段）──────────────────────

摄像头是**独占设备**（本项目踩过：两个进程一起开，先开的那个变全黑 + 1 fps）。

  demo / replay / live  ——  界面**不开摄像头**。live 只读 `fuse.py` 写的 CSV。
                           驾驶员画面画的是**由真实数据驱动的示意头像**，
                           界面上标明，不冒充实时视频。
  cam                   ——  界面**自己开摄像头、自己跑模型**（`ui/cam.py`），
                           画面是真画面，数字是真判决，还带真 FaceMesh 叠加。
                           代价：**此时不能再跑 `live_fuse.bat`**，两边会抢设备。

cam 那一路的融合判据是从 `src/fuse.py` 抄过来的，正确性靠
`tools/cmp_cam_fuse.py` 逐格对拍保证（见 ui/cam.py 的模块注释）。
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from aiohttp import web, WSMsgType

# ⚠️ **`.webp` 必须登记到 aiohttp 自己那张表上，登记到 stdlib 上没用。**
# 这一段改过两遍，第一版是错的，把坑记下来：
#   第一版写的是 `mimetypes.add_type("image/webp", ".webp")`，理由是"add_static 会
#   交给 `mimetypes.guess_type()`、stdlib 把 .webp 只写在非标准表 common_types 里
#   （strict=0 才命中）"。**推理本身没错，但这个前提是错的** —— 实测发送的仍是
#   `application/octet-stream`。去源码里看才明白（aiohttp 3.14.3，
#   `aiohttp/web_fileresponse.py:52`）：
#       CONTENT_TYPES: Final[MimeTypes] = MimeTypes()
#   FileResponse 用的是**自己 new 的一个 `MimeTypes()` 实例**，有独立的映射表；
#   模块级的 `mimetypes.add_type()` 改的是模块全局那份，**两者根本不是一个对象**，
#   所以怎么加都不生效。aiohttp 自己加 .js/.css/.wasm 也是加到那个实例上的
#   （同文件 :83-86）。
# 后果不是"图不显示"（`<img>` 靠嗅探照样显示），而是**碰巧能用**：
# 任何按 Content-Type 判断的地方（缓存、CSP、下载行为）都会走错分支 —— 所以
# 验的时候必须看**响应头**，不能看"图出来了没有"。
# 我们那张循环动图 xiaorui_live.webp 就靠这条。
try:
    from aiohttp.web_fileresponse import CONTENT_TYPES as _AIO_TYPES
    _AIO_TYPES.add_type("image/webp", ".webp")
except Exception:                       # aiohttp 换了内部结构也别把服务带崩
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ui"))
sys.path.insert(0, str(ROOT / "src"))
# ★ 唤醒那条路在 ui/voice/ 里，几个模块之间是**平级 import**（`from kws import …`），
#   所以这个目录也要在 sys.path 上。不加的话 `import voice.loop` 会在里面
#   报 "No module named 'asr_stream'" —— 而那个错看起来像"文件不见了"。
sys.path.insert(0, str(ROOT / "ui" / "voice"))

from amap import AMap                                      # noqa: E402
from asr import LocalAsr                                  # noqa: E402
from deepseek import load_config, mask, resolve_key       # noqa: E402
# ★ 2026-09-26 心率：HPM5300 + MAX30102 从板载 FT2232 的 console 串口进
#   （板端固件在 hr/firmware/，2026-09-26 从 hpm_sdk\hr_project 复制进来）。这一路**和摄像头、和 fuse.py 那条 CSV
#   完全无关**，它是独立的一根数据管子，只在 tick() 里往当前这一帧的 State 上
#   贴一个数。所以它不需要新的 WS 消息类型、不需要改前端通道 —— 见
#   serial_hr.py 的 apply_to_state()。
from serial_hr import apply_to_state, make_hr_reader       # noqa: E402
from sources import CsvSource, DemoSource                 # noqa: E402
# ★ 2026-09-26：`CLASSES` 给下面的 `vision_line()` 用 —— 那一行的概率列要**按
#   类别顺序**打（`ui/state.py` 二类：normal/fatigue），顺序不能在这儿现编一份。
from state import CLASSES                                 # noqa: E402
from tts import ServerVoice, list_edge_voices              # noqa: E402
from wechat import WeChatPusher                            # noqa: E402
from xiaorui import (ACTIONS, Agent, ScriptedAgent, detect_action,  # noqa: E402
                     detect_intent, emotion_for, is_affirm, state_brief)

WEB = ROOT / "ui" / "web"
SEV_CFG: dict = {}
# 支路二那两条独立告警的阈值（见 ui/state.py 的 alarms 那一段）。和 SEV_CFG
# 一样是这个进程的全局，main() 里从 config 读一次。
ALARM_CFG: dict = {}
# 微信推送那一段（见 ui/wechat.py）。同样是 main() 里读一次。
WECHAT_CFG: dict = {}
# 高德地图那一段（见 ui/amap.py）——「最近服务区」那个数字的**唯一来源**。
# ⚠️ 这里只放**服务端**要用的东西；页面上要用的 JS key 走 `hello.amap.js`
#    （见那个文件头「两把 key 谁去哪」）。同样 main() 里读一次。
AMAP_CFG: dict = {}

# 除 index.html 之外的页面（都是 web/ 下的真实文件，见 main() 里的注册）。
# flow / design / cover 是纯展示页，不连 WebSocket；其余几页都接同一路数据。
# ★ 2026-09-25：**media 从"纯展示页"里挪出来了** —— 多媒体页现在也连 WS，只用其中
#   一个字段（`state.severity`：整页跟着档位换色 + 疲劳时小瑞推荐舒缓音乐）。
#   所以它和别的页面一样算进 `watch_pages` 的"还有人在用"（那段注释里本来就把
#   多媒体写进去了，那时是句空话，现在才算数）。见 media.html 文件头。
# ★ `nav` 2026-09-25 晚**又是真的了**：nav.html 建回来了，而且这一版挂的是真高德
#   （`ui/amap.py` + JS API 2.0），左导航第五项就是它。它 2026-09-24 曾从磁盘删掉
#   （用户砍演示脚手架），当时这个条目留在了元组里 —— 现在不用再当"遗留"看了，
#   但那条历史值得记着：**元组里有名字 ≠ 文件在盘上**，反过来说文件在盘上也得
#   有名字，少一个就是 404（而 404 在浏览器里是一张白页）。
# ⚠️ link / flow / design / phone 是**旧作品页**：左导航那十个作品编号整块删掉了，
# 它们已经**没有入口**，但文件还在、URL 还开得出来（用户拍板：去掉入口，保留文件）。
# ★ 2026-09-25「第八次改版」新增 `monitor`：detail.html 的「更多」按钮现在是一条
#   跳到 monitor.html 的链接（原来是在本页弹五个按钮的浮层，用户否了）。detail.html
#   上那五个页签的深层面板（疲劳/生理/行为/历史）整块搬去了 monitor.html，所以它是
#   **座舱主界面的一部分**，不是上面说的"旧作品页"。别漏注册，漏了就是 404。
# ★ 2026-09-25「第十六次改版」新增 `about`：帮助 & 关于项目介绍页（竞赛答辩 /
#   作品展示用）。入口只有一个 —— 首页「快捷功能」里那格 `a[href="about.html"]`
#   （⚠️ 第十七次改版起它**不再跨满整行**了：用户点名要它和新增的「导航」同一行、
#      导航在左，所以 `qk-full` 摘掉了。别照着旧注释去 `pages.css` 里找跨满）。
#   ⚠️ 它和 flow / design / link / phone 那几页**不是一类**：那几页是"旧作品页，
#      没入口、只留着文件"，`about` 是**有入口的正经页面**，别哪天跟着一起删。
#   ⚠️ 它不连 WebSocket（讲结构不讲实时状态），所以也不进下面那份 watch 名单。
#   ⚠️ 漏登记的表现就是 404 —— 而 404 在浏览器里是一张**白页**，
#      看起来和"页面写错了"一模一样（这次就踩了；`_scratch/_check_about.py`
#      的文件头记了怎么在不重启服务器的前提下先验证它）。
# ★ 2026-09-26「第十八次改版」新增 `data`：「数据详情」页。入口两个 ——
#   首页 `.ntiles` 里那格 `a[href="data.html"]`、以及驾驶监测页免责小字下面
#   那个 `.md-more`。**不进左导航**（`chrome.js` 的 NAV 一行都没动），
#   所以左栏一项都不亮 —— `chrome.js:371-375` 传空 active 时不报错，
#   `about.html` 已经是这么干的（`XQ.mountChrome({ active: '' })`）。
#   ⚠️ 它和 `about` 有一处**不一样**：`about` 不连 WebSocket（讲结构不讲
#      实时状态），这一页**连**（串口行和视觉决策两路都要实时推），
#      所以 `Hub.watch_pages()` 那份"还有没有人在用这个界面"的名单里
#      **有它一份**（那份名单就是 `hub.sockets`，是自动的，不用登记）。
PAGES = ("detail", "monitor", "chat", "link", "flow", "design", "phone", "cover",
         "nav", "about", "media", "settings", "data")


# ---------------------------------------------------------------- 数据源
def make_source(cfg: dict, spec: str | None = None):
    """spec 形如 `demo` / `replay:runs/session1.csv` / `live:路径` / `cam[:视频]`。"""
    sc = cfg.get("source", {})
    mode, _, raw = (spec or sc.get("mode", "demo")).partition(":")
    mode = mode.strip() or "demo"
    raw = raw.strip()
    # ⚠️ 冒号后面**真的写了路径**才用显式路径；没写才去套 config 的默认值。
    # 关键在于 `cam` 是个例外：它的"没写路径"意思是**开真摄像头**，不是
    # "用默认那段视频"。早先这里是一行 `path = path.strip() or sc.get("path", ...)`，
    # 于是 `--source cam` 被套上 runs/session1.csv，`if path:` 恒真 →
    # CamSource 把 CSV 当视频打开，启动直接 RuntimeError: 打不开视频。
    # 表现是"文档里写着的 cam 模式一跑就崩"，而 cam:某段.mp4 反倒是好的。
    if raw:
        path = raw
    elif mode == "cam":
        path = ""
    else:
        path = sc.get("path", "runs/session1.csv")
    speed = float(sc.get("speed", 1.0))
    loop = bool(sc.get("loop", True))
    if mode == "demo":
        return "demo", DemoSource(loop=loop)
    if mode == "cam":
        # ⚠️ 延迟导入：`cam.py` 会把 torch + mediapipe + cv2 全拉起来（启动要
        #   好几秒）。demo/replay 用不上它，不该为此等。
        from cam import CamSource
        # `cam` 开摄像头；`cam:某段.mp4` 把同一套推理跑在视频上 ——
        # 没有摄像头（或者在别人机器上演示）时走这条，判据一模一样。
        replay = None
        if path:
            p = Path(path)
            replay = str(p if p.is_absolute() else ROOT / p)
        return "cam", CamSource(cfg, replay=replay)
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    return mode, CsvSource(p, live=(mode == "live"), speed=speed, loop=loop)


def stop_source(src) -> None:
    """放掉一个数据源。**摄像头必须显式 release**，否则切走了它还占着设备。

    ★ 2026-09-25 深夜：`stop()` 回来之后**再看一眼那个线程还在不在**，不在就
      print 一行。这一行是"灯到底灭没灭"的唯一现场证据 —— 设备是在
      `CamSource._run()` 的 `finally: self.src.release()` 里放的，而 `stop()`
      只 `join(1.5)`：线程要是卡在 `cap.read()` 或 mediapipe 推理里没赶上这
      1.5 秒，**进程就还攥着设备**（灯继续亮，用户再插摄像头也打不开）。
      这里**不补救**（从别的线程去 `cap.release()` 正被 `read()` 用的
      句柄 = 数据竞争，可能直接把服务打死，比灯多亮一会儿严重得多），
      只如实记下来。真出现这一行，再去查那个线程卡在哪。
    """
    stop = getattr(src, "stop", None)
    if callable(stop):
        try:
            stop()
        except Exception as e:
            print(f"[cam] 松手时出错：{type(e).__name__} {e}")
    th = getattr(src, "_th", None)
    if th is not None and th.is_alive():
        print("[cam] ⚠️ 松手后摄像头线程还活着 —— 设备可能还没放掉，"
              "见 stop_source 的注释")


def switch_source(cfg: dict, old, mode_spec: str):
    """换源：**先建新的，建成了才放旧的**。返回新源；抛异常 = 一个字节都没动。

    ⚠️ 顺序是这个函数的全部意义。这里原来（2026-09-25 之前）写在 handle() 里，
    是 `stop_source(hub.source)` 然后才 `make_source(...)`。加按钮之前没人会走到
    "换源失败"这条路，加了之后它就是**用户天天会走的那条**：他明说了
    「没有实时接人脸摄像头」，所以点「接入摄像头」十有八九就是失败。

    失败长什么样：`ui/cam.py` 的 `CamSource.__init__` 里 `CameraSource(...)` 会
    抛 `RuntimeError: 打不开摄像头 0`（`src/live.py:361`）。旧顺序下这一抛发生
    在 `stop_source` **之后** —— 正在跑的那个源已经被放掉了，而 `hub.source`
    还指着它。表现：用户点一下按钮，本来好好的演示画面**当场死掉**，此后一帧
    state 都不来。新顺序下失败只是**一句 info**，数据源原地不动。

    ⚠️ 代价（写在这儿免得后人当 bug 修）：`cam` 换 `cam` 时新源抢不到设备
    （旧的还占着），会报失败。加这一条重试**不值得** —— 唯一能发出
    `spec:'cam'` 的入口是那颗按钮，而摄像头连上时那颗按钮显示的是"断开"，
    所以这条路从界面上到不了。宁可如实报错，也不要在重试失败时把
    `hub.source` 留在已释放状态（那正是要修的这个病）。

    ⚠️ **调用者必须把它丢进线程**（`run_in_executor`）：建 cam 源要 load 两个
    torch 权重 + 两个 mediapipe landmarker，实测量级是**秒**。在事件循环里建
    = 整页冻结：state 不推、MJPEG 断流，而用户只是点了一下按钮。
    """
    new_mode, new_src = make_source(cfg, mode_spec)
    stop_source(old)
    return new_mode, new_src


# ---------------------------------------------------------------- 视觉那一行
# ★ 2026-09-26：这一行**以前到不了浏览器**。`src/fuse.py` 的 print 直接进它自己的
#   控制台窗口（`live_fuse.bat`），而 `fuse.py` 和 `ui/server.py` 是两个独立进程。
#   现在 `--source cam` 这一路（`ui/cam.py`）本来就在**本进程内存里**放着同样一帧
#   `State`（`l_fused` / `probs` / `gate` / `l2` / `p_fat` / `perclos` / `src`
#   一个不缺），所以这一行是**拼出来的**，不是转发的 —— 一行都不用碰 `fuse.py`。
#   ⚠️ 摄像头是**独占设备**：`--source cam` 的时候不能同时跑 `live_fuse.bat`
#   （谁后抢谁黑屏）。这也正是"别做转发层、直接拼"的另一条理由。
#
# ⚠️ 列序照 `src/fuse.py:861-866`，但有**三处不一样**，都是刻意的：
#   · fuse 那边是三类快照（normal/phone/fatigue），`ui/` 这一侧已经把 phone 并进
#     fatigue（`ui/state.py:70` 的 `CLASSES`），所以概率只有 `nor=` / `fat=` 两根。
#   · fuse 那一行末尾还有 ` YAWN` / ` EYE=..s` / ` HEAD=..°` 三段。**这里不打**：
#     那三条判据（哈欠 / 持续闭眼 / 头部持续低垂）的阈值只在 `fuse.py` 里有一份，
#     要在这儿重推就得**把显示阈值抄第二遍**，而 `ui/sources.py:49-51` 白纸黑字
#     写着「不能在这里重新按阈值推一遍（那就会多出第二份阈值）」。如实少打三段，
#     比多一份会漂的抄本强。
#   · `ema(nor)=` 用的**只能是** `st.ema_normal`（本侧的字段，就是清醒类那一个 EMA）。
#     不是 fuse 的 `ema[argmax(ema)]`（那要每一类的 EMA，本侧只留了清醒这一类）——
#     所以标签**写死 `nor`**、不跟着 `l1` 走，免得看着像"当前最高那一类"。
def vision_line(st) -> str:
    """把当前这一帧 `State` 拼成一行，形如：

        [  12.3s] L0 清醒   <pose> nor=0.99 fat=0.01  ema(nor)=0.77  | gate OPEN  L2=0 P=  -  pc=  -

    没数的列一律 `-`，**绝不用 0 顶**：`P=0.00` 是一个判决（"这一帧判他不累"），
    "这一帧没这个数"是另一件事，而这两件事在屏幕上必须是两个样子 ——
    这是全项目一条贯的规矩（`ui/state.py` 的 `_f()` 那段注释）。

    `st is None`（这一帧还没有任何源出数）时返回空串 —— 页面把它当成"还没开始"。
    """
    if st is None:
        return ""
    # `src` 是"**是谁**把 l_fused 抬起来的"（pose/face/yawn/eye/head），空串时打
    # `-`，**不替它猜一个 pose** —— 那一列的全部意义就是"哪条路说了话"。
    src = (getattr(st, "src", "") or "-")
    probs = st.probs or {}
    cols = " ".join(
        "%s=%s" % (c[:3],
                   "-" if probs.get(c) is None else "%.2f" % probs[c])
        for c in CLASSES)
    e = st.ema_normal
    tail = "  | gate %s L2=%d" % ("OPEN " if st.gate else "shut", st.l2)
    # ⚠️ 两个 `-` 分支里的空格是**对的齐**的（`P=0.71` 和 `P=  -` 一样宽），
    #    照抄 `fuse.py` 那两行原样，别"顺手修一下"。
    tail += (" P=%.2f" % st.p_fat) if st.p_fat is not None else " P=  -"
    tail += (" pc=%.2f" % st.perclos) if st.perclos is not None else " pc= -"
    return ("  [%6.1fs] L%d %-2s <%s> %s  ema(nor)=%s%s"
            % (st.t, st.l_fused, st.level_name, src[:4], cols,
               "%.2f" % e if e is not None else " -", tail))


# ---------------------------------------------------------------- 服务
class Hub:
    # ★ 2026-09-24「只做疲劳」加的发声闸：档位要**稳住**这么久才出声。
    #   显示不等它 —— 界面照旧 8 Hz 跟着状态跳，慢的只有声音这一路。
    #   为什么只给重度：三类之后支路一只剩 L0/L3 两档，79 段实测里 `normal_14`
    #   这种"整段头都低"的片段会在 **2.27 s** 内被判成重度（它的鼻尖比干净清醒段
    #   低了 0.39 个肩宽，标"清醒"本身可疑），而真正的 phone/fatigue 段最短也有
    #   **7.00 s**。误报抖动和真事件差 3 倍，取中间 2.5 s 两边都安全。
    #   ⚠️ 轻度/中度不设闸：它们来自支路二的滚动量（perclos / p_fat），本来就不抖；
    #   而 `ENTER_SEC=0.25` 是用户为延迟调的，**别动它**（那是显示和级别的路径）。
    SPEAK_HOLD = {"mild": 0.0, "moderate": 0.0, "severe": 2.5}
    PROACTIVE_COOLDOWN = 20.0

    # ★ 2026-09-25 晚：**摄像头跟着页面开关**。用户原话：
    #   「我摄像头只有在打开网页的时候才打开」。以前 `--source cam` 是**启动时**
    #   就 `cv2.VideoCapture` 把设备抓住的（那时候一个页面都还没开），关网页当然
    #   不会松手 —— 页面只是个观众，持有者是这个进程。于是用户看到的是
    #   "关了网页摄像头灯还亮着，还得去关那个黑框"。
    #   现在改成：启动时**不开**。最后一个页面关掉之后等这么久再松手
    #   （`watch_pages`）。
    #   ★ 2026-09-24 晚（用户：「只有我点接入摄像头才接入」）：这一条又往前走了一步
    #     —— 连"第一个页面连上来再开"都不成立了。**开设备只有那一个入口：驾驶
    #     监测页右上角那颗「接入摄像头」**（`{"type":"source"}`，`want` 变成 cam）。
    #     页面连上来只是把 `maybe_autocam` 叫来看一眼，而它的第一道闸
    #     （`want != CAM_SPEC`）就是关着的。所以下面那段"给刷新留的 3 秒"现在管的
    #     只是**松手**这一侧：松手之后 `want` 一起复位成 demo，再想开就得再点一次。
    #   ⚠️ 那 12 秒是**给刷新和翻页留的**：刷新一次会让 WS 断一下再连回来，
    #      间隔远小于 1.8 s 的重连；掐到 0 的话每刷新一次都要重开设备
    #      （开一次要 load 两个 torch 权重 + 两个 mediapipe landmarker，秒级）。
    #   ⚠️ 只管 **spec 恰好是 `cam`** 这一种。`cam:某段.mp4` 不占设备（跑文件），
    #      松手没意义，而重开要几秒 —— 那是演示路径，别动它。
    #   ★ 2026-09-25 深夜：这个数从 **12 s 改成 3 s**。用户报「关闭浏览器
    #     摄像头还是开着」—— 他关了浏览器、回头看一眼镜头旁边的灯，灯还亮着。
    #     12 s 是当初拍脑袋定的（"给刷新和翻页留的余地"），但那个余地**根本不
    #     需要 12 s**：实测刷新/翻页时旧 WS 关到新 WS 开只隔 **0.2~0.6 s**
    #     （`_scratch/_check_cam_release.py` 量的，见那份报告的「断连窗口」）。
    #     留 3 s 已经是它的 5 倍余量，而用户眼睛能容忍的"灯还亮着"大概就是
    #     一两秒。宁可偶尔多开一次设备，也不要让灯在用户盯着的十几秒里亮着。
    #   ⚠️ 下限也别再砍到 0：刷新时 WS 断一下是**必然**的，掐到 0 就是每刷新
    #      一次都重开设备（开一次要 load 两个 torch 权重 + 两个 mediapipe
    #      landmarker，秒级），表现为"每按一下 F5 就卡几秒"。
    CAM_IDLE_GRACE = 3.0
    CAM_SPEC = "cam"

    def __init__(self, cfg: dict, source_spec: str | None):
        self.cfg = cfg
        # `want` = **用户此刻期望的源**，`mode`/`source` = 此刻真的在跑的源。
        # 两者在"摄像头没开"那段时间里是不一样的，这个区分是这一整段的支点：
        # `want` 决定"要不要开摄像头"，`mode` 决定"界面现在该怎么显示"。
        # 按钮（`{"type":"source"}`）改的是 `want`；空闲超时只动 `mode`。
        # ★ 2026-09-24 晚：**`want` 现在只有那颗按钮能改**（见下面 `if` 那一支）。
        #   用户原话：「只有我点接入摄像头才接入」—— 命中"严格"那一档：
        #   空闲松手（或刷新）之后页面回来**不会**自动接回，必须再点一次。
        #   所以 `want` 初值永远是 demo，命令行 `--source cam` 只声明
        #   **"摄像头可用"**（= `source_spec`，界面靠它决定显不显示那颗按钮、
        #   占位卡该写什么），不再等于"现在就开"。
        initial = source_spec or (cfg.get("source") or {}).get("mode") or "demo"
        self.want = initial
        self.source_spec = source_spec
        if initial == self.CAM_SPEC:
            # 摄像头**只由那颗按钮开**。先挂一个 demo 源占位 ——
            # 它是唯一不要设备、又永远建得起来的源，而且界面本来就把它如实
            # 标成「示意画面 · 未接摄像头」，所以这段时间里页面显示的是真话。
            self.mode, self.source = make_source(cfg, "demo")
            self.cam_open = False
            # ⚠️ 这一行就是那个"只有点才接入"。少了它，`want` 一路都是 cam，
            #    `maybe_autocam` 会在页面连上来的那一刻把设备抓走（老行为）。
            #   判据用 `initial`（= 命令行给的 spec）而不是 `mode`：
            #   `cam:某段.mp4` 走的是下面 else 那一支，它**不占设备**、本来就该
            #   立刻接上，别把它也一起冻住（见下面那段 spec/mode 的注释）。
            self.want = "demo"
        else:
            self.mode, self.source = make_source(cfg, source_spec)
            # ⚠️ 判据是**spec**，不是 `mode`：`make_source` 对 `cam` 和
            #   `cam:某段.mp4` 都返回 `"cam"` 这个 mode（同一个 CamSource，
            #   只是帧源不同）。拿 mode 去判的话，`cam:视频` 会被当成"真摄像头开着"，
            #   于是空闲超时去关它、而它本来就不占设备 —— 白折腾一次几秒的换源。
            self.cam_open = (initial == self.CAM_SPEC)
        # 上一次**自动**开摄像头失败的原因。它在的时候不自动重试 ——
        # 页面的 WS 断了会每 1.8 s 重连一次，不带这个闸的话每重连一次就跑一遍
        # 几秒的开设备 + 一条"切换失败"，日志和 CPU 都会被刷爆。
        # 用户手动点「接入摄像头」会清掉它（那是一次明确的"我现在插上了，再试"）。
        self.cam_error = ""
        # ★ 2026-09-26 心率（HPM5300 + MAX30102，串口）。**和摄像头无关的一条路**，
        #   所以它不参与下面那套 spec/mode/want 的拉扯：串口不像摄像头那样"独占
        #   且要用户点头才接"，它是常开的 —— 板子没插就是读数器里一句 error，
        #   页面照常显示「未接入」。
        #   ⚠️ 建在这里（而不是第一次 tick 时懒建）是因为构造函数里就要把读线程
        #   起起来：串口从开机到出第一个心率要几秒（攒 4 个间隔），晚起就白等。
        #   代价是这个进程一启动就占着 COM 口 —— 用户想用串口助手看板子输出的话
        #   得先关掉界面，这一点写在 serial_hr.py 的类注释里了。
        self.hr = make_hr_reader(cfg)
        # 「数据详情」页那路 `{"type":"log"}` 的上一次推送时刻（`time.monotonic()`）。
        # 0.0 是"从来没推过" —— 第一个 tick 必然满足 `now - 0.0 >= 0.5`，
        # 所以页面连上来第一帧就有东西看，不用等半秒。
        self._last_log = 0.0
        self.idle_since: float | None = None
        self._cam_task = None
        self.agent = Agent(cfg)
        # 服务端备路。⚠️ 传的是整个 `tts` 段，音色那一项要它自己去嵌着的
        # `server` 子字典里取 —— 顶层那个 `voice` 是浏览器的关键词（默认"自动"）。
        self.voice = ServerVoice(cfg.get("tts") or {})
        # 语音输入的兜底那一路（主路是浏览器的 SpeechRecognition）。
        # ⚠️ 装了 whisper 的话，`LocalAsr.__init__` 里的 `import whisper` 会把 torch
        # 拉起来，**服务启动会慢几秒**；没装就是一次立刻失败的 import。模型本身是在
        # 后台线程里加载的（`preload`），不占启动时间。
        # ⚠️ 模型**不在本地时连 load_model 都不调** —— 那是"绝不联网下模型"那条
        # 承诺的实现处，见 ui/asr.py 文件头。
        self.asr = LocalAsr(cfg.get("asr") or {})
        # ★ 2026-09-25：小瑞的耳朵（常听「你好，小瑞」→ 录音 → 转文字 → 交给 agent）。
        #   ⚠️ **懒创建**，两条理由：
        #     1. 用户没点"听"之前，这个进程不该有任何多余动作 —— 和"只有点接入
        #        摄像头才接摄像头"是同一条原则。麦克风更是这样。
        #     2. 唤醒模型要加载 0.8 s，放启动路径上就是白让启动慢一截。
        #   所以是第一个 `{"type":"voice_start"}` 来了才建，建在**线程**里
        #   （0.8 s 卡在事件循环里 = 所有页面心跳停一下）。
        #   ⚠️ 名字叫 `ear` 不叫 `voice` —— `self.voice` 已经被服务端 TTS 占了
        #   （见上面几行），重名会把出声那一路整个顶掉。
        self.ear = None
        self.ear_note = ""
        self.ear_building = False
        # 耳朵归**哪一张页面**。开着麦的那一张是唯一能往这里送音频的，
        #   `voice_send` 也只往它发（理由见那个函数的注释）。
        #   多开几个标签页时，"谁开麦谁算数"，不是"大家都算" ——
        #   两份麦克风的音频交错喂进同一个识别器，出来的是两句话各一半。
        self.ear_ws = None
        # "念完了"的看门狗（见 `voice_answer`：这个信号不保证会来）
        self.ear_task = None
        # ★ 2026-09-25：正在等的那件「让页面去做的事」，形如 (轮次号, id, future)。
        #   语音说「给我放个音乐」时，服务端让开麦那张页面真去放，然后**等它的回执**
        #   再决定说什么（见 `voice_do`）。⚠️ 认轮次号：迟到的回执不许算到新一轮上
        #   —— 和 `_voice_watchdog` 认 `ear.round` 是同一条纪律。
        self.ear_do = None
        # ★★ 2026-09-26：**跨句**的那件事 —— "小瑞问了一句，主人还没答"。
        #   形如 `(id, deadline)` 或 None。和上面那个 `ear_do` 是**两件事**，别混：
        #     · `ear_do` 是**当轮**正在飞的那一次调用（1.5 s 就超时，形如
        #       `(轮次, id, future)`），它的生命周期在一句话之内；
        #     · `pending_do` 是**上一句的提议**等主人回话，跨句、跨轮，由主人
        #       说一句「要」来兑现（`take_pending`）。
        #   起点是用户报的那串话：「我『给我导航』→ 小瑞『要不要我帮您导航到最近的
        #   服务区？』→ 我『要』→ 小瑞『我这就帮您调出最近的服务区…』→ **屏上什么都
        #   没发生**」。前两句当时是模型现编的，服务端一次动作都没发起，「要」于是
        #   永远只值一句话。现在服务端自己问（`voice_ask`）+ 自己记（这一格）。
        #   ⚠️ 注册点只有 `voice_ask` 一处，兑现点只有 `take_pending` 一处。
        self.pending_do = None
        # ★ 2026-09-25：状态机吐出来的事件**必须排队、由一个常驻协程串行处理**，
        #   不能在 WebSocket 读循环里直接 `await`（理由见 `voice_enqueue` 的文首，
        #   那是实测逮到的一次**循环等待**）。
        self.voice_q = None
        self.voice_pump = None
        self.sockets: set[web.WebSocketResponse] = set()
        self.last_state = None
        self.last_severity = None
        self.sev_since = 0.0        # 当前档位是什么时候开始的（发声闸计时用）
        self.spoke_for = None       # 这一档已经念过了（同一档只念一次）
        self.last_proactive = 0.0
        self.history: list[dict] = []
        # ★ 2026-09-25：驾驶监测页加了「接入摄像头 / 断开摄像头」按钮，换源从
        #   "命令行参数"变成了"运行时可点两下的事"。换源要 load 两个 torch 权重
        #   （实测量级是**秒**），期间必须挡住第二次点击 —— 两个线程同时
        #   `make_source("cam")` 会去抢同一个设备，第二个必然失败。
        #   ⚠️ 只是个**节流阀**，不是锁：真正的互斥靠"整段切换在同一个
        #      协程里顺序跑完"，见 handle() 的 source 那支。
        self.switching = False
        # ★ 2026-09-25 晚：疲劳告警推到微信（企业微信群机器人，见 ui/wechat.py）。
        #   ⚠️ `maybe_push()` 是**同步、立刻返回**的：真正的 POST 在另一个协程里，
        #   一次网络超时绝不会卡住这个 8 Hz 的主循环。见那个文件头的第 2 条。
        #   ⚠️ 只给它一个 state 对象、别给它 Agent —— 否则"推出去的消息长什么样"
        #   会和"小瑞说什么"耦合在一起漂。
        self.wechat = WeChatPusher(WECHAT_CFG)
        # ★ 2026-09-25：「最近服务区」那块数字的来源（见 ui/amap.py）。
        #   ⚠️ 它同时是**两处**的来源 —— 小瑞嘴上念的那个公里数（`voice_answer`）
        #   和导航页屏上显示的那个（`/amap/nearby`）。**必须是同一个数**：
        #   两份算法迟早会差 1 公里，答辩时正好被指着问。
        self.amap = AMap(AMAP_CFG)

    # ------------------------------------------------ 摄像头跟着页面开关
    def drop_last_state(self, why: str) -> None:
        """换源时把**上一路**的最后一帧丢掉。

        它是"给刚连上来的页面垫一帧"用的（`hello` 之后那一发，见新连接那一段的
        注释），对**同一路**的页面是好事：连上来就有数，不闪空。
        但换源之后它就不是"这一路的数"了 —— demo 换 cam 要 load 两个权重再填满
        45 帧窗口（实测秒级），这几秒里新连上来的页面拿到的是 hello(`cam`) +
        state(**上一路 demo 的数**)，于是屏上「实时监测中」亮着、数字是演示脚本的。
        用户 2026-09-26 报的「撒谎的显示不能有」就是这一条。

        宁可空着：页面自己有"连接中 / 等待数据"的样子（`app.js` 的初始 state、
        `detail.html` 的 `NUM_CAM` 那一格），而"拿另一路的数冒充这一路"是**没有
        任何补救**的那种错 —— 屏上没有任何东西能让人看出这个数是假的。

        ⚠️ 所有读 `last_state` 的地方都已经能收 None（`voice_answer` / `voice_ask` /
        `handle` 的 say 分支都是 `is None` 早退，且都**如实说了**"还没拿到座舱状态"），
        所以丢它是安全的，不会把哪一路悄悄卡死。
        """
        if self.last_state is not None:
            print("[source] %s：丢掉上一路的最后一帧（source=%r）"
                  % (time.strftime("%H:%M:%S"), self.last_state.source))
        self.last_state = None

    async def _switch_to(self, spec: str, note: str) -> bool:
        """换到 `spec`，成功返回 True。**只改内存里的 mode/source，不碰 want。**

        和 `handle()` 里那支换源是同一套顺序（`switch_source`：先建新的、
        成了才放旧的），区别只有一个 —— 这里**不广播 hello**，
        由调用方决定什么时候广播（`open_cam` / `close_cam` 各广播一次，
        合起来一次动作一条，不会因为内部走了两层就发两遍）。

        ⚠️ 必须在事件循环里 await（里面会把建源丢进线程）。理由同
           `handle()` 那支：建 cam 源是秒级的，在这里同步调 = 整页冻结。
        """
        if self.switching:
            return False
        self.switching = True
        try:
            new_mode, new_src = await asyncio.get_running_loop().run_in_executor(
                None, switch_source, self.cfg, self.source, spec)
        except Exception as e:
            self.cam_error = f"{type(e).__name__}: {e}"
            await self.broadcast({"type": "info", "data": {
                "text": note + f"：{type(e).__name__} {e}",
                "source_switch": spec, "ok": False, "busy": False}})
            return False
        finally:
            self.switching = False
        self.mode, self.source = new_mode, new_src
        self.source_spec = spec
        self.last_severity = None
        # ⚠️ 判 spec 不判 mode，理由见 __init__ 里那一行。
        self.cam_open = (spec == self.CAM_SPEC)
        self.drop_last_state("换源")
        await self.broadcast({"type": "hello", "data": self.hello()})
        return True

    async def open_cam(self) -> bool:
        """把摄像头开起来（页面来了）。**已经是 cam 就一个字节都不动。**

        ⚠️ 这条路上**唯一**会去开设备的地方（除了用户在页面上点那颗按钮）。
           `cam` 换 `cam` 会失败（同一个设备被两个 `VideoCapture` 抢），
           所以下面那两行守卫不是优化，是正确性。
        """
        if self.cam_open or self.mode == self.CAM_SPEC or self.switching:
            return False
        # 「正在打开摄像头…」先发出去：这一步是秒级的，页面那颗按钮要在这个
        # 中间态里写「正在接入…」，否则用户会以为没点上（和手动那颗按钮同一个
        # 道理，`busy:True` 就是给前端认这个状态的，**别靠匹配中文文案**）。
        await self.broadcast({"type": "info", "data": {
            "text": "正在打开摄像头…", "source_switch": self.CAM_SPEC,
            "ok": None, "busy": True}})
        if await self._switch_to(self.CAM_SPEC, "自动接入摄像头失败"):
            self.cam_error = ""
            print(f"[cam] {time.strftime('%H:%M:%S')} 接入（页面打开）")
            return True
        return False

    async def close_cam(self, note: str) -> bool:
        """松手摄像头，回到 demo 源。**并把 `want` 一起复位成 demo。**

        ★ 2026-09-24 晚（用户选的是"严格"那一档）：原来是**不动 `want`**的 ——
          页面再开的时候照旧自动接回来。用户的要求是「只有我点接入摄像头才接入」，
          所以这次松手要**把那次点击消费掉**：页面回来是未接入状态，得再点一次。
          不清的话 `maybe_autocam` 的 `want != CAM_SPEC` 那道闸就形同虚设，
          刷新一下就自己接回来了。

        ⚠️ 这里**只被空闲超时那一处调用**（`watch_pages` 里，见下面 `[cam] 松手`
           那一行），所以改它 = 只影响"没人看了自动松手"这一条路。
           用户手动点「断开摄像头」走的是 `{"type":"source"}` 那一支，自己会写
           `hub.want`，不经过这里。

        ⚠️ **副作用（是故意的，别"顺手修"）**：`_switch_to` 会把 `self.source_spec`
           也写成传进去的 spec，所以松手之后 `hello().source_spec` 从 `"cam"` 变成
           `"demo"`。这是**对的** —— `source_spec` 的含义是"**现在跑的是哪个 spec**"，
           而此刻跑的确实是 demo（设置页那行「当前数据源」照实显示 demo）。
           关键是它**不会**挡住"再点一次接入"：驾驶监测页那颗按钮发的是**字面量**
           `'cam'`（`detail.html` 的 `camToggleClick`：`CAM_LIVE ? 'demo' : 'cam'`），
           而 `CAM_LIVE` 由 `mode` 算 —— 跟 `source_spec` 没有关系。
        """
        if not self.cam_open:
            return False
        ok = await self._switch_to("demo", note)
        # ⚠️ 放在 `_switch_to` **之后**：换源失败时 `cam_open` 还是 True，设备
        #   还在我们手里，这时把 `want` 清掉会变成"设备开着但没人认领"——
        #   下一次页面连上来 `maybe_autocam` 不动它，而过期判据又读 `want`，
        #   摄像头就再也关不掉了。换源成功才复位。
        if ok:
            self.want = "demo"
            # 收尾再看一眼：松手这 1~2 秒里要是正好有人打开了页面 ——
            # ★ 2026-09-24 晚：**这一眼现在什么都不做了**（`want` 刚被清成 demo，
            #   `maybe_autocam` 第一道闸就拦住）。**故意留着这个调用**，不要删：
            #   ① 它和 `maybe_autocam` 那个 `if not self.sockets` 守卫是一对，
            #      `_check_cam_idle.py` 有一组 case 量的就是"松手之后不许立刻又抓"；
            #   ② 以后真要做"点过一次就记住"（用户当天选的是严格那一档，不是这个），
            #      复活的入口就在这一行，而不是散在别处。
            # ⚠️ 这一眼**只对"真的有页面在看"生效** —— `maybe_autocam` 开头的
            #   `if not self.sockets` 就是为它加的：少了那行，这一眼会在
            #   "没有页面"这个最常见的情况下把刚放掉的设备又抓回来。别删。
            self.maybe_autocam()
        return ok

    def maybe_autocam(self) -> None:
        """页面连上来了 —— 该开摄像头就开，**不阻塞这一次连接**。

        ★ 2026-09-24 晚：名字里的"auto"已经不是"页面一开就自动接"了。
          用户定的规矩是「只有我点接入摄像头才接入」，而 `want` 现在**只有那颗
          按钮能改成 cam**（`--source cam` 只给 `source_spec`，初值是 demo）。
          所以这个方法现在实际管的是**"点过接入之后，刷新/翻页换一条 WS 时别把已经
          开着的摄像头弄丢"**：设备还在（`cam_open` True）就什么都不做。真掉进
          松手那 1~2 秒的缝里也**不会**接回来 —— 那条路 `want` 已经被清成 demo
          （见 `close_cam`），而用户要的就是"再点一次才接"。

        ⚠️ 不 await：开一次是秒级的，await 在这里 = 页面的 hello 要等几秒才到，
           表现为"页面卡住不动"。所以起一个任务，让 hello 先飞出去。

        🔴 **`if not self.sockets` 那行是正确性，不是优化**（2026-09-25 补）。
           调用点有两个：页面连上来（那时 `sockets` 非空），以及 `close_cam()`
           结尾那次补看。**后者的 `sockets` 恰好是空的**（就是没有页面在看了
           才松的手）。少了这一行，松手之后立刻又去抓设备：
           抓 → 12 s 空闲 → 松 → 抓，来回跳，**灯基本不灭**。
           用户报的「关闭后摄像头要关闭」就是这个病。
           ↳ 判据是**此刻有没有页面在看**，不是"有没有人打开过页面"。
           ↳ 2026-09-24 晚之后 `want` 那道闸已经能单独拦住它了，但**这行不许删**：
             它管的是"有没有人在用界面"，和 `want`（用户想不想接）是两件事。
        """
        if not self.sockets:
            return
        if self.want != self.CAM_SPEC or self.cam_open or self.cam_error:
            return
        if self._cam_task is not None and not self._cam_task.done():
            return
        self._cam_task = asyncio.create_task(self._open_cam_safe())

    async def _open_cam_safe(self) -> None:
        """`open_cam` 的壳。任务里抛出来的异常没人接，会变成
        "Task exception was never retrieved" 那种没人看的日志 —— 这里吃掉，
        并且**留下话**（`cam_error` + 一条 info），让页面上看得见。"""
        try:
            await self.open_cam()
        except Exception as e:
            self.cam_error = f"{type(e).__name__}: {e}"

    async def watch_pages(self, now: float) -> None:
        """页面开开关关 → 摄像头开开关关。**每个 tick 调一次**（见 `tick`）。

        ⚠️ `sockets` 是**所有**页面的 WS（首页/多媒体/设置都算）—— 这是故意的：
           判断的是"还有没有人在用这个界面"，不是"还有没有人在看摄像头"。
           按后者的话，从驾驶监测页翻到首页就会把摄像头掐了，而用户只是换了一页。
        """
        if self.switching:
            return
        if self.sockets:
            self.idle_since = None
            return
        if self.idle_since is None:
            self.idle_since = now
            return
        if now - self.idle_since < self.CAM_IDLE_GRACE:
            return
        if self.want == self.CAM_SPEC and self.cam_open:
            # ★ 2026-09-25 深夜：这一行是**用户那颗灯灭没灭的现场记录**。
            #   「关了浏览器摄像头还开着」这种报障，第一件事就是看这行在不在、
            #   什么时候打的 —— 没有它就只能靠猜。
            #   ⚠️ 必须在下面那行 `idle_since = now` **之前**打：先清零就量不出
            #      "页面走空了多久才松的手"，那个数正是判断余量够不够的依据。
            print(f"[cam] {time.strftime('%H:%M:%S')} 松手：没有页面在看了"
                  f"（空闲 {now - self.idle_since:.1f}s）")
            self.idle_since = now      # 关失败的话别每 1/8 秒重试一次
            await self.close_cam("没有页面在看了")

    # ---- 推 ----
    async def broadcast(self, payload: dict):
        dead = []
        text = json.dumps(payload, ensure_ascii=False)
        for ws in list(self.sockets):
            try:
                await ws.send_str(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.sockets.discard(ws)

    async def tick(self):
        now = time.monotonic()
        # ★ 2026-09-25 晚：先看页面还在不在。这一句不能挪到 `poll` 后面 ——
        #   它可能要 await 一次关摄像头（秒级），放在后面会把这一帧的 state
        #   一起拖住。放前面则是"这一帧照常推，源在下一帧换过来"。
        await self.watch_pages(now)

        # ★ 2026-09-26：「数据详情」页那两路流（`ui/web/data.html`）。
        #   **位置在 `poll()` 之前是刻意的**：串口这一路（`self.hr`，自己的读线程）
        #   和"这一帧是谁供的、出没出数"没有任何关系。放 `poll()` 后面的话，
        #   下面 `st is None` 那条 `return`（摄像头启动中 / fuse.py 还没写 CSV）
        #   会把这整帧挡掉 —— 页面上的「心率串口」会在摄像头没开的时候**一整片
        #   空白**，而板子其实一直在打。视觉那一行退而用 `self.last_state`（上一帧
        #   的），差一帧在 2 Hz 的显示上完全看不出来。
        #   2 Hz 而不是每帧：串口原文最快就是 1 Hz（`H` 全留 + `D` 每秒 1 行），
        #   视觉那一路 8 Hz 推到屏幕上只是眼花。
        #   ⚠️ 用**本 tick 开头取的那个 `now`**，不在这儿重取墙钟 —— 中间隔了几次
        #   await，慢帧上两次取钟能差出几十毫秒。
        if now - self._last_log >= 0.5:
            self._last_log = now
            await self.broadcast({"type": "log", "data": {
                # 串口原文**整份发**（不是增量）。240 行 × 约 28 B ≈ 6.7 KB，
                # 2 Hz ≈ 13 KB/s —— 和 state 帧（8 Hz × ~2 KB）同一个量级。
                # 换来的是**无状态**：页面刷新/新开自动拿全历史，不用给每个连接
                # 记游标，也就没有"游标和环不同步 → 少几行而没人发现"那一类 bug。
                "serial": self.hr.raw_lines(),
                "vision": vision_line(self.last_state),
            }})

        st = self.source.poll(now)
        if st is None:
            if self.mode == "live":
                await self.broadcast({"type": "info", "data": {
                    "text": "等待 fuse.py 写入 CSV…（先在另一个窗口跑 live_fuse.bat）"}})
            elif self.mode == "cam":
                # 摄像头要跑满一个 45 帧窗口才有第一次决策（3 秒），
                # 这期间说一句，免得让人以为卡死了
                err = getattr(self.source, "error", None)
                await self.broadcast({"type": "info", "data": {
                    "text": err or "摄像头启动中 · 正在填满第一个决策窗口…"}})
            return
        # ★ 2026-09-26 心率贴到这一帧上。**位置是刻意的：在 derive() 之前、
        #   在"源还没出数就 return"之后。**
        #   · 放在 derive() 之前：`derive()` 是原地改 `self` 再 `return self`，
        #     不碰 hr；而 `to_json()` 是 `asdict()` —— 所以贴着它的这一帧，
        #     WS 消息里自动就有 hr，通道一行都不用改。
        #   · 放在 None 那个 return 之后：源还没出数时这一帧根本不推，贴了也白贴。
        #   · **不放进各个 Source 里**：那样 cam / live / demo 每一路都要各写一遍，
        #     而且串口这一路跟"这一帧是谁供的"没有关系。
        apply_to_state(self.hr, st)
        st = st.derive(SEV_CFG, ALARM_CFG)
        self.last_state = st
        await self.broadcast({"type": "state", "data": st.to_json()})

        # 被动预警：**只在跨档那一刻**开口，不反复念。
        # ★ 2026-09-24：从"三档里挑一句"升级成**四档按档选文案**
        #   （`scripted.proactive` 现在有一张四档表，轻/中/重逐字是口径原文）。
        # 档位一变就重新计时 —— 计时器只服务发声，**显示不等它**。
        if st.severity != self.last_severity:
            self.last_severity = st.severity
            self.sev_since = now
            self.spoke_for = None
        held = now - self.sev_since
        if (st.severity != "normal" and self.spoke_for != st.severity
                and held >= self.SPEAK_HOLD.get(st.severity, 0.0)
                and now - self.last_proactive > self.PROACTIVE_COOLDOWN):
            self.spoke_for = st.severity
            self.last_proactive = now
            r = self.agent.scripted.proactive(st, now)
            if r:
                self.history.append({"role": "assistant", "content": r.text})
                await self.broadcast({"type": "say", "data": r.to_json()})

        # ★ 2026-09-25 晚：微信推送（企业微信群机器人）。**放在 tick 的最后**，
        #   两条理由：
        #     1. 上面那些 `await broadcast` 才是界面的事，推送慢一点无所谓 ——
        #        真出事的时候，先把界面这一帧送出去比先发微信重要。
        #     2. `maybe_push()` 本身不 await 网络（发送在别的协程里），所以它
        #        挂在这儿**不会**让这一帧变慢；放最后只是为了让"出异常也只影响
        #        推送"这一条成立（`loop()` 里那层 try 兜的是整帧）。
        #   ⚠️ 去重（边沿触发 + 冷却）在 `maybe_push` 里，**别在这儿再判一次** ——
        #   两边各判一半的话，改任何一边都会让"到底推没推"说不清。
        self.wechat.maybe_push(st, now)

    async def loop(self, hz: float):
        while True:
            t0 = time.monotonic()
            try:
                await self.tick()
            except Exception as e:                      # 一帧出错不能把服务打死
                await self.broadcast({"type": "info",
                                      "data": {"text": f"取数出错：{type(e).__name__} {e}"}})
            await asyncio.sleep(max(0.0, 1.0 / hz - (time.monotonic() - t0)))

    def tts_hello(self) -> dict:
        """给前端的语音现状。前端靠 `default_on` 决定喇叭按钮的初值。

        ⚠️ `default_on` 是**按当前数据源**算的，不是全局常数，所以它得在这儿
        现算 —— 运行时切源（`{"type":"source"}`）之后会重发一次 hello，
        按钮的初值就跟着换到新源上。
        """
        c = self.cfg.get("tts") or {}
        modes = c.get("enabled_in_modes") or {}
        # 漏写的源按"除 live 外都开"处理。live 单独例外是有硬原因的：
        # 那时读的是 fuse.py 正在写的 CSV，而那个进程自己就在念同一条预警
        # （src/fuse.py:697），界面再念一遍就是两个声音叠着说同一句话。
        # 所以哪怕配置里漏写了 live，也不能让它默认开口。
        default_on = bool(modes.get(self.mode, self.mode != "live"))
        prosody = {k: v for k, v in (c.get("emotion_prosody") or {}).items()
                   if not k.startswith("_") and isinstance(v, dict)}
        return {
            "default_on": default_on and self.voice.enabled,
            "voice": c.get("voice") or "自动",
            "prosody": prosody,
            "server_fallback": bool(c.get("server_fallback", True)),
            "server_ok": self.voice.enabled,
            "stats": self.voice.status(),
        }

    def hello(self) -> dict:
        key, src = resolve_key((self.cfg.get("agent") or {}).get("deepseek") or {})
        info = getattr(self.source, "info", None)
        return {
            "source": self.mode,
            "source_spec": self.source_spec or self.cfg.get("source", {}).get("mode"),
            "cam": info() if callable(info) else None,
            "agent": {
                "mode": self.agent.mode,
                "api_ready": self.agent.client.ready,
                "model": self.agent.client.model,
                "key": mask(key),
                "key_from": src,
                "error": self.agent.last_error,
            },
            "actions": ACTIONS,
            "severity_cfg": SEV_CFG,
            # 前端要靠 hold_sec 把告警横幅压住（yawn_sec 是滚动量，会在阈值
            # 上下抖），理由见 ui/state.py 里 alarms 那一段。
            "alarm_cfg": ALARM_CFG,
            # ★ 2026-09-25 晚：微信推送的现状（配没配、发出去几条、上次错在哪）。
            #   ⚠️ `status()` 里**不含 webhook 本身**，连打码的尾巴都不含 ——
            #   那条地址等同密码，页面上只需要知道"配了没有"。
            "wechat": self.wechat.status(),
            # ★ 2026-09-25 高德（见 ui/amap.py）。里面**含 JS key + 安全密钥**
            #   （`js` 那一条）—— 那两个值按高德 JS API 2.0 的设计本来就要出现在
            #   页面源码里，页面拿它建图；真正的保护是控制台里的域名白名单。
            #   🔴 **`web_key` 不在里面**（`status()` 里也没有）：那是打 restapi 的
            #   那把，只许留在服务端 —— 这里是**广播**，12 张页面都收得到。
            "amap": self.amap.status(),
            "tts": self.tts_hello(),
            # 语音输入那一路的状态（装没装、能不能干活、出路是什么）。
            # 界面靠它决定点了麦克风之后说什么 —— **按钮永不置灰**，
            # 点了就给一句具体的话，见 ui/asr.py 的 status()。
            "asr": self.asr.status(),
            # ★ 2026-09-25 常听唤醒。页面靠它决定"点了听之后能不能真的听"：
            #   模型没下就如实说，别转圈。**不预载模型**，所以这里只报"文件在不在"。
            "voice": self.voice_hello(),
        }

    def voice_hello(self) -> dict:
        """唤醒那一路的状态。**不加载模型**，只看文件在不在（`find_model_dir` 很便宜）。"""
        try:
            import voice.kws as _kws
            kw = _kws.find_model_dir()
            names = []
            try:
                kf = Path(_kws.VOICE_DIR) / "keywords.txt"
                if kf.exists():
                    names = [ln.split("@")[-1].strip() for ln in
                             kf.read_text(encoding="utf-8").splitlines()
                             if ln.strip() and not ln.lstrip().startswith("#")]
            except Exception:
                pass
            return {
                "kws_model": kw.name if kw else None,
                "keywords": names,
                # 识别那一路的现状：whisper 已就绪 / 流式模型还没下 —— 如实报
                "asr_ok": self.asr.ok(),
                "asr_engine": self.asr.engine(),
                "built": self.ear is not None,
                "note": self.ear_note,
            }
        except Exception as e:
            return {"kws_model": None, "keywords": [],
                    "asr_ok": self.asr.ok(), "asr_engine": self.asr.engine(),
                    "built": False, "note": "加载唤醒模块失败：%s: %s" % (type(e).__name__, e)}

    # ---- 耳朵（唤醒那一路） ----
    def ear_hello(self) -> dict:
        """耳朵起来之后给页面报的状态。页面拿它显示"听的是哪条识别路"。

        `kws` / `asr` 两行是**给人看的一句话**（带型号名），页面直接贴在状态行上 ——
        演示时要能一眼答出"唤醒是本地跑的、识别是 whisper 还是流式"，所以这两个
        字符串是从 `status()` 里取的**引擎自报**，不是我手写的常量。
        """
        out = self.voice_hello()
        out["built"] = self.ear is not None
        out["note"] = self.ear_note
        if self.ear is not None:
            st = self.ear.status()
            k = st.get("kws") or {}
            a = st.get("asr") or {}
            out["kws"] = k.get("engine") or k.get("why") or ""
            out["asr"] = a.get("engine") or a.get("why") or ""
            out["asr_ok"] = bool(st.get("asr_ready"))
            out["asr_partial"] = bool(a.get("partial"))
            out["state"] = st.get("state")
            out["wakes"] = st.get("wakes")
            out["round"] = st.get("round")
        return out

    async def ear_start(self, ws) -> None:
        """页面点了「听」。第一次来的时候才建唤醒器，而且**建在线程里**。

        为什么要线程：唤醒模型加载实测 0.8 s，识别那边（whisper 没就绪时）更久。
        直接在协程里建，这段时间**所有页面的 state 推送和心跳全停** ——
        表现是"点了听，整块屏幕卡住"（`ui/asr.py:787` 记过同一件事）。
        """
        self.ear_ws = ws
        if self.ear is None and not self.ear_building:
            self.ear_building = True
            try:
                loop = asyncio.get_running_loop()
                v, note = await loop.run_in_executor(None, build_ear, self)
                self.ear, self.ear_note = v, note
            except Exception as e:
                self.ear_note = "建耳朵失败：%s: %s" % (type(e).__name__, e)
                print("[voice] " + self.ear_note, file=sys.stderr)
                await voice_send(ws, {"ev": "idle", "why": self.ear_note})
                return
            finally:
                self.ear_building = False
        elif self.ear_building:
            # 第二张页面在第一次还没建完的时候也点了「听」：**等它建完**，
            # 不要再建第二份（380 MB 的模型 + 1.6% 的核，没理由来两份）。
            for _ in range(300):                        # 最多等 30 s，别死等
                if not self.ear_building:
                    break
                await asyncio.sleep(0.1)
            if self.ear is None:
                await voice_send(ws, {"ev": "idle", "why": self.ear_note or "耳朵还没起来"})
                return
        else:
            # 已经建好了（换页面/重点一次）：**状态清干净**再听 ——
            # 不清的话上一回没说完的那半句会跟着新的一轮一起进识别。
            self.ear.stop()
        print(f"[voice] {time.strftime('%H:%M:%S')} 开始听（{self.ear_note}）")
        await voice_send(ws, {"ev": "ready", "voice": self.ear_hello()})


def build_ear(hub: "Hub"):
    """把 `VoiceLoop` 建起来。**必须在别的线程里调**（见 `Hub.ear_start`）。

    两处复用是刻意的：
      · 识别的 `local` 传的是 `hub.asr` —— 服务端本来就为"语音输入"那条兜底路
        载了一份 whisper，再建一份就是**又 145 MB 内存 + 又十几秒加载**
        （`ui/voice/asr_stream.py` 的 `WhisperAsr.__init__` 里写着这一段）。
      · 配置传 `hub.cfg` 整份 —— `VoiceLoop` 自己会去取 `kws` 和 `asr` 两段。
    """
    import voice.loop as _loop

    t0 = time.time()
    v = _loop.VoiceLoop(hub.cfg or {}, local=hub.asr)
    note = "%s；唤醒：%s" % (v.asr_note, v.kws.status().get("engine") or v.kws.why)
    print("[voice] %s 耳朵就绪（%.2f s）—— %s"
          % (time.strftime("%H:%M:%S"), time.time() - t0, note))
    return v, note


async def voice_send(ws, data: dict) -> None:
    """把一条语音事件**只发给开麦的那一张页面**。

    ⚠️ 这里**故意不 broadcast**（和 `handle()` 里 `tts` 那条同一个理由）：
       音频是这张页面自己的麦克风里来的。广播出去，别的页面就会把**别人的**
       识别结果显示成自己的 —— "我没说话，我这儿弹出「我有点困」"是最容易
       让人以为见鬼的一种。答复本身是要广播的，但那走的是 `say`（对话气泡），
       不是这条通道。
    """
    if ws is None:
        return
    try:
        await ws.send_str(json.dumps({"type": "voice", "data": data},
                                     ensure_ascii=False))
    except Exception:
        pass


# 「上一句问过、等主人回一句『要』」这个窗口 = **追问窗口 + 一次断句 + 这点余量**（秒）。
#
# ★ 为什么必须装下"一次断句"（这段是 2026-09-26 补的，前面那一版写错了）：
#   主人说「要」之后，那句话**不是当场变成文字的** —— 要等他闭嘴满 10 s（静音判据，
#   `ui/voice/asr_stream.py` 的 `whisper_silence_s` / `rule1_min_trailing_silence`，
#   两条路都是 10.0），才轮得到 `finalize_text()`，再轮到这里判。
#   原来写的是 `follow_s + 5`（= 15 s），而实测一次「要的」从头到尾要 11.8 s
#   （1.3 s 话音 + 10 s 静音）—— 加上那一轮前面的几秒，正好越过 15 s。于是
#   `_check_voice_do.py` 的 J2 段当场逮到：**识别出来了、「要的」也在 `AFFIRM` 里，
#   可它还是走了模型那一路**，屏幕上什么都没发生 —— 正是用户报的那串话。
# ⚠️ 静音判据**从耳朵上现读**（`ask_window()` 里的 `status()["endpoint_silence_s"]`），
#   不在这儿再抄一个 10：抄出来就是第二份会走样的数（本项目的老毛病，见
#   `_check_voice_do.py` 的 H3 段 —— 两份手抄的表必须有一处摆在一起比）。
# ⚠️ 这和 `ear_do` 那 1.5 s **不是一回事**：那个是"页面回执有多快"，这个是
#   "主人想一下再说要 + 他闭嘴之后还要等一次断句" —— 人的量级 + 产品的判据，
#   别拿机器的量级去卡它。
# ⚠️⚠️ 我第一版写的是模块级 `PENDING_S = _loop.FOLLOW_S + 5.0`，**服务端当场起不来**
#   （`NameError: name '_loop' is not defined`，`runs/_check_voice_do_srv.log` 里那句话）：
#   `import voice.loop` 是**在 `build_ear()` 函数体里**的（懒建耳朵，见那一段注释），
#   模块级根本看不到这个名字。而"干脆挪到顶层 import"会顺带把 sherpa_onnx 拖成
#   **开机就加载** —— 那正是懒建要躲的东西。所以改成：**期限用耳朵上那个活的值**
#   （`ask_window(ear)` 现读），本常量只留那点余量。
#   顺带比原来更准：`follow_s` 和静音判据都是能被配置/自测改的（`VoiceLoop(follow_s=…)`、
#   `asr_stream.py` 里那两个 10.0），写成模块常量的话，改了判据、兑现期限还钉死在旧数上。
# ⚠️ 这个期限是**下限**，不是最终那个：注册的这一刻主人还没听见问句。页面把那句话
#   念完之后（`voice_spoken` 受理那一支）会**重新起算**一次。
ANSWER_MARGIN_S = 5.0


def ask_window(ear) -> float:
    """「他答一句『要』」这件事，从**他听得见那句问话**起算，最多给多少秒。

    = 追问窗口（他得先听见、再想一下）+ 一次断句（那 10 s 静音判据）+ 余量。

    ⚠️ 读不到就退回 10.0：假耳朵（`_check_barge_in.py` 的 `FakeAsr`）没有这个键，
       真耳朵一定有（`asr_stream.py` 的 `status()`）。**退回不等于可以瞎写** ——
       真耳朵在的时候它总是现读的，改判据这边跟着变。
    """
    ep = 10.0
    try:
        v = (ear.status() or {}).get("endpoint_silence_s")
        if v:
            ep = float(v)
    except Exception:                                    # noqa: BLE001
        pass
    return float(getattr(ear, "follow_s", 0.0) or 0.0) + ep + ANSWER_MARGIN_S


def take_pending(hub: "Hub", text: str) -> str:
    """这一句是**在回答小瑞上一句的提议**吗？是就吐出那个动作 id（并把它消费掉）。

    ★★ 2026-09-26：用户报的那串话里，最刺眼的是最后一下 —— 小瑞问「要不要我帮您
       导航到最近的服务区？」，主人答「要」，然后**什么都没发生**。前面两句当时是
       模型现编的（`detect_action('给我导航')` 回空串，落到了模型那一路），服务端
       根本没发起过动作；而"要"这个字在任何一张判据表里都不存在，于是它也只是一句话。

    现在这一半由这儿管：`voice_ask` 问出那一句时把动作记进 `hub.pending_do`，
    主人回一句同意（`xiaorui.is_affirm`）就**真的去执行**。

    ⚠️ **一次性**：不管这次是不是同意，进来就把它清掉。主人没说"要"而是说了别的
       （「今天天气不错」），那件事就作废 —— 留着它，三句之后一句「好」会把一件主人
       早就忘了的事做出来（而且是**跳页**那种大动作），那比不做还糟。
    ⚠️ 状态这一条**不是** `in ("follow", "listen")`（那是我第一版写的，写错了）。
       这个函数的**唯一**调用点是 `voice_answer`，而它只从耳朵的 `need_answer` 事件来
       —— 那一刻 `finalize_text()` 刚把状态置成 **THINK**（`ui/voice/loop.py:307`）。
       照 follow/listen 判的话它**永远**不成立，「要」一辈子执行不了，而那正是用户
       报的那件事。2026-09-26 由 `_check_voice_do.py` 的 J2 段当场逮到：识别出「要的」、
       识别前状态也确实是 follow，可它还是走了模型那一路。
       这一条真正要拦的是"这句话不是耳朵送上来的"（打字走 `handle()` 的 `say` 那一支，
       压根到不了这儿）—— THINK 就是那个证据，顺带把"轮次早翻篇了"的竞态也挡掉。
    ⚠️ 判据只用 `is_affirm`（整句相等），不用 `in`：见 `xiaorui.AFFIRM` 上面那段。
    """
    cur = hub.pending_do
    hub.pending_do = None
    if cur is None:
        return ""
    aid, until = cur
    if not is_affirm(text):
        return ""
    ear = hub.ear
    if ear is None or ear.state != "think":
        return ""
    if time.monotonic() > until:
        return ""
    print(f"[voice] {time.strftime('%H:%M:%S')} 主人应了上一句的提议（{aid}）——去执行")
    return aid


async def voice_do(hub: "Hub", ws, aid: str, timeout: float = 1.5) -> dict:
    """让**开麦的那一张页面**去做一件事，并且**等它回执**。

    ★ 为什么必须是"单播 + 等回执"，而不是广播一条命令：
        · 广播 = 每一个开着的标签页各执行一遍。12 张页面都挂了 `player.js`，
          各有自己的 `new Audio()`，结果就是同一首歌放两遍、差几百毫秒 —— 回声。
          `player.js:56-60` 那段注释记的就是这件事（它的存档故意走 `sessionStorage`，
          也是为了让标签页之间互不干扰）。
        · 不等回执 = 又回到「说了但不知道做没做成」，那就没法决定该说哪句话
          （见 `ScriptedAgent.act_reply`）。

    返回页面的回执原文（`ok`/`why`/各自的数据）。**超时或压根没有页面时回
    `{"ok": False, "why": "timeout"|"no_page"}` —— 调用方必须按失败处理**，
    不许因为"大概会成"就跳过这一步。

    ⚠️ 超时给得短（1.5 s）是有意的：这是**本地回环**，正常量级是毫秒；卡住的
       是站在车里的主人的等待。宁可当场说"没放上"，也不要让人干站着。
    """
    if ws is None or hub.ear is None or hub.ear_ws is not ws:
        return {"ok": False, "why": "no_page"}
    seq = hub.ear.round
    fut = asyncio.get_running_loop().create_future()
    hub.ear_do = (seq, aid, fut)
    await voice_send(ws, {"ev": "do", "id": aid, "seq": seq})
    try:
        return await asyncio.wait_for(fut, timeout)
    except asyncio.TimeoutError:
        return {"ok": False, "why": "timeout"}
    finally:
        # ⚠️ 只清掉**自己那一个**：这 1.5 s 里完全可能已经翻了一轮、新的等待
        #    已经把自己挂上去了，无脑置 None 就是把别人的等待掐死。
        if hub.ear_do is not None and hub.ear_do[2] is fut:
            hub.ear_do = None


async def voice_events(hub: "Hub", ws, evs) -> None:
    """把状态机吐出来的事件翻译成给页面的话。该转文字的转文字，该问大脑的问大脑。

    ⚠️ 两个**阻塞调用**都必须丢线程，否则**所有页面**的 state 推送会跟着卡：
         · `finalize_text()` —— whisper 整段识别，0.5~2 s
         · `agent.respond()`  —— 一次 DeepSeek 往返，几百毫秒到几秒
       而 `feed()` 本身**不丢线程**：唤醒实测 1.6 ms / 100 ms 帧（1.6% 一颗核），
       每 100 ms 一次的高频调用，为它多一次线程调度不值当。
    """
    for e in evs:
        t = e.get("type")
        if t == "wake":
            # ★ 2026-09-26（B2）：**主人是在小瑞念的过程中叫醒它的。**
            #   那先把这一句掐掉，再喊醒 —— 顺序不能反：`ev:"halt"` 让页面
            #   `XQ.tts.halt()`（推 `_seq` 再 `cancel()`，理由写在 live.js 里），
            #   页面收到 `ev:"wake"` 就已经是"闭嘴 + 开始听"的样子了。
            #   反过来的话，屏上会留着一句永远念不完的话，而且它还在念的音
            #   会和主人接下来的话一起被麦克风收进去。
            #
            #   ⚠️ 旧看门狗**当场收工**：它守的是"那句被掐掉的话念完了没有"，
            #   而那句话已经不存在了。新一轮的看门狗由 `voice_answer` 自己架
            #   （它开头就会 `cancel()` 一次，这里提前清掉只是让日志干净些）。
            if e.get("from_speak"):
                if hub.ear_task is not None and not hub.ear_task.done():
                    hub.ear_task.cancel()
                await voice_send(ws, {"ev": "halt", "why": "主人喊我了"})
            await voice_send(ws, {"ev": "wake", "word": e.get("word") or "",
                                  "asr_ready": e.get("asr_ready"),
                                  "asr_why": e.get("asr_why") or ""})
        elif t == "partial":
            await voice_send(ws, {"ev": "partial", "text": e.get("text") or ""})
        elif t == "heard":
            await voice_send(ws, {"ev": "heard", "text": e.get("text") or ""})
        elif t == "idle":
            await voice_send(ws, {"ev": "idle", "why": e.get("why") or ""})
        elif t == "need_text":
            # 收尾转文字。**线程里**（见上面）。递归只有一层：`finalize_text()`
            # 只会回 heard / need_answer / idle，不会再回一个 need_text。
            await voice_send(ws, {"ev": "thinking"})
            more = await asyncio.to_thread(hub.ear.finalize_text)
            await voice_events(hub, ws, more)
        elif t == "need_answer":
            await voice_answer(hub, ws, e.get("text") or "")


async def voice_answer(hub: "Hub", ws, text: str) -> None:
    """把识别出来的话交给大脑，把答复发给页面。

    ⚠️ 答复走的是**和打字那条完全一样的广播**（`{"type":"say"}`），理由有两条：
      1. 对话气泡、表情、`backend` 提示这些**一处都不用重写** —— 语音和打字
         在小瑞看来是同一件事，只是"怎么进来的"不同。
      2. 现场演示时静音、没插音箱、语音开关关着都发生过：文字必须出现在
         屏幕上，功能才是可验证的（`wake.js` 文首第 4 条纪律）。
    唯一多带的一个字段是 `"voice": True` —— 页面靠它知道这条是语音来的。
    """
    st = hub.last_state
    if st is None:
        # 座舱状态还没上来（比如摄像头刚开、第一帧判决没到）。**如实说一句**，
        # 不能默默丢掉：用户对着车里说了一句话，什么都不发生是最坏的结果。
        # ⚠️ `follow=False`：这一句**根本没念出来**（没有 TTS，只有屏幕上一行字），
        #    开追问窗口就成了"它一个字没说，却竖着耳朵等你接话"。
        hub.ear.answer_done(follow=False)
        await voice_send(ws, {"ev": "idle", "why": "还没拿到座舱状态，等一秒再说"})
        return
    hub.history.append({"role": "user", "content": text})
    if hub.ear_task is not None and not hub.ear_task.done():
        hub.ear_task.cancel()                    # 上一轮的看门狗收工
    now = time.monotonic()
    # ★ 2026-09-25：**动作类的意图不走模型。**
    #   用户报的是「我给它命令了 他不做」，根因是这条链路只产文本。所以凡是
    #   "该有件事发生"的意图，一律由服务端**先去让页面做**、拿到回执再组话
    #   （见 `voice_do` / `ScriptedAgent.act_reply`）：
    #     · 走模型的话，模型只会说「这就给您放」（规矩 7 允许），而没人去放；
    #     · 而且这句话和真实结果**不可能一致** —— 模型根本不知道放没放成。
    #   `detect_intent` 的意图表里 music 排在 greeting 前面，所以
    #   「你好小瑞 给我放个音乐」命中的是 music，不是招呼。
    # ★★ 2026-09-26：识别"有没有动作"这件事从 `detect_intent` 换成了
    #   `detect_action`（见它的注释）—— 因为用户要来"对这个网页所有东西的操控权"：
    #   除了放音乐和查服务区，还要能**打开任何一页**、能**真导航过去**。
    #   ⚠️ 换的是**判据**不是行为：`detect_action` 里放音乐那一支仍然调 `detect_intent`，
    #      所以原来命中的那些话一个字都没变。
    # ★★ 2026-09-26：**先问"这是在回答上一句的提议吗"**，再问"这句话自己是什么动作"。
    #   语序就是优先级：主人说「要」时，那句话本身**没有任何动作**（`detect_action`
    #   回空串），它的全部意义在于回答上一句。反过来先走 `detect_action` 的话，
    #   「要」永远落给模型 —— 用户报的正是这一下。
    intent = take_pending(hub, text) or detect_action(text)
    if intent == "music":
        res = await voice_do(hub, ws, "music")
        r = hub.agent.scripted.act_reply(st, "music", res, now)
    elif intent == "nearby":
        # ★ 2026-09-25：问服务区**也不走模型**。分两步：
        #   ① 让开麦那张页面给坐标（定位只有浏览器才知道）；
        #   ② 拿坐标问高德（`ui/amap.py`），**按真结果组话**。
        #   ⚠️ 超时给 4 s（放音乐那条是 1.5 s）：页面手上要是没有缓存坐标，
        #      它得现调一次 `getCurrentPosition`，那条路的量级就是几秒。
        #      常态下页面进来时已经查过一次、缓存是热的，仍是毫秒级。
        res = await voice_do(hub, ws, "nearby", timeout=4.0)
        drew = bool(res.get("drew"))
        lat, lng = res.get("lat"), res.get("lng")
        if not res.get("ok"):
            pass                      # 页面已经给了 why（no_geo / timeout / …）
        elif lat is None or lng is None:
            # 页面说成了、却没给坐标 —— 当成"定位拿不到"处理，别拿 None 去查。
            res = {"ok": False, "why": "no_geo", "drew": drew}
        else:
            j = await hub.amap.nearby(float(lat), float(lng))
            res = dict(j)
            res["drew"] = drew        # 页面那一半的结果要留下，severe 那句靠它
        r = hub.agent.scripted.act_reply(st, "nearby", res, now)
    elif intent:
        # ★★ 2026-09-26：**打开某一页 / 导航过去**（`detect_action` 的那两类）。
        #   用户原话：「我让它导航它肯定真导航啊 直接跳转这些啊」。
        #   由**开麦那一张页面**执行（`location.href`），服务端只等一句回执。
        # ⚠️ 超时 1.5 s（和放音乐同档）：这两个动作页面**当场**就能回话 —— 跳转是
        #   本地的事，不像定位要等 `getCurrentPosition`。
        # ⚠️ 回执给的是"页面答应了这个动作、这就去做"，**不是"已经做完了"**：
        #   页面一跳，这条 WebSocket 就断了，服务端再也验不到结果。所以这两类的
        #   话一律是正在做（见 `ScriptedAgent.act_reply`），**别照着 music 那条
        #   去用完成时** —— 主人抬头看屏幕，屏幕还是原来那一页就穿帮了。
        res = await voice_do(hub, ws, intent)
        r = hub.agent.scripted.act_reply(st, intent, res, now)
        # ★★ 2026-09-26：**念不念，由页面那句回执说了算 —— 不是由 intent 说了算。**
        #   原来这里写死 `jump=True`，理由是"这两个动作页面马上要跳"。那句话对
        #   **成功跳走**的那一趟是对的（页面 180 ms 后就被跳走，`speechSynthesis`
        #   随 document 一起没了，念出来只有半句，那条"念完了"的回执也永远不来）；
        #   可页面**经常不跳**，而下面这三种情况写死 `jump=True` 就是**哑巴**：
        #     · `{ok:true, here:true}` —— 主人已经站在导航页上，就地查（「要的」
        #       那一趟走的就是这条，`rest_stop_here`）。J2 段当场逮到：do 发了、
        #       回执也对了，屏上却一个字都没有。
        #     · `{ok:true, same:true}` —— 主人已经在那张页面上（`go_same`）。
        #     · `{ok:false, why:…}` —— 页面**拒绝了**这个动作（`no_target` 等）。
        #       这一档最不该沉默：主人喊了一句，屏幕上既没跳也没声，只有一行气泡。
        #   所以判据是"**页面这一趟真的要跳走吗**"：答应了（`ok`）**且**没有说
        #   "我就在这一页上"（`here`/`same`）。不跳的那几档照常念，走 SPEAK +
        #   追问窗口的常规那一套（`voice_say(jump=False)`）。
        #   ⚠️ 用户拍板的「跳过去 + 问一句」落在**跳走**那一支上 —— 顺序**必须**是
        #      "先跳、后说"，反过来的话那句问话必然被跳页掐断，「要」也就永远落空。
        #   ⚠️ 超时那一档（`why="timeout"`，`ok` 是假的）也走"念"：那一刻**确实不
        #      知道**页面跳没跳，而那一句话本身就把这份不确定说出来了（「我没收到
        #      页面的回执，导航页**可能**没打开」）—— 比一个字都不说要好。
        jumping = bool(res.get("ok")) and not res.get("here") and not res.get("same")
        await voice_say(hub, ws, r, text, jump=jumping)
        return
    else:
        r = await asyncio.to_thread(hub.agent.respond, st, text, hub.history, now)
    await voice_say(hub, ws, r, text)


async def voice_say(hub: "Hub", ws, r, text: str, jump: bool = False) -> None:
    """把一句组好的答复**交出去**：画气泡、进 SPEAK、让开麦那一页念、架看门狗。

    抽出来是因为现在有**两个**调用方：`voice_answer`（主人说了一句）和
    `voice_ask`（跳过去之后那一页来要一句话，见 `{"type":"ask"}`）。抄第二份的
    结果一定是"两边慢慢长歪" —— 而这条尾巴上每一行都是踩过坑的（见下面那些 ⚠️）。

    `jump=True` = **这一页马上就要被跳走**（`go:` / `rest_stop`）：不念、不进 SPEAK，
    只画气泡，当场把状态机收回 IDLE。理由见那一支的注释。
    """
    hub.history.append({"role": "assistant", "content": r.text})
    hub.history = hub.history[-12:]
    payload = r.to_json()
    payload["user"] = text
    payload["voice"] = True
    # 见 `wake.js`：开麦的那一张页面**自己念**（它要拿"念完了"回执去把状态机
    # 放回 IDLE），所以这一条广播只画气泡、不出声。
    payload["silent"] = True
    await hub.broadcast({"type": "say", "data": payload})
    if jump:
        # ⚠️ 不进 SPEAK，也**不架看门狗** —— 这一轮压根没有"念"这件事。
        #    但状态机**必须**从 THINK 里出来：THINK 那一支是"只攒不识别"，
        #    停在那儿的话 KWS 就再也不喂了（表现是"跳完页之后怎么叫都不应"）。
        #    所以当场收回 IDLE。页面随后一跳，WS 断掉，`ear.stop()` 再清一遍。
        hub.ear.answer_done(follow=False)
        return
    # ★ 上面那句 `to_thread` 是**几秒**的（一次 DeepSeek 往返）。这几秒里这一轮
    #   完全可能已经结束了：用户按了停、点掉了「听」、页面走了，或者看门狗先到
    #   把状态机收回了 IDLE。这时候**绝不能进 SPEAK、也不能念** ——
    #   进了 SPEAK 就再没人把它放出来（表现是"之后怎么叫都不应"），而念出声的话
    #   没有回声消除、它自己的声音会被当成新一轮的输入。
    #   自测脚本 `_check_voice_ws.py` 逮到过这一下（第二轮反过来叫醒了第一轮）。
    # ⚠️ 判据是"**这一轮还在它该在的那一档**"，不是"== idle"：`finalize_text()`
    #   把状态留在 THINK，所以走到这儿时它就应该是 think。原来写成 `== "idle"`
    #   是因为当年"念完"只有 IDLE 一个去处 —— 现在**念完还有 FOLLOW**（追问窗口），
    #   而 page 那条迟到的 `voice_spoken`（上一轮的 TTS 回执）正好会把人送进
    #   follow。照旧判的话，这一句**上一句的答复**会在主人已经开始说下一句的时候
    #   念出来 —— 抢话，而且麦克风还热着（follow 是真在喂识别器），它自己的声音
    #   就变成主人的话了。
    if hub.ear.state != "think":
        print(f"[voice] {time.strftime('%H:%M:%S')} 答复来迟了（这一轮已经收了，"
              f"现在在 {hub.ear.state}），只画气泡不念：{r.text[:24]}…")
        return
    # ★★ 2026-09-26：**"小瑞在念的时候，主人喊唤醒词能不能把它打断"** —— 这一句
    #   就是要开的那个闸（`ui/voice/loop.py` 文首第 1 条 + `barge_in_ok`）。
    #   开它的**前提是"这一句掐得断"**：浏览器那条路（`XQ.speak` →
    #   `speechSynthesis.cancel()`）掐得断，所以开；服务端兜底那条路掐不断
    #   （`ui/tts.py` 的 `stop()` 是一次性闩锁），页面一旦走了兜底就会回一条
    #   `{"type":"tts"}`，`handle()` 那条分支再把闸关回去。
    #   ⚠️ **自激挡板**：这一句里要是带了唤醒词（「你好小瑞」），闸**不能开** ——
    #      否则它自己念出来就把自己叫醒了（没有 AEC，喇叭的声音就是从麦克风回去的）。
    #      走模型那条路的话文案是它现编的，只有这一道拦得住。
    ok = not any(w and w in r.text for w in hub.ear.wake_words())
    if not ok:
        print(f"[voice] {time.strftime('%H:%M:%S')} 这句答复里带了唤醒词，"
              f"这一轮不开抢话的闸：{r.text[:24]}…")
    hub.ear.barge_in_ok = ok
    # 进 SPEAK：**从这一刻起喂进来的 ASR 音频一个字节都不处理** —— 没有回声消除，
    # 小瑞的声音会从麦克风回来（`ui/voice/loop.py` 文首第 1 条）。
    # （唤醒词那一层是开的，见上面那个闸。）
    hub.ear.speaking()
    await voice_send(ws, {"ev": "reply", "text": r.text, "emotion": r.emotion,
                          "backend": r.backend, "user": text,
                          # 轮次号跟着答复一起下去：页面念完之后要**原样带回来**
                          # （`voice_spoken` 的卫兵，见 `handle()` 那条分支）。
                          # ⚠️ 页面自己算不出轮次 —— 它是服务端的东西。
                          "round": hub.ear.round})
    # 看门狗：见 `VoiceLoop.answer_done()` 的说明 —— "念完了"这个信号**不保证
    # 会来**（服务端兜底那条路只报"排上队"），所以到点没回执就自己收尾，
    # 而且**如实告诉页面**自己收的尾。估时按中文 ~5 字/秒，留足余量。
    hub.ear_task = asyncio.create_task(_voice_watchdog(hub, ws, hub.ear.round,
                                                      6.0 + len(r.text) * 0.35))


async def voice_ask(hub: "Hub", ws, req: dict) -> None:
    """**刚跳过来的那一页**来要一句话：小瑞该说"要不要我导到最近的服务区？"。

    ★★ 2026-09-26：用户拍板的是「跳过去 + 问一句」。这一条就是那个"问一句"的入口。

    🔴 **为什么不在跳之前念**（这是直写必然踩的坑，不是设计偏好）：
       `wake.js` 的 `go:`/`rest_stop` 分支回执之后 **180 ms** 就 `location.href`。
       页面一拆，`speechSynthesis` 随 document 一起没了 —— 那一句会被**拦腰切掉**，
       而且"念完了"那条回执（`voice_spoken`）**永远不会来**（页面已经没了），
       于是追问窗口开不了、主人那句「要」必然落空。
       所以跳之前那一轮**不念**（`voice_say(jump=True)`：只画气泡 + 当场收 IDLE），
       由跳过来之后**活着的那一页**在麦克风起来之后发一条
       `{"type":"ask","id":"rest_stop","origin":…}`，由这儿组话。

    `req["origin"]` = 页面此刻**手上真有的起点**（`XQ.nav.originNow()`），没有就是
    null。它决定两件**完全不同**的事（见 `ScriptedAgent.ask_reply`）：
      · 有起点 → 说 `SCRIPT["ask_rest_stop"]`（是问句），**并且**把
        `hub.pending_do` 挂上 —— 主人回一句「要」就真去查、真算路线；
      · 没有起点 → 说 `ACT_FAIL["nearby"]["no_geo"]`（早就写好的实话，不含数字），
        **不挂** —— 主人就算说「要」也没坐标可查。⚠️ 这一档**不许**拿问句顶上：
        听着像答应了就能成，实际上查不到，那就是新的一种"话和事不一致"。

    ⚠️ 认不出的 id、或者没有座舱状态：**什么都不说**（回一条 `idle` 说明原因）。
      别自己编一句兜底 —— 这个项目里"遇到不知道的事就编一句"正是要修的病。
    """
    aid = str(req.get("id") or "")
    origin = req.get("origin") or None
    st = hub.last_state
    if hub.ear is None or hub.ear_ws is not ws:
        return                                   # 不是开麦的那张页面，见 voice_send
    if st is None:
        await voice_send(ws, {"ev": "idle", "why": "还没拿到座舱状态，这一句先不说了"})
        return
    now = time.monotonic()
    r = hub.agent.scripted.ask_reply(st, aid, origin, now)
    if r is None:
        print("[voice] 页面要了一句我不认识的话（id=%r）——不说" % aid)
        return
    if origin and aid == "rest_stop":
        # 只在这儿、也只在这一档挂"待确认动作"（见 `take_pending`）。
        # ⚠️ 期限从**耳朵上那个活的值**算（`ask_window`），不用模块常量：
        #    见 `ANSWER_MARGIN_S` 上面那段（写成常量时服务端压根起不来）。
        # ⚠️ 这里算出来的期限是**下限**：真正的窗口在页面把那句话念完之后会**重新
        #    起算**（`voice_spoken` 那一支）。因为注册的这一刻主人还没听见那句话。
        due = now + ask_window(hub.ear)
        hub.pending_do = (aid, due)
        print(f"[voice] {time.strftime('%H:%M:%S')} 问了主人一句（{aid}），"
              f"{due - now:.0f} s 内说「要」就真去查")
    # 这一轮**不是**主人说的，history 里记一条自己问的 —— 让模型那一路（要是
    # 之后接上话）知道小瑞刚问过什么。`text` 传空串：`voice_say` 靠它回填气泡上
    # 的"我问了什么"，而这一轮主人还没说。
    hub.history.append({"role": "user", "content": "（小瑞主动问的）"})
    # ⚠️ **必须先摆状态再交给 `voice_say`**：那一趟有一道不能删的守门（只在
    #    `state == "think"` 时才念），而这一句不是主人刚说完话来的，状态还停在
    #    这一页 `voice_start` 之后的 IDLE 上。漏了这一步的表现是"跳过去之后
    #    一个字都不说，气泡也是空的"，而且不报错。见 `VoiceLoop.expecting`。
    hub.ear.expecting()
    await voice_say(hub, ws, r, "")


async def _voice_watchdog(hub: "Hub", ws, rnd: int, sec: float) -> None:
    """到点还没收到 `voice_spoken` 就把状态机收回 IDLE。

    ⚠️ 认的是**轮次号**不是时间：超时醒来时那一轮可能早就念完、用户也早又叫醒
    了一轮，这时候再去 `answer_done()` 就是把**别人正在说的那一轮**掐掉。
    """
    try:
        await asyncio.sleep(sec)
    except asyncio.CancelledError:
        return
    if hub.ear is None or hub.ear.round != rnd:
        return                                   # 已经翻篇了，别动
    # ⚠️ `follow` 也要放行：状态是它说明**回执早就到了**（只有真收到
    #    `voice_spoken` 才会进追问窗口），这一轮根本轮不着看门狗收尾。
    #    不认它的话，看门狗到点会把主人正在里面说话的追问窗口**当场掐掉**。
    if hub.ear.state in ("idle", "follow"):
        return
    # ⚠️ `follow=False`：到点还没回执 = **没有证据说它已经念完了**，它很可能
    #    还在说话。这时候放开麦克风，它自己的声音会被当成主人的话（没有回声消除）。
    hub.ear.answer_done(follow=False)
    await voice_send(ws, {"ev": "idle", "why": "念完了没等到回执，已经回去听了"})


async def voice_pcm(hub: "Hub", req: dict, ws) -> None:
    """页面送来一片 100 ms 的音频。**每一次说话都从这儿过。**"""
    ear = hub.ear
    if ear is None or hub.ear_ws is not ws:
        return                                   # 不是开麦的那张页面，见 voice_send
    try:
        raw = base64.b64decode(req.get("b64") or "")
        x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    except Exception as e:
        # 解不开就说出来。**装作没发生**的话，表现是"说了没反应"，
        # 而原因（丢片/编码坏了）已经在门外了，查无可查。
        await voice_send(ws, {"ev": "gone", "why": "这一片音频解不开：%s" % e})
        return
    try:
        evs = ear.feed(x)
    except Exception as e:
        # 状态机自己抛错 = 这条链路坏了，**必须让页面看见**，不能吞
        await voice_send(ws, {"ev": "gone", "why": "音频处理出错：%s: %s"
                              % (type(e).__name__, e)})
        return
    if evs:
        voice_enqueue(hub, ws, evs)


def voice_enqueue(hub: "Hub", ws, evs) -> None:
    """把状态机吐出的事件**排进队列**，交给常驻协程 `_voice_pump` 串行处理。

    🔴 **为什么不能在这儿直接 `await voice_events(...)`** —— 2026-09-25 自测
       真逮到的一次**循环等待**：
         · `voice_events` 里有一处要**等页面的回执**（`voice_do` → 等 1.5 s）；
         · 而页面的回执是**同一个 WebSocket 读循环**在派发的
           （`ws_handler` 的 `async for msg in ws` → `handle()` → 这儿）。
       在读循环里等读循环，那条回执**永远读不进来**，必然超时 ——
       而"超时"在小瑞那儿是一句**具体的假话**：「我没收到播放的回执，可能没放上」。
       实测那一刻的状态是：歌**真的放出来了**（页面收到 `do` 就去放了），
       小瑞却说没放上。又一次"话和事实不一致"（和 `wechat.py` 文首那三条同一个血统）。

    ★ 用**队列 + 一个常驻协程**、而不是每个事件 `create_task` 一下：
      事件之间有严格的先后（`heard` 必须在 `reply` 前面，一轮只许组一次话），
      并发跑 `voice_events` 会把"这一轮"和"上一轮"搅在一起。队列同时保住了
      原来那个"阻塞"顺带给到的**串行**性质 —— 换的是"谁来等"，不是"要不要等"。
    ⚠️ `ear.feed()` 仍然留在读循环里**同步**跑（实测 1.6 ms / 100 ms 帧）：它才是
      驱动状态机的那一步，挪进队列反而会打乱帧的先后。
    """
    if hub.voice_q is None:
        hub.voice_q = asyncio.Queue()
    hub.voice_q.put_nowait((ws, evs))
    if hub.voice_pump is None or hub.voice_pump.done():
        hub.voice_pump = asyncio.create_task(_voice_pump(hub))


async def _voice_pump(hub: "Hub") -> None:
    """队列的消费者：串行跑 `voice_events`。

    ⚠️ 这个协程**跌倒了必须自己爬起来**：它一死，所有语音事件就只是安静地排队、
    屏幕上什么都不会发生 —— 那看起来和"麦克风坏了"一模一样，而且再也不会好。
    """
    while True:
        ws, evs = await hub.voice_q.get()
        try:
            await voice_events(hub, ws, evs)
        except asyncio.CancelledError:
            raise
        except Exception as e:                   # noqa: BLE001
            print("[voice] 处理事件时出错：%s: %s" % (type(e).__name__, e))
            await voice_send(ws, {"ev": "gone", "why": "处理事件出错：%s: %s"
                                  % (type(e).__name__, e)})


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    hub: Hub = request.app["hub"]
    ws = web.WebSocketResponse(heartbeat=25)
    await ws.prepare(request)
    hub.sockets.add(ws)
    # ★ 页面的来去是"摄像头什么时候松手"的**唯一触发条件**，所以要看得见。
    #   低噪：只有 0 → 1 和 1 → 0 那两下打，翻页/刷新时你看得见"走了 0.03 s 就
    #   回来"（所以宽限 3 s 完全够），关浏览器时看得见"走空了，3 s 后松手"。
    gone = hub.idle_since
    if len(hub.sockets) == 1:
        print(f"[cam] {time.strftime('%H:%M:%S')} 页面打开"
              + (f"（上一个是 {time.monotonic() - gone:.1f}s 前走的）"
                 if gone is not None else ""))
    # ★ 2026-09-25 晚：有人来了。先取消"空闲"这个状态（晚一步的话，
    #   `watch_pages` 可能正好在这一刻把摄像头关掉），再把 hello 发出去。
    hub.idle_since = None
    await ws.send_str(json.dumps({"type": "hello", "data": hub.hello()},
                                 ensure_ascii=False))
    if hub.last_state is not None:
        await ws.send_str(json.dumps({"type": "state", "data": hub.last_state.to_json()},
                                     ensure_ascii=False))
    # ★ 2026-09-24 晚：这一眼**不再开摄像头**了（用户：「只有我点接入摄像头才接入」，
    #   `want` 只有那颗按钮能改成 cam）。现在它管的是"点过接入之后刷新/翻页，
    #   别把已经开着的设备弄丢"。**位置仍必须在 hello 之后**：万一将来在这一眼上
    #   真开了设备，开一次是秒级的，放 hello 前面就是页面卡几秒什么都收不到。
    hub.maybe_autocam()
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                continue
            try:
                req = json.loads(msg.data)
            except Exception:
                continue
            await handle(hub, req, ws)
    finally:
        hub.sockets.discard(ws)
        # ★ 开麦的那张页面走了（关标签页、刷新、切页）。音频从这一刻起不会再来了，
        #   所以状态机必须**收干净**：不收的话它可能停在 SPEAK/THINK 等一个永远
        #   不会来的回执，而下次有人点「听」时 `ear_start` 又只是 `stop()` 一下 ——
        #   表现是"刷新之后叫不醒，再刷新一次又好了"这种没法复现的坏法。
        # ⚠️ 这里**不能 `stop()` 整个耳朵**（模型要留着，下次点「听」是秒开的），
        #   只把状态和缓冲清掉。
        if hub.ear is not None and hub.ear_ws is ws:
            hub.ear.stop()
            if hub.ear_task is not None and not hub.ear_task.done():
                hub.ear_task.cancel()
            hub.ear_ws = None
            print(f"[voice] {time.strftime('%H:%M:%S')} 开麦的页面走了，耳朵停下")
        if not hub.sockets:
            print(f"[cam] {time.strftime('%H:%M:%S')} 页面走空"
                  f"（{hub.CAM_IDLE_GRACE:.0f}s 后松手，除非又有人回来）")
    return ws


# ---------------------------------------------------------------- 曲库（内置 + 本机）
# 多媒体页的歌有**两个来源**，合成一张表发给前端：
#
#   1. **内置** `ui/media/`：30 首 91 MB，**跟着项目走**。挑的是用户曲库里体积最小的
#      那 30 首（加载快、单首最大 5.3 MB，歌手是散的 —— 27 个歌手 / 30 首），
#      拷它们的是一次性脚本 `_scratch/_add_bundled_music.py`。
#      存在的理由：**答辩机器上多半没有用户的音乐目录**，没有这一份，这一页就是
#      一个空列表 + 一句"没找到目录"。
#   2. **本机** `config.json` 的 `media.dir`（默认 `D:\CloudMusic`）：剩下的 125 首。
#
# ⚠️ **顺序就是优先级**：`music_roots()` 回的顺序，既是曲目表里谁排在前面的依据，
#    也是 `/music/<名>` 去哪儿找这个文件的依据。两处**必须是同一个顺序** ——
#    不一致的表现是"点列表第 3 行放出来的是另一首"。
# ⚠️ 内置那份是**从用户目录里拷的**，所以两边有 30 个同名文件。按**文件名去重、
#    内置优先**：155 首还是 155 首，不会变成 185。**不要给内置的文件改名**，
#    改名就等于去重失效、同一首歌在列表里出现两遍。
# ⚠️ 这一节对外只有两条接口：列表 `/music.json`、取文件 `/music/<文件名>`。
MUSIC_EXTS = {".mp3", ".m4a", ".wav", ".ogg", ".opus", ".flac"}
BUNDLED_DIR = ROOT / "ui" / "media"


def media_dir(cfg: dict) -> str:
    """`config.json` 里写的那个目录（原样，**不判断存在**）—— 界面要把它显示出来，
    所以"没配"和"配了但不在"是两种要分开说的情况。"""
    return str((cfg.get("media") or {}).get("dir") or "").strip()


def music_root(cfg: dict):
    """用户那个目录；**不存在就回 None**。"""
    raw = media_dir(cfg)
    if not raw:
        return None
    p = Path(raw)
    return p if p.is_dir() else None


def music_roots(cfg: dict) -> list:
    """`[(目录, 标记)]`，内置在前。**顺序即优先级**（见文件头那一段）。
    任一目录不存在就跳过；两个都不在就回 `[]`。"""
    out = []
    if BUNDLED_DIR.is_dir():
        out.append((BUNDLED_DIR, "内置"))
    p = music_root(cfg)
    if p is not None:
        out.append((p, "本机"))
    return out


def music_list(cfg: dict) -> dict:
    """给 `/music.json`：两个来源合起来的曲目表。

    歌名/歌手是从文件名 `歌手 - 标题.mp3` 拆出来的 —— 这批文件是网易云客户端
    下载的，命名就是这个格式。拆不出 ` - ` 的整串当标题，**不编歌手**。
    每首带 `src`（"内置" / "本机"），界面要按它标出来：用户看得见"哪 30 首是
    不管在哪台机器上都放得出来的"。

    三个状态位**都不许省**，界面靠它们说实话：
      ok      —— 有 ≥1 首可放（内置那份在，它就轮不到 false）
      dirOk   —— 用户那个目录在不在。false 时界面必须**明说**"只有内置的 N 首"，
                 不能安静地少掉 125 首 —— 那看起来像"我的歌丢了"
      bundled —— 其中内置几首
    """
    raw = media_dir(cfg)
    dir_ok = music_root(cfg) is not None
    roots = music_roots(cfg)
    tracks, seen = [], set()
    for root, tag in roots:
        try:
            files = sorted((p for p in root.iterdir()
                            if p.is_file() and p.suffix.lower() in MUSIC_EXTS),
                           key=lambda p: p.name.lower())
        except OSError as e:
            # 一个源读不动不该把另一个源也毁掉：已经收进来的照发，再说为什么少。
            return {"ok": bool(tracks), "dir": raw, "dirOk": dir_ok,
                    "bundled": sum(1 for t in tracks if t["src"] == "内置"),
                    "tracks": tracks, "error": f"{type(e).__name__}: {e}"}
        for p in files:
            if p.name in seen:
                continue                      # 内置那份赢了，同一首歌不列两遍
            seen.add(p.name)
            stem = p.stem
            if " - " in stem:
                artist, title = stem.split(" - ", 1)
            else:
                artist, title = "", stem
            try:
                mb = round(p.stat().st_size / 1048576, 1)
            except OSError:
                continue                      # 刚好被删了：跳过这一首，别整个列表报错
            tracks.append({"file": p.name, "title": title.strip(),
                           "artist": artist.strip(), "mb": mb, "src": tag})
    return {"ok": bool(tracks), "dir": raw, "dirOk": dir_ok,
            "bundled": sum(1 for t in tracks if t["src"] == "内置"),
            "tracks": tracks}


async def music_json(request: web.Request) -> web.Response:
    hub: Hub = request.app["hub"]
    return web.json_response(music_list(hub.cfg))


async def amap_nearby(request: web.Request) -> web.Response:
    """「离我最近的服务区 + 怎么走」。`?lat=&lng=`（**浏览器定位给的坐标**）。

    调用方有两个，用的是**同一个** 返回值（这是这一整件事的重点：话和屏上的
    公里数必须是同一个数，见 `Hub.__init__` 里那段）：
      · `nav.html` 一拿到定位就来问一次，顺手把缓存填上；
      · 语音问「附近有服务区吗」时服务端自己调。
    缓存和"拿不到就照实说"都在 `ui/amap.py` 里，这里只负责收参数。

    🔴 **没有兜底坐标。** 参数不合法就 400，绝不"默认给个北京"—— 起点要么是
       浏览器定位、要么是用户在导航页上自己选的（`nav.html` 里那条「起点（手动）」），
       两者都不在的时候，正确的行为是**照实说查不到**（见 `SCRIPT` 里那句
       "定位没打开"），不是编一个坐标去算出一串看起来很真的数字。
    """
    hub: Hub = request.app["hub"]
    try:
        lat = float(request.query.get("lat", ""))
        lng = float(request.query.get("lng", ""))
    except (TypeError, ValueError):
        return web.json_response({"ok": False, "why": "没给坐标"},
                                 status=400)
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
        # 0,0 是合法坐标（几内亚湾），这里只管**越界**的（NaN 也会走到这来：
        # `float('nan')` 的所有比较都是 False，所以上面那两个条件同时不成立）。
        return web.json_response({"ok": False, "why": "坐标不合法"},
                                 status=400)
    return web.json_response(await hub.amap.nearby(lat, lng))


async def amap_search(request: web.Request) -> web.Response:
    """`?kw=&mode=&lat=&lng=` → **一串候选地点**（高德 `assistant/inputtips`）。
    `nav.html` 那两个搜索框用的。

    ★ **只回候选，不回"就是它"** —— 高德的关键词是模糊/语义匹配（实测拿
      「服务区」在天安门搜，第一条是顺丰的一个驿站；拿一句废话去搜，它也能硬凑
      出几条），"哪个是你想要的那个"这一步必须由**人**来点。理由写在
      `ui/amap.py` 的 `search()` 文首。

    ★★ 2026-09-25→26：这一条**就是**给"每敲一个字问一次"用的，走 `inputtips`；
      `?mode=full` = **上屏那一下**（回车 / 「搜索路线」），服务端再并上
      `place/text` 的结果（整地名、看得懂的分类只有它有）。为什么分成两条、
      以及"一个字为什么必须用 inputtips"，见 `ui/amap.py` 的 `search()` 文首
      —— 那里有当场量出来的那张对照表（单字 `place/text` 全是 count=0）。
    ⚠️ 页面那头**必须**有防抖（450 ms）和"同时只允许一条在飞"，别裸着打过来：
       高德个人 key 的 QPS 已经在单字上撞过墙（`CUQPS_HAS_EXCEEDED_THE_LIMIT`）。

    ★ 可选的 `lat`/`lng` = **起点的坐标**，只用来把候选往身边拉（实测：「站」
      不给它是合肥站/北京站/大连站，给了（无锡）就是站前商贸城/无锡站北进站口）。
      ⚠️ 它是**偏置、不是条件** —— 缺了、越界了、不是数了，一律当没给，
         **绝不因此把这次搜索判成失败**（理由写在 `ui/amap.py` 的 `search()` 里）。
    """
    hub: Hub = request.app["hub"]
    kw = (request.query.get("kw") or "").strip()
    if not kw:
        return web.json_response({"ok": False, "why": "没给关键词",
                                  "keyword": "", "list": []}, status=400)
    if len(kw) > 60:
        # 不是防谁，是防着一串粘进来的东西把 URL 撑爆（高德那头也会拒）。
        return web.json_response({"ok": False, "why": "关键词太长了",
                                  "keyword": "", "list": []}, status=400)
    full = (request.query.get("mode") or "").strip() == "full"
    return web.json_response(
        await hub.amap.search(kw, full=full,
                              lat=request.query.get("lat"),
                              lng=request.query.get("lng")))


async def amap_route(request: web.Request) -> web.Response:
    """`?olat=&olng=&dlat=&dlng=&name=&addr=` → **起点到指定目的地怎么走**。

    和 `/amap/nearby` 的区别只有一个：目的地是**人点的那条候选**，不是"附近搜
    出来的最近一个"。返回值形状**完全一样**（`ui/amap.py` 的 `to()`），所以页面那
    一套渲染两处共用。

    🔴 这条路**没有"直线距离"这一档**（`place/text` 不返回距离），算不出驾车路线时
       它**一个数字都不给**（`km`/`min` 都是 0，`why` 是一句人话）—— 页面必须照实
       显示，不许自己补一个直线距离上去。见 `to()` 文首那段。
    """
    hub: Hub = request.app["hub"]
    try:
        olat = float(request.query.get("olat", ""))
        olng = float(request.query.get("olng", ""))
        dlat = float(request.query.get("dlat", ""))
        dlng = float(request.query.get("dlng", ""))
    except (TypeError, ValueError):
        return web.json_response({"ok": False, "why": "起点或终点的坐标没给全"},
                                 status=400)
    # ⚠️ 四个坐标**一起判**，别图省事写成 `for v in (...)` 一个循环：纬度上限是 90、
    #    经度是 180，一个循环套同一个范围会漏掉。另外 `float('nan')` 的**所有**比较
    #    都是 False —— 所以判据必须写成"在范围内"（NaN 会掉到 else 里被拒），
    #    写成"不在范围内就拒"的话 NaN 反而能过去。
    if not (-90.0 <= olat <= 90.0 and -90.0 <= dlat <= 90.0
            and -180.0 <= olng <= 180.0 and -180.0 <= dlng <= 180.0):
        return web.json_response({"ok": False, "why": "坐标不合法"}, status=400)
    # 名字/地址是**页面回传的**（人点的那条候选），长度掐一下就够了：
    # 它只被原样放进卡片（页面用 textContent 赋值，不是 innerHTML）。
    name = (request.query.get("name") or "").strip()[:120]
    addr = (request.query.get("addr") or "").strip()[:200]
    return web.json_response(await hub.amap.to(
        olat, olng, dlat, dlng, name, addr))


async def amap_ip(request: web.Request) -> web.Response:
    """「这台电脑大概在哪个城市」→ **城市级**的 IP 定位（高德 `v3/ip`，见
    `ui/amap.py` 的 `ip_locate()`）。

    ★ 它是**浏览器定位的备用路**：用户拍板「起点默认就是我的电脑位置」，
      而这台机器上浏览器定位拿不到坐标（实测 `getCurrentPosition` code 3 超时）。
      IP 定位问的是**服务端出网那条路**，是另一条真数据。

    🔴 说清楚它的粒度是**城市**（`ip_locate()` 的注释里写了为什么这条必须写明）
      —— 页面把 `city` 写在起点标签上，城市对不上，人一眼就知道要自己改。
      ⚠️ 拿不到时如实回 `ok=False`（实测这个 key 的 `v3/ip` 回的是**空数组**，
         `infocode` 却是 `10000` —— 又一个"HTTP 200 不等于成功"的实例）。
    """
    hub: Hub = request.app["hub"]
    return web.json_response(await hub.amap.ip_locate())


async def music_file(request: web.Request) -> web.FileResponse:
    """一首歌。`web.FileResponse` **自带 Range 支持**（实测 3.14.3）——
    拖进度条靠它，没有 206 的话 `<audio>` 只能从头放。
    `.mp3` 在 aiohttp 自己那张表里就是 `audio/mpeg`（那张表和 stdlib 不是一份，
    踩过坑，见文件头 .webp 那一段），所以这里不用手动设 Content-Type。

    ⚠️ 按 `music_roots()` 的顺序**逐个数找**（内置在前）—— 和曲目表同一个顺序，
    否则同一首歌会因为两份文件大小不同而"列表里标 5.3 MB、放出来是另一个版本"。"""
    hub: Hub = request.app["hub"]
    name = request.match_info.get("name") or ""
    # ⚠️ 这几个判断是**路径穿越**的防线，不是多余：aiohttp 会先对路径做一次解码，
    #    落到这里的东西可能已经带了分隔符。
    if not name or name.startswith(".") or "/" in name or "\\" in name:
        raise web.HTTPNotFound()
    for root, _tag in music_roots(hub.cfg):
        path = root / name
        try:
            if root.resolve() not in path.resolve().parents:
                continue
        except OSError:
            continue
        if path.is_file():
            return web.FileResponse(path, headers={"Accept-Ranges": "bytes"})
    raise web.HTTPNotFound()


async def mjpeg(request: web.Request) -> web.StreamResponse:
    """把摄像头画面以 MJPEG 推给 <img>。

    为什么用 MJPEG 而不是 WebRTC/HLS：浏览器原生支持（`<img src>` 就完事），
    零依赖、零握手、延迟低。代价是没有音频、不能硬件解码 —— 对一个本地座舱
    界面来说都是无关项。

    ⚠️ 只在 cam 模式下有流。别的模式下直接 404，让前端回落到 SVG 示意头像。
    """
    hub: Hub = request.app["hub"]
    src = hub.source
    if hub.mode != "cam" or not hasattr(src, "seq"):
        raise web.HTTPNotFound()

    resp = web.StreamResponse(status=200, headers={
        "Content-Type": "multipart/x-mixed-replace; boundary=frame",
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Pragma": "no-cache",
    })
    await resp.prepare(request)
    last = -1
    try:
        while True:
            if src.seq != last and src.jpeg:
                last = src.seq
                await resp.write(
                    b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                    + str(len(src.jpeg)).encode() + b"\r\n\r\n"
                    + src.jpeg + b"\r\n")
            # 20 Hz 轮询：cam 那边 15 fps 出图，这个节奏够跟，又不会空转
            await asyncio.sleep(1 / 20)
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    except Exception:
        pass
    return resp


async def asr_post(request: web.Request) -> web.Response:
    """收一段 WAV，返回识别文本。

    为什么是 `POST` 而不是 WS 上再加一种消息：录和停都在**页面**那一侧完成
    （理由见 ui/asr.py 文件头），服务端这边就是一次无状态的"字节进、文字出"——
    那正是 POST 的形状。用 WS 反而要在 Hub 上挂 per-socket 状态，而两个页面都有
    麦克风按钮，那份状态没有明确的归属。

    ⚠️ **`transcribe` 必须放 `to_thread`**（照 `handle()` 里 `agent.respond` 的先例）：
    它要跑几百毫秒到几秒的 CPU。直接在事件循环里调，这期间**所有** state 推送、
    所有页面的心跳都会停 —— 表现是"点了一下麦克风，整块屏幕卡住"，而最后状态
    还是会到，所以别的测试完全看不出来。

    ⚠️ 返回体里**没有** `install_hint` 之类的大段配置：那是 `hello.asr` 的事。
    这里只回答"这次识别出了什么、没出来是为什么"。
    """
    hub: Hub = request.app["hub"]
    # 先按 Content-Length 挡一道，给一句人话的错误。不挡的话 aiohttp 会拿
    # `client_max_size`（默认 1 MB）丢一个 413 回来，前端只看到"请求失败"，
    # 完全看不出是因为音频太长。
    # ★ 2026-09-26：门槛从 2 MB 收到 **1 MB**（= aiohttp 自己那条线）。
    #   原来写 2 MB 是想"比 aiohttp 宽一点"，但那道闸门是**在读 body 的时候**
    #   才落的，2 MB 这条人话错误根本轮不到 —— 1~2 MB 的请求照样 413 而且没有
    #   人话。1 MB 才真的挡在它前面。浏览器侧录多长由 `live.js` 的
    #   `ASR_REC_MAX_S`（30 s ≈ 960 KB）管着，这条只挡畸形请求。
    n = request.content_length or 0
    if n > 1024 * 1024:
        return web.json_response(
            {"text": "", "why": f"这段音频太大了（{n / 1024 / 1024:.1f} MB）。"
                                f"点麦克风录的这一段最多 30 秒，"
                                f"要连着说请直接喊「你好小瑞」。"},
            status=413)
    blob = await request.read()
    text, why = await asyncio.to_thread(hub.asr.transcribe, blob)
    return web.json_response({"text": text, "why": why, "ok": hub.asr.ok()})


async def handle(hub: Hub, req: dict, ws: web.WebSocketResponse):
    kind = req.get("type")
    now = time.monotonic()
    st = hub.last_state

    if kind == "say":
        text = (req.get("text") or "").strip()
        if not text or st is None:
            return
        hub.history.append({"role": "user", "content": text})
        r = await asyncio.to_thread(hub.agent.respond, st, text, hub.history, now)
        # 带上驾驶员那句，界面才能画出左右两边的气泡
        payload = r.to_json()
        payload["user"] = text
        hub.history.append({"role": "assistant", "content": r.text})
        hub.history = hub.history[-12:]
        await hub.broadcast({"type": "say", "data": payload})

    elif kind == "action":
        aid = req.get("id")
        label = ACTIONS.get(aid, aid)
        hub.history.append({"role": "user", "content": label})
        # 动作也交给小瑞说一句，但走固定话术：这是"操作确认"，不需要模型发挥
        # ⚠️ **服务区这两颗按钮不走 `nearby`**（2026-09-26 改）：`SCRIPT["nearby"]`
        #    四档是**带 `{name}/{km}` 的模板**，只有 `_nearby_reply` 填得满 ——
        #    在这里 `_pick` 它会直接把占位符念出来（「还有 {km}」）。
        #    而这条路上**本来就没有数据**：按钮自己做完的事是跳到导航页
        #    （`location.href = 'nav.html?do=nearby'`），真数字是**那一页**查出来
        #    的、也画在那一页上。所以这两颗走 `rest_stop` 那张不带数字的表。
        #    ⚠️ 语音那条路（`voice_answer` 的 `voice_do` → `act_reply`）没动，
        #       它拿得到真数据，仍然是模板。
        intent = {"music": "music", "rest_stop": "rest_stop",
                  "status": "status", "nearby": "rest_stop",
                  "snooze": "snooze"}.get(aid, "chat")
        text = hub.agent.scripted._pick(intent, st.severity if st else "normal", now)
        hub.history.append({"role": "assistant", "content": text})
        await hub.broadcast({"type": "say", "data": {
            "text": text, "emotion": emotion_for(st) if st else "normal",
            "actions": [], "backend": "scripted", "user": f"[点击] {label}",
            "action_done": aid}})

    elif kind == "source":
        # ★ 2026-09-25：驾驶监测页那颗「接入摄像头 / 断开摄像头」按钮走的就是这支
        #   （协议本身早就在，只是一直没有界面入口）。`spec` 见 `make_source`：
        #   `demo` / `cam` / `cam:某段.mp4` / `replay:…` / `live:…`。
        mode_spec = req.get("spec") or req.get("mode") or "demo"
        # ★ 2026-09-25 晚：这一下是**人**点的。它是"我现在插上摄像头了，再试一次"
        #   的明确意思，所以要清掉自动接入留下的那个闸 —— 不清的话，
        #   上一次自动接失败之后，用户点这颗按钮也照样会被 `cam_error` 挡住
        #   （`maybe_autocam` 那个守卫），表现是"点了没反应"，最难查的一种。
        hub.cam_error = ""
        # 顺手把"用户到底想要哪个源"记下来。空闲超时只动 mode，不动它 ——
        # 页面再打开时靠它决定要不要自动把摄像头接回来。用户点了「断开」，
        # 那这一轮就不该再自动接（`want` 变成 demo），这是对的。
        hub.want = mode_spec
        if hub.switching:
            await hub.broadcast({"type": "info", "data": {
                "text": "正在切换数据源，稍等一下", "source_switch": mode_spec,
                "ok": False}})
            return
        hub.switching = True
        try:
            # ⚠️ 丢进线程里建。理由（含"失败也不能弄死老源"这条顺序）全在
            #   `switch_source` 的 docstring 里，别改成在循环里直接调。
            new_mode, new_src = await asyncio.get_running_loop().run_in_executor(
                None, switch_source, hub.cfg, hub.source, mode_spec)
        except Exception as e:
            # 手动这一次也失败 -> 和自动接入失败是同一件事（多半就是没插摄像头），
            # 同样把闸落下，免得页面重连时每 1.8 s 重试一遍几秒的开设备。
            hub.cam_error = f"{type(e).__name__}: {e}"
            await hub.broadcast({"type": "info", "data": {
                "text": f"切换失败：{type(e).__name__} {e}",
                # 结构化字段：前端靠它复位那颗按钮的「正在接入…」。
                # 别让前端去匹配中文文案 —— 那是靠人肉维持的一致。
                "source_switch": mode_spec, "ok": False}})
            return
        finally:
            hub.switching = False
        hub.mode, hub.source = new_mode, new_src
        hub.source_spec = mode_spec
        # ★ 2026-09-25 晚：`cam_open` 必须跟着一起改 —— 它才是"设备现在被占着吗"
        #   的唯一判据（`watch_pages` 和 `maybe_autocam` 都读它）。
        #   漏了这一行的话：手动接入成功了，但 `cam_open` 还是 False，
        #   于是空闲超时不会松手（摄像头又关不掉了），而页面每次连上来还会
        #   再"自动接入"一次 —— 而 cam 换 cam 是必失败的。
        hub.cam_open = (new_mode == hub.CAM_SPEC)
        hub.last_severity = None
        # 和 `_switch_to` 里那一句同一个理由：换源之后上一路那一帧不能留着
        # （它会被"给新连上来的页面垫一帧"那一发送出去，冒充这一路）。
        hub.drop_last_state("手动换源")
        # hello 要**先发**：页面靠它决定这一格是画人还是出等待卡（`CAM_LIVE`），
        # 而紧接着那条 info 只是给人看的一句提示。
        await hub.broadcast({"type": "hello", "data": hub.hello()})
        await hub.broadcast({"type": "info", "data": {
            "text": f"数据源已切到 {mode_spec}",
            "source_switch": mode_spec, "ok": True}})

    elif kind == "seek":
        # 把演示演出挪到某一档（`index.html?sev=mild` 就是这么用的；
        # 那五个段名见 `ui/sources.py` 的 arc，界面自己翻成四档档位键
        # —— 后两个段名（phone / fatigue）翻出来都是 `severe`，见 app.js 的 PIN 段）。
        # 只有 demo 源有时间轴；其余源明说做不到，不假装成功。
        seek = getattr(hub.source, "seek", None)
        if callable(seek):
            seek(float(req.get("t") or 0.0))
            hub.last_severity = None            # 定位后允许重新播报一次预警
            await hub.broadcast({"type": "info",
                                 "data": {"text": f"演示时间轴已定位到 {float(req.get('t') or 0):.0f}s"}})
        else:
            await hub.broadcast({"type": "info",
                                 "data": {"text": f"{hub.mode} 源没有时间轴，不能用 ?sev= 定位"}})

    elif kind == "status":
        if st is not None:
            await hub.broadcast({"type": "info", "data": {"text": state_brief(st)}})

    elif kind == "tts":
        # 浏览器那条路没开口时的兜底：页面自己探测到 600 ms 内没出声，
        # 就把这句话发上来让服务端念（见 web/live.js 的 XQ.speak）。
        #
        # ⚠️ 这里**故意一个字都不 broadcast**。上行是 say 的话，下行再回一条 say，
        # 每个页面都会拿去念一遍，而念的又是同一条 —— 立刻变成回音室。
        # 别的分支都在广播，只有这一条不广播，这是有意的，不是漏了。
        text = (req.get("text") or "").strip()
        if text:
            # ★ 2026-09-26（B1 的另一半）：这条消息的**真正含义**是"浏览器这条路
            #   没念出来，该服务端兜底念了"—— 而服务端兜底那条**掐不断**
            #   （`ui/tts.py` 的 `stop()` 是一次性闩锁，daemon 线程里 `$s.Speak`
            #   阻塞着）。掐不断的还在念 + 麦克风开着 = 小瑞把自己的声音听成
            #   主人的话。所以**这一刻把闸关回去**：这一轮从此不再接受"被叫醒"。
            #   依据是"**掐得断吗**"，不是"谁念的" —— 和 `answer_done(follow)`
            #   那条注释是同一套逻辑（见 `ui/voice/loop.py` 的 `barge_in_ok`）。
            if hub.ear is not None and hub.ear.barge_in_ok:
                hub.ear.barge_in_ok = False
                print("[voice] 这一句走服务端兜底念（掐不断）—— 本轮不再接受掐断唤醒")
            hub.voice.say(text, req.get("emotion") or "normal")

    elif kind == "tts_voices":
        # ★ 2026-09-25：试音台要一份"服务端这条路上有哪些在线音色"。
        # 这是**问一句答一句**，不是广播 —— 名单只有几十行，但没道理让每个
        # 页面都收一份（和上面 tts 那条同一个思路：只有该收的收）。
        # ⚠️ 列名单要联网、要几秒，所以丢进线程 —— 这一条是普通消息，
        # 卡在事件循环里会**把 state 推送一起卡住**（整页掉帧的那种卡）。
        # ⚠️ 没装 edge-tts 或断网时返回空名单 + 原因，**不抛异常**：
        # 试音台得把"为什么列不出来"显示出来，而不是让页面转圈。
        vs, why = await asyncio.get_running_loop().run_in_executor(
            None, list_edge_voices)
        if ws is not None:
            await ws.send_str(json.dumps({"type": "tts_voices", "data": {
                "voices": vs, "why": why,
                "engine": hub.voice.engine,
                "current": (hub.voice.edge_voice if hub.voice.engine == "edge"
                            else hub.voice.voice),
                "enabled": hub.voice.enabled}}))

    elif kind == "voice_start":
        # ★ 2026-09-25 常听唤醒：页面点了「听」。
        #   ⚠️ 这一支**永远不会自动触发** —— 麦克风只有人点了才开，
        #   和"只有点接入摄像头才接摄像头"是同一条原则（见 web/wake.js 第 1 条）。
        await hub.ear_start(ws)

    elif kind == "voice_stop":
        # 用户把耳朵关了。**不广播**（同 voice_send 的理由）：别的页面没开麦，
        # 不该收到"别人的麦克风关了"。
        if hub.ear is not None:
            hub.ear.stop()
        if hub.ear_task is not None and not hub.ear_task.done():
            hub.ear_task.cancel()
        hub.ear_ws = None
        await voice_send(ws, {"ev": "idle", "why": ""})

    elif kind == "pcm":
        await voice_pcm(hub, req, ws)

    elif kind == "voice_status":
        # **诊断用**：问一句"你那边的状态机现在停在哪一档、第几轮、耳朵归谁"。
        # 加它是因为自测脚本（和将来查"叫不醒"的人）只能从**外面**看这条链路，
        # 而事件流里没有"现在是什么状态"这个东西 —— 没有它就只能靠 sleep 猜
        # 时序，而猜时序已经让自测脚本误报过一次（见 _check_voice_ws.py 的注释）。
        # ⚠️ 页面**不要**拿它当状态源：页面自己的状态来自事件流，这条只是给
        #    "坏了要查"用的（和 `tts_voices` 那条一样，只在问的时候答）。
        await voice_send(ws, {"ev": "status",
                              "voice": hub.ear_hello(),
                              "ear": hub.ear.status() if hub.ear is not None else None,
                              "owner": hub.ear_ws is ws})

    elif kind == "do_result":
        # 开麦那张页面把「让你做的那件事做完了没有」回执过来（见 `voice_do`）。
        # ⚠️ 三条守门，一条都不能少：
        #   1. 没人等着 —— 1.5 s 早就超时收工了，这条回执**必须丢掉**，
        #      否则会把结果塞进……下一个 future？没有下一个，只是白忙。
        #   2. **轮次对不上** —— 这 1.5 s 里主人可能已经又叫醒了一轮，
        #      这条迟到的是**上一轮**的回执。拿它去回答新一轮 = 答非所问。
        #   3. id 对不上 —— 同一轮里也可能有别的动作在等。
        cur = hub.ear_do
        if cur is None:
            # 没人等 —— 1.5 s 早就超时收工了。**照样记一行**：这正是"页面回得太慢"
            # 唯一看得见的痕迹。不记的话，表现只剩"小瑞说没放上"这一个结果，
            # 而放没放成、回执是几时到的，查无可查（要和"轮次不对"分开说 ——
            # 那一条是**设计上就要丢**的，这一条是**真的慢了**）。
            print("[voice] 收到一条没人等的 do_result（超时之后才到）：seq=%r id=%r"
                  % (req.get("seq"), req.get("id")))
            return
        if req.get("seq") != cur[0] or (req.get("id") or "") != cur[1]:
            print("[voice] 丢掉一条迟到的 do_result：seq=%r id=%r（当前等的是 %r/%r）"
                  % (req.get("seq"), req.get("id"), cur[0], cur[1]))
            return
        if not cur[2].done():
            cur[2].set_result(req)

    elif kind == "ask":
        # **刚跳过来的那一页**来要一句话（见 `voice_ask`）。
        #
        # 为什么要让**页面**来要、而不是跳之前就说：跳页会把 document 连同
        # `speechSynthesis` 一起拆掉，那句话念到一半就没了，`voice_spoken` 也
        # 永远不会来（详见 `_voice_say(jump=True)` 上面那段）。所以跳过去之后，
        # 由**活着的那一页**在麦克风起来之后发这一条，小瑞才说得出完整的一句。
        await voice_ask(hub, ws, req)

    elif kind == "voice_spoken":
        # 开麦的那张页面念完了（浏览器这条路能精确报"念完"，服务端兜底那条不能，
        # 所以这条**可能不来** —— 兜底靠 `_voice_watchdog`，两者都到也不冲突：
        # `answer_done()` 只是把状态放回 IDLE，重复调没有副作用）。
        #
        # ★ 2026-09-26：**只有这条路**能开追问窗口（`ui/voice/loop.py` 的
        #   FOLLOW）—— 因为只有它是"确实念完了"的**证据**。开了之后有这么两件事：
        #     · 页面那行状态改成「在听 —— 接着说」，主人不用再喊唤醒词；
        #     · 服务端 `follow_s` 秒没人说话会自己发一条 `ev:"idle"` 回来
        #       （`VoiceLoop.feed` 里那一条），页面照旧处理，不用自己掐表。
        #
        # ★ 2026-09-26（B3）：**两道卫兵，一条都不能少。** 掐断（B2 的
        #   `XQ.tts.halt`）会调 `speechSynthesis.cancel()`，而 `cancel()` **同样会
        #   触发 `onend`** —— 页面那边靠推 `_seq` 把这一下挡掉了（`live.js` 的
        #   `halt`），可**被掐断的那一句**本来就已经在飞了：它可能正在路上，
        #   而这一轮早换了人。迟到的回执干两件坏事：把**刚开的 LISTEN 推回
        #   FOLLOW**（主人明明正在说话，页面却变成"接着说"），并掐掉**新一轮**的
        #   看门狗（新一轮从此没人兜底）。所以：
        #     ① `round` 对不上 —— 这是**上一轮**的回执；
        #     ② 状态机已经不在 `speak` —— "这条回执说它念完了，而它早不在念了"，
        #        说明它过期了（主人已经喊过唤醒词、已经在 LISTEN）。
        #   两条**都**不成立时**照样打一行日志**：不记的话，表现只剩"小瑞卡住了"，
        #   查无可查（和上面"没人等的 do_result"同一条道理）。
        rnd = req.get("round")
        if hub.ear is not None and rnd is not None and rnd != hub.ear.round:
            print("[voice] 丢掉一条上一轮的 voice_spoken：round=%r 当前 round=%r"
                  % (rnd, hub.ear.round))
            return
        if hub.ear is not None and hub.ear.state != "speak":
            print("[voice] 丢掉一条 voice_spoken：状态机已经不在 speak 了（现在是 %r）"
                  % hub.ear.state)
            return
        if hub.ear is not None:
            hub.ear.answer_done()
            if hub.ear.state == "follow":
                await voice_send(ws, {"ev": "follow", "sec": hub.ear.follow_s})
        # ★ 待确认动作的期限**从这一刻重新起算**。
        #   注册它的那一刻（`voice_ask`）主人**还没听见**那句话 —— 他得先把问句
        #   听完、再想一下、再说「要」，然后那 10 s 静音判据才走完。所以按注册时刻
        #   算出来的期限只是**下限**，这一条才是真的那个（页面刚刚念完，主人从这一
        #   秒起才答得上）。
        #   ⚠️ 位置在两道卫兵**之后**：过期回执走不到这儿（它 return 了），
        #      也就不会替一句早被顶掉的提议续命。
        if hub.pending_do is not None:
            hub.pending_do = (hub.pending_do[0],
                              time.monotonic() + ask_window(hub.ear))
        if hub.ear_task is not None and not hub.ear_task.done():
            hub.ear_task.cancel()

    elif kind == "tts_voice":
        # 换服务端这条路的音色。**只改内存**（理由写在 tts.py 的 set_voice 里：
        # config.json 里躺着 api_key，不为一个音色去重写它）。
        name = (req.get("edge_voice") or "").strip()
        ok = hub.voice.set_voice(name)
        if ws is not None:
            await ws.send_str(json.dumps({"type": "tts_set", "data": {
                "ok": ok, "wanted": name, "engine": hub.voice.engine,
                "current": (hub.voice.edge_voice if hub.voice.engine == "edge"
                            else hub.voice.voice),
                "why": "" if ok else (
                    "服务端这条路现在是 SAPI 引擎（config.json 的 tts.server.engine），"
                    "它不用在线音色" if name else "音色名是空的")}}))


def open_browser(url: str):
    edges = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
             r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"]
    for e in edges:
        if os.path.exists(e):
            # --autoplay-policy：实测不加这一条也能念（headless 下 speak() 不需要
            # 用户手势就被接受、跑到 onend），所以它是**保险丝**不是必需品。
            # 留着是因为演示现场没有第二次机会：万一哪台机器的 Edge 策略更严，
            # 表现为"点了按钮却没声"，而这条 flag 正是那个开关。
            subprocess.Popen([e, "--kiosk",
                              "--autoplay-policy=no-user-gesture-required", url])
            return
    try:
        os.startfile(url)            # 没有 Edge 就用默认浏览器
    except Exception:
        pass


@web.middleware
async def no_store(request: web.Request, handler):
    """给**所有**响应补上 `Cache-Control: no-store`。

    为什么需要（2026-09-24，用户报「切源按钮还在」之后加的）：
        `add_static` 走 aiohttp 默认，只发 `ETag` + `Last-Modified`，
        **一条 `Cache-Control` 都没有**。浏览器于是按 RFC 7234 的启发式缓存算新鲜期：
            freshness = 10% × (本次响应时刻 − Last-Modified)
        这个式子有个恶性后果 —— **服务端回 304 的时候，新鲜期是按那个老旧的
        Last-Modified 重算的**。所以「改了 chrome.js → 用户刷新 → 拿到 304 →
        又是将近一小时」是真的会发生，而用户看到的仍是**改动之前**的界面。

    这次就是这么撞上的：`chrome.js` 改完的 Last-Modified 是 10:33，可那个标签页
    是 10:08 之前加载的，它缓存里那条的老 Last-Modified 还是前一天的 ——
    新鲜期一路续到 11:13 开外。**界面里「数据源」那四个按钮早就删了，屏幕上还在。**
    加这一条之后，任何一次加载都重新读盘，这类"改了没变"再不会出现。

    ⚠️ **`if not resp.prepared` 那个判断不能省。** 对已经 prepare 过的响应
       改 headers，aiohttp 会抛 `RuntimeError: Cannot modify headers after prepare`。
       这个仓库里有两类响应是 handler 内部就 prepare 掉的：
         · `/video.mjpg`（MJPEG 流，它自己已经显式设了 no-store）
         · `/ws`（WebSocket 升级）
       它们靠这个判断**自动跳过** —— 所以这里不需要按路径挑，也不会把视频流弄坏。
    """
    resp = await handler(request)
    if not resp.prepared:
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
    return resp


def main():
    ap = argparse.ArgumentParser(description="小瑞座舱界面")
    ap.add_argument("--config", default=None)
    ap.add_argument("--source", default=None, help="demo / replay:路径 / live:路径")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--host", default=None)
    ap.add_argument("--hz", type=float, default=None)
    ap.add_argument("--media-dir", default=None,
                    help="曲库目录，覆盖 config.json 的 media.dir。"
                         "指一个不存在的路径 = 演示「只有内置那 30 首」那条路")
    ap.add_argument("--open", action="store_true", help="顺便开浏览器")
    a = ap.parse_args()

    cfg = load_config(a.config)
    if a.media_dir is not None:
        cfg.setdefault("media", {})["dir"] = a.media_dir
    global SEV_CFG, ALARM_CFG, WECHAT_CFG, AMAP_CFG
    SEV_CFG = cfg.get("severity", {})
    ALARM_CFG = cfg.get("alarm", {})
    WECHAT_CFG = cfg.get("wechat", {})
    AMAP_CFG = cfg.get("amap", {})
    srv = cfg.get("server", {})
    host = a.host or srv.get("host", "127.0.0.1")
    port = a.port or int(srv.get("port", 8765))
    hz = a.hz or float(srv.get("hz", 8))

    hub = Hub(cfg, a.source)
    app = web.Application(middlewares=[no_store])
    app["hub"] = hub
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/video.mjpg", mjpeg)
    app.router.add_post("/asr", asr_post)
    # 曲库（多媒体页）。内置 ui/media/ + media.dir 两个来源合成一张表；
    # 两个都不在时列表 ok:False、取文件 404（界面要说清是哪一种"没有"）。
    app.router.add_get("/music.json", music_json)
    app.router.add_get("/music/{name}", music_file)
    # 高德：最近服务区 + 驾车路线（见 ui/amap.py）。`nav.html` 打开时拿它填卡片，
    # 语音问服务区时也走它 —— **一个来源**，见 Hub.__init__ 那段注释。
    app.router.add_get("/amap/nearby", amap_nearby)
    # 导航页那两个搜索框（起点 / 终点）和"给几个方案"那一步。三条路由是同一套
    # 高德 key、同一份 `ui/amap.py`，返回值的形状也一样 —— 页面那一套渲染三处共用。
    # ⚠️ 它们**不能少**：`nav.html` 一进页面就会打 `/amap/nearby`，人再一打字就是
    #    `/amap/search`、`/amap/route`；漏注册的表现是控制台 404 + 页面上
    #    "服务端没回话"，而不是任何一句能看出根因的话。
    app.router.add_get("/amap/search", amap_search)
    app.router.add_get("/amap/route", amap_route)
    # 「这台电脑在哪个城市」—— 浏览器定位拿不到时的**备用起点**（城市级）。
    app.router.add_get("/amap/ip", amap_ip)
    app.router.add_static("/static", WEB)
    # `/assets` 是 `/static/assets` 的别名。前端用相对路径探资产
    # （`new Image().src = 'assets/xiaoqi.png'`），那是相对**文档**的，
    # 从 `/index.html` 出发算出来是 `/assets/...` 而不是 `/static/assets/...`。
    # 挂这一条，服务器上和 `file://` 直接打开就都对得上，前端不用管环境。
    app.router.add_static("/assets", WEB / "assets")

    # 页面级路由：每个页面是 web/ 下的一个真实文件（多页而不是单页路由），
    # 这样直接用 file:// 打开也能看，答辩现场少一层依赖。
    # `/` 是**封面**（用户要求：进浏览器先看到展示封面，右下角「进入」才到座舱）——
    # 不是 index.html。run_ui.bat 打开的就是这个地址，所以改这里就是改开场。
    # ⚠️ `/index.html` 仍然必须注册：封面的「进入」按钮和左导航「首页」都指向它，
    # 而且是**相对链接**，少了这条两处全 404。
    app.router.add_get("/", lambda r: web.FileResponse(WEB / "cover.html"))
    app.router.add_get("/index.html", lambda r: web.FileResponse(WEB / "index.html"))
    for name in PAGES:
        app.router.add_get(f"/{name}.html",
                           (lambda n: lambda r: web.FileResponse(WEB / f"{n}.html"))(name))
    # 试音页。**故意不放进 PAGES**：PAGES 是"服务器上有的页面"这份名单，
    # 而左导航那五项是**写死在 chrome.js 的 NAV 里**的，跟这份名单没关系。
    # 这个是工具页（挑音色用的），不给它导航入口，
    # 但只要服务还开着就能从 /voice.html 打开它。
    app.router.add_get("/voice.html", lambda r: web.FileResponse(WEB / "voice.html"))

    async def _start(app):
        app["task"] = asyncio.create_task(hub.loop(hz))

    async def _stop(app):
        app["task"].cancel()
        stop_source(hub.source)
        # 心率那条读线程是 daemon，进程没了它自然也没了；这里只是让"服务停掉"
        # 和"串口松开"是同一件事 —— 不然 Ctrl+C 之前那个口还占着，
        # 用户切过去开串口助手会打不开。
        hub.hr.close()

    app.on_startup.append(_start)
    app.on_cleanup.append(_stop)

    key, src = resolve_key((cfg.get("agent") or {}).get("deepseek") or {})
    print(f"数据源   : {hub.mode}  ({a.source or cfg.get('source', {}).get('mode')})")
    # ★ 2026-09-24 晚：判据从 `hub.want` 换成 `hub.source_spec`。
    #   `want` 现在初值恒为 demo（"只有点接入摄像头才接入"），拿它判的话
    #   这一段永远不会打 —— 用户就看到一行都没有，灯没亮也不知道该不该等。
    #   这里问的是"**摄像头可用吗**"，那正是 `source_spec`
    #   （和 `hello()` 里 `source_spec` 那一项同一个表达式，别写成两份口径）。
    if (hub.source_spec or (cfg.get("source") or {}).get("mode")) == hub.CAM_SPEC:
        # 这句话说反了的话：用户看到灯没亮会以为坏了，而看到"已接管"又会以为
        # 摄像头被占着、不敢跑 live_fuse.bat。
        print("           ⏳ 摄像头**还没开**：要手动接入 —— 驾驶监测页右上角那颗"
              "「接入摄像头」")
        print(f"              点了才接；页面全关掉 {hub.CAM_IDLE_GRACE:.0f}s 后自动松手，"
              "松手之后要再点一次")
        print("              所以没点之前跑 live_fuse.bat 是安全的；接了之后别跑")
    print(f"小瑞     : {hub.agent.mode}"
          + (f" · API 已配置（{mask(key)} via {src}，模型 {hub.agent.client.model}）"
             if hub.agent.client.ready else " · 只用固定话术（没配 API key）"))
    th = hub.tts_hello()
    print(f"小瑞语音 : 浏览器优先（关键词 {th['voice']}）· 当前源"
          + ("出声" if th["default_on"] else "静音")
          + (f" · 服务端兜底 {hub.voice.voice}" if hub.voice.enabled else " · 服务端兜底已关"))
    if hub.voice.enabled:
        print("           音色不满意就打开 http://"
              f"{host}:{port}/voice.html 挨个试听（不进作品集，是工具页）")
    # 语音输入的兜底那一路。**装没装都要打出来**：这一行是"界面为什么说听不见"
    # 的第一现场，藏起来的话就只能靠翻界面猜了（和 tts 那一行同一个道理）。
    ast = hub.asr.status()
    print(f"语音输入 : {ast['engine']}"
          + ("" if ast["ok"] else f"  → {ast['install_hint']}"))
    if ast["ok"]:
        print(f"           浏览器优先，浏览器那条路不通才走本地（prefer={ast['prefer']}）")
    # 心率（HPM5300 + MAX30102，串口）。和语音输入那行同一个道理：**成没成都打**，
    # 藏起来的话界面上那格显示「未接入」时就只能靠翻设备管理器猜了。
    hri = hub.hr.info()
    print(f"心率     : {hri['port'] or '未找到串口'}"
          + (f"  → {hri['error']}" if hri["error"] else "  · 手指按上去才出数"))
    if not hri["port"]:
        print("           板子插上了吗（认 VID:PID=0403:6010，不认 COM 号）；"
              "板端固件在 hr\\firmware")
    print(f"地址     : http://{host}:{port}/     (Ctrl+C 退出)")
    if a.open:
        open_browser(f"http://{host}:{port}/")
    try:
        web.run_app(app, host=host, port=port, print=None)
    finally:
        stop_source(hub.source)
        hub.hr.close()
        # 杀掉可能正在念稿的那个 powershell.exe。`os._exit(0)` 不会跑任何
        # cleanup，daemon 线程也一并消失，所以只剩这一个子进程需要管 ——
        # 不管的话它会变成孤儿，在你下一次启动界面时突然开口说话。
        hub.voice.stop()
        # cam 模式下进程里有**两个** mediapipe landmarker，各自析构固定 42 秒
        # （见 src/fuse.py 的同款注释）。不硬退，Ctrl+C 之后要干等 84 秒。
        sys.stdout.flush()
        os._exit(0)


if __name__ == "__main__":
    main()
