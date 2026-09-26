/* =========================================================================
   座舱主界面（清醒 / 轻度疲劳 / 中度疲劳 / 重度疲劳）的逻辑。
   -------------------------------------------------------------------------
   这里**不做任何判断**。疲劳档位、安全级别、注意力全都是服务端
   （ui/state.py + src/fuse.py 的真实判决）推出来的，前端只负责画。
   改判据要去改 src/ —— 否则界面上看到的东西会跟 `src/fuse.py` 的真实行为对不上。

   ★ 2026-09-24「只做疲劳」：**整页外观跟「疲劳档位」（severity）**，四档
   清醒/轻度/中度/重度。上一版跟的是支路一的**类别**（normal/glance/phone/fatigue），
   那是"分心"还在的时候定的；三类之后支路一只剩 L0/L3 两档，按它上色的话
   轻度/中度永远变不出黄和橙黄，大标题还会和旁边「疲劳程度」那一行自相矛盾。

   ⚠️ 界面上一共**两套名字**，别混：
     · **档位** normal/mild/moderate/severe —— 驱动 `data-sev` 配色、大标题、
       小瑞的表情和话（`XQ.LV` 那张表）。它来自 `ui/state.py` 的 severity。
     · **类别** normal/phone/fatigue —— 支路一**模型自己的输出**，只出现在
       「疲劳概率」那三条和 `attention`（头部持续低垂 / 疲劳点头）上。**键名不许改**
       （`probs` 的键、id 都是拿它拼的）。
       ⚠️ 「不许改」说的是**键名**，不是屏幕上那行字：2026-09-24 深夜按用户原话，
          `phone` 那一类在首页上的**显示名**从「低头看手机」改成了「头部持续低垂」
          （`ui/state.py` 的 attention 同步改了，否则同一张卡里会冒出两个名字）。
          改显示名要连 `_check_alarm.py` / `_check_grade.py` 里的字面量一起看。

   顶栏 / 左导航 / 底栏 / 时钟在 chrome.js；WebSocket / 历史 / 图表在 live.js。
   ========================================================================= */
'use strict';

const $ = (id) => document.getElementById(id);
const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
/* 「拿不到元素就静默跳过」。★ 2026-09-24（第五次改版）新增。
   -------------------------------------------------------------------------
   首页从"一页塞下所有实时块"改成了**总览页** —— 摄像头画面、支路一/二的
   概率条、支路二的原始量、底部对话栏整块搬去了驾驶监测页（detail.html）。
   于是这一页里**每一个实时块都是可选的**，`app.js` 不能再无条件去写它。

   ⚠️ 这不是"防御性编程"，是**必需**：`$('x').textContent = y` 在元素不存在时
      是 `null.textContent`，当场 TypeError；而它在 **8 Hz 的 render()** 里，
      抛一次之后整个 onState 就断了 —— 表现是"服务在跑、页面一个数都不动"，
      控制台之外完全看不出是这里。
   ⚠️ 「可选」只对**搬走的**那些块成立。留在首页的（`#sevName` / `#rPc` /
      `#rPose` / `#barLevel` / `#xqPill` …）**故意保持不带守卫的直接写法** ——
      那几处是"这一页必须有这些元素"的**断言**：改版时漏掉一个，
      当场抛比静默不显示好查得多。 */
const on = (id, fn) => { const e = $(id); if (e) fn(e); };
const ICONS = XQ.ICON;                      // 全站一张图标表，见 live.js
/* toast 在 live.js 里（十页共用一份）。⚠️ 这里必须**先赋值再用** ——
   `onInfo: flash` 是取值不是引用，未定义的话整段 connect() 直接抛
   ReferenceError，表现是"服务在跑但页面一个数都不动"，很难看出原因。 */
const flash = XQ.flash;

/* 答辩时要能把每一档的稿**稳定地翻出来**，所以给一个 ?sev= 定位。
   ---------------------------------------------------------------------
   它做的事是：**切到演示数据，并把演出时钟挪到那一档**（server 的 seek）。
   刻意**不做**"只锁外观、数字照样实时"—— 那样会把「疲劳驾驶」的标题配上一排
   正常档的数字，看的人只会当成 bug，而且那确实是在骗人。现在标题、配色、
   小瑞的台词、数字全来自同一段演示数据，是自洽的。
   页面上照样挂「演示锁定」的标记：这批数据是编的，这件事不能藏。

   ★ 2026-09-24「只做疲劳」：合法值跟着演示的**段名**走，现在是**五个**
     （见 ui/sources.py 的 `DemoSource.arc`）：normal / mild / moderate / phone / fatigue。
   ⚠️ 段名和 `data-sev` 那四个档位键**现在只差最后两个**：`phone` 和 `fatigue`
      是**重度疲劳的两个演出入口**（低头看手机 / 疲劳点头），它们的档位都是
      `severe`。要单独截"低头"或"点头"那一段就得能定位到它们，所以留着这两个键。
   ⚠️ `severe` 收成 `fatigue` 的**别名**：`severe` 是档位名（通用），演示里
      真正演"点头"的是 `fatigue` 段，所以通用名指向它。两个写法都认。 */
const PIN_ALIAS = { severe: 'fatigue' };
const PIN_KEYS = ['normal', 'mild', 'moderate', 'phone', 'fatigue'];
const PIN = (() => {
  const v = new URLSearchParams(location.search).get('sev');
  const k = PIN_ALIAS[v] || v;
  return PIN_KEYS.indexOf(k) >= 0 ? k : null;
})();
const PIN_NO = {
  normal: '01 清醒', mild: '02 轻度疲劳', moderate: '03 中度疲劳',
  phone: '04 重度疲劳·低头', fatigue: '05 重度疲劳·点头',
};
/* 演出是五段，各 30~40 秒：清醒 0~40 / 轻度 40~80 / 中度 80~110 /
   重度·低头 110~140 / 重度·点头 140~170（累计值，见 `ui/sources.py` 的 arc）。
   取**各段中段**，避开换档时的过渡斜坡，截出来才是干净的那一档。
   ⚠️ 清醒段取 30 而不是中段 20 —— 支路二要到 27 秒才有第一个判决
      （`WARMUP_SEC`），20 秒时「疲劳程度」那张卡还写着"热身中"，截出来不好看。
   ⚠️ 轻度段取 45 而不是中段 60 —— 那一段里塞了两个独立告警的桥段
      （打哈欠 48~55 / 长时间闭眼 62~68，见 `DemoSource.YAWN_A` 那几行），
      60 秒正好落在两个桥之间、又离闭眼桥太近；45 秒是干净的**纯轻度**。 */
