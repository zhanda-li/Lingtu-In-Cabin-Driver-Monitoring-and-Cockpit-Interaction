/* =========================================================================
   顶栏 / 左导航 / 气候栏 —— **各页共用这一份**。
   -------------------------------------------------------------------------
   为什么做成 JS 而不是复制 8 遍：这三块在每个页面上一模一样，复制之后
   "改个 slogan 要改 8 个文件"，一定会漏。这里生成一次，各页只管自己的内容。

   页面本体（驾驶员画面、状态卡、小瑞…）**不在这里** —— 那些每页都不同。
   ========================================================================= */
'use strict';

/* ⚠️ 必须是 `var` 不能是 `const`。chrome.js 和 live.js 都要声明这个名字，
   而两个**普通脚本**的顶层 `const` 落在同一个全局词法作用域里，第二个会
   直接抛 "Identifier 'XQ' has already been declared"，整页白屏。
   `var` 重复声明是合法的，所以两个文件都用它。 */
var XQ = (window.XQ = window.XQ || {});

/* 左导航 5 项（车机的导航，不是作品集的目录）。
   ★ 顺序是 [key, 文案, 目标页, 图标]，第 3 个字段是**目标页**，五项全都有 —— 早先只有"驾驶监测"有
   （其余三项点了弹一句"这一项本次没做"、当前页那一项干脆静默 return），
   看着就像坏了。现在五项都是真的，一个壳都不留。

   ★ 2026-09-24：「导航」那一项和 nav.html 一起删了（用户：「把导航页删了吧」）。
   为什么当时删：那一页是个**没有接真实地图服务**的自制路线动画（换目的地重算折线/里程/
   转向提示，全是页内算的几何，不是任何地图 SDK）。用户那天在收口"只留实时画面"，
   一张假地图留在五项里比删掉更费事 —— 答辩时被指着问"这是哪家地图"是不好答的。

   ★ 2026-09-25 晚：**它回来了，理由正好是当初删它的那个理由。**
   这一页现在挂的是**真的高德地图**（`ui/amap.py` 打的 Web 服务 + JS API 2.0 建图），
   「最近服务区」那个公里数从写死的 12 变成高德返回的真数，页面上明写
   「数据 © 高德地图」。当初"这是哪家地图"答不上来，现在答得上来了，
   而且是这一页唯一敢站住的东西（见 nav.html 文件头第 1 条）。
   ⚠️ 子页面 `nav.html` 必须同时在 `server.py` 的 `PAGES` 里注册（那边一直留着
      `"nav"` 这个条目），少注册就是 404 —— 而 404 在浏览器里是一张**白页**。 */
const NAV = [
  ['home', '首页', 'index.html', '<path d="M3.5 10.5 12 3.5l8.5 7V20a1 1 0 0 1-1 1h-5v-6h-5v6h-5a1 1 0 0 1-1-1z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>'],
  ['mon', '驾驶监测', 'detail.html', '<circle cx="12" cy="12" r="8.6" fill="none" stroke="currentColor" stroke-width="1.8"/><circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M12 3.4v5.2M12 15.4v5.2M3.4 12h5.2M15.4 12h5.2" stroke="currentColor" stroke-width="1.8"/>'],
  ['media', '多媒体', 'media.html', '<path d="M9 18V6.5l10-2v11" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><circle cx="6.5" cy="18" r="2.6" fill="none" stroke="currentColor" stroke-width="1.8"/><circle cx="16.5" cy="15.5" r="2.6" fill="none" stroke="currentColor" stroke-width="1.8"/>'],
  ['navi', '导航', 'nav.html', '<path d="M21 3 3.4 10.4l7 2.2 2.2 7z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>'],
  ['set', '设置', 'settings.html', '<circle cx="12" cy="12" r="3.2" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M12 2.6l1.4 2.6 2.9-.6.6 2.9 2.6 1.4-1.6 2.5 1.6 2.5-2.6 1.4-.6 2.9-2.9-.6L12 21.4l-1.4-2.6-2.9.6-.6-2.9L4.5 15l1.6-2.5L4.5 10l2.6-1.4.6-2.9 2.9.6z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>'],
];

/* ★ 2026-09-26：把这张表挂到 `XQ` 上，给 `wake.js` 用 —— 它收到
   `ev:"do" id:"go:<键>"` 时要拿键换目标页文件（见那边的 `ev === 'do'` 分支）。
   `const NAV` 只在全局词法作用域里，别的脚本按名字读得到，但那是**隐式**耦合；
   挂到命名空间上才是明写的，而且取不到时能判空。
   ⚠️ 键必须和服务端 `ui/xiaorui.py` 的 `PAGES` 对齐。对不上时页面回 `no_target`、
      小瑞照实说"这一页我找不到"（这是设计好的那一档，不是静默跳错页）。 */
XQ.NAV = NAV;

const HOME = 'index.html';

