# -*- coding: utf-8 -*-
"""把疲劳告警推到微信 —— 走**企业微信群机器人**的 webhook。

 ── 为什么是这条路，不是"接微信" ────────────────────────────────────
   · **个人微信没有官方发消息接口。** 网上那些 itchat / wechaty 走的是网页版
     协议，微信早把网页版大面积封了，能登上去的号也有封号风险 —— 答辩现场
     挂掉的代价远大于"能在自己微信里看到"。这条路不碰。
   · **企业微信群机器人** = 一条 URL + 一个 POST。不要认证、不要公网 IP、
     不要审核，本机跑着就能发。这是**当天就能通**的唯一一条。
   · 代价是**单向**：只能往外推，收不回来。所以"在微信里回一句让小瑞做事"
     这一版做不了（那要企业微信自建应用：企业认证 + 一个公网能回调的地址）。
     界面和文档都别写成能做。

 ── 改这个文件之前先读这三条（都是会静默出错的那种）────────────────
  1. **边沿触发，不是电平触发。** `state.alarms` 是一条**判据**：持续闭眼的那几秒里
     它每一帧都在（8 Hz）。按电平推 = 一秒几十条，群机器人的限流立刻把这一路打死
     （而且限流之后是**整批**发不出去，连真告警一起丢）。所以这里只认
     "上一帧不在、这一帧在"那个上升沿；档位同理，只认 `severity` 的**变化**。
  2. **推送绝不阻塞 `tick()`。** 那是 8 Hz 的主循环，一次网络超时（默认 6 s）
     就是 48 帧状态推送被吞掉 —— 界面直接卡住。所以发送一律 `create_task` 另开
     一个协程，`maybe_push()` 本身是**同步、立刻返回**的。
  3. **HTTP 200 不等于发成功。** 群机器人失败时照样回 200，失败写在 body 的
     `errcode` 里（93000 = webhook 无效、45009 = 触发限流、45047 之类）。只看
     状态码 = **静默失败**：界面说"已接入"，手机一条都没响。所以这里必须解析
     body，并且**要求 `errcode == 0`** 才算成功。

 ── 不做什么（都是刻意的）────────────────────────────────────────
   · **不把 webhook 发给前端**，连打码的尾巴都不发（`status()` 里没有它）。
     它等同密码，没有"只露一点点"的必要。要看配没配，看 `configured` 就够。
   · **不带小瑞那句建议。** 消息是一条告警**记录**，不是聊天。硬加那句话就得让
     这个模块认识 `Agent`，而它现在只认识一个 state 对象 —— 为了好看去换一个
     会漂的耦合不划算。建议在座舱界面上，那儿本来就是它的位置。
"""
from __future__ import annotations

import asyncio
import json
import time

import aiohttp

from state import SEVERITY_NAMES

# 数据源标签。★ 必须**说实话**：演示脚本推出去的告警和摄像头实拍的告警，
# 在手机上看长得一样，不标出来就等于把"演的"当成"测的"存档。
# 这几条和界面上 `hello.source` 那行是两码事（那边只有 demo/replay/live/cam 四个词）。
SOURCE_LABEL = {
    "demo": "演示脚本（按预设演，不是实测）",
    "replay": "回放录像（真人会话 CSV）",
    "live": "实时管线（fuse.py 正在写的数据）",
    "cam": "摄像头实拍",
}

# 支路二告警 kind → 人在微信里看得懂的名字。`state.py` 的 `NOTE_FACE` /
# `NOTE_YAWN` 是告警**本身**的文案，优先用它（逐字和 src/fuse.py 一致）；
# 这张表只在拿不到文案时兜底。
KIND_LABEL = {"eyes": "持续闭眼", "yawn": "打哈欠"}


def build_text(st, trigger: str) -> str:
    """把一帧状态写成一条企业微信 markdown 消息。

    ⚠️ 只用企业微信 markdown **确定支持**的那几个记号：`##` 标题、`**粗体**`、
    `>` 引用。表格、嵌套列表、行内 HTML 都不在里面 —— 写了会原样显示成一堆星号。
    """
    sev = SEVERITY_NAMES.get(st.severity, str(st.severity))
    lines = [
        "## 疲劳预警 · %s" % sev,
        "> **来源**：%s" % SOURCE_LABEL.get(st.source, str(st.source)),
        "> **时间**：%s" % time.strftime("%Y-%m-%d %H:%M:%S"),
        "> **触发**：%s" % trigger,
    ]
    if getattr(st, "attention", ""):
        lines.append("> **行为**：%s" % st.attention)
    texts = [a.get("text") for a in (st.alarms or []) if a.get("text")]
    if texts:
        lines.append("> **支路二**：%s" % "、".join(texts))
    return "\n".join(lines)


