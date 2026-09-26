# -*- coding: utf-8 -*-
"""把高德的**错误码**一个个真撞出来 —— 别照记忆改 `CODE_CN`。

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch\\_t_amap_codes.py

`ui/amap.py` 的 `CODE_CN` 那张表上头写着一条规矩（第 65-67 行）：**表里只许放
实测过的码**，因为"编一个具体的解释"正是这一整件事的起因。可表里现在有几行是
**照记忆写的**，而且自相矛盾：`10021` 在表里写着「数字签名没通过（安全密钥对不
上）」，可 `search()` 的注释里又拿它当"问得太快、等一会儿"用。
（`10019`/`10012`/`20000` 同样可疑。）

所以这一条**不猜**，四种错一个个撞出来看 `infocode` + `info` 原文：
  ① 假 key            —— key 不认是哪个码
  ② 参数缺必填        —— 少参数是哪个码
  ③ 限流（连着快打）  —— 撞 `CUQPS_…` 那一个到底是几号
  ④ 平台不符          —— 拿 JS 那把 key 打 Web 服务接口（这一条**故意不做**：
                         那要读出 config 里另一把 key，见下）
⚠️ key 只在进程里用，**一个字都不打印**（memory：绝不把 config.json 的值倒进
   工具输出）。这一条只打 `status`/`infocode`/`info` —— 那三个是高德自己的话。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from deepseek import load_config                             # noqa: E402
from amap import AMap                                        # noqa: E402

ROWS = []


def show(tag, r):
    d = r.get("data") if isinstance(r, dict) else None
    if isinstance(d, dict):
        st, code, info = d.get("status"), d.get("infocode"), d.get("info")
    else:
        st = code = info = None
    # `_rest` 失败时 why 是"人话（码 xxx）"，日志里那行才有高德原文
    print("   %-22s ok=%-5s status=%-4s infocode=%-6s info=%s"
          % (tag, r.get("ok"), st, code, info))
    if code:
        ROWS.append((str(code), str(info)))
    return r


async def main():
    cfg = load_config(None)
    real = (cfg.get("amap") or {}).get("web_key") or ""
    if not real:
        print("没配 web_key")
        return 1
    am = AMap(cfg.get("amap") or {})

    print("\n① 正常一次（对照组）")
    show("place/around 正常", await am._rest("place/around", {
        "keywords": "服务区", "location": "116.88,38.96", "radius": 30000}))

    print("\n② 假 key（key 不认）")
    bad = AMap(dict(cfg.get("amap") or {}))
    bad.web_key = "0" * 32
    show("假 key", await bad._rest("place/around", {
        "keywords": "服务区", "location": "116.88,38.96", "radius": 30000}))

    print("\n③ 少必填参数（`place/around` 不给 location）")
    show("缺 location", await am._rest("place/around", {"keywords": "服务区"}))

    print("\n④ 空关键词")
    show("空 keywords", await am._rest("place/text", {"keywords": ""}))

    print("\n⑤ 限流：连着快打 15 发（同一秒里）")
    hits = []
    for i in range(15):
        r = await am._rest("place/around", {
            "keywords": "服务区", "location": "116.88,38.96", "radius": 30000})
        d = r.get("data") if isinstance(r.get("data"), dict) else {}
        code, info = str(d.get("infocode")), str(d.get("info"))
        if code != "10000":
            hits.append((i, code, info))
            print("   第 %2d 发 → infocode=%s info=%s" % (i, code, info))
            ROWS.append((code, info))
            if len(hits) >= 3:
                break
    if not hits:
        print("   15 发全过（这个 key 的 QPS 比 15/s 高，或者这一秒没被算进去）")

    print("\n⑥ 平台不符：拿 **JS API 那把 key** 打 Web 服务接口")
    # ⚠️ 这一条**故意用 js_key**：它是设计上就该出现在页面源码里的那个（见
    #    `ui/amap.py` 文件头），不是 `web_key`。只打高德回的码，key 本身不打印。
    js = (cfg.get("amap") or {}).get("js_key") or ""
    if not js:
        print("   config 里没配 js_key —— 跳过")
    else:
        jsr = AMap(dict(cfg.get("amap") or {}))
        jsr.web_key = js
        show("JS key 打 REST", await jsr._rest("place/around", {
            "keywords": "服务区", "location": "116.88,38.96", "radius": 30000}))

    print("\n══ 实测撞到的码 ══")
    for code, info in sorted(set(ROWS)):
        print("   %-6s %s" % (code, info))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