/* ★ 2026-09-23（第二次改版）：**顶栏中间那个时钟整块拿掉了**，换成
   「页面自己愿意挂什么就挂什么」的一个空槽 `.tbtitle`。
   用户原话：「不要在页面顶部放置时间日期」+ 拍板「**全站都去掉**」。

   为什么留槽而不是把中间的格子删掉：
     `.topbar` 是 `grid-template-columns:1fr auto 1fr`，中间那格是 `auto`。
     现在封面往里放项目主题文字（13.png 的版式：左 logo、中标题、右状态），
     座舱页不传就是空的 —— **空格子会把两侧的 1fr 顶住**，品牌和状态栏
     永远钉在最左/最右，不会因为中间有没有东西而左右漂。
     ⚠️ 别为了"空着不好看"给座舱页也塞一行字：那 10 页每页自己都有一个
        页面标题（导航/首页/…），顶栏再写一遍就是同一句话出现两次，
        而且「情感化智能座舱驾驶员健康监测预警系统」有 19 个字，
        放进去比 logo 还长，整个顶栏的重心就歪了。
        哪一页要挂什么，由**那一页自己**在 mountChrome 里传 `title`，别在这里写死。

   ⚠️ 连带删掉的东西（不是一个 CSS 类的死活问题）：
     · `<b id="hhmm">` / `<span id="date">` 两个元素 —— 它们是 XQ.tickClock 唯一的落点；
     · `XQ.tickClock` 本身，以及 mountChrome 里那个 `setInterval(tickClock, 10000)`
       —— 定时器留着就是每 10 秒空转一次、两个 getElementById 都拿到 null。
     · style.css 里的 `.clock` 三条规则。
     三个检查脚本（_check_pages / _check_mascot / _theme_shots）里原本就带
     `if (a)` 空值保护，所以元素没了它们不会报错 —— 那几处**不用改**。
     另外 style.css 里有一句注释拿 `.clock b` 的 2.05rem 当排版基准，
     时钟没了那句基准也失效了，一并改掉了。 */
/* ★★ 2026-09-24（第五次改版，照用户给的 `ui/图片效果/首页.png` 那四张参考图）
   -------------------------------------------------------------------------
   顶栏从「左品牌 / 中标题 / 右院徽」改成参考图上那一版：

     左  .brand       标志 + 灵途智行 + LINGTU ZHIXING，**再跟一句系统副标题**
                       （座舱页才有；封面不加 —— 封面顶栏中间本来就是这句话，
                        再来一遍就是同一行字出现两次，见下面 SUB 那个常量的注释）
     中  .tbtitle     **只有封面用**（`#tbTitle`）。座舱页这一格故意的空的，
                       `_check_theme2.py` 有一条判据钉着这件事。
     右  .collab      封面 = 同济院徽；**座舱页是空的**。
                       ★ 2026-09-25：原来这一格是「智驾相伴 安全出行」+ 铃铛 +
                       管理员(头像+名字+箭头) 三件。用户分两次点名
                       「顶部那些感觉多余了」和「驾驶监测与报警那个小铃铛去掉」
                       —— 现在**一件都不剩**了（理由写在下面那段注释里）。
                       ⚠️ 也别往这一格补「返回展示页」：加过一次，被用户否了，
                          回程口在**首页那条 `.dash-strip` 的 `.dash-cta`** 上
                          —— 见下面那段已否记录。
                       ⚠️ 这一格本身**不能删**：它是第三列，空着也占位。
                       两拨东西共用一个格子是因为 `.topbar` 就是
                       `1fr auto 1fr` 三列 —— 再加一列会把封面那个居中的标题挤偏。
                       （⚠️ 这句原来是「它是 `auto` 那列」—— **写错了**：`auto`
                        那列是中间 `.tbtitle`，`.collab` 是 1fr。判据一直按
                        `.collab` 数，所以这个笔误没造成过后果，但它是错的。）
                       ⚠️ 代价：院徽和座舱那拨**在同一个 `.collab` 里**，所以
                          "院徽只有封面有"这条判据不能再数 `.collab img`（座舱页
                          那个头像也是 img，铃铛是 svg）；`_check_theme2.py` 的
                          B2 段数是 `.collab-logo`（留个记录：这个坑是上一版
                          "头像也是 img"踩出来的，现在头像没了，但判据照旧按
                          `.collab-logo` 数，不因此放松）。
   ⚠️ ❌ 这里原来还有一句「铃铛上那个红点**纯 CSS 驱动**（`body[data-sev]` 不是
      normal 就亮），没有 JS、没有定时器 —— 它要表达的就是"当前有报警"，
      点了跳 detail.html」—— 铃铛本身已经按用户要求删了，那套红点样式
      （style.css 的 `.tb-bell .dot` 三条）也一起删干净了。
      这段留着是为了让搜 `.tb-bell` / 「红点」的人读到"它为什么没了"。 */
/* ⚠️ 必须是 `var` 不是 `const`，理由和文件顶上那个 `var XQ` 完全一样：
   chrome.js 和 live.js 都是**普通脚本**，顶层 const 落在同一个全局词法作用域，
   同名就 `SyntaxError: Identifier 'XQ_SUB' has already been declared`，整页白屏。
   var 重复声明合法，所以这个文件的顶层一律用 var。 */
var XQ_SUB = '情感化智能座舱驾驶员健康监测预警系统';

/* ═════════════════════════════════════════════════════════════════════════
   ★★ 2026-09-25 晚：顶栏右上角**又**放回了一个用户入口。
   -------------------------------------------------------------------------
   ⚠️ 先说清这件事的来路，因为它和下面 clockHTML 里那段"删掉"的注释
      **是直接冲突的**，不写明白，下一个人会以为这页自相矛盾：
      同一天早些时候用户分两次点名，把这一格里的东西删光了 ——
        「把智驾相伴 安全出行、管理员去掉，就是顶部那些，感觉多余了」
        「把驾驶监测与报警那个小铃铛去掉 在顶部」
      「管理员」就是现在这个东西的前身：头像 + 名字 + 箭头，而且头像画的是
      **内联 SVG 的人形**，不是一个真头像。当时它立不住的理由是：这套系统
      **没有账号体系**（settings 那张卡上也明写着没有登录），它点不动、
      没有下拉、没有内容，是个纯装饰的假控件。
   ★ 现在用户自己点名要它回来，而且这次**真有内容**：
      「页面右上角搞个用户 然后用我的用户头像 有我个人基本信息 能连微信吗」
     —— 头像换成他本人的照片，点开是一张真的个人档。所以这不是"把删掉的
        东西加回来"，是把一个假控件换成一个真控件；"没内容可显示"那条理由
        因此不成立了。
     ⚠️ 将来谁要再删它，别拿上面那两句话当依据 —— 那两句否掉的是
        "一个点不动的装饰"，不是"一个有内容的入口"。
   ⚠️ 但那条记录里**还有半句理由今天仍然成立，我照做了**：
        「同一个动作放两处，一个显眼一个不显眼，只会让人在答辩现场去找那个
        不显眼的」—— 所以这张个人档里**没有「返回展示页」也没有「退出座舱」**。
        回程口依然只有一处：首页那条 .dash-strip 上的 .dash-cta（缘由见
        style.css 里那段已否记录）。要往这儿加，先问用户，别自己补一颗。
   ═══════════════════════════════════════════════════════════════════════ */

