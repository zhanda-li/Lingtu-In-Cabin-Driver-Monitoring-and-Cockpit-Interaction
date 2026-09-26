
/* =========================================================================
   10 PPT 展示封面
   -------------------------------------------------------------------------
   纯展示页，不连 WebSocket，正文全是 HTML 里写死的（封面没有什么要算的东西）。
   脚本只干三件必须由 JS 干的事：眉标前面那个图标、小瑞那张 SVG、
   以及小瑞那一格「点一下换形象」。
   **「进入座舱」那个按钮是纯 <a>，不在这里的 JS 里** —— 它不能依赖 socket。

   小瑞这一格是全场唯一一个**立绘位**（pages.css 里 .cover-r .mascot 是高槽，
   不是 6.6rem 的方槽），所以吃形象库里 **`l`（730x1000）** 那套；
   方槽（对话栏、手机页、设置页、聊天气泡）吃 **`h`（192x192）**，
   座舱里的立绘位吃 **`s`（210x288）**。三套的来历见 live.js 的 XQ.POSES 那段。
   ⚠️ 小瑞这几张图**已经进仓库了** —— 原来那两张（从 7.png 抠的雪宝二创）因版权被
      .gitignore 挡着，2026-09-23 换成本项目原创的小瑞之后那两条就删了；
      见 .gitignore 那段注释。
   ========================================================================= */
'use strict';
const $ = (id) => document.getElementById(id);

/* ★ 2026-09-24：原来这里是 `$('eyebrow').insertAdjacentHTML(...)`，
   眉标胶囊删掉之后那行会**崩在 null 上**（整段脚本停在这儿，下面的
   `mascotSlot` 就不会跑，小瑞直接不出来）。改成给三个特性胶囊填图标：
   `data-ic` 上写名字、这里统一填，HTML 里就不用嵌 SVG。 */
