# -*- coding: utf-8 -*-
"""高德地图：**服务端**这一半（周边搜索 + 驾车路线）。

 ── 为什么要有这个文件 ────────────────────────────────────────────
   `ui/xiaorui.py` 的 `SCRIPT['nearby']` 原来四档全部写死「前方 12 公里有一个服务区」，
   `severe` 那档甚至是完成时「**我已经把路线准备好了**」—— 而这条路径上没有任何
   导航实现。用户拿到两把高德 key 之后拍板：数字要真的。这个文件就是"真的"的来源。

 ── 两把 key 谁去哪（**类型不能混用**）──────────────────────────────
   · `js_key` + `security_js_code`（「Web端(JS API)」类型）→ **下发到页面**，
     页面拿它建地图。按高德 JS API 2.0 的设计这两个值**本来就会出现在页面源码里**，
     真正的保护是控制台里的**域名白名单**，不是在代码里藏。
   · `web_key`（「Web 服务」类型）→ **只在服务端**，打 `restapi.amap.com`。
     ⚠️ **绝不能进 `hello()`** —— 那是**广播**，12 张页面（和 12 个浏览器的
     devtools）都收得到。`status()` 里也没有它，连打码的尾巴都没有：
     和 `wechat.py` 的 webhook 是同一个道理。
   · 拿错平台去调 restapi 会回 `USERKEY_PLAT_NOMATCH(10009)`，而且 key 的
     **平台类型建了就改不了**，只能新建一个 —— 所以这个文件宁可把话说清楚，
     也不做"两个 key 互相兜底"那种机灵事。

 ── 三条会静默出错的（和 `wechat.py` 文首那三条同一个血统）────────────
  1. **HTTP 200 不等于成功。** 高德出错也回 200，真正的判据是 JSON 里的
     `status == "1"` **且** `infocode == "10000"`。只看状态码 = 静默失败：
     界面上写着"最近的 12 公里"，其实那条是编的。所以这里**要求两个字段都对**
     才算成功，失败记 `last_error` 并且**绝不返回编造的数字**。
  2. **绝不阻塞主循环。** 一次网络超时就是几秒，挂在 8 Hz 的 `tick()` 上
     界面直接卡住（`wechat.py` 那条注释说的同一件事）。所以请求一律 `await`，
     而且**缓存由页面自己那一问就热了** —— 见下面 `_cache` 那段和文件末尾那块
     墓碑（当初写过 `prewarm()`，后来发现"页面拿到定位就查一次"本身就是预热）。
  3. **缓存键要取整。** 浮点坐标直接当键 = 每帧一个新键，缓存永远不命中。
     取到 3 位小数（≈111 m）够用：车在动，但服务区不会因为 100 m 换一个。
"""
from __future__ import annotations

import asyncio
import time

import aiohttp

REST = "https://restapi.amap.com/v3"
# ★ 2026-09-25：**路径规划走 v5**（`/v5/direction/driving`），POI 搜索仍然走 v3。
#   为什么非换不可（实测，见下面的 `_drive`）：v3 的驾车规划**永远只回 1 个方案**
#   —— 显式要 `number=3` 也只回 1 条，换 `strategy` 回的还是同一条（996160 米，
#   一分不差）。而用户要的是**像高德那样把几种情况摆出来、由他自己挑**，
#   那正是 v5 的默认行为（裸调就回 3 个方案）。
REST5 = "https://restapi.amap.com/v5"

