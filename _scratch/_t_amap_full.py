# -*- coding: utf-8 -*-
"""收尾核对：`search(..., full=True)`（**上屏那一下**那条路）到底并出了什么。

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch\\_t_amap_full.py

`_t_nav_type.py` 走的是**打字**那条（`full=False`），全过；这一条补上没被它盖到
的那一半：叫得全的地名（「无锡」→「无锡市」）和看得懂的分类（`type`）是不是真
的从 `place/text` 并进来了 —— 那是加 `full` 的**全部理由**，不验就等于没加。
⚠️ key 只在进程里用，一个字都不打印。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from deepseek import load_config                             # noqa: E402
from amap import AMap                                        # noqa: E402


async def main():
    cfg = load_config(None)
    am = AMap(cfg.get("amap") or {})
    if not am.configured():
        print("没配 key")
        return 1
    # 起点给静海（= 页面里 PRESETS[0]），和真跑时一样带上偏置。
    # ⚠️ 这四个词各有各的用途，别随手改：
    #    无锡     —— 整地名（「无锡市」）是不是真并进来了
    #    服       —— `place/text` 对**单字**是空的，这条本来就该并不出东西
    #    服务区   —— 演示里最可能敲的词，头几条得是真服务区
    #    无锡站   —— **页面 `resolveBox()` 那个"一字不差就自动用"的判据**看的是
    #                `list[0].name`；`full` 把 place/text 挪到前面之后，这一条的
    #                头一名必须还是「无锡站」本身，否则按回车会从"直接算路"
    #                退成"摆一张表让人点"。
    for kw in ["无锡", "服", "服务区", "无锡站"]:
        a = await am.search(kw, full=False, lat=38.96, lng=116.88)
        b = await am.search(kw, full=True, lat=38.96, lng=116.88)
        na = [x["name"] for x in a["list"]]
        nb = [x["name"] for x in b["list"]]
        typed = [x for x in b["list"] if x["type"]]
        print("\n「%s」 打字 %d 条 / 上屏 %d 条" % (kw, len(na), len(nb)))
        # ⚠️ 空表必须把 `why` 也打出来 —— 这个 key 的 QPS 很低，"上屏 0 条"
        #    既可能是没搜到、也可能是**这一发被高德限流了**，两者的处置完全相反
        #    （一个"换个词"，一个"等一会儿"）。不打出来就会把限流读成"没结果"。
        for tag, r in (("打字", a), ("上屏", b)):
            if not r["ok"]:
                print("   %s 没成：%s" % (tag, r["why"]))
        print("   上屏多出来的：%s" % ([x for x in nb if x not in na] or "（没有）"))
        print("   带上分类的  ：%s" % ([(x["name"], x["type"]) for x in typed[:3]]
                                     or "（一条都没有）"))
        print("   头三条      ：%s" % nb[:3])
        print("   一字不差能自动用吗：%s（第一名=%s）"
              % ("能" if (nb and nb[0] == kw) else "不能，会摆表让人点",
                 nb[0] if nb else "（空）"))
        await asyncio.sleep(1.2)      # 这个 key 的 QPS 撑不住背靠背地打
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