for (const el of document.querySelectorAll('.cover-feats .ic')) {
  el.innerHTML = XQ.icon(el.dataset.ic);
}
$('coverMascotSvg').innerHTML = XQ.mascotSVG();
/* ============================ 封面这一格：点一下换形象 ============================
   ★ 2026-09-24 的口径（用户原话）：「不要这个了 展示页变成 可点击小瑞然后换动作
     从我图片里换」。追问之后定了两条：**只走好看的几张**、不点的时候**上下浮动就行**。
   所以这里**不再是循环动图**了 —— 上一版挂的是 `assets/xiaorui_hero.webp`（立绘尺寸的
   待机动画），这条注释就是替换它留下的。

   ★ 2026-09-25（第十次改版）：用户「小瑞图片能变化的太少了 我不是有 40 多张图片吗
     把那些出现小瑞的地方都变成可以变化的」。于是这里原来那套 5 张
     （`assets/xiaorui_pose_*.png`，805x1200，`_mk_cover_poses.py` 出的）**整批删掉**，
     换成全站共用的 **43 张形象库**；机制也不再是这里自己那十几行，而是
     `XQ.poseDeck`（live.js）—— 十页的左栏、座舱的立绘位、手机页、设置页、聊天气泡
     走的是同一个函数。这一格现在只剩"传尺寸、传起始形象"两件事。

   ★ **"上下浮动"不用另写 keyframe**：style.css 的 `xqIdle` 就是它 ——
     `translateY(-2.2%) scale(1.015)`、4s 一循环、`transform-origin:50% 88%`（贴脚转，
     所以像站着起伏而不是像飘）。那条规则挂在 `.mascot-img` 上，全站所有小瑞都吃，
     这一格只要**不挂 `data-act`** 就是浮动状态。

   ★ **换形象那一下的位移**是 `img[data-act="swap"]`（style.css），挂上就盖住 `xqIdle`，
     由 `poseDeck` 在 620 ms 后摘掉。
   ⚠️ **摘掉这一步是整套的关键**：那些 `[data-act]` 规则权重一直压着 `.mascot-img`，
     不摘的话 `xqIdle` **永远回不来**，这一格就变成"点一下之后就再也不浮动了"。
     `poseDeck` 里那条注释记的是同一个坑。

   ★ **为什么这里不调 `XQ.mascot.bind()`**：这一格是纯展示页，不连 WebSocket、
     没有档位可跟，而 `bind` 那套的全部价值就在于**跟档位**（`react()` 的 MAP）。
     所以这一格只要"点一下换形象 + 呼吸"，`bind` 一个字都不动。
     （早先这里还写了一条"封面只呼吸、不换姿态"的理由 —— 那条 2026-09-25 已经
      不成立了，用户要求全站都能点着换。）

   ⚠️ **素材是 `l` 那套**（`assets/xq/l/p01..p43.webp`，730x1000）。这一格是
     **立绘位**（`.cover-r .mascot` 是 44x46rem = 638x667 px），DPR=2 下要 1276 px 高，
     1000 是**略欠**的（1.5x 而不是 2x）—— 这是已知取舍：再出一套 1400 高的会让
     43 张的总体积从 9.4 MB 涨到 18 MB，而 `/assets` 是 no-store、点一下就要下一次。
     要改这个取舍（改成 1400 或改成"封面只留 10 张大的"），改之前先问用户。
   ⚠️ 那 43 张**逐张对齐过**（脚踩同一张画布底、水平按 alpha 包围盒中心对齐，残差
     0.55 px；`_mk_xq_poses.py` 里断言过），所以点一下换形象**不会左右跳也不会上下挪**。
     ⚠️ 例外只有 p43（一张头部特写）：它比别的宽，被按**宽**缩到画布 89% 高，
       点过去会看见人突然变小一圈。这是脚本里写明的已知例外，不是翻车。

   ⚠️ 没有 `still` 可传：底图是静态 webp，不涉及"CSS 关不掉 <img> 里的动画 WebP"
     那个老问题；「减弱动态效果」由 style.css 那条媒体查询把 `xqIdle` 和
     `[data-act]` 的位移**一起**关掉，退化成一张静止立绘（点一下仍然换，只是不浮不弹）。

   ★ 2026-09-25：`coverShow()` / `COVER_POSES` / `COVER_HOLD` 三个名字**一起删了**。
     它们是"这一格自己一套"的残留，留着会和 `XQ.poseDeck` 变成两套口径 ——
     这正是用户这轮抱怨的那个毛病（同一件事在几个地方各写一遍，一处改了别处没改）。
     检查脚本要用名字的话读 `XQ.POSES`。（`_scratch/_check_mascot.py` 的封面那几条
     按新素材改过了，别照旧名字找。） */
XQ.mascotSlot('coverMascotImg', 'coverMascotSvg', {
  /* 底图 = 形象库的 p01（`deck` 传了尺寸就会自己取这张，这里显式写一遍是为了
     让"封面吃哪一套"在这行上看得见）。 */
  src: XQ.poseURL('p01', 'l'),
  onReady: (im) => {
    /* 手点挂**父节点**上：.mascot-img 只有图片本身大小、且 ::after 那团地台光在
       .mascot 里，挂父节点面积更大也更好点（和 live.js 里 poseDeck 的 ③ 同一条）。 */
    const host = $('coverMascot');
    if (!host) return;
    XQ.poseDeck(im || $('coverMascotImg'), host,
                { size: 'l', base: 'p01', title: '点一下换个形象' });
  },
});

/* 封面这一页 rail 被 `body.cover` 藏掉了，`active` 谁都不亮 —— 无所谓，
   留着是为了和别的页同一个调用形状（改起来只改一处）。
   气候栏已经整条删掉（XQ.climateHTML 不再存在），不用再管它。

   ★ 2026-09-23：顶栏中间那个时钟拿掉了，改成由**页面自己**决定挂什么。
   封面挂的是项目主题文字（13.png 的版式：左 logo、中标题、右状态）。
   ⚠️ **只有封面传 title**。座舱内那 10 页每页自己已经有一个页面标题
      （导航/首页/多媒体/…），顶栏再写一遍同一句话是重复；
      而这一行有 19 个字，塞进每一页的顶栏会把左右两块压得没地方站。
      哪一页要挂什么，由那一页自己在 mountChrome 里传 —— 见 chrome.js 里
      XQ.clockHTML 上面那段。 */