/* 这一格显示谁。★ 换名字、换那行小字，改这里就行 —— 全站共用的只有这一份
   （和 NAV 同一个理由：复制到 8 个页面里，改的时候一定会漏掉一个）。
   ⚠️ 名字是**用户本人** 2026-09-25 晚给的：先写成占位的「张主任」，
      他当场改成「李展达」。**这是真人姓名**，别再拿它当占位符改回去。
   ⚠️ 头像是**用户本人的照片**：他给的原片是 1080x1080 的 ui/图片效果/用户头像.jpg，
      落到 ui/web/assets/user_avatar.jpg 是 400x400。实测两者 PSNR 38.6 dB
      ——是同一张照片的缩放，所以**不用再转换**，直接引那一张就行。
      会话气泡（chat.html 里那颗 DRIVER_AVA）用的也是同一个文件，一个文件两处用。
   ⚠️ 路径写**相对**的 assets/...，不写 /static/assets/... —— 理由和左栏那一格
      小瑞完全一样（见 railHTML 里那段）：server.py 把 ui/web/assets 同时挂在
      /assets 和 /static/assets 两条上，相对路径在 / 和 /xxx.html 两种深度都
      指得对，file:// 直接打开也对。上面那两张 chery_mark 写绝对路径是历史原因。
   ⚠️ 这是**真人照片 + 真人姓名**，不是素材图 —— 用户 2026-09-25 明确要求用它。 */
var XQ_USER = {
  name: '李展达',
  sub: '灵途智行 · 智能座舱体验',
  avatar: 'assets/user_avatar.jpg',
};

/* 顶栏右上角那颗用户入口 + 它的下拉。**只有座舱页有**（封面那格放院徽，
   两样东西共用一个 .collab —— 见下面 clockHTML 里那段"两拨东西共用一个格子"）。
   ⚠️ 本函数里**一个反引号都不能有**（它 return 的就是模板字符串），
      要强调就用 HTML 的 b 标签。改完跑 _scratch/_js_template_scan.py。
   ⚠️ 下拉是**默认关着**的（hidden），开关在 XQ.userMenu 里，由 mountChrome 调。
      别把 hidden 去掉指望 CSS —— style.css 里那条 .tb-menu[hidden] 是安全带，
      真正的开关是 JS。 */
XQ.userHTML = () => {
  const ava = XQ_USER.avatar;
  return `
  <div class="tb-user" id="tbUser">
    <!-- ⚠️ 这里是个真 button（不是 div）：它真的能点、有 aria-expanded，
         键盘 Tab 也能到 —— 上一版那个"管理员"是纯 div，正是它被否掉的原因之一。
         ⚠️ 头像的 alt **留空**：旁边紧跟着就是名字，读屏再念一遍头像就是
            同一个信息说两遍。（railHTML 那格小瑞留空也是这个理由。） -->
    <button class="tb-ubtn" id="tbUserBtn" type="button"
            aria-haspopup="menu" aria-expanded="false" aria-controls="tbUserMenu">
      <img class="tb-ava" src="${ava}" alt="">
      <span class="tb-name">${XQ_USER.name}</span>
      <svg class="tb-caret" viewBox="0 0 12 12" aria-hidden="true"><path d="M2.6 4.6 6 8l3.4-3.4" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </button>
    <div class="tb-menu" id="tbUserMenu" role="menu" hidden>
      <div class="tb-menu-head">
        <img class="tb-menu-ava" src="${ava}" alt="">
        <b class="tb-menu-name">${XQ_USER.name}</b>
        <span class="tb-menu-sub">${XQ_USER.sub}</span>
      </div>
      <div class="tb-menu-sep"></div>
      <a class="tb-menu-item" href="settings.html" role="menuitem">
        <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3.2" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M12 2.6l1.4 2.6 2.9-.6.6 2.9 2.6 1.4-1.6 2.5 1.6 2.5-2.6 1.4-.6 2.9-2.9-.6L12 21.4l-1.4-2.6-2.9.6-.6-2.9L4.5 15l1.6-2.5L4.5 10l2.6-1.4.6-2.9 2.9.6z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/></svg>
        <span>设置</span>
      </a>
      <!-- ⚠️ 这句话**不是**装饰，是这一格诚不诚实的判据：这套系统真的没有
           账号体系，头像和这行字只存在这台机器上。少了它，这张卡看起来就像
           一个真能登录/退出的账号，那正是上一版"管理员"被否掉的那个形状。 -->
      <p class="tb-menu-note">演示模式 · 未接入真实账号，信息只在本机</p>
    </div>
  </div>`;
};

