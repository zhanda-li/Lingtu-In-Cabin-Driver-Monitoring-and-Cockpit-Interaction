"""找出 JS 里「写在模板字符串**内部**的反引号」—— 这一类错 `node --check` 抓不到。

    python _scratch/_js_template_scan.py ui/web/chrome.js [更多文件...]

## 为什么需要单独一个脚本

2026-09-23 我在 `XQ.clockHTML` 的模板里写了一句注释：
    「……所以 `.rail-foot` 里的 chery_mark.png……」
那两个反引号**把模板当场截断**了，于是这一小段

    所以 `.rail-foot` 里的

被解析成：

    (`……所以 `) .rail  -  foot  -  (`里的……`)

—— 是**合法语法**（属性访问 `-` 减号 `-` 标识符），
所以 `node --check` 一路绿灯；运行时才炸 `ReferenceError: foot is not defined`。
更坏的是**浏览器控制台一条错都不报**（本项目的 CDP 收报错那条也对它瞎），
表现只是"顶栏一片空白"，完全看不出跟一个反引号有关。

**一个错的反引号不用成对就能造成这种后果**，所以我需要的不是"数一数奇偶"
（奇偶是 `node --check` 已经会做的），而是**位置**：
在模板里，哪一个反引号**不该在那儿**。

## 判据（第一版写错过，记下来）

第一版判据是「收尾反引号后面必须跟代码符号 `;` `,` `)` …」。**太糙**：
三元表达式的 `` `a` : `b` `` 那个收尾后面跟的是 `:`，被误报了；
更糟的是**一旦误报，状态机就跟着解析器的真实走向提前弹了一层**，
后面所有行全错位、报出一堆噪音（第一版就这样把 live.js / app.js 也刷了一片）。

现在是**两条同时成立**才算数（缺一条就全是噪音）：

  判据一 · **埋在中文散文里**：紧挨着这个反引号（跳过空格）的前一个字符是 CJK，
          或后一个字符是 CJK。
  判据二 · **这个模板是跨行的**（开引号在更早的一行）。

为什么非要加判据二：只留判据一的话，`app.js` 里
`` flash(`已经在用「${…}」这一路了`) `` 这种**内容本来就是中文**的合法单行模板
会被整片误报（收尾反引号前面正好是个「了」）。而本项目真正踩的那种，
是**跨行的 HTML 大模板里夹了一句中文注释**，行内模板从来不这么写。

  · 真出事的写法：`所以 `.rail-foot` 里的`（模板从第 32 行开到第 37 行）→ 两条都中
  · `` flash(`…了这一路了`) `` → 判据二不中 → 不报
  · 三元 `` `a` : `b` `` → 判据一不中 → 不报

## ★ 2026-09-24 补了一条**硬**判据（上面两条当时漏掉了一次真实事故）

事故现场：`chrome.js` 的 `XQ.clockHTML` 模板里写了一句注释，注释里给 `.voice`
套了一对反引号。**上面两条判据一条都没中**，脚本报了「通过」。原因很具体 ——
判据一只看**紧挨着**反引号（跳过空格和 tab）的字符，而那个反引号是在**行首缩进
之后**开的，它的前一个字符是换行、后一个是 `.`，两个都不是 CJK，于是判据一
不成立、判据二不成立、整条不报。表现是 index.html 顶栏和左导航**整个空白**，
控制台只有一句 `title.voice is not a function @ chrome.js:139`。

补的这条是**硬判据**，不是"可疑"：

    模板正文里的 HTML 注释必须配平 —— `<!--` 和 `-->` 数量相等。

为什么这条是**可靠的**而不是又一个启发式：本项目的大模板里夹注释是**成文习惯**
（`<!-- ... -->` 到处都在），而模板一旦被反引号截断，截断点几乎必然落在一句
中文注释**中间**，于是两个碎片各自拿到半个注释标记 —— 一个只有 `<!--`，
另一个只有 `-->`。事故那天出的正是这个形状（前一个模板有 `<!--` 没 `-->`，
后一个反过来），两条都会被这条判据抓住。合法的完整模板里注释永远配平，
所以它**没有误报面**。

⚠️ 顺带记一条**没用**的判据，别再写第二遍：数反引号的奇偶。事故那次是**成对**
   加进去的（`.voice` 左右各一个），总数从 136 变 140，奇偶**照样是偶**。
   奇偶只能抓"落单一个"，抓不到成对写进去的那种 —— 而后者恰恰更常见。

⚠️ 上面两条"可疑"判据和这条"硬"判据**都只是预筛，都不能当放行**。
   真正算数的防线是**把页面跑起来**：改完 `chrome.js` 就跑一遍
   `_check_pages.py`（它真的 goto 每一个页面），退一步至少跑
   `_check_theme2.py` 的 A0（把每个 XQ.* 函数真调一遍）。
   事故那天 `node --check` 过了、这个脚本也说"通过"，是**浏览器**抓住的。

## ★ 2026-09-25：改完一定要**先**跑 `node --check`

    D:\node.exe --check ui/web/player.js

那天我在 `player.js` 的 CSS 模板里连写三处行内代码反引号，三次都是
**`node --check` 报出来的**，这个脚本一次都没报（那种形状是"模板被截断后
剩下的碎片恰好不是合法表达式"，落在上面两条启发式的缝里 —— 判据一要求
反引号紧挨 CJK，而 `` （`paint()` `` 这种是"中文括号 + 反引号"，
反引号前一个字符是 `（`（全角括号，不在 CJK 区里））。

两边管的是**不同的坏法**，所以两边都要跑，别拿一个替另一个：

  · `node --check`  —— 抓"截断后不是合法语法"的。快、硬、零误报。
  · 这个脚本       —— 抓"截断后**恰好是**合法语法"的（`a `x` b` 那种）。
                      那天 `chrome.js` 的 `.rail-foot` 就是这一种，
                      `node --check` 一路绿灯。

顺带：**这个脚本不传文件不会报错**，只是空转 —— 上面已经改成直接返回 1。
"""

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CJK = re.compile(r"[　-〿一-鿿＀-￯]")


