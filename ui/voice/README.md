# 小瑞的耳朵 —— 常听唤醒（对着笔记本说「你好，小瑞」）

一条链，两边：

```
   浏览器（持麦的那张页面）                 服务端（只做推理）
   采麦 16 kHz 单声道
   每 100 ms 一片 ──── {"type":"pcm"} ────▶ KWS 常听（一直开着，便宜）
        ▲                                        │ 唤醒词命中
        │                                        ▼
        │                                   识别（whisper / 流式）
        │                                        │ 出文字
        │                                        ▼
        └── {"type":"voice"} 事件 ◀────── DeepSeek（一次往返）
            ＋ 广播出去的 say（气泡/情绪/后端都走原来那套）
            念，由**开麦的那张页面**自己念（它手上有 done 回调）
            念完回 {"type":"voice_spoken"} ─▶ 开 **10 s 追问窗口**（不用再喊唤醒词）

   ★ 动作类的那一条（不走模型，见 [6] 第 9 条）：服务端认出来是个动作就直接让
     **开麦的那一张页面**去做，等它回执，再照回执挑话：
       服务端 ── {"ev":"do","id":"go:media","seq":N} ──▶ 这张页面
       页面   ── {"type":"do_result","id":…,"seq":N,"ok":…,"same":…,"here":…} ──▶ 回来
     单播**只发给开麦那一张**（广播 = 每张页面各做一遍，12 张页面各有自己的
     `new Audio()`，听出来是回声）；`seq` 认轮次号，迟到的回执丢掉。

   ★ 打断它自己（2026-09-26 加，见 [6] 第 1 条）：它念的时候喊唤醒词 ——
     服务端 ── {"ev":"halt","why":"主人喊我了"} ──▶ 这张页面（`XQ.tts.halt()` 掐断）
     服务端 ── {"ev":"wake",…,"from_speak":true} ──▶ 接着就转过来听

   ★ 跳过去 + 问一句（2026-09-26 加，见 [6] 第 10 条）：跳页那一轮**不念**
     （念出来只有半句），由**跳过去之后活着的那一页**来要那句话：
       页面 ── {"type":"ask","id":"rest_stop","origin":{…}|null} ──▶ 服务端
       服务端 ── {"ev":"reply","text":"…要不要我导到最近的服务区？","round":N} ──▶
     主人应一声「要的」（追问窗口里，**不用喊唤醒词**）→ 待确认的那个动作
     才真的发出去（`{"ev":"do","id":"rest_stop"}`）。
```

**为什么这么分：音频归属在浏览器，Python 只推理。** 所以 `ui/voice/` 里
`sounddevice` / `PyAudio` / `soundfile` 一个都不需要（真要装也能装上，但那是
给"服务端自己开麦"那条路用的，本项目没走）—— 换台机器演示不用重配声卡。
代价很具体，写在下面 [4]：**服务端不知道页面的喇叭什么时候念完**。

---

## 1. 文件清单（分文件）

### 服务端 · 耳朵本体（`ui/voice/`，共 1101 行，纯 Python，无第三方框架）

| 文件 | 行数 | 干什么 | 关键设计点 |
|---|---|---|---|
| `kws.py` | 236 | 唤醒。sherpa-onnx 关键词检出，喂 100 ms 一片 | 模型目录**按特征 glob**，不写死版本名（换个包就换文件名）；`debounce_s=1.0` 是**按挂钟**的去抖 |
| `asr_stream.py` | 446 | 识别。两条路**同一个接口**：`StreamAsr`（sherpa 流式）/ `WhisperAsr`（整段式，包 `ui/asr.py` 的 `LocalAsr`）；还提供 `RingBuffer` | `WhisperAsr` **自己管单句安全阀**（从 `LocalAsr.max_s` 推算，2026-09-26 起是 299.5 s，判"说完"只看 10 s 静音）、复服务端已有那份 whisper（不再建第二个 145 MB）；空串必带 `last_why`；两条路都报 `heard`（`loop.py` 的兜底超时靠它分辨"真在说话"和"叫醒了没人吭声"） |
| `loop.py` | 293 | 状态机 `IDLE ⇄ LISTEN → THINK → SPEAK → FOLLOW` | ★★ 半双工：SPEAK 期间**绝不喂 ASR**（没有 AEC）+ 念完 `GUARD_S=0.4 s` 余音保护。**但唤醒词那一层是开的**：`barge_in_ok`（默认 False）为真时 SPEAK 里喂 KWS，主人喊一声就掐断它的话转过来听（`from_speak`，见 [6] 第 1 条；闸的另一半是"放开麦克风"，所以默认必须是关）;唤醒前 2 s 环形缓冲补喂（"你好小瑞我有点困"一口气说不丢字）；`round` 轮次号给看门狗认轮次；★ **`FOLLOW`（追问窗口 `FOLLOW_S=10 s`）**：念完之后接着说就接着答，不用再喊唤醒词（见 [6] 第 8 条）；THINK 那几秒单独攒在 `self.think`，开窗时补喂；`expecting()` = "小瑞马上要主动说一句"，把状态摆到 THINK 好让 `voice_ask` 过 `voice_say` 那道 `state == "think"` 的守门（**不动 `round`**） |
| `fetch_models.py` | 166 | 下模型（KWS 已下；流式 ASR 133 MB 要外网） | 断点/失败如实报，不假装装好了 |
| `keywords.txt` | 1 | 唤醒词表（`你好小瑞`） | 词表是文件不是配置：改词不用动代码 |