XQ.clockHTML = ({ title = '', logo = false } = {}) => {
  /* 右上角那一格。★ 2026-09-24：原来是「天气 + 信号格 + 联网 + 小瑞语音状态」
     一整组（类名 env），用户要求**整组去掉**（原话「天气那些去掉」），
     换成同济大学汽车与能源学院的院徽（素材 ui/图片效果/14.png，
     生成脚本 _scratch/_mk_tongji.py）。

     ⚠️ **只有封面传 logo:true**（cover.html 的 mountChrome）。传了走院徽，
        没传走座舱那一组 —— 这就是上面那段说的"两拨东西共用一个格子"。
     ⚠️ 两张图（深色主题一张、浅色主题一张），和 lingtu / CHERY 那几组**同一个
        机制**，见 style.css 里那一段全局说明。别只放一张再拿滤镜凑 ——
        深墨版压深色底会整个消失，白墨版压浅底同理。
     ⚠️ 这段在**模板字符串外面**，所以这里的注释里能用反引号。下面 return 的
        那个模板**里面**一个都不能有 —— 那件事在本文件里踩过五次，
        见 lingtu 那一段和 _scratch/_js_template_scan.py。为了不再考验工具，
        本段注释也一律不用反引号。 */
  const logoSrc = logo
    ? '<img class="collab-logo on-dark" src="/static/assets/tongji_logo.png" alt="">'
      + '<img class="collab-logo on-light" src="/static/assets/tongji_logo_ink.png" alt="">'
    : '';
  /* ❌ **顶栏这边我加过一颗「返回展示页」，被用户当场否掉（2026-09-25）。**
     用户原话：「返回展示页在首页进入座舱那个位置 把进入座舱改成这个」——
     他要的位置是**首页（index.html）那条 `.dash-strip` 里原来那颗
     「进入座舱」**（最重的那颗胶囊，指向 detail.html），做法是**把那颗改成
     「返回展示页」**（指向 cover.html）。所以这一格**照旧是空的**，
     别在这里补一颗 —— 同一个动作放两处，正是 cover.html 那边删掉
     「返回展示页」文字链时记下的那条理由（见那个文件的注释）。
     ⚠️ 那条路现在只有一处入口，所以 `_check_pages.py` 的 C 段（封面流程）
        是**从首页那颗 `.dash-cta` 点回去**的，闭环判据钉在那里。
     ⚠️ 那一段（以及本段）在模板字符串**外面**，但还是不用反引号 ——
        本文件那条规矩，见 _scratch/_js_template_scan.py。 */
  /* ❌ 座舱页右上角那一组 —— **整块删掉了**，现在只剩封面那张院徽。
     三轮删除，都是用户一句话一次：
       · 2026-09-25  「把**智驾相伴 安全出行**、**管理员**去掉，就是顶部那些，
                     感觉多余了」→ 口号和管理员删了，只剩铃铛；
       · 2026-09-25  「把**驾驶监测与报警那个小铃铛**去掉 在顶部」→ 铃铛也删了，
                     这一格在座舱页**彻底空了**。
     ⚠️ 那三件不只是"用户觉得多余"，各自也都立不住：
        · 「智驾相伴 安全出行」和左边 `.brand` 底下那句系统副标题，是**两句话在
          同一个顶栏里并排喊**，第二句并不比第一句多说什么；
        · 「管理员」是照参考图抄的，而**这套系统没有账号体系**（settings 那张卡上
          也明写着没有登录）—— 它点不动、没有下拉，是个纯装饰的假控件。
        · 铃铛（跳 detail.html，小红点由 `body[data-sev]` 驱动）删掉之后，
          **全站少了一处"当前有报警"的常驻提示** —— 这是这次删除的代价，
          我上一版正是拿这条当理由留它的。用户要的是干净的顶栏，删了。
          留下的报警提示是**页面内部那几处**：驾驶监测页的档位卡 / 底部提示条、
          首页的 `data-sev` 整页染色、底部小瑞那一句。
          将来若要找回一个常驻指示，**先问用户**，别拿这段注释当授权加回来。
     ⚠️ 删掉的类（`.tb-slogan` / `.tb-user` / `.tb-ava` / `.tb-name` / `.tb-caret`
        / `.tb-bell`）在 style.css 里**连规则一起删干净了** —— 留着一堆没人用的
        选择器，下次改版会让人以为顶栏还有那一组。
     ⚠️ `.collab` 这一格**留着**（只是空的）：`.topbar` 是 `1fr auto 1fr` 三列，
        这一格是 `auto`，**空着也占住中线** —— 删掉它中间那个标题会在封面上左右跑。
        `_check_theme2.py` 有一条判据钉着"座舱页这一格是空的"，正是这里。
        `_shot_media.py` 里那两行 `bell:` / `slogan:` 量到的是 `null`，
        **那不是坏了**，是它们真的没了。 */
  return `
  <div class="brand">
    <!-- ★ 2026-09-23：**左上角换成灵途智行自己的标志组**（用户点名）。
         原来这里挂的是 CHERY 官方 lockup（chery_logo.png + 一道竖线 + 本组），
         现在把 CHERY 那半截去掉。2026-09-24 晚那一版把剩下的"标志图 + 两行
         HTML 文字"又并成了**整张 lockup** —— 细节见下面那段，这一段的
         「只换左上角、左下角 CHERY 保留」和"反引号会把模板截断"两条**仍然有效**。
         ⚠️ **只换左上角，左下角那个 CHERY 保留** —— 用户明确说了
         「左上角那个标换掉 但是左下角不去除」，所以左下角 rail-foot 那一组里的
         chery_mark.png + CHERY 一个字都不许动，别顺手"统一品牌"。
         ⚠️ 这里原来把 rail-foot 写成反引号包着的代码样式，**那是个真错**：
            反引号在模板字符串里会把模板当场截断，rail-foot 被解析成
            「.rail 减 foot」（属性访问、减号、标识符），运行时抛
            ReferenceError: foot is not defined，整份 chrome.js 不执行。
            ⚠️ 而且 **node --check 是绿的**（截断后仍是合法语法），
               浏览器控制台也**一条错都不报**。防它的是
               _scratch/_js_template_scan.py + _check_theme2.py 的 A0。
         ⚠️ 生成脚本 _scratch/_mk_lingtu2.py。它 2026-09-24 晚**重写过**：
            上一版按 alpha 的列投影找"标志和文字之间那道 >200px 的空列缝"、
            把文字那半切掉只留 G；现在**整张都要**，那一段已经删了。
            别看着"少了一段"就往回加 —— 而且实测整张 lockup 是一块**连通**的
            构图（那几道细线从左贯到右），列投影上根本没有空缝可切。 -->
    <!-- ★ 2026-09-24 晚（第七次改版）：**整张 lockup 直接放上去**。
         用户原话：「我给了灵途智行的标志 直接整张图替换所有左上角出现
         灵途智行标的部分」。所以这里从「标志图 + 两行 HTML 文字」变成
         **一张图**（G + 灵途智行 + 与你同行 + 那几道细线，全在素材里），
         .lingtu 那层 span 和 .lingtu-txt 那两条 CSS 规则一起删掉。
         ⚠️ 那两行字**不是"丢了"**：它们在素材图上，而且是原字体原间距 ——
            再排一遍 HTML 文字只会是同一句话写两遍，字体和间距还永远对不上。
         ⚠️ alt **必须写**（原来留空是"旁边就有真文字、读屏再念一遍是同义重复"，
            现在**图就是名字本身**，留空等于把品牌名从无障碍树里抹掉）。

         ⚠️ **两张图，同一几何，CSS 按主题显一张。**
           两张现在**内容完全相同**（都是原图）—— 2026-09-25 用户拍板
           「整张原图直接贴，不管看不看得见」。为什么会有"两张"这套机制：
           素材是**给深色底做的**（实测文字区 93% 是纯白、G 的左弧一半是纯白），
           而顶栏底色是 #F9FAF8 近白，所以浅色顶栏上那四个字会淡掉 ——
           **这是已知代价，用户明确接受**，别再"修"它。
           ★ 中间被用户打回来过两版填色（按饱和度挑像素填蓝 / 按区域整块铺
             渐变再把文字填成实心蓝），原话「颜色不对啊」「不是蓝色的啊」。
             原因：白字填成实心蓝、G 的白弧被填掉之后，**标志的形状就不成立了**。
             判据是"像不像用户那张图"，不是"在浅底上够不够清楚"。
           ⚠️ 之所以还留两张文件：换主题是靠 display 切 .on-dark/.on-light，
             这套机制和它的检查脚本（_check_theme2.py 的 A0）都还在这儿，
             删文件或改成共享 src 是另一件事，别顺手做。
           两张的 alpha 逐像素相同（_mk_lingtu2.py 里当场断言过 max diff = 0），
           所以切主题时整组**不会跳**。
         ⚠️ 「与你同行」现在**跟着这张图上了顶栏**（原来只有封面 h1 的遮罩图
            lingtu_wordmark_mask.png 上有它）。封面 h1 那处一个字没动，两处各归各的。

         ⚠️⚠️ **这整段注释里一个反引号都不能有。**
            这里是 XQ.clockHTML 那个模板字符串的**内部**，反引号会把模板
            **当场截断**，后面整段变成野代码 —— 整份 chrome.js 因此整个不执行。
            2026-09-23 这个坑当场踩了两次（第二次还是写在"别用反引号"那句警告里），
            表现是**顶栏一片空白、而浏览器控制台一条错都不报**，很难查。
            要强调某个词就用 HTML 的 <b>，别用反引号。
            防它的是 _scratch/_check_theme2.py 里那条
            「chrome.js 的函数真的挂上 XQ 了」——**不是**控制台零报错那条，
            那条对这个坑是瞎的。 -->
    <img class="lingtu-lockup on-dark" src="/static/assets/lingtu_lockup.png"
         alt="灵途智行 · 与你同行">
    <img class="lingtu-lockup on-light" src="/static/assets/lingtu_lockup_ink.png"
         alt="灵途智行 · 与你同行">
    <!-- ★ 2026-09-24（第五次改版）：品牌组右边跟一句系统副标题，照参考图
         首页.png 的顶栏。**只有座舱页有**（logo 为假）—— 封面顶栏中间那一格
         （<b>#tbTitle</b>）写的就是这同一句话，两处一起出现就是同一行字念两遍。
         ⚠️ 它是 .brand 的子节点，所以 .cover-foot .brand（封面页脚那个
            CHERY 组）**不受影响** —— 那边是 cover.html 自己写的 HTML，
            不走这个模板。
         ⚠️ 这里**不能**改叫 .tbtitle 或挂 #tbTitle：_check_theme2.py
            有一条判据钉着「座舱页顶栏中间是空的」，改了就红。
         ⚠️⚠️ 本段在模板字符串**内部**，所以上面一个反引号都没有 ——
            这不是笔误。第一次写这段时给 logo / #tbTitle / .brand 都套了
            反引号，模板当场被劈成四段，正是 _js_template_scan.py 硬判据
            抓的那个形状（两个碎片各拿半个注释标记）。要强调就用 b 标签。 -->
    ${logo ? '' : '<span class="tb-sub">' + XQ_SUB + '</span>'}
  </div>
  <div class="tbtitle" id="tbTitle">${title}</div>
  <!-- ★ 2026-09-25 晚：这一格现在**两拨东西共用一个格子** ——
       封面（logo 为真）放院徽，座舱页（logo 为假）放右上角那个用户入口。
       跟 .brand 里那句系统副标题**同一个开关、同一个理由**（见上面那段）：
       封面顶栏中间写的就是项目主题，座舱页才是"你的车"。
       ⚠️ 两拨**不会同时出现**，所以这里可以简单地二选一；哪天要同时出现，
          先去量 .collab 这一格的宽度够不够，别直接拼。 -->
  <div class="collab">${logo ? logoSrc : XQ.userHTML()}</div>`;
};