/* ★ 2026-09-24：多传一个 logo:true —— 顶栏右上角放同济大学汽车与能源学院的
   院徽（素材 ui/图片效果/14.png，生成脚本 _scratch/_mk_tongji.py）。
   **只有本页传**：院徽是院校标识，座舱内那 11 页的顶栏右侧保持空着
   （空着也占位，见 style.css 里 .collab 那段）。

   ★ 2026-09-25：这行标题**缩短了**。用户原话：「顶部标题重复：大字已经写了
   『情感化智能座舱驾驶员健康监测预警系统』，顶部小字可以精简，避免文字冗余。
   顶部改成简短一行：情感化智能座舱 | 驾驶员健康监测预警」。
   他说的**大字**是左栏那行 `.cover-sub`（1.75rem，见上面那段注释里那串字数
   统计）；顶栏这行只有 1.06rem（style.css 的 `.tbtitle`），是"小字"。
   同一句话在一屏里出现两遍 —— 一遍大一遍小 —— 就是这里要消掉的那处重复。
   ⚠️ **`.cover-sub` 一个字都没动**（1.75rem 那行才是"大字"，用户要保留它）。
      别看着两边字数不一样就"顺手统一"，那正好把用户要的东西改回去了。
   ⚠️ `_check_theme2.py:594` 那条断言是全等比对（`==`），同批改成新句子；
      它下面 `:574` 那条 `endswith` 盯的是 `.cover-sub`，**不受影响**。 */
XQ.mountChrome({ active: 'home', logo: true,
                 title: '情感化智能座舱 | 驾驶员健康监测预警' });

/* ---------------------------------------------------------------------------
   ★ 2026-09-24：标题两侧那两道装饰（样式在页面 <style> 里，见上面那段）。

   **必须在 mountChrome 之后再跑** —— 顶栏那一格是它 `innerHTML` 塞进去的，
   在这之前 `#tbTitle` 根本不存在。
   （那套模板原来还有个 `setInterval(XQ.tickClock, 10000)` 会每 10 秒重建顶栏、
   把这里加的两个元素冲掉，2026-09-23 时钟删掉时那个 interval 一并删了，
   所以现在塞一次就够。哪天顶栏又变回"会被重建"，这段就得跟着重跑。）

   位置按**实测矩形**摆，不写百分比：标题是 19 个字、字号随 rem 走，
   写死的 `calc(50% ± Nrem)` 一改字号就错位。

   ⚠️ `getBoundingClientRect()` 给的是**边框盒**；绝对定位的包含块是 `.topbar` 的
      **内边距盒**。`.topbar` 只有 `border-bottom`，左右边框是 0，
      所以两者的左右边一致，下面直接用 `r.left/r.right` 换算不用补偿。
      哪天给 `.topbar` 加了左右边框，这里就要减去边框宽。
   ⚠️⚠️ **这两个数不能只算一次，必须能重算。** 两端的元素里都有 `<img>`
      （品牌那个标志、院徽），而它们都**没写死宽度**（只有高度，宽度 auto）——
      图没加载完时 `getBoundingClientRect().width` 是 **0**。在 `mountChrome`
      刚跑完那一刻量，量到的是"标志宽 0 / 院徽宽 0"的幻影：
      左边那条会短一截、右边那条直接算成**负宽 = 整个不见**，而且不报任何错。
      （2026-09-24 踩到：`runs/_cover_v8.png` 左边有右边空。）
      所以下面 `layout()` 是**幂等**的，创建一次元素、反复摆：
      立刻一次 → `window.load` → 再补两次定时（图片解码慢的时候兜底）。
   ⚠️ 院徽是**两张图二选一**（`.collab-logo.on-dark` / `.on-light`，见 chrome.js
      那段说明），没显的那张 `display:none` ⟹ 它的 rect 恒为 0。
      所以取的是"宽度 > 0 的那一张"，都量不到就退回整格 `.collab`（那一格的
      左边在标题右格线上，只能当"实在没辙"的兜底，位置是错的）。
   ⚠️ 窄屏（<1180px）这两个元素是 `display:none`，但**矩形的计算照样跑** ——
      无所谓（算出来是坏值也没人看），`layout()` 在 `load` 时还会再跑一次，
      那时若还是窄屏就还是隐藏的。本页是投屏用的固定尺寸页，不做 resize 监听。 */
