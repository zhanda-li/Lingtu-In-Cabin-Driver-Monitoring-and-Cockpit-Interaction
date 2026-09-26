/* =========================================================================
   live.js —— 04 ~ 10 这几页共用的运行时
   -------------------------------------------------------------------------
   三件事：

   1. **一条 WebSocket**。图表页要的是"连上、收 state、画出来"，四页一模一样，
      何必各写一遍。没连上时**不装作有数据**：`XQ.online` 是 false，页面据此
      显示「—」和一句实话。

   2. **客户端历史缓冲** `XQ.Hist`。服务端只推"当前这一拍"，趋势图要的是过去
      N 分钟的序列，所以这里自己攒。⚠️ 攒的是**本次页面打开之后**的时间，不是
      "近 1 小时"—— 页面刚打开 20 秒就只画得出 20 秒。图上写清楚已记录多久，
      免得看的人以为是"一小时里就这么点波动"。

   3. **图表原语** `XQ.plot()`。折线 / 网格 / 刻度 / 「当前」气泡。
      刻度字走 HTML（见 pages.css 里 .plot 的注释：SVG 被拉伸会把字压扁）。

   还有 `XQ.esc()`：小瑞说的话来自模型，进 DOM 前必须转义。
   ========================================================================= */
'use strict';

/* `var`，不是 `const` —— 理由同 chrome.js 开头那段注释：两个普通脚本的顶层
   `const` 会撞在一起，第二份直接抛重复声明、整页白屏。 */
var XQ = (window.XQ = window.XQ || {});

/* ---------------------------------------------------------------- 图标 */
/* 全站一张表。app.js（座舱主界面）也用这一份，别再抄第二遍。 */
XQ.ICON = {
  music: '<path d="M9 18V6.5l10-2v11" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><circle cx="6.5" cy="18" r="2.6" fill="none" stroke="currentColor" stroke-width="1.8"/><circle cx="16.5" cy="15.5" r="2.6" fill="none" stroke="currentColor" stroke-width="1.8"/>',
  rest_stop: '<path d="M21 3 3.4 10.4l7 2.2 2.2 7z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>',
  nearby: '<path d="M12 21s7-5.6 7-11a7 7 0 1 0-14 0c0 5.4 7 11 7 11z" fill="none" stroke="currentColor" stroke-width="1.8"/><circle cx="12" cy="10" r="2.6" fill="none" stroke="currentColor" stroke-width="1.8"/>',
  status: '<path d="M2.5 12S6 5.6 12 5.6 21.5 12 21.5 12 18 18.4 12 18.4 2.5 12 2.5 12z" fill="none" stroke="currentColor" stroke-width="1.8"/><circle cx="12" cy="12" r="3.1" fill="none" stroke="currentColor" stroke-width="1.8"/>',
  snooze: '<circle cx="12" cy="12" r="8.4" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M12 7.4v5l3.2 2" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>',
  eye: '<path d="M2.5 12S6 5.6 12 5.6 21.5 12 21.5 12 18 18.4 12 18.4 2.5 12 2.5 12z" fill="none" stroke="currentColor" stroke-width="1.7"/><circle cx="12" cy="12" r="2.8" fill="none" stroke="currentColor" stroke-width="1.7"/>',
  alert: '<path d="M12 3.6 21 19.4H3z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><path d="M12 9.4v4.2" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/><circle cx="12" cy="16.6" r=".9" fill="currentColor"/>',
  heart: '<path d="M12 20s-7.5-4.7-7.5-9.6A4.4 4.4 0 0 1 12 7.7a4.4 4.4 0 0 1 7.5 2.7C19.5 15.3 12 20 12 20z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>',
  chev: '<path d="M9 5.5 15.5 12 9 18.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
  chevL: '<path d="M15 5.5 8.5 12 15 18.5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
  sparkle: '<path d="M12 3.5 13.9 9 19.5 11l-5.6 2L12 18.5 10.1 13 4.5 11 10.1 9z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>',
  play: '<path d="M7.5 5.2 18.5 12 7.5 18.8z" fill="currentColor"/>',
  pause: '<rect x="7" y="5.2" width="3.4" height="13.6" rx="1.2" fill="currentColor"/><rect x="13.6" y="5.2" width="3.4" height="13.6" rx="1.2" fill="currentColor"/>',
  prev: '<path d="M18 5.4v13.2L8.6 12z" fill="currentColor"/><rect x="5" y="5.4" width="2.2" height="13.2" rx="1" fill="currentColor"/>',
  next: '<path d="M6 5.4v13.2L15.4 12z" fill="currentColor"/><rect x="16.8" y="5.4" width="2.2" height="13.2" rx="1" fill="currentColor"/>',
  mic: '<rect x="9" y="3.2" width="6" height="10.4" rx="3" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M5.6 11.4a6.4 6.4 0 0 0 12.8 0M12 17.8V21" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>',
  send: '<path d="M3.6 11.4 20.6 3.6l-7.8 17-2.2-6.8z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>',
  car: '<path d="M3 14.2 5.2 7h13.6L21 14.2v3.6h-2.4M5.4 17.8H3v-3.6" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><circle cx="7.4" cy="17.9" r="1.7" fill="none" stroke="currentColor" stroke-width="1.6"/><circle cx="16.6" cy="17.9" r="1.7" fill="none" stroke="currentColor" stroke-width="1.6"/>',
  phone: '<rect x="6.4" y="2.6" width="11.2" height="18.8" rx="2.4" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M10.4 5.4h3.2" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><circle cx="12" cy="18.2" r="1" fill="currentColor"/>',
  watch: '<rect x="7" y="6.6" width="10" height="10.8" rx="2.6" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M9.4 6.6 9.9 3h4.2l.5 3.6M9.4 17.4 9.9 21h4.2l.5-3.6" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>',
  cloud: '<path d="M7.4 18.4h8.8a4 4 0 0 0 .6-7.96A5.6 5.6 0 0 0 6.3 9.8 4.6 4.6 0 0 0 7.4 18.4z" fill="none" stroke="currentColor" stroke-width="1.6"/>',
  wave: '<path d="M2 12h3l2-6 3 12 3-9 2.4 5.4L17 12h5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>',
  clock: '<circle cx="12" cy="12" r="8.6" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M12 7v5.4l3.4 2" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
  list: '<path d="M4 6.5h16M4 12h16M4 17.5h10" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>',
  shield: '<path d="M12 3.2 19.4 6v6c0 4.2-3.1 7.4-7.4 8.8C7.7 19.4 4.6 16.2 4.6 12V6z" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/><path d="M9 12.2l2.2 2.2 4-4.4" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>',
  brain: '<path d="M12 5.2a3 3 0 0 0-5.6-1.3A2.9 2.9 0 0 0 4.6 9.4 3.1 3.1 0 0 0 6.4 15a3 3 0 0 0 5.6-1.4z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="M12 5.2a3 3 0 0 1 5.6-1.3A2.9 2.9 0 0 1 19.4 9.4 3.1 3.1 0 0 1 17.6 15a3 3 0 0 1-5.6-1.4z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="M12 5.2v13.6" stroke="currentColor" stroke-width="1.5"/>',
  info: '<circle cx="12" cy="12" r="8.6" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M12 11v5.4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/><circle cx="12" cy="8" r="1" fill="currentColor"/>',
  /* 喇叭两个：出声 / 静音。**全站只有这一份** —— 早先 chat.html 因为这张表里
     没有喇叭，自己就地画了一个常量，现在那个删了改用这里。 */
  speaker: '<path d="M4 9.6h3.2L12 5.6v12.8L7.2 14.4H4z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><path d="M15.2 9.2a4 4 0 0 1 0 5.6M17.7 6.8a7.4 7.4 0 0 1 0 10.4" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>',
  speakerOff: '<path d="M4 9.6h3.2L12 5.6v12.8L7.2 14.4H4z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><path d="M15.4 9.8l5 4.4M20.4 9.8l-5 4.4" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>',
  /* ★ 2026-09-25：下面 8 个是给**设置页重做**补的（照 `ui/图片效果/设置.png`
     那张四栏参考图 —— 参考图每一行前面都有一枚圆角小图标，缺了就只能是
     一排光字）。风格照上面那份：24 视框、`stroke-width` 1.6~1.7、
     描边不填充（实心的点用 `fill="currentColor"` 的小圆，和 `info`/`alert` 一致）。
     ⚠️ `gear` 这一枚**和 `chrome.js` 左导航「设置」那枚是同一个图形**（那边是
        内联在 RAIL 表里的，搬不过来）。两处都改的时候记得对一下，
        不然左栏和页标题上会是两个不一样的齿轮。 */
  gear: '<circle cx="12" cy="12" r="3.2" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M12 2.6l1.4 2.6 2.9-.6.6 2.9 2.6 1.4-1.6 2.5 1.6 2.5-2.6 1.4-.6 2.9-2.9-.6L12 21.4l-1.4-2.6-2.9.6-.6-2.9L4.5 15l1.6-2.5L4.5 10l2.6-1.4.6-2.9 2.9.6z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>',
  edit: '<path d="M4 20.2h16" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/><path d="M15.4 4.4l4.2 4.2L9.4 18.8H5.2v-4.2z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>',
  user: '<circle cx="12" cy="8.3" r="4" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M4.5 20.4a7.5 7.5 0 0 1 15 0" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>',
  display: '<rect x="2.8" y="4.2" width="18.4" height="12.4" rx="2.2" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M9 20.4h6M12 16.6v3.8" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>',
  sun: '<circle cx="12" cy="12" r="4.1" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M12 2.6v2.5M12 18.9v2.5M2.6 12h2.5M18.9 12h2.5M5.5 5.5l1.8 1.8M16.7 16.7l1.8 1.8M18.5 5.5l-1.8 1.8M7.3 16.7l-1.8 1.8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>',
  globe: '<circle cx="12" cy="12" r="8.6" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M3.6 12h16.8" stroke="currentColor" stroke-width="1.7"/><path d="M12 3.4c2.3 2.6 3.5 5.4 3.5 8.6S14.3 18 12 20.6c-2.3-2.6-3.5-5.4-3.5-8.6S9.7 6 12 3.4z" fill="none" stroke="currentColor" stroke-width="1.7"/>',
  grid: '<rect x="3.4" y="3.4" width="7.4" height="7.4" rx="1.8" fill="none" stroke="currentColor" stroke-width="1.7"/><rect x="13.2" y="3.4" width="7.4" height="7.4" rx="1.8" fill="none" stroke="currentColor" stroke-width="1.7"/><rect x="3.4" y="13.2" width="7.4" height="7.4" rx="1.8" fill="none" stroke="currentColor" stroke-width="1.7"/><rect x="13.2" y="13.2" width="7.4" height="7.4" rx="1.8" fill="none" stroke="currentColor" stroke-width="1.7"/>',
  bell: '<path d="M12 3.2a5.6 5.6 0 0 0-5.6 5.6c0 4.2-1.4 5.4-1.4 5.4h14s-1.4-1.2-1.4-5.4A5.6 5.6 0 0 0 12 3.2z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/><path d="M10.2 17.6a1.9 1.9 0 0 0 3.6 0" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>',
  /* ★ 2026-09-25：导航页的**搜目的地**输入框要一枚放大镜。这张表是全站图标的
     唯一来源（页面里就地画一个的话，改一处就得改两处），所以补在这儿。
     ⚠️ 表里没有的名字**不报错**，`XQ.icon()` 会静默退成 `info`（一个"i"）——
        所以在页面上看到"i"就说明名字写错了。 */
  search: '<circle cx="10.8" cy="10.8" r="6.6" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M15.6 15.6 20.4 20.4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>',
};

/* ---------------------------------------------------------------- 杂项 */
XQ.esc = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

/** null/undefined/NaN 一律给「—」。**不要给 0** —— 那是在编数。 */
XQ.num = (v, d = 0, unit = '') => (v == null || Number.isNaN(v))
  ? '—' : v.toFixed(d) + unit;

XQ.isFile = () => location.protocol === 'file:';

XQ.icon = (name, cls = '') =>
  `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true">${XQ.ICON[name] || XQ.ICON.info}</svg>`;

let toastTimer = null;

/* ---------------------------------------------------------------- 本机偏好 */
/* ★ 2026-09-25：设置页「通知与提醒」那三个开关里，有两个住在这里
   （第三个是「语音播报」，它就是 `XQ.tts.on`，早就有自己的 LS 键）。
   **必须放在 live.js，不能放在 settings.html 自己的 <script> 里** ——
   偏好是**跨页**的：设置页只负责写，真正照做的是每一页的渲染代码
   （横幅在这份文件的 `XQ.alarms.render`、提示条在下面几行的 `XQ.flash`）。
   写在页面里就成了"按了在别的页面上没反应"的假开关。

   ⚠️ **两个都默认开**（`localStorage` 里没有这个键 = 开）。默认值一改，
      全站现有截图和检查脚本的行为就跟着变 —— 要改默认值得当成一次改版做。
   ⚠️ `localStorage` 被禁用时（无痕 / kiosk 里某些策略）**一律当作开**：
      读不出来就把功能关掉，只会让现场表现和代码不一样，而这里读不到并不是
      "用户想要关掉"。 */
XQ.prefs = {
  KEY: { banner: 'xq.alarm.banner', toast: 'xq.ui.toast' },
  get(k) {
    try {
      const v = localStorage.getItem(this.KEY[k]);
      return v === null ? true : v === '1';
    } catch (e) { return true; }
  },
  set(k, on) {
    try { localStorage.setItem(this.KEY[k], on ? '1' : '0'); } catch (e) {}
  },
};

XQ.flash = function (text) {
  const t = document.getElementById('toast');
  if (!t) return;
  if (!XQ.prefs.get('toast')) return;          // 「提示条」关掉了：只写不弹
  t.textContent = text;
  t.classList.add('on');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('on'), 2800);
};

/* ---------------------------------------------------------------- 共用图形 */
/* 驾驶员示意头像。**座舱主界面和 04 详情页共用这一份** —— 两份的话哪天改了
   一个 id 另一处就静默不动了。id 与 app.js / detail.html 里的渲染代码一一对应：
   #driver（头姿） #eyeL/#eyeR（开合） #irisL/#irisR #mouth（MAR/哈欠）
   #mesh（定位点） #facebox #scanline。
   这是**示意画面**，不是摄像头视频、也不是 478 点真 FaceMesh，页面上要写明。
   ★ 2026-09-25：五官那一层（`.st-face`）和 `#driver` 剪影**该不画人时整层淡出**，
     配合 detail.html 的 `#noFace` 浮层，判据在 live.js 里只写一处（`HEAD_MODE`）。
   ⚠️ **这张脸现在实际上画不出来了**，别当成 bug 去找：`detail.html` 的 `onHello`
     里，`d.source === 'cam'` 才 `headMode('auto')`，而**同一支**又会把 `#stageHost`
     整个 `hidden` 掉 —— 其余源一律 `headMode('none')`（用户 2026-09-25 拍板
     「永远不画人，只留等待卡」，同一天又补了「只要接入摄像头后 就不要再出现
     没人像的那个了」）。所以"看得见 + auto"这两个条件凑不到一起。
     留着它是因为它是这一格最后的兜底，删掉等于把 `XQ.headPose` / `XQ.buildMesh`
     一起废掉；真要删，`#mesh` 那条"每帧都在写"的注释也要一起处理。 */