const PIN_SEEK = {
  normal: 30.0, mild: 45.0, moderate: 95.0, phone: 125.0, fatigue: 155.0,
};
/* `?sev=` 到底生效了没有。**不能只看 PIN 有没有值** —— 在 cam（真人实时）源上
   这个定位是**故意不生效**的，那时候如果还按 PIN 去定标题和配色，就会拿真人的
   数字去配一档假的分级（真实数据 + 假标签），正是当初设计时明确要避免的那件事。
   所以外观也归它管：只有真的把演出挪过去了，才允许锁外观。 */
let PIN_ON = false;

/* ★ 2026-09-24（第六次改版）：四档外观表 / 档位条宽 / 快捷操作清单**搬到
   `live.js` 了**（`XQ.LOOK` / `XQ.DEG_W` / `XQ.QUICK`）。

   搬家的原因不是"文件太长"，是**驾驶监测页也要用同一份**：那一页按参考图
   `驾驶监测.png` 有「小瑞·驾驶陪伴」卡，台词和表情跟首页是同一条轴。
   各写一份的代价很具体 —— 改了档位定义之后某个页面停在上一个版本的文案上，
   `LOOK[lvKey]` 照样取得到一个值，**不报错、看着完全正常**，只有并排看才发现。

   这里保留同名别名，所以下面那几十处 `LOOK[...]` / `DEG_W[...]` / `QUICK`
   一个字都不用动。 */
const LOOK = XQ.LOOK;
const DEG_W = XQ.DEG_W;
const QUICK = XQ.QUICK;


/* ---------------------------------------------------------------- 静态零件 */
/* FaceMesh 那一层（脸上的定位点）**搬去 live.js 了** —— `XQ.buildMesh()`。
   搬的理由写在那边：总览页和驾驶监测页各有一张 `XQ.headSVG()`，两份的话
   改了一处坐标，另一页的网格会静默变空。
   ⚠️ 这里原来那份 `buildMesh()` 是**在总览页跑不到的死代码**：`#mesh` 是
      `XQ.headSVG()` 里的元素，而画面卡已经搬去 detail.html（那一页不加载 app.js）。 */

/* 心率那一格。
   ★ 2026-09-26：**这一路接上了** —— HPM5300EVK + MAX30102 走 I2C0，原始 PPG
     计数从板载 FT2232 的 console 串口出来，PC 侧 `ui/serial_hr.py` 算成心率，
     由服务端贴进 state 的 `hr`。板端固件在 `hr/firmware`。
   ⚠️ 旁边那条 sparkline **仍然是装饰性的空线**（低幅噪声），不是波形 ——
     真波形（每秒 100 个点）没有任何地方往浏览器送，所以别按"既然有心率了
     那就照着 BPM 画一条心电"的思路改：那是伪造测量值。
   ⚠️ 量不出来（手指没按上去 / 串口没数据）时写「未接入」，**不拿上一次的数凑**。 */
function buildEcg() {
  const p = $('ecgPath');
  if (!p) return;
  let d = 'M0 23';
  let seed = 7;
  for (let x = 0; x <= 320; x += 4) {
    seed = (seed * 1103515245 + 12345) & 0x7fffffff;
    const n = ((seed % 1000) / 1000 - 0.5) * 2.6;
    d += ` L${x} ${(23 + n).toFixed(1)}`;
  }
  p.setAttribute('d', d);
}

/* 驾驶员画面的资产槽：有真图/真视频就盖上去，没有就留着示意头像。
   ⚠️ cam 模式下**整块跳过** —— 那时候画面是摄像头直推的 MJPEG，不该被静图盖掉。 */
let USING_CAM = false;
function probeAssets() {
  if (USING_CAM) return;
  /* ★ 第五次改版：画面那一整块搬去了驾驶监测页，总览页没有这些元素 ——
     直接整段跳过，而不是逐个守卫（下面每一句写的都是画面自己的元素，
     缺一个就没有"画面"这件事可谈了）。 */
  if (!$('camStream')) return;
  const probe = (url) => new Promise((res) => {
    const im = new Image();
    im.onload = () => res(url);
    im.onerror = () => res(null);
    im.src = url;
  });
  const vid = (url) => new Promise((res) => {
    const v = $('camVideo');
    if (!v) return res(null);
    v.oncanplay = () => { v.hidden = false; v.play().catch(() => {}); res(url); };
    v.onerror = () => res(null);
    v.src = url;
  });

  probe('assets/camera.jpg').then((u) => {
    if (USING_CAM) return;
    if (u) { $('camImg').src = u; $('camImg').hidden = false; $('camNote').hidden = true; }
    else vid('assets/camera.mp4').then((v) => {
      if (!v || USING_CAM) return;
      $('stageHost').hidden = true;
      $('camNote').textContent = '演示视频 · assets/camera.mp4';
    });
  });
}

/* cam 模式：把摄像头画面接进来。MJPEG 直接塞 <img src>，浏览器原生支持。 */
function useCamStream(info) {
  USING_CAM = true;
  /* ★ 第五次改版：总览页（index.html）没有摄像头画面块，但是**服务端在 cam
     源上仍然会推 hello**，于是这里会被调到。不跳过就是 null.src 当场抛，
     而它在 onHello 里 —— 抛出去之后问候语、数据源判定、渲染全都不会发生。
     ⚠️ `USING_CAM` 放在这行**前面**是对的：这个标志的语义是"这一路是摄像头
        推的流"，和"本页画不画它"是两件事（`probeAssets()` 也读它）。 */
  if (!$('camStream')) return;
  const im = $('camStream');
  im.src = '/video.mjpg';
  im.hidden = false;
  $('stageHost').hidden = true;
  $('camVideo').hidden = true;
  $('camImg').hidden = true;
  const bits = [];
  if (info && info.replay) bits.push('回放视频');
  else bits.push('本机摄像头');
  bits.push('真机推理 · FaceMesh 叠加');
  if (info && info.fps) bits.push(`约 ${info.fps} fps`);
  $('camNote').hidden = false;
  $('camNote').textContent = bits.join(' · ');
  $('camLive').textContent = info && info.replay ? '推理回放画面' : '驾驶员实时画面';
  flash('已切到摄像头 —— 此时不要再跑 live_fuse.bat（会抢设备）');
}

/* ---------------------------------------------------------------- 画一帧 */
let LOOK_NOW = LOOK.normal;

