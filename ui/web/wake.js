/* ===========================================================================
   小瑞的耳朵：常听「你好，小瑞」（浏览器持麦，服务端只做推理）
   ---------------------------------------------------------------------------
   这是新加的一层，**不动 live.js 里任何东西**，只借它现成的三样：
     · `XQ.connect` 的 WS 链路（`link.send`）
     · `XQ.speak`   说话（浏览器语音合成，服务端兜底都在它里面）
     · `XQ.flash` / `XQ.mascot.react` 给用户的即时反馈

   数据流（每一段都有它非这样不可的理由）：

     点按钮 → getUserMedia → AudioContext(16 kHz) → 攒够 100 ms
       → Int16 → base64 → WS `{"type":"pcm"}` ─→ 服务端 KWS 常听（1.6% 一颗核）
                                                 ├ 命中 → `{"ev":"wake"}`  → 这里响一声、亮状态
                                                 └ 断句 → whisper → DeepSeek
                                                          → `{"ev":"reply"}` → 这里 XQ.speak
                                                          → 念完回 `{"type":"voice_spoken","round":N}`
                                                            → 服务端开**追问窗口**（10 s）
                                                              → `{"ev":"follow"}` → 状态行改「在听 —— 接着说」
                                                              → 静默满 10 s → `{"ev":"idle"}` 收窗

     ★★ 2026-09-26 加的第二条路（小瑞**正在念**的时候主人喊唤醒词）：
       念 → 服务端 KWS 命中 → `{"ev":"halt"}` → 这里 `XQ.tts.halt()`（当场闭嘴）
                                          → `{"ev":"wake"}` → 进 LISTEN，主人的话接着听
       用户原话：「它回复我话的时候 我说话为啥它听不见」。服务端只在小瑞**念得断**
       的时候才开这个口子（浏览器这条路），走服务端兜底念的时候是**不开**的
       —— 那条路掐不断，开了它就听自己说话。见 `ui/voice/loop.py` 的 `barge_in_ok`。

   ★ **2026-09-26 加了追问窗口。** 原来"念完 → IDLE"，而 IDLE **只认唤醒词** ——
     主人问「你好小瑞」，小瑞答「有什么要我帮忙的？」，主人接着说「给我放个音乐」，
     这一句被**整句丢掉**。用户报的原话：「我在说了你好 小瑞之后 它只回复一句话
     根本不听我后边说的什么 也不去做 他应该听我后边的啊」。
     现在念完之后 10 秒内接着说就接着答，连着说就是连续对话。
     ★ 2026-09-26 用户又把它和"说完了"**并成同一个数**：「语音结束的标志是我中途
       10s 没有发出声音」「否则可以一直说 一直对话」—— 所以窗口从 8 s 改成 10 s，
       而且"说完了"那条判据也是 10 s（`asr_stream.py`）。**两个数一起动**。
     ⚠️ **窗口关不关由服务端说了算**（它发 `idle` 我们才关），这边一个计时器都不起
     —— 见 `XQ.wake.follow` 的注释。
     ⚠️ 小瑞**正在念**的时候插话仍然是丢的（半双工，没有回声消除）——
        但**喊唤醒词是例外**：那一下会把它的嘴掐掉、立刻开始听（见上面那条和
        `XQ.tts.halt`）。"趁它还在想"的那一句也**已经能捞回来了**（服务端那边）。

   ⚠️ 五条纪律，全是这套东西实际会咬人的地方：

   1. ★ **2026-09-25 晚翻过来了：打开页面就自己开麦。** 用户原话
      「能不能不需要我按就可以说你好小瑞 然后唤醒了」。而这一条**原来写的是
      「绝不自动开麦」**（抄的是他自己 2026-09-24 对摄像头那句「只有我点接入
      摄像头才接入」）—— **是他本人把这条规矩翻过来的**，不是谁顺手改的。
      · 自动开麦的挂点只能是 `hello` 之后（`link.online` + 引擎状态都要到手），
        所以调用点在**每张页面的 `onHello` 里**，不在 DOMContentLoaded。
      · **「停」在这一次会话内必须黏住**：用户点过「停」再翻页，不许又自己开起来。
        所以存的是 `sessionStorage['xq.wake.want']='off'` —— 它只记"用户这一次
        明确说了不要"，**关掉浏览器就没了**，下次启动回到默认的"自己听"。
        ⚠️ 原来那句「不往 localStorage 存（存了就等于下次自动开）」的顾虑在这里
        **正好反过来**：自动听就是要的默认值，要防的只是"用户关过又被系统打开"。
        所以这里**既不存 localStorage，也不存"上次是开的"**。
      · 实测（`_scratch/_probe_wake_auto.py`，两臂对照、**全程不点任何东西**）：
        权限给过之后 `ctx.state='running'`、`sampleRate=16000`、音频片真的在走，
        唤醒命中、答复也画进了气泡；**带不带 `--autoplay-policy` 都一样**。
        唯一的门槛是**麦克风权限必须给过一次**（浏览器会记住，见第 7 条）。
   2. **采样率必须真的是 16000。** `new AudioContext({sampleRate:16000})` 在 Chrome/
      Edge 上会照做（浏览器内部重采样），JS 一行重采样都不用写 —— 但**要检查**
      `ctx.sampleRate`。它要是不是 16000，喂进去的音频就是"放慢/加快"的版本，
      识别结果会是胡话，**而且不报任何错**（`ui/asr.py` 头三个陷阱里的第三个）。
   3. **`XQ.speak` 返回 false 时也要告诉服务端"念完了"。** 语音开关关着、页面在后台、
      浏览器念不出来 —— 这些情况下 `XQ.speak` 直接返回 false 就结束了，而这边的
      状态机在等 `voice_spoken`。**不发的话小瑞就永远卡在"正在说话"状态，叫不醒**。
      所以这里一律"先发 done，再说话"。
      ★★ 2026-09-26 补一句：**也不能迟发。** 这条回执现在带**轮次号**
      （`XQ.wake.round`，服务端在 `ev:"reply"` 里给下来的），服务端只认"轮次对得上
      而且状态还停在 SPEAK"的那一条。原因就是掐断（`XQ.tts.halt`）会调
      `speechSynthesis.cancel()`，而 `cancel()` **也会触发 `onend`** ——
      一条**上一轮**的回执要是被当真，会把刚打开的 LISTEN 推回追问窗口，还掐掉
      新一轮的看门狗。`halt()` 里推 `_seq` 是第一道防线，轮次号是第二道。
   4. **文字一定要显示出来，不能只靠声音。** 演示现场静音、没插音箱、语音开关关着，
      都发生过。答复写在面板上，功能就是可验证的；只出声的版本，那些情况下等于坏了。
   5. **每一片音频都标了序号。** 服务端是异步处理的，丢片/乱序时**别装作没发生** ——
      序号跳了就在状态行里说清楚（"音频有丢片，可能听不全"），而不是让小瑞答得
      驴唇不对马嘴还查不出原因。
   6. **`ctx.state` 必须是 `running`。** `suspended` 的 AudioContext 里
      `onaudioprocess` **一次都不触发** —— 状态行会照写「在听 —— 说「你好，小瑞」」、
      按钮亮着，而**一帧音频都没收到**。又是本项目的头号失败形态（不报错的坏掉）。
      ⚠️ 说清楚：**这一条是安全带，不是我量出来过的故障** —— 实测里 `ctx.state`
      一直是 running（带不带 `--autoplay-policy` 都是）。之所以照样要写，是因为
      "它为什么一定是 running"的机制我没法在别的机器/别的浏览器上担保，而它一旦
      不成立就是**静默无声**，事后查不出来。
   7. **权限框没人点的时候，`getUserMedia` 既不 resolve 也不 reject。** 页面会
      **永远**停在 'starting'，界面上只有一句「正在起麦克风…」转下去，一个字都
      不解释。所以到点（8 s）就说人话：「浏览器在等麦克风权限（点一下地址栏那个
      小锁里的「允许」）」。⚠️ 这一格 **headless 测不到**（headless 里根本没有权限
      框、Chromium 直接拒），真机 kiosk 上那个气泡弹在哪儿只有人眼说了算。
   =========================================================================== */