(function () {
  const tb = document.getElementById('topbar');
  const ttl = document.getElementById('tbTitle');
  if (!tb || !ttl) return;

  /* 珠子中心到标题左边 = 45px。这是**量的**：13.png 里标题占 x 630..1044，
     左珠子中心 x≈585（630−585=45）、右珠子 x≈1092（1092−1044=48），两侧一致。
     珠子半宽 1.3rem≈19px，所以珠子右缘离标题约 25px。 */
  const GAP = 45;
  /* 线离品牌/院徽留的空。13.png 左边 87px、右边 104px；这里两侧都用 80 ——
     参考那两个数是按**它自己的**标志宽度定的，本站标志宽度不同，
     照抄反而不对称。 */
  const PAD = 80;

  const mk = (cls) => {
    const e = tb.querySelector('.trace.' + cls);
    if (e) return e;
    const i = document.createElement('i');
    i.className = 'trace ' + cls;
    tb.appendChild(i);
    return i;
  };
  const a = mk('a'), b = mk('b');

  const shown = (sel) => {
    for (const e of tb.querySelectorAll(sel)) {
      if (e.getBoundingClientRect().width > 0) return e;
    }
    return null;
  };

  function layout() {
    const r = tb.getBoundingClientRect();
    const t = ttl.getBoundingClientRect();
    /* ⚠️ 必须用 shown()：`.lingtu-lockup` 现在有**两张**（on-dark / on-light），
       被主题藏起来的那张 rect 宽高是 0，直接 querySelector 在浅色主题下会拿到
       藏起来的那张（它是 on-dark，排在前面），于是左半边那条线**根本不画**。
       2026-09-24 晚品牌组从 .lingtu 换成整张 lockup 时同步改的。 */
    const brand = shown('.lingtu-lockup') || tb.querySelector('.brand');
    const collab = shown('.collab-logo');
    /* 哪一个量不出来就**保持上一次的位置**，不要拿 0 去算 ——
       拿 0 去算正是"右边那条整个不见"的那个 bug。 */
    const put = (e, left, right) => {
      e.style.left = (left - r.left).toFixed(1) + 'px';
      e.style.right = (r.right - right).toFixed(1) + 'px';
    };
    if (brand && brand.getBoundingClientRect().right > r.left) {
      put(a, brand.getBoundingClientRect().right + PAD, t.left - GAP);
    }
    if (collab && collab.getBoundingClientRect().left > t.right) {
      put(b, t.right + GAP, collab.getBoundingClientRect().left - PAD);
    }
  }

  layout();
  window.addEventListener('load', layout);
  setTimeout(layout, 300);
  setTimeout(layout, 1200);
})();