/* --- 哈欠的显示锁存（2026-09-25，修用户报的「打哈欠后为啥显示那么长时间」）---
   ⚠️ 为什么不能直接把 `s.yawn_sec` 印出来：它是**缓冲区里最长的那一回张嘴**
      （`src/face.py` 的 `yawn_seconds`，窗长 27 秒）。所以它是**平台**不是脉冲 ——
      哈欠本身 d 秒，这个数就冻在 d 上，一直到那回张嘴滑出窗口才归零，也就是
      **打完还要再挂 27 − d 秒**。一次 4.8 秒的哈欠，屏上会挂 22 秒。
   ★ 能用的信号是**最后一次上涨**：哈欠**进行中**这个值在涨（`runs_sec` 把还没
      结束的那一段也算进去），嘴一合上它就冻住不动了。于是「最后一次上涨 +
      `hold_sec`」=「哈欠结束 + 3 秒」—— 正是用户要的「秒数早 3 秒收掉」。
   ⚠️ 计划里原定的触发点是「`yawn_sec` 掉回 `< yawn_min` **之后**再保持 `hold_sec`
      秒」。量过了（`_scratch/yawn_linger.py`）：那个"掉"发生在哈欠结束
      **二十几秒之后**，照那个改法只会把显示**再拖长** 3 秒，治不了这个抱怨。
      这里按用户的原意换了触发点，配置项还是同一个 `hold_sec`。
   ⚠️ 只动**显示**。`ui/state.py` 的判据（severity / alarms）照样按原始 `yawn_sec`
      走 —— 「打哈欠就是轻度疲劳」是口径，不是显示 bug（计划里那条"残余"）。
   ⚠️ 已知边角：`yawn_sec` 取的是窗内**最大**，所以「紧跟着一个更长的哈欠、又来
      一个更短的（更长的那个还在 27 秒窗里）」时，新哈欠不会让这个数上涨 →
      数字显示 0（横幅和大标题仍照 `yawn_sec` 报，屏幕不会整个哑掉）。
      这种"两分钟内连打两次、第二次还更短"的场景按已知代价记着。 */
/* 实现搬去 live.js 了（`XQ.yawnShown`），那边是**唯一**一份 ——
   驾驶监测页的「哈欠时长」和这张脸都是同一个锁存。
   ⚠️ 每帧只能推进一次，见 live.js 那段注释：多处各调一次会把"涨的那一刻"
      当场消耗掉，数字永远是 0。 */
const yawnShown = XQ.yawnShown;