### 服务端 · 那条桥（`ui/server.py`，改动都在这一块）

| 位置 | 干什么 |
|---|---|
| `Hub.voice_hello` / `hello()` 568 | hello 里报耳朵状态，**但不加载模型**（页面一打开就拉模型的话，用户没点「听」也白等十几秒） |
| `Hub.ear_hello` 627 / `Hub.ear_start` 650 / 模块级 `build_ear` 689 | 懒建耳朵（第一次 `voice_start` 才建，建在线程里）；**最多一份**，第二个连接不发第二份 |
| `voice_send` 708 | 只发给**开麦的那一张** socket。**故意不广播** —— 语音事件广播出去，别的页面会跟着画状态、跟着念 |
| `voice_events` 726 | `wake/partial/heard/idle` → 转发；`need_text` → 先发 `thinking` 再到线程里 `finalize_text`（whisper 是几百毫秒的阻塞调用，在事件循环里跑会把整块屏幕卡住） |
| `voice_answer` 966 | 判据一句变两句（**语序就是优先级**）：`take_pending(hub, text) or detect_action(text)` → 动作走 `voice_do` + `act_reply`，其余问 DeepSeek；收尾一律交给 `voice_say` |
| `voice_say` 1026 | 广播 `say`（带 `voice/user/silent`）→ 进 SPEAK → 架看门狗。★ **`voice_answer` 和 `voice_ask` 共用**（抄第二份的结果是"两边慢慢长歪"）。★ 里面有**答复来迟了**的守卫：判据是 **`ear.state != "think"`**（`to_thread` 那几秒里这一轮可能已经收了、或者主人已经开始说下一句），那就只画气泡、不进 SPEAK（不然状态机会卡在 SPEAK = "叫醒一次再也叫不醒"）。⚠️ 原来写的是 `== "idle"` —— 现在**念完还有 FOLLOW 一个去处**，写 `idle` 会让上一句的答复在主人说下一句的时候念出来。★★ `jump=True`（跳页那两个动作）：**不念、不进 SPEAK、不架看门狗**，当场 `answer_done(follow=False)` 收回 IDLE —— 页面 180 ms 后就没了，等它的 `voice_spoken` 是白等（见 [6] 第 10 条）。★★ 开抢话的闸：`barge_in_ok = 这句里没带唤醒词`（自激挡板，词表现取 `ear.wake_words()`） |
| `voice_ask` 1100 | **刚跳过来的那一页**来要一句话（`{"type":"ask","id":"rest_stop","origin":…}`）：有起点 → `SCRIPT["ask_rest_stop"]` + **挂 `hub.pending_do`**；`origin` 为 null → `ACT_FAIL["nearby"]["no_geo"]` 那句实话、**不挂**（答应了也是查不到）。⚠️ 交给 `voice_say` 之前必须先 `ear.expecting()` 摆状态，否则那一趟的 `state == "think"` 守门会把它静默丢掉（表现是"跳过去之后一个字都不说"，不报错） |
| `take_pending` 821 | 「主人这是在回答上一句的提议吗」。三个条件同时成立才吐 id：`is_affirm(text)` + 麦克风正开着（`follow`/`listen`）+ 没过 `deadline`。**取走即清**；任何**别的**话也会把它清掉（主人换了话题，那件事就作废）。注册点只有 `voice_ask` 一处 |
| `_voice_watchdog` 1155 | 见下面 [4]。⚠️ 到点时的守卫是 `state in ("idle","follow")` 直接返回：状态在 follow 说明**回执早就到了**（只有真收到 `voice_spoken` 才开窗口），轮不着它收尾 —— 不认它就会把主人正在说话的追问窗口当场掐掉 |
| `voice_pcm` 828 | base64 → float32 → `ear.feed()`。只认 `ear_ws` 那一张；解不开/出异常发 `gone` 说明原因，不静默 |
| `handle()` `voice_spoken` 分支 | ★★ **两道卫兵**（2026-09-26 和"掐断"一起加）：① `req["round"] == ear.round`；② `ear.state == "speak"`（这条回执说它念完了，而状态机**已经不在 SPEAK** ⟹ 它是过期的）。不认的话，`speechSynthesis.cancel()` 触发的那条 `onend` 会白回一条 `voice_spoken`，把刚打开的 LISTEN **推回**追问窗口、还掐掉新一轮的看门狗。丢掉时**照旧打一行日志**（不记的话表现只剩"小瑞卡住了"）|
| `handle()` `ask` 分支 1831 | 见 `voice_ask`。跳页那一趟由**活着的那一页**在麦克风起来之后发一次 |
| `handle()` `tts` 分支 | 页面说"这句走服务端兜底念"→ `barge_in_ok = False`（兜底那条路掐不断，见 [6] 第 1 条）|
| `handle()` 其余 | `voice_start / voice_stop / voice_status` |
| `ws_handler` finally 900 | 开麦的页面走了 → 耳朵停下（**但不销毁模型**，下次点「听」不用重新加载） |

### 浏览器侧