class WeChatPusher:
    """一条 webhook + 一套去重。**不 import 任何 UI 侧的东西**，方便单测。"""

    def __init__(self, cfg: dict | None = None):
        c = cfg or {}
        self.webhook = str(c.get("webhook") or "").strip()
        self.enabled = bool(c.get("enabled", True))
        # 空字符串 = 不按档位推（只推支路二那两条）。
        self.on_severity = str(c.get("on_severity") or "").strip()
        kinds = c.get("kinds")
        self.kinds = {str(k) for k in kinds} if isinstance(kinds, list) else {"eyes"}
        self.cooldown_s = float(c.get("cooldown_s") or 0)
        self.min_gap_s = float(c.get("min_gap_s") or 0)
        self.timeout_s = float(c.get("timeout_s") or 6)

        # ---- 运行态 ----
        self.sent = 0
        self.failed = 0
        self.skipped = 0            # 被冷却/最小间隔压掉的条数
        self.last_error = ""
        self.last_sent_wall = ""    # 给人看的"最后一条是什么时候发的"
        self._active: dict[str, bool] = {}   # kind -> 上一帧在不在（用来找上升沿）
        self._prev_sev = ""
        self._last: dict[str, float] = {}    # 冷却计时，按 key 各算各的
        self._last_any = float("-inf")
        self._tasks: set = set()             # 保住 task 引用，不然会被 GC 掉

    # ---------------------------------------------------------------- 状态
    def configured(self) -> bool:
        """配了 webhook 且开关开着。**和 enabled 不是一回事** —— 界面上
        「没配」和「已关」要说成两句不同的话，别都写成一个"未启用"。"""
        return bool(self.enabled and self.webhook)

    def ok(self) -> bool:
        """现在这一秒能不能真的发出去。和 `asr.ok()` 同一个口径：
        配置开着 ≠ 能干活；上一次真失败了就不再声称 ok。"""
        return bool(self.configured() and not self.last_error)

    def note(self) -> str:
        if not self.enabled:
            return "关掉了（配置 wechat.enabled = false）"
        if not self.webhook:
            return "没配 webhook（config.json 的 wechat.webhook 是空的）"
        if self.last_error:
            return "已接入，但上次发送失败：" + self.last_error
        if not self.sent:
            return "已接入，还没发过"
        return "已接入 · 已发 %d 条，最后一条 %s" % (self.sent, self.last_sent_wall)

    def status(self) -> dict:
        """进 `hello.wechat`。**每个键都要在**（缺键前端显示"—"，和"没做"长得一样）。
        ⚠️ 这里**不含 webhook 本身**，连尾巴都不含。"""
        return {
            "enabled": self.enabled,
            "configured": bool(self.webhook),
            "ok": self.ok(),
            "on_severity": self.on_severity,
            "kinds": sorted(self.kinds),
            "cooldown_s": self.cooldown_s,
            "min_gap_s": self.min_gap_s,
            "sent": self.sent,
            "failed": self.failed,
            "skipped": self.skipped,
            "last_sent": self.last_sent_wall,
            "last_error": self.last_error,
            "note": self.note(),
        }

    # ---------------------------------------------------------------- 判据
    def maybe_push(self, st, now: float) -> list:
        """看一眼这一帧该不该推。**同步、立刻返回**，真正的网络请求在别的协程里。

        返回这一帧要推的 key 列表（给测试用，正常调用不用管）。
        """
        fires = []          # [(key, trigger_text), ...]
        # ★ `_prev_sev` / `_active` 必须**每帧都更新**，不能只在命中时更新 ——
        #   否则"重度 → 清醒 → 重度"里的第二次永远不触发（档位没被记下来过）。
        prev_sev, self._prev_sev = self._prev_sev, st.severity
        if self.on_severity and st.severity == self.on_severity \
                and prev_sev != st.severity:
            fires.append(("sev:" + st.severity,
                          "疲劳程度跨到「%s」" % SEVERITY_NAMES.get(st.severity, st.severity)))
        now_on = {a.get("kind") for a in (st.alarms or [])}
        for k in sorted(self.kinds):
            on = k in now_on
            if on and not self._active.get(k):
                text = ""
                for a in (st.alarms or []):
                    if a.get("kind") == k and a.get("text"):
                        text = a["text"]
                        break
                fires.append(("kind:" + k, text or KIND_LABEL.get(k, k)))
            self._active[k] = on

        if not self.configured():
            return []
        out = []
        for key, trigger in fires:
            # 冷却两道：**同一类**自己的冷却 + 全局最小间隔（兜底 20 条/分钟）。
            if now - self._last.get(key, float("-inf")) < self.cooldown_s:
                self.skipped += 1
                continue
            if now - self._last_any < self.min_gap_s:
                self.skipped += 1
                continue
            self._last[key] = now
            self._last_any = now
            out.append(key)
            self._spawn(build_text(st, trigger))
        return out

    # ---------------------------------------------------------------- 发送
    def _spawn(self, text: str):
        """另开一个协程发。⚠️ 调用方必须是正在跑的 loop 里（`tick()` 是），
        否则 `get_running_loop()` 抛异常 —— 那就干脆不发，也不许把主循环带崩。"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        t = loop.create_task(self._post(text))
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    async def _post(self, text: str) -> bool:
        payload = {"msgtype": "markdown", "markdown": {"content": text}}
        try:
            timeout = aiohttp.ClientTimeout(total=self.timeout_s)
            async with aiohttp.ClientSession(timeout=timeout) as s:
                async with s.post(self.webhook, json=payload) as r:
                    raw = await r.text()
                    try:
                        d = json.loads(raw)
                    except Exception:                    # noqa: BLE001
                        d = {}
                    code = d.get("errcode")
                    # ★ 要求 `errcode == 0`，**不是**"状态码 200 就行"。
                    #   解析不出 body 也算失败 —— 宁可报错，也不许把没发出去
                    #   说成发出去了。
                    if r.status != 200 or code != 0:
                        self.failed += 1
                        self.last_error = "HTTP %s errcode=%s %s" % (
                            r.status, code, (d.get("errmsg") or raw[:120]))
                        return False
        except Exception as e:                            # noqa: BLE001
            self.failed += 1
            self.last_error = "%s: %s" % (type(e).__name__, e)
            return False
        self.sent += 1
        self.last_error = ""
        self.last_sent_wall = time.strftime("%H:%M:%S")
        return True

    # ---------------------------------------------------------------- 单测/自检用
    def send_now(self, text: str):
        """**绕过判据直接发一条**（自检脚本 / 以后界面上那颗"测试"按钮用）。
        ⚠️ 只允许在已经跑起来的 loop 里调用。"""
        self._spawn(text)