def buried_in_prose(src, i):
    """反引号 src[i] 是不是埋在中文散文里。"""
    j = i - 1
    while j >= 0 and src[j] in " \t":
        j -= 1
    if j >= 0 and CJK.match(src[j]):
        return True
    k = i + 1
    while k < len(src) and src[k] in " \t":
        k += 1
    return k < len(src) and bool(CJK.match(src[k]))


def scan(path):
    """用一个最小的 JS 词法状态机走一遍。

    返回 (susp, hard, lines)：
      · susp —— "可疑"表 [(行号, 列号, 模板起始行)]，判据一+判据二；
      · hard —— **硬**表 [(模板起始行, 结束行, '<!--'数, '-->'数)]，
                模板正文里 HTML 注释不配平。见文件头那段。
    """
    src = Path(path).read_text(encoding="utf-8")
    # 状态栈。'tpl' = 模板正文，'code' = 代码（含模板里的 ${...}），
    # 'sq' / 'dq' = 普通字符串，'bc' = 块注释，'lc' = 行注释
    st = ["code"]
    tpl_open = []        # 每个在栈里的模板是在第几行开的（判据二要用）
    tpl_buf = []         # 每个在栈里的模板**已走过的正文**（硬判据要用）
    susp, hard = [], []
    i, line, col = 0, 1, 1

    def peek(k=0):
        j = i + k
        return src[j] if j < len(src) else ""

    while i < len(src):
        c = src[i]
        top = st[-1]

        if c == "\n":
            if top == "lc":
                st.pop()
            if top == "tpl":
                tpl_buf[-1].append(c)
            line, col = line + 1, 1
            i += 1
            continue

        if top == "lc":
            i, col = i + 1, col + 1
            continue

        if top == "bc":
            if c == "*" and peek(1) == "/":
                st.pop(); i += 2; col += 2; continue
            i, col = i + 1, col + 1
            continue

        if top in ("sq", "dq"):
            want = "'" if top == "sq" else '"'
            if c == "\\":
                i, col = i + 2, col + 2; continue
            if c == want:
                st.pop()
            i, col = i + 1, col + 1
            continue

        # ---- 代码 / 模板正文 ----
        if c == "/" and peek(1) == "/":
            st.append("lc"); i += 2; col += 2; continue
        if c == "/" and peek(1) == "*":
            st.append("bc"); i += 2; col += 2; continue

        if c == "`":
            if top == "tpl":
                # 候选收尾。两条判据都中才算 —— 见文件头那段"为什么非要加判据二"。
                if tpl_open and line > tpl_open[-1] and buried_in_prose(src, i):
                    susp.append((line, col, tpl_open[-1]))
                # ★ 硬判据：这个模板的正文里 HTML 注释配不配平。
                #   截断会在一句中文注释中间把它劈成两半，两个碎片各拿半个标记。
                body = "".join(tpl_buf[-1])
                o, cl = body.count("<!--"), body.count("-->")
                if o != cl:
                    hard.append((tpl_open[-1], line, o, cl))
                st.pop()                      # 收尾，回到上一层
                tpl_buf.pop()
                if tpl_open:
                    tpl_open.pop()
            else:
                st.append("tpl")              # 开一个模板
                tpl_open.append(line)
                tpl_buf.append([])
            i, col = i + 1, col + 1
            continue

        if top == "tpl":
            if c == "$" and peek(1) == "{":
                # ⚠️ 这里**不往 tpl_buf 里塞**：`${` 后面是**代码**不是正文，
                #    而代码里出现 `<!--`/`-->` 是不可能的，塞了只会干扰计数。
                st.append("code"); i += 2; col += 2; continue
            tpl_buf[-1].append(c)
            i, col = i + 1, col + 1
            continue

        # ---- 纯代码 ----
        if c == "'":
            st.append("sq")
        elif c == '"':
            st.append("dq")
        elif c == "}" and len(st) > 1 and st[-2] == "tpl" and st[-1] == "code":
            st.pop()                          # ${...} 收尾，回到模板正文
        i, col = i + 1, col + 1

    return susp, hard, Path(path).read_text(encoding="utf-8").split("\n")