| 文件 | 行数 | 干什么 |
|---|---|---|
| `ui/web/wake.js` | 746 | 采麦（`AudioContext({sampleRate:16000})`）→ ScriptProcessor 切片 → base64 → WS；收 `voice` 事件画状态行；`reply` → `XQ.speak`（**它持麦，所以它念**），念完回 `voice_spoken`（★ **带上 `round`**：服务端靠它丢掉迟到的回执，而页面自己算不出轮次 —— 它从 `ev:"reply"` 里拿）；收 `follow` 把状态行改成「在听 —— 接着说」（**秒数存着，但不自己掐表**：关窗由服务端发 `idle` 通知）；★ 收 `do` 就**真去做**（放音乐 / 给定位 / `go:<键>` 与 `rest_stop` 的**真跳转**）并回 `do_result` —— `navTarget()` 从 `XQ.NAV` 取目标文件名（不另抄一份表），`samePage()` 比路径最后一段决定"跳还是就地办"；★★ 收 `halt` → `XQ.tts.halt()` 掐断自己的话 + 清掉没念完的气泡；★★ 跳页时 URL 带 `?ask=<id>`，**跳过去之后**由 `XQ.wake.ask()` 在麦克风真的起来（`state === 'listening'`）之后发一条 `{"type":"ask"}` 去要那句话 |
| `ui/web/detail.html` | — | 那一格 UI（`.wk` 药丸：按钮 + 状态行 + 引擎行）。⚠️ 每张页面都要自己把 `{"type":"voice"}` 转给 `XQ.wake.onMsg`（`XQ.connect` 的 catch-all 是页面自己接的） |
| `ui/web/app.js` | — | `onSay` 里 `if (!d.silent)` —— 语音来的答复由页面念，别的页面只画气泡 |
| `ui/web/style.css` | — | `.wk*` 那一块样式（含窄屏） |

---

## 2. 依赖列表

服务端（在这个项目的 `dms` 环境里，**必需**）：

| 包 | 版本（本机实测） | 干什么 |
|---|---|---|
| `sherpa-onnx` | 1.13.8 | KWS 唤醒（+ 可选：流式识别） |
| `numpy` | 2.2.6 | 音频 |
| `aiohttp` | 3.14.3 | 服务端本体（WS 也走它） |
| `openai-whisper` | 20250625 | 识别兜底（整段式） |
| `torch` | 2.14.0 | whisper 的运行时（CPU 版） |
| `scipy` | 1.15.3 | 重采样（`ui/asr.py` 用） |

```bash
d:\Anaconda3\envs\dms\python.exe -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple \
    sherpa-onnx numpy aiohttp openai-whisper scipy
```

**不需要**（也**没装**）：`sounddevice` / `PyAudio` / `soundfile` / `pydub`
—— 麦克风在浏览器那边，服务端不碰音频设备。
前端**零依赖**：一个 `wake.js` + 原生 `fetch`/`WebSocket`/`AudioContext`/`speechSynthesis`。

模型（都不进 git，`fetch_models.py` 下）：

| 模型 | 大小 | 在不在 | 说明 |
|---|---|---|---|
| KWS `…kws-zipformer-wenetspeech-3.3M…` | 十几 MB | ✅ `models/sherpa/` | 唤醒用，全程离线 |
| 流式 ASR `…streaming-zipformer…` | 133 MB | ❌ | 要 GitHub，本机不通（WinError 10060）。**没它不影响用**：自动走 whisper |
| `whisper base.pt` | 142 MB | ✅ `models/whisper/` | 识别兜底，全程离线 |

---

## 3. 部署步骤

```bash
# 1) 依赖（上一节那条 pip；dms 环境里已经装好了，新机器才要）
# 2) 模型
cd D:\sdk_env_v1.12.1\dms_project
d:\Anaconda3\envs\dms\python.exe ui\voice\fetch_models.py kws     # 唤醒模型（十几 MB）
d:\Anaconda3\envs\dms\python.exe ui\voice\fetch_models.py asr     # 可选：133 MB，要外网
#    whisper 走 ui\install_asr.bat（或已经在了就不用管）

# 3) 起服务
ui\run_ui.bat                    # = 端口 8765，默认摄像头源
#    只是看界面/听语音： ui\run_ui.bat --source demo

# 4) 打开驾驶监测页，点「听」那一格，说「你好，小瑞」
```

⚠️ 三件事：
1. **不带 `-u` 起、输出重定向到文件时，日志会一直 0 字节**（Python 的 stdout 块缓冲）。
   调试就 `python -u ui/server.py`。
2. `ui/config.json` 里有 API key（**已经进 .gitignore**），别贴出去。
3. **麦克风只在点了「听」之后才开**（和「只有点接入摄像头才接入」同一条）。
   验收脚本里有一条判据就是 `getUserMedia` 调用次数必须为 0（见下）。

---

## 4. 自测（7 个脚本，都能单独跑）