# ---------------------------------------------------------------------------
# 高德的 `infocode` → **屏幕上说的人话**。
#
# 🔴 为什么要这张表（2026-09-25 实测逼出来的）：`_rest` 原来是直接把高德返回的
#    `info` 原文当 `why` 用的，于是屏幕上出现的是这么一句 ——
#        「高德没算出驾车路线（INSUFFICIENT_ABROAD_PRIVILEGES（20011））」
#    这话**是真的**，但它会原样出现在答辩的屏幕上：观众看到的是两个大写的英文词，
#    既不知道发生了什么，也不知道该去修哪儿。**照实说 ≠ 把原文甩给人**。
#
# ★ 分层，两边都不丢：
#     · **屏幕上** = 这张表里的人话 + 括号里的码（码留着，方便按码去查控制台）；
#     · **日志里**   = `_fail()` 记的那一行仍是高德原文（`status=/infocode=/info=`）
#                     —— 出问题时能查到真话的仍然是日志。
#
# ⚠️ 表里没有的码**不回原文**（原文是 `ROUTE_FAIL` 这种大写英文，摆到屏幕上
#    对观众等于没说），而是回一句中文的笼统话 + 码 —— 不编一个**具体**的解释，
#    因为我不知道它具体是什么意思（编 = 就是这一整件事的起因）。
# 🔴 表里**只许放实测过的码**。v3 换 v5 那次就吃过亏：同一个海上的点，v3 报
#    `INSUFFICIENT_ABROAD_PRIVILEGES（20011）`，v5 报 `ROUTE_FAIL（20802）` ——
#    两个体系各有各的码，没量过的先别往里写。
#
# 🔴 **2026-09-26 因为没守这条规矩，真出过一次错**：`10021` 那行原来写的是
#    「数字签名没通过（安全密钥对不上）」—— 那是照记忆写的，而它**实际是限流**。
#    后果不是"少说一句"，是**把人指到完全相反的方向**：页面上明明只是问得太快
#    （等几秒就好），屏幕上却让人去高德控制台翻安全密钥。`20000` 那行同样写错了
#    （写成"没有这条数据"，实际是"参数不对"）。
#    现在这一张表的每一行都是**在这台机器上撞出来**的，见
#    `_scratch/_t_amap_codes.py`（假 key / 缺参数 / 空参数 / 连着快打 / 拿 JS key
#    打 REST，四种错一个个撞，把 `infocode`+`info` 原样抄下来）。
#    2026-09-26 撞到的：
#      10000 OK · 10001 INVALID_USER_KEY · 10009 USERKEY_PLAT_NOMATCH
#      10021 CUQPS_HAS_EXCEEDED_THE_LIMIT · 20000 INVALID_PARAMS
#      20001 MISSING_REQUIRED_PARAMS
#    另有 20011 / 20802 两行是更早实测留下的（见下面各自的注释）。
#
# ⚠️ 表里现在**没有**这几行（10002 没开通 / 10003 日配额 / 10004 太频繁 /
#    10012 / 10013 / 10019 / 20003）—— 不是漏了，是**还没撞到过**。撞到的时候
#    屏幕上是「高德那边没算成（码 10003）」：**码照样给出来**，日志里那一行
#    （`_fail`）还是高德原文 `info=…`，什么都没藏，只是不敢替它编解释。
#    要补就把那一发也加进 `_t_amap_codes.py`，撞出来再照抄。
#    ⚠️ 出事的那行**不是照文档抄错的，是照记忆写的** —— 官方表上 10021 明明白白
#      写着 QPS 超限（`ui/web/nav.html` 的 `SLOW_CODE` 那段 2026-09-25 拉过原文，
#      抄的是对的）。所以核对的顺序是：**先在这台机器上撞**，撞不到再去看官方表，
#      并且把"这是文档上的、没实测"写进注释 —— 记忆不能当来源。
CODE_CN = {
    "10001": "这把 key 高德不认（去控制台核对一下 Web 服务那把）",
    "10009": "key 的平台类型不对 —— 拿 JS 那把来查数据了，要的是 Web 服务那把",
    # ★ 实测（2026-09-26）：连着快打 15 发，第 2 发起就是这个。
    #   ⚠️ 这一行原来错成了"数字签名没通过"，见上面那段。
    "10021": "问得太快了，高德限流了（隔一下再试）",
    # ★ 实测（2026-09-26）：空 `keywords` 回的就是它（INVALID_PARAMS）。
    "20000": "这次请求的参数不对",
    # ★ 实测（2026-09-26）：`place/around` 不给 `location` 回的就是它。
    "20001": "这次请求少带了必填参数",
    "20011": "起点或终点不在高德算得动的路网里（境外/海上都算）",
    # ★ 实测（2026-09-25）：静海 → 太平洋上一个点，v5 回的就是它。
    "20802": "高德说这条路规划不出来（没有路网，或者两点的距离太近）",
}


def _f(v, default=0.0) -> float:
    """高德把数字全写成**字符串**（`"distance": "2620"`），而且拿不到时给空串。"""
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _i(v, default=0) -> int:
    return int(_f(v, default))


# 「能停车休息的地方」在 POI 名字/分类里的字样。**这两种写法都算**：高速上叫
# 「服务区」的居多，也有叫「停车区」的（实测：京沪高速静海段的「王口停车区」）。
REST_WORDS = ("服务区", "停车区")


def _is_rest(poi: dict, by_name: bool) -> bool:
    """这条 POI 是不是真的"能停车休息的地方"。

    ⚠️ **为什么必须有这一层**（不是防御性编程，是有实测证据的）：高德的 `keywords`
      是**模糊/语义**匹配。实测拿「服务区」在**天安门**搜，返回的**第一条**是
      「北京顺丰速运有限公司安华里业务部职工暖心驿站」（`type=生活服务;生活服务场所`，
      6169 m）—— 真服务区排在它后面，长这样：
      `type=道路附属设施;服务区;高速加油站服务区`。
      照单全收的话，屏上会出现「最近的服务区：顺丰速运暖心驿站」，
      那是**答非所问**，和"编一个数"是同一类错（这一整件事的起因）。
    `by_name=True` 只认名字里的字样（最硬），`False` 再看 `type`（退一步）。
    """
    if by_name:
        return any(w in (poi.get("name") or "") for w in REST_WORDS)
    return any(w in (poi.get("type") or "") for w in REST_WORDS)