function render(s) {
  /* ⚠️ 每帧**只在这里推进一次**（见上面 `yawnShown`）。下面嘴巴和那行小字
     都读这一份；各调一次的话锁存会被推两次，涨的那一刻就被消耗掉了。 */
  const yawnS = yawnShown(s.yawn_sec);
  /* 外观**跟疲劳档位**（`s.severity`）—— 整页配色、大标题、小瑞的表情和话
     都是这一档。★ 2026-09-24 改的（上一版跟 `s.level`，也就是支路一的类别）：
     三类之后 level 只剩 L0/L3，中间两档在它上面不存在，轻度/中度就永远
     变不出黄和橙黄。档位才是口径那张分级表的轴。
     ⚠️ 这张表**不在这里写第二份** —— 它在 `live.js` 的 `XQ.LV`，因为
        detail.html / link.html / chat.html 也要用同一份。键名 / 顺序必须和
        `ui/state.py` 的 SEVERITY_NAMES、`style.css` 里那四条 `body[data-sev]`、
        `live.js` 的 `sev:*` 动作表一致，改一处要一起改。 */
  const LV = XQ.LV;
  /* ⚠️ **不拿 `?sev=` 当档位用**：它只负责把演出时钟挪到那一段（见 PIN_* 那段），
     档位仍旧照服务端给的 `s.severity` 算 —— 时钟挪过去之后，数据自己就会把
     档位变成对应的那一个。锁定只是把外观和数据**绑在同一段演示上**，
     不是在外观上硬贴一个标签（那样标题和数字会互相打架，是骗人）。 */
  const lvKey = LV[s.severity] || 'normal';
  const look = LOOK[lvKey] || LOOK.normal;
  LOOK_NOW = look;
  document.body.dataset.sev = lvKey;

  /* 档位变了才换小瑞的动作。**这一段必须放在最前面**（在下面所有绘制之前）：
       · render 每帧（8 Hz）都跑，不 diff 就等于每帧重放一次动作；
       · 上一拍写在 `data-xqSev` 上，下一帧拿它比，所以顺序不能挪。
     写法照抄 detail.html / link.html 那两处的 lastSev。

     ⚠️ **记不记这一笔，取决于"有没有真的送到"**（`react()` 的返回值）。
     不判的话有一个必然踩的竞态：页面刚加载时小瑞那张图还没下载完，槽**还没登记**
     （`XQ.mascot` 是在图片 onload 里登记的），这时第一帧 state 就到了 ——
     `react()` 会因为没有槽而返回 false，可 dataset 已经被记成 normal，
     **以后同样的档位再也不会触发**，小瑞就一直停在底图打招呼。
     跑 `_check_mascot.py` 时 `?sev=normal` / `?sev=mild` 就是这么挂的
     （`?sev=severe` 侥幸过了：它那次图片先到）。不记这一笔，下一帧（8 Hz）自然重试。 */
  const last = document.body.dataset.xqSev;
  /* 档位**上升**的那一刻单独给一个「加油」（`sev:up`），再落到该档的常驻表情。
     只在上升时给 —— 一直停在 severe 的时候每帧都播一次加油，那是骚扰不是提醒。
     ⚠️ **两次 react 的顺序不能反**：先发 hold!=0 的事件类（加油），再发 hold==0 的
        状态类（常驻表情）。`react()` 里那条"槽正忙就排队"的逻辑会把常驻表情接在
        加油后面演；反过来发的话，常驻表情（hold 0）当场就挂上去，加油排到它后面。
     ⚠️ 上升判据用 `rank(lvKey) > rank(last)`，`last` 是 undefined（页面刚开）时
        rank 得 0，所以**首帧就是 severe 的那次也会给加油**，这是想要的。
     ⚠️ 和下面那次一样，判断要在**送成功**之前：没槽的时候 react 返回 false，
        这一帧不记 dataset，下一帧（8 Hz）自然重试。 */
  const rank = (v) => ({ mild: 1, moderate: 2, severe: 3 }[v] || 0);
  if (lvKey !== last && rank(lvKey) > rank(last) && XQ.mascot) {
    XQ.mascot.react('sev:up');
  }
  if (lvKey !== last && (!XQ.mascot || XQ.mascot.react('sev:' + lvKey))) {
    document.body.dataset.xqSev = lvKey;
  }

  /* --- 画面那一块（摄像头 / 示意头像 / 头姿 / 眼开合 / 嘴）**整段搬走了** ---
     ★ 第六次改版：它搬去 detail.html，画法收进 `XQ.buildMesh()` / `XQ.headPose()`
       （live.js），**这里不再留一份**。
     ⚠️ 原来留在这儿的那一份是**在总览页跑不到的死代码**，而且注释写着
        「只有驾驶监测页有」—— 那句话是反的：全项目只有 `index.html` 加载 app.js
        （`grep -rn "static/app.js" ui/web/` 只有一行），而驾驶监测页不加载它。
        留着它的代价不是几行冗余，是下一个人会以为改这里就能改到那一页的脸。
     ✅ `#camAlertTxt`（画面底边那行"在算什么"）同理，由 detail.html 从
        `XQ.LOOK[lvKey].cam` 直接取。 */

  /* --- 驾驶员状态卡 --- */
  /* 大标题 = **疲劳档位**名（清醒/轻度疲劳/中度疲劳/重度疲劳），直接取服务端的
     `severity_name`（`ui/state.py` 的 SEVERITY_NAMES）。★ 2026-09-24 改：
     上一版取的是 `level_name`（支路一的类别），三类之后它只有"清醒/重度疲劳"
     两个值 —— 中等那两档标题会写成"清醒"，和旁边「疲劳程度」那一行打架。
     ⚠️ 别用 `look.name`：那张表里已经不放名字了，理由见 LOOK 那段注释。 */
  $('sevName').textContent = s.severity_name || '—';
  $('sevPill').textContent = look.pill;
  const md = look.mood;
  on('mood', (e) => {
    e.querySelector('.m-mouth').setAttribute('d', md.mouth);
    e.querySelector('.m-brow').setAttribute('opacity', md.brow);
    e.querySelectorAll('.m-eye').forEach((x) => x.setAttribute('r', md.eye));
  });

  /* 疲劳程度能量条 —— 条宽按 `DEG_W[severity]` 取。
     ★ 2026-09-24 深夜：它原来在 `.rows` 里独占一行（「疲劳程度」四个字 + 数值 + 条），
       现在搬到了 `.hero` 里（大标题下面），**文字不再写第二遍**（那四个字和大标题
       是同一个数：`severity_name`，见 ui/state.py）。
     ⚠️ 所以这里**只剩条、没有字**了；`#rLevel` 那个元素已经不存在。
        检查脚本原来读 `#rLevel` 当"别接回 level_name"的钉子，现在那颗钉子
        换成了**条宽**（读 `#barLevel` 的 style.width）——靶子一样是
        `DEG_W`（跟着档位走），而且比读那行字更硬：接错了宽度就变。 */
  $('barLevel').style.width = ((DEG_W[s.severity] || 0) * 100).toFixed(0) + '%';

  if (s.perclos == null) {
    $('rPc').textContent = '—';
    $('barPc').style.width = '0%';
  } else {
    $('rPc').textContent = (s.perclos * 100).toFixed(1) + '%';
    $('barPc').style.width = (clamp(s.perclos / 0.6, 0, 1) * 100).toFixed(0) + '%';
  }

  /* 头部姿态那一行：**服务端 `attention` 的换一种说法**，同一组判据，只换词面。
     ⚠️ 不在这里重判一遍（原来是自己再看 `d_pitch >= 12`），否则这一行和底部小字
        的「注意力 …」会在同一张卡里说两种话 —— 它们本来就是同一件事。
     ⚠️ "偏头"这个词**没了**：它说的是分心（glance），那个类别已经删了。
     ⚠️ 直接读 `s.attention`：上一版这里读的是一个局部变量 `attention`，它跟
        画面那张脸（头姿/眼/嘴）一起定义在上面那段里 —— 那段第六次改版搬去了
        live.js（`XQ.headPose`），变量跟着没了。**总览页现在没有那张脸**
        （画面卡整块在驾驶监测页），所以这里不再需要它。 */
  const POSE_OF = {'疲劳点头': '点头', '头部持续低垂': '低头',
                   '略有低头': '略低头', '专注': '正常'};
  $('rPose').textContent = POSE_OF[s.attention] || '正常';
  /* 心率。⚠️ 文字和 `.muted` **要一起改**：`.muted`（style.css:1236）是
     「未接入」那一档的小号灰字样式，只换文字不摘类的话，一个真数字会按
     未接入的样式显示（小一号、灰的），看着像没量到。 */
  const hrEl = $('rHr');
  if (hrEl) {
    /* ★ 2026-09-26：文案**不在这里写** —— 走 `XQ.hrText()`（live.js），
       三页共用一处。为什么要把「未按压」从「未接入」里拆出来，
       见那个函数的注释（手指拿开时写「未接入」是假话）。 */
    hrEl.textContent = XQ.hrText(s);
    hrEl.classList.toggle('muted', s.hr == null);
  }
  /* ★ 2026-09-26：心率那一路的另外两个量（`#rAc` / `#rPi`，在 `.ntiles` 里）。
     ⚠️ 单位**不写进字符串**，用 `<u>`（`.nt .v u` 那一档是小号灰字）；
        两个量的量纲不一样：`hr_ac` 是**带通后的交流 RMS、单位是 ADC 计数**，
        `hr_pi` 是**百分数**（0.16 就是 0.16%，`serial_hr.PI_LOW_PCT` 有标定）。
     ⚠️ `hr_ac` **刻意不给单位**：那个计数没有物理刻度（没标定过），写"计数"是
        加一个读者看不懂的词。PI 是同一件事的比值口径，要刻度看它。
     ⚠️ 没数一律 `--`，**绝不拿上一次的数凑**（`ui/state.py` 那条）。
     ★ 2026-09-26 深夜：这一格**原本是 HRV-RMSSD**（要 NN 连续跨度 ≥ 30 s，
        实测那场会话 0.0% 的帧有数），用户说「换个一直有的」，换成交流幅度
        （同一场日志里它 100% 有数，且与心率独立 r=−0.20、与 PI 只中度相关）。 */
  const ntNum = (id, v, dec, unit) => {
    const e = $(id);
    if (!e) return;
    e.textContent = v == null ? '--' : v.toFixed(dec);
    if (v != null && unit) {
      /* 数字与单位之间的空格**要写出来**，不能只靠 `.nt .v u` 的
         `margin-left` —— 另两页写的是 `toFixed(2) + ' %'`（字面量空格），
         三页的 `textContent` 必须逐字一样。 */
      e.appendChild(document.createTextNode(' '));
      const u = document.createElement('u');
      u.textContent = unit;
      e.appendChild(u);
    }
    e.classList.toggle('na', v == null);
  };
  ntNum('rAc', s.hr_ac, 0);
  ntNum('rPi', s.hr_pi, 2, '%');
  /* PI 偏低那一行小字。**文案整句是服务端给的**（`s.hr_pi_hint`）——
     这个文件里不许出现那句中文。空串就整行收起来（`hidden` ⟹ `display:none`
     ⟹ 不占高度，`.status` 卡的高度是量出来的）。 */
  const piHintEl = $('rPiHint');
  if (piHintEl) {
    const h = s.hr_pi_hint || '';
    piHintEl.hidden = !h;
    piHintEl.textContent = h;
  }
  /* 情绪状态 —— 照参考图 首页.png 那一行。
     ⚠️ 这是**同一档位的换词**，不是新数据：这张卡左边那个表情（`look.mood`
        的嘴/眉/眼）说的就是这件事，`look.moodWord` 只是把它写成字。
        没有"情绪识别"这一路（本项目没做），所以**别把它当成一个测量值**；
        真要说它测了什么，测的是疲劳档位。
     ⚠️ 取不到 `moodWord` 时留空，不兜底成"平静" —— 兜底词会把"表里漏了一档"
        显示成一个看起来正常的结论。 */
  on('rMood', (e) => { e.textContent = look.moodWord || '—'; });

  /* --- 两块概率条 ---
     ① `#p4`：支路一的**类别**（不是档位）。
     ★ 2026-09-24：四类 → 三类（`glance` 分心删了）。
     ⚠️ **名单不在这里写死**：直接遍历服务端给的 `probs` 的键（出处是
     `ui/state.py` 的 CLASSES）。类别数再变一次时这里会跟着变；
     名字对不上某个 `<div>` 时 `set()` 里那句 `if (e)` 会让它安静跳过，
     不会把别的条填错。三条 = 正常头部姿态 / 疲劳瞌睡点头 / 头部持续低垂
     （屏幕上的字在 index.html，id 按**类别名**拼，见那块注释）。 */
  const P = s.probs || {};
  const set = (id, vid, v, txt) => {
    const e = $(id), t = $(vid);
    if (e) e.style.width = (clamp(v, 0, 1) * 100).toFixed(0) + '%';
    if (t) t.textContent = txt;
  };
  const srcTag = (who) => (s.source === 'demo' ? '演示数据'
    : (s.source === 'cam' ? who + ' · 摄像头实测' : who + ' · 实测'));
  const p4src = $('p4src');
  if (p4src) p4src.textContent = srcTag('支路一');
  Object.keys(P).forEach((c) => {
    const v = P[c] || 0;
    set('p' + c[0].toUpperCase() + c.slice(1), 'v' + c[0].toUpperCase() + c.slice(1),
        v, (v * 100).toFixed(0) + '%');
  });

  /* ② `#p5`：支路二的**两个真数**。
     ⚠️ 这一块**不是遍历出来的**，就两个写死的 id —— 支路二是个二分类
        （只有 `p_fat` + 档 `l2`），没有第二个类别名可以遍历（见 index.html 那块）。
     ⚠️ `p_fat` 为 null（热身到 27 秒之前）时：写「—」、宽度 0，**不写 0%**。
        "0% 疲劳"是一个判决，"没有这个数"是另一件事 —— 界面别把后者说成前者。
     ⚠️ 另一半 `alert` 用服务端算好的 `b2_alert`（= 1 − p_fat，见 `ui/state.py`），
        **不在这里现减**：两处各减一次，迟早有一天不一致，而那是同一块屏幕上
        两根加起来不等于 100% 的那种错。 */
  const p5src = $('p5src');
  if (p5src) p5src.textContent = srcTag('支路二');
  const setN = (id, vid, v) => {
    const e = $(id), t = $(vid);
    if (e) e.style.width = (v == null ? 0 : clamp(v, 0, 1) * 100).toFixed(0) + '%';
    if (t) t.textContent = (v == null ? '—' : (v * 100).toFixed(0) + '%');
  };
  setN('pAlert', 'vAlert', s.b2_alert);
  setN('pDrowsy', 'vDrowsy', s.p_fat);

  /* --- 底部小字：安全通道 + 支路二的原始量 --- */
  /* ⚠️ 这一行跟的是 `pc_ready`（**统计量**出数，基线攒够 10 秒就有），不是
     `b2_ready`（模型的第一个判决，要连续 27 秒）。四个格子 —— 眨眼频率 /
     点头次数 / 哈欠时长 / 闸门 —— 没有一个是模型算的，之前跟着 27 秒一起亮，
     结果上面「疲劳程度」那张卡里 PERCLOS 已经写出数来了，这一行还写着"热身中"。
     两级的分法见 `ui/state.py` 的 ROLL_WIN / WARMUP_SEC。 */
  const ready = !!s.pc_ready;
  /* ⚠️ 整块用 `if (statsEl)` 包住而不是逐句守卫：这四个格子是一体的
     （同一次 `pc_ready` 亮、同一次灭），缺一个就说明整块都不在本页。 */
  const statsEl = $('stats');
  if (statsEl) {
    statsEl.hidden = !ready;
    if (ready) {
      $('sBr').textContent = s.brate == null ? '—' : s.brate.toFixed(0);
      $('sNod').textContent = s.nod == null ? '—' : s.nod.toFixed(0);
      $('sYawn').textContent = yawnS == null ? '—' : yawnS.toFixed(1);
      $('sGate').textContent = s.gate ? '开' : '关';
    }
  }

  const bits = [`安全通道 L${s.level} ${s.level_name}`, `注意力 ${s.attention}`];
  if (s.b2_ready) {
    if (s.p_fat != null) bits.push(`支路二 疲劳概率 ${s.p_fat.toFixed(2)}`);
    if (!s.gate) bits.push('闸门关闭 · 支路二暂停投票');
  } else {
    bits.push(s.note || '支路二热身中');
  }
  if (PIN_ON && PIN) bits.unshift(`演示锁定 ${PIN_NO[PIN]} · 演示数据（非真人）`);
  /* ⚠️ `title` 必须跟着一起写：第五次改版把 `.status-foot` 限成了两行
     （那一行在重度档会长到三个分句，卡片是定高的，不夹就会被裁掉尾巴）。
     夹掉的是**显示**，不是内容 —— 悬停仍然能看全。 */
  const foot = bits.join(' · ');
  $('statusFoot').textContent = foot;
  $('statusFoot').title = foot;

  /* --- 小瑞 --- */
  $('xqPill').textContent = look.xqPill;
  $('xqNote').hidden = !look.note;
  if (look.note) $('xqNote').innerHTML = look.note + '<span class="swash"></span>';
  $('xqBubble').hidden = !look.bubble;
  if (look.bubble) $('xqBubble').textContent = look.bubble;
  renderActs($('xqActs'), look.acts);
  /* 「快捷操作」只在最坏那一档挂出来。★ 键名从 `fatigue`（类别）改成
     `severe`（档位）—— 现在挂出来的时机是"疲劳程度到重度"，正是想要的。
     ★ 第五次改版：这张卡**搬去驾驶监测页了**（总览页的小瑞卡按参考图到
     "手写那句话"就结束；而且它在本页装不下、会溢出到下行）。所以这里要守卫。 */
  on('quick', (e) => { e.hidden = lvKey !== 'severe'; });
  /* 支路二那两条独立告警的横幅。**和上面这一整段无关**：它不看档位、
     只看支路二自己的判决，所以最后一次调、不和配色抢先后。 */
  if (XQ.alarms) XQ.alarms.render($('alarms'), s, XQ.alarms.holdSec);
}