def escaped(t, i):
    """`t[i]` 前面那串反斜杠是奇数个吗 —— 奇数 = 这个字符被转义了。"""
    k, j = 0, i - 1
    while j >= 0 and t[j] == "\\":
        k, j = k + 1, j - 1
    return k % 2 == 1


def count_marker(t, marker):
    """数 `marker`，但**跳过后一个字符被反斜杠转义的**那些。

    ★ 2026-09-26 补。起因是一个**恒红的误报**：`about.html` / `flow.html` 里
    各有一个 markdown 加粗用的正则字面量

        .replace(/\\*\\*(.+?)\\*\\*/g, '<b>$1</b>')

    —— 写出字符序列是 `\ * \ * / g`，里面第 3~4 位是一个**转义掉的星号**
    紧接着 `/`，裸 `text.count("*/")` 会把它数成一个注释收尾（`/*` 那边没有
    对应物，于是恒差 1）。把这两个正则从文本里剔掉之后两页的块注释正好
    20/20、15/15 —— 也就是说**红的不是页面，是这把尺子**。

    一条永远红的护栏比没有护栏更坏：它会教人学会忽略它，然后盖住真正的
    那次"缺收尾 `*/`、一大段代码被吞成注释"（见上面那段事故）。所以这里
    按 JS 的词法规则办事 —— **反斜杠转义掉的星号不是运算符**，不参与计数。
    （奇偶都算：`\\\\*/` 前面那串是偶数个，那个 `*` 是真星号，照数。）

    ⚠️ 它仍然证明不了**位置**对不对（多开一个 + 后面多收一个，计数照样相等），
       也仍然会把字符串/正则里**没转义**的 `/*` 数进去。真要漏，靠的还是把
       页面跑起来。
    """
    n, i = 0, t.find(marker)
    while i >= 0:
        if not escaped(t, i):
            n += 1
        i = t.find(marker, i + 1)
    return n