```bash
cd D:\sdk_env_v1.12.1\dms_project
d:\Anaconda3\envs\dms\python.exe -u _scratch\_check_wake.py            # 唤醒率 / 误唤醒率 / CPU
d:\Anaconda3\envs\dms\python.exe -u _scratch\_check_voice_loop.py     # 状态机（离线，不开服务）
d:\Anaconda3\envs\dms\python.exe -u _scratch\_check_voice_ws.py 8790  # 服务端协议（要起着服务）
d:\Anaconda3\envs\dms\python.exe -u _scratch\_check_voice_do.py       # 发没发 do / 按回执挑哪句话
d:\Anaconda3\envs\dms\python.exe -u _scratch\_check_wake_browser.py 8790  # 真浏览器 + 假麦克风
d:\Anaconda3\envs\dms\python.exe -u _scratch\_check_voice_jump.py     # 真页面上的真跳转
d:\Anaconda3\envs\dms\python.exe -u _scratch\_measure_latency.py 8790     # 延迟拆解
```


**每个脚本证明什么、不证明什么**（别拿它们互相冒充）：

| 脚本 | 证明 | **证明不了** |
|---|---|---|
| `_check_wake.py` | 唤醒词在合成样本 + 真人录音上的命中/误命中，常听占多少 CPU | 车里的误唤醒率（反样本只有 47 s 音频） |
| `_check_voice_loop.py` | 状态机：唤醒→断句→出字、SPEAK 期间不被自己叫醒、**念完进追问窗口（接着说不用喊唤醒词，含"趁它还在想时抢话"那一条）**、窗口超时自己关且识别器清干净、说太长由识别器自截 | 识别准不准（样本是合成的） |
| `_check_voice_ws.py` | 那条 WS 协议：顺序、事件、`say` 上的标记、**追问窗口（`follow` 事件 + 窗口里不用唤醒词 + 到点自己关 + 关了还能再喊）**、停得干净 | 浏览器里任何事 |
| `_check_voice_do.py` | **动作那条路**：真音频 → 服务端**真发了 `do`**（`go:media` / `rest_stop`）、`do` 带轮次号 `seq`、按回执挑的**是哪一句话**、迟到的回执被丢掉；外加两张手抄的表（`xiaorui.PAGES` × `chrome.js` 的 `NAV`）逐条对上、`go`/`go_same` 两张模板**真的填得满** | **浏览器里跳没跳**（那一侧扮演页面的就是 Python，没有 `location.href`）、真高德有没有数据 |
| `_check_wake_browser.py` | 页面侧：不自动开麦、16 kHz、字真画进气泡、停得干净、控制台干净 | 真机上快不快（headless + 假设备，不报毫秒数） |
| `_check_voice_jump.py` | **真浏览器里真跳了**：说「打开多媒体」→ `location.pathname` 变 `/media.html`（且识别里真出现过「多媒体」，把这次跳转钉死在语音这条路上）；已在那一页上时回执 `same:true` 且**不白重载**；「导航」→ `/nav.html?ask=rest_stop`（⚠️ 2026-09-26 从 `?do=nearby` 改的 —— 语音这条路上是「跳过去 + 问一句」，页面上那三颗按钮才走 `?do=nearby`）；`navTarget`/`samePage` 对五个键逐一算对 | 唤醒/识别准不准（假麦克风放的是合成 wav）、延迟（headless 时序不是真机）、跳到导航页之后**高德那边有没有数据** |
| `_check_barge_in.py` | 状态机那一侧：闸关着时 SPEAK 里 KWS/ASR 一个字节不进（= 老行为）、开闸后唤醒词命中就转 LISTEN、**唤醒前那半句（含命中那一片）补喂进识别器**、`_wake` 不碰 `round`、`GUARD_S` 之内叫不醒 | 真人喊不喊得灵（假 KWS/假 ASR）、车里 |
| `_check_voice_halt.py` | 浏览器那一侧：`ev:"halt"` 真的叫了 `speechSynthesis.cancel()`、**被掐断的那一句不会回一条 `voice_spoken`**（`_seq` 那一推）、服务端对迟到的回执（过期轮次 / 早不在 SPEAK）都不当真且留痕 | 服务端**会不会**发 `ev:"halt"`（真抢话那条路，靠真机手点）、真 KWS |
| `_run_regress.py` | 🔴 把上面这几条**一条一条**跑完的壳（**绝不能同时跑两份** —— 各自起服务端、各自抢 CDP 端口）。⚠️ 分两拨：`_check_voice_ws.py` / `_check_wake_browser.py` / `_check_pages.py` 是**双层壳**（外面得先有一份服务在 8790 上），这个壳自己把那份服务起起来 | —— |
| `_measure_latency.py` | 说完到答复的**分段秒数** | 页面出声那一段（那是 TTS 的事） |

---

## 5. 实测数字（2026-09-25，本机：CPU 版 torch / 这台笔记本 / 走配置里的 DeepSeek）

**唤醒**（`_check_wake.py`）
- 唤醒率 **3/3 = 100%**（正样本：3 段 SAPI 合成，「你好，小瑞」）
- 误唤醒 **0/11 段 = 0%**，反样本合计 **47 秒**音频（4 段合成 11 s + 7 段**真人录音** 36 s）
  ⚠️ 这是**下界**：47 秒 0 次 ≠ 车里 0 次。车上的数要真人/真环境录一整天。
- 常听代价：**1.55 ms / 100 ms 帧 = 1.6% 一颗核**；KWS 加载 738 ms，模型十几 MB，全离线

**延迟拆解**（`_measure_latency.py`，3 轮，按真实时间喂 5.3 s 音频）