function renderActs(host, acts) {
  if (!host) return;
  const key = JSON.stringify(acts);
  if (host.dataset.key === key) return;
  host.dataset.key = key;
  host.innerHTML = '';
  acts.forEach(([id, label, primary]) => {
    const b = document.createElement('button');
    b.className = 'xq-btn' + (primary ? ' primary' : '');
    b.innerHTML = `<svg viewBox="0 0 24 24">${ICONS[id] || ICONS.status}</svg><span>${label}</span>`;
    /* ★ 2026-09-25 晚：这张卡上的「播放舒缓音乐」也**真的放**（同 player.js 那节）。
       `look.acts` / `XQ.QUICK` 两个来源里都有 `music`，所以判 id 就够。
       ⚠️ 这一页没有 `XQ.flash` 的那套"已执行"文案，成功后**只**靠左下角那条 +
          小瑞那句话 —— 别为它在这页加一个三页各写一遍的 toast。 */
    b.onclick = () => {
      send({ type: 'action', id });
      if (id === 'music' && window.XQP && XQP.playCalm) XQP.playCalm();
      /* ★★ 2026-09-26：这两颗**真的能导航**（用户：「其他页面有导航到最近服务区
         或者导航啥的按钮 要真的有这个功能 不是摆设」）。
         `rest_stop`/`nearby` 在这张卡上出现过三个文案（「建议休息一下」/「查看附近
         服务区」/「导航至最近服务区」），**都是同一件事**：去查最近的服务区、
         把路画出来。干这件事的地方只有 `nav.html`（高德地图和那份服务区数据
         都在那一页），所以就是**跳过去**，参数告诉它要干嘛。
         ⚠️ `send()` 照发：服务端那边也会回一句小瑞的话（它有自己的口径），
            这里只是**顺手把人送到真能干事的那一页**，不是替它说话。 */
      else if (id === 'rest_stop' || id === 'nearby') {
        location.href = 'nav.html?do=nearby';
      }
    };
    host.appendChild(b);
  });
}