XQ.railHTML = ({ active = 'home' } = {}) => {
  /* 这一格现在只剩**导航四项**（下面）和**小瑞立绘**（再下面）。
     ★ 2026-09-24：原来还有一个「数据源」块（演示 / 真人·均衡 / 真人·疲劳 /
     摄像头·实时 四个按钮 + 一个 #srcNote），**整块删掉了**（用户：「数据源栏改成只有
     摄像头实时的 直接不要那个栏 我只要实时的画面」）。源现在只由启动参数决定。

     ⚠️ 删那块带出一条**必须一起改**的东西：`app.js` 和 `settings.html` 里各有一段
     `document.querySelectorAll('.src-btn[data-spec]')` 的绑定循环，专门吃这四个按钮。
     块没了它们会选到 0 个元素（不报错、也不生效），但 `$('srcNote').innerHTML` 那条
     会**当场抛 TypeError**（`#srcNote` 已经不在了）—— 表现是首页的 hello 处理挂掉、
     连问候气泡都出不来。那两处已同步删干净。

     ★★ 2026-09-25：**「小瑞语音」那块也删了**（用户：「小瑞语音 / 出声 /
     Microsoft Xiaoxiao Online (Natural) —— 左边栏不要出现这些」）。
     这里原来有一行 `const voiceBlock = (voice && XQ.tts && XQ.tts.btnHTML) ? … : '';`，
     往 NAV 与立绘之间那个空行里塞 live.js 吐的喇叭按钮；`voice` 这个参数和
     `mountChrome` 里那句 `XQ.tts.bind(rail)` 一起删了（三个传 `voice:true` 的页面
     也各删了一处，见 app.js / chat.html / settings.html）。语音能力本身没动 ——
     静音开关在设置页那张「语音播报」卡上，见 live.js 里那段墓碑注释。
     （下面那个空行就是原喇叭按钮的位置，留着当标记；它是 flex 容器里的纯空白
       文本节点，不会生成匿名 flex item，删不删都不影响版式。）

     ⚠️ **`.src` / `.src-title` / `.src-btn` / `.src-note` 这四个类名现在全站没有使用者了。**
        它们当初是给"数据源块 + 喇叭按钮"借样式用的；两块先后删掉之后，style.css 里
        那几条规则已按本仓库的规矩连根删掉（留了墓碑注释）。**别再往这几行里塞东西** ——
        要加回左栏的块，先去 style.css 的墓碑那段看清原来长什么样再重建样式。 */
  return `
  <div class="rail-card">
    ${NAV.map(([k, label, target, ico]) => `
      <a class="ri${k === active ? ' active' : ''}" href="${target}" data-nav="${k}"
         data-target="${target}">
        <svg viewBox="0 0 24 24" aria-hidden="true">${ico}</svg><span>${label}</span>
      </a>`).join('')}


    <!-- ★★ 2026-09-25（第九次改版）：左栏下面的**小瑞立绘**，点一下换形象。
         用户：「然后做左侧空白处放上小瑞形象是每一页哦 类似多媒体.png左边小瑞那种
         小瑞形象从我给你的图片里找」，随后又补：「而且左下小瑞应该可以**像展示页
         一样**可以点击变换 并且上下浮动」。
         图来自全站共用的 43 张形象库（assets/xq/s/p01..p43.webp，出图脚本
         _scratch/_mk_xq_poses.py），不再有左栏自己的一套。
         底图 = p01：不点的时候看到的就是它，挂在 .mascot-img 上吃 xqIdle 上下浮动。
         路径用**相对 assets/xq/...**（不是 /static/assets/...）：server.py 把
         ui/web/assets 同时挂在 /assets 和 /static/assets 两条上，所以相对路径在
         / 和 /xxx.html 两种深度都指得对，file:// 直接打开也对。上面那两张
         chery_mark 写绝对路径是历史原因，别照抄到这里 —— 换形象时 XQ.poseDeck
         赋的是相对路径，两边混着写同一张图会出现两个 URL。
         位置：它排在四个入口**下面**（2026-09-25 之前中间还夹着喇叭按钮，那块
         连同 voiceBlock 一起删了，所以它现在是从入口直接往下顶到底），靠
         .rail-xr 的 margin-top:auto
         顶到列底并给下面那条播放条留出位置（避让的量是量出来的，见 style.css
         里 .rail-xr 那段）。让它"点一下换形象"的是 XQ.poseDeck()，由
         XQ.railMascot() 在 mountChrome 里调用 —— 那一段的注释写了必须知道的事。
         ⚠️ 这段注释里**一个反引号都不能有**（模板字符串内部），改完跑
            _scratch/_js_template_scan.py。 -->
    <div class="rail-xr" id="railXr">
      <img class="mascot-img" id="railXrImg" src="assets/xq/s/p01.webp" alt="小瑞">
    </div>
  </div>

  <div class="rail-foot">
    <!-- 白墨 + 深墨两张，CSS 按主题显一张（同上方 lingtu 标志那套 .on-dark / .on-light）。
         ⚠️ 为什么需要深色版：cherymark 是**白墨透明底**，压在 12.png 那套近白底上
           等于消失（2026-09-23 刷亮色调时 nav 页左下角就是这么没的）。
           色是 _scratch/_mk_chery_ink.py 刷的，alpha 逐像素没动，所以切主题不跳。
         ⚠️ 上面这几行注释里**一个反引号都不能有** —— 它就在 railHTML 的模板字符串
           里面，反引号会当场把模板截断，整份 chrome.js 不执行、顶栏空白。
           这个坑我踩到第三次了（前两次在 clockHTML 里），有专门的扫描脚本
           _scratch/_js_template_scan.py，改完这个文件**一定要跑一遍**。 -->
    <img class="brand-mark on-dark" src="/static/assets/chery_mark.png" alt="">
    <img class="brand-mark on-light" src="/static/assets/chery_mark_ink.png" alt="">
    <!-- 下面那个 <em> 是**空的**，等用户自己填一句 —— 原来是「以人为本 智慧出行」，
         用户要求换掉但还没定换成哪句。留空比先编一句好：编的那句会被当真。
         CHERY 和 chery_mark.png 不动 —— 那是车标，刚按用户给的 8.png 校准过。 -->
    <span class="rf-txt"><b>CHERY</b><em></em></span>
  </div>`;
};