'use strict';

/* ---------------------------------------------------------------------------
   定位 —— 「最近的服务区」那件事的**起点**（`nav.html` 和语音问服务区都走这里）。
   ---------------------------------------------------------------------------
   为什么放在 wake.js 而不是 nav.html：**任何一张开着麦的页面都可能被问到
   "最近有服务区吗"**（服务端认的是"谁开麦谁算数"）。所以这个能力必须跟着耳朵走，
   而不是跟着地图走 —— nav.html 只是**恰好**还有一张地图可以顺手画出来。

   ⚠️ 四条，全是这套东西实际会咬人的地方：
   1. **`navigator.geolocation` 只在安全上下文里存在。** `http://127.0.0.1` 算
      （浏览器把它当 localhost），**局域网 IP 不算** —— 从 `http://192.168.x.x:8765`
      打开时这个对象**压根不存在**，`if (!g)` 那条分支就是给这种时候用的。
      不去 `getCurrentPosition` 试一下再报错：没有对象，调它就是 TypeError。
   2. **权限气泡没人点的时候，它既不成功也不失败** —— 和文首第 7 条麦克风那个坑
      是**同一个形状**。而且它的 `timeout` 选项**在这段时间里不生效**
      （2026-09-25 `_scratch/_probe_geo_nearby.py` 量到过：headed 窗口、CDP 预授权、
      `navigator.permissions` 报 granted，`getCurrentPosition` 照样 code 3 超时）。
      所以 `ask()` **自己上闹钟**，到点就当拿不到 —— 它保证**永不 pending**。
   3. **这台机器拿不到坐标**（同一份探针：Windows 侧 Allow + lfsvc 在跑 + 网卡都在，
      但机器上挂着 Array Networks 的 SSL VPN 和两张 VMware 虚拟网卡，定位要联网问
      微软，多半卡在这一层）。→ 用户拍板：**拿不到就照实说 + 让人手动选起点**
      （`nav.html` 的下拉点位 / 在地图上点一下），**不编坐标**。
   4. **缓存 5 分钟。** 车在动，但一个"最近的服务区"不会因为 100 m 换一个；
      而语音问一次就现调一次定位，正好会撞上坑 2 那个几秒的窗口。
   --------------------------------------------------------------------------- */
XQ.geo = {
  last: null,                 // {lat, lng, acc, manual, ts}
  TTL: 5 * 60 * 1000,
  ASK_MS: 2500,

  /** 记下一个坐标。`manual:true` = 人在导航页上自己设的起点（要在地图上标出来）。 */
  remember(p) {
    if (!p || p.lat == null || p.lng == null) return null;
    XQ.geo.last = { lat: +p.lat, lng: +p.lng, manual: !!p.manual,
                    acc: (p.acc == null ? null : +p.acc), ts: Date.now() };
    return XQ.geo.last;
  },

  /** 手上这个坐标还新不新。 */
  fresh() {
    const l = XQ.geo.last;
    if (!l || Date.now() - l.ts > XQ.geo.TTL) return null;
    return l;
  },

  /** 拿一个坐标。**永不 pending**（见第 2 条）：拿不到就回 `{why:'no_geo'}`。 */
  ask(ms) {
    const l = XQ.geo.fresh();
    if (l) return Promise.resolve(l);
    const g = navigator.geolocation;
    if (!g) return Promise.resolve({ why: 'no_geo' });      // 见第 1 条
    const lim = ms || XQ.geo.ASK_MS;
    return new Promise((resolve) => {
      let done = false;
      const fin = (v) => { if (!done) { done = true; resolve(v); } };
      const t = setTimeout(() => fin({ why: 'no_geo' }), lim);
      try {
        g.getCurrentPosition((pos) => {
          clearTimeout(t);
          const c = pos && pos.coords;
          fin(XQ.geo.remember(c ? { lat: c.latitude, lng: c.longitude,
                                    acc: c.accuracy } : null) || { why: 'no_geo' });
        }, (err) => {
          clearTimeout(t);
          fin({ why: 'no_geo', code: err && err.code });
        }, { enableHighAccuracy: false, timeout: lim, maximumAge: 60000 });
      } catch (e) { clearTimeout(t); fin({ why: 'no_geo' }); }
    });
  },
};

/* ---------------------------------------------------------------------------
   「跳到哪一页」的两个小工具（`ev === 'do'` 的 `go:` / `rest_stop` 分支用）
   ---------------------------------------------------------------------------
   ★★ 2026-09-26 用户原话：「它可以对这个网页所有东西进行操控 比如我让它导航它
      肯定真导航啊 直接跳转这些啊」。这两个函数就是那句"直接跳转"的落点。

   ⚠️ 目标页文件名**只从 `chrome.js` 的 `XQ.NAV` 取**，不在这儿另抄一份：
      左栏一改，抄的那份就开始跳错页 —— 而**跳到不存在的文件在浏览器里是一张
      白页**，看起来和"这一页本来就没做"一模一样（这个项目在 `PAGES` 上踩过一次）。
   ⚠️ 键必须和服务端 `ui/xiaorui.py` 的 `PAGES` 对齐。对不上时回 `no_target`，
      让小瑞照实说"这一页我找不到" —— 这是设计好的那一档，不是静默失败。
   --------------------------------------------------------------------------- */