| 段 | 平均 | 是谁花的时间 |
|---|---|---|
| ① 收口等待（说完→判定说完） | 0.84 s → **10 s** | 断句静音（**2026-09-26 用户拍板改成 10 s**，见已知限制 3） |
| ② 转文字（→`heard`） | 0.44 s | whisper base，本地 CPU（自报 427~448 ms） |
| ③ 问模型（→`reply`） | 2.57 s | **一次 DeepSeek 往返**（2.19~3.11 s，抖动几乎全在这儿） |
| **说完 → 答复** | **3.85 s → ≈13 s** | 最慢 4.38 / 最快 3.47。★ ① 改成 10 s 之后，这一行整体要 +9.2 s —— **这是用户要的**（他宁可不切话），不是变慢了 |
| ④ 出声 | 未测 | 页面 TTS（headless 里量不准，要在目标机器上量） |

**浏览器链路**（`_check_wake_browser.py`，headless Edge + 假麦克风）
- 打开页面**不碰麦克风**（`getUserMedia` 0 次）；点一下 → `listening`、`sampleRate=16000`、片在涨
- 说「你好，小瑞，我有点困」→ `ready | wake | thinking | heard:你好,小瑞,我有点困。` → 答复
  两次都画进了气泡（`我:你好,小瑞,我有点困。` / `小瑞:主人，…`）
- 再点一下 → `off`、音轨全部 `ended`、控制台零报错（放过 1 条已知的
  `ScriptProcessorNode is deprecated`，理由见 `_check_wake_browser.py` 的 `KNOWN_WARNINGS`）

---

## 6. 已知限制与代价（诚实清单）

1. **没有回声消除（AEC），是半双工的**：小瑞说话时说的**内容**它听不见（SPEAK 期间
   **ASR 一个字节都不进**，念完还压 `GUARD_S=0.4 s` 等余音散掉）。
   ★★ 但**唤醒词那一层是开的**（2026-09-26 加，用户拍板「掐断 + 听」）：念话的时候
   喊一声「你好小瑞」，它**当场闭嘴**并转过来听 —— SPEAK 里喂 KWS、命中就发
   `ev:"halt"`（页面 `XQ.tts.halt()` 掐断）再发 `ev:"wake"`，唤醒前那 2 s 的环形
   缓冲照旧补喂给 ASR（主人常常是"你好小瑞，给我…"一口气说完的）。
   · 闸是 `loop.py` 的 **`barge_in_ok`，默认 False**（= 老行为）。它由服务端在广播
     `ev:"reply"` 之前按"**这一句掐得断吗**"置位：浏览器 TTS 掐得断 → 开；
     `ui/tts.py` 那条**服务端兜底**是**一次性闩锁**、掐不断 → 页面一旦回
     `{"type":"tts"}` 就把闸关回去。⚠️ 开闸的另一半是**放开麦克风**，所以默认值必须
     是关：忘设的后果是它把自己的声音听成主人的话，比"打断不了"坏得多。
   · **自激挡板**：这一句答复里带了唤醒词就不开闸（`ear.wake_words()` 现取，
     和 `keywords.txt` 永远一致）—— 没有 AEC，它念出来就把自己叫醒。
   · ⚠️ 掐不断的那条路（兜底 TTS）念的时候喊它，**照旧不打断**：这是设计好的降级，
     不是漏做。
2. **whisper 是整段式**：出不了中间结果，页面上看不到"正在听写"，说完才一次性出字
   （② 那 0.44 s）。流式模型下来之后这一条会变（`make_asr` 自动切过去，`loop.py` 不用改）。
3. **"说完了"= 10 s 没出声，没有单句上限**（2026-09-26 用户拍板，原话：
   「语音结束的标志是我中途 10s 没有发出声音」「否则可以一直说 一直对话」）。
   · 判据只有一条：`WhisperAsr.silence_s` / `StreamAsr` 的
     `rule1_min_trailing_silence`，**两条路都是 10.0**（原来 whisper 那条是 0.9、
     流式是 0.9/1.6）。代价写在延迟表上：**答复会比主人闭嘴晚 10 s 出来**。
   · 原来那条「单句上限 = `asr.max_s(8 s) − 0.5 = 7.5 s`」**降级成安全阀**：
     `asr.max_s` 抬到 300 s，所以它是 299.5 s，只防"麦克风卡住/一直有噪声"。
     它响的话 `status.last_over` 为真、`last_over_s` 是当时攒了多久 —— **响了就是
     有东西不对**。
   · ⚠️ `asr.max_s` **不再管浏览器录音能录多久**：语音输入是一次 HTTP 传整段音频，
     那个上限在 HTTP 那一层（aiohttp `client_max_size` 1 MB ≈ 31 s），所以
     `live.js` 里另立了一个 `ASR_REC_MAX_S = 30`，点麦克风最多录 30 s。
   · ⚠️ 挂钟后果：说话超过 10 s 才停 = 整段一起转文字。whisper 整段式在 CPU 上按
     30 s 一个窗口跑，**说得越久，答得越慢**（这一条没实测，因为 300 s 没人会说到）。
4. **"念完了"这个回执不保证来**：浏览器念不出来会走服务端兜底（`XQ.tts._fallback`），
   而那条路**只报"排上队了"、不报"念完了"**。所以 `voice_answer` 里挂了个**按轮次号**
   的看门狗（不用时间认轮次）：到点还没回执就把状态机收回 IDLE，并如实说
   `念完了没等到回执，已经回去听了`。没有它，表现就是**叫醒一次之后再也叫不醒**。