XQ.headSVG = () => `
  <svg class="stage-svg" viewBox="0 0 660 520" preserveAspectRatio="xMidYMid slice" aria-label="驾驶员示意画面">
    <defs>
      <linearGradient id="gCabin" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#0d1a24"/><stop offset="100%" stop-color="#060d14"/>
      </linearGradient>
      <linearGradient id="gSky" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#22333f"/><stop offset="55%" stop-color="#16232e"/><stop offset="100%" stop-color="#0c1620"/>
      </linearGradient>
      <linearGradient id="gSkin" x1="0.2" y1="0" x2="0.8" y2="1">
        <stop offset="0%" stop-color="#40606f"/><stop offset="58%" stop-color="#2a4453"/><stop offset="100%" stop-color="#1b2c37"/>
      </linearGradient>
      <linearGradient id="gSeat" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#1d2c38"/><stop offset="100%" stop-color="#0e1822"/>
      </linearGradient>
      <linearGradient id="gRim" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0%" stop-color="var(--accent)" stop-opacity=".85"/>
        <stop offset="100%" stop-color="var(--accent)" stop-opacity="0"/>
      </linearGradient>
      <radialGradient id="gVig" cx="50%" cy="44%" r="74%">
        <stop offset="58%" stop-color="#000" stop-opacity="0"/>
        <stop offset="100%" stop-color="#000" stop-opacity=".52"/>
      </radialGradient>
    </defs>

    <rect width="660" height="520" fill="url(#gCabin)"/>

    <!-- 车窗外：两块侧窗 + B 柱 + 远山。**压得比人物暗**，否则会抢主体 -->
    <g class="outside" opacity=".85">
      <rect x="18" y="30" width="176" height="242" rx="16" fill="url(#gSky)"/>
      <rect x="466" y="30" width="176" height="242" rx="16" fill="url(#gSky)"/>
      <path d="M18 202 L70 170 L120 198 L176 162 L194 178 L194 272 L18 272Z" fill="#101c26" opacity=".9"/>
      <path d="M466 170 L520 192 L566 160 L642 198 L642 272 L466 272Z" fill="#101c26" opacity=".9"/>
      <rect x="188" y="22" width="14" height="262" rx="4" fill="#080f16"/>
      <rect x="458" y="22" width="14" height="262" rx="4" fill="#080f16"/>
    </g>

    <path d="M112 520 C114 372 168 316 250 310 L416 310 C498 316 552 372 554 520 Z" fill="url(#gSeat)"/>

    <!-- ======== 下面这一组被真实数据驱动 ======== -->
    <g id="driver">
      <path d="M70 520 C82 428 160 396 330 396 C500 396 578 428 590 520 Z" fill="#17242e"/>
      <path d="M294 296 h72 v112 q-36 20 -72 0 z" fill="#203440"/>
      <ellipse cx="330" cy="248" rx="76" ry="92" fill="url(#gSkin)"/>
      <path d="M330 156 A76 92 0 0 0 256 248" fill="none" stroke="url(#gRim)" stroke-width="3.4" stroke-linecap="round" opacity=".85"/>
      <ellipse cx="256" cy="256" rx="9" ry="15" fill="#2b4351"/>
      <ellipse cx="404" cy="256" rx="9" ry="15" fill="#2b4351"/>
      <path d="M254 232 C250 162 286 128 330 128 C374 128 410 162 406 232 C394 194 370 174 330 174 C290 174 266 194 254 232 Z" fill="#0f1b24"/>

      <!-- ===== 这一层**只在真的拿到人脸数据时**才显示 =====
           （选择器 #stageHost[data-face="none"] 那一条，判据在 XQ.headPose）
           2026-09-25 用户报「没人脸的时候那个画面太丑了」。丑的具体形态就是这一层：
           一帧人脸都没识别到，画面上却瞪着一双睁着的眼睛、抿着/张着的嘴、一脸定位点，
           外加一对粗眉毛和一根鼻梁线 —— 看起来像"正在识别一张脸"，**实际上什么都没识别到**。
           那是这一格最假的地方，也是它像一张画歪的卡通头像的原因。
           处理：眉毛和鼻梁线整条删掉（最像卡通的两笔），五官收小、颜色压暗；
           然后把整个"识别态"收进这**一个 g**，没人脸时整层淡出，
           只剩一个安静的剪影 + 外面那块「未检测到人脸」浮层（见 detail.html 的 #noFace）。
           ⚠️ 零件 id 一个都没改（XQ.headPose / XQ.buildMesh 全靠它们），
              只是外面多包了一层。
           ⚠️ **这段里不许出现反引号** —— 整个 SVG 是一个模板字符串，
              注释里的反引号会把模板当场截断（这个坑 chrome.js 里已经踩过一次）。 -->
      <g class="st-face">
        <g id="mesh"></g>
        <ellipse id="eyeL" cx="306" cy="244" rx="13" ry="8"/>
        <ellipse id="eyeR" cx="354" cy="244" rx="13" ry="8"/>
        <circle id="irisL" cx="306" cy="244" r="4.2" opacity=".5"/>
        <circle id="irisR" cx="354" cy="244" r="4.2" opacity=".5"/>
        <ellipse id="mouth" cx="330" cy="304" rx="14" ry="4.5"/>

        <g id="facebox" fill="none" stroke="var(--accent)" stroke-width="3" stroke-linecap="round">
          <path d="M250 178 v-26 h26"/>
          <path d="M410 178 v-26 h-26"/>
          <path d="M250 318 v26 h26"/>
          <path d="M410 318 v26 h-26"/>
        </g>
        <line id="scanline" x1="250" y1="152" x2="410" y2="152"/>
      </g>
    </g>

    <rect width="660" height="520" fill="url(#gVig)"/>
  </svg>`;

/* FaceMesh 那一层：**沿脸部轮廓**铺的定位点 + 三条轮廓线。
   之前是"在椭圆里铺同心圆"，结果像一脸麻子 —— 关键点是贴轮廓，不是均匀撒。
   位置写死，不冒充 MediaPipe 的 478 点。
   ★ 第六次改版从 app.js 搬到这里：驾驶监测页那张画面卡用的也是 `XQ.headSVG()`，
     各存一份的下场很具体 —— 改了一处坐标，另一页的网格会**静默变成空的**
     （`g.innerHTML = ''` 之后没填，不报错，只是脸上没有点）。 */