/* ---------------------------------------------------------------- 对话 */
const MAX_BUBBLES = 12;

function addBubble(role, text, pending) {
  const box = $('bubbles');
  /* ★ 2026-09-24：**这一格只能是"没有就算了"，不能是"没有就抛"**。
     `#bubbles` 只在 detail.html（驾驶监测页）里 —— 对话栏第五次改版搬过去了，
     可 `onSay` 还在无条件调这个函数。首页每收到一句 say 就在 `box.appendChild`
     抛 TypeError，把**整个 onSay 打断**：后面那句 `XQ.speak(d.text, ...)` 根本没跑，
     所以**座舱首页小瑞一句话都不念**，连带 `XQ.tts` 那条 `react('speak')`
     也不触发 —— 表现是"首页的小瑞从不张嘴"，而它跟这行看着没关系。
     onHello 里那句问候语早就有同样的判空（见上面 `const box = $('bubbles')`），
     这里当时漏了。返回值保留原语义：没格子可放就返回 null。 */
  if (!box) return null;
  const el = document.createElement('div');
  el.className = 'b' + (role === 'me' ? ' me' : '') + (pending ? ' pending' : '');
  el.innerHTML = `<u>${role === 'me' ? '我' : '小瑞'}</u><p></p>`;
  el.querySelector('p').textContent = text;      // textContent：模型的话不进 HTML
  box.appendChild(el);
  while (box.children.length > MAX_BUBBLES) box.removeChild(box.firstChild);
  box.scrollTop = box.scrollHeight;
  return el;
}

/* ---------------------------------------------------------------- 通信 */
let send = () => {};
let SEEK_DONE = false;
/* `link` 提上来当模块级变量（原来它是 connect() 里的局部 `const`）：
   底部对话栏和麦克风要用 `link.online` 判断"服务连上没有"，
   而 `send` 那个空函数默认值**什么都吞**——正是"点了没反应"的由来。
   见 chat.html 里同款的 `link.online` 兜底。
   （★ 2026-09-24：原来这里还写着"数据源按钮"，那个按钮已随左栏数据源块删掉。） */
let link = null;
/* 上一个 hello 报的数据源。切数据源**没有 ack**，只能在下一个 hello 里比对
   —— 服务端每次切源都会重发 hello，所以这条判据是可靠的。 */
let lastSpec = null;