5. **叫醒了不说话**（误唤醒 / 电视里的词）：识别器判不出"说完了"，会一直听到
   26 s 才回 IDLE（`loop.py` 那条兜底现在**只在"一个字都没听到"时出手**，
   所以它只管这一种情况）—— **这 26 s 里叫它，它听不见**。想改得先在目标机器上量
   `WhisperAsr.speech_peak`（那个判据是相对本句峰值算的，增益低的麦克风上"说了话"
   可能一直判不出来），没有实测就动它是在拿"安静房间说半句话被丢"换"少聋 20 秒"。
6. **这台机器上没有流式 ASR 模型**（GitHub 不通，133 MB 下不来），所以 ② 走的是
   whisper 整段式。不是设计成这样，是**没得选时的兜底**。
7. **样本是合成的**：`runs/wake_samples/` 里的正/反样本是 SAPI 离线合成 +
   模型自带的一小段真人录音。它们证明的是"链路通、协议对、词表准"，**不是"车上也这样"**。
8. **追问窗口（`FOLLOW`，2026-09-26 加）**：念完之后 10 秒内**不用再喊唤醒词**，
   接着说就接着答；连着说就是连续对话，**静默满 10 秒**才回 IDLE。补的是用户报的
   那一下：「我在说了你好 小瑞之后 它只回复一句话 根本不听我后边说的什么 也不去做
   他应该听我后边的啊」—— 原来 `SPEAK → IDLE`，而 IDLE **只认唤醒词**，
   于是那句「有什么要我帮忙的？」是个反问、反问完却不听。
   · 窗口长度 `FOLLOW_S` **2026-09-26 从 8 s 改成 10 s**：和"说完了"那条判据取
     **同一个数**（`whisper_silence_s`），用户要的是「一直跟我对话，我只在静默满
     10 s 时才结束」。**两个数必须一起改**，不然会出现"句子还没说完、对话已经
     结束"这种自相矛盾的状态。原来取 8 的理由（这个窗口开着时识别器一直在吃
     音频，太长等于"它明明听懂了却一直在听"，还会把车里的闲聊收进来）**依然成立**
     —— 是拿"一直对话"这个需求换掉了它，不是那个理由失效了。
   · 🔴 **窗口原来按挂钟关，那是个真 bug（2026-09-26 修）**：`FOLLOW` 那条分支
     只判"开窗够不够 `follow_s`"，而 `follow_s` 和"说完了"那条判据**是同一个数
     10 s** —— 于是主人在窗口里开口（哪怕第 1 秒就说），收口最早也要等到第 11 秒，
     而窗口第 10 秒就关了、`_to_idle()` 把已经收上来的**整句扔掉**。症状就是用户
     要的那句话反过来说：**追问窗口里永远接不住第二句**。修法是加上
     `not self._heard()`（和 LISTEN 那条兜底同一个写法）：**这 10 秒里真的听到过
     声音就不许关**，窗口于是顺势变成"说完了"那条判据在管。负面对照是
     `_check_voice_loop.py` 的 D2（全程静音 → 窗口照常关）。
     ⚠️ **压缩回放的测法逮不到它**：喂音频比挂钟快，窗口根本没走 —— 逮到它的是
     `_check_voice_do.py`（按真实节拍喂）。这也是 [4] 里那份"证明不了什么"的由来。
   · **关窗只有服务端说了算**（它发 `ev:"idle"`，页面才把状态行改回去）——
     两边各掐一份表迟早会不一致（窗口还会被"打住"、被下一轮叫醒提前关掉）。
   · ⚠️ **半双工那一条没变**（但多了一个例外，见 [1]）：小瑞**正在念**的时候说的话
     仍然丢（没有 AEC，它分不清是主人还是自己的声音）。**例外是唤醒词** ——
     2026-09-26 起喊「你好小瑞」能把它掐断（B 组「掐断 + 听」），但它只认那一个词，
     别指望在它念的时候直接补一句内容。**演示时要么先喊唤醒词，要么等它念完。**
   · 但"趁它还在想"（THINK，一次 DeepSeek 往返 ≈ 2.6 s，喇叭是静的）**那一句不会丢**
     了 —— 那几秒进 `self.think`，开窗时补喂给识别器。旧版本是
     `if state == THINK: return`（直接从门口扔掉）。
   · 只有**真收到 `voice_spoken`**（页面确实念完了）才开窗；看门狗收尾那条路
     `follow=False` 直接回 IDLE —— 那时候没有证据说它已经闭嘴了，放开麦克风
     就是把自己的声音当主人的话收。