/* ★ 2026-09-23：`XQ.climateHTML` **整条删掉了**（用户：「下边空调那些一栏 直接去除」）。
   一起删的还有 style.css 里那一整块气候栏样式（`.climate` … `@keyframes spin`）和
   十二个页面里的 `<footer class="climate">`。
   ⚠️ 不是"藏起来"是"删掉"：藏起来的东西会一直在 DOM 里被截图检查脚本数到，
   而这一栏是真的不要了。 */

/* ★ 2026-09-23：`XQ.tickClock` 整个函数**删掉了**（用户「不要在页面顶部放置
   时间日期」，拍板全站）。它做的全部事情就是往 #hhmm / #date 两个元素里写时间，
   而那两个元素已经不在 clockHTML 里了 —— 函数留着就是每 10 秒跑一次、
   两次 getElementById 都返回 null 的空转。
   ⚠️ 连带删的还有下面 mountChrome 里那个 `setInterval(XQ.tickClock, 10000)`。
      只删函数不删定时器的话，控制台每 10 秒会抛一次 "XQ.tickClock is not a function"，
      而且**只在页面开够 10 秒之后才出现** —— 那种错最容易在检查脚本里漏掉。 */

/* ★★ 2026-09-25（第九次改版）：左栏那一格小瑞 —— **点一下换形象，不点就上下浮动**。
   用户原话：「而且左下小瑞应该可以像展示页一样可以点击变换 并且上下浮动」。
   ★ 同一天晚些的第十次改版：用户说「小瑞图片能变化的太少了 我不是有 40 多张图片
   吗 把那些出现小瑞的地方都变成可以变化的」。于是原来那 5 张自己的一套
   （`xiaorui_rail_*.png`）**整套删掉**了，改成全站共用的 43 张形象库 ——
   这一格现在只是 `XQ.poseDeck` 的一个调用点，机制全在 live.js 里。

   ⚠️ 这一格的**尺寸是 `s`**（210x288 那套）。左栏那一格实测 144.8x194.75 px
      （见 _mk_xq_poses.py 里量的数），`s` 在 DPR=2 下 288 > 2x194.75 有余。
      换成 `l`（730x1000）只会每张多下 190 KB，肉眼没差别。
   ⚠️ `class="mascot-img"` **必须挂着**（在 railHTML 的模板里）：上下浮动 `xqIdle`
      和动作位移**都挂在那个类上**（见 style.css）。少了它就只有一张静止图 ——
      用户要的"上下浮动"正是它给的，不是这里再写一个 keyframe。
   ⚠️ `data-act` 的摘除现在由 `XQ.poseDeck` 负责（`swap` 那一下），这一格不再自己
      挂定时器。那十条 animation 都是 `iteration 1` 且没写 `fill-mode`（播完停在
      原地），但只要 `data-act` 还插着，选择器权重就依然高过 `.mascot-img` ——
      `xqIdle` **永远回不来**，这一格就变成"点一下之后就再也不浮动了"。
   ⚠️ 手点挂在**外层 `#railXr`** 上、不挂在 img 上：img 只有图片本身那么大，
      而这一格底下还留着避让播放条的空白，挂外层面积更大、更好点。
      它现在是能点的东西了，所以**不再写 `aria-hidden`**；
      但也不做键盘可达（没有 tabindex/role）—— 和封面那一格保持一致，
      要改就两处一起改，别只改一边。
   ⚠️ **没有预加载了**。原来那 4 张"等 load 了再后台预取"的做法和形象库的口径
      相反：43 张不可能预取，而"只预取前 5 张"会让"点第 6 下突然卡一下"，
      比一直都不预取更让人困惑。统一成"点一下才下这一张"（每张约 32 KB）。
   ⚠️ 这个函数**依赖 live.js 已经加载**（`XQ.poseDeck` 在那边）。每一页的
      `<script src>` 顺序都是 chrome.js -> live.js -> 行内脚本，而它是在
      **行内脚本**里被 `mountChrome` 调到（见每页最后一行的 XQ.mountChrome），
      所以顺序一定对。要是哪天有人把 mountChrome 提到 live.js 之前，
      这里会当场抛 ReferenceError —— 那是好事，别改成静默 return。 */
