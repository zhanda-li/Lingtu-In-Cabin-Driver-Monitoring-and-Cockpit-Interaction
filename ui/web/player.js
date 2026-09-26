/* =========================================================================
   player.js —— 跨页播放：走出多媒体页，歌不断（2026-09-25 晚）
   -------------------------------------------------------------------------
   用户原话：「还有就是退出多媒体页面后 我就听不到歌了 我要听的啊」。

   **为什么需要一个新文件**：座舱每一页都是**独立文档**，点一下左栏、`<a href>`
   一走，上一个文档连同它里面那个 `<audio>` 一起销毁 —— 这是浏览器换页的物理
   事实，不是代码写错。全站唯一能"跨页活下来"的存储是 `sessionStorage`
   （同一个标签页里换页还在、新标签页是空的），所以做法只有一条：
   **每换一页，在新文档里把歌重新举起来，位置从存的那一秒接着走。**

   ⚠️ **不许说成"无缝"。** 新文档要重新拿文件、重新解码、重新起播，中间有
      几百毫秒的静音，位置最差会差 1 秒（存档是按秒节流的，见 `push()`）。
      这是这套做法的代价，写在注释里，也写在验收脚本里（它量的是"接得上"，
      不是"听不出缝"）。真要零缝只有把座舱改成单页外壳（iframe/SPA），
      那要动 11 张页面的结构，答辩前不做。

   ---------------------------------------------------------------- 谁在做什么
     多媒体页：自己有播放器，调用 `XQP.bind(au, ...)` 把这一层**接管**过去 ——
               位置/音量/在放哪一首按秒写进存档。它**不画悬浮条**（那一页自己
               就是一整个播放器），只在开局用 `XQP.resume()` 把上次那一秒接回来。
     别的页面：`DOMContentLoaded` 时发现"存着东西、而且我没被 bind"，就自己建一个
               `<audio>` 接着放，并在左下角画一条悬浮条（播放/暂停 + 下一首 + 歌名）。
     从没开过多媒体页的页面：存档是空的 → 开局**什么都不做、什么都不画**；
               ★ 2026-09-25 晚补：但**点播**（下面那节）会当场把它建出来 ——
               存档的"有没有"决定的是"开局要不要自己响"，不是"这一层能不能用"。

   ---------------------------------------------------------------- 从别的页面点播
   ★★ 2026-09-25 晚新加。用户原话：「还有个问题 为啥我在驾驶监测部分点舒缓音乐
   只有本地固定话术而没有真正地去放音乐」。

   **根因**（三层，少一条都不是这个症状）：
     ① 那几颗 chip / 按钮只发了一条 `{type:'action', id:'music'}`，服务端拿它做的
        只有一件事：挑一句 `xiaorui.SCRIPT['music'][档位]` 播回所有页面 —— 那个分支里
        `actions` 是**空数组**，`action_done:'music'` 广播出去**一个消费者都没有**。
     ② 全站唯一真正出声的 `<audio>` 住在 media.html 里（`const au = new Audio()`）。
        别的页面根本没有播放器，所以"放音乐"这件事在别的页面上**从来没实现过**。
     ③ 这一层原来只有"接着放上次那一首"（`mount()`）和"下一首"（`step()`）两个入口，
        **没有"点一首新的"**。
   于是用户看到的就是只剩那句固定话术 + 屏幕上一句「已执行：…」。

   **做法**：把"挑一首舒缓的"从 media.html **原样搬进这一层**（量出来的那张表就在
   localStorage 里，键一样、算法一样），再给它一个"从这一层开始放"的入口 `playCalm()`。
   别的页面点了就是：拉曲库 → 用手上那张表挑 → 建/复用左下角那条 → 真的 `play()`。
   ⚠️ **只搬"挑"，不搬"量"**：量一轮要 30 首各自 fetch + `OfflineAudioContext` 解码，
      只有多媒体页做（它自己那一套 `calmScan`/`calmMeasure` 一行没动）。这一层只读
      结果；读不到（还没量过 / 换了台机器）就**如实说**，然后放内置那批的第一首。
   ⚠️ **多媒体页上那一颗不归这里管**：它有自己那个真播放器、自己那套 chip，
      `playCalm()` 见 `native` 直接让路。**但挑法是共用的**（`XQP.pickCalmIdx`），
      所以两个入口摇的是同一张表、同一个池子、同一份"刚推过谁"的账。
   ⚠️ 搬过来之后 `media.html` 里那三个函数变成一行调用 —— **别在那边再留一份**：
      两份迟早会漂，而"同一档位推两首不同的歌"这种事（用户实测报过）恰恰是
      两份算法各算各的才有的。

   ---------------------------------------------------------------- 两个存储别搞混
     `xq.media.play`（本文件，**sessionStorage**）：这一趟别断，按标签页隔离。
     `xq.media.last`（media.html 自己，localStorage）：下次打开还给你留着。
   ⚠️ 为什么不用 localStorage 装这套：它是**整个浏览器**共用的。开第二个标签页
      时两个标签会同时放同一首歌、差半秒，听出来是回声；sessionStorage 按标签页
      隔离，新标签页干干净净，同一标签页内换页才接上 —— 正好是我们要的语义。

   ---------------------------------------------------------------- 装在哪
   9 张座舱页各加一行 `<script src="/static/player.js"></script>`（在 live.js 之后）。
   ⚠️ **cover.html（展示封面）和 design.html（设计稿）故意不装** —— 那两张不是
      座舱里开着车的界面，左下角挂一条播放条是错的。所以是"逐页显式装"，
      不是从 chrome.js 里自动注入：自动注入会顺手糊上去，而那两张页需要"没有"。
      哪天要改这个名单，改的是各页的 `<script>`，别改成自动的。
   ⚠️ 它依赖 `XQ.icon()` / `XQ.ICON` / `XQ.flash()`（live.js 提供）和主题变量
      （`--panel-4` / `--accent` / `--rgb` / `--ink` / `--fs-sm`，style.css 提供）。
      都是**已经在那儿**的东西，这里不新造颜色、新造字号。
   ========================================================================= */