def comment_balance(path):
    """`/*` 和 `*/` 的**全文件计数**是否相等。返回 (n_open, n_close)。

    ★ 2026-09-24 加。为什么要在这儿加：改封面那天把 live.js 里一整块 JSDoc
    连同它后面的方法一起换掉，新注释**只有开头的 `/*`、没有收尾的 `*/`** ——
    于是 `bind(root) {` 和它后面一大段**全成了注释体**，喇叭按钮的点击处理根本
    没绑上。而这件事：

      · `node --check` **是绿的** —— 注释掉的东西仍然是合法语法；
      · 本脚本原来只数模板里的 `<!--`/`-->`，对这种一窍不通；
      · 浏览器控制台**一条报错都没有**。

    只有"跑起来点一下"才抓得到（`_check_pages.py` 那条「点喇叭真的能开关」）。
    计数一条就够便宜，所以在这儿补上 —— 它管的是**全文件**，包括模板外面
    那些注释，正好补住原来那块空白。

    ⚠️ 它证明不了的事：**位置**对不对。`/*` 和 `*/` 个数相等而错位（比如在前面
       多开一个、在后面多收一个）它看不出来。真有那天，靠的还是把页面跑起来。

    ★ 2026-09-26：计数改走 `count_marker()`（跳过转义掉的星号）。原因写在那边 ——
       简言之，两个页面里的 markdown 正则 `/\*\*…\*\*/g` 让裸 `count()` **恒报**
       多收一个 `*/`，而那两页的块注释一个不缺。
    """
    t = Path(path).read_text(encoding="utf-8")
    return count_marker(t, "/*"), count_marker(t, "*/")


def main():
    bad = 0
    # ★ 2026-09-25 补：**不传文件不是"通过"，是"什么都没扫"**。
    #   我自己就踩过：先写反引号把 player.js 弄成语法错，然后不带参数跑这个脚本，
    #   看到一句「扫描通过」就以为没事了 —— 实际上那个 for 循环一次都没进。
    #   一句"通过"配上一个空输入，比报错危险得多。
    if len(sys.argv) < 2:
        print("  !!  没给文件 —— 这个脚本**不会自己找文件**，"
              "刚才什么都没扫。用法：")
        print("         python _scratch/_js_template_scan.py ui/web/player.js ...")
        return 1
    for p in sys.argv[1:]:
        n_open, n_close = comment_balance(p)
        if n_open != n_close:
            bad = 1
            d = n_open - n_close
            print("  !!  %s：块注释**不配平** —— `/*` %d 个，`*/` %d 个"
                  % (p, n_open, n_close))
            print("        → %s 了 %d 个。"
                  % ("有代码被注释吞掉（缺收尾 `*/`）" if d > 0
                     else "多收了 `*/`（有代码漏在注释外面）", abs(d)))
            print("        ⚠️ `node --check` 对这条是瞎的（注释里的东西仍是合法语法），"
                  "浏览器控制台也不会报错。")
        susp, hard, lines = scan(p)
        if not susp and not hard:
            if n_open == n_close:      # 不配平时上面已经报过了，别再补一句 OK
                print("  OK  %s（模板里没有多余的反引号，块注释配平）" % p)
            continue
        bad = 1
        if hard:
            print("  !!  %s：%d 个模板的 HTML 注释**不配平**（硬判据）" % (p, len(hard)))
            for opened, closed, o, cl in hard:
                print("        模板 第 %d~%d 行：<!-- 出现 %d 次，--> 出现 %d 次"
                      % (opened, closed, o, cl))
                print("        → 八成是被反引号劈成了两半，去看第 %d 行前后。" % opened)
        if susp:
            print("  ?   %s：%d 处可疑反引号（启发式，可能是误报）" % (p, len(susp)))
            for line, col, opened in susp:
                print("        第 %d 行 第 %d 列（模板从第 %d 行开到这里）： %s"
                      % (line, col, opened, lines[line - 1].strip()[:90]))
    print("\n" + ("**有问题，见上**" if bad
                  else "**扫描通过**（注意：这只是语法层的；真正算数的是**把页面"
                       "跑起来** / 把每个 XQ.* 函数**真调一遍**，"
                       "见 _check_pages.py 和 _check_theme2.py 的 A0）"))
    return bad


if __name__ == "__main__":
    sys.exit(main())