XQ.buildMesh = function (hostId) {
  const g = document.getElementById(hostId || 'mesh');
  if (!g) return;
  let s = '';

  /* 轮廓线：下颌 / 颧骨 / 额头 */
  s += '<path d="M258 250 Q268 322 330 338 Q392 322 402 250"/>';
  s += '<path d="M266 268 Q300 300 330 302 Q360 300 394 268"/>';
  s += '<path d="M262 196 Q330 162 398 196"/>';

  const dot = (x, y) => { s += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="1.5"/>`; };

  /* 下颌弧：左半边 7 点，右半边镜像 */
  for (let i = 0; i <= 7; i++) {
    const t = i / 7, u = 1 - t;
    const x = u * u * 258 + 2 * u * t * 268 + t * t * 330;
    const y = u * u * 250 + 2 * u * t * 322 + t * t * 338;
    dot(x, y);
    if (i) dot(660 - x, y);
  }
  /* 额头 + 眼角 + 鼻梁 */
  for (let i = 0; i <= 6; i++) {
    const x = 262 + (398 - 262) * (i / 6);
    dot(x, 196 - 30 * Math.sin(Math.PI * (i / 6)));
  }
  [222, 240, 258].forEach((y) => dot(330, y));
  [[284, 240], [376, 240], [286, 290], [374, 290], [308, 222], [352, 222]].forEach(([x, y]) => dot(x, y));

  g.innerHTML = s;
};

/* 「这一格要不要画人 / 要不要出等待卡」**只有一道判据**：`HEAD_MODE` ——
   这一页**有没有摄像头**。`detail.html` 的 `onHello` 按 `d.source` 调
   `XQ.headMode('none' | 'auto')`，那是全站唯一的写入点。

   ★ 这一整块的形状是用户 2026-09-25 两句话定下来的，两句都要留着读：
     · 「没有实时接人脸摄像头」+ 拍板「永远不画人，只留等待卡」
       → 没摄像头时那张示意头像**一次都不画**，只出等待卡；
     · 「只要接入摄像头后 就不要再出现 没人像的那个了」
       → 接了摄像头就**再也不出**那块等待卡：那一格里放的就是真实视频，
         视频里有没有人脸是视频自己的事，空镜也照样是真实视频。
         给它盖一块写着"未检测到人脸"的浮层，遮的是**画面**而不是假数据。

   ⚠️ 这里**曾经**还有第二道判据：看这一帧有没有面部数据（`ear`/`mar`/`pitch`
      三个原始量全缺则算没人，带 6 帧迟滞）。上面第二句话把它整个废掉了，
      所以删干净，别留着当"以后可能有用" —— 留着就会有人照着它把浮层加回来。
   ⚠️ 也**不要**改回"没数据就出等待卡"：`ui/sources.py` 的 `DemoSource`
      **自己造** `ear`/`mar`/`en_now`，所以"有没有数据"在 demo 源下恒为真；
      而这一页真正需要区分的从来是"有没有摄像头"——只有这一条是页面知道的事实。 */
/* ★ 2026-09-25 深夜：初值从 `'auto'` 改成 `'none'`，**这一改修的是一个看得见的闪烁**。
   用户报：「未接摄像头时候 从其他界面换到驾驶监测界面……现在不是直接显示我的
   背景图 而是从灰变成我的背景图」。

   事故链（三处各写了一半，缺一处这个闪就不会有）：
     1. `detail.html` 的 HTML 初值是 `data-face="none"` —— 页面第一帧是**对的**；
     2. 可 `live.js` 加载时 `HEAD_MODE = 'auto'`，而 `headPose()` 每帧都算
        `HEAD_BLANK = HEAD_MODE === 'none'`。**`onState` 比 `onHello` 先到**，
        于是还没等到 hello，就先按 `'auto'` 写了 `data-face="ok"` —— 那张
        画出来的暗色座舱**自己冒出来了**；
     3. `onHello` 到了才 `headMode('none')` 把它按回去。
   净效果就是"灰座舱 -> 背景图"。改 `'none'` 之后，JS 的初值和 HTML 的初值
   **指向同一件事**（没收到 hello 之前就是"没摄像头"），这本来也是那一段注释
   写明的原则：「页面刚打开、还没收到 hello 时，"没摄像头"是诚实的默认态」。

   ⚠️ 别改回 `'auto'` 以求"有摄像头时先画上"：cam 源下 `#stageHost` 会被
      `hidden`（detail.html:779），先画也没人看得见，只会换来上面那个闪。
   ⚠️ 这条必须和 `style.css` 里 `.stage-svg` **不写 `transition`** 那条一起读：
      两处都改掉才是"直接显示背景图"；只改一处，另一个还会闪一下。 */
let HEAD_MODE = 'none';
let HEAD_BLANK = true;       // 最近一次算出来的结果，headPose 每帧刷新它

/* 等待卡副标题。**只剩一种情况能看见这块浮层**（没接摄像头），所以只剩一句
   固定文案，而且是写在 `detail.html` 的 HTML 里的 —— 这里不再改它的 DOM。
   （早先那句「请正对摄像头 · 保持面部在画面内」随"接了摄像头也出浮层"一起没了；
   对着一台没接摄像头的机器说"请正对摄像头"本来就是句废话。） */

function headApply() {
  const host = document.getElementById('stageHost');
  if (host) host.dataset.face = HEAD_BLANK ? 'none' : 'ok';
  const nf = document.getElementById('noFace');
  if (nf) nf.hidden = !HEAD_BLANK;
}

/* 页面级开关。`'none'` = 没摄像头：永远不画人 + 出等待卡；
                 `'auto'` = 有摄像头：不出等待卡，那一格就是真实视频。 */
XQ.headMode = function (mode) {
  HEAD_MODE = mode === 'none' ? 'none' : 'auto';
  HEAD_BLANK = HEAD_MODE === 'none';
  headApply();
};

/* 把 state 画到那张示意头像上（头姿 / 眼开合 / 嘴）。
   ★ 第六次改版从 app.js 搬到这里 —— 总览页和驾驶监测页各有一张 `XQ.headSVG()`，
     两份的话「头部姿态」这一项会有一页不动。
   @param yawnS 已经过 `XQ.yawnShown` 锁存的哈欠秒数（嘴读它，不读原始 `s.yawn_sec`）。 */
XQ.headPose = function (s, yawnS) {
  const g = (id) => document.getElementById(id);

  /* ---------------------------------------------------- 这一格要不要画人 */
  /* ★ 判据就是 `HEAD_MODE` 那一个，**不在这一帧里算任何东西** —— 完整理由
     （用户那两句话、以及为什么"这一帧有没有人脸数据"不能当判据）写在上面
     `HEAD_MODE` 那一段里。这里调一次 `headApply()` 只是让它在 state 到的时候
     也跟着刷一遍（`headMode()` 已经刷过一次了，重复写同一份 DOM 是幂等的）。 */
  HEAD_BLANK = HEAD_MODE === 'none';
  headApply();

  /* 头部姿态**直接用服务端判好的 `attention`**（`ui/state.py` 的 `derive()`），
     这里不再自己算一份 —— 判据只留一处，两处各算一份必然有一天说出两种话
     （「头部姿态」那一行和底部小字的「注意力 …」在**同一张卡**里）。
     ⚠️ `l1` 也不行：`CLASS_LEVEL` 把非正常类落 3，"低头"和"点头"在级别上是同一个数。
     ⚠️ **绝对 pitch 不能设阈值**：每个人有自己的头部基线（实测 session1 中位 7.5°、
       session2 中位 7.0°），按绝对角判必然误判 —— 这个坑本项目踩过。 */
  const attention = s.attention || '专注';
  const HEAD = attention === '疲劳点头' ? [0, 7, 2]
             : (attention === '头部持续低垂' ? [0, 14, 5] : [0, 0, 0]);
  const drv = g('driver');
  if (drv) drv.setAttribute('transform',
    `translate(${HEAD[0]}, ${HEAD[1]}) rotate(${HEAD[2]} 330 248)`);

  /* 眼睛开合：用服务端判好的 `s.eyes`（阈值是 BLINK_THR 0.80，标定过的），
     具体开多大再拿 en_now 微调一点，免得看起来只有全开/全闭两档。 */
  const en = s.en_now == null ? 1.0 : s.en_now;
  const q = Math.min(1, Math.max(0, (en - 0.80) / 0.20));
  const ry = s.eyes === 'closed' ? 1.6 : (6.6 + 1.7 * q).toFixed(2);
  ['eyeL', 'eyeR'].forEach((id) => { const e = g(id); if (e) e.setAttribute('ry', ry); });
  const io = s.eyes === 'closed' ? 0.10 : 0.5;
  ['irisL', 'irisR'].forEach((id) => { const e = g(id); if (e) e.setAttribute('opacity', io); });

  /* ⚠️ 嘴用**锁存后**的 `yawnS`，不用原始 `s.yawn_sec`（2026-09-25）：
     原始值是 27 秒窗内的平台，打完哈欠嘴还会张着二十几秒。
     嘴同时仍跟着原始 `mar`（那是**此刻**的张嘴程度，没有平台问题）。 */
  const mar = s.mar == null ? 0.12 : s.mar;
  const mr = Math.min(15, Math.max(3, 2.5 + mar * 22 + (yawnS || 0) * 0.9)).toFixed(1);
  const mo = g('mouth');
  if (mo) mo.setAttribute('ry', mr);
};

/* 哈欠秒数的**显示锁存**：判据（`yawn_sec`）是 27 秒窗内的平台，打完哈欠
   那个数还会在高位挂二十几秒 —— 直接显示的话，"哈欠时长"这一格会一直有数。
   这里只在**它涨的那一刻**起算，之后最多显示 `hold_sec` 秒就归 0。
   ⚠️ 只动**显示**。`ui/state.py` 的判据（severity / alarms）照样按原始 `yawn_sec`
      走 —— 「打哈欠就是轻度疲劳」是口径，不是显示 bug。
   ⚠️ 已知边角：`yawn_sec` 取的是窗内**最大**，所以「紧跟着一个更长的哈欠、又来
      一个更短的（更长的那个还在 27 秒窗里）」时，新哈欠不会让这个数上涨 →
      数字显示 0（横幅和大标题仍照 `yawn_sec` 报，屏幕不会整个哑掉）。
   ⚠️ **每帧只能推进一次**：同一个 state 上多处读到它又各调一次的话，锁存会被推两次，
     "涨的那一刻"当场被消耗掉，数字永远是 0。调用方拿到一次就传下去（见 XQ.headPose）。 */
const YAWN_L = { last: 0, grewAt: -1e9 };
XQ.yawnShown = function (v) {
  if (v == null) return null;
  const now = performance.now();
  if (v > YAWN_L.last + 1e-9) {
    YAWN_L.last = v;
    YAWN_L.grewAt = now;
  } else if (v < YAWN_L.last - 1e-9) {
    YAWN_L.last = v;
  }
  const hold = (XQ.alarms && XQ.alarms.holdSec > 0 ? XQ.alarms.holdSec : 3) * 1000;
  return (now - YAWN_L.grewAt) <= hold ? YAWN_L.last : 0;
};

/* 小瑞的内置形象（**占位**，早期画的矢量版）。`assets/xiaorui_*.png` 探到了
   就用真图盖掉它 —— 真图才是用户自己的原创角色（源图 ui/图片效果/10.png，
   抠图脚本 _scratch/_mk_xiaorui.py）。这套 SVG 保留的**唯一**价值是兜底：
   图没生成、路径写错、或者单独打开某一个 html 时，页面不至于空一块。 */
XQ.mascotSVG = ({ simple = false } = {}) => simple ? `
  <svg class="mascot-svg sm" viewBox="0 0 160 170" aria-hidden="true">
    <rect x="30" y="34" width="100" height="94" rx="44" fill="#dceaf5"/>
    <rect x="44" y="56" width="72" height="46" rx="24" fill="#0e1d29"/>
    <ellipse cx="66" cy="78" rx="8.4" ry="9.6" fill="#eafcff"/>
    <ellipse cx="94" cy="78" rx="8.4" ry="9.6" fill="#eafcff"/>
    <circle cx="66" cy="78" r="4.6" fill="var(--accent)"/>
    <circle cx="94" cy="78" r="4.6" fill="var(--accent)"/>
    <path d="M72 92 q8 6 16 0" fill="none" stroke="#eafcff" stroke-width="2.6" stroke-linecap="round"/>
  </svg>` : `
  <svg class="mascot-svg" viewBox="0 0 160 170" aria-hidden="true">
    <defs>
      <linearGradient id="gShell" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stop-color="#ffffff"/><stop offset="55%" stop-color="#dceaf5"/><stop offset="100%" stop-color="#9fc2da"/>
      </linearGradient>
      <linearGradient id="gVisor" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#16283a"/><stop offset="100%" stop-color="#0a1620"/>
      </linearGradient>
      <radialGradient id="gGlow" cx="50%" cy="50%" r="50%">
        <stop offset="0%" stop-color="var(--accent)" stop-opacity=".55"/>
        <stop offset="100%" stop-color="var(--accent)" stop-opacity="0"/>
      </radialGradient>
    </defs>
    <circle cx="80" cy="82" r="78" fill="url(#gGlow)"/>
    <path d="M80 24 v-11" stroke="#cfe2ef" stroke-width="4" stroke-linecap="round"/>
    <circle cx="80" cy="10" r="6.5" fill="var(--accent)"/>
    <path d="M46 132 q0 -18 34 -18 t34 18 q0 22 -34 22 t-34 -22z" fill="url(#gShell)" opacity=".95"/>
    <circle cx="80" cy="140" r="9" fill="var(--accent)" opacity=".85"/>
    <circle cx="25" cy="86" r="12.5" fill="#cfe2ef"/>
    <circle cx="135" cy="86" r="12.5" fill="#cfe2ef"/>
    <circle cx="25" cy="86" r="5.5" fill="var(--accent)" opacity=".9"/>
    <circle cx="135" cy="86" r="5.5" fill="var(--accent)" opacity=".9"/>
    <rect x="30" y="34" width="100" height="94" rx="44" fill="url(#gShell)"/>
    <rect class="visor" x="44" y="56" width="72" height="46" rx="24" fill="url(#gVisor)"/>
    <g class="m-face">
      <ellipse class="mascot-eye" cx="66" cy="78" rx="8.4" ry="9.6" fill="#eafcff"/>
      <ellipse class="mascot-eye" cx="94" cy="78" rx="8.4" ry="9.6" fill="#eafcff"/>
      <circle cx="66" cy="78" r="4.6" fill="var(--accent)"/>
      <circle cx="94" cy="78" r="4.6" fill="var(--accent)"/>
      <path class="mascot-mouth" d="M72 92 q8 6 16 0" fill="none" stroke="#eafcff" stroke-width="2.6" stroke-linecap="round"/>
    </g>
  </svg>`;

/* ------------------------------------------------- 小瑞的形象库（43 张） */
/**
 * ★ 2026-09-25（第十次改版）：用户原话「左下那个应该小瑞图片能变化的太少了
 * 我不是有 40 多张图片吗 把那些出现小瑞的地方都变成可以变化的 并且形象要多一些」。
 * 这一块就是那 43 张，加上"点一下换一个形象"的**公共**机制 —— 全站 10 个
 * 小瑞槽都走下面那一个 `XQ.poseDeck`，口径写一处。
 *
 * 素材：用户给的 `ui/图片效果/微信图片_*.png` 43 张，出图脚本
 * `_scratch/_mk_xq_poses.py`。它干的三件事，这里**逐条对齐**、别改单边：
 *   · 按**身高**归一化（43 张的脚都踩在画框底、头顶都落在 0.995 以上）；
 *   · 水平按 **alpha 包围盒中心**对齐 —— 实测残差 0.55 px；另一个候选
 *     「躯干质心」是 4.2 px，因为原画是三分之四侧身，躯干质心跟着不对称的
 *     轮廓跑，**已否**（`_mk_xq_poses.py` 的 `torso_cx()` 里记着这件事）；
 *   · 补到同一张画布上，出 l / s / h 三套。
 * ⚠️ `p01..p43` 就是**文件名的排序**，和脚本产出的文件名一一对应。要删中间
 *    某一张必须**重跑脚本**（它按文件名重新编号），不能只手删一个文件 ——
 *    那样后面每一张都会往前串一位，点出来的人全错位。
 * ⚠️ 43 张不是矢量图，是微信下载的 PNG（有 JPEG 振铃），画质已经压到不肉眼的
 *    下限，**别再降 q**：`_mk_xq_poses.py` 的注释里有量化证据（263 万不透明
 *    像素里 35.8 万种颜色、laplacian 均值 3.12）。
 *
 * 三套尺寸各管一段，选错不是"糊一点"而是**不可用**：
 *   · `s` 210x288  —— 座舱里的立绘位（首页 6.6rem、chat 8rem、左栏 13.4rem）
 *   · `l` 730x1000 —— 封面的立绘位（44x46rem，DPR=2 也扛得住）
 *   · `h` 192x192  —— **方形头像位**（对话栏、手机页四个 hero、设置页两处、
 *                     聊天气泡 2.3rem）。方槽必须用这一套：全身立绘塞进 33 px
 *                     的圆里，脸只剩几个像素，认不出是谁。
 *
 * ⚠️ **不预加载。** `/static/` 和 `/assets/` 都带 `no-store`（server.py 的
 *    `no_store` 中间件），"预取一批放缓存里"在这套服务器上**根本不成立** ——
 *    每次给 src 赋值都会真的重新下载。所以口径是"**点一下才下这一张**"：
 *    43 张里只有真被点到的那些会走网络。单张：s 约 32 KB / h 约 23 KB /
 *    l 约 220 KB。
 */
XQ.POSES = (function () {
  const a = [];
  for (let i = 1; i <= 43; i++) a.push('p' + (i < 10 ? '0' : '') + i);
  return a;
})();
/* 三套的**高度**（和 `_mk_xq_poses.py` 的 SIZES / HEAD_OUT 是同一组数）。
   这里只用来校验调用点传的尺寸名，不当几何用 —— 图已经出好了。 */
XQ.POSE_PX = { s: 288, l: 1000, h: 192 };
/** 一张形象的 URL。尺寸名不认识就退回 `s`（宁可糊一点也别 404）。 */
XQ.poseURL = function (name, size) {
  return 'assets/xq/' + (XQ.POSE_PX[size] ? size : 's') + '/' + name + '.webp';
};
/** 这个名字是不是一张形象 —— `XQ.mascot` 拿它把形象名和 10 个动作名分开。 */
XQ.isPose = function (n) {
  return typeof n === 'string' && XQ.POSES.indexOf(n) >= 0;
};

/**
 * **预加载一张形象，落地了才回调**（`token` 上只认最后一次请求）。
 *
 * 抽这一小段出来，是因为"先加载、后赋 src"这条规矩有两个用点，而它是整块逻辑里
 * 最容易写错的地方（见 `poseDeck` 的 ①）：
 *   · `poseDeck` —— **一张图一个槽**（左栏、立绘位、封面）；
 *   · chat.html 的气泡头像 —— **一堆图一起换**，它们没有"一个槽"可言，
 *     而且要跟着新消息不断重建，所以那边不能挂 `poseDeck`（它认死一个 img 节点）。
 * 两处要是各抄一份，哪天改了其中一份，另一份就静默地退回"直接赋 src"的老毛病。
 *
 * ⚠️ `token` 只要是个**对象**就行（元素、普通对象都可以）：令牌记在它身上，
 *    所以"同一个 deck 连着点两下"和"聊天气泡连着点两下"用的是同一套守卫。
 * ⚠️ 加载失败（404）**不回调** —— 调用方保持原样，不去换成一张破图。
 */
XQ.poseLoad = function (token, name, size, cb) {
  const rid = (token.__poseRid = (token.__poseRid || 0) + 1);
  const src = XQ.poseURL(name, size);
  const probe = new Image();
  probe.onload = () => {
    if (token.__poseRid !== rid) return;       // 期间又点过，这一张作废
    cb(src, name);
  };
  probe.onerror = () => {};
  probe.src = src;
  return src;
};

/**
 * **点一下换一个形象**（`im` 要换的图，`host` 接点击的外层节点）。
 *
 * opts：`size` 's'/'l'/'h'、`base` 起始形象（默认 p01）、`title` 悬停提示、
 * `hold` 动作位保持多久（默认 620 ms）、`onPose(name)` 换完回调。
 *
 * 下面三条是**踩过的坑**，不是风格：
 *
 * ① **先加载、后换 src。** 直接赋 `im.src = 下一张`，在网络慢一点的时候会把
 *    原来那张**清空**再重画 —— 看上去像"点了一下小瑞没了"。所以先 `new Image()`
 *    探到 `onload` 再赋给 `im`；探不到（404）就**什么都不做**、保留当前这张，
 *    比换成一张破图好。`rid` 防连点：只有**最后一次**点击的结果允许落地，
 *    否则两张图加载次序一颠倒，屏幕上停的是先点的那张。
 * ② **`data-act='swap'` 必须摘掉。** 挂上它这一格会弹一下（keyframe `xqSwap`
 *    在 style.css），盖住 `xqIdle` 浮动；**不摘掉浮动就永远回不来** —— 那些
 *    `[data-act]` 规则都是 `iteration 1` 且没写 `fill-mode`，但选择器权重一直
 *    压着 `.mascot-img`。这条在 cover.html 和 chrome.js 里各写过一遍，同一个坑。
 * ③ **手点挂 `host`，不挂 img**：img 只有图片本身那么大，外层通常大得多、
 *    好点得多（左栏那一格底下还留着避让播放条的空白）。
 */
XQ.poseDeck = function (im, host, opts) {
  opts = opts || {};
  if (!im) return null;
  const size = XQ.POSE_PX[opts.size] ? opts.size : 's';
  const hold = opts.hold === undefined ? 620 : opts.hold;
  const n = XQ.POSES.length;
  let i = Math.max(0, XQ.POSES.indexOf(opts.base || 'p01'));
  let timer = 0;
  const api = {
    size: size,
    count: n,
    at: () => XQ.POSES[i],          // 当前形象名（检查脚本读它）
    index: () => i,
    next: next,
  };

  /* 换到 `src` 这张。摘 -> 强制重算 -> 挂回这三步和 `playOne` 里那条注释说的
     是同一件事：同名动画在 CSS 里算"更新"不算"重建"，不摘掉第二次不弹。 */
  function apply(src) {
    im.src = src;
    im.removeAttribute('data-act');
    void im.offsetWidth;
    im.dataset.act = 'swap';
    clearTimeout(timer);
    timer = setTimeout(() => { delete im.dataset.act; }, hold);
  }

  function next() {
    /* 顺序走、不随机：`POSES` 的顺序是出图时定的，随机走会出现"连点两下还是
       同一张"的观感。走到 p43 回 p01。 */
    i = (i + 1) % n;
    const name = XQ.POSES[i];
    XQ.poseLoad(im, name, size, (src) => {
      apply(src);
      if (typeof opts.onPose === 'function') opts.onPose(name);
    });
    return name;
  }

  if (host) {
    host.style.cursor = 'pointer';
    host.title = opts.title || '点一下换个形象';
    host.addEventListener('click', () => { next(); });
  }
  return api;
};

/* 小瑞形象的资产槽。**真图优先**：`assets/xiaorui_*.png` 探到了就用它，
   探不到退回内置 SVG。`hostId` 是装内置 SVG 的那个容器 —— 真图来了就把它整块藏掉。
   ⚠️ 图在**页面加载时**探一次，路径相对文档，所以服务端要挂 `/assets`
   （见 ui/server.py 里那条 add_static），`file://` 直接打开也能用。 */
/* 小瑞的两张图分开用 —— 一张图伺候不了两种槽：
     assets/xiaorui_head.png  400x400 正方，**方槽默认用它**（头像、手机端 hero、光环）
     assets/xiaorui_hero.png  612x613 立绘，给**立绘位**用（封面右边那种高槽），
                             调用时显式传 src:'assets/xiaorui_hero.png'
   为什么非要分：
     · 头像是**脸占大比例**的方裁，小到 2.2rem(28px) 还认得出是谁；
     · 立绘是整身 1:1.09，塞进正方槽在 6.6rem 里脸上五官就糊成一团了。
   分工和抠图脚本 `_scratch/_mk_xiaorui.py` 的产物一一对应。

   ⚠️ `simple` 是**收了不用**的死参数（函数体从来没读过它）。留着是因为 6 个调用点
      里 4 个还在传 `{simple:true}`，删掉就要同时改 4 个文件；它没有副作用，
      所以先记在这里，等哪次顺手改到那些调用点再一起清。
   `onReady(im)` 给 `XQ.mascot` 用：真图**落地之后**才挂动作（图没来就挂是白挂）。

   `still`：**动图的静帧孪生**。传了它、且系统开了「减弱动态效果」，就探它而不是
   探 `src` —— 和 `XQ.mascot` 里那条 `RM` 是同一个理由：CSS 的
   `animation:none` **关不掉 <img> 里的动画 WebP**（那是图片自己的帧），
   只能在 JS 里降级。封面立绘位现在吃的是 `xiaorui_hero.webp`，所以它必须传这个，
   否则开了减弱动态的用户在封面上看到的还是一直在动的小瑞。
   ⚠️ 只在**加载时**读一次；运行中改系统设置不实时跟随（重载页面即可，
      和全站其它动效一致）。不传 `still` 的行为和以前一模一样。

   ★ 2026-09-25：加了 `deck` / `deckBase` / `deckTitle` 三个参数 —— 传了 `deck`
   （尺寸名 's'/'l'/'h'）这个槽就**顺手接到形象库上**：底图取 `deckBase`
   （默认 p01）那一张，点一下换一个形象。传的尺寸名同时决定**要哪一套图**，
   所以方槽传 `'h'`、立绘位传 `'s'`，别混。
   ⚠️ **不传 `deck` 的槽，行为和一个字都没改之前完全一样**（还是探 `src`、
      还是 `assets/xiaorui_head.png`）。默认值一个字没动，就是为了这条。 */
XQ.mascotSlot = function (imgId, hostId, opts) {
  opts = opts || {};
  /* `simple` 仍然收下不用（见上面那条），只是现在从 `opts` 里取。 */
  const still = opts.still || '';
  const deck = opts.deck || '';
  const deckBase = opts.deckBase || 'p01';
  /* 传了 `deck` 而没显式给 `src`，底图就是形象库里的 `deckBase`。 */
  const src = opts.src || (deck ? XQ.poseURL(deckBase, deck) : 'assets/xiaorui_head.png');
  const onReady = opts.onReady;
  const rm = (typeof window.matchMedia === 'function')
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const probe = new Image();
  probe.onload = () => {
    const im = document.getElementById(imgId);
    const host = document.getElementById(hostId);
    if (im) { im.src = probe.src; im.hidden = false; }
    if (host) host.hidden = true;
    if (im && deck) {
      /* 手点挂**父节点**：这一格的外层通常比图片本身大得多（见 poseDeck 的 ③）。 */
      XQ.poseDeck(im, im.parentNode, {
        size: deck, base: deckBase, title: opts.deckTitle,
      });
    }
    if (typeof onReady === 'function') onReady(im);
  };
  probe.onerror = () => {};                 // 没有图就留着内置 SVG，不报错
  probe.src = (rm && still) ? still : src;
};

/* ---------------------------------------------------------------- 小瑞的动作 */
/**
 * 动作层。**10 张立绘**（设定图 11.png「表情延展」那 10 格，见
 * `_scratch/_mk_xiaorui16.py`）加上一套挂在真实状态上的触发 —— 不是随机循环，
 * 也不是装饰。**待机底图是循环动图**（从宣传片 小瑞.mp4 抠的，见
 * `_scratch/_mk_xiaorui_loop.py`），所以不演动作的时候他也一直在动。
 *
 * ⚠️ 「动态动作」那 6 格**没用上**（白底白身抠不干净），原因和证据写在下面 ACTS 那段。
 *
 * ⚠️ **口径**：待机是**逐帧动画**（真动图，25 帧），但 10 个动作仍然是
 *    "换一张静止立绘 + 播一段 CSS keyframe"，**不是骨骼动画**。答辩时别说成后者。
 *
 * 用法（两个会动的槽，其余槽只用 XQ.mascotSlot 拿静态图）：
 *
 *   XQ.mascot.bind('mascotImg', 'mascotSvgHost', { cycle: true });
 *   XQ.mascot.play('happy');                  // 手动放一个（自检脚本也走这条）
 *   XQ.mascot.react('sev:severe');            // 事件名，映射表在 MAP 里
 *
 * **封面立绘位刻意不 bind**：这一格只吃 CSS 里那条 `xqIdle` 呼吸 + 下面那套
 * "点一下换形象"（`XQ.poseDeck`），不连 WebSocket、也没有事件可跟。
 * ⚠️ 早先这里写的理由是"封面只呼吸、不换姿态"，**2026-09-25 已经不成立** ——
 *    用户要求全站小瑞都能点着换形象，封面现在是 43 张那套里的一张（`l` 尺寸）。
 *    不 bind 的理由只剩一条：它是展示页，没有档位可跟。
 */
XQ.mascot = (function () {
  /* 10 个动作名 = 11.png「表情延展」那一块的 10 格。
     ⚠️ 这里的顺序**不再是"手点的顺序"**（2026-09-25 起手点换的是 43 张**形象**，
        见 `XQ.poseDeck`）；它现在只是 `ACTS` 这张表的排列，`play()` 不按顺序走。
     ⚠️ `live` **不在**这张表里：它是待机底图，不是动作，`play()` 也不该放它。
     ⚠️ **11.png 的「动态动作」那 6 格（挥手/出发/导航/加油/庆祝/送爱心）没有进这张表**，
        不是漏了，是抠不干净：那 6 格的底是**白/极淡蓝**，小瑞的身体也是白的，
        逐像素抠图把下半身判成了背景 —— 贴到深色槽上就是**身上破一个洞**。
        定量证据（`_scratch/_probe_cheer.py`）：身体 R-B 中位 **+0**、背景 **−1**，
        颜色通道里根本没有区分信息；最好的一条规则也把 26% 的身体判成背景。
        边缘/泛洪那条路也堵死：原画是柔和喷绘，整格都是弱边缘（幅值中位 20），
        墙一闭就把整格封死。**这 6 张要么换个底、要么请美术导一张透明底 PNG。**
        对照图：`_scratch/_sprite_probe/qa16_checker.png`（棋盘底，白残留藏不住）。 */
  const ACTS = ['happy', 'wink', 'wow', 'shy', 'angry', 'think', 'sad', 'sleep',
                'like', 'heart'];
  const IDLE = 'live';                 // 待机底图的"名字"，走 src() 但不进 ACTS

  /* ⚠️ **`prefers-reduced-motion` 关不掉 <img> 里的动画 WebP。**
     CSS 的 `animation:none` 只关 CSS 动画，GIF/WebP 是图片自己的帧，CSS 管不着 ——
     这是加动图时引进来的真回归，不是理论问题。只能在 JS 里降级：命中就把底图换成
     **同一段素材的第 0 帧静帧**（`xiaorui_live_still.png`，同一张图冻住），
     换过去看不出跳变，也不会去请求那个 webp。
     ⚠️ 只在 `bind` 的时候读一次。运行中改系统设置不会实时跟随 —— 那种情况要
        重载页面，和全站其它动效的表现一致（CSS 那套也要重算才会生效）。 */
  const RM = (typeof window.matchMedia === 'function')
    ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
  const src = (n, slot) => {
    /* ★ 2026-09-25：形象名（`p07`）也走这里 —— 手点换形象之后 `slot.base` 会是
       一个形象名，动作演完"回底图"那一支要能把它解析回 URL。
       ⚠️ 尺寸**从槽上读**（`slot.psize`）：同一个形象在 chat 那格要用 s、
       在方槽里要用 h，这个函数自己不知道它在给谁换图。 */
    if (XQ.isPose(n)) return XQ.poseURL(n, (slot && slot.psize) || 's');
    if (n !== IDLE) return 'assets/xiaorui_' + n + '.png';
    return (RM && RM.matches) ? 'assets/xiaorui_live_still.png'
                              : 'assets/xiaorui_live.webp';
  };
  const slots = [];                    // 登记过的槽，react() 要通知所有
  let warmed = false;

  /* 事件 -> [动作, 保持多少毫秒]。**映射集中在这一张表里**，不许散到调用点去 ——
     十几处调用点各记一个动作名，想改口径就得满仓库翻。
     ⚠️ `0` = **一直保持**，不回底图。这是给"状态类"动作用的。说话/听语音那种是
        "事件"，用完就回去。
     ★ 2026-09-24：`sev:normal` 从 `happy` 改成 **`live`（待机循环动图）**。
        原来四档都是"按住一张静止立绘"，实测座舱首页 **30 秒里 0% 时间是动的** ——
        而"清醒"本来就是**待机**状态，那个档位该看到的就是待机动图。
        用户原话：「在展示页面中让小瑞动起来」。
        改完之后：清醒 = 一直在轻轻动；轻度/中度/重度**仍然是按住对应表情**（那三个
        是"有事发生"的状态，静止的表情是有意义的，不是漏改）。
        ⚠️ `live` 不在 ACTS 里也没关系 —— `src()` 认得它（走 IDLE 那条分支，
           会按 `prefers-reduced-motion` 选 webp 还是静帧），`playOne()` 只是把
           名字写进 `data-act`。CSS 里没有 `[data-act="live"]` 那条 keyframe，
           所以它上面挂的还是底图那条 `xqIdle` 呼吸 —— 和"没有动作"时一致。
        ⚠️ 跟着一起改的还有 `_scratch/_check_mascot.py` 的 `SEV_ACT`（那张表是
           **故意重写一遍**的自证表，见那里的注释），它 F 段那条断言也改成了
           「normal 回底图、其余三档按住」。**别只改一处。**
     ⚠️ 10 张里**只有这 7 张挂了事件**。这是如实的情况，不是漏了——那些情绪在这个
        项目里没有对应的真实信号，硬编一个触发只会变成随机表演。
     ⚠️ 剩下那 3 张（害羞/生气/委屈）★ 2026-09-25 起**在界面上看不到了**：以前
        还能靠"手点一下换下一个动作"转到它们，现在手点换的是 43 张**形象**。
        要看到它们只剩 `XQ.mascot.play('shy')` 这一条路（控制台 / 检查脚本）。
        这是换形象库的**已知代价**，不是漏改；想恢复得另外给它们找个交互
        （比如长按循环动作），别偷偷把手点改回去 —— 那正好是用户要的东西。
     ⚠️ 2026-09-23：原来挂在 加油/出发/导航/庆祝 上的四条改用了 `like`/`wow` ——
        那 4 格的图抠不出来（见上面 ACTS 那段），**语义靠得近的顶上**，不是随便挑的：
        加油→点赞、出发/导航→惊讶(引起注意)、庆祝→点赞。

     ★ 2026-09-24：`nav:start` / `nav:arrive` 两条**删掉了**（`nav.html` 整页删除，
     用户「把导航页删了吧」）。两条的生命周期不一样，一并说明免得看着像删错：
       · `nav:start` 从来**就没有过调用点**（一直是给"以后加开始导航"预留的）；
       · `nav:arrive` 全库唯一的调用点是旧 `nav.html:445`，页没了它也就不可能触发。
     留着的代价是那张表里躺着两条永远进不去的分支 —— 表格是"事件->动作"的口径表，
     谎报有几个事件比少一行危险。

     ★ 2026-09-25 晚：**`nav.html` 回来了（接的是真高德），这两条仍然不加。**
     别看着"页回来了"就顺手补上 —— 新的这一页**没有"出发/到达"这个交互**：
     它是一张卡片页，人在上面定起点、高德算路、路线直接画出来，没有"开始导航"
     那个按钮，也就没有"到达"那一刻。加了就是加两条**永远不会触发**的映射，
     正好是上面那句话反对的事。哪天真做了"开始导航"，两条一起补。
     ⚠️ `source` 那条**留着而且仍然是活的**，别一起删：页面上虽然没有切源入口了，
        但 `?sev=` 演示定位在 replay/live 源上会真的发一条 `{type:'source',spec:'demo'}`
        过去（app.js 的 onHello，cam 源上被显式排除），那是一次真实切换、会重发 hello。 */
  /* ★ 2026-09-24「只做疲劳」：`sev:*` 四条**又改了一次键名**，现在是
     `normal/mild/moderate/severe` —— **疲劳档位**（`ui/state.py` 的 severity），
     和 `data-sev` 的四个取值同源。上一版跟的是支路一的类别（glance/phone/fatigue），
     三类之后那条路只剩 L0/L3 两档，中间两档永远出不来，表情也就废掉一半。
     · 中度用 `wow`（惊讶）当"引起注意"用，**不是** `angry`：生气留给手点循环，
       让角色板起脸训驾驶员跟这个项目"用温和的方式说话"的立意是反的 ——
       跟重度用比心而不是红灯脸是同一个理由。
     ⚠️ 四条键与 `XQ.LV` 那张表**必须一起改**：一个改了一个没改，档位一变
        表情就不动了（事件名对不上 MAP，`react()` 直接返回 false，不报错）。 */
  const MAP = {
    'sev:normal':  ['live', 0],        // 清醒 -> 待机循环动图（一直在动，见上面 ★）
    'sev:mild':    ['think', 0],       // 轻度疲劳 -> 思考（比"疑问"贴这个项目的语气）
    'sev:moderate': ['wow', 0],        // 中度疲劳 -> 惊讶（引起注意）
    'sev:severe':  ['heart', 0],       // 重度疲劳 -> 比心
    /* 比心代替旧的"感动"：同样是"用温和的方式说话"这个立意，
       但 11.png 的动作库里没有捧心，比心是最近的一格。 */
    'sev:up':      ['like', 2400],     // 档位**上升**的那一下 -> 点赞（原「加油」）
    speak:        ['happy', 2200],     // 开口说话
    listen:       ['wink', 1200],      // 开始听语音
    heard:        ['happy', 2000],     // 听清了
    missed:       ['think', 2000],     // 没听清 / 失败
    source:       ['wow', 2000],       // 数据源真的切了（原「出发」；现仅 ?sev= 会触发）
  };

  /* 在一个槽上放一个动作。`hold` 0/缺省 = 保持不回底图。 */
  function playOne(slot, name, hold) {
    if (!slot || !slot.el) return;
    slot.last = name;
    slot.pending = null;
    slot.el.src = src(name, slot);
    /* ⚠️ 让动画**真的**从头再来，必须「摘掉 -> 强制一次样式重算 -> 挂回」三步。
       **只写 `void offsetWidth` 是不够的** —— 那是我的推断，2026-09-23 在浏览器里
       实测推翻了（`_scratch/_probe_replay.py`，用 `animationstart` 事件数当判据）：
       把 `data-act` 赋成**同样的值**时，两次样式重算里动画名都是 `xqHappy`，
       而按 CSS Animations 的规则**同名动画是"更新"不是"重建"**，已经播完的
       （`iteration-count:1` + 默认 `fill:none`）就停在终态 —— 表现是"点第二次没反应"。
       先摘掉（此时"旧列表里没有 xqHappy"）、强制重算、再挂回去，才会被当成新建。
       中间不落绘，所以看不见闪。 */
    slot.el.removeAttribute('data-act');
    void slot.el.offsetWidth;
    slot.el.dataset.act = name;
    clearTimeout(slot.timer);
    slot.timer = 0;
    /* `until` = 这个动作演到什么时候。`react()` 靠它决定"现在就切"还是"排到后面"，
       所以**必须存绝对时刻**，不能只留一个 setTimeout —— 从外面看不出还剩多久。 */
    slot.until = hold ? Date.now() + hold : 0;
    if (hold) {
      slot.timer = setTimeout(() => {
        slot.timer = 0;
        slot.until = 0;
        /* 演完了先看有没有排着的下一个 —— 有就直接接上，别闪一下底图。
           （典型情况：开场挥手还没演完，`sev:normal` 就来了，排在它后面。） */
        if (slot.pending) { const p = slot.pending; slot.pending = null; playOne(slot, p[0], p[1]); return; }
        /* ★ 演完"回哪儿"不等于"回底图"：**当前档位有表情的话要回那个表情**
           （`slot.state`，见 `react()`）。这条是跑 `_check_mascot.py` 才暴露的：
           `?sev=mild` 那档小瑞停在 hello 而不是 ask —— 因为开场那句台词的 TTS
           回调是**几秒后**才来的（要先合成），它 `react('speak')` 放了个「开心」
           （hold 2200），演完就把底图 hello 放回来了，而档位表情 ask 早被顶掉、
           `xqSev` 又已经记成 mild 不会再触发 —— 结果小瑞的表情和面板上的档位对不上。
           这不是测试的问题：**状态类表情必须能盖过事件类动作，事件演完要还回去**。 */
        const back = slot.state || slot.base;
        if (back === slot.base) {
          slot.el.removeAttribute('data-act');   // 摘掉 -> CSS 里的 xqIdle 呼吸自然回来
          slot.el.src = src(slot.base, slot);
        } else if (slot.el.dataset.act !== back) {
          playOne(slot, back, 0);                // hold 0 = 不再挂 timer，稳在表情上
        }
        /* ⚠️ 上面这两支**不能合并成一句 `if (dataset.act === back) return;`** ——
           底图那个分支必须无条件把 `data-act` 摘掉。第一版就是这么写的，结果
           槽的底图正好是 `hello`、开场又播了一次 `hello`（`bind` 里那次打招呼），
           演完 `back === 'hello' === dataset.act` 直接 return 了，`data-act` 一直
           挂着 —— 那一格**再也回不到 xqIdle 呼吸**。
           两种"已经在位"不是一回事：底图要的是"摘掉动作"，表情要的是"不重播"。 */
      }, hold);
    }
  }

  function play(name, opts) {
    opts = opts || {};
    if (ACTS.indexOf(name) < 0) return false;
    const hold = opts.hold === undefined ? 1600 : opts.hold;
    if (opts.slot) { playOne(opts.slot, name, hold); return true; }
    for (const s of slots) playOne(s, name, hold);
    return slots.length > 0;
  }

  function bind(imgId, hostId, opts) {
    opts = opts || {};
    /* 底图默认是**循环动图**（IDLE）；nav 那格显式传 `base:'head'` 要方形头像版。
       两者都走 src()，所以这里存的仍然是一个"名字"而不是路径。
       ★ 2026-09-25：`base` 现在**也可以是一个形象名**（`p07`）—— 手点换形象之后
       `slot.base` 会被 `onPose` 改成新形象，所以"事件演完回哪儿"回的是**人挑的
       那一张**，不再是待机动图。 */
    const base = opts.base || IDLE;
    /* 这个槽要是立绘位就吃 `s` 那套形象图。`poseSize` 只有手点换形象用得上
       （一个 bind 槽要么是立绘位要么没有形象库，不存在"方槽还 bind"的情况）。 */
    const psize = XQ.POSE_PX[opts.poseSize] ? opts.poseSize : 's';
    /* 16 张动作图加起来约 412 KB，**一次全预加载**：换 src 时若还没下载完，
       动作会先空一下再出来。只在第一个槽上做一次。
       ⚠️ 别把 IDLE 也塞进这个循环 —— 那张 webp 正在当底图用，本来就在下载了。
       ⚠️ 形象库那 43 张**不在**这里预加载，也**不能**加进来：`/assets` 是
          `no-store` 的，"预取进缓存"在这套服务器上不成立（见 XQ.POSES 那段）。 */
    if (!warmed) {
      warmed = true;
      ACTS.forEach((n) => { const p = new Image(); p.src = src(n); });
    }
    XQ.mascotSlot(imgId, hostId, {
      src: XQ.isPose(base) ? XQ.poseURL(base, psize) : src(base),
      onReady: (im) => {
        /* `state` = 这个槽**当前的档位表情**（`hold === 0` 的那种，见 `react()`），
           事件类动作演完要还回它而不是还回底图。`last` = 上一个演过的动作名，
           只为"手点循环"记下一个该演谁。两者不是一回事：
           点完一轮之后 `last` 一直在变，`state` 只由档位改。 */
        const slot = { el: im, base: base, psize: psize, timer: 0, last: base,
                       until: 0, pending: null, state: null };
        slots.push(slot);
        /* ★ 2026-09-25（第十次改版）：这个槽原来手点是"在 10 个**动作**里循环"
           （happy -> wink -> ...），现在换成"在 43 张**形象**里循环" —— 用户
           「小瑞图片能变化的太少了 我不是有 40 多张图片吗」。动作那套一个字没删：
           它仍然是**事件驱动**的（`react()` / `play()`），只是不再挂在手点上。
           ⚠️ **只能有一个手点处理**。原来那 5 行就删在这儿了，留着会和 deck 抢
              click —— 点一下"换个形象"和"换个动作"各来一次，看着就是乱跳。
           ⚠️ `onPose` 必须把槽的底图挪过去（`slot.base = n`）：不然点完换了个
              形象，来一条 `speak` 就把它顶回待机动图了，人会以为"点了没用"。
              `playOne` 里那支"回 `slot.state || slot.base`"会自动用上这个新底图，
              所以"人挑的那张"在事件演完之后还在。 */
        if (opts.cycle && im.parentNode) {
          XQ.poseDeck(im, im.parentNode, {
            size: psize,
            base: XQ.isPose(base) ? base : 'p01',
            title: '点一下换个形象',
            onPose: (n) => { slot.base = n; },
          });
        }
        /* 认领的时候打个招呼。原来是 `wave`（11.png 的「招手」），2026-09-23 那格
           抠不干净被否掉之后改用 `happy` —— **`playOne` 不校验名字**，图不在盘上
           就是一个静默 404（控制台报错、槽上停在上一张图），别随手写名字。
           ⚠️ 想恢复成招手的话，先把 ACTS 里加回去、assets 里补上那张图。 */
        playOne(slot, 'happy', 2000);
      },
    });
  }

  /* 事件入口。**没登记的槽就什么都不做** —— live.js 在十页里都加载，
     而绝大多数页面上根本没有会动的小瑞。

     ⚠️ **来了事件但槽正在演上一个动作时，排到它演完再切，不顶掉它。**
     这条不是可有可无的讲究，是必须的：页面一加载服务端的 hello/state 就到了，
     `sev:normal` 会被 `render()` 立刻发出来，而开场那一下「打招呼」要 2 秒 ——
     不排队的话开场挥手**必然**只看得见半下。同样地"听清了"紧跟在"开始听"后面
     （眨眼 1.2s），不排队就把眨眼压掉了。
     ⚠️ `pending` 只存最后一个：状态抖动连着来的时候不会堆成一串动作排队放，
        而是每次都覆盖，最终只演最新那个。
     ⚠️ **`hold === 0` 的那些是"状态类"，要记进 `slot.state`**（记在这一层、
        **不是**在 `playOne` 里记）：它是这个槽的"当前表情"，事件类动作演完要还回
        这个表情而不是还回底图。而且必须在**排队之前**就记下 —— 排到最后可能被
        中间任何一个 `playOne` 把 `pending` 清掉，那时"记在哪一次播放里"就丢了。 */
  function react(ev) {
    const hit = MAP[ev];
    if (!hit || !slots.length) return false;
    for (const s of slots) {
      if (hit[1] === 0) s.state = hit[0];
      if (s.until > Date.now()) { s.pending = hit; continue; }
      playOne(s, hit[0], hit[1]);
    }
    return true;
  }

  return { bind: bind, play: play, react: react, ACTS: ACTS,
           get bound() { return slots.length; } };
})();

/* ------------------------------------------------------------- 心率那一格写什么 */
/* ★ 2026-09-26 加。**一个地方定义，三页共用**。
   为什么要共用：`poseOf` 那种"每页抄一份"的写法这个工程已经踩过 ——
   两边文案不一致会被当成 bug 报上来。心率这一格现在三页都要写。

   ⚠️ 为什么要分「未接入」和「未按压」两档 —— 用户当场报的：
      手指从传感器上拿开之后，页面写「未接入」，可板子明明接着
      （LED 常亮、`D,` 行照来）。**那句话是假的**，而且在答辩现场
      正好是最容易被看见"坏"的一幕。
      三个状态 `serial_hr.snapshot()` 本来就分得清清楚楚（`finger` 键：
      `unknown` / `off` / `on`），只是以前没有消费方，前端又把
      `hr == null` 一律写成「未接入」，把它们压成了一句话。

   映射（`hr` 有值时**任何状态都优先给数字**）：
     hr 有数        -> `62 BPM`      —— 手指在不在都不重要，有数就是有数
     finger = off   -> `未按压`      —— 传感器上没有手指（DC 电平塌了）
     finger = on    -> `--`          —— 手指在、但还没攒够心跳，**没有数字可给**
     unknown        -> `未接入`      —— 串口没打开 / 没数据 / 停了
   🔴 `on` 那档**只给横杠，不给词**：`finger=on` 不等于"在攒心跳"，
      也可能是"没搏动"（`snapshot` 里那条 `no_pulse`）——
      一句话只能覆盖其中一种，而覆盖不到的那一种就是**编的**。
      横杠是中性的：有量到，只是还没有数字。 */
XQ.hrText = (s) => {
  if (s.hr != null) return s.hr.toFixed(0) + ' BPM';
  if (s.hr_finger === 'off') return '未按压';
  if (s.hr_finger === 'on') return '--';
  return '未接入';
};

/* ---------------------------------------------------------------- 历史缓冲 */
/* 服务端只推"这一拍"，趋势图要序列 → 客户端自己攒。
   长度按 24 Hz 攒 40 分钟留余量，实际 8 Hz，够用很久。 */
XQ.Hist = {
  rows: [],
  MAX: 20000,
  push(s) {
    this.rows.push({
      t: Date.now(),
      severity: s.severity,
      perclos: s.perclos,
      p_fat: s.p_fat,
      hr: s.hr,
      /* ★ 2026-09-26：心率那一路的两个新量。`XQ.Hist.series(key, min)` 是
         按**字段名**取数的 —— 不补这两行，页面上有数、趋势图上却是空的，
         而那种"缺"看起来跟"这段时间没量到"一模一样。
         ★ 深夜：`hr_rmssd` 换成 `hr_ac`（页面上那一格换的就是它，见
         `ui/web/app.js`）。`hr_rmssd` 在 `state` 帧里**还在**，只是没有人画它
         —— 要留就留成一行，别让它悄悄变成"有字段没画面"的第三种状态。 */
      hr_ac: s.hr_ac,
      hr_pi: s.hr_pi,
      l1: s.l1,
      d_pitch: s.d_pitch,
      level: s.level,
      yawn_sec: s.yawn_sec,
      brate: s.brate,
      nod: s.nod,
      en_now: s.en_now,
      gate: s.gate,
      probs: s.probs,
    });
    if (this.rows.length > this.MAX) this.rows.splice(0, this.rows.length - this.MAX);
  },
  /** 取最近 minutes 分钟内、且 key 有值的点（横轴归一化到 0..1）。 */
  series(key, minutes) {
    const now = Date.now();
    const lo = now - minutes * 60000;
    const pts = this.rows.filter((r) => r.t >= lo && r[key] != null && !Number.isNaN(r[key]));
    if (!pts.length) return { t: [], v: [] };
    return { t: pts.map((r) => r.t), v: pts.map((r) => r[key]) };
  },
  /** 已记录多久（秒）。页面上要写出来 —— 免得把"刚打开 20 秒"当成"一小时"。 */
  spanSec() {
    if (this.rows.length < 2) return 0;
    return (this.rows[this.rows.length - 1].t - this.rows[0].t) / 1000;
  },
  fmtSpan() {
    const s = Math.round(this.spanSec());
    if (s < 60) return `${s} 秒`;
    return `${Math.floor(s / 60)} 分 ${s % 60} 秒`;
  },
};

/* ---------------------------------------------------------------- 档位键 */
/* `s.severity`（`ui/state.py` 的四档疲劳程度）-> 界面档位键，也就是
   `data-sev` 的四个取值、`--sev-*` 四个变量、`pages.css` 时间轴圆点
   四条规则共用的那四个名字。
   **放在这里是因为三个页面都要用它**（app.js / detail.html / link.html）——
   各写一份的话，改了档位定义就会有一页的配色和文案停在旧档上，而且不报错。
   ★ 2026-09-24：上一版这张表是 `s.level` -> `glance/phone/fatigue`（支路一的类别）。
   三类之后 level 只剩 L0/L3 两档，按它上色的话轻度/中度永远出不来黄和橙黄，
   所以整页外观改跟 **severity**（档位），它才是口径那张分级表的轴。
   ⚠️ 键和值现在同名（看着像恒等映射），但**别删这张表**：
     · 三个页面从这一处取；
     · `XQ.LV[s.severity] || 'normal'` 那句 `|| 'normal'` 是给未知值兜底的 ——
       没有它 `data-sev` 会被赋成 `undefined`，四条 `body[data-sev]` 一条都不命中，
       整页停在上一拍的颜色（不报错，很难查）。 */
XQ.LV = { normal: 'normal', mild: 'mild', moderate: 'moderate', severe: 'severe' };

/* =========================================================================
   四档外观表（`XQ.LOOK` / `XQ.DEG_W` / `XQ.QUICK`）—— 全站一份
   -------------------------------------------------------------------------
   键名 = **疲劳档位** = `ui/state.py` 的 `severity` = `data-sev` 的四个取值
   = `XQ.LV` = `style.css` 那四条 `body[data-sev]`，一把钥匙开全站。
   ★ 2026-09-24 从 `app.js` 搬过来的（原文一字未改，只加了 `XQ.` 前缀）：
     驾驶监测页的「小瑞·驾驶陪伴」卡要用同一张表 —— 见 app.js 里那段别名注释。
   ========================================================================= */
/* ---------------------------------------------------------------- 四档外观 */
/* 每档要说的话、要显示的颜色态度，集中在这一张表里。加一档只改这里。
   ★ 2026-09-24「只做疲劳」：**键名 = 疲劳档位**（normal/mild/moderate/severe，
   `ui/state.py` 的 severity），和 `data-sev` 的四个取值、`XQ.LV`、`pages.css`
   那几条圆点规则同一套名字。上一版这四个键是支路一的类别（glance/phone/fatigue）。
   ⚠️ 表里**没有 `name` 这一项**：大标题 `#sevName` 直接取服务端的
      `s.severity_name`（清醒/轻度疲劳/中度疲劳/重度疲劳），比在这儿抄一份可靠 ——
      抄一份的话两边迟早不一致，而不一致的表现是"标题和配色定级不同"。
   ⚠️ 也**没有 `level` 那一项**了：它原来既当外观常量、又喂下面那条
      「疲劳程度」的条，把两条轴混在一张表里。现在那条条的宽度由 `DEG_W` 给。
   ⚠️ **上一版的 `mildLine` 补丁删掉了**：它存在的原因是"轻度疲劳在级别轴上
      没有位置"（level 还是 0，配色按 normal 走，只好单独换一套话）——
      现在外观直接跟档位，轻度有自己的 `data-sev` 和配色，补丁没有用了。 */
XQ.LOOK = {
  normal: {
    /* 情绪状态那一行（参考图 首页.png）用的词。**同一档位的换词**，
       不是测出来的情绪 —— 本项目没有情绪识别这一路，见 render() 里那段。
       ⚠️ 改档位名时这张表要一起看：漏一档会显示成 `—`（故意的，见 render()）。 */
    moodWord: '平静',
    pill: '安全驾驶',
    cam: 'AI 正在监测驾驶员状态',
    xqPill: '状态良好',
    mood: { mouth: 'M22 39 q10 8 20 0', brow: 0, eye: 3.4 },
    note: '有我在，<br>一路都很安心~',
    bubble: '',
    acts: [],
  },
  /* 轻度疲劳（支路二：闭眼变长 / 打哈欠）。管线里这一档**不是**支路一给的
     —— 它的 `level` 可能还是 0，但外观跟档位，所以这里该变黄也真的变黄。
     小瑞在这一档**也提醒**（口径要求"轻度疲劳提示"），所以它有 bubble、
     有动作按钮，不是只换个颜色。 */
  mild: {
    /* 情绪状态那一行（参考图 首页.png）用的词。**同一档位的换词**，
       不是测出来的情绪 —— 本项目没有情绪识别这一路，见 render() 里那段。
       ⚠️ 改档位名时这张表要一起看：漏一档会显示成 `—`（故意的，见 render()）。 */
    moodWord: '略显疲惫',
    pill: '注意',
    cam: '检测到疲劳征兆',
    xqPill: '关切陪伴',
    mood: { mouth: 'M23.5 41.5 h17', brow: 0, eye: 3.1 },
    note: '',
    bubble: '检测到你有些疲劳，要不要听一段舒缓音乐？',
    acts: [['music', '播放舒缓音乐', 1], ['rest_stop', '建议休息一下', 0],
           ['nearby', '查看附近服务区', 0]],
  },
  /* 中度疲劳（支路二：持续闭眼 —— perclos 过 42.6% 或 p_fat 过 0.55）。 */
  moderate: {
    /* 情绪状态那一行（参考图 首页.png）用的词。**同一档位的换词**，
       不是测出来的情绪 —— 本项目没有情绪识别这一路，见 render() 里那段。
       ⚠️ 改档位名时这张表要一起看：漏一档会显示成 `—`（故意的，见 render()）。 */
    moodWord: '疲惫',
    pill: '警告',
    cam: '检测到持续闭眼',
    xqPill: '认真提醒',
    mood: { mouth: 'M22.5 43 q10.5 -6 19 0', brow: 1, eye: 3.1 },
    note: '',
    bubble: '闭眼时间越来越长了，找个服务区歇一会儿好吗？我帮你导。',
    acts: [['rest_stop', '导航至最近服务区', 1], ['snooze', '稍后提醒', 0]],
  },
  /* 重度疲劳（支路一：低头看手机 / 疲劳点头）。
     ⚠️ 文案里写的是**总称**（低头/点头），具体是哪一个由 `attention` 那一行说
        （低头看手机 / 疲劳点头）—— 这两件事在档位上完全一样，只有归因不同。 */
  severe: {
    /* 情绪状态那一行（参考图 首页.png）用的词。**同一档位的换词**，
       不是测出来的情绪 —— 本项目没有情绪识别这一路，见 render() 里那段。
       ⚠️ 改档位名时这张表要一起看：漏一档会显示成 `—`（故意的，见 render()）。 */
    moodWord: '困倦',
    pill: '紧急',
    cam: '检测到低头 / 点头',
    xqPill: '紧急提醒',
    mood: { mouth: 'M22 44.5 q10 -9 20 0', brow: 1, eye: 3.0 },
    note: '',
    bubble: '这个状态别再开了，先靠边停一下 —— 我帮你找最近的服务区。',
    acts: [['rest_stop', '导航至最近服务区', 1], ['snooze', '稍后提醒', 0]],
  },
};

/* 「疲劳程度」那一行的条。**键就是上面那张表的四个档位键**（severity）——
   这一版两条轴合成了一个名字，所以表可以只写这一份。
   值是上一版三档那三个数（0.12 / 0.45 / 0.88）**逐档挪过来的**，中间补了中度：
   原来 mild 那 0.45 给轻度、原 severe 那 0.88 给重度。 */
XQ.DEG_W = { normal: 0.12, mild: 0.45, moderate: 0.66, severe: 0.88 };

/* 重度时额外挂出来的「快捷操作」。参考图 3.png 里有这一块。 */
XQ.QUICK = [['music', '播放舒缓音乐'], ['rest_stop', '导航服务区'], ['status', '查看驾驶状态']];

/* ---------------------------------------------------------------- 独立告警 */
/* 支路二自己判出来的两条：**持续闭眼** 和 **打哈欠**。
   -------------------------------------------------------------------------
   为什么另开一条通道，而不是直接读 `level`：
     `src/fuse.py:634-644`（`ui/cam.py:321-323` 逐字搬过来的那份同理）里，
     哈欠会把 `l_fused` **抬到至少 L1**、持续闭眼经 `l2` 抬到 L1/L2 ——
     也就是说这两件事在**级别轴上和"瞟了一眼后视镜"撞在同一格**。
     光看级别分不出是谁，报个"注意"等于把原因丢了。所以服务端另外给一条
     `alarms: [{kind, text}]`（`ui/state.py` 的 `derive()` 末尾算的，
     文案逐字来自 `src/fuse.py:133-134` 的 `NOTE_YAWN` / `NOTE_FACE`）。
     ⚠️ 所以"打哈欠时整页也变成 L1 的黄"**不是重复报警**，别当 bug 修：
        颜色说的是级别，横幅说的是**归因**。`ui/sources.py` 那边同样写明了。

   呈现分两半（用户拍板「常驻横幅 + 瞬时 toast」）：
     · **横幅** = 只要 `alarms` 里还有这一条就一直挂着（不闪、不自己消失）；
     · **toast** = 只在**上升沿**弹一次，复用 `XQ.flash`。
   为什么需要"保持"（`held`）：`yawn_sec` 是缓冲区内的滚动量，就在阈值 2.0
   上下抖，`src/fuse.py` / `ui/cam.py` 靠 `yawn_until = mt + YAWN_HOLD` 压住它。
   前端不做同一件事的话横幅一秒闪一次。`hold_sec` 由服务端给
   （`hello()` 的 `alarm_cfg.hold_sec`，= 5.0，与 `YAWN_HOLD` 同值），不写死。

   ⚠️ **不新增发声**：live 模式下 `src/fuse.py` 自己就在念同一句
      （`config.json` 的 `enabled_in_modes.live=false` 正是为了防两个声音叠着说），
      界面这边只做视觉。
   ⚠️ 图标：`XQ.ICON` 里没有"嘴/哈欠"的图形，哈欠借用 `snooze`（钟，表示困），
      闭眼借用 `eye`。认不出来的 kind 一律给 `alert`，这样服务端将来加第三种
      kind 也不会渲染成空白。 */
XQ.alarms = {
  ICON_OF: { yawn: 'snooze', eyes: 'eye' },
  held: {},                       // kind -> 到期时刻（毫秒，performance.now 口径）
  /* 下面两个数**只有这一份**：页面从 hello 的 `alarm_cfg` 灌进来（setCfg），
     谁要用就读 `XQ.alarms.holdSec` / `.yawnMin`。页面各存一份的话，
     同一屏上"横幅的保持时长"和"判定哈欠的阈值"迟早会不一样。 */
  holdSec: 5.0,                   // = src/fuse.py 的 YAWN_HOLD
  yawnMin: 1.0,                   // = src/face.py 的 YAWN_MIN（ui/state.py 也有一份）

  /** 灌服务端的 `alarm_cfg`。字段缺失/为 0 就沿用现在的值，不覆盖成 0。 */
  setCfg(c) {
    if (!c) return;
    if (c.hold_sec > 0) this.holdSec = c.hold_sec;
    if (c.yawn_min > 0) this.yawnMin = c.yawn_min;
  },

  /**
   * 渲染 + 去重。**容忍 null host 和没有 alarms 字段的老数据** ——
   * 不展示告警的页面（chat/link/media/phone/settings…）拿到的就是 null，
   * 这里抛异常会顺着调用点把那页的整条渲染链打断。
   * @returns {Array} 这一拍仍生效的告警，调用方可拿去做别的判断。
   */
  render(host, s, holdSec) {
    const list = (s && s.alarms) || [];
    const hold = (holdSec > 0) ? holdSec : this.holdSec;
    const now = performance.now();
    const live = [];
    for (const a of list) {
      if (!a || !a.kind) continue;
      if (!(this.held[a.kind] > now)) {      // 上升沿：第一次看见才弹一次 toast
        if (a.text) XQ.flash(a.text);
      }
      this.held[a.kind] = now + hold * 1000; // 这一拍还在报 -> 续期
      live.push(a);
    }
    if (!host) return live;
    /* ★ 2026-09-25：设置页的「疲劳横幅」开关（`XQ.prefs`）。
       **只影响"显不显示"，不动上面那本 `held` 台账、也不改返回值** ——
       关掉横幅不该连带改掉 toast 的去重时序，那是另一件事（两个开关各管各的）。
       放在这一行（而不是函数最顶上）就是为了让 `held` 那几行照常跑完。 */
    if (!XQ.prefs.get('banner')) {
      host.hidden = true;
      host.innerHTML = '';
      return live;
    }
    /* 这一拍没报但还没过期的那几条，**不显示**（横幅只反映"此刻"），
       续期只为压住 toast 的抖动 —— 判据一消失，横幅立刻收。 */
    host.hidden = !live.length;
    host.innerHTML = live.map((a) => `
      <div class="alarm-item">
        ${XQ.icon(this.ICON_OF[a.kind] || 'alert')}
        <span>${XQ.esc(a.text)}</span>
      </div>`).join('');
    return live;
  },
};

/* ---------------------------------------------------------------- 小图 */
/** 迷你折线（不给坐标轴）。values 为 null 的点直接跳过。 */
XQ.spark = function (values, { w = 100, h = 30, pad = 2 } = {}) {
  const v = values.filter((x) => x != null && !Number.isNaN(x));
  if (v.length < 2) return '';
  const lo = Math.min(...v), hi = Math.max(...v);
  const span = hi - lo || 1;
  const n = v.length;
  const px = (i) => pad + (w - 2 * pad) * (i / (n - 1));
  const py = (x) => h - pad - (h - 2 * pad) * ((x - lo) / span);
  let d = `M${px(0).toFixed(1)} ${py(v[0]).toFixed(1)}`;
  for (let i = 1; i < n; i++) d += `L${px(i).toFixed(1)} ${py(v[i]).toFixed(1)}`;
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">`
       + `<path d="${d}" vector-effect="non-scaling-stroke"/></svg>`;
};

/* ---------------------------------------------------------------- 折线图 */
const fmtClock = (ms) => {
  const d = new Date(ms);
  return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
};
/* 跨度不到 3 分钟就带上秒。不然刚打开页面时四个刻度全是「16:45」，
   看着像标签坏了，其实是真的只有 4 秒数据。 */
const fmtClockSec = (ms) => {
  const d = new Date(ms);
  const p = (n) => String(n).padStart(2, '0');
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
};

/**
 * 往一个 `.plot` 元素里画折线。
 *
 *   XQ.plot(el, {
 *     t: [ms,...], v: [num,...],      // 数据（来自 XQ.Hist.series）
 *     yMin, yMax, ticks: [0,20,40,60],
 *     fmt: (v) => v.toFixed(1),       // y 刻度与气泡的格式
 *     callout: '当前',                 // 气泡前缀；null 则不画气泡
 *     empty: '…',                     // 没数据时的说明
 *   })
 *
 * ⚠️ 没有数据时**画空白 + 写一句实话**，不画一条平的零线 —— 那条线会被当成
 *    "驾驶员状态很稳"。
 */
XQ.plot = function (el, cfg) {
  const { t = [], v = [], yMin, yMax, ticks = [], fmt = (x) => String(Math.round(x)),
          callout = '当前', empty = '还没有数据' } = cfg;
  /* ⚠️ 容忍 null：下面那一句在 el 为 null 时会抛，而调用点都在 8 Hz 的 render 里
     —— 抛一次，那一页**从那一拍起整条渲染链就断了**，控制台还只报一次。
     `XQ.alarms.render` 早就按"容忍 null host"这个口径写，这里跟上。 */
  if (!el) return { last: null };
  el.innerHTML = '';
  if (v.length < 2) {
    el.insertAdjacentHTML('beforeend', `<div class="plot-empty">${XQ.esc(empty)}</div>`);
    return { last: null };
  }

  const lo = yMin != null ? yMin : Math.min(...v);
  const hi = yMax != null ? yMax : Math.max(...v);
  const span = hi - lo || 1;
  const t0 = t[0], t1 = t[t.length - 1];
  const tspan = (t1 - t0) || 1;

  /* 归一化到 0..100 的框里，线宽靠 non-scaling-stroke 保持不变 */
  const X = (ms) => ((ms - t0) / tspan) * 100;
  const Y = (val) => 100 - ((val - lo) / span) * 100;

  const d = v.map((val, i) => `${i ? 'L' : 'M'}${X(t[i]).toFixed(2)} ${Y(val).toFixed(2)}`).join('');
  const area = `${d}L100 100L0 100Z`;

  let grid = '';
  ticks.forEach((tv) => {
    const y = Y(tv);
    if (y < -1 || y > 101) return;
    grid += `<line class="grid" x1="0" y1="${y.toFixed(2)}" x2="100" y2="${y.toFixed(2)}" vector-effect="non-scaling-stroke"/>`;
  });

  el.insertAdjacentHTML('beforeend',
    `<svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">`
    + grid
    + `<line class="axis" x1="0" y1="100" x2="100" y2="100" vector-effect="non-scaling-stroke"/>`
    + `<path class="area" d="${area}"/>`
    + `<path class="line" d="${d}" vector-effect="non-scaling-stroke"/>`
    + `</svg>`);

  /* y 刻度：HTML 层，不会被拉伸 */
  ticks.forEach((tv) => {
    const y = Y(tv);
    if (y < -1 || y > 101) return;
    el.insertAdjacentHTML('beforeend',
      `<span class="ylab" style="top:${y.toFixed(2)}%">${XQ.esc(fmt(tv))}</span>`);
  });

  /* x 刻度：按时间取 4 个（首 / 1/3 / 2/3 / 末） */
  const clock = (t1 - t0) < 180000 ? fmtClockSec : fmtClock;
  const nX = v.length >= 8 ? 4 : 2;
  for (let i = 0; i < nX; i++) {
    const k = Math.round((v.length - 1) * (i / (nX - 1)));
    el.insertAdjacentHTML('beforeend',
      `<span class="xlab" style="left:${X(t[k]).toFixed(2)}%">${clock(t[k])}</span>`);
  }

  const last = v[v.length - 1];
  if (callout) {
    el.insertAdjacentHTML('beforeend',
      `<span class="pt-ring" style="position:absolute;left:${X(t1).toFixed(2)}%;top:${Y(last).toFixed(2)}%;`
      + `width:.85rem;height:.85rem;margin:-.425rem 0 0 -.425rem;border-radius:50%;`
      + `border:1.4px solid var(--accent);opacity:.6"></span>`);
    el.insertAdjacentHTML('beforeend',
      `<span class="bub" style="left:${X(t1).toFixed(2)}%;top:${Y(last).toFixed(2)}%">`
      + `${XQ.esc(callout)} ${XQ.esc(fmt(last))}</span>`);
  }
  return { last };
};

/* ---------------------------------------------------------------- 小瑞出声 */
/**
 * 小瑞的语音。**主路是浏览器自己的 `speechSynthesis`**，不是服务端。
 *
 *   Edge 白送晓晓/云希那一批中文神经音色 —— 本次实测这台机器上 `getVoices()`
 *   能列出 325 个音色，其中中文 17 个，最好的是
 *   `Microsoft 晓晓 Online (Natural)`。零安装、零 key、零依赖。
 *   Windows 自带的 SAPI（服务端那一路）**够不到这批音色**，只能用
 *   `Microsoft Huihui Desktop` 那个 2010 年代机器人音，所以服务端只当兜底。
 *
 * 浏览器这条真念不出来时（没有中文音色 / speak 被策略挡掉），探测到它一直没开口
 * （600 ms 看一次、1.6 s 再看一次，两次都没动静才认），就把这句话发回服务端让
 * PowerShell 念（`ui/tts.py`）。为什么是两级而不是探一次，理由写在 `XQ.speak` 里。
 * 这就是本项目「在线优先、离线兜底」那套设计在音频上的同一份 ——
 * 断网时神经音色用不了，会自动掉到本地那几个（Huihui/Kangkang/Yaoyao），
 * **声音变难听，但仍然出声**。
 *
 * ⚠️ 四个坑，都是实测踩出来的，别改回去：
 *   1. `getVoices()` **在页面加载那一瞬间返回 0 个**，要等 `voiceschanged`
 *      事件之后才有值。同步读必然挑不到音色 → 表现是"永远在走服务端兜底"。
 *      所以下面既等事件、又留 1.5 s 超时，而且 `speak()` 里还会再挑一次。
 *   2. **必须探测"到底开口没有"**（`speaking || pending`）。少了这一步，
 *      浏览器和服务端会同时念同一句话 —— 两个声音叠着说，比不出声更糟。
 *   3. 静音开关和音色选择存 `localStorage`，**不回写 config.json** ——
 *      那个文件里躺着不能进仓库的 API key，让浏览器去改它风险不值当。
 *   4. 后台标签页不出声，见 `XQ.speak` 里那条 visibility 判断的注释。
 */
XQ.tts = {
  supported: typeof speechSynthesis !== 'undefined'
          && typeof SpeechSynthesisUtterance !== 'undefined',
  LS: { on: 'xq.tts.on', voice: 'xq.tts.voice' },

  on: false,          // 当前选择（localStorage 优先，其次 config 的 default_on）
  keyword: '自动',     // 音色关键词；"自动" = 优先名字带 Natural 的中文音色
  prosody: {},        // emotion -> {rate, pitch}
  serverOk: false,    // 服务端兜底可用吗（配置开了 + 那边真起了线程）
  link: null,         // XQ.connect 给的链路，兜底靠它发
  voice: null,        // 挑中的那个音色对象
  ready: false,       // voiceschanged 已经来过（或等超时了）
  fellBack: 0,        // 走了几次服务端兜底（自检读它）
  lastError: '',
  _seq: 0,
  _probe: null,
  _started: false,    // 这一句到底开口没有（onstart 报的），兜底探测的判据

  _read(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  _write(k, v) { try { localStorage.setItem(k, v); } catch (e) {} },

  /** 从 hello 的 tts 段初始化。`defaultOn` 是**按当前数据源**算的（live 源是关的）。 */
  attach(link, cfg) {
    XQ.tts.link = link || null;
    cfg = cfg || {};
    XQ.tts.prosody = cfg.prosody || {};
    XQ.tts.serverOk = !!cfg.server_fallback && cfg.server_ok !== false;
    // 试音页选过的音色优先于配置文件 —— 那是这台机器自己的偏好，
    // 换机器/换人演示才该改配置。配置文件里那个关键词留一份，
    // 试音页的"恢复自动"要回到它（那才是这台机器上"自动"的含义）。
    XQ.tts.cfgKeyword = cfg.voice || '自动';
    XQ.tts.keyword = XQ.tts._read(XQ.tts.LS.voice) || XQ.tts.cfgKeyword;
    const stored = XQ.tts._read(XQ.tts.LS.on);
    XQ.tts.on = stored === '1' ? true : (stored === '0' ? false : !!cfg.default_on);
    XQ.tts.voice = XQ.tts._pick();
  },

  set(on) {
    XQ.tts.on = !!on;
    XQ.tts._write(XQ.tts.LS.on, on ? '1' : '0');
    if (!on && XQ.tts.supported) { try { speechSynthesis.cancel(); } catch (e) {} }
  },

  /**
   * 挑音色。顺序：关键词命中 > 普通话 Natural > 普通话本地 > 普通话 > 其他中文。
   *
   * ⚠️ **必须按 `zh-CN` 精确筛，不能只挑"名字带 Natural 的中文音色"。**
   * 这台机器上 17 个中文音色里除了晓晓/云希那些普通话的，还有粤语
   * （`zh-HK` 的曉曼/雲龍/曉佳）和台湾腔（`zh-TW` 的曉臻/雲哲/曉雨），
   * 而 `getVoices()` 的**顺序每次都不一样**（实测同一台机器两次调用拿到
   * 325 和 326 个，列表是慢慢填满的）。
   * 早先的写法是"取第一个名字带 Natural 的中文音色"，于是自检脚本逮到过
   * 一次挑中 **HiuGaai（粤语）** —— 小瑞开口说粤语。不是每次都那么倒霉，
   * 所以更难发现。现在普通话优先，再按名字钉一次晓晓，结果就定了。
   */
  _pick() {
    if (!XQ.tts.supported) return null;
    let all = [];
    try { all = speechSynthesis.getVoices() || []; } catch (e) { return null; }
    if (!all.length) return null;                       // 还没加载好，等 voiceschanged
    const zh = all.filter((v) => /^zh/i.test(v.lang || ''));
    const pool = zh.length ? zh : all;
    const kw = XQ.tts.keyword;
    if (kw && kw !== '自动') {
      const hit = pool.find((v) => (v.name || '').indexOf(kw) >= 0);
      if (hit) return hit;                              // 关键词没命中就继续往下走
    }
    const mandarin = pool.filter((v) => /^zh[-_]?(CN|Hans)/i.test(v.lang || ''));
    const rank = (list) => {
      const nat = list.filter((v) => /Natural/i.test(v.name || ''));
      // 几个普通话神经音色里钉一个：config 里的说明写的就是"优先晓晓"。
      const xiao = nat.find((v) => /晓晓|Xiaoxiao/i.test(v.name || ''));
      return xiao || nat[0] || list.find((v) => v.localService) || list[0] || null;
    };
    return rank(mandarin) || rank(pool);
  },

  /* ★★ 2026-09-25：左栏那块「小瑞语音 / 出声 / <音色全名>」**整块删掉了**。
     用户原话：「小瑞语音 / 出声 / Microsoft Xiaoxiao Online (Natural) —— 左边栏
     不要出现这些」。他点名的是那块牌子的**三行字**：标题、按钮上的「出声」、
     说明行里的音色全名。所以这里**不是把字改短，是把整块连根拔掉**。

     连同它的四个方法和**全部**调用点一起走：
       voiceDesc()  只被 render() 用
       btnHTML()    往左栏吐那段 HTML（唯一调用点：chrome.js 的 railHTML）
       render()     把按钮画成 on/off、往 #voiceNote 写音色名（6 个调用点）
       bind()       给 [data-voice-toggle] 挂 onclick（唯一调用点：mountChrome）
     ⚠️ 留着它们"以备将来"不行：`#voiceNote` / `[data-voice-toggle]` 已经不在 DOM
        里了，render() 会变成每次语音状态一变就查一次 null 的空转 —— 正是删时钟
        （tickClock）和气候栏（climateHTML）时踩过的同一个坑，那两次也都是连根删。

     ⚠️ **语音能力一个字没动，丢的只是"左栏那个开关"**：`XQ.tts.on` / `_pick()` /
        `_fallback()` / `XQ.speak()` 全在，设置页那张「语音播报」卡
        （settings.html 的 `#ttsSw`）开关的是**同一个 localStorage 键**，静音照样
        能静音，音色名在那一页和「关于我们」的只读表里也都还看得到。少的是
        "在座舱页想静音得回设置页"这一步。
     ⚠️ 那件事当初想说清的东西留此备查（浏览器语音合成的"在线"至少混了三件事：
        supported 支不支持 / on 按没按静音 / voice.localService 是本机合成还是
        云端神经音色 —— 其中 localService 为真的音色**断网也能出声**，标成「在线」
        正好把真相说反）—— 现在**全站没有地方显示它了**，留此备查以免以后有人
        又拿"在线/离线"两种状态去描述语音。 */

  /** 服务端兜底：把这句话发上去让 PowerShell 念。 */
  _fallback(text, opts) {
    if (!XQ.tts.serverOk || !XQ.tts.link) {
      XQ.tts.lastError = '浏览器念不出来，服务端兜底也没开';
      return false;
    }
    XQ.tts.fellBack += 1;
    /* 交给服务端念也算"小瑞开口了" —— 不然走兜底时它一直没动作，和真的哑掉
       看起来一模一样。和 onstart 那条是同一个动作，两处都要挂。 */
    XQ.mascot.react('speak');
    XQ.tts.link.send({ type: 'tts', text: text,
                       emotion: (opts && opts.emotion) || 'normal',
                       reason: (opts && opts.reason) || 'browser_failed' });
    return true;
  },

  /**
   * ★★ 2026-09-26：**把正在念的这一句当场掐掉。**
   *
   * 干什么用的：小瑞正念着，主人喊「你好小瑞」—— 服务端发一条 `ev:"halt"`，
   * 这一句立刻闭嘴，接着开始听主人的话（见 `ui/voice/loop.py` 文首第 1 条
   * 和 `barge_in_ok`）。用户原话：「它回复我话的时候 我说话为啥它听不见」。
   *
   * 🔴 **必须先推 `_seq`、再 `cancel()`，顺序不能反。**
   *    `speechSynthesis.cancel()` **同样会触发当前那条 utterance 的 `onend`**
   *    （这是浏览器的行为，不是我们的选择），而 `XQ.speak` 的 `onend` 只在
   *    `token === XQ.tts._seq` 时才回调 `done`（见 `XQ.speak` 里 onend 的注释）。
   *    不推的话，"被掐断"会被页面当成"念完了"→ 白回一条 `voice_spoken` →
   *    服务端把**刚打开的 LISTEN 推回追问窗口**，还掐掉新一轮的看门狗
   *    （那两道卫兵在 `server.py` 的 `voice_spoken` 分支里，是第二道防线；
   *    第一道就是这一推）。
   *
   * ⚠️ `_probe` 也要清掉：那是"浏览器到底动没动"的兜底探测（见 `_probe` 的注释），
   *    不清的话它到点会拿这一句去走**服务端兜底** —— 主人刚把话头抢过来，
   *    服务端却开始念上一句，正好是最不该发生的那件事。
   */
  halt() {
    ++XQ.tts._seq;
    clearTimeout(XQ.tts._probe);
    XQ.tts._probe = null;
    try { speechSynthesis.cancel(); } catch (e) {}
  },

  _init() {
    if (!XQ.tts.supported) { XQ.tts.ready = true; return; }
    const settle = () => {
      const v = XQ.tts._pick();
      if (v) XQ.tts.voice = v;
      XQ.tts.ready = true;
    };
    try {
      if (typeof speechSynthesis.addEventListener === 'function') {
        speechSynthesis.addEventListener('voiceschanged', settle);
      } else {
        speechSynthesis.onvoiceschanged = settle;
      }
    } catch (e) {}
    settle();              // 再次访问这个站点时，这一刻可能已经有值了
    setTimeout(settle, 1500);   // 等不到事件也不能一直空着
  },
};
XQ.tts._init();

/**
 * 让小瑞说一句。**返回"接受了没有"，不是"念完了没有"** —— 语音是后台的事，
 * 不该让调用方等它。
 *
 *   XQ.speak(text, { emotion: 'alert' })      // emotion 来自服务端的 say 消息
 *
 * 可选回调（chat.html 那个语音条用它们显示"正在念"和实测时长）：
 *   started()      —— 浏览器**真的开口了**的那一刻。走服务端兜底时不会触发，
 *                     因为那条路我们看不到进度，宁可不动也别假装在动。
 *   done(sec)      —— 浏览器念完了，sec 是实测秒数。
 *
 * 返回 false 且**不出声也不兜底**的三种情况，这是有意的：
 * 用户按了静音、这一页在后台、没有文字可念。
 */
XQ.speak = function (text, opts) {
  opts = opts || {};
  const t = String(text == null ? '' : text).trim();
  if (!t) return false;
  if (!XQ.tts.on) return false;

  /* 后台标签页不出声。
     ⚠️ 这里**故意只看 visibility，不看 hasFocus()** —— 后者会把"你点到终端窗口
     看日志"也算成后台，而那恰恰是演示时最常见的样子，小瑞会毫无道理地哑掉。
     而本项目真正要防的"两个说话页同时开口"，在同一个 Kiosk 窗口里就是
     "另一个标签页 hidden"，visibility 这一条已经覆盖了。
     （并排两个窗口仍然会双声，这个不做跨页仲裁 —— 不值当。） */
  if (document.visibilityState && document.visibilityState !== 'visible') return false;

  if (!XQ.tts.supported) return XQ.tts._fallback(t, opts);
  if (!XQ.tts.voice) XQ.tts.voice = XQ.tts._pick();      // 事件还没来也救得回来
  if (!XQ.tts.voice) return XQ.tts._fallback(t, opts);

  // 新的一句把上一句顶掉：小瑞说的话是"现在这句"，不是播客队列。
  const token = ++XQ.tts._seq;
  const u = new SpeechSynthesisUtterance(t);
  u.voice = XQ.tts.voice;
  u.lang = XQ.tts.voice.lang || 'zh-CN';
  const p = XQ.tts.prosody[opts.emotion] || XQ.tts.prosody.normal || null;
  if (p) { if (p.rate) u.rate = p.rate; if (p.pitch) u.pitch = p.pitch; }
  const t0 = Date.now();
  XQ.tts._started = false;                 // 每次开口都重算，兜底探测要看它
  u.onstart = () => {
    XQ.tts._started = true;
    /* 小瑞开口了。挂在这里而**不是调用点的 started 回调**上：一是所有调用方
       都自动有（不用挨个改十几个调用点），二是走服务端兜底那条路也要算"开口了"
       （兜底在 _fallback 里，两处都挂）。 */
    if (token === XQ.tts._seq) XQ.mascot.react('speak');
    if (opts.started && token === XQ.tts._seq) { try { opts.started(); } catch (e) {} }
  };
  u.onerror = (e) => {
    XQ.tts.lastError = '浏览器念不出来：' + ((e && e.error) || '未知原因');
    if (token === XQ.tts._seq) XQ.tts._fallback(t, opts);
  };
  u.onend = () => {
    XQ.tts.lastError = '';
    // token 对不上说明这句是被下一句顶掉的（cancel 也会触发 onend），
    // 那就别把上一句的时长报给下一句。
    if (opts.done && token === XQ.tts._seq) {
      try { opts.done((Date.now() - t0) / 1000); } catch (e) {}
    }
  };

  try {
    try { speechSynthesis.cancel(); } catch (e) {}
    speechSynthesis.speak(u);
  } catch (e) {
    XQ.tts.lastError = 'speak 抛错：' + (e && e.message ? e.message : e);
    return XQ.tts._fallback(t, opts);
  }

  if (!XQ.tts.serverOk || !XQ.tts.link) return true;

  /* 兜底探测。**这一步是防双声的关键，不能省，而且不能只探一次。**
     为什么不能只探一次：在线神经音色（晓晓那类）第一句要先联网合成，
     起声慢的时候能到 1 秒上下。早先这里只探一次、600 ms 就下结论，结果是
     浏览器刚要开口、服务端也被叫起来了 —— 两个声音叠着念同一句，
     正好是这一步想防的那个后果。
     所以改成两级：600 ms 没动静再等一次，1.6 s 仍然没动静才认定它念不出来。

     ⚠️ 判据是 `_started || speaking`（**真的开口了**），**故意不看 `pending`**：
     `pending` 只说明"排上队了"，不说明"轮到你念了"。而"一直排队、永远轮不上"
     恰恰是最难发现的那种坏法 —— 没有报错、没有声音、`pending` 还一直是 true，
     要是把它当成"它好好的"，兜底就永远不会触发，人看到的就是"点了没反应"。
     这条是自检脚本逼出来的：headless 里那句就卡在 pending，于是两边都没出声。
     （同一时刻只会有一条待念 —— `speak()` 每次都先 `cancel()`，所以正常排队
     这件事不会造成误判。） */
  clearTimeout(XQ.tts._probe);
  const probe = (delay) => {
    XQ.tts._probe = setTimeout(() => {
      if (token !== XQ.tts._seq) return;                 // 已经换下一句了，别管
      if (XQ.tts._started) return;                       // onstart 报过了，最硬的证据
      const ss = window.speechSynthesis;
      if (ss && ss.speaking) return;                     // 正在念
      if (delay < 1600) { probe(1600); return; }         // 再给一次机会
      XQ.tts._fallback(t, opts);
    }, delay);
  };
  probe(600);
  return true;
};

/* ---------------------------------------------------------------- 语音输入 */
/**
 * 语音输入。**双路，恰好交付一条**。
 *
 *   主路：浏览器的 `SpeechRecognition` —— Edge 上零安装、说三五个字几百毫秒，
 *         而且识别在浏览器/系统那边做，服务端一点 CPU 都不用。
 *   兜底：把这段录音 `POST` 给服务端，让本地 whisper 认（见 `ui/asr.py`）。
 *
 * ⚠️ **判据是"恰好一条"，不是"至少一条"**（和 TTS 那边形状像但方向相反）：
 *   TTS 判「有没有开口」，两条路不排斥（兜底本来就是主路没成之后的动作）；
 *   语音输入两条路**都出结果 = 同一次说话被识别两遍、小瑞答两遍**，所以必须互斥。
 *
 * ⚠️ **`_done` 存的是 token，不是布尔。** 这是这一整块里最容易写错、也最难查的
 * 一处：布尔值在"连点两次"时有个真实窗口 —— 第 1 次交付完把 `_done` 置真，
 * 第 2 次 click 又把它重置为假，此时第 1 次那条迟到的 `onresult` 回来，居然
 * 还能通过检查再交付一次。表现是**偶尔把小瑞的话说两遍**，复现不了。
 * 存 token 就没有这个问题：迟到的结果带的是**旧 token**，`tok !== _seq` 直接丢掉。
 * 因此还有一条配套纪律：**`_seq` 只在点击那一刻自增一次，任何一条路内部都不许
 * 再动它** —— 兜底那条路要是自己 `++_seq`，上面整套保护当场失效。
 *
 * ⚠️ 麦克风是**点一下开始、再点一下结束**，不是按住说话：`mousedown/mouseup`
 * 在触屏和键盘上行为不一致（键盘上根本没有 mouseup），而且它和"静音自动停"
 * 是两套语义，混在一起必然打架。座舱里两手都在方向盘上，"点一下就走开"更现实。
 */
/* 「语音输入」这条路（点麦克风按钮 → 录一段 → 一次性 POST 上来）**最多录多久**。
   ⚠️ 它**不是** `hello.asr.max_s` —— 那个数 2026-09-26 起是"识别器能吃下多长的
      音频"（300 s，从 `ui/asr.py` 的 `DEFAULT_MAX_S` 来的，常听那条路拿它推单句
      上限）。录音这一路是真的把整段 WAV 一次性 POST 上来，所以它的上限由 **HTTP
      那一层**定：16 kHz / 16 bit / 单声道 = 32 KB/s，aiohttp 的 `client_max_size`
      默认 1 MB ⟹ 天花板 ≈ 31 s（再往上服务端会 413，前端只看到"请求失败"，
      完全看不出是因为音频太长）。取 30 s 留一点余量。
   本来这个位置写的就是 `max_s`（那时它等于 8 s，两个含义恰好重合）；max_s 一抬到
   300，再不分开就等于"点一下麦克风，录到 9.6 MB 然后 413"。 */
const ASR_REC_MAX_S = 30;

XQ.asr = {
  /* ⚠️ 在**用的时候**读 `window`，不在加载时定死 —— 自测脚本要在页面脚本跑之前
     装一个桩（永远不触发任何事件的那种），定死了就换不掉。 */
  get SR() { return window.SpeechRecognition || window.webkitSpeechRecognition || null; },

  cfg: null,            // hello.asr 那一段
  link: null,
  state: 'idle',        // idle | listening | sending | failed
  on: false,
  browserDead: false,   // 浏览器那条路试过、证明不行 —— 本次会话不再碰它
  lastText: '',
  lastWhy: '',

  _seq: 0,              // 只在点击时自增（见文件头）
  _done: 0,             // 已经交付过的 token。**不是布尔**
  _btn: null,
  _submit: null,
  _tok: 0,
  _rec: null,           // SpeechRecognition 实例
  _probe: null,         // "浏览器到底动没动"的定时器
  _timer: null,         // ASR_REC_MAX_S 自动收尾
  _local: false,        // 现在这条是本地录音那条路（决定 stop 时要不要往上送）
  _stream: null, _ctx: null, _src: null, _proc: null, _sink: null,
  _chunks: [], _n: 0, _peak: 0, _quiet: true, _sr: 16000,

  attach(link, cfg) {
    XQ.asr.link = link || null;
    XQ.asr.cfg = cfg || {};
    // ⚠️ 这里**不去重置 `browserDead`**。它记的是"这个浏览器行不行"，
    // 跟服务端连没连上无关；重连一次就把结论丢掉，等于每断一次线都再白等
    // 一个探测窗口。要用回浏览器那条路，刷页面（新的会话）是有意为之的代价。
    XQ.asr._render();
  },

  /** 现在能不能用。**按钮永不置灰**是硬规矩：置灰了人就不知道为什么，
      点了给一句具体的话才是对的（这里返回的是"点了该说什么"）。 */
  ready() {
    if (!XQ.asr.cfg) return '还没连上座舱服务（用 run_ui.bat 启动服务端）';
    return '';
  },

  bind(btn, opts = {}) {
    XQ.asr._btn = btn;
    XQ.asr._submit = opts.submit || null;
    btn.onclick = () => XQ.asr.toggle();
    btn.removeAttribute('disabled');   // 保险丝：谁给它加了 disabled 都当场撤掉
    btn.setAttribute('aria-pressed', 'false');
    btn.title = '点一下开始说话，再点一下结束';
    XQ.asr._render();
  },

  toggle() { if (XQ.asr.on) XQ.asr.stop('manual'); else XQ.asr.start(); },

  start() {
    const no = XQ.asr.ready();
    if (no) { XQ.flash(no); return; }
    if (XQ.asr.on) return;

    /* ⚠️ **唯一**一处自增。下面两条路只读它、绝不改它。 */
    XQ.asr._seq += 1;
    XQ.asr._tok = XQ.asr._seq;

    XQ.asr.on = true;
    XQ.asr.state = 'listening';
    XQ.asr.lastText = '';
    XQ.asr.lastWhy = '';
    XQ.mascot.react('listen');          // 开始听了 -> 眨眼
    XQ.asr._render();

    const c = XQ.asr.cfg || {};
    const useBrowser = !XQ.asr.browserDead && String(c.prefer || 'browser') !== 'local'
                       && !!XQ.asr.SR;
    if (useBrowser) XQ.asr._startBrowser(XQ.asr._tok);
    else XQ.asr._startLocal(XQ.asr._tok);

    /* 录多久：见 `ASR_REC_MAX_S`。取两者小的那个 —— 服务端把识别器的上限往下调
       （比如换个小模型）时，这里跟着变短，不会录出一段识别器拒收的音频。 */
    const maxs = Math.min(Number(c.max_s) || ASR_REC_MAX_S, ASR_REC_MAX_S);
    XQ.asr._timer = setTimeout(() => XQ.asr.stop('timeout'), maxs * 1000);
  },

  /** 收尾。`why` 只是给日志/排错用，交付与否不靠它。 */
  stop(why) {
    if (!XQ.asr.on) return;
    XQ.asr.on = false;
    clearTimeout(XQ.asr._timer); XQ.asr._timer = null;
    clearTimeout(XQ.asr._probe); XQ.asr._probe = null;
    XQ.asr._stopBrowser();

    /* 本地那条路：**先把音频收下来、再放掉设备**。反过来的话 `_stopRec()` 一关
       AudioContext，`_chunks` 就再也拿不齐了。 */
    const tok = XQ.asr._tok;
    let blob = null;
    if (XQ.asr._local) {
      XQ.asr._local = false;
      if (XQ.asr._n > 0) blob = XQ.asr._wav();
    }
    XQ.asr._stopRec();
    if (XQ.asr.state === 'listening') XQ.asr.state = 'idle';
    XQ.asr._render();

    /* 往上送。三个前提缺一不可：
         `tok === _seq`   —— 这一次点击还是当前那一次；
         `_done !== tok`  —— 这一次**还没**交付过（`_deliver`/`_fail` 都把它置成 tok，
                             所以交付完、或者已经判失败时，这里不会再送一遍）；
         `blob`           —— 真录到东西了（静音那段已经被丢掉，`_n` 清零）。
       `_done` 那一条就是"点了结束键之后又发一遍"的挡板。 */
    if (blob && tok === XQ.asr._seq && XQ.asr._done !== tok) XQ.asr._send(tok, blob);
    else if (why === 'timeout' && !XQ.asr.lastText) XQ.flash('说完了吗？我先停了');
  },

  /* -------------------------------------------------------------- 主路 */
  _startBrowser(tok) {
    let rec;
    try { rec = new (XQ.asr.SR)(); }
    catch (e) { XQ.asr._browserGaveUp(tok, '这个浏览器起不了语音识别'); return; }
    rec.lang = 'zh-CN';
    rec.interimResults = false;   // 只要最终结果：中间结果会把同一句话交付两遍
    rec.continuous = false;
    rec.maxAlternatives = 1;
    XQ.asr._rec = rec;

    let sawAnything = false;
    /* 「它到底动没动」的探测。⚠️ 探的是 onstart/onspeechstart 这类**起步事件**，
       不是"识别出结果" —— 起步事件正常在 100 ms 内就到，所以这个窗口可以很短，
       短到用户在窗口里说的话几乎不会丢。要是拿"出结果"当判据，窗口得开到好几秒，
       那才真会丢掉开头。 */
    const first = Number((XQ.asr.cfg || {}).first_ms) || 900;
    XQ.asr._probe = setTimeout(() => {
      if (!sawAnything) XQ.asr._browserGaveUp(tok, '浏览器那条路没反应（没麦克风权限 / kiosk 里被禁）');
    }, first);

    const alive = () => { sawAnything = true; clearTimeout(XQ.asr._probe); XQ.asr._probe = null; };
    rec.onstart = alive;
    rec.onaudiostart = alive;
    rec.onspeechstart = alive;
    rec.onresult = (ev) => {
      alive();
      let text = '';
      for (let i = ev.resultIndex; i < ev.results.length; i++) {
        if (ev.results[i].isFinal) text += ev.results[i][0].transcript;
      }
      if (text) XQ.asr._deliver(tok, text, '浏览器');
    };
    rec.onerror = (ev) => {
      const e = (ev && ev.error) || '未知';
      // `no-speech` 是**正常结果**：人没说话。不该因此判浏览器这条路死了，
      // 也不该转本地（本地同样什么都没有）。
      if (e === 'no-speech') { XQ.asr._deliver(tok, '', '浏览器：没听到说话'); return; }
      XQ.asr._browserGaveUp(tok, `浏览器识别失败：${e}`);
    };
    rec.onend = () => {
      // 没交付就结束（人没说话、或者被浏览器自己收了）。**这里不转本地** ——
      // 转不转由上面那个探测窗口说了算，它才是"这条路行不行"的判据。
      if (!XQ.asr.lastText && XQ.asr.on) XQ.asr.stop('browser-end');
    };
    try { rec.start(); }
    catch (e) { XQ.asr._browserGaveUp(tok, `浏览器起不来：${e && e.message || e}`); }
  },

  /** 浏览器那条路证明不行：记下来（本次不再试），然后**用同一个 token** 转本地。 */
  _browserGaveUp(tok, why) {
    XQ.asr.browserDead = true;
    clearTimeout(XQ.asr._probe); XQ.asr._probe = null;
    XQ.asr._stopBrowser();
    if (tok !== XQ.asr._seq || !XQ.asr.on) return;   // 已经翻篇了
    XQ.flash(`${why} —— 改用本机识别`);
    XQ.asr._startLocal(tok);
  },

  _stopBrowser() {
    const rec = XQ.asr._rec;
    XQ.asr._rec = null;
    if (!rec) return;
    // 先摘掉回调再 abort：abort 会同步触发 onerror/onend，留着的话它们会
    // 拿一个已经作废的 token 去走一遍 _browserGaveUp / stop。
    rec.onstart = rec.onaudiostart = rec.onspeechstart = null;
    rec.onresult = rec.onerror = rec.onend = null;
    try { rec.abort(); } catch (e) {}
  },

  /* -------------------------------------------------------------- 兜底 */
  async _startLocal(tok) {
    if (tok !== XQ.asr._seq) return;
    const c = XQ.asr.cfg || {};
    if (XQ.isFile()) { XQ.asr._fail(tok, '这一页是 file:// 直接打开的，没有服务端能转写'); return; }
    // 服务端那条路能不能干活，hello 里已经说清楚了。**不能干活就别录** ——
    // 让人对着麦克风说完一整句再告诉他"本机没装"，是最不体面的失败方式。
    if (!c.ok) {
      XQ.asr._fail(tok, `${c.engine || '本机识别不可用'}${c.install_hint ? ' —— ' + c.install_hint : ''}`);
      return;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      XQ.asr._fail(tok, '这个浏览器不给用麦克风（getUserMedia 不可用）'); return;
    }

    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); }
    catch (e) {
      XQ.asr._fail(tok, '没拿到麦克风权限（浏览器地址栏里那个麦克风图标是关着的）'); return;
    }
    if (tok !== XQ.asr._seq || !XQ.asr.on) {          // 等权限这会儿人又点了一下
      stream.getTracks().forEach((t) => t.stop()); return;
    }
    XQ.asr._stream = stream;

    /* ⚠️ 采样率直接要 16000，让**浏览器**去重采样 —— JS 里一行重采样都不用写，
       而 whisper 内部认死 16k 且没有任何检查（见 ui/asr.py 文件头第 3 个陷阱）。 */
    const AC = window.AudioContext || window.webkitAudioContext;
    const ctx = new AC({ sampleRate: 16000 });
    if (ctx.state === 'suspended') { try { await ctx.resume(); } catch (e) {} }
    XQ.asr._ctx = ctx;
    XQ.asr._chunks = []; XQ.asr._n = 0; XQ.asr._peak = 0; XQ.asr._quiet = true;
    /* ⚠️ 用**context 实际给的**采样率，不是我们请求的那个。请求 16000 一般都会给，
       但"一般"不是"一定"（不同声卡/浏览器策略下会被顶到 48000），而 WAV 头里
       写错采样率正是 ui/asr.py 文件头第 3 个陷阱：whisper 内部没有任何检查，
       它会照着错的数去理解波形 → 放慢几倍 → 胡话，且不报错。
       照实写进头里，服务端那边会重采样（`wav_bytes_to_float32`）。 */
    XQ.asr._sr = ctx.sampleRate || 16000;
    const SR = XQ.asr._sr;

    const src = ctx.createMediaStreamSource(stream);
    // ScriptProcessor 是过时接口，但它给的是**已经在目标采样率上的时域样本**，
    // 换 AudioWorklet 得再写一个 worker 文件，为这点事不值当。Edge 上照常可用。
    const proc = ctx.createScriptProcessor(4096, 1, 1);
    proc.onaudioprocess = (ev) => {
      const d = ev.inputBuffer.getChannelData(0);
      XQ.asr._chunks.push(new Float32Array(d));
      XQ.asr._n += d.length;
      for (let i = 0; i < d.length; i++) {
        const a = Math.abs(d[i]);
        if (a > XQ.asr._peak) XQ.asr._peak = a;
      }
      /* 静音保护：整段几乎全是零的时候**别往上送**。Windows 关了麦克风权限时，
         设备给的是**全零音轨且不报错** —— 不拦的话就是把一段静音送去识别，
         而 whisper 对静音会自信地吐一句不存在的话（幻视）。
         ⚠️ `_fail` 会把 `_done` 置成这个 token，所以 `stop()` 里那道
         "`_done !== tok` 才往上送"的闸门自动把这段静音挡在门外 —— 不用在这里
         再手动清 `_chunks`，清两处迟早漏一处。 */
      const mins = Number(XQ.asr.cfg.min_s) || 0.4;
      if (XQ.asr._n > SR * mins) {
        XQ.asr._quiet = XQ.asr._peak < 0.012;
        if (XQ.asr._quiet && XQ.asr._n > SR * (mins + 1.2)) {
          XQ.asr._fail(tok, '麦克风里一直是静的（没拾到声音，或者这台机器没开麦克风权限）');
        }
      }
      // 录多久的精确收尾交给 AudioContext 自己给样本数，别用墙上时间猜。
      // 上限见 `ASR_REC_MAX_S`（**不是** `max_s`：那个数只管识别器能吃多长）。
      const maxs = Math.min(Number(XQ.asr.cfg.max_s) || ASR_REC_MAX_S, ASR_REC_MAX_S);
      if (XQ.asr._n > SR * maxs) XQ.asr.stop('timeout');
    };
    // 必须接到一个"静音"的出口才会被回调；直接接 destination 会变成啸叫。
    const sink = ctx.createGain();
    sink.gain.value = 0;
    src.connect(proc); proc.connect(sink); sink.connect(ctx.destination);
    XQ.asr._src = src; XQ.asr._proc = proc; XQ.asr._sink = sink;
    // 到这一步才算"录音这条路真的架起来了"，`stop()` 据此决定要不要把音频送上去。
    XQ.asr._local = true;
  },

  _stopRec() {
    const { _src: src, _proc: proc, _sink: sink, _ctx: ctx, _stream: st } = XQ.asr;
    XQ.asr._src = XQ.asr._proc = XQ.asr._sink = null;
    if (proc) { proc.onaudioprocess = null; try { proc.disconnect(); } catch (e) {} }
    if (src) { try { src.disconnect(); } catch (e) {} }
    if (sink) { try { sink.disconnect(); } catch (e) {} }
    if (ctx) { try { ctx.close(); } catch (e) {} }
    // 摄像头踩过的坑：不显式放掉，设备就一直被占着（灯还亮着）。
    if (st) st.getTracks().forEach((t) => t.stop());
    XQ.asr._ctx = XQ.asr._stream = null;
  },

  /** 把录到的浮点样本拼成 16 bit 单声道 WAV。采样率写 `_sr`（AudioContext 实际给的那个）。 */
  _wav() {
    const chunks = XQ.asr._chunks, n = XQ.asr._n;
    const SR = XQ.asr._sr || 16000;
    XQ.asr._chunks = [];
    if (!n) return null;
    const buf = new ArrayBuffer(44 + n * 2);
    const v = new DataView(buf);
    const put = (off, s) => { for (let i = 0; i < s.length; i++) v.setUint8(off + i, s.charCodeAt(i)); };
    put(0, 'RIFF'); v.setUint32(4, 36 + n * 2, true); put(8, 'WAVE');
    put(12, 'fmt '); v.setUint32(16, 16, true); v.setUint16(20, 1, true);
    v.setUint16(22, 1, true); v.setUint32(24, SR, true);
    v.setUint32(28, SR * 2, true); v.setUint16(32, 2, true);
    v.setUint16(34, 16, true);
    put(36, 'data'); v.setUint32(40, n * 2, true);
    let o = 44, k = 0;
    const one = new Float32Array(1);
    for (const c of chunks) {
      for (let i = 0; i < c.length && k < n; i++, k++) {
        one[0] = Math.max(-1, Math.min(1, c[i]));
        // 负半轴乘 0x8000、正半轴乘 0x7FFF：对称地乘 32767 会让负方向差一格，
        // 听不出来，但"逐样本一致"这类对拍会被它绊住。
        v.setInt16(o, one[0] < 0 ? one[0] * 0x8000 : one[0] * 0x7FFF, true);
        o += 2;
      }
    }
    return new Blob([buf], { type: 'audio/wav' });
  },

  async _send(tok, blob) {
    XQ.asr.state = 'sending'; XQ.asr._render();
    let r;
    try {
      r = await fetch('/asr', { method: 'POST', body: blob });
    } catch (e) {
      XQ.asr._fail(tok, 'POST /asr 没发出去（服务端还在吗？）'); return;
    }
    if (!r.ok) { XQ.asr._fail(tok, `服务端回了 ${r.status}`); return; }
    let d = {};
    try { d = await r.json(); } catch (e) { XQ.asr._fail(tok, '服务端回的不是 JSON'); return; }
    XQ.asr._deliver(tok, d.text || '', d.why || '');
  },

  /* -------------------------------------------------------------- 交付 */
  /**
   * 唯一出口。**两条路都只能走这里**，而且这里保证"恰好交付一次"。
   *
   * 判据两条，缺一条就会漏：
   *   `tok !== _seq`  —— 这是**上一次**点击的结果（迟到了），丢掉；
   *   `_done === tok` —— 这一次**已经**交付过（两条路都出结果了），丢掉。
   * 第二条正是"两条路都出结果"时挡住第二遍的那一下。
   */
  _deliver(tok, text, how) {
    if (tok !== XQ.asr._seq) return false;
    if (XQ.asr._done === tok) return false;
    XQ.asr._done = tok;
    if (XQ.asr.on) XQ.asr.stop('delivered');

    text = String(text || '').trim();
    if (!text) {
      // 空串 = 没听清，**绝不用一段编的话填空**。把 why 露出来，人才知道
      // 是"没听到"还是"没装"还是"太短"。
      XQ.mascot.react('missed');
      XQ.flash(`没听清，再说一遍？（${how || '没有返回文字'}）`);
      return true;
    }
    XQ.mascot.react('heard');
    XQ.asr.lastText = text;
    /* 先说原文再交付。whisper 和浏览器都会听错，而"小瑞答非所问"的时候，
       人**完全查不出**是听错了还是答错了 —— 把原文露一次是最便宜的诚实。 */
    XQ.flash(`听到：${text}`);
    if (XQ.asr._submit) XQ.asr._submit(text);
    return true;
  },

  _fail(tok, why) {
    XQ.asr.lastWhy = why;
    if (tok !== XQ.asr._seq) return;
    if (XQ.asr._done === tok) return;
    XQ.asr._done = tok;
    XQ.asr.state = 'failed';
    if (XQ.asr.on) XQ.asr.stop('failed');
    XQ.mascot.react('missed');          // 没听清 -> 疑问脸
    XQ.asr._render();
    XQ.flash(why);
  },

  /* -------------------------------------------------------------- 画 */
  _render() {
    const b = XQ.asr._btn;
    if (!b) return;
    b.classList.toggle('rec', XQ.asr.on);
    b.setAttribute('aria-pressed', XQ.asr.on ? 'true' : 'false');
    b.title = XQ.asr.on ? '正在听 —— 点一下结束' : '点一下开始说话，再点一下结束';
  },

  /** 给设置页/只读区的一句话。状态和出路都说清楚，不编。 */
  desc() {
    const c = XQ.asr.cfg;
    if (!c) return '还没连上座舱服务，看不出本机识别能不能用';
    const way = c.ok ? '' : (c.install_hint ? `　出路：${c.install_hint}` : '');
    return `${c.engine}（${c.ok ? '能干活' : '干不了活'}）${way}`
         + `　偏好：${c.prefer === 'local' ? '直接用本机' : '先问浏览器'}`
         + `　这次会话里浏览器那条路：${XQ.asr.browserDead ? '试过，不行' : '还没试过'}`;
  },
};

/* ---------------------------------------------------------------- 连接 */
/**
 * 开一条 WebSocket。opts:
 *   onHello(h) / onState(s) / onSay(d) / onInfo(text) / onDown(bool)
 *
 * 断线自动重连。**连不上时调 onDown(true)**，页面据此把数字换成「—」——
 * 打开 `file://` 直接看页面时就是这个状态，那是正常的，不该显示成假数据。
 */
XQ.connect = function (opts = {}) {
  let ws = null, retry = null, down = false;

  const setDown = (d) => { if (d !== down) { down = d; opts.onDown && opts.onDown(d); } };

  /* 先建出 api 再连：hello 一到就要把链路交给 XQ.tts（服务端兜底要靠它发）。
     消息是异步的，理论上等 api 建好再连更保险，但 `open()` 里只是发起连接，
     真正的 onmessage 一定晚于这一行返回。 */
  const api = {
    send: (o) => { if (ws && ws.readyState === 1) ws.send(JSON.stringify(o)); },
    get online() { return !down; },
  };

  const open = () => {
    if (XQ.isFile()) { setDown(true); return; }      // file:// 下没有服务端，别白试
    try {
      ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
    } catch (e) { setDown(true); return; }

    ws.onopen = () => setDown(false);
    ws.onmessage = (ev) => {
      let m; try { m = JSON.parse(ev.data); } catch (e) { return; }
      const d = m.data || {};
      if (m.type === 'hello') {
        // ⚠️ 交给 XQ.tts **在 onHello 之前**：页面自己的 onHello 里可能就开口
        // 说话了（chat.html 的开场白那样），那时配置必须已经就位。
        XQ.tts.attach(api, d.tts);
        // 语音输入那段同理：挂在 XQ.tts 后面（它俩互不相干，但顺序上先语音输出
        // 再语音输入读着顺），而且同样要在 `onHello` 之前 —— 页面的 onHello 里
        // 可能就调 `XQ.asr.bind()` 去画麦克风按钮的状态。
        if (XQ.asr && XQ.asr.attach) XQ.asr.attach(api, d.asr);
        opts.onHello && opts.onHello(d);
      }
      else if (m.type === 'state') { XQ.Hist.push(d); opts.onState && opts.onState(d); }
      else if (m.type === 'say') opts.onSay && opts.onSay(d);
      // ⚠️ 第二个参数是整个 payload，不只是文案：驾驶监测页那颗换源按钮要靠
      //    `d.source_switch` / `d.ok` 复位「正在接入…」，**不能**去匹配中文文案
      //    （那是靠人肉维持的一致，改一个字这里就悄悄失效）。老页面只取第一个
      //    参数，多传一个不影响它们。
      else if (m.type === 'info') opts.onInfo && opts.onInfo(d.text, d);
      // ★ 2026-09-25：给"只有某一页关心"的消息留的口子（试音台的
      //   `tts_voices` / `tts_set` 就是）。**在主干之后无条件调一次**：
      //   它是个观察口，标准那几种也会路过来，页面别在这儿重复处理它们。
      //   不写这个口子的话，每加一种页内消息就要来改这个函数一次，
      //   而改它等于动全站每一个页面。
      if (opts.onMsg) opts.onMsg(m.type, d);
    };
    ws.onclose = () => { setDown(true); clearTimeout(retry); retry = setTimeout(open, 1800); };
    ws.onerror = () => {};
  };
  open();

  return api;
};