(function () {
  'use strict';

  /* ⚠️ 全套包在 IIFE 里，只把 `XQP` 挂出去。外墙那几个文件（chrome.js / live.js）
     都是**普通脚本**，顶层 const 落在同一个全局词法作用域里、重名就
     `SyntaxError` 整页白屏 —— 它们为此一律用 `var`。这里没有那个约束（IIFE 有
     自己的作用域），所以内部照常用 const，但**对外只占一个名字**。 */
  const KEY = 'xq.media.play';
  /* 存档超过这么久就当没有。浏览器一个标签页可以开一整天，昨天下午那首放到
     一半的歌，今天早上打开这一页不该自己响起来 —— 那不是"接着听"，是吓人。 */
  const FRESH = 6 * 3600 * 1000;
  const DEFAULT_VOL = 0.8;      // 和 media.html 那个 `#vol` 的初始值一致

  const XQP = {};
  let native = null;            // 多媒体页那个真播放器（`bind` 进来的）
  let metaOf = null;            // 多媒体页给的"当前这首是什么"（它自己知道）
  let local = null;             // 别的页面自己造的那个 audio
  let bar = null, ppBtn = null, nxBtn = null, nameEl = null, subEl = null, progEl = null;
  let blocked = false;          // 浏览器不让自动放（要用户点一下）
  let wroteAt = 0;              // 上次写存档的时刻（节流用）

  const num = (v, d) => (typeof v === 'number' && isFinite(v) ? v : d);

  function load() {
    try {
      const raw = sessionStorage.getItem(KEY);
      if (!raw) return null;
      const o = JSON.parse(raw);
      if (!o || !o.file) return null;
      if (Date.now() - num(o.t, 0) > FRESH) return null;
      return o;
    } catch (e) {
      /* 无痕 / kiosk 里某些策略会直接把 sessionStorage 抛掉。**当作没有**，
         不放也不炸 —— 少了这条，整页会因为一行存档读不出来而白屏。 */
      return null;
    }
  }

  function save(o) {
    try { sessionStorage.setItem(KEY, JSON.stringify(o)); } catch (e) { /* 存不住就算了 */ }
  }

  /* 和 media.html 里那个 `fileUrl()` 是同一个拼法。**故意抄一份**：这一层要能
     独立在别的页面跑起来（那边没有 media.html 的任何函数），为一行字符串去
     `window.XQ.mediaXXX` 拉一条反向依赖，比抄一行更难懂。 */
  const srcOf = (file) => '/music/' + encodeURIComponent(file);

  const fmt = (s) => {
    s = Math.max(0, Math.floor(num(s, 0)));
    const m = Math.floor(s / 60);
    return m + ':' + String(s % 60).padStart(2, '0');
  };

  /* 当前在放的那一首是谁。多媒体页问它自己（`TRACKS[idx]`，权威）；别的页面
     只能信存档 —— 这也是为什么"当前是哪一首"**不用拉 /music.json**。
     ⚠️ 2026-09-25 补：**"下一首是哪一首"要拉**（★ 见下面 `tracks()` 那段）。
        两件事不一样：一个是"我在哪儿"，存档里有；一个是"我后面是谁"，
        只有曲库那张表知道。别因为下面加了 `tracks()` 就把这条注释当成过期的删掉。
     ⚠️ 别把它写成"没有 `metaOf` 就返回空"。第一版就是那样，后果很隐蔽：
     `snapshot()` 见 `file` 是空的**直接返回 null** → `push()` 就什么都不写 →
     **在别的页面上存档一直停在离开多媒体页那一刻**。用户听到的是：在设置页听了
     十分钟、回多媒体页，歌跳回十分钟前那一段；在设置页按了暂停、回去又是响的。
     所以这里必须有那条**从存档回读**的路。 */
  function meta() {
    if (metaOf) { const m = metaOf(); if (m && m.file) return m; }
    const st = load();
    if (st && st.file) {
      return { file: st.file, title: st.title || '', artist: st.artist || '' };
    }
    return { file: null, title: '', artist: '' };
  }

  /* 抽一份存档。**从正在放的那个 audio 现抽**，不靠调用方传 —— 少一个能对不上的
     参数：位置、音量、在不在放，三样都只有元素自己知道。 */
  function snapshot() {
    const a = native || local;
    if (!a || !a.src) return null;
    const m = meta();
    if (!m.file) return null;
    return {
      file: m.file, title: m.title || '', artist: m.artist || '',
      pos: num(a.currentTime, 0),
      dur: num(a.duration, 0),
      vol: num(a.volume, DEFAULT_VOL),
      playing: !a.paused,
      t: Date.now(),
    };
  }

  function push(force) {
    const o = snapshot();
    if (!o) return;
    const now = Date.now();
    /* `timeupdate` 每秒来 4~5 次，每次都写一遍 sessionStorage 是白费的写盘 ——
       按秒节流。**换页/暂停/拖进度走 force**：那几下是"最后一次机会"，
       省掉就丢位置。 */
    if (!force && now - wroteAt < 1000) return;
    wroteAt = now;
    save(o);
  }

  /* ---------------------------------------------------------------- 多媒体页 */
  /* 把这一层接管到页面那个**真播放器**上。不画条、不建 audio、不改它的行为。 */
  XQP.bind = function (a, m) {
    native = a;
    metaOf = m || null;
    /* 前四个是"状态变了"，必须当场写；`timeupdate` 是"在走"，按秒写。 */
    ['play', 'pause', 'seeked', 'loadedmetadata', 'volumechange'].forEach((ev) => {
      a.addEventListener(ev, () => push(true));
    });
    a.addEventListener('timeupdate', () => push(false));
    /* ⚠️ **换页时最后能写字的机会**就是 `pagehide`：`unload` 在移动端和 bfcache
       下常常不触发，而 `beforeunload` 会把页面挡在 bfcache 外面（代价更大）。
       `visibilitychange → hidden` 再补一道：切到后台/锁屏也把位置落下来。 */
    window.addEventListener('pagehide', () => push(true));
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') push(true);
    });
  };

  /* 多媒体页开局问一句"上次听到哪儿了"（它自己决定怎么接）。 */
  XQP.resume = function () { return load(); };

  /* ---------------------------------------------------------------- 曲库（别的页面）
     ★★ 2026-09-25 新加。用户原话：「你给我左下角设计的那个音乐那个 右边应该有
     下一首的按键 **而不是播完就暂停了 并且应该自动播下一首**」。
     做这两件事都必须知道**整个曲库的顺序**，而这个顺序只有 `/music.json` 有 ——
     存档里只记着"现在这一首是谁"（见上面 `meta()` 的注释）。
     所以这一层**破例拉一次曲库**：原来"别的页面不拉 /music.json"是当年的设计取舍，
     换来的代价就是放完一首只能停在原地；现在用户明确要"自动下一首"，
     那个取舍就反过来了。
     ⚠️ 只在**需要的时候**拉：`mount()` 里调一次（也就是"条要画出来了"的时候）。
         没有存档、不画条的页面（从来没开过多媒体页）一个字节都不拉。
     ⚠️ 拉不到（`file://` 直接打开、服务端挂了）**要退回旧行为**：那一首放完
         停在原地、留一个 ▶，按钮置灰。**不假装**下一首 —— 这条别删。 */
  let listP = null;
  let listLen = 0;
  /* ★ 2026-09-25 晚：**未经过滤的那一份**和 JSON 根上的 `bundled` 也留着 ——
     "舒缓"那张表的指纹是拿它们算的（`calmPrint`），而指纹必须和多媒体页
     算出来的**一模一样**，所以这边不能拿 `filter()` 之后的那份去算。 */
  let listRaw = null, listBundled = 0;

  function tracks() {
    if (!listP) {
      listP = fetch('/music.json', { cache: 'no-store' })
        .then((r) => r.json())
        .then((j) => {
          const all = (j && Array.isArray(j.tracks)) ? j.tracks : [];
          listRaw = all;
          listBundled = num(j && j.bundled, 0);
          const a = all.filter((t) => t && t.file);
          listLen = a.length;
          return a;
        })
        .catch(() => { listLen = 0; listRaw = null; return []; });   // 安静退回，不打印
    }
    return listP;
  }

  /* 上一首 / 下一首。`dir = +1` 下一首、`-1` 上一首。
     返回"到底换没换" —— 放完那一首时要用它决定要不要退回旧行为。
     ⚠️ 找不到当前这首（存档里那首已经不在曲库里了）就**从头上开始**，不是不动：
        这是"曲库变了"的正常情况，不动会变成一个按了没反应的按钮。 */
  async function step(dir) {
    const list = await tracks();
    if (!list.length) return false;
    const cur = meta().file;
    let i = list.findIndex((t) => t.file === cur);
    i = i < 0 ? (dir > 0 ? 0 : list.length - 1)
              : (i + dir + list.length) % list.length;
    playFile(list[i]);
    return true;
  }

  /* 换到某一首：位置归零、马上起播，并**立刻写进存档**。
     ⚠️ `save()` 必须在 `play()` **之前**：`play()` 会同步触发 `play` 事件，
        那条路上会 `push()` 一次（读的是 `meta()`，而它读的正是存档）——
        存档要是还没换过来，那一笔写的就还是上一首。
     ⚠️ 这一层没有时长、没有波形（那两样是多媒体页自己的活），所以 `dur` 先写 0；
        元素自己拿到元数据之后 `loadedmetadata` 会补一次。
     ★ 2026-09-25 晚：**返回"到底放起来了没有"**（`playCalm` 要拿它说真话）。
        `.catch` 在里面，所以这个 promise **只会 resolve、不会 reject**：
        `step()`/`ended` 那两条路照旧不看返回值，不会因此多出一条 unhandled
        rejection（本项目控制台零报错的老规矩）。 */
  function playFile(t) {
    local.src = srcOf(t.file);
    try { local.currentTime = 0; } catch (e) { /* 还没元数据，本来就是 0 */ }
    const name = t.title || String(t.file).replace(/\.[^.]+$/, '');
    nameEl.textContent = name;
    nameEl.title = name;
    save({ file: t.file, title: t.title || '', artist: t.artist || '',
           pos: 0, dur: 0, vol: local.volume, playing: true, t: Date.now() });
    return local.play().then(() => { blocked = false; paint(); return true; })
                       .catch(() => { blocked = true; paint(); return false; });
  }

  /* ================================================================ 点播
     ★★ 2026-09-25 晚。这一节的来龙去脉（用户原话、三层根因、为什么只搬"挑"
     不搬"量"）写在文件头上，这里只留"怎么用"。
     ⚠️ 这一节里**一个 `local`/`nameEl` 都不许直接用** —— 那些是"别的页面那条
        悬浮条"的东西，点播要先把它们建出来（`buildAudio()`），顺序错了就是
        `null.textContent` 当场打断整个点击回调，表现是"点了没反应"。 */
  const CALM_KEY = 'xq.media.calm.v2';    // 和 media.html 同一个键（改算法要一起换版本号）
  XQP.CALM_KEY = CALM_KEY;                // media.html 写这张表时读它，**不许另抄一份字符串**
  const CALM_AVOID = 2, CALM_POOL_MIN = 3, CALM_POOL_MAX = 10;
  let calmAsked = [];      // 这一页刚点播过的（文件名，新的在前），供 pick 避开

  const say = (t) => { if (XQ.flash) XQ.flash(t); };

  /* 曲库指纹：首数 + 内置数 + 文件名清单。**和 media.html 那版逐字等价** ——
     两边算出来必须是同一个数，不然一边扫出来的表另一边读不出来。
     🔴 原版第一句是 `let h = TRACKS.length + ':' + 内置数;`，那是个**真 bug**：
        JS 把 "155:30" 当数字转是 NaN（冒号不是小数点），`h*31` 一步就成 NaN，
        整个函数返回 NaN；`JSON.stringify({print:NaN})` 落到 localStorage 里是
        `"print":null`，读回来 `null === NaN` 恒假 → **指纹从来没对上过，
        每打开一次多媒体页都要重新量那 30 首**（几十秒的解码一直在和正在放的
        那首歌抢磁盘——正是那一节注释想避免的事）。
        量出来的证据：`_probe_calmprint.py` 读 localStorage 那份 `print`，
        改之前是 `null`、改之后是一个数。 */
  XQP.calmPrint = function (list, bundled) {
    let h = (list ? list.length : 0) * 1e6 + num(bundled, 0);
    for (let i = 0; list && i < list.length; i++) {
      const f = list[i].file || '';
      for (let j = 0; j < f.length; j++) h = (h * 31 + f.charCodeAt(j)) % 1e9;
    }
    return h;
  };

  /* 读多媒体页量出来的那张表（`{文件名: {bpm,rms,dyn}}`）。指纹对不上 / 还没量过
     → null —— **不猜**，猜出来的"舒缓"就是骗人。 */
  XQP.calmItems = function (print) {
    try {
      const raw = localStorage.getItem(CALM_KEY);
      if (!raw) return null;
      const o = JSON.parse(raw);
      return (o && o.print === print && o.items && Object.keys(o.items).length)
        ? o.items : null;
    } catch (e) {
      return null;      // file:// 下 localStorage 可能直接抛，见 media.html 那几处
    }
  };

  /* 从量出来的那批里摇一首，返回**`list` 里的下标**（-1 = 还没得挑）。
     算法、池子大小、避开谁，全部和 media.html 原版一致（理由写在那边的注释里：
     在最舒缓的那一档里摇，避开正在放的 + 刚推过的两首 —— 用户实测报过
     "两档疲劳推同一首"）。
     ⚠️ 参数用 `list` + `items` 而不是直接读 media.html 的全局：这一层要在
        **没有 media.html 的页面**上跑（那边 `TRACKS` 根本不存在）。 */
  XQP.pickCalmIdx = function (list, items, curFile, recent) {
    if (!items || !list || !list.length) return -1;
    const rows = [];
    for (let i = 0; i < list.length; i++) {
      const m = items[list[i].file];
      if (m && m.bpm > 0) rows.push({ i: i, m: m });
    }
    if (!rows.length) return -1;
    const norm = (key) => {
      const vs = rows.map((r) => r.m[key]);
      const lo = Math.min.apply(null, vs), hi = Math.max.apply(null, vs);
      return (r) => (hi > lo ? (r.m[key] - lo) / (hi - lo) : 0);
    };
    const B = norm('bpm'), R = norm('rms'), D = norm('dyn');
    rows.forEach((r) => {
      r.score = 0.6 * (1 - B(r)) + 0.25 * R(r) + 0.15 * D(r);   // bpm 越低越好，所以 1 减
    });
    rows.sort((a, b) => b.score - a.score);
    const k = Math.max(CALM_POOL_MIN,
                       Math.min(CALM_POOL_MAX, Math.ceil(rows.length / 3)));
    const pool = rows.slice(0, Math.min(k, rows.length)).map((r) => r.i);
    const rec = recent || [];
    let cand = pool.filter((i) => list[i].file !== curFile && rec.indexOf(list[i].file) < 0);
    if (!cand.length) cand = pool.filter((i) => list[i].file !== rec[0]);
    if (!cand.length) cand = pool;
    return cand[Math.floor(Math.random() * cand.length)];
  };

  /* 记一笔"刚点播过这首"，供 pick 避开。`file` 是文件名（**不是下标**）——
     这一层的下标在多媒体页那份 `TRACKS` 上根本对不上。 */
  XQP.calmNote = function (file) {
    if (!file) return;
    calmAsked = [file].concat(calmAsked.filter((f) => f !== file)).slice(0, CALM_AVOID);
  };
  XQP.calmRecent = function () { return calmAsked.slice(); };

  /* 内置那批里的第一首。`items` 读不到时用它兜底。
     ⚠️ 只在 `src === '内置'` 里找（`file` 一定跟项目走），找不到才退回"列表第一首
        —— 和"推荐一首放不出来的歌"是同一个理由（演示机上未必有用户的音乐目录）。 */
  function firstBuiltin(list) {
    for (let i = 0; i < list.length; i++) if (list[i].src === '内置') return i;
    for (let i = 0; i < list.length; i++) if (list[i].file) return i;
    return -1;
  }

  /* 点一首舒缓的，**当场就放**（留在当前页面，见文件头上用户选的那条路）。
     返回 `{ok, why, file, title, measured}` —— 给调用方和检查脚本读的就是这个。
     ⚠️ 三种"没放成"各有各的话，**不许合并成一句**：曲库没读到 vs 没量过（降级放了
        另一首）vs 浏览器不让自动放。用户看到的是哪一句，就是他遇上的是哪件事。 */
  XQP.playCalm = function () {
    if (native) return Promise.resolve({ ok: false, why: 'native' });
    return tracks().then(function () {
      const list = listRaw || [];
      if (!list.length) {
        say('曲库还没读出来 —— 稍等一下再点一次');
        return { ok: false, why: 'nolib' };
      }
      const items = XQP.calmItems(XQP.calmPrint(list, listBundled));
      let i = XQP.pickCalmIdx(list, items, meta().file, calmAsked);
      const measured = i >= 0;
      if (!measured) i = firstBuiltin(list);     // 降级：内置那批的第一首
      if (i < 0) {
        say('曲库里没有能放的文件');
        return { ok: false, why: 'nofile' };
      }
      const t = list[i];
      buildAudio();
      return playFile(t).then(function (ok) {
        if (!ok) {
          /* 被挡了就**别装作在放**：条上会留一个 ▶（`paint()` 里那套），
             这里再说一句点到哪儿。第一次点这一下本身就是用户手势，
             所以正常情况不会走到这儿（只有连点/无手势时才可能）。 */
          say('浏览器不让自动放 —— 点左下角那个播放键');
          return { ok: false, why: 'blocked', file: t.file, title: t.title };
        }
        XQP.calmNote(t.file);
        say(measured ? '正在放《' + (t.title || t.file) + '》—— 内置那批里量出来舒缓的'
                     : '先放一首《' + (t.title || t.file) + '》—— 舒缓那几首还没量过，'
                       + '去多媒体页放一会儿我就量好了');
        return { ok: true, why: '', file: t.file, title: t.title, measured: measured };
      });
    });
  };

  /* ---------------------------------------------------------------- 别的页面 */
  function paint() {
    if (!bar || !local) return;
    const paused = local.paused;
    ppBtn.innerHTML = XQ.icon(paused ? 'play' : 'pause');
    /* ★ 下一首那个键：曲库没读出来就**置灰**（`step()` 那时会返回 false，
       按了没反应），别让它看着能按却什么都不干。
       ⚠️ `listLen` 是 `tracks()` 解析完才有的，所以 `mount()` 里挂了
          `tracks().then(paint)` —— 少了那一句，按钮会一直是灰的。 */
    nxBtn.disabled = listLen === 0;
    nxBtn.title = listLen ? '下一首' : '曲库没读出来 —— 点歌名回多媒体页';

    /* ⚠️ 被浏览器挡住的时候**不说"暂停"** —— 那不是用户按的暂停，是没放起来。
       按钮换成实心高亮、`title` 写明原因，用户一眼看得见要点哪儿。 */
    ppBtn.title = paused ? (blocked ? '浏览器不让自动接着放 —— 点一下' : '继续')
                         : '暂停';
    bar.classList.toggle('need', blocked && paused);
    const d = num(local.duration, 0);
    progEl.style.width = (d > 0 ? Math.min(100, (local.currentTime / d) * 100) : 0) + '%';
    subEl.textContent = paused
      ? (blocked ? '点 ▶ 接着听' : '已暂停')
      : (d > 0 ? fmt(local.currentTime) + ' / ' + fmt(d) : '正在播放');
  }

  /* ------------------------------------------------------------ 拖动（用户点名要的）
     ★ 2026-09-25 晚加。用户原话：「打开音乐后 别的页面左下角不是有一个小框吗
     那个小框有时候挡住别的字了 所以把它做成可以动的吧 我可以把它拖到别的地方」。

     ⚠️ **默认位置一个像素都没动**（还是 `left:.62rem / bottom:4rem` —— 那是
        `_scratch/_probe_mini_spot.py` 在 1638×843 上量出来的一条空带子）。
        改的是"只能在这儿"变成了"可以先拖走"。为什么需要这一手：那组数是
        **当时那几张页**量的，而页面版式一直在动（首页那次 `.main.dash .rail
        {grid-row:1}` 就把内容整体挪过）。默认值负责"大多数页面现在也对"，
        拖动负责"剩下的那些、以及以后再改版时"。两条都留着，别用"干脆换个默认位置"
        去替掉拖动 —— 换位置治不了"下一张页又挡上了"。

     ⚠️ 用 **pointer 事件**，不是 mouse 事件：展板那块屏能摸，触摸时 mouse 事件
        一个都不会来。配套的 `touch-action:none` 在样式那一段里（不写它，
        手指在条上划会被浏览器当成滚动抢走）。
     ⚠️ **条上三块都是能点的**（播放键 / 指回 media.html 的歌名链接 / 下一首键），
        所以"拖"和"点"必须分得开：
          · 走过 `DRAG_MIN` 像素才算拖 —— 手指按下去天然会抖，阈值不能是 0；
          · 拖过之后**那一次 click 要在捕获阶段掐掉**。歌名那条是 `<a href>`，
            不掐的话"把它拖到别处"会变成"跳去多媒体页"。
            标志位在下一次 `pointerdown` 复位，所以不会漏掉后面真正想点的那一下。

     ⚠️ 位置存 **localStorage**，不是 sessionStorage：这条框横跨 11 张页面，
        人拖一次就该到处都算数。**别和播放进度那个存档（sessionStorage）合并**，
        两者语义正好相反，见文件头「两个存储别搞混」。
     ⚠️ 存 px 不存比例。窗口尺寸变了靠 `clamp()` 夹回屏幕内，不做等比换算 ——
        展板是固定分辨率，等比换算只会带来"换台机器就飘到别处"的新麻烦。 */
  const POS_KEY = 'xq.media.mini.pos';
  const DRAG_MIN = 5;                    // 走过这么多像素才算"拖"，以下都算"点"

  function readPos() {
    try {
      const s = JSON.parse(localStorage.getItem(POS_KEY) || 'null');
      if (s && typeof s.l === 'number' && typeof s.t === 'number') return s;
    } catch (e) { /* 没存过 / 存坏了 / 隐私模式不让读：一律当没存过 */ }
    return null;
  }

  function savePos(l, t) {
    try {
      localStorage.setItem(POS_KEY, JSON.stringify({ l: Math.round(l), t: Math.round(t) }));
    } catch (e) { /* 写不进去就算了：这一趟照样是拖过去的，只是下次打开回默认位置 */ }
  }

  function makeDraggable(el) {
    /* 夹进视口。**四边各留 4px**：贴死了就再也抓不起来（那一侧没有像素可点）。 */
    function clamp(l, t) {
      const w = el.offsetWidth, h = el.offsetHeight;
      return [Math.min(Math.max(4, l), Math.max(4, innerWidth - w - 4)),
              Math.min(Math.max(4, t), Math.max(4, innerHeight - h - 4))];
    }
    function place(l, t) {
      const c = clamp(l, t);
      el.style.left = c[0] + 'px';
      el.style.top = c[1] + 'px';
      /* ★ `bottom:auto` 不能省：样式里那条 `bottom:4rem` 还在，top 和 bottom
         同时有值时元素会被**拉长**（高度变成"从 top 撑到 bottom"），
         条会当场变成一根竖着的长条。 */
      el.style.bottom = 'auto';
    }

    let sx = 0, sy = 0, ox = 0, oy = 0, live = false, moved = false;
    /* ★★ 监听挂在 **window** 上，**不能用 `el.setPointerCapture()`** ——
       这是 2026-09-25 晚**用户当场报回来的那个 bug**，原话：
           「能拖动 怎么不能暂停和下一首」。
       根因：`setPointerCapture(el)` 会把后续的指针事件**重定向到 el**，
       而浏览器顺手重定向的还有 mousedown/mouseup 那套兼容鼠标事件 ——
       于是 `click` 的目标变成了条本身、**不是条里那颗 `#xqMiniPP`**，
       `ppBtn.onclick` 一次都不跑。表现正是"拖得动，但播放/下一首按不动"。
       （我写完拖动时自己没测出来：那一支脚本只量了"点一下条会不会被拖走"，
         **没量"这一下点到底送到按键上没有"** —— 和 `_check_intro.py` 里
         `real_click` 缺 `mouseMoved` 是同一类失误：只验后果，不验送达。
         现在 `_check_minibar.py` 的 F 段挂了点击计数器，专门堵这个洞。）
       挂 window 是标准做法：不重定向任何东西，手指/鼠标划出条外也照样收得到 move。 */
    function onMove(e) {
      if (!live) return;
      const dx = e.clientX - sx, dy = e.clientY - sy;
      if (!moved) {
        if (dx * dx + dy * dy < DRAG_MIN * DRAG_MIN) return;
        moved = true;
        el.classList.add('dragging');
      }
      place(ox + dx, oy + dy);
      e.preventDefault();                  // 别顺手把歌名那几个字选上
    }
    function stop() {
      if (!live) return;
      live = false;
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', stop);
      window.removeEventListener('pointercancel', stop);
      if (moved) savePos(el.getBoundingClientRect().left,
                         el.getBoundingClientRect().top);
      el.classList.remove('dragging');
    }
    el.addEventListener('pointerdown', (e) => {
      if (e.pointerType === 'mouse' && e.button !== 0) return;   // 只认左键
      const r = el.getBoundingClientRect();
      sx = e.clientX; sy = e.clientY; ox = r.left; oy = r.top;
      live = true; moved = false;          // ← 复位在这里，见下面那条 click
      window.addEventListener('pointermove', onMove, { passive: false });
      window.addEventListener('pointerup', stop);
      window.addEventListener('pointercancel', stop);
    });
    /* ★ 拖完那一次 click **在捕获阶段**掐掉（`true`）：不掐的话松手会顺手
       触发底下的播放键/歌名链接。`moved` 只在下一次 pointerdown 复位，
       所以"漏一次掐到下一回真点"不存在。 */
    el.addEventListener('click', (e) => {
      if (!moved) return;
      e.preventDefault();
      e.stopPropagation();
    }, true);
    el.addEventListener('dragstart', (e) => e.preventDefault());   // 别拖出个图片影子

    const p = readPos();
    if (p) place(p.l, p.t);
    /* 窗口变小（退出全屏、换分辨率）之后存的位置可能已经出界 —— 夹回来。 */
    addEventListener('resize', () => {
      const r = el.getBoundingClientRect();
      place(r.left, r.top);
    });
  }

  function build() {
    const el = document.createElement('div');
    el.className = 'xq-mini';
    el.id = 'xqMini';
    /* 一行四块：播放键 / 歌名（点它回多媒体页）+ 右侧那一小截时间 / 下一首键。
       进度条是那条贴底边的细线（`overflow:hidden` + 圆角把它裁在胶囊里）。
       ★ 2026-09-25：最右边那一格原来是箭头（回多媒体页），换成了下一首键（见下）。
       ⚠️ **歌名和时间是同一行**（不是上下两行）。第一版写的是上下两行、总高
       47px，结果顶上那 2px 正好压进首页那两块快捷功能砖（`a.qk` 底边 y=740，
       而条最高只能到 741）—— E 段当场报红。改成一行之后高度是
       1.7rem(播放键) + padding ≈ 36px，稳稳落在 741~785 那条 44px 的缝里。
       **别再把它写回两行**，除非先重跑 `_probe_mini_spot.py` 看缝还够不够。 */
    /* ★ 2026-09-25：右边那个 `>` 箭头（`.xq-mini-chev`，"回多媒体页"）**换成了
       下一首键**。用户要的是「右边应该有下一首的按键」，而箭头和 ⏭ 并排会出现
       两个都像"下一个"的东西 —— 留哪个都得解释半天，所以留功能性的那个。
       "回多媒体页"这条路**没丢**：歌名本身就是一条指回 media.html 的链接
       （`title="回多媒体页"`），箭头只是它的一个视觉提示。 */
    el.innerHTML =
      '<button class="xq-mini-pp" id="xqMiniPP" type="button"></button>' +
      '<a class="xq-mini-tx" id="xqMiniGo" href="media.html" title="回多媒体页">' +
        '<b id="xqMiniName"></b><span id="xqMiniSub"></span></a>' +
      '<button class="xq-mini-nx" id="xqMiniNext" type="button"></button>' +
      '<i class="xq-mini-prog"><i id="xqMiniProg"></i></i>';
    document.body.appendChild(el);
    makeDraggable(el);          // ★ 见上面那段：这一条现在能拖到别处（用户点名要的）

    bar = el;
    ppBtn = el.querySelector('#xqMiniPP');
    nxBtn = el.querySelector('#xqMiniNext');
    nameEl = el.querySelector('#xqMiniName');
    subEl = el.querySelector('#xqMiniSub');
    progEl = el.querySelector('#xqMiniProg');
    nxBtn.innerHTML =
      '<svg viewBox="0 0 24 24" aria-hidden="true">' + XQ.ICON.next + '</svg>';

    ppBtn.onclick = () => {
      /* 被挡住的那一次，**这一下点击就是浏览器要的用户手势** —— 所以这里不是
         "重试一次播放"，而是"补上它一直缺的那一下"。 */
      if (local.paused) {
        local.play().then(() => { blocked = false; paint(); })
                    .catch(() => { blocked = true; paint(); });
      } else {
        local.pause();
      }
    };
    nxBtn.onclick = () => { step(1); };
    ['play', 'pause', 'ended', 'loadedmetadata', 'volumechange'].forEach((ev) => {
      local.addEventListener(ev, () => {
        if (ev === 'play') blocked = false;
        paint();
        push(true);
      });
    });
    local.addEventListener('timeupdate', () => { paint(); push(false); });
    local.addEventListener('ended', () => {
      /* ★★ 2026-09-25：**放完自动接下一首**。
         用户原话：「右边应该有下一首的按键 而不是播完就暂停了 并且应该自动播下一首」。
         这一段原来是"如实停在原地"（位置归零、状态写"不在放"，条上留一个 ▶），
         理由是当年这一层不拉曲库、不知道下一首是谁。现在为了这个功能把曲库
         拉进来了（见 `tracks()` 那段），那条理由**没有了** —— 所以这里跟着改，
         不是"偷偷加了一条自动播放"。
         ⚠️ 但曲库拉不到时（file:// 直接打开、服务端挂了）**必须退回旧行为**：
            停在原地、留一个 ▶、不假装。所以是 `if (ok) return;` 加下面那段
            老逻辑，**不是把老逻辑删掉**。
         ⚠️ 用 `.then` 不用 `await`：这是个事件回调，写成 async 的话它返回的
            Promise 没人接，中间抛出来的东西会变成一条 unhandled rejection
            （本项目控制台零报错的老规矩）。 */
      step(1).then((ok) => {
        if (ok) return;
        save({ file: meta().file, title: meta().title, artist: meta().artist,
               pos: 0, dur: num(local.duration, 0), vol: local.volume,
               playing: false, t: Date.now() });
        paint();
      });
    });
  }

  /* 把"别的页面那个 audio + 左下角那条"建起来。**幂等**（已经建过就什么都不做）。
     ★ 2026-09-25 晚从 `mount()` 里拆出来给 `playCalm()` 用：点播的时候存档可能
     是空的（这一趟从没开过多媒体页），而原来那版 `mount()` 见存档为空就直接
     return —— 于是"点播"根本没有能出声的元素，点了什么都不发生。
     ⚠️ 音量在这里设，不留给调用方：`playFile()` 会把 `local.volume` 写进存档，
        新建的元素默认是 1.0，比多媒体页那个 `#vol` 的初始值(0.8)响一档 ——
        不设的话"从驾驶监测页点进去的歌"比"在多媒体页点的同一首歌"响。
     ⚠️ `src` **不在这里设**：`mount()` 要接着上次那一秒（要 seek），
        `playFile()` 要从头放 —— 两件事各自设，别在公共函数里猜。 */
  function buildAudio() {
    if (local) return;
    local = new Audio();
    local.volume = num((load() || {}).vol, DEFAULT_VOL);
    build();
  }

  function mount() {
    if (native) return;                       // 多媒体页：它自己就是播放器
    const st = load();
    if (!st) return;                          // 没开过多媒体页 / 存档过期：开局不画。
                                              // ★ 点播照样能建（见 `buildAudio`）
    buildAudio();
    local.src = srcOf(st.file);
    /* ⚠️ `currentTime` **要在 `play()` 之前设**，而且这时候 `readyState` 还是 0
       —— 按规范，HAVE_NOTHING 时写 `currentTime` 会存成"默认起播位置"，等元数据
       到了一次性生效（Chrome 就是这么实现的，不会抛）。写成"等 loadedmetadata
       再 seek"也行，但那样会先从头响一小下再跳。 */
    try { if (num(st.pos, 0) > 0) local.currentTime = st.pos; } catch (e) { /* 老引擎拒了就从头放 */ }
    nameEl.textContent = st.title || (st.file || '').replace(/\.[^.]+$/, '');
    nameEl.title = nameEl.textContent;
    paint();                                   // 先画一版（哪怕还没起播）
    /* ★ 2026-09-25：开局就把曲库拉起来（不在 `paint()` 里拉 —— 那个每秒跑五次）。
       两个作用：① 下一首那个键由灰变亮的时机（`paint()` 读 `listLen`）；
       ② 第一首放完时**不用等一次网络往返**，接得上。 */
    tracks().then(paint);

    if (st.playing) {
      local.play().then(() => { blocked = false; paint(); })
                  .catch(() => {
                    /* 起播被挡：**如实说**（live.js 那条提示条），条上留 ▶。
                       不吞异常、也不装作在放 —— 页面看着在放而没声音是最坏的。 */
                    blocked = true;
                    paint();
                    say('浏览器不让自动接着放 —— 点左下角那个播放键');
                  });
    }
  }

  /* ---------------------------------------------------------------- 自检口子 */
  /* 和 media.html 的 `XQ.mediaLink.stats()` 同一个规矩：**读的是真状态，一个
     转发层都没有**（`native`/`local` 就是那两个 audio 本身）。检查脚本靠它验
     "换了一页之后真的接着在放"，不是靠屏幕上的字。 */
  XQP.stats = function () {
    const a = native || local;
    return {
      mounted: !!bar, native: !!native, mini: !!local,
      file: meta().file, title: meta().title,
      pos: a ? num(a.currentTime, 0) : -1,
      dur: a ? num(a.duration, 0) : 0,
      vol: a ? num(a.volume, -1) : -1,
      playing: a ? !a.paused : false,
      blocked: blocked,
      /* ★ 2026-09-25：曲库读到了几首（0 = 没读到，"放完停住"那条老路还在走）。 */
      listLen: listLen,
      src: a ? (a.currentSrc || a.src || '') : '',
      saved: (function () { const o = load(); return o ? o.pos : null; })(),
      /* ★ 2026-09-25 晚：点播那一路的读数（`_probe_click_calm.py` 用）。**注意名
         字**：media.html 的 `stats().calmRecent` 是**下标**，这里是**文件名** ——
         两边的"最近推过谁"是同一份账（共用 `XQP.calmNote`），只是各自的坐标系
         不一样，取的时候别混。 */
      asked: calmAsked.slice(),
    };
  };

  /* ---------------------------------------------------------------- 样式 */
  /* ⚠️ 样式**从 JS 里注入**，不写进 style.css / pages.css。理由：这一层的开关
     就是"有没有这么一个 `<script>`"，把样式留在同一个文件里，删掉那一行就
     **整个东西都不见了**；拆成两处的话，删了脚本会在 9 张页面上留下一堆死规则。
     颜色/字号/圆角**全部借现成的变量**（和 `.toast` 同一套面子），不新造。 */
  const CSS = `
  /* 🔴 **这个模板串里不许出现反引号本身** —— 就是英文键盘左上角、波浪号底下
     那一个（这里连它都打不出来，写了它这一行就完了）。它就是这一层的字符串
     结束符。下面那几行注释里原本用「英文反引号」包着 #rail、max-width 这些
     名字，于是整个 player.js 当场 SyntaxError、**一行都没跑**：表现是
     window.XQP 是 undefined、「#xqMiniCss」不在文档里，而服务端给这个文件是
     200（_scratch/_probe_player_js.py 量的）。要写代码名就写「」，别用引号。
     同一类坑还有「</script>」不能出现在行内脚本的字符串里。 */
  /* ⚠️ **位置是量出来的，不是挑出来的。** 这条卡在左下角，而左下角本来就住着
     东西：#rail（左导航）占 x[9,176]，一直伸到屏幕底；.rail-foot（左下角那个
     CHERY 车标，用户点名要留的）占 y[785,836]。1638×843 的窗口量下来
     （_scratch/_probe_mini_spot.py），**九张页上唯一一条横着没人用的带子**是
       x[12,302] × y[750,785]  ——
     往上一档是首页那两块快捷功能砖（.qk 到 y=740）、以及左栏那颗喇叭按钮
     （到 y=721；★ 2026-09-25 那颗按钮全站删了，所以这一档现在只会更空 ——
     这几个数是**有按钮时**量的，少一个元件不会把 y[750,785] 那条带子占回去）；
     往右一档是 chat.html 底中那组 ⏮▶⏭（从 x=378 起，到 y=811）；
     再往右是驾驶监测/多媒体那行对话输入（从 x=960 起，到 y=823）。
     所以：**贴着左栏左边缘、压在导航卡下沿与车标之间那条缝里**。这个位置看一眼
     是"左栏那一摞的最下面一格"（导航卡 → 播放条 → 车标），不挡任何一个可点的
     东西，也没把车标盖掉。
     🔴 想挪它之前**先重跑那个探针**：这几个数是量出来的，改了别的页面布局它们就变。 */
  .xq-mini{
    position:fixed; left:.62rem; bottom:4rem; z-index:40;
    display:flex; align-items:center; gap:.5rem;
    /* 宽度**写死**，不用 max-width 让它随内容缩：这是"现在在放哪一首"的条，
       长度跟着歌名变的话，换一首就跳一下。窄屏那条 @media 再压窄。 */
    width:20rem; max-width:calc(100vw - 1.4rem); box-sizing:border-box;
    padding:.42rem .72rem;
    border-radius:2rem; overflow:hidden;
    background:var(--panel-4); border:1px solid rgba(var(--rgb),.42);
    box-shadow:0 0 1.6rem rgba(var(--rgb),.24);
    color:var(--ink); font-size:var(--fs-sm); line-height:1.15;
    opacity:0; transform:translateY(.7rem);
    animation:xqMiniIn .45s ease-out forwards;
    /* ★ 2026-09-25 晚：这一条**能拖**（见 JS 里 makeDraggable 那段）。
       这三句都是"拖得动"必需的，不是装饰：
         cursor:grab       —— 鼠标移上去能看出"这东西抓得起来"（触摸屏上看不到，
                              所以真正的说明写在用户看得到的地方：他提的需求）。
         user-select:none  —— 不写的话拖一次就把歌名那几个字**选中**了，
                              蓝色的选区留在条上，下一首歌名刷新才消失。
         touch-action:none —— ⚠️ 展板那块屏能摸。触摸时浏览器默认把手势当滚动，
                              不写这句的话手指在条上划会变成"页面滚一下"、
                              pointermove 根本不来 —— 触摸屏上等于拖不动。
                              条里没有可滚的东西，所以这一句没有副作用。 */
    cursor:grab; user-select:none; -webkit-user-select:none; touch-action:none;
  }
  /* 正在拖：光标换成抓握，影子放大一点当"我现在提起来了"的反馈。
     ⚠️ transition 不能写在这条上（左右上下的位移要跟手，加了过渡就有橡皮筋感）。
        —— 这句原本把 transition 用「英文反引号」括起来了，于是**整个 CSS 模板串
           在这里就断了**：文件当场 SyntaxError、window.XQP 是 undefined、
           12 张页面上的悬浮条全是死的，而服务端给这个文件回 200。
           症状正是 "Uncaught SyntaxError: Unexpected identifier 'transition'"。
           这条坑文件头已经用黑体写过两遍（见上面那两处 ⚠️），我又踩了一次 ——
           所以这里连标记都不加了，**这个模板串里一个反引号都不许有**。 */
  .xq-mini.dragging{ cursor:grabbing; box-shadow:0 0 2.4rem rgba(var(--rgb),.42); }
  @keyframes xqMiniIn{ to{ opacity:1; transform:translateY(0); } }
  .xq-mini .xq-mini-pp{
    flex:0 0 auto; width:1.6rem; height:1.6rem; border-radius:50%;
    display:grid; place-items:center; cursor:pointer; padding:0;
    color:var(--accent); background:rgba(var(--rgb),.16);
    border:1px solid rgba(var(--rgb),.34); transition:.25s;
  }
  .xq-mini .xq-mini-pp svg{ width:.95rem; height:.95rem; }
  .xq-mini .xq-mini-pp:hover{ background:rgba(var(--rgb),.28); }
  /* 被浏览器挡住时按钮实心高亮 —— "没放起来"要和"我按了暂停"长得不一样。 */
  .xq-mini.need .xq-mini-pp{
    color:#fff; background:var(--accent);
    border-color:var(--accent); box-shadow:0 0 0 .18rem rgba(var(--rgb),.22);
  }
  .xq-mini .xq-mini-tx{
    flex:1 1 auto; min-width:0; text-decoration:none; color:inherit;
    display:flex; flex-direction:row; align-items:baseline; gap:.42rem;
  }
  .xq-mini .xq-mini-tx b{
    flex:1 1 auto; min-width:0;
    font-size:var(--fs-sm); font-weight:600;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
  }
  /* 右侧那一小截（时间 / 已暂停 / 点 ▶ 接着听）。**宽度随字走、不被压扁**：
     它短，而歌名会先让位给省略号。 */
  .xq-mini .xq-mini-tx span{
    flex:0 0 auto; font-size:.62rem; color:var(--ink-3);
    white-space:nowrap;
  }
  /* ★ 2026-09-25：这一格原来是一个朝右的小箭头（指的是"回多媒体页"），
     现在换成了下一首键。它**比播放键小一圈、不填底色** ——
     一左一右两个一样重的圆钮会让人以为"上一首/下一首"，而左边那个是播放。
     ⚠️ 这段注释在一个模板串里面：**里面一个反引号都不能写**
        （哪怕只是想标个行内代码，也会把模板串当场截断、整个文件语法错、XQP 全没了）。
        这条踩过两次，见 _scratch/_js_template_scan.py。 */
  .xq-mini .xq-mini-nx{
    flex:0 0 auto; width:1.5rem; height:1.5rem; border-radius:50%;
    display:grid; place-items:center; cursor:pointer; padding:0;
    color:var(--ink-3); background:transparent;
    border:1px solid rgba(var(--rgb),.28); transition:.25s;
  }
  .xq-mini .xq-mini-nx svg{ width:.9rem; height:.9rem; }
  .xq-mini .xq-mini-nx:hover{ color:var(--accent); background:rgba(var(--rgb),.22); }
  /* 曲库没读出来时**置灰**（paint() 里按 listLen 开关）。
     ⚠️ :disabled:hover 也要写：不写的话鼠标压上去还会亮一下，
        看着像"能按但按不动"，比一直灰着更让人困惑。
     ⚠️ 这一段在模板串里面，**一个反引号都不能写** —— 见上面那条。 */
  .xq-mini .xq-mini-nx:disabled{ opacity:.38; cursor:default; }
  .xq-mini .xq-mini-nx:disabled:hover{ color:var(--ink-3); background:transparent; }
  /* 贴底边那条进度细线（被 overflow:hidden 的圆角裁成胶囊底边）。 */
  .xq-mini .xq-mini-prog{
    position:absolute; left:0; right:0; bottom:0; height:2px;
    background:rgba(var(--rgb),.14);
  }
  .xq-mini .xq-mini-prog i{
    display:block; height:100%; width:0;
    background:var(--accent); transition:width .3s linear;
  }
  /* 窄屏（投影仪 1280 那档）：条压窄一点，别横到页面中间去。
     ⚠️ 那档上 1rem 本身也变小了（1638 宽时是 14.5px），左右的东西跟着一起缩，
        所以上面那套"谁挨着谁"的关系整体成比例，不用另算。 */
  @media (max-width:1180px){
    .xq-mini{ width:14rem; }
    .xq-mini .xq-mini-tx span{ display:none; }
  }
  `;
  const style = document.createElement('style');
  style.id = 'xqMiniCss';
  style.textContent = CSS;
  document.head.appendChild(style);

  /* ⚠️ 等 `DOMContentLoaded` 再决定画不画：这一页的**行内脚本排在最后**，
     多媒体页就是在那里调 `XQP.bind()` 的 —— 早于它跑，多媒体页会被当成
     "别的页面"、多出一条悬浮条来（判断依据是 `native` 有没有被 bind 过）。 */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }

  window.XQP = XQP;
})();