class AMap:
    """一把 Web 服务 key + 一层缓存。**不 import 任何 UI 侧的东西**，方便单测。"""

    CACHE_TTL = 60.0        # 秒。页面报一次定位就能覆盖一次语音问询
    CACHE_GRID = 3          # 坐标取整到几位小数（3 位 ≈ 111 m）

    def __init__(self, cfg: dict | None = None):
        c = cfg or {}
        self.cfg = c
        self.enabled = bool(c.get("enabled", False))
        self.js_key = str(c.get("js_key") or "").strip()
        self.security = str(c.get("security_js_code") or "").strip()
        self.web_key = str(c.get("web_key") or "").strip()
        self.timeout_s = float(c.get("timeout_s") or 5)
        kws = c.get("keywords")
        self.keywords = [str(k) for k in kws] if isinstance(kws, list) else ["服务区"]
        self.radius_m = _i(c.get("radius_m") or 50000, 50000)

        # ---- 运行态 ----
        self.calls = 0          # 真正打出去的 REST 请求数
        self.hits = 0           # 缓存命中
        self.failed = 0
        self.last_error = ""
        self.last_ok_wall = ""
        self.last_name = ""
        self._cache: dict = {}          # (lat, lng) -> (monotonic, dict)

    # ---------------------------------------------------------------- 状态
    def configured(self) -> bool:
        """配了 Web 服务 key 且开关开着。"""
        return bool(self.enabled and self.web_key)

    def ok(self) -> bool:
        """现在这一秒能不能真的查。和 `wechat.py` / `asr.ok()` 同一个口径：
        **配置开着 ≠ 能干活**；上一次真失败了就不再声称 ok。"""
        return bool(self.configured() and not self.last_error)

    def note(self) -> str:
        if not self.enabled:
            return "关掉了（配置 amap.enabled = false）"
        if not self.web_key:
            return "没配 Web 服务 key（config.json 的 amap.web_key 是空的）"
        if self.last_error:
            return "已接入，但上次查询失败：" + self.last_error
        if not self.calls:
            return "已接入，还没查过"
        return "已接入 · 查了 %d 次（缓存命中 %d），最后一次：%s %s" % (
            self.calls, self.hits, self.last_ok_wall, self.last_name)

    def status(self) -> dict:
        """进 `hello.amap`。**每个键都要在**（缺键前端显示"—"，和"没做"长得一样）。

        ⚠️ 这里**没有 `web_key`**，连尾巴都没有。`js` 那一条是**故意**的：
        JS API 的 key + 安全密钥本来就要出现在页面源码里（见文件头），
        页面拿它建图，所以只能下发。
        """
        return {
            "enabled": self.enabled,
            "configured": self.configured(),
            "ok": self.ok(),
            "js": {"key": self.js_key, "security": self.security},
            "js_ready": bool(self.js_key and self.security),
            "keywords": list(self.keywords),
            "radius_m": self.radius_m,
            "timeout_s": self.timeout_s,
            "calls": self.calls,
            "hits": self.hits,
            "failed": self.failed,
            "cached": len(self._cache),
            "last_ok": self.last_ok_wall,
            "last_name": self.last_name,
            "last_error": self.last_error,
            "note": self.note(),
        }

    # ---------------------------------------------------------------- 请求
    async def _rest(self, path: str, params: dict, base: str = REST) -> dict:
        """打一次 REST。**成功 = `status=="1"` 且 `infocode=="10000"`**，见文件头第 1 条。

        返回 `{"ok": bool, "why": str, "data": dict}`：失败时 `data` 是原始的 body，
        方便日志里看真话（但**调用方不许拿它当数据用**）。

        ⚠️ `base` 只用来选 **v3 还是 v5**：两边的信封（`status`/`infocode`/`info`）
           是同一套，所以判据一个字都不用改 —— 变的是**路径和字段名**（见 `_drive`）。
        """
        q = dict(params)
        q["key"] = self.web_key
        self.calls += 1
        try:
            to = aiohttp.ClientTimeout(total=self.timeout_s)
            async with aiohttp.ClientSession(timeout=to) as s:
                async with s.get("%s/%s" % (base, path), params=q) as r:
                    body = await r.text()
                    try:
                        d = await r.json(content_type=None)
                    except Exception:                     # noqa: BLE001
                        d = {}
                    if r.status != 200 or not isinstance(d, dict):
                        self._fail("HTTP %s %s" % (r.status, body[:120]))
                        return {"ok": False, "why": "接口没通（HTTP %s）" % r.status,
                                "data": d if isinstance(d, dict) else {}}
        except asyncio.TimeoutError:
            self._fail("超时 %.1fs" % self.timeout_s)
            return {"ok": False, "why": "查高德超时了", "data": {}}
        except Exception as e:                            # noqa: BLE001
            self._fail("%s: %s" % (type(e).__name__, e))
            return {"ok": False, "why": "连不上高德（%s）" % type(e).__name__,
                    "data": {}}
        st, code = str(d.get("status")), str(d.get("infocode"))
        if st != "1" or code != "10000":
            # ⚠️ 这里**必须**两个字段都对（HTTP 200 也可能是失败）。具体哪几个码
            #    是实测撞过的，看下面 `CODE_CN` 上头那段 —— **别在这儿又凭记忆列
            #    一串**（10021 就那样被写成"数字签名没通过"，实际是限流）。
            # ★ 日志里记的是**高德原文**；返回给人的是 `CODE_CN` 里的人话。
            self._fail("status=%s infocode=%s info=%s"
                       % (st, code, d.get("info")))
            return {"ok": False,
                    "why": "%s（码 %s）" % (CODE_CN.get(code)
                                          or "高德那边没算成", code),
                    "data": d}
        return {"ok": True, "why": "", "data": d}

    def _fail(self, msg: str):
        self.failed += 1
        self.last_error = msg

    # ---------------------------------------------------------------- 业务
    async def _drive(self, o_lat, o_lng, d_lat, d_lng) -> dict:
        """起点 → 终点，按驾车方式，**回高德给的每一个方案**（通常 1~3 个）。

        ★ 为什么必须抽出来（不是"顺手去重"）：这一页现在有两个问法 ——
          「最近的**服务区**在哪」（`nearby`）和「到**我指定**的这个地方怎么走」
          （`to`）。两边的公里数/分钟数/折线**必须是同一份算法算出来的**，
          各写一份的话迟早差 1 公里，而答辩时正好被指着问"这两个数怎么不一样"。

        ★★ **为什么回一个表而不是只回一条**（2026-09-25 用户拍板）：
           "在高德地图里输入起点终点，它会给很多种情况，我自己选" —— 对。走高德
           推荐的哪一条**是用户的事**，不是我们的。v3 只给 1 条（实测：显式
           `number=3` 也只回 1 条），所以这里换了 v5。**方案一 = 高德推荐的那条**，
           顺序原样保留、不自作主张重排。

        🔴 **不许传 `strategy`**（实测踩过）：v5 里一旦显式给了 `strategy=0`，
           返回的**方案就只剩 1 个** —— "给几种情况"恰恰是**不传 strategy** 时的
           默认行为。谁"顺手补一个 strategy"，三种情况当场就没了，而且不报错。

        🔴 **`show_fields=cost,polyline` 不能省**：v5 不写这一项时，方案里**既没有
           `cost`（时长/过路费/红绿灯）也没有每段折线**，只剩一个里程数 ——
           页面上会变成"有方案但没有路可画"。

        ⚠️ v5 的字段名和 v3 **不一样**，照抄 v3 会全是 `None`：
             每段里程 = `step_distance`（v3 是 `distance`）
             每段时长 = `cost.duration`（v3 是平铺的 `duration`）
             整条时长 = `cost.duration`、过路费 = `cost.tolls`、
             红绿灯 = `cost.traffic_lights`
        """
        r = await self._rest("direction/driving", {
            "origin": "%.6f,%.6f" % (o_lng, o_lat),
            "destination": "%.6f,%.6f" % (d_lng, d_lat),
            "show_fields": "cost,polyline",
        }, base=REST5)
        if not r["ok"]:
            return {"ok": False, "why": r["why"], "has_route": False,
                    "routes": [], "km": 0, "min": 0}
        paths = ((r["data"].get("route") or {}).get("paths") or [])
        routes = []
        for p in paths:
            poly, step_list, run = [], [], 0
            for s in (p.get("steps") or []):
                seg = [pt for pt in (s.get("polyline") or "").split(";") if pt]
                poly.extend(seg)
                sc = s.get("cost") or {}
                run += _i(s.get("step_distance"))
                step_list.append({
                    "tx": (s.get("instruction") or "").strip(),
                    "m": _i(s.get("step_distance")),
                    "s": _i(sc.get("duration")),
                    # ★★ 导航态（逐段引导）要的三个数，**全是高德原样给的**：
                    #   `lights` = 这一段自己的红绿灯个数（`cost.traffic_lights`，
                    #             在 v5 里是**逐段**都有的，实测每段都在）；
                    #   `at_m`   = 走到这一段**末尾**时，全程已走了多少米
                    #             （由各段 `step_distance` 依次累加，**不重算几何**、
                    #              也不去和高德那个总里程相减 —— 累加出来的数最坏
                    #              会差几米，但它是"高德给的各段之和"，不是我自己
                    #              量的距离。页面把它写成"全程 X 公里处"）。
                    "lights": _i(sc.get("traffic_lights")),
                    "at_m": run,
                    # ⚠️ **每段自己那份折线也带上**：导航态里"点一段、图上只亮这段"
                    #    靠它。仍然全是高德给的原样的点 —— 页面只切片，不重算。
                    "poly": seg,
                })
            if not poly:
                # 没有折线的方案点了也画不出来 —— 不摆出去让人选一个空的。
                continue
            dm, ds = _i(p.get("distance")), _i((p.get("cost") or {}).get("duration"))
            routes.append({
                "i": len(routes),
                "drive_m": dm, "drive_s": ds,
                "km": int(round(dm / 1000.0)), "min": int(round(ds / 60.0)),
                "tolls": _i((p.get("cost") or {}).get("tolls")),
                "lights": _i((p.get("cost") or {}).get("traffic_lights")),
                "toll_m": _i((p.get("cost") or {}).get("toll_distance")),
                "polyline": poly, "steps": len(step_list), "step_list": step_list,
            })
        if not routes:
            return {"ok": False, "why": "高德没给出路线折线", "has_route": False,
                    "routes": [], "km": 0, "min": 0}
        return {"ok": True, "why": "", "has_route": True, "routes": routes,
                "km": routes[0]["km"], "min": routes[0]["min"]}

    async def to(self, o_lat, o_lng, d_lat, d_lng, name="", address="") -> dict:
        """从起点到**人指定的**那个地方怎么走（搜出来的那条候选）。

        返回的形状和 `nearby()` **一模一样**，页面那一套渲染两处共用 ——
        少一套"目的地版的渲染"，就少一处迟早会不一致的地方。

        🔴 **这一条没有"直线距离"这一档，而且这是有意为之**：`nearby()` 里那个
           `distance_m` 是高的 `place/around` **返回**的一个字段；搜目的地走的
           `assistant/inputtips`（打字）/ `place/text`（上屏，见 `search()`），
           这两支**都不返回距离**。我不能自己用两点坐标算一个直线距离顶上
           —— 那就变成了"我算的数冒充高德给的数"，正是这一整件事的起因。
           所以：算不出驾车路线 → **一个数字都不给**，如实说算不出来。
        """
        dr = await self._drive(o_lat, o_lng, d_lat, d_lng)
        out = {
            "ok": dr["ok"], "why": "" if dr["ok"] else ("算不出驾车路线 —— %s"
                                                        % dr["why"]),
            "name": (name or "").strip() or "目的地",
            "address": (address or "").strip(),
            "keyword": "目的地",
            "poi_lat": float(d_lat), "poi_lng": float(d_lng),
            "has_route": dr["has_route"], "routes": dr["routes"],
            "cached": False,
            "route_why": ("" if dr["ok"] else dr["why"]),
            # ⚠️ 见上面那段：这里**不退回直线距离**，两个数字格留空由页面写「—」
            "km": dr["km"] if dr["ok"] else 0,
            "min": dr["min"] if dr["ok"] else 0,
        }
        out["by"] = "drive"
        if out["ok"]:
            self.last_error = ""
            self.last_ok_wall = time.strftime("%H:%M:%S")
            self.last_name = "%s · %d 公里（drive）" % (out["name"], out["km"])
        else:
            self._fail(out["why"])
        return out

    async def search(self, kw: str, limit: int = 8, full: bool = False,
                     lat=None, lng=None) -> dict:
        """把用户敲的一串字变成**几个候选地点**。

        ★ 走 **`v3/assistant/inputtips`**（高德专为"输入提示"开的那一支），
          **不是** `v3/place/text`。理由是当场量出来的
          （`_scratch/_t_amap_tips.py`、`_scratch/_t_nav_type.py`，2026-09-26）：

            keywords     place/text        inputtips
            「无」        count=0           tips=10（9 条带坐标）
            「站」        count=0           tips=10（10 条）
            「服」        count=0           tips=10（9 条）
            「静」        （没试）           tips=10（10 条）
            「无锡」      8 条               tips=10
            「无锡站」    8 条               tips=10

          三个**单字**在 `place/text` 上全是 `status=1 infocode=10000 count=0`
          —— 不是坏了、不是限流，是**它不认一个字**。而用户要的正是"每输入一个
          字都要有相关地点推荐"（2026-09-26：「我在起点终点每输入一个字 都要有
          相关的地点推荐啊 不要我点enter才推荐以及去除字才推荐」）。
          inputtips 连一个字都给十条，而且**不给 `city` 也按出口 IP 就近排**
          （实测：不给 city 打「无」，头三条是无锡站 / 无锡东站 / 无锡硕放机场）。

        `full=True` = **上屏那一下**（按回车、按「搜索路线」）**再并上**
          `place/text` 的结果，按名字去重、**`place/text` 在前**。两条理由：
            · **整地名**只有 `place/text` 给得准：打「无锡」按回车，tips 的头几条
              是无锡站 / 无锡东站 / 硕放机场，**没有「无锡市」**；
            · `type` 那一列（「火车站」这种看得懂的分类）也只有 `place/text` 有。
              inputtips 给的是 `typecode`（`150200` 这种**码**）——
              把一个码印到屏幕上的分类位，比不印还糟。
          🔴 **顺序是第二次才对的**：原先写的是"tips 在前"，实测等于**没合并** ——
             inputtips 一次就回 8~10 条，把 `lim`（默认 8）填满，末尾那句
             `out[:lim]` 一刀下去，后面并进来的 `place/text` 一条都剩不下。
             （`_scratch/_t_amap_full.py` 量到：上屏比打字「多出来的：（没有）」、
             「带上分类的：（一条都没有）」。）反过来之后还有第二个好处：
             上屏这一下用户敲的是**一个完整的词**，而 `place/text` 才是"整词"的
             那一支，把它排前面，头几行就都带着看得懂的分类。
          ⚠️ **打字那条路只打一次接口**：一个字两次调用 = QPS 直接翻倍，而这个 key
             已经在单字上撞过墙（`CUQPS_HAS_EXCEEDED_THE_LIMIT`）。合并只发生在
             "上屏"那一下 —— 次数少，也正是最需要准的时候。

        ★★ **给了 `lat/lng` 就把候选拉到身边**（`location` 参数）。实测
          （同一个 `_t_amap_tips.py`，不给 city / 不给 citylimit）：

            不给 location： 「站」→ 合肥站 / 北京站 / 大连站（**天南海北**）
            给了 location（无锡）：「站」→ 站前商贸城1912 / 站头新村二期 / 无锡站(北进站口)
            给了 location（无锡）：「服」→ 梅村服务区(京沪高速上海方向) / …
                                    / 堰桥服务区(京沪高速上海方向)

          「服」那一行最说明问题：**最近的真服务区**上来了。开车的人敲「服」想要的
          就是它，而不是淄博的服装城。所以页面把**起点的坐标**传进来（起点不知道
          就不传，退回高德按出口 IP 就近排 —— 那也是真数据，只是粗一档）。

        ★ **为什么不直接取第一条**：高德的关键词是**模糊/语义**匹配。实测拿
          「服务区」在**天安门**搜，第一条返回的是「北京顺丰速运…暖心驿站」
          （`_is_rest` 那段注释里记的就是它）。"猜哪个是他想要的那个"这件事
          **交给知道自己在哪的人**去点，比代码猜一个"大概吧"诚实得多 ——
          所以这一条**只回候选表，不回一个"就是它"**。

        返回 `{"ok", "why", "keyword", "list": [{name,address,lat,lng,type}]}`。
        失败时 `list` 是**空表**，一个坐标都不编。
        """
        kw = (kw or "").strip()
        if not kw:
            return {"ok": False, "why": "没给关键词", "keyword": "", "list": []}
        if not self.configured():
            return {"ok": False, "why": "高德没配（%s）" % self.note(),
                    "keyword": kw, "list": []}
        lim = max(1, min(_i(limit, 8), 20))
        q = {"keywords": kw, "datatype": "all"}
        # ⚠️ `location` 是**"把候选往这儿拉"**，不是限制：给了它，「站」就不再是
        #    合肥站那种天南海北的结果。没给（起点还没定）就退回高德按出口 IP 排。
        #    坐标越界/NaN 一律**当没给**：那是"偏置"不是"条件"，为一个坏参数把
        #    整次搜索打回失败，比少一个偏置糟得多。
        if lat is not None and lng is not None and \
                (-90.0 <= _f(lat, 999) <= 90.0) and (-180.0 <= _f(lng, 999) <= 180.0):
            q["location"] = "%.6f,%.6f" % (_f(lng), _f(lat))
        tip = await self._rest("assistant/inputtips", q)
        txt = None
        if full:
            txt = await self._rest("place/text", {
                "keywords": kw, "offset": lim, "page": 1,
                "extensions": "base", "citylimit": "false"})

        out, seen = [], set()

        def _add(name, addr, lat, lng, typ):
            """同名只要一条（**先来的那条赢**，见下面的摆放顺序）。"""
            name = (name or "").strip()
            if not name or name in seen:
                return
            seen.add(name)
            out.append({"name": name, "address": (addr or "").strip(),
                        "lat": lat, "lng": lng, "type": (typ or "").strip()})

        def _tips():
            """打字这一支。每一条**都有坐标**才留 —— 没坐标的点了也画不出来。"""
            if not tip["ok"]:
                return
            for t in (tip["data"].get("tips") or []):
                loc = (t.get("location") or "").strip()
                if "," not in loc:
                    continue
                lng, lat = loc.split(",")[:2]
                # ⚠️ tips 的 `address` 常常只有一条街名（「车站路1号」），把
                #    `district`（「江苏省无锡市梁溪区」）摆在前面才看出是哪儿 ——
                #    拼出来的每一个字都是高德给的，不是我们编的地名。
                _add(t.get("name"),
                     " ".join(x for x in [(t.get("district") or "").strip(),
                                          (t.get("address") or "").strip()] if x),
                     _f(lat), _f(lng), "")

        def _pois():
            """上屏这一支。只有这里有 `type`（看得懂的分类）。"""
            if txt is None or not txt["ok"]:
                return
            for p in (txt["data"].get("pois") or []):
                loc = (p.get("location") or "").strip()
                if "," not in loc:
                    continue
                lng, lat = loc.split(",")[:2]
                # ⚠️ `place/text` 的 `address` 也常常只有街名，但它的"在哪儿"
                #    不在 `district`（那是 inputtips 的字段），而是拆在
                #    `pname`/`cityname`/`adname` 三个里（「江苏省」「无锡市」
                #    「梁溪区」）。按同一套拼起来，去重是防「无锡市 无锡市」
                #    这种 —— 每一个字仍然是高德给的。
                parts = []
                for k in ("pname", "cityname", "adname", "address"):
                    v = (p.get(k) or "").strip()
                    if v and v not in parts:
                        parts.append(v)
                _add(p.get("name"), " ".join(parts),
                     _f(lat), _f(lng), p.get("type"))

        # ★★ `full` 时 place/text 在前 —— 顺序就是"谁能活过下面那把剪刀"。
        #    反过来的话（tips 先）8~10 条 tips 直接把 lim 填满，合并等于没做。
        if full:
            _pois()
        _tips()
        _pois()      # full=False 时 `txt` 是 None，这一句自己就返回了
        out = out[:lim]
        if not out:
            # 两边都空。`why` 优先用**打字这条路**（inputtips）那句：它带高德原码
            # （「…（码 10021）」）时比"没搜到"有用得多 —— 那是"等一会儿"和
            # "换个词"两种完全不同的处置。两边都没话说才退回"没搜到"。
            w = (tip["why"] or ((txt or {}).get("why") or "")).strip()
            self._fail("搜「%s」一条都没搜到" % kw)
            return {"ok": False, "why": w or ("高德没搜到「%s」" % kw),
                    "keyword": kw, "list": []}
        self.last_error = ""
        return {"ok": True, "why": "", "keyword": kw, "list": out}

    async def ip_locate(self) -> dict:
        """「这台电脑大概在哪个城市」—— 高德 `v3/ip`，**服务端出口 IP 的定位**。

        ★ 为什么要有它：用户拍板「起点默认就是我的电脑位置」。**浏览器定位**在
          这台机器上拿不到坐标（实测：权限给了、`getCurrentPosition` 仍然
          code 3 超时，机器上挂着 SSL VPN 和两张虚拟网卡），于是"默认"就落空了。
          IP 定位是**另一条真数据**：走服务端出网那条路问高德，回的是
          **城市级**的位置（省 · 市 · 一个覆盖全市的矩形）。

        🔴 **口径必须写清楚是"IP 定位 · 某市"，不许说成"你的位置"**：
          IP 定位的粒度是城市（有时还会落在 VPN 的出口城市上）——把它当成
          精确定位摆出去，就是拿一个真的数去下一个它撑不住的结论。所以
          返回值里带 `city`，页面把它**写在标签上**给人看：城市对不上，
          用户一眼就知道该自己改起点。

        ⚠️ 返回的坐标是**高德那个矩形（`rectangle`）的中心**，不是任何一栋楼
          ——中心是算出来的（`(min+max)/2`），不是编的。矩形都没给就**不给坐标**
          （`ok=False`），绝不退回一个"大概就是市中心吧"。

        返回 `{"ok", "why", "province", "city", "lat", "lng"}`。
        """
        if not self.configured():
            return {"ok": False, "why": "高德没配（%s）" % self.note(),
                    "province": "", "city": "", "lat": 0.0, "lng": 0.0}
        # ⚠️ **不带 `ip` 参数** = 问高德"我（服务端出口）在哪" —— 正是我们要的。
        #    传 `ip=` 会变成查某个人的地址，那是另一件事。
        r = await self._rest("ip", {})
        if not r["ok"]:
            return {"ok": False, "why": r["why"], "province": "", "city": "",
                    "lat": 0.0, "lng": 0.0}
        d = r["data"]
        prov = (d.get("province") or "").strip()
        city = (d.get("city") or "").strip()
        rect = (d.get("rectangle") or "").strip()
        # `v3/ip` 在国内查不到时会回一个**空 province/city 但是 infocode=10000**
        # 的"成功"（比如出口 IP 在国外）—— 这种"成功"里没有任何位置，别当成定位。
        if not (prov or city):
            self._fail("v3/ip 没说这是哪儿（province/city 都是空的）")
            return {"ok": False, "why": "高德没给出这台电脑在哪个城市",
                    "province": "", "city": "", "lat": 0.0, "lng": 0.0}
        if ";" not in rect:
            self._fail("v3/ip 给了地名但没给范围（rectangle=%r）" % rect[:40])
            return {"ok": False, "why": "高德只说了城市，没给这一带的范围",
                    "province": prov, "city": city, "lat": 0.0, "lng": 0.0}
        a, b = rect.split(";")[:2]
        try:
            lng1, lat1 = [float(v) for v in a.split(",")[:2]]
            lng2, lat2 = [float(v) for v in b.split(",")[:2]]
        except ValueError:
            self._fail("v3/ip 的范围解析不了（rectangle=%r）" % rect[:40])
            return {"ok": False, "why": "高德给的范围读不出来",
                    "province": prov, "city": city, "lat": 0.0, "lng": 0.0}
        self.last_error = ""
        return {"ok": True, "why": "", "province": prov, "city": city,
                "lat": _f((lat1 + lat2) / 2.0), "lng": _f((lng1 + lng2) / 2.0)}

    async def nearby(self, lat: float, lng: float) -> dict:
        """「最近能停车休息的地方」+ 到那儿怎么走。

        返回的**每个数字都是高德给的**（见文件头第 1 条），一个都不许编。失败时
        `ok=False` 且 `why` 是人话 —— 调用方拿它去说「照实说查不到」那一版话术。

        ⚠️ `km`/`min` 是**服务端算好的**，页面直接显示、话也是它 ——
           同一句话和同一屏必须是**同一个来源**，不许页面自己再算一遍
           （两份算法迟早会差 1 公里，答辩时正好被指着问）。
        """
        if not self.configured():
            return {"ok": False, "why": "高德没配（%s）" % self.note()}
        key = (round(lat, self.CACHE_GRID), round(lng, self.CACHE_GRID))
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < self.CACHE_TTL:
            self.hits += 1
            return dict(hit[1], cached=True)

        loc = "%.6f,%.6f" % (lng, lat)          # ⚠️ 高德是**经度在前**
        cand = []
        kw_used = ""
        why_last = ""
        for kw in self.keywords:
            r = await self._rest("place/around", {
                "location": loc, "keywords": kw, "radius": self.radius_m,
                "offset": 25, "page": 1, "extensions": "all",
                "sortrule": "distance"})
            if not r["ok"]:
                why_last = r["why"]
                continue
            pois = [p for p in (r["data"].get("pois") or []) if p.get("location")]
            if not pois:
                why_last = "附近没搜到「%s」" % kw
                continue
            # ⚠️ 两级筛（见 `_is_rest`）：名字里写着「服务区/停车区」的**最硬**，
            #    有就不再试下一个关键词；没有才退一步用 `type` 认。
            # ⚠️ `sortrule=distance` 下第一条通常就是最近的，但**不靠它取第一条**
            #    —— 就是这一条让「顺丰速运暖心驿站」排在了真服务区前面。
            named = [p for p in pois if _is_rest(p, True)]
            cand = named or [p for p in pois if _is_rest(p, False)]
            kw_used = kw
            if named:
                break
        poi = min(cand, key=lambda p: _f(p.get("distance"), 1e12)) if cand else None
        if poi is None:
            # ⚠️ 这里**不许退回"随便给一条最近的路边 POI"**：那正是上面那个
            #    顺丰驿站的来路。搜不到就搜不到，调用方有实话可说。
            why_last = why_last or "附近没搜到服务区"
            self._fail(why_last)
            return {"ok": False, "why": why_last}

        plng, plat = (poi.get("location") or ",").split(",")[:2]
        out = {
            "ok": True, "why": "",
            "name": (poi.get("name") or "").strip() or kw_used,
            "keyword": kw_used,
            "address": (poi.get("address") or "").strip(),
            "distance_m": _i(poi.get("distance")),          # 直线，高德给的
            "poi_lat": _f(plat), "poi_lng": _f(plng),
            "cached": False,
        }
        # ---- 路线。拿不到**不算整条失败**：服务区是真的，路线是另一件事 ----
        # ⚠️ 这一段现在和"到指定目的地"共用 `_drive`（见那儿文首"两个入口必须
        #    同一份算法"）。它回的是**方案表**，原样带给页面由人选；
        #    顶层那两个数取 `routes[0]` = **高德推荐的那一条** —— 小瑞嘴上念的
        #    就是这一条（见文件头"话和屏上的数字必须是同一个来源"）。
        dr = await self._drive(lat, lng, _f(plat), _f(plng))
        out["has_route"] = dr["has_route"]
        out["routes"] = dr["routes"]
        if dr["ok"]:
            out["km"], out["min"] = dr["km"], dr["min"]
            out["by"] = "drive"
        else:
            out["route_why"] = dr["why"]
        # ★ 报给人和念出来的那两个数（**只在这里算一次**）
        if not out.get("has_route"):
            out["km"] = int(round(out["distance_m"] / 1000.0))
            out["min"] = 0
            out["by"] = "direct"          # 只有直线距离 → 不许说"路线准备好了"
        self.last_error = ""
        self.last_ok_wall = time.strftime("%H:%M:%S")
        self.last_name = "%s · %d 公里（%s）" % (out["name"], out["km"], out["by"])
        self._cache[key] = (time.monotonic(), dict(out))
        return out

    # ---------------------------------------------------------------- 墓碑
    # ❌ **`prewarm(lat, lng)` 删了**（2026-09-25）。
    #
    #    它是照 `wechat.py` 的 `_spawn()`（起个协程、不阻塞主循环）写的，
    #    目的写在原来的文件头里：「页面一报上定位就后台查一次，语音问的时候
    #    立刻答」。写完之后**一个调用方都没有** —— 而查下来它不是"忘了接"，
    #    是**这件事已经有人做了**：
    #
    #      · `nav.html` 的 `tryGeo()` 拿到定位 → `useOrigin()` → `query()` →
    #        `GET /amap/nearby`，这一次请求本身就把 `_cache` 填上了（TTL 60 s）；
    #      · 语音那条路（`wake.js` 的 `ev:"do" id:"nearby"` → `XQ.nav.doNearby`）
    #        走的是**同一个** `query()`，所以 `voice_answer` 里那次
    #        `hub.amap.nearby()` 是**同一次缓存命中** —— 而且几乎同一时刻，
    #        不存在"查的时候还没热"。
    #
    #    也就是说：**页面自己那一问就是预热**。留着它只会多一个永远不跑的
    #    后台任务入口，并且让"语音问的时候缓存是热的"这句注释看起来像是它干的
    #    —— 那种注释比没有注释更坏（这个项目的注释就是文档）。
    #    ⚠️ 别再把 `self._tasks`（保住 task 引用、免得被 GC）一起加回来：
    #       它只服务于这个函数。