function connect() {
  link = XQ.connect({
    onHello: (d) => {
      /* 支路二那两个数（告警保持时长 / 哈欠阈值）由服务端给，灌进 live.js 的
         `XQ.alarms`。**放在最前面**：下面 cam 那个分支会 `return`，放后面会漏。
         ⚠️ 漏了看不出来 —— 默认值 5.0 / 2.0 恰好就是服务端现在的值，
            只有改了 `ui/config.json` 的 `alarm` 段才会现形（横幅比语音早/晚收）。 */
      XQ.alarms.setCfg(d.alarm_cfg);
      if (d.source === 'cam') useCamStream(d.cam);
      /* ★ 第五次改版：对话栏搬去驾驶监测页了，总览页没有 `#bubbles` ——
         问候语那一句跟着它一起走（这里不补一句到别处，那会变成两个地方说同一句）。 */
      const box = $('bubbles');
      if (box && !box.children.length) addBubble('xq', '你好呀！我是小瑞，一路陪着你。');
      /* ★ 2026-09-24：这里原来还有两句，跟着左栏「数据源」块一起删了 ——
           $('srcNote').innerHTML = ...   ← 把当前源和小瑞后端（API / 固定话术）写在那块里
           document.querySelectorAll('.src-btn[data-spec]')...toggle('on', ...)   ← 点亮当前源
         ⚠️ 删它们**不是可删可不删**：`#srcNote` 是那个块生成的，块没了这一句就是
            `null.innerHTML`，**当场 TypeError**，把整个 onHello 打断 —— 表现是
            首页连问候气泡都出不来、源也永远切不动（但控制台之外看不出是这里）。
         ⚠️ 那条"小瑞后端是 API 还是固定话术"的信息**没有丢**，只不再出现在首页：
            settings.html 的只读区有「API 是否可用」那一行（会写「不可用 —— 已降级为
            本地固定话术」），是同一份数据。 */
      /* 数据源**真的切了**才播「出发」。
         ⚠️ 首次连接不算切换：那时 lastSpec 还是 null，把小瑞从「打招呼」直接
            顶成一次「出发」是错的（每次开页面都会看到）。
         ⚠️ 这条判据放在 `PIN && !SEEK_DONE` 那段**之前**：定位过程本身会先
            切到 demo 源，那是一次真实切换，理应有「出发」；而它后面 `return` 掉了，
            放在后面就永远走不到。 */
      if (lastSpec && d.source_spec && d.source_spec !== lastSpec
          && XQ.mascot) XQ.mascot.react('source');
      lastSpec = d.source_spec || d.source;
      /* ?sev= 定位：先切演示（切源会把演出时钟归零），再把时钟挪到那一档。
         只在**首次** hello 时做一次；之后用户自己点了数据源就不该被拽回去。

         ⚠️ **cam 源是个例外，而且是硬要求**：界面开着摄像头时，这套定位必须
         完全不生效。原来的写法是"不是 demo 就发 source:demo 切过去"，于是在 cam
         模式下点左栏的「03 重度」，会**当场把真人实时画面换成罐头演示** ——
         恰好跟"我是什么状态就显示什么状态"相反。现在 cam 源上连 seek 都不发，
         真人数据照原样流，只提示一次为什么点了没反应。
         注意只排除 cam：replay/live 放的是**录像**不是本人，那两种源上继续允许
         切到演示，否则"截 01/02/03 三张稿"这个用途就断了。 */
      if (PIN && !SEEK_DONE) {
        if (d.source === 'cam') {
          /* 真人实时：一概不碰，到此为止 */
          SEEK_DONE = true;
          flash(`${d.source_spec || d.source} 是真人实时画面，?sev= 演示定位不生效`);
          return;
        }
        if (d.source !== 'demo') {
          /* 先切源。**这里不能置 SEEK_DONE** —— 切源会把演出时钟归零，得等切过去
             之后那次 hello（source 变成 demo）再拨时钟，否则时钟刚归零就被当成
             "已经定位过了"，停在第 0 秒上。 */
          send({ type: 'source', spec: 'demo' });
          return;
        }
        SEEK_DONE = true;                       // 只做一次，之后用户自己点了源就不管了
        PIN_ON = true;                          // 外观也归它管，见 PIN_ON 那段注释
        send({ type: 'seek', t: PIN_SEEK[PIN] });
        markPinned();
      }
    },
    onState: render,
    onSay: (d) => {
      if (d.user) addBubble('me', d.user);
      addBubble('xq', d.text);
      // 念出来。`emotion` 是服务端早就给好、以前一处都没用过的字段
      // （ui/xiaorui.py 的 emotion_for），用它调语速和音高，见 XQ.tts.prosody。
      // 静音开关、后台标签页、服务端兜底这些判断都在 XQ.speak 里面。
      //
      // ★ 2026-09-25 常听唤醒：`silent` 那条**只画气泡、不出声**。
      //   语音进来的答复是**开麦的那张页面**自己念的（`web/wake.js`），因为它
      //   需要 `XQ.speak` 的 "念完了" 回调去把服务端状态机放回 IDLE —— 而那条
      //   回调只有**发起者**拿得到。要是这里也跟着念，同一个窗口里就会**两遍**。
      //   ⚠️ 所以判据是字段，不是"这一页有没有开麦"：`d.silent` 由**服务端**写，
      //   页面这边永远不需要知道谁在开麦。
      if (!d.silent) XQ.speak(d.text, { emotion: d.emotion });
      if (d.backend && d.backend !== 'deepseek') flash('本地固定话术（' + d.backend + '）');
    },
    onInfo: flash,
    onDown: (down) => {
      if (down && !XQ.isFile()) flash('连接断开，正在重连…');
    },
  });
  send = link.send;
}

/* ---------------------------------------------------------------- 事件 */
function bind() {
  /* ★ 第五次改版：对话栏搬去驾驶监测页了。总览页里这三个元素一个都没有 ——
     整段跳过。`bind()` 是**顶层调用**的（见文件末尾），在这里抛出去的话
     后面 `renderActs` / `connect()` 全都不执行，页面连数据都连不上。 */
  const input = $('sayInput');
  if (!input) return;
  const submit = (text) => {
    text = (text || '').trim();
    if (!text) return;
    if (!link || !link.online) {
      flash('还没连上座舱服务，这句话没发出去（用 run_ui.bat 启动服务端）');
      return;
    }
    send({ type: 'say', text });
    input.value = '';
  };
  const sendBtn = $('send');
  if (sendBtn) sendBtn.onclick = () => submit(input.value);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(input.value); });
  /* 麦克风：真的语音输入（`XQ.asr`，双路：浏览器优先 + 本地 whisper 兜底）。
     ⚠️ 回调传的是**本页自己的 `submit`** —— `XQ.asr` 只负责把识别出的文字交出来，
     发不发、怎么发由页面决定。让它内部直接 `link.send`，这一页的守卫就被绕过了。 */
  if ($('mic')) XQ.asr.bind($('mic'), { submit });

  /* ★ 2026-09-24：这里原来有一整段「数据源切换」的绑定 ——
       document.querySelectorAll('.src-btn[data-spec]').forEach(b => b.onclick = ...)
     随左栏那个「数据源」块一起**删掉了**（用户：「直接不要那个栏 我只要实时的画面」）。
     源现在只由启动参数决定（`run_ui.bat` 默认 `--source cam`）；
     连不上时的兜底提示那一套知识还在，只是这页不再有点数据源这个动作。

     ⚠️ 上面这个循环当年为什么必须带 `[data-spec]`：左导航那个喇叭按钮（「出声」，
     live.js 的 `XQ.tts.btnHTML()`）**也用 `.src-btn` 这个类**借样式，不带限定会把它
     一起选中、`onclick` 被整个覆盖掉。谁赢只看先后（`mountChrome` 先绑、
     本文件的 `bind()` 后跑），于是"同一份代码在首页被抢、在 settings.html 却是对的"。

     ★ 2026-09-25：**这条规矩现在没有对象了** —— 数据源块（2026-09-24）和喇叭按钮
     （今天）先后都删了，全站再没有一个 `.src-btn`（style.css 里那几条规则也连根删了，
     墓碑在那边）。所以 `[data-spec]` 不再是"必须带"，而是"没事可带"。
     真有人要再做一个 `.src-btn` 出来，先去读 style.css 那段墓碑 —— 那里记着
     "一个类名被两个完全不同的按钮借样式"是怎么把 onclick 搞丢的。 */
}

