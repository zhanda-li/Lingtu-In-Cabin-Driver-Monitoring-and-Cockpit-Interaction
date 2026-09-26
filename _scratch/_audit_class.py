# -*- coding: utf-8 -*-
"""**裸类名撞车**审计：detail.html 里用到的 class，有没有和一个"光杆单类选择器"
（`.foo{...}` 这种，没有任何祖先/标签限定）重名。

为什么要专门查这一种：类名撞车在本项目已经咬了两次，两次都不是"样式二选一"那么
温和，而是**另一处的规则悄悄跟了过来**：
  · `.ring`  —— pages.css 里我给评分环写的那条 `.ring{position:relative}`
                 把 style.css 里小瑞那两圈光晕也改成了相对定位（光晕不是 `!` 而是
                 `position:absolute; inset:6%`），两圈于是上下排开、把小瑞顶出卡片；
  · `.nt`    —— 首页 `.ntiles .nt` 那张白底胶囊是**光杆的 `.nt{}`**，
                 我的 `.cam-bar .nt` 只覆盖了我写到的属性，白底和圆角照样跟过来。

判据：光杆 `.foo{}` 里的 `foo` 就是**全站共享**的，谁用谁继承它的全部属性。
所以新写的页面**不要复用这些名字**，要么换名，要么自己也写一条光杆规则覆盖它
（但那会污染别处），要么把对方那条也加上祖先限定（动别人的样式，风险更大）。

    python _scratch/_audit_class.py ui/web/detail.html
"""
import io
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CSS = ["ui/web/style.css", "ui/web/pages.css"]


def bare_names(path):
    """收集「光杆单类选择器」的类名：`.foo{...}`、`.foo, .bar{...}` 这种。"""
    txt = io.open(path, encoding="utf-8").read()
    txt = re.sub(r"/\*.*?\*/", "", txt, flags=re.S)          # 去掉注释，免得把例子当规则
    names = {}
    for m in re.finditer(r"(?:^|[}{;])\s*([^{}]*?)\{", txt):
        sel = m.group(1).strip()
        if not sel or sel.startswith("@"):
            continue
        for one in sel.split(","):
            one = one.strip()
            mm = re.fullmatch(r"\.([A-Za-z_][\w-]*)", one)
            if mm:
                names.setdefault(mm.group(1), path)
    return names


def classes_used(path):
    txt = io.open(path, encoding="utf-8").read()
    used = set()
    for m in re.finditer(r'class="([^"]*)"', txt):
        for c in m.group(1).split():
            used.add(c)
    return used


bad = {}
for p in CSS:
    for n, src in bare_names(p).items():
        bad.setdefault(n, src)

used = classes_used(sys.argv[1])
hit = sorted(n for n in used if n in bad)
print("裸类名（全站共享）一共 %d 个：" % len(bad))
print("  " + " ".join(sorted(bad)))
print()
print("%s 用到 %d 个 class，其中和裸类名撞车的：" % (sys.argv[1], len(used)))
if not hit:
    print("  （一个都没有）")
for n in hit:
    print("  ⚠️  .%-14s 裸规则在 %s" % (n, bad[n]))
