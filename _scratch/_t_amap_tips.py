# -*- coding: utf-8 -*-
"""高德有没有一个**为"打字时给候选"设计**的接口 —— 一个字也能出东西？

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch\\_t_amap_tips.py

背景（2026-09-26 用户）：「我在起点终点每输入一个字 都要有相关的地点推荐啊
不要我点enter才推荐以及去除字才推荐」。
`_t_nav_type.py` 量到的事实：`v3/place/text` 对**一个字**基本是空的
（「无」「站」「服」全回 count=0，`status=1 infocode=10000` —— 不是坏了、不是限流）。

所以这一条量的是**另一个接口** `v3/assistant/inputtips`（高德文档里就是干
"输入提示"这件事的）。判据同全项目：`status=="1"` 且 `infocode=="10000"`；
再看它一条候选里**有没有坐标**（`location`）—— 没坐标的候选点了也画不出来。

⚠️ key 只在进程里用，**一个字都不打印**（见 memory：绝不把 config.json 的值
   倒进工具输出）。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from deepseek import load_config                             # noqa: E402
from amap import AMap                                        # noqa: E402

KWS = ["无", "站", "服", "静", "无锡", "无锡站", "服务区", "静海", "京沪高速"]


def brief(p: dict) -> str:
    loc = (p.get("location") or "").strip()
    return "%-22s | %-10s | %s" % (
        (p.get("name") or "")[:22], (p.get("district") or "")[:10],
        ("有坐标 " + loc) if loc else "**没坐标**")


async def main():
    cfg = load_config(None)
    am = AMap(cfg.get("amap") or {})
    print("configured=%s  enabled=%s" % (am.configured(), am.enabled))
    if not am.configured():
        print("没配 key —— 先看 ui/config.json 的 amap 那一段。")
        return 1

    # ★ 只给 `location`（不给 city / 不给 citylimit）会不会把候选拉到身边？
    #   页面那头只有"起点在哪"这一个已知量，拿它当偏置最省事 —— 但**先量**。
    print("══ inputtips · 只给 location（无锡 120.3019,31.5800），不给 city ══")
    for kw in ["站", "服", "静", "无", "服务区"]:
        r = await am._rest("assistant/inputtips",
                           {"keywords": kw, "datatype": "all",
                            "location": "120.3019,31.5800"})
        if not r["ok"]:
            print("   「%s」 失败 %s" % (kw, r["why"]))
            await asyncio.sleep(0.3)
            continue
        tips = [t for t in (r["data"].get("tips") or [])
                if (t.get("location") or "").strip()]
        print("   「%s」 有坐标 %d 条 → %s" % (
            kw, len(tips),
            " / ".join((t.get("name") or "")[:14] for t in tips[:3])))
        await asyncio.sleep(0.3)

    for city in (None, "无锡", "上海"):
        print("\n══ inputtips · city=%s ══" % (city or "（不给）"))
        for kw in KWS:
            q = {"keywords": kw, "datatype": "all"}
            if city:
                q["city"] = city
                q["citylimit"] = "true"
            r = await am._rest("assistant/inputtips", q)
            if not r["ok"]:
                print("   「%s」 **失败** %s" % (kw, r["why"]))
                await asyncio.sleep(0.3)
                continue
            tips = r["data"].get("tips") or []
            good = [t for t in tips if (t.get("location") or "").strip()]
            if tips and kw == KWS[0]:
                print("   （一条 tip 到底有哪些字段：%s）"
                      % sorted(tips[0].keys()))
                print("   （原样一条：%s）"
                      % {k: v for k, v in tips[0].items() if k != "id"})
            print("   「%s」 tips=%d 有坐标=%d" % (kw, len(tips), len(good)))
            for t in good[:3]:
                print("        %s" % brief(t))
            if tips and not good:
                print("        （全都没坐标，例：%s）"
                      % brief(tips[0]))
            await asyncio.sleep(0.3)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