/** 键 → 目标页文件名（`XQ.NAV` 的第 3 个字段）。取不到回空串。 */
function navTarget(key) {
  const nav = (window.XQ && XQ.NAV) || null;
  if (!nav || !key) return '';
  for (let i = 0; i < nav.length; i++) {
    if (nav[i] && nav[i][0] === key) return nav[i][2] || '';
  }
  return '';
}

/** 现在这一页是不是 `target`。比**路径最后一段**（页面都挂在根上：`/detail.html`），
 *  所以不掺目录、不掺 query。 */
function samePage(target) {
  const here = (location.pathname.split('/').pop() || '').toLowerCase();
  return !!target && here === String(target).toLowerCase();
}

XQ.wake = {
  /* ⚠️ **只存"用户这一次明确说了停"**（sessionStorage，关浏览器就没了）——
     见文首第 1 条，别改成 localStorage，也别存"上次是开的"。 */
  WANT_KEY: 'xq.wake.want',
  silent: false,           // 自动开麦那条路不弹提示（每翻一页弹一次太吵）
  _permTimer: null,        // 权限框没人点时的看门狗（见文首第 7 条）
  link: null,
  cfg: null,
  state: 'off',            // off | starting | listening | error
  why: '',                 // error 时给一句人话
  engine: null,            // hello.voice 报上来的（模型在不在、识别的状态）
  partial: '',
  reply: '',
  lastHeard: '',
  frames: 0,
  sent: 0,
  lost: 0,                 // 序号跳了的片数（见第 5 条）
  goneWhy: '',             // 最近一次丢片/出错时服务端给的原因
  busy: false,             // 服务端正在转文字/问模型（这段时间界面上要有话说）
  /* ★ 追问窗口的秒数，**服务端说了算**（`ev:"follow"` 带过来的 `sec`，见
     `ui/voice/loop.py` 的 FOLLOW）。非 0 = 小瑞刚答完，这段时间**不用再喊
     唤醒词**，接着说就接着答。窗口关掉是由服务端发一条 `ev:"idle"` 通知的
     —— 所以这里**只存秒数，不起计时器**：两边各掐一份表，迟早会不一致
     （服务端的窗口还可能被"打住"、被下一轮叫醒提前关掉）。 */
  follow: 0,
  /* ★★ 2026-09-26：这一轮答复的**轮次号**（服务端 `ev:"reply"` 带下来的
     `round`）。念完的时候要**原样带回去**（`voice_spoken`）—— 服务端靠它对
     一条迟到的回执说"不"。⚠️ 页面自己**算不出**这个数，它只存在服务端那边；
     这里只做一件事：收到就存下，发的时候带回去。见 server.py 的
     `voice_spoken` 那两道卫兵。 */
  round: 0,
  /* ★★ 2026-09-26：跳过来之后要**替这一页**跟服务端要的那一句话。见 `ask()`。 */
  _ask: null,
  _seq: 0,
  _stream: null, _ctx: null, _src: null, _proc: null, _sink: null,
  _acc: null,              // 攒着还没到 100 ms 的样本
  _btn: null, _host: null,

  SR: 16000,

  attach(link, cfg) {
    XQ.wake.link = link || null;
    XQ.wake.cfg = cfg || {};
    XQ.wake.engine = cfg || null;
    /* ⚠️ 字段名有两套，这里抹平：
         · `hello.voice`（服务端 `Hub.voice_hello`）报的是 `asr_engine`，
           因为那一份是给**页面/语音输入**看的，全站都叫这个名字；
         · `ready` 带的那份（`Hub.ear_hello`）是在它基础上加了运行时字段，
           挨着 `kws` 放的是 `asr`（**引擎自报的那一句**）。
       不抹平的话，第二行状态里会少半截 —— 而那是演示时唯一能一眼答出
       "识别走的是哪条路"的地方。 */
    if (XQ.wake.engine && !XQ.wake.engine.asr && XQ.wake.engine.asr_engine) {
      XQ.wake.engine.asr = XQ.wake.engine.asr_engine;
    }
    XQ.wake._render();
  },

  /** 绑按钮。`host` 是显示状态/文本的容器（可以不传，那就只做提示）。 */
  bind(btn, host) {
    XQ.wake._btn = btn || null;
    XQ.wake._host = host || null;
    if (btn) {
      btn.onclick = () => XQ.wake.toggle();
      btn.removeAttribute('disabled');       // 和 XQ.asr 一样：永不置灰，点了给一句人话
      btn.setAttribute('aria-pressed', 'false');
    }
    XQ.wake._render();
  },

  toggle() { if (XQ.wake.state === 'listening' || XQ.wake.state === 'starting') XQ.wake.stop('manual'); else XQ.wake.start(); },

  /**
   * ★★ 2026-09-26：**替这一页**跟服务端要一句话说（用户拍板的「跳过去 + 问一句」）。
   *
   * 为什么是页面来要，而不是跳之前就说：`ev:"do"` 的 `go:`/`rest_stop` 那一支
   * 回执之后 **180 ms** 就 `location.href`，这一页连 document 一起拆 ——
   * `speechSynthesis` 没了，那句话会被**拦腰切掉**，而且"念完了"那条回执
   * （`voice_spoken`）**永远不会来**。所以跳之前那一轮**不念**（服务端
   * `voice_say(jump=True)`），由跳过来之后活着的那一页在**麦克风起来之后**发
   * `{"type":"ask","id":…,"origin":…}`，服务端才组得出一句完整的话。
   *
   * 调用点：**目标页自己**（现在是 `nav.html`，见那边 `?ask=` 那一段），而且
   * 必须在**起点定完之后**才调 —— `origin` 决定服务端说哪一句话：
   *   · 有起点 → 「要不要我导到最近的服务区？」并挂上"待确认"，主人说「要」才真去查；
   *   · 没有起点 → 照实说"拿不到定位"，**不挂**（答应也没坐标可查）。
   * 起点还没定就抢着问，会永远问成第二档 —— 那就是"话和屏幕不一致"。
   *
   * ⚠️ 攒着不发的情况只有一种：**麦克风还没起来**（`state !== 'listening'`）。
   *    服务端认的是"谁开麦谁算数"（`server.py` 的 `voice_send` 单播给 `ear_ws`），
   *    页面还没 `voice_start` 的话这条消息会被丢掉。所以先存下来，等
   *    `start()` 走到 'listening' 那一刻补发。**只发一次**（`_ask` 存进去就清）。
   * ⚠️ 也就是说：**麦克风起不来（用户点过「停」、没给权限）这一句就永远不发** ——
   *    这是对的，不是漏做：没有麦克风就没有「要」可言，问一句只会让人白答应。
   */
  ask(id, origin) {
    if (!id) return;
    XQ.wake._ask = { id: String(id), origin: origin || null };
    if (XQ.wake.state === 'listening') XQ.wake._flushAsk();
  },

  /** 把攒着的那个 `ask` 发出去（**只发一次**）。见 `ask()`。 */
  _flushAsk() {
    const a = XQ.wake._ask;
    if (!a) return;
    if (!XQ.wake.link || !XQ.wake.link.online) return;    // 没连上就继续攒着
    XQ.wake._ask = null;
    XQ.wake.link.send({ type: 'ask', id: a.id, origin: a.origin });
  },

  /** ★ 不用点任何一下就开始听 —— 用户 2026-09-25 晚要的就是这个（见文首第 1 条）。
   *
   *  调用点：**每张有唤醒 UI 的页面的 `onHello` 里，紧挨着 `attach()` 之后**。
   *  不能写在 DOMContentLoaded 里，因为那时 `link.online` 还没有、引擎状态也没到，
   *  `start()` 第一句就会退回去。
   *
   *  ⚠️ 三个"不许自动开"的口子，缺一个都会变成骚扰：
   *    · `state !== 'off'` —— 已经在听/正在起/出错，就别再起一遍
   *      （`onHello` 在**换源成功**时也会跑，不是只在打开页面时跑一次）；
   *    · `sessionStorage.want === 'off'` —— 用户点过「停」，这一次会话就别再自作主张；
   *    · `link.online` —— 没连上服务端时起了也白起（`start()` 会弹一句"还没连上"，
   *      而自动这条路弹提示是**打扰**：用户什么都没做，凭什么被弹一句）。 */
  autostart() {
    const w = XQ.wake;
    if (w.state !== 'off') return false;
    try { if (sessionStorage.getItem(w.WANT_KEY) === 'off') return false; } catch (e) {}
    if (!w.link || !w.link.online) return false;
    w.silent = true;
    w.start();
    return true;
  },

  /* ---------------------------------------------------------------- 起 */
  async start() {
    if (XQ.wake.state === 'listening' || XQ.wake.state === 'starting') return;
    if (!XQ.wake.link || !XQ.wake.link.online) {
      XQ.flash('还没连上座舱服务（用 run_ui.bat 启动）');
      return;
    }
    const eng = XQ.wake.engine || {};
    if (eng.kws_model === null || eng.kws_model === undefined) {
      // 模型没下的时候**别假装能听** —— 说清出路，比转圈强
      XQ.flash('唤醒模型还没下好：跑 python ui/voice/fetch_models.py kws');
      XQ.wake.state = 'error';
      XQ.wake.why = '没有唤醒模型';
      XQ.wake._render();
      return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      XQ.wake.state = 'error';
      XQ.wake.why = '这个浏览器不给用麦克风（要 http://localhost 或 https）';
      XQ.wake._render();
      XQ.flash(XQ.wake.why);
      return;
    }

    /* ★ 这条是"自动开麦"那条路吗？—— 是的话最后不弹「在听了」那种提示
       （每翻一页弹一次太吵）。**出错的提示一律照弹**：自动开的麦也是麦，
       它坏了用户有权立刻知道，不能因为"是他没要求开的"就闷着。 */
    const quiet = XQ.wake.silent;
    XQ.wake.silent = false;

    XQ.wake.state = 'starting';
    XQ.wake.why = '';
    XQ.wake.partial = '';
    XQ.wake.reply = '';
    XQ.wake.busy = false;
    XQ.wake.frames = 0; XQ.wake.sent = 0; XQ.wake.lost = 0; XQ.wake._seq = 0;
    XQ.wake._render();

    /* 手动点开的就记一笔"这次会话要听" —— 不然用户先点「停」再点「听」，
       翻页之后 `want` 还是 'off'，他明明刚点过「听」却又不响了。 */
    if (!quiet) { try { sessionStorage.setItem(XQ.wake.WANT_KEY, 'on'); } catch (e) {} }

    /* ★ 见文首第 7 条：权限框没人点的时候 `getUserMedia` 的 promise **既不
       resolve 也不 reject**，页面会永远停在 'starting' 转圈。到点就说人话。
       ⚠️ 这只是**把话说出来**，不去打断那个 promise —— 万一用户在两秒后点了
       「允许」，promise 一 resolve，下面照常走到 'listening'（状态行自己会翻回来）。 */
    clearTimeout(XQ.wake._permTimer);
    XQ.wake._permTimer = setTimeout(() => {
      if (XQ.wake.state !== 'starting') return;
      XQ.wake.why = '浏览器在等麦克风权限（点一下地址栏那个小锁里的「允许」）';
      XQ.wake._render();
      XQ.flash(XQ.wake.why);
    }, 8000);

    let stream;
    try {
      /* ⚠️ 关掉浏览器的自动增益/降噪/回声消除：KWS 是拿**声学特征**去比对的，
         浏览器为了"听着舒服"做的那些处理会改掉频谱（降噪尤其）。这个模型是
         在干净语音上训的，交给它原始一点的信号反而更稳。
         （反正服务端在说话时不听，回声消除在这里没有用武之地。） */
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: false,
                 noiseSuppression: false, autoGainControl: false },
      });
    } catch (e) {
      clearTimeout(XQ.wake._permTimer);          // 有真错了就别再说"在等权限"
      XQ.wake.state = 'error';
      XQ.wake.why = '拿不到麦克风：' + ((e && e.name) || e) +
                    (e && e.name === 'NotAllowedError' ? '（权限被拒了，地址栏那个小锁里改）' : '');
      XQ.wake._render();
      XQ.flash(XQ.wake.why);
      return;
    }
    clearTimeout(XQ.wake._permTimer);            // 麦到手了，看门狗撤掉
    XQ.wake._stream = stream;

    let ctx;
    try { ctx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: XQ.wake.SR }); }
    catch (e) { ctx = null; }
    if (!ctx) {
      XQ.wake._release();
      XQ.wake.state = 'error'; XQ.wake.why = '这个浏览器起不了 AudioContext';
      XQ.wake._render(); XQ.flash(XQ.wake.why);
      return;
    }
    XQ.wake._ctx = ctx;
    // 见第 2 条：**必须核对**。不等就不是 16 k，识别会变成胡话而且不报错。
    if (Math.abs(ctx.sampleRate - XQ.wake.SR) > 1) {
      XQ.wake.stop('badrate');
      XQ.wake.state = 'error';
      XQ.wake.why = '浏览器给的采样率是 ' + ctx.sampleRate + '，不是 16000 —— 识别会不准，先停下';
      XQ.wake._render(); XQ.flash(XQ.wake.why);
      return;
    }

    /* ★ 见文首第 6 条：**suspended 的 AudioContext 里 `onaudioprocess` 一次都不
       触发** —— 界面会写「在听」而一帧音频都收不到。所以"挂起来"这件事必须在
       **宣布 listening 之前**当场问清楚，不能等界面上看起来对了就算。
       先尽力 `resume()` 一次（有些情况下它是能自己起来的），不行就如实报错、
       关掉麦克风（不让它亮着指示灯干等）。 */
    if (ctx.state !== 'running') {
      try { await ctx.resume(); } catch (e) {}
    }
    if (ctx.state !== 'running') {
      XQ.wake.stop('notrunning');
      XQ.wake.state = 'error';
      XQ.wake.why = '浏览器把音频挂起了（' + ctx.state + '），这样一句都听不到，先停下';
      XQ.wake._render(); XQ.flash(XQ.wake.why);
      return;
    }

    const src = ctx.createMediaStreamSource(stream);
    const proc = ctx.createScriptProcessor(4096, 1, 1);
    // 没地方接的 ScriptProcessor 在某些版本上不会被触发，接一个静音出口
    const sink = ctx.createGain();
    sink.gain.value = 0;
    XQ.wake._acc = new Float32Array(0);
    proc.onaudioprocess = (ev) => {
      if (XQ.wake.state !== 'listening') return;
      const buf = ev.inputBuffer.getChannelData(0);
      XQ.wake._push(new Float32Array(buf));       // 拷一份，inputBuffer 会被复用
    };
    src.connect(proc); proc.connect(sink); sink.connect(ctx.destination);
    XQ.wake._src = src; XQ.wake._proc = proc; XQ.wake._sink = sink;

    XQ.wake.state = 'listening';
    XQ.wake._render();
    if (XQ.mascot && XQ.mascot.react) XQ.mascot.react('listen');
    XQ.wake.link.send({ type: 'voice_start' });   // 服务端那边开始建唤醒器
    /* ★★ 2026-09-26：跳过来之前攒下的那句 `ask`（见 `ask()`），到这一刻才发。
       ⚠️ **必须在 `voice_start` 之后**：服务端认的是"谁开麦谁算数"，先发 ask 的话
           `hub.ear_ws` 还没轮到这一页，那条消息会被直接丢掉。 */
    XQ.wake._flushAsk();
    XQ.flash('在听了 —— 说「你好，小瑞」');
  },

  stop(why) {
    const was = XQ.wake.state;
    XQ.wake._release();
    if (was === 'listening' || was === 'starting') XQ.wake.state = 'off';
    XQ.wake._render();
    if (XQ.wake.link && XQ.wake.link.online) XQ.wake.link.send({ type: 'voice_stop' });
    /* ★ 见文首第 1 条：**只有用户自己点的「停」才黏住**（且只黏这一次会话）。
       自动那条路自己退回来（badrate / notrunning）**不算"用户不要"** ——
       把那种也记成 'off' 的话，用户翻一页就再也不自动开了，可他从来没说过不要。 */
    if (why === 'manual') {
      try { sessionStorage.setItem(XQ.wake.WANT_KEY, 'off'); } catch (e) {}
      XQ.flash('不听了');
      return;
    }
    if (why === 'badrate' || why === 'notrunning') return;
    if (was === 'listening') XQ.flash('不听了');
  },

  _release() {
    clearTimeout(XQ.wake._permTimer);            // 麦已经在收了，看门狗没意义了
    try { if (XQ.wake._proc) { XQ.wake._proc.onaudioprocess = null; XQ.wake._proc.disconnect(); } } catch (e) {}
    try { if (XQ.wake._src) XQ.wake._src.disconnect(); } catch (e) {}
    try { if (XQ.wake._sink) XQ.wake._sink.disconnect(); } catch (e) {}
    try { if (XQ.wake._ctx) XQ.wake._ctx.close(); } catch (e) {}
    // ⚠️ 一定要 stop 每条音轨：只关 AudioContext 的话**麦克风的使用指示灯还亮着**
    //    （和摄像头"不 release 就换不了"是同一类事）。
    try { if (XQ.wake._stream) XQ.wake._stream.getTracks().forEach((t) => t.stop()); } catch (e) {}
    XQ.wake._stream = XQ.wake._ctx = XQ.wake._src = XQ.wake._proc = XQ.wake._sink = null;
    XQ.wake._acc = null;
  },

  /* ---------------------------------------------------------------- 送 */
  _push(chunk) {
    const old = XQ.wake._acc || new Float32Array(0);
    const all = new Float32Array(old.length + chunk.length);
    all.set(old, 0); all.set(chunk, old.length);
    // 按 100 ms 一片切，和离线回测/模型帧长对齐
    const n = XQ.wake.SR / 10;
    let off = 0;
    while (all.length - off >= n) {
      XQ.wake._send(all.subarray(off, off + n));
      off += n;
    }
    XQ.wake._acc = all.subarray(off);            // 尾巴留着，凑下一片
  },

  _send(floats) {
    // Float32(-1~1) → Int16。⚠️ 别忘了乘 32767 再取整（不乘就是全零，静默无声）。
    const pcm = new Int16Array(floats.length);
    for (let i = 0; i < floats.length; i++) {
      let v = floats[i];
      if (v > 1) v = 1; else if (v < -1) v = -1;
      pcm[i] = v < 0 ? v * 32768 : v * 32767;
    }
    const bytes = new Uint8Array(pcm.buffer);
    let bin = '';
    for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    XQ.wake._seq += 1;
    XQ.wake.sent += 1;
    XQ.wake.link.send({ type: 'pcm', seq: XQ.wake._seq, b64: btoa(bin) });
  },

  /* ---------------------------------------------------------------- 收 */
  onMsg(d) {
    const ev = d.ev || '';
    if (ev === 'ready') {
      XQ.wake.engine = d.voice || XQ.wake.engine;
      XQ.wake._render();
      return;
    }
    if (ev === 'wake') {
      XQ.wake.partial = '';
      XQ.wake.reply = '';
      XQ.wake.follow = 0;          // 新的一轮开始了，上一轮的追问窗口作废
      XQ.wake._chime();
      XQ.flash('我在（' + (d.word || '唤醒词') + '）');
      XQ.wake._render();
      return;
    }
    if (ev === 'halt') {
      /* ★★ 2026-09-26：**主人在小瑞念话的时候把它叫醒了**，服务端要它当场闭嘴
         （用户原话：「它回复我话的时候 我说话为啥它听不见」）。`XQ.tts.halt()`
         里那一推 `_seq` 是关键，理由写在 live.js 那边 —— 一句话版：`cancel()`
         也会触发 `onend`，不推的话"被掐断"会被当成"念完了"，白回一条
         `voice_spoken` 出去。 */
      if (window.XQ && XQ.tts && XQ.tts.halt) XQ.tts.halt();
      /* 屏上不留一句没念完的话。⚠️ 清的只是**这一轮的话**，不动 `lastHeard`
         （那是"我听到主人说了什么"，主人正靠它确认自己有没有被听见）。 */
      XQ.wake.reply = '';
      XQ.wake.partial = '';
      XQ.wake.busy = false;
      XQ.wake._render();
      XQ.flash(d.why || '好，我不说了，你说');
      return;
    }
    if (ev === 'follow') {
      // ★ 2026-09-26：小瑞答完了，服务端开着**追问窗口**（`ui/voice/loop.py` 的
      //   FOLLOW）—— 这段时间接着说就行，不用再喊唤醒词。关窗由服务端发
      //   `ev:"idle"` 通知，这里不掐表（见 `XQ.wake.follow` 的注释）。
      XQ.wake.follow = Number(d.sec) || 0;
      XQ.wake._render();
      return;
    }
    if (ev === 'partial') { XQ.wake.partial = d.text || ''; XQ.wake._render(); return; }
    if (ev === 'heard') { XQ.wake.lastHeard = d.text || ''; XQ.wake._render(); return; }
    if (ev === 'thinking') {
      // 转文字那一段是 **0.5~2 秒的阻塞调用**（whisper 整段识别），服务端把它
      // 丢在线程里跑，所以这里必须有话说 —— 否则用户看到的是"说完了，界面
      // 一动不动"，然后突然蹦出一句答复。
      XQ.wake.partial = '';
      XQ.wake.reply = '';
      XQ.wake.busy = true;
      XQ.wake._render();
      return;
    }
    if (ev === 'do') {
      // ★ 2026-09-25：服务端让**这一张页面**去做一件事，并且**在等回执**。
      //
      // 为什么是单播而不是广播：见 `server.py` 的 `voice_do`。一句话版 ——
      // 广播会让每个开着的标签页各放一遍，差几百毫秒，听出来是回声。
      //
      // ⚠️ 回执**必须发**，成功失败都发：服务端拿它决定小瑞说哪句话
      //   （成功了才说「这就给您放」，见 `xiaorui.py` 的 `ACT_FAIL`）。
      //   不发 = 服务端只能等到 1.5 s 超时，然后说一句"没收到回执"，
      //   而实际上音乐可能已经响起来了 —— 那就成了另一种"话和事不一致"。
      const id = d.id || '';
      const seq = d.seq;
      const back = (res) => {
        if (XQ.wake.link && XQ.wake.link.online) {
          XQ.wake.link.send({ type: 'do_result', id: id, seq: seq,
                              ok: !!res.ok, why: res.why || '',
                              file: res.file || '', title: res.title || '',
                              lat: (res.lat == null ? null : res.lat),
                              lng: (res.lng == null ? null : res.lng),
                              acc: (res.acc == null ? null : res.acc),
                              drew: !!res.drew,
                              // 🔴 **`same` 和 `here` 必须原样带回去。**
                              //   2026-09-26 补上这两个 —— 在这一行之前它们是**算了
                              //   却没发**的：下面 `go:`/`rest_stop` 那一段算出了
                              //   `same`（就在这一页上，没跳），`rest_stop` 还算出
                              //   `here`（已经站在导航页上，就地查），可这个白名单
                              //   式的 `send` 里没有它们，于是服务端永远收不到。
                              //   后果不是报错，是**话和屏幕不一致**：主人站在
                              //   `detail.html` 上说「打开驾驶监测」，屏上什么都没
                              //   发生，小瑞却说「好，主人，这就打开驾驶监测」。
                              //   ——`SCRIPT["go_same"]` / `["rest_stop_here"]` 那两张
                              //   表就是为这一档写的，原来一次都没被用上。
                              // ⚠️ 增删字段时**两边一起看**：服务端读它们的地方在
                              //   `xiaorui.py` 的 `_go_reply` / `act_reply`。
                              same: !!res.same, here: !!res.here });
        }
      };
      if (id === 'music') {
        if (!window.XQP || !XQP.playCalm) { back({ ok: false, why: 'no_player' }); return; }
        let p;
        try { p = XQP.playCalm(); } catch (e) { back({ ok: false, why: 'throw' }); return; }
        // ⚠️ `playCalm()` 返回的是 **Promise**，失败原因在 resolve 出来的对象里
        //    （`{ok, why, file, title, measured}`，见 player.js:369-399），
        //    所以只能 `.then` 之后回执 —— 同步地 back() 会把"点下去的那一刻"
        //    当成结果，而那一刻谁也不知道放不放得成。
        Promise.resolve(p).then((r) => {
          r = r || {};
          back({ ok: !!r.ok, why: r.why || '', file: r.file || '', title: r.title || '' });
        }).catch(() => back({ ok: false, why: 'throw' }));
        return;
      }
      if (id === 'nearby') {
        // ★ 2026-09-25：问「最近有服务区吗」时服务端要的是**坐标** —— 定位只有
        //   浏览器知道，所以第一步由这一张页面给（见 `XQ.geo` 文件头）。
        //   有地图的页面（只有 nav.html）顺手把车/服务区/路线画出来，并回 `drew`；
        //   服务端拿它决定 severe 那档能不能说「路线我已经准备好了」。
        // ⚠️ `drew` **必须是"真画成了"**：只算不画的时候说完成时，用户抬头看屏幕
        //   会发现屏上什么也没有 —— 那是另一次"话和事不一致"。
        const bg = window.XQ && XQ.geo;
        if (!bg) { back({ ok: false, why: 'no_geo' }); return; }
        bg.ask().then((p) => {
          if (!p || p.lat == null) {
            /* ⚠️ 定位拿不到时**先看这一页上有没有已经定好的起点**（人在下拉里选的 /
               在地图上点的地方）—— 有就照用，没有才回 no_geo。
               ★ 用户拍板的顺序就是「先试自动定位，拿不到再手动」，这一条把那句话
                 接到了语音这条路上：屏上明明标着「起点（手动）」，却回一句
                 "定位没打开"，那是**话和屏不一致**。
               ⚠️ 兜底来的坐标一律 `manual:true` —— 它不是定位算出来的，
                  地图上必须标成「起点（手动）」，不能标成「我的位置」。 */
            const cur = (window.XQ.nav && XQ.nav.originNow)
              ? XQ.nav.originNow() : null;
            if (cur && cur.lat != null) {
              const draw2 = (window.XQ.nav && XQ.nav.doNearby);
              const pt = { lat: cur.lat, lng: cur.lng, manual: true };
              if (!draw2) {
                back({ ok: true, lat: pt.lat, lng: pt.lng, manual: true });
                return;
              }
              Promise.resolve(XQ.nav.doNearby(pt)).then((drew) => {
                back({ ok: true, lat: pt.lat, lng: pt.lng, manual: true,
                       drew: !!drew });
              }).catch(() => {
                back({ ok: true, lat: pt.lat, lng: pt.lng, manual: true,
                       drew: false });
              });
              return;
            }
            back({ ok: false, why: (p && p.why) || 'no_geo' });
            return;
          }
          const draw = (window.XQ.nav && XQ.nav.doNearby);
          if (!draw) { back({ ok: true, lat: p.lat, lng: p.lng, acc: p.acc }); return; }
          Promise.resolve(XQ.nav.doNearby(p)).then((drew) => {
            back({ ok: true, lat: p.lat, lng: p.lng, acc: p.acc, drew: !!drew });
          }).catch(() => {
            back({ ok: true, lat: p.lat, lng: p.lng, acc: p.acc, drew: false });
          });
        }).catch(() => back({ ok: false, why: 'no_geo' }));
        return;
      }
      if (id === 'rest_stop' || id.indexOf('go:') === 0) {
        // ★★ 2026-09-26：**打开某一页**（`go:<键>`）和**导航过去**（`rest_stop`）。
        //   用户原话：「我让它导航它肯定真导航啊 直接跳转这些啊 我让它干嘛肯定干嘛」。
        //   这两个 id 由服务端的 `xiaorui.detect_action` 判出来（见那个函数）。
        //
        // ⚠️ **必须先回执、再跳，中间还得留一小段**（`JUMP_MS`）：回执走的是
        //    WebSocket，而 `location.href` 一赋上值这一页立刻开始拆 —— 同步跳的话
        //    那一帧十有八九还没发出去。服务端于是只等到 1.5 s 超时、说一句"没收到
        //    回执"，**而这一页其实已经跳过去了**。两边看起来都做对了，是最难查的
        //    那种"话和事不一致"。180 ms 是本地回环的量级，够发一帧、人感觉不到。
        //
        // ⚠️ 回执的 `ok` 只表示"这一页**答应了**这个动作"，**不表示做完了** ——
        //    页面一跳连接就断，服务端再也验不到结果。所以小瑞说的是「这就打开」，
        //    不是完成时（见 `xiaorui.py` 的 `act_reply`，那里写明了为什么这一档
        //    不能照 `music` 抄）。
        const JUMP_MS = 180;
        const key = (id === 'rest_stop') ? 'navi' : id.slice(3);
        const target = navTarget(key);
        if (!target) { back({ ok: false, why: 'no_target' }); return; }
        if (samePage(target)) {
          if (id === 'rest_stop') {
            // 主人**已经站在导航页上**：`location.href` 给同一个地址 = 整页重载，
            // 而重载会把已经画好的路线、选好的起点全丢掉 —— 所以就地查一次。
            const o = (window.XQ.nav && XQ.nav.originNow) ? XQ.nav.originNow() : null;
            if (o && o.lat != null && XQ.nav.doNearby) {
              back({ ok: true, here: true });
              /* ★★ 2026-09-26：第二个参数 `true` = **顺便真的进逐段引导**。
                 主人说的是「导航」不是「问一下」，所以他应了「要」之后屏上必须
                 真的是在导航（见 `nav.html` 的 `doNearby`）。 */
              try { XQ.nav.doNearby({ lat: o.lat, lng: o.lng, manual: true }, true); }
              catch (e) { /* 回执已经发了：这一页查不成，屏上自己会说为什么 */ }
              return;
            }
            // 这一页上还没有起点（定位没打开、也没人选过）—— 就地查不了，往下走
            // 整页重载那一趟：带着 `?ask=rest_stop` 进来，会走"先试定位、拿不到
            // 就让人手动选起点"的路，定完起点再问那一句。这一档**不报 `here`**
            // （页面确实在重新进）。
          } else {
            // 就在这一页上，不跳（跳了是白重载一次）。服务端据此换一句话说
            // （`SCRIPT["go_same"]`：不能还说"这就打开"，那和屏幕不一致）。
            back({ ok: true, same: true });
            return;
          }
        }
        back({ ok: true });
        /* ★★ 2026-09-26：`rest_stop` 那一趟带的是 **`?ask=rest_stop`**，不再是
           `?do=nearby`。
           🔴 为什么改：`?do=nearby` 是"跳过去**什么都不问**、直接查最近的服务区并
              进导航"。而用户拍板的是「跳过去 + 问一句」—— 先跳、再问
              「要不要我导到最近的服务区？」，主人应一声「要」才真去查。
              两个都带的话，页面已经在导航了，那句问话就成了多余的。
           ⚠️ 这一趟**没有把 `rest_stop` 那件事做完**：真正的查询要等主人说「要」
              —— 服务端那时会发 `ev:"do" id:"rest_stop"` 回来，而这一页**此刻就
              站在导航页上**、起点也定好了，于是走上面 `samePage` 的 `here:true`
              那一支就地查（`SCRIPT["rest_stop_here"]`）。
           ⚠️ `go:<键>` 那一趟照旧不带参数（打开就完了，没有什么可问的）。 */
        const url = (id === 'rest_stop') ? target + '?ask=' + id : target;
        setTimeout(() => { location.href = url; }, JUMP_MS);
        return;
      }
      back({ ok: false, why: 'unknown_action' });
      return;
    }
    if (ev === 'reply') {
      XQ.wake.reply = d.text || '';
      XQ.wake.busy = false;
      /* ★★ 2026-09-26：把这一轮的**轮次号**记下来，念完原样带回去（见 `round`
         那一格和 server.py `voice_spoken` 的两道卫兵）。⚠️ 缺了就当没带 ——
         **不编一个数**：编出来的数会让服务端把一条上一轮的回执**当真**。 */
      XQ.wake.round = (d.round == null) ? 0 : d.round;
      XQ.wake._render();
      // 见第 3 条：**先发 done 再说话**。`XQ.speak` 因为任何原因不出声（开关关着、
      // 页面在后台、浏览器不支持），服务端也得知道"该回 IDLE 了"，否则永远卡住。
      //
      // ⚠️ 但**不能只靠这一条**：`XQ.speak` 走服务端兜底那条路时（浏览器念不出来，
      // 交给服务端念）它会返回 true，而服务端那条路只能报"排上队了"、报不出
      // "念完了"（见 ui/tts.py 的 `say()`）—— 于是 `done` **永远不会触发**。
      // 所以服务端那边还有一道**看门狗**（`server.py` 的 `_voice_watchdog`），
      // 到点自己收尾并回一条 `idle`，原因写在 `why` 里。这边如实显示出来。
      // 两处都到也没关系：`answer_done()` 重复调没有副作用。
      /* ★★ 2026-09-26：回执**带上轮次号**（服务端 `voice_spoken` 的卫兵①）。
         ⚠️ 掐断（`XQ.tts.halt`）也走这条 `done` 吗？—— **不走**，那一推 `_seq`
            让 `onend` 里的 `token === _seq` 不成立，所以被掐断的那一句不会回执。
            这是**两道**防线里的第一道，第二道在服务端（轮次 + 状态）。 */
      const done = () => {
        if (XQ.wake.link && XQ.wake.link.online) {
          XQ.wake.link.send({ type: 'voice_spoken', round: XQ.wake.round });
        }
      };
      let spoke = false;
      try { spoke = XQ.speak(XQ.wake.reply, { emotion: d.emotion || 'normal', done }); } catch (e) { spoke = false; }
      if (!spoke) done();
      return;
    }
    if (ev === 'idle') {
      XQ.wake.partial = '';
      XQ.wake.busy = false;
      XQ.wake.follow = 0;          // 追问窗口关了（也可以是超时自己关的）
      XQ.wake._render();
      // ⚠️ `why` 里的原话照说，别一律翻成"没听清"：它可能是"识别模型不可用"、
      //    "念完了没等到回执"，也可能是"没听清" —— 这三件事要修的地方完全不同。
      if (d.why) XQ.flash(d.why);
      return;
    }
    if (ev === 'gone') {
      XQ.wake.lost += 1;
      // 见第 5 条：丢片/出错**要说出来**。`why` 是服务端给的原因，原样留着。
      XQ.wake.goneWhy = d.why || XQ.wake.goneWhy;
      XQ.wake._render();
      if (d.why) XQ.flash('音频有问题：' + d.why);
    }
  },

  /** 唤醒提示音。用 WebAudio 现场合成 —— 不为一声"叮"多加一个音频文件。 */
  _chime() {
    try {
      const ctx = XQ.wake._ctx || new (window.AudioContext || window.webkitAudioContext)();
      const t0 = ctx.currentTime;
      [880, 1174.7].forEach((f, i) => {          // A5 → D6，往上走，听着"被叫醒了"
        const o = ctx.createOscillator(), g = ctx.createGain();
        o.type = 'sine'; o.frequency.value = f;
        const s = t0 + i * 0.11;
        g.gain.setValueAtTime(0.0001, s);
        g.gain.exponentialRampToValueAtTime(0.18, s + 0.02);   // 别太响，车里吓人
        g.gain.exponentialRampToValueAtTime(0.0001, s + 0.16);
        o.connect(g); g.connect(ctx.destination);
        o.start(s); o.stop(s + 0.18);
      });
      if (!XQ.wake._ctx) { setTimeout(() => { try { ctx.close(); } catch (e) {} }, 600); }
    } catch (e) {}
  },

  /* ---------------------------------------------------------------- 画 */
  _render() {
    const b = XQ.wake._btn;
    if (b) {
      const on = XQ.wake.state === 'listening' || XQ.wake.state === 'starting';
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
      const lbl = b.querySelector('.wk-label');
      if (lbl) lbl.textContent = on ? '停' : '听';
      b.classList.toggle('on', on);
      b.title = on ? '点一下让小瑞别听了' : '点一下让小瑞开始听（说「你好，小瑞」）';
    }
    const h = XQ.wake._host;
    if (!h) return;
    const st = XQ.wake.state;
    /* 状态行的优先级：出错 > 起麦 > **正在转文字/等答复** > 在听 > 没在听。
       ⚠️ `busy` 那一档不能省：转文字 + 问模型加起来可能好几秒，这段时间界面
       一动不动的话，演示的人会以为坏了然后再说一遍（于是变成两轮对话）。 */
    /* ⚠️ 'starting' 那一档**要能把 `why` 显出来**（见文首第 7 条）：权限框没人点
       的时候状态仍然是 'starting'，唯一能说出"它在等什么"的地方就是这一行；
       写死成「正在起麦克风…」的话，那 8 秒之后说的那句话就白说了。 */
    const line = st === 'error' ? ('起不来：' + XQ.wake.why)
      : st === 'starting' ? (XQ.wake.why || '正在起麦克风…')
        : XQ.wake.busy ? '听到了，正在想…'
          : st === 'listening'
            ? (XQ.wake.partial ? '在听…「' + XQ.wake.partial + '」'
              : (XQ.wake.follow ? '在听 —— 接着说' : '在听 —— 说「你好，小瑞」'))
            : (XQ.wake.reply ? '（不听了，刚才说：' + XQ.wake.reply + '）' : '没在听');
    // ⚠️ 用 textContent 拼，不用 innerHTML —— 识别出来的文本是**外部内容**，
    //    拼进 innerHTML 就是把麦克风里听到的东西当代码执行。
    h.textContent = line;
    h.className = 'wk-host ' + st;
    const detail = h.parentElement && h.parentElement.querySelector('.wk-detail');
    if (detail) {
      const bits = [];
      if (XQ.wake.lastHeard) bits.push('听到：' + XQ.wake.lastHeard);
      if (XQ.wake.sent) bits.push(XQ.wake.sent + ' 片音频');
      if (XQ.wake.lost) bits.push('⚠️ 丢了 ' + XQ.wake.lost + ' 片'
        + (XQ.wake.goneWhy ? '（' + XQ.wake.goneWhy + '）' : ''));
      const eng = XQ.wake.engine || {};
      if (eng.kws) bits.push(eng.kws);
      if (eng.asr) bits.push(eng.asr);
      else if (eng.note) bits.push(eng.note);
      detail.textContent = bits.join(' · ');
    }
  },
};