9. **动作类的话，服务端只买得到"页面答应了"，买不到"做完了"**（2026-09-26 加，
   用户要的「我让它导航它肯定真导航啊 直接跳转这些啊 …它肯定要拥有这些网页的
   操控权啊」）。放音乐、查服务区、**打开某一页**（`go:<键>`）、**导航过去**
   （`rest_stop`）现在都不走模型：服务端先 `voice_do` 让**开麦那一张页面**去做、
   等回执，再照回执挑话（`xiaorui.ScriptedAgent.act_reply`）。
   · **跳转这一类的回执含义和别的不同**：`location.href` 一赋上值这一页立刻开始拆，
     那条 WebSocket 跟着断，服务端**再也验不到结果**。所以回执只表示"这一页答应了
     这个动作、这就去做"，两句话一律是正在做（「这就打开」），**不许出现完成时** ——
     `SYSTEM_PROMPT` 第 7 条那个"系统明确写了已经执行"的口子对跳转**不适用**。
     这不是保守，是主人抬头看屏幕时屏幕还是原来那一页就穿帮了。
   · 🔴 **`back()` 曾经把 `same`/`here` 丢掉（2026-09-26 修）**：`wake.js` 算出了
     "就在这一页上，不跳"（`same`）和"已经站在导航页上，就地查"（`here`），
     但那个白名单式的 `send` 里没这两个字段，服务端于是**永远收不到** ——
     后果不是报错，是**话和屏幕不一致**：站在 `detail.html` 上说「打开驾驶监测」，
     屏上什么都没发生，小瑞却说「好，主人，这就打开驾驶监测」。
     `SCRIPT["go_same"]` / `["rest_stop_here"]` 那两张表就是为这一档写的一次都没被用上。
     ⚠️ 逮到它的是 `_check_voice_jump.py`（它看的是**页面发出去的那一帧原文**，
     不是屏幕上的后果）—— 纯 Python 扮演页面的 `_check_voice_do.py` **验不到**：
     那一侧的回执是手写的，字段当然齐全。
   · **还没做的（说清楚，别当成有了）**：① 打字进来说「打开多媒体」仍然只走模型，
     不会真跳 —— 动作只在**语音**这条路上执行；② 音乐**暂停/下一首/停止**跨页做不到
     （每张页面各有自己的 `new Audio()`，`player.js` 没有对外暴露遥控接口），
     现在能做的是"在开麦那一页上放起来"；③ 跳到 `media.html` 之后那一页**没有
     `wake.js`**（首页、多媒体页故意没有耳朵），所以在多媒体页上要再叫小瑞得先
     回有耳朵的那三张页。
10. **「跳过去 + 问一句」和「要」的兑现**（2026-09-26 加，用户拍板；起点是他那句
    「我『给我导航』→ 小瑞『要不要我帮您导航到最近的服务区？』→ 我『要』→
    **屏上什么都没发生**」）。四件事串起来才是"真去做"：
    · **判得出来**：`detect_action` 认「导航」类**硬词**（`NAV_STRONG`），不带"服务区"
      三个字也算"导航过去"。⚠️ 它**故意不含**「带我」「我要去」——「我要去睡觉」
      「带我去吃饭」也是它们，光凭这几个字就跳导航页是最没礼貌的坏法（那几条留在
      `NAV_CMD` 里，靠"服务区"当上下文兜着）。**判据表**在 `_check_voice_do.py` 的 F 段。
    · **真的要跳走的那一轮不念**：`voice_say(…, jump=True)` 只画气泡、当场收回 IDLE。
      页面 180 ms 后就 `location.href`，念出来只有半句，而且 `voice_spoken` **永远不会来**。
      ⚠️ 判据是**页面那句回执**（`ok` 为真且**没有** `here`/`same`），**不是** intent：
      页面**不跳**的那三档（`here`/`same`/`ok:false`）照常念 —— 写死成"这两个 id 就不念"
      的话，主人已经站在导航页上说「要」→ 就地查了、屏上却一个字都没有（J2 段逮到）。
    · **由活着的那一页来要那句话**：`{"type":"ask","id":"rest_stop","origin":…}`。
      有起点 → 问句（`SCRIPT["ask_rest_stop"]`）+ **挂 `hub.pending_do`**；
      `origin` 是 null → 说 `ACT_FAIL["nearby"]["no_geo"]` 那句实话、**不挂**。
      ⚠️ 这一档不许拿问句顶上：听着像答应了就能成，实际上查不到 —— 那是新的一种
      "话和事不一致"。**降级照实说**：主人还没选完起点时就是这一档，"要"不会动
      （要先把起点定下来）。
    · **「要」才真做**：主人应一声（`is_affirm`，**整句相等**：见 `xiaorui.AFFIRM`）→
      `take_pending` 吐出 id → 服务端**再发**一次 `do rest_stop` → 这一页此刻就站在
      导航页上 → 回 `here:true` → 话出自 `SCRIPT["rest_stop_here"]`（「就在这一页上，
      我这就给你查」）。⚠️ 待确认是**一次性**的：主人换了话题（说了别的话）那件事就
      作废 —— 留着的话，三句之后一句「好」会把一件他早忘了的事做出来（而且是**跳页**
      那种大动作），比不做还糟。
    · ⚠️ **兑现期限 = 追问窗口 + 一次断句 + 5 s 余量**（`ui/server.py` 的
      `ask_window(ear)`）。那个"断句"是**从耳朵上现读**的
      （`ear.status()["endpoint_silence_s"]`，读不到退回 10.0），**不在这儿抄第二份 10**。
      两处**都**要现读，两个理由各自都足以致命：
        · `follow_s` 写成模块常量时服务端**当场起不来** —— `import voice.loop` 在
          `build_ear()` 函数体里，模块级看不到这个名字，那一次是
          `runs/_check_voice_do_srv.log` 里的一句 `NameError` 逮到的；
        · 静音判据写死 5 s 那个余量时，"要"**永远执行不了** —— 说一句「要的」实测要
          11.8 s（1.3 s 话音 + 10 s 静音），窗口 15 s 差一点不够，J2 段当场逮到
          （识别出来了、也在 `AFFIRM` 里，却还是走了模型那一路）。
      ⚠️ 这个期限是**下限**：注册它的那一刻主人还没听见问句。页面把那句话念完之后
      （`voice_spoken` 受理那一支）会**重新起算**一次。
    · ★★ **`voice_spoken` 的两道卫兵也是这时候加的**（`handle()` 那条分支）：
      `round` 对得上 **且** 状态还在 `speak`。因为"掐断"会制造一条**迟到**的回执
      （`speechSynthesis.cancel()` 同样触发 `onend`），不认的话它会把刚打开的 LISTEN
      推回追问窗口、还掐掉新一轮的看门狗 —— 表现是"喊醒之后立刻又变成在听"。
      丢掉时**照旧打一行日志**（不记的话，症状只剩"小瑞卡住了"，查无可查）。