/* ---------------------------------------------------------------- 起步 */
/* 先铺图形再挂骨架：mountChrome 会重写 #rail，而 #stageHost 在它外面，无所谓先后。
   ⚠️ 这里原来写着「真正有先后的是 bind() —— 它要等 chrome.js 把 .src-btn 生成出来」，
   那说的是已删的喇叭按钮。现在下面的 `bind()` / `mascotSlot()` / `deck` 都只碰
   `#mascotSvgHost` 这些不在 #rail 里的宿主，跟 mountChrome 没有任何先后关系了。 */
/* 画面那块（`#stageHost`）和对话栏头像（`#talkAvaSvgHost`）都搬走了；
   小瑞那张（`#mascotSvgHost`）留在首页 —— 它是**总览页的小瑞卡**。 */
const stageHost = $('stageHost');
if (stageHost) stageHost.innerHTML = XQ.headSVG();
$('mascotSvgHost').innerHTML = XQ.mascotSVG();
const talkAvaHost = $('talkAvaSvgHost');
if (talkAvaHost) talkAvaHost.innerHTML = XQ.mascotSVG({ simple: true });
/* 首页这一格是「首页」，不再传 `sheet:` —— 左导航那十格作品索引已经删了
   （用户要求彻底去掉入口），`sheet` 参数本身也从 chrome.js 的 railHTML 里拿掉了。
   现在高亮哪一项只看 `active`，跟 `?sev=` 那三档没关系了。
   ★ 2026-09-25：`voice: true` 也拿掉了 —— 左栏那块「小瑞语音」整块删了
   （用户：「左边栏不要出现这些」）。`voice` 参数本身已从 railHTML 的签名里删掉。 */
XQ.mountChrome({ active: 'home' });
/* 首页这一格（6.6rem）是**会动 + 可点**的那个：bind 会挂上待机呼吸、把动作
   挂到真实状态上，并允许手点循环切十个动作（答辩时想演哪个就点哪个）。
   ⚠️ 旁边的对话栏头像（3.6rem）**不 bind**，只拿静态图 —— 3.6rem 上动作是糊的，
      而且它和这一格在同一个视野里，两个一起动会显得乱。 */
XQ.mascot.bind('mascotImg', 'mascotSvgHost', { cycle: true });
/* ★ 2026-09-25：`deck:'h'` = 这一格接 43 张形象库的**方形头像**那套（192x192）。
   方槽必须用 h：一张全身立绘塞进 2.4rem 的圆里，脸只剩几个像素（见 live.js 的
   XQ.POSES 那段）。用户「把那些出现小瑞的地方都变成可以变化的」。 */
if (talkAvaHost) XQ.mascotSlot('talkAvaImg', 'talkAvaSvgHost', { simple: true, deck: 'h' });

/* ★ 2026-09-25：首页主视觉右下角那张欢迎立绘（`.dash-mascot`）也接上 43 张形象库。
   ⚠️ **宿主就是这张图自己**，不是 `im.parentNode` 那种写法：`im.parentNode` 是
      `.dash-visual` 整个面板，挂上去等于"点面板哪儿都换形象"。`poseDeck(im, host, …)`
      里的 host 决定**点哪儿**，这里要的是"点在图上才算"。
   ⚠️ `size:'l'`：这一格屏上高约 352px，`s` 那套（画布 210x288）要放大到 1.22x，
      会看出糊；`l` 是 730x1000，缩下来 0.35x，最清楚。
   ⚠️ 初始形象是 **`p02`**，不是 `p01` —— `p02` 才是原来那张 `xiaorui_welcome.png`
      的同一个姿势（`FS[1]` 摊手迎客）。它必须和 HTML 里那个
      `src="assets/xq/l/p02.webp"` 对上（对不上表现为"第一下点下去和没点一样"）。
   ⚠️ `pointer-events` 是**这里**开的，不在 CSS 里 —— 理由写在 pages.css 那条
      注释里：CSS 写死的话，JS 万一没跑就成了"看着能点、点了没反应"的白块。
      给它开之前量过一遍（`_scratch/_probe_dash_rects.py`）：它不吃任何点击。 */
const dashIm = document.querySelector('.dash-mascot');
if (dashIm && XQ.poseDeck(dashIm, dashIm, { size: 'l', base: 'p02', title: '点一下换个形象' })) {
  dashIm.style.pointerEvents = 'auto';
}

XQ.buildMesh();
buildEcg();
probeAssets();
bind();
/* ⚠️ 第五次改版：`#quickBtns` 跟着「快捷操作」那张卡一起搬去了驾驶监测页，
   总览页没有它（`renderActs` 自己带 `if (!host) return;`）。 */
renderActs($('quickBtns'), QUICK);

/* 锁定档时挂一个显眼的标记 —— 别让人把"锁定的稿"看成"实时判决"。
   ⚠️ 只在**真的锁上了**才挂（见 onHello 里那个分支）：如果是 cam 那种实时源，
   ?sev= 不生效，这时候还挂着「演示锁定」就是在撒谎。所以做成函数等确认后再调。 */
function markPinned() {
  if (!PIN || $('pinChip')) return;
  const chip = document.createElement('div');
  chip.className = 'cam-chip';
  chip.id = 'pinChip';
  chip.style.cssText = 'right:1rem;top:1rem;color:var(--accent);border-color:rgba(var(--rgb),.5);background:rgba(var(--rgb),.16)';
  chip.textContent = `演示锁定 ${PIN_NO[PIN]}`;
  /* 「演示锁定」那颗标记挂的是**画面左上角**。总览页没有画面 ——
     那里不挂（也没有别的位置适合挂），但 `?sev=` 的定位照常生效，
     底部的 `#statusFoot` 照样会写「演示锁定 · 演示数据（非真人）」。 */
  const cam = $('cam');
  if (cam) cam.appendChild(chip);
}

/* 起来先画一帧中性占位。**这里不能直接用 PIN** —— 那会在"已经知道 ?sev= 但还
   没确认源能不能用它"的空档里，先按锁定档画一次外观。真的锁上了会由随后的
   state 帧覆盖过去（PIN_ON 那时才为真）。 */
render({ severity: 'normal', probs: {}, attention: '专注', level: 0, level_name: '清醒',
         severity_name: '清醒', source: 'demo', note: '连接中…',
         b2_ready: false, pc_ready: false,
         l1: 0, d_pitch: null, eyes: 'unknown', alarms: [] });
connect();