XQ.railMascot = function (root) {
  const im = root.querySelector('#railXrImg');
  const host = root.querySelector('#railXr');
  if (!im || !host) return;
  XQ.poseDeck(im, host, { size: 's', base: 'p01', title: '点一下换个形象' });
  /* 给检查脚本读（_scratch/_check_railxr.py）。以前是这里自己那 5 个名字，
     现在就是全站那一份 —— 故意**不复制**一份出来，那样两边才会一起变。 */
  XQ.RAIL_POSES = XQ.POSES;
};

/* ★ 2026-09-25 晚：顶栏右上角那颗用户入口的开关。
   ⚠️ 这一格的 DOM 是 mountChrome 用 innerHTML **现塞进去的**，所以事件只能
      在这里绑（跟每页自己的行内脚本没关系）。绑定必须发生在 innerHTML 之后
      —— mountChrome 里就是按这个顺序调的。
   ⚠️ 外面点一下、按 ESC 都要能关：只做"点按钮开关"的话，这个下拉会一直挂在
      屏幕上，而整页导航**不会**帮你把它收掉（点了别处它还在，看着像卡住了）。
   ⚠️ makeChrome 一次加载只调一次，所以这两条 document 级监听不会累积；
      真要在同一页里重复调，得先把旧的摘掉，否则每调一次就多一个监听。 */