---

## 7. 想改哪里

| 想改 | 改哪儿 |
|---|---|
| 唤醒词 | `ui/voice/keywords.txt`（一行一个，不用碰代码） |
| 唤醒灵不灵 / 爱不爱误唤醒 | `kws.py` 的 DEFAULTS：`keywords_threshold`（漏唤→降、误唤→升）、`num_trailing_blanks`；改完跑 `_check_wake.py --th/--nb` |
| **多久算说完 / 对话多久结束** | `asr_stream.py` 的 `whisper_silence_s`（whisper 路）**和** DEFAULTS 里的 `rule1_min_trailing_silence`（流式路）**和** `loop.py` 的 `FOLLOW_S` —— 现在是**同一个数 10 s**，改一个必须改另外两个（见已知限制 3、8） |
| 单句安全阀（不是"说多久算完"） | `ui/config.json` 的 `asr.max_s`（见已知限制 3） |
| 点麦克风最多录多久 | `ui/web/live.js` 的 `ASR_REC_MAX_S`（30 s，卡在 HTTP body 1 MB 上） |
| 念完的余音保护 | `ui/voice/loop.py` 的 `GUARD_S` |
| 追问窗口多长 | `ui/voice/loop.py` 的 `FOLLOW_S`（见已知限制 8；`VoiceLoop(follow_s=…)` 也能改，自测里就是这么把它改小来验超时的） |
| 语气/人设 | `ui/xiaorui.py`（人设 + 三档状态 + 40~60 字），**不是**这个目录 |
| 页面那一格的显示 | `ui/web/wake.js` 的 `_render()`（优先级：报错 > 正在想 > 正在听 > 没在听） |
| **认哪些话算"动作"** | `ui/xiaorui.py` 的 `detect_action`（`REST_WORDS` / `NAV_CMD` / **`NAV_STRONG`** / `ASK_WORDS` / `GO_VERBS`+`GO_WORDS`）—— ⚠️ **别为了迁就合成音的识别结果去放宽它**（见已知限制 7 和 `_probe_rest_stop_wav.py`）；改完**必须**跑 `_scratch/_check_voice_do.py` 的 F 段（那张判据表就是它的看门狗，第一行是用户原话「给我导航」） |
| **哪些话算"同意上一句"** | `ui/xiaorui.py` 的 `AFFIRM` + `is_affirm`（**去掉句末标点后整句相等**，不是 `in`）—— 加词随便加，**别改成 `in`**：那样「好的我知道了」也会把车导去服务区（见已知限制 10） |
| **「要」的兑现期限 / 跳过去之后问哪一句** | `ui/server.py` 的 `ask_window(ear)`（期限 = 追问窗口 + 现读的静音判据 + `ANSWER_MARGIN_S`）+ `ui/xiaorui.py` 的 `SCRIPT["ask_rest_stop"]`（⚠️ **必须是问句**，而且**不许用完成时**：路线是主人答应之后才算的）；`origin` 拿不到时那一档在 `ACT_FAIL["nearby"]["no_geo"]`，「不挂待确认」那一条在 `ScriptedAgent.ask_reply` |
| **它念话时能不能喊醒它** | `ui/voice/loop.py` 的 `barge_in_ok`（SPEAK 里喂不喂 KWS）+ `ui/server.py` 里置位那一段（"掐得断吗" + 自激挡板）。⚠️ 默认值**必须是 False**，理由见 [1] |
| **有哪些页面、叫什么名字** | **两张手抄的表要一起改**：`ui/xiaorui.py` 的 `PAGES`（服务端认哪个键、话里填什么名）和 `ui/web/chrome.js` 的 `const NAV`（左栏 + 真跳哪个文件）。键和文件名**两边都得对**，对不上时页面回 `no_target`、小瑞照实说找不到（不会跳到白页）|
| 先回执后跳的那一小段 | `ui/web/wake.js` 里 `go:` 分支的 `JUMP_MS`（180 ms）—— 同步跳的话那一帧回执多半还没发出去，服务端会说"没收到回执"，而页面其实已经跳了 |
| 服务端等回执等多久 | `ui/server.py` 的 `voice_do(hub, ws, aid, timeout=…)`（放音乐/跳转 1.5 s，问服务区 4.0 s —— 后者页面可能要现调一次定位）|