/* ===========================================================================
   品牌片头（`assets/lingtu_intro.mp4`，15.07 s）。样式在上面那段 <style> 里。
   ---------------------------------------------------------------------------
   用户 2026-09-25 拍板：「静音自动播吧」。所以是 `muted` + `autoplay`，
   不需要任何点击 —— 浏览器只拦"自动播放**且带声**"，静音那条路是放行的。

   ★★ 这一段的全部重点是**退出口**，不是播放。片头是 `position:fixed` +
      `z-index:9999` 的全屏不透明层，**它盖着「进入座舱」**。所以只要有一条
      退出路径漏了，人就被关在封面外面 —— 这是这一块唯一真正危险的地方。
      三条，缺一不可：
        ① `ended`  —— 正常播完（15.07 s）
        ② 跳过按钮 —— 评委不想看第二遍；重播练习时更用得上
        ③ **兜底定时器** —— 这条最容易被"优化"掉，而它恰恰是必须的：
      🔴 真机上解不出 HEVC 时（没装扩展 / 显卡不能硬解）**不会触发 `error`
         事件**。实测那台机器的表现是 `error.code = 0`、控制台干干净净、
         `readyState = 4` 甚至连 `duration` 都读得出来 —— **只是画面全黑**。
         一个"等 error 再收掉"的写法在这里会**永久卡在黑屏上**，而且没有任何
         报错指向它。所以兜底不能挂在事件上，必须挂**时间**。

   ★ 什么时候不播（判在前，播在后；顺序就是优先级）：
       · `?intro=0`  —— 不播。**给检查脚本用的**（`_check_mascot.py` /
         `_check_posedecks.py` 要点这一页的小瑞、`_check_bg.py` 要量这一页的
         亮度、`_check_pages.py` 要点「进入座舱」；一层全屏不透明的盖子会把
         这些**全部静默压死**，而且报出来的错跟"片头"看不出关系）。
       · `?intro=1`  —— **一定播**，压过下面两条。重播练习 / 验收片头用。
       · 「减弱动态效果」—— 不播。和全站现有约定一致（小瑞那套也是这么降级的）。
       · 这次会话已经播过 —— 不播。答辩现场刷新一下不该被再看 15 秒。
   ⚠️ `?intro=1` **不写 sessionStorage 之外的例外**：它照样会记"播过了"，
      所以别指望用 `?intro=1` 连着刷两遍都看得到 —— 要连看两遍请开新标签页
      （sessionStorage 是按标签页的）。
   =========================================================================== */
(function () {
  const box = $('intro'), v = $('introV'), sk = $('introSkip');
  if (!box || !v) return;                       /* 元素被删了也当没有片头 */

  const KEY = 'xq.intro.seen';                  /* 全站 localStorage 键都带 xq. 前缀 */
  const q = location.search;
  const forced = /[?&]intro=1(?:&|$)/.test(q);
  const banned = /[?&]intro=0(?:&|$)/.test(q);
  const calm = !!(window.matchMedia
                  && matchMedia('(prefers-reduced-motion: reduce)').matches);
  let seen = false;
  try { seen = sessionStorage.getItem(KEY) === '1'; } catch (e) { /* 无痕模式 */ }

  /* ⚠️ 只**不加 `.on`**（元素留在 DOM 里），不要 `remove()` —— 检查脚本要能
     数得到这个元素、也要能证明"它默认是 display:none 的"。 */
  if (banned || (!forced && (calm || seen))) return;

  box.classList.add('on');
  try { sessionStorage.setItem(KEY, '1'); } catch (e) { /* 记不住也不影响播放 */ }

  let done = false;
  const finish = () => {
    if (done) return;                           /* 三条路可能同时到，只认第一条 */
    done = true;
    box.classList.add('gone');                  /* 淡出（.55s） */
    setTimeout(() => {
      box.classList.remove('on');                /* 摘掉 .on → 回到 display:none */
      try { v.pause(); } catch (e) { /* 已经收掉了 */ }
    }, 620);                                     /* 比过渡长一点，别抢在淡出中间 */
  };

  v.addEventListener('ended', finish);
  v.addEventListener('error', finish);           /* 有的机器会报，报了就早点收 */
  if (sk) sk.addEventListener('click', finish);

  /* ③ 兜底定时器。有元数据就按**真实时长** +1.4 s，没有就 20 s 硬收。
     ⚠️ 这两个 setTimeout **不挂在任何事件上** —— 见上面那条 🔴。 */
  const arm = (ms) => setTimeout(finish, ms);
  v.addEventListener('loadedmetadata', () => {
    const d = (isFinite(v.duration) && v.duration > 0) ? v.duration : 15.1;
    arm(d * 1000 + 1400);
  });
  arm(20000);

  /* 自动播放被拒（真浏览器里"静音"这条路一般是放行的，但别赌）：
     不抛出去、也不收掉片头 —— 跳过按钮还在，人仍然出得去。 */
  const p = v.play();
  if (p && p.catch) p.catch(() => { /* 交给上面那条 20 s 硬收 */ });
})();