XQ.userMenu = function (top) {
  const host = top.querySelector('#tbUser');
  const btn = top.querySelector('#tbUserBtn');
  const menu = top.querySelector('#tbUserMenu');
  if (!host || !btn || !menu) return;
  const close = () => {
    menu.hidden = true;
    btn.setAttribute('aria-expanded', 'false');
  };
  btn.onclick = (e) => {
    /* ⚠️ 这个 stopPropagation 不能省：下面那条 document 上的 click 监听
       就是为了"点外面关掉"而挂的，而按钮自己的这一次 click 同样会冒泡到
       document —— 不拦住的话，同一个点击先把菜单打开、紧接着又被判定成
       "点在按钮外面"而关掉，表现是**菜单永远弹不出来**（且不报错）。 */
    e.stopPropagation();
    const willOpen = menu.hidden;
    menu.hidden = !willOpen;
    btn.setAttribute('aria-expanded', String(willOpen));
  };
  document.addEventListener('click', (e) => {
    if (!host.contains(e.target)) close();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') close();
  });
};

XQ.mountChrome = function (opts = {}) {
  const top = document.getElementById('topbar');
  const rail = document.getElementById('rail');
  if (top) {
    top.innerHTML = XQ.clockHTML(opts);
    /* ★ 2026-09-25 晚：右上角那颗用户入口（只在座舱页出现 —— 封面那一格
       放的是院徽，见 clockHTML）。必须紧跟 innerHTML，理由见函数本体的注释。
       ⚠️ 它在封面上会安静地 return（#tbUser 不存在），那不是坏了。 */
    XQ.userMenu(top);
  }
  if (rail) {
    rail.innerHTML = XQ.railHTML(opts);
    /* 左导航点击：五项现在**全部**有目标页（见 NAV），所以只有两种结果 ——
       跳过去，或者你已经在这一页了。
       ⚠️ 和早先那个"静默 return"不是一回事：那时那几项**根本没有目标页**，
       点了没反应是因为无路可走；现在这一项有目标页，只是它就是你当前所在的
       那一页，而且它身上有 `.active` 高亮明说了"你在这"。点它什么都不做是对的，
       `href` 已经写好，中键/新标签仍然能开。 */
    rail.querySelectorAll('.ri').forEach((a) => {
      a.onclick = (e) => {
        const t = a.dataset.target;
        if (!t || a.dataset.nav === (opts.active || '')) return;   // 让 href 自己走
        e.preventDefault();
        location.href = XQ.href(t);
      };
    });
    /* ★ 2026-09-25：这里原来是 `if (opts.voice && XQ.tts && XQ.tts.bind) XQ.tts.bind(rail);`
       —— 给左栏那个喇叭按钮挂 onclick（开关状态、localStorage、试听那句话都在
       live.js 那边）。按钮整块删了，这一句和 live.js 的 `XQ.tts.bind()` 一起走。
       ⚠️ 删它**不影响** `XQ.tts.set()` / `XQ.speak()`：设置页那张「语音播报」卡是
          自己调 `XQ.tts.set()` 的，不经过这里。 */
    /* ★ 2026-09-25：左栏那一格小瑞点一下换动作。它**不看 opts** ——
       每一页的左栏都有这一格（用户：「放上小瑞形象是每一页哦」）。 */
    XQ.railMascot(rail);
  }
  /* ★ 2026-09-24：这里原来还要调 live.js 那个填顶栏语音标识的函数。
     用户把那整格去掉了（「天气那些去掉」），所以调用和函数**一起删干净**，
     不是留着不调 —— 留一个再也没有落点的函数，下一个人会以为顶栏还在
     显示语音状态。
     ⚠️ 那次删的只是"顶栏那一格显示语音通不通"；左栏那张说明牌（喇叭按钮 +
        voiceNote）当时没动。**2026-09-25 那张牌也删了**（见 railHTML 那段和
        live.js 的墓碑注释）—— 所以语音状态现在**全站没有任何一处显示**，
        只剩设置页那张卡能开关它。 */
};

/* ★ 2026-09-24：这里原来有一整个 XQ.env 模块（上面那段长注释 + IIFE），
   做两件事：实时取本机天气（ip-api 定位 → open-meteo 取气温），
   以及探测端到端联网状态。用户要求「天气那些去掉」，整块删掉了。

   ⚠️ **不是"藏起来"**：模板里的元素、style.css 的规则、这个模块、
      以及 mountChrome 里那句 init 调用，四处一起删。只删一处的话剩下的会
      静默空转 —— 最典型的是留着一分钟一次的定时器，每轮 getElementById
      都拿到 null。这个坑本项目在删时钟（tickClock）和气候栏（climateHTML）
      时已经各踩过一次，两次都是"连根删"，这次照做。

   ⚠️ 删掉的是**显示**，不是能力。那套代码在 git 历史里，
      `_scratch/_bak_cover/chrome.js` 也有本次删除前的原件。
      要恢复就整块拿回来 —— 别只把模板那一格补上，那样它永远是「取天气…」。

   顶栏右上角现在放的是同济院徽，只在封面出现，见 XQ.clockHTML。 */
/* 跳转用的路径。**现在就是个恒等函数，留着是因为它是个收口点** ——
   所有页面路径本来就写成相对路径（`index.html`、`nav.html`），服务器上和
   `file://` 直接打开都算得对，所以两个分支本来就一样。
   ⚠️ 早先这里的注释写着"file:// 时退回相对路径"，那是在描述一个**没写出来的
   分支**（`? p : p` 两个分支一模一样）。真要做绝对路径的那天，改这一个函数。 */
XQ.href = (p) => p;
