"""三个数据源，产出的都是同一个 `State`。

    demo    按脚本演一遍分级预警的四档状态（答辩用，不会翻车）
    replay  回放真人会话 CSV（真实数据，但录的是刻意闭眼 protocol，
            所以重度占比高——想看得均衡就回放 session1）
    live    跟着 `src/fuse.py` 正在写的那个 CSV 跑

⚠️ **live 是"读文件"不是"插进推理进程"**，这是故意的：
`src/fuse.py` 现在是支路一的回归基线，之前已经验证过 121 段逐帧一致，
为了接界面去改它的主循环，等于把那个验证作废。CSV 是它本来就会写的产物，
读它就把两个东西完全解耦了——界面崩了不影响推理，推理重启界面也不会断。
"""

from __future__ import annotations

import csv
import math
import time
from pathlib import Path

from state import (CLASSES, ROLL_WIN, State, WARMUP_SEC, _f,
                   YAWN_MIN_DEFAULT)

# CSV 列 -> State 字段。列名就是 src/fuse.py 写出来的那套，别改。
_COLMAP = {
    "l1": "l1", "gate": "gate", "ema_normal": "ema_normal", "p_fat": "p_fat",
    "l2": "l2", "perclos": "perclos", "brate": "brate", "nod": "nod",
    "en_now": "en_now", "d_pitch": "d_pitch", "yawn_sec": "yawn_sec",
    "eye_sec": "eye_sec", "head_swing": "head_swing",
    "l_fused": "l_fused", "ear": "ear", "mar": "mar", "pitch": "pitch",
    # ⚠️ `src` **不在**这张表里 —— 它是字符串（pose/face/yawn/eye/head），
    #    而这张表的每个值都要过 `_f()` 转 float。见下面单独那一行。
}


def row_to_state(row: dict, source: str) -> State:
    """CSV 的一行 -> State。容忍缺列、空单元格和短行。"""
    st = State(t=_f(row.get("t")) or 0.0, source=source)
    st.probs = {c: (_f(row.get(c)) or 0.0) for c in CLASSES}
    for col, attr in _COLMAP.items():
        if col in row:
            setattr(st, attr, _f(row[col]))
    if st.gate is not None:
        st.gate = bool(int(st.gate or 0))
    for attr in ("l1", "l2", "l_fused"):
        v = getattr(st, attr)
        setattr(st, attr, int(v) if v is not None else 0)
    st.mark = bool(int(_f(row.get("mark")) or 0))
    # `src` = **是哪条来源把 l_fused 抬起来的**（`src/fuse.py` / `ui/cam.py` 写的那一列）。
    # `ui/state.py` 按它报「检测到持续闭眼 / 持续低头」—— 所以它必须原样搬运，
    # **不能**在这里重新按阈值推一遍（那就会多出第二份阈值）。
    st.src = str(row.get("src") or "").strip()
    # ⚠️ 这里**不再**设 `b2_ready` / `pc_ready`：它们由 `State.derive()` 从
    #    `p_fat` / `perclos` 有没有值推出来（2026-09-24 晚统一），数据源只管给数。
    #    原来的那行是 `st.b2_ready = st.p_fat is not None` —— 判据本身没错，错在
    #    它在这儿一套、demo 的 poll() 里又一套，两份就会漂。
    # 也不用时间戳去猜：闸门关过之后热身会重来，按时间猜必然错。
    return st


# ---------------------------------------------------------------- demo
def _blip(t: float, a: float, b: float) -> float:
    """`a..b` 之间从 0 涨到 1 再回落到 0，区间外是 0（三角波）。

    桥段用它做**包络**，不是拿它当判据 —— 真实的哈欠也不是"啪一下出现"，
    而是张嘴 → 保持 → 合上，`yawn_seconds()` 量出来的时长就是这么涨落的。
    """
    if t < a or t > b:
        return 0.0
    m = (a + b) / 2.0
    return (t - a) / (m - a) if t < m else (b - t) / (b - m)



# ★ 2026-09-24 晚重写（「只做疲劳」）：演出从"级别轴"改成**四档疲劳轴**。
#
# 为什么要动：旧的五段里，L1 演的是「分心」、L2 演的是「看手机」—— 那是**类别**，
# 而这一版把两者都删/并了（`glance` 删除、`phone` 归入重度疲劳）。四档疲劳才是
# 现在唯一的轴，所以演出就按四档排：**清醒 / 轻度 / 中度 / 重度·低头（看手机）/
# 重度·点头**。最后两段都落 L3，靠 `probs` 区分"是什么行为引起的"。
#
# 另一个变化：**两个桥段（打哈欠 / 长时间闭眼）从 normal 段挪进轻度段**。
# 用户原话「轻度疲劳就是打哈欠啊 闭眼时间稍长啊」—— 打哈欠在这个口径里**就是**
# 轻度疲劳，所以它在"清醒"段里出现才是自相矛盾的。挪过去之后：
#   打哈欠桥段 -> yawn_sec 过线 -> l_fused=1（黄）+ severity=轻度
#   长闭眼桥段 -> l2=1       -> l_fused=1（黄）+ severity=轻度
# 两个桥段仍然各报一条独立告警，只是换了一段演。
#
# 第三处：**`l_fused` 不再硬编码**，见下面 poll() 里那一段。
class DemoSource:
    """脚本演出：清醒 -> 轻度 -> 中度 -> 重度·低头（看手机）-> 重度·点头，循环。

    四档的来源按口径分工：轻/中度由支路二演（perclos / p_fat / 哈欠 / 长闭眼），
    重度由支路一演（`l1 = 3`，两类都落 L3）。

    桥段（打哈欠 + 长闭眼）落在**轻度段**里，且必须在支路二热身（27 s）之后 ——
    这就是清醒段比别的段长的原因（轻度段从 40 s 起，最早那个桥段 48 s 才到）。

    数字是照着实测数据编的（p_fat 睁眼 ≈0.19 / 闭眼 ≈0.57，rate 从 session1/2
    的分布里取；支路一那三个概率照 `tools/replay_clip.py` 实测的峰值 ≈0.70 编），
    不是随便写的——但**它终究是编的**，所以界面右上角会挂"演示"标，
    切换数据源时要让看的人知道现在看的不是真人。
    """

    # 两个桥段的时刻（秒，绝对时间轴）。放这儿是为了让 `?sev=` 的定位点
    # 和 `_scratch/_check_alarm.py` 有个共同出处 —— 桥段挪了那边要跟着挪。
    # ★ 2026-09-24 晚：跟着轻度段一起挪了（原来在 normal 段的 32~45 s）。
    YAWN_A, YAWN_B = 48.0, 55.0        # 打哈欠：yawn_sec 涨到 3.5 再落回 0
    EYES_A, EYES_B = 62.0, 68.0        # 长时间闭眼：en_now 掉到 0.15、l2 = 1

    def __init__(self, loop: bool = True):
        self.loop = loop
        self.t0 = time.monotonic()
        # (名字, 持续秒数)。名字就是 `?sev=` 能取的值 —— 最后两段（phone / fatigue）
        # **都是重度疲劳**，只是"由什么行为引起"不同，这是 demo 唯一要演的区别。
        self.arc = [
            ("normal",   40.0),    # 清醒
            ("mild",     40.0),    # 轻度疲劳：含哈欠 + 长闭眼两个桥段
            ("moderate", 30.0),    # 中度疲劳：更长的闭眼（L2）
            ("phone",    30.0),    # 重度疲劳 · 低头（看手机）
            ("fatigue",  30.0),    # 重度疲劳 · 点头
        ]
        self.total = sum(d for _, d in self.arc)

    def seek(self, t: float) -> None:
        """把演出时钟挪到第 t 秒（等价于"从 t 秒前就开始放了"）。

        **为什么需要它**：答辩时要能把各档的稿稳定地翻出来，而不是
        "等 38 秒大概就是轻度那档"。让演示数据**真的走到那一档**，比在外观上
        硬锁一档要诚实 —— 那样界面上的数字和标题才是同一件事。
        只有 demo 源有这个方法；真人 CSV / 摄像头没有"时间轴"可挪。
        """
        self.t0 = time.monotonic() - max(0.0, float(t))

    def _seg(self, t: float):
        acc = 0.0
        for name, dur in self.arc:
            if t < acc + dur:
                return name, (t - acc) / dur
            acc += dur
        return self.arc[-1][0], 1.0

    def poll(self, now: float) -> State:
        t = now - self.t0
        if self.loop:
            t = t % self.total
        name, k = self._seg(t)
        st = State(t=t, source="demo")

        # 每段的起点/终点：k 从 0 到 1 平滑过渡，免得数字跳变。
        # `l1` / `l2` 是这一段要演的**级别**（支路一 / 支路二各自的判决）。
        # ★ 2026-09-25 二类之后**没有 `share` 了**：`phone` 和 `fatigue` 并成一个类，
        #   模型的实际约束是 `p_normal + p_fatigue = 1`，所以非正常那一根条
        #   直接就是 `1 − ema_normal`，没有"在两个非正常类之间怎么分"这回事了。
        #   （原先 `share` 是"扣掉 ema_normal 之后剩给 (phone, fatigue) 的比例"。）
        ramp = {
            # 清醒：闸门开（ema_normal 高、支路一判正常），疲劳条压在 0.20 之下。
            "normal":   dict(pc=(0.05, 0.09), pf=(0.14, 0.22), br=(13.0, 15.0),
                             pitch=(-3.0, 1.0), nod=(1.0, 2.0), dp=(4.0, 6.0),
                             ema=(0.90, 0.80),
                             l1=0, l2=0),
            # 轻度疲劳：**级别在这一段是 L0，只有 severity 进 mild**（两档都过 mild
            # 线、都不过 moderate 线），黄灯和出声来自两个桥段 —— 见下面 poll() 里
            # 打哈欠/长闭眼那一段，以及 `l_fused` 那条式子。
            # ⚠️ p_fat 一直压在 B2_ENTER(0.60) 之下，所以桥段之外 l2 恒为 0
            #   —— 不会误报"持续闭眼"。
            "mild":     dict(pc=(0.20, 0.30), pf=(0.38, 0.46), br=(9.0, 12.0),
                             pitch=(-6.0, -8.0), nod=(3.0, 6.0), dp=(6.0, 9.0),
                             ema=(0.78, 0.72),
                             l1=0, l2=0),
            # 中度疲劳：p_fat 已过 B2_ENTER，所以 **l2=2 是真的**（不是硬凑），
            # 于是 l_fused = max(0, min(2,2)) = 2（橙黄）✓ 和 severity=中度 同一档。
            # 这一段闸门是开的（人还是正视前方，累的是眼睛）—— 所以支路二**能**投票。
            "moderate": dict(pc=(0.44, 0.54), pf=(0.62, 0.74), br=(7.0, 10.0),
                             pitch=(-8.0, -10.0), nod=(5.0, 8.0), dp=(8.0, 10.0),
                             ema=(0.74, 0.68),
                             l1=0, l2=2),
            # ---- 重度疲劳：两段都落 L3，区别只在"什么行为引起的" ----
            # ⚠️ 两段的 ema_normal 都**故意压在 0.60 之下**：驾驶员一低头，闸门本来
            #   就该关（这正是真实数据上的行为，`ui/state.py` 的 note 会说明）。
            #   而 `l1=3` 本身蕴含"非正常那个类的 EMA 过 ENTER_TH(0.60)"——
            #   二类下就是 `1 − ema_normal > 0.60`，即 `ema_normal < 0.40`：
            #   0.22 / 0.14 都满足 ✓（这是**同一个等式**，不是凑出来的）。
            # ★ 两段的概率条现在**是同一个数**（`1 − ema_normal`）—— 那正是合并的含义，
            #   不是偷懒：`phone` 和 `fatigue` 已经是同一个类了。两段的区别落在
            #   `pitch` / `nod`（→ `attention` 那行文字）和 `l2` 上：
            #     phone  段：低头 + 眼睛不累（pc/pf 留在正常档）→ l2=0，只看支路一
            #     fatigue 段：点头 + 眼睛也累（p_fat 过 B2_ENTER）→ l2=2 + 持续闭眼告警
            #   这两格正好把"融合"演示全：一个靠支路一、一个两支路一起。
            # ⚠️ 闸门关只挡支路二的**级别**投票（`min(l2,2) if gate else 0`），
            #   **不挡独立告警** —— 告警看的是 l2 的原始判决（`ui/state.py` 的
            #   alarms）。所以"闸门关 ＋ 持续闭眼告警"同时出现是设计如此。
            "phone":    dict(pc=(0.10, 0.14), pf=(0.20, 0.28), br=(12.0, 13.0),
                             pitch=(9.0, 15.0), nod=(2.0, 4.0), dp=(16.0, 21.0),
                             ema=(0.22, 0.14),
                             l1=3, l2=0),
            # ⚠️ 这一段 pitch 是**负**的，和 `tools/selftest.py` 的约定（正 = 低头）
            #   以及 `phone` 段（+9~+15）都相反。是历史遗留的演出数字，**不影响档位**
            #   —— `attention` 那行（2026-09-25 起）只看 `nod` 和 `d_pitch` 两个
            #   **免基线**的量，不看 pitch 的绝对值，所以这里没改。
            #   要动它就得连 `app.js` 的头像一起看，别单独改。
            "fatigue":  dict(pc=(0.44, 0.54), pf=(0.62, 0.74), br=(7.0, 10.0),
                             pitch=(-11.0, -14.0), nod=(7.0, 11.0), dp=(20.0, 26.0),
                             ema=(0.22, 0.14),
                             l1=3, l2=2),
        }[name]

        def lerp(a, b):
            return a + (b - a) * min(1.0, max(0.0, k))

        st.perclos = lerp(*ramp["pc"])
        st.p_fat = lerp(*ramp["pf"])
        st.brate = lerp(*ramp["br"])
        st.pitch = lerp(*ramp["pitch"])
        st.nod = lerp(*ramp["nod"])
        st.ema_normal = lerp(*ramp["ema"])
        st.l1 = ramp["l1"]
        st.l2 = ramp["l2"]

        # ---- 两个独立告警的桥段（演在**轻度**段里）----
        # ★ 2026-09-24 晚：从 normal 段挪过来。用户原话「轻度疲劳就是打哈欠啊
        #   闭眼时间稍长啊」—— 打哈欠在这个口径里**就是**轻度疲劳，让它出现在
        #   "清醒"段里才是自相矛盾。桥段期间 `l1` 仍然是 0（支路一确实判正常），
        #   把级别顶上去的是 `yawn_sec` / `l2`，与管线同一条式子（见下面 l_fused）。
        st.yawn_sec = 0.0
        closed = False
        if name == "mild":
            st.yawn_sec = 3.5 * _blip(t, self.YAWN_A, self.YAWN_B)
            closed = self.EYES_A <= t <= self.EYES_B
            if closed:
                st.l2 = 1                       # 支路二判出"持续闭眼"
        st.mar = 0.20 + st.yawn_sec * 0.06
        st.ear = 0.16 if (closed or name == "fatigue") else (
            0.28 if name == "moderate" else (0.33 if name == "mild" else 0.38))
        # en_now < 0.80（BLINK_THR）就是界面头像的"闭眼"。中度那一段用了 0.76，
        # 是故意压在 0.80 之下 —— "更长的闭眼"该看得出来。
        st.en_now = 0.15 if closed else {
            "normal": 0.97, "mild": 0.88, "moderate": 0.76,
            "phone": 0.93, "fatigue": 0.52,
        }[name]
        # 头部晃动 `d_pitch` = 窗内 pitch 的 p95−p5 极差（`src/face.py:323` 那个量）。
        # ★ 2026-09-24 深夜：**从"由 nod 算出来"改成每段一条自己的斜坡。**
        #   原来写的是 `4.0 + nod * 1.5`，而 `nod` 是"窗内点头次数"（轻度 3~6、
        #   中度 5~8）—— 那个系数让**轻度段后半段和中度段整段**的 d_pitch 超过
        #   12°，于是界面上「头部姿态」那行显示"头部晃动"，而这两段的立意恰恰是
        #   「人还正视前方，累的是眼睛」（见上面 mild/moderate 那两行注释）。
        #   `_check_grade.py` 的 A 段抓到的就是这个：档位/大标题都对，只有这一行
        #   在说另一件事。**别把 `nod` 和 `d_pitch` 再绑到一起** —— 一个是次数、
        #   一个是角度，真实管线里两者也没有换算关系。
        # ⚠️ 12° 是 `ui/web/app.js:366` 判"头部晃动"的那条线。清醒/轻度/中度都
        #    **明显压在它下面**（不是贴着它：贴着它就成了"阈值决定判决"）；
        #   低头/点头两段在它上面（那两段的姿态确实在动，虽然界面上被"低头/
        #   点头"那两行盖住，值本身也该是合理的）。
        st.d_pitch = lerp(*ramp["dp"])

        # 支路一**二类**概率：`p_normal + p_fatigue = 1`，和真实模型同一条约束
        # （softmax 只有两个输出）。所以非正常那一根条就是 `1 − ema_normal`。
        e = st.ema_normal
        st.probs = {"normal": e, "fatigue": max(0.0, 1.0 - e)}

        # 闸门：与 `src/live.py:71` 的 `GATE_MIN = 1 - EXIT_TH = 0.60` 同一条式子。
        # **不写死 True** —— 分心/看手机那两段的 ema_normal 就在 0.60 之下，闸门
        # 本来就是关的，界面上的「闸门」格子该照着显示。
        # （只判 ema_normal 就够：它 ≥0.60 时剩下三类各自 ≤0.40，normal 必然是
        #   argmax，所以和原式 `argmax==normal and ema[normal]>=GATE_MIN` 等价。）
        st.gate = st.ema_normal >= 0.60
        # 冷启动**照真实路径的两道门槛演**（`ui/cam.py:300-302` 判的也是这两级）：
        #   span < ROLL_WIN(10 s)  基线没攒够 → `fb.ready()` 假 → 统计量一个都没有
        #   span < WARMUP_SEC(27 s) 模型没得喂 → `fb.full()` 假 → p_fat 没有
        # ★ 2026-09-24 晚：原来 10~27 秒这一段也把 perclos 抹掉了，等于把"统计量"
        #   和"判决"压成一级，屏上 PERCLOS 白白多等 17 秒。cam 那边一直是分开的，
        #   demo 这边是漏的 —— 用户说的"不要 27 秒"就是这里。
        # ⚠️ 门槛不能再往前提：基线是"每个点往前 10 秒的 p75"，短于 10 秒时它会被
        #   闭眼自己拽塌，算出来的是恒偏低的假数（见 `state.ROLL_WIN` 那段）。
        if t < ROLL_WIN:
            st.perclos = st.brate = st.nod = st.en_now = st.d_pitch = None
        if t < WARMUP_SEC:
            st.p_fat = None
        # demo 的演出时钟就是基线年龄（这一段闸门是开的），直接报给界面当倒计时。
        # `b2_ready` / `pc_ready` 不在这儿设 —— `derive()` 从上面这两个 None 推。
        st.pc_span = t

        # ---- 融合：**照管线的式子算，不硬编码** ----
        # 与 `src/fuse.py:635-638` / `ui/cam.py:321-323` 是同一个式子。
        # 硬编码 l_fused 正是老 mild 段自相矛盾的根源（l1=1 却配着疲劳味的数）。
        # 写成计算式之后，demo 从结构上**不可能**再和管线漂移。
        # ★ 2026-09-26：多了两条规则（持续闭眼 → L2、低头/点头 → L3），式子的**形状
        #   没变**（还是"四条来源取最大"），只是来源从两条变成四条 —— 与
        #   `src/fuse.py` / `ui/cam.py` 里那个 `max(...)` 逐位同构。
        # ⚠️ 这里**不判阈值**：演出是脚本，它自己知道这一段在演什么，所以
        #   `closed`（闭眼桥段）和 `phone`/`fatigue`（低头/点头两段）直接**声明**
        #   级别和 `src`。这不是偷懒 —— 在 `ui/` 里再写一份 `CLOSE_EYE_SEC` /
        #   `HEAD_DEG` 就是第七、第八个抄本，而这一版就是为了消灭抄本才把
        #   `src` 做成日志列的。
        st.eye_sec = 1.4 if closed else 0.0        # 只给界面看，判级别用的是 closed 本身
        st.head_swing = st.d_pitch                 # demo 里两者同源（同一个姿态斜坡）
        l_yawn = 1 if st.yawn_sec >= YAWN_MIN_DEFAULT else 0
        l_eye = 2 if closed else 0
        l_head = 3 if name in ("phone", "fatigue") else 0
        # ⚠️ `l_face` 必须**先过闸门**再判来源 —— 用原始 `l2` 会在闸门关着时判出
        #   `src="face"` 而级别是 0（"说是它抬的，可它这一票作废了"）。
        #   管线的判据是 `l_face > l1`（见 `src/fuse.py` 那个 max），这里必须同款。
        l_face = min(st.l2, 2) if st.gate else 0
        # 平局顺序与 `src/fuse.py` / `ui/cam.py` 一致：**规则赢基线**（低头 > 闭眼 >
        # 哈欠 > 基线票）。平局只决定"念哪一句原因"，级别不变。
        l_base = max(st.l1, l_face)
        st.l_fused = max(l_base, l_yawn, l_eye, l_head)
        # ⚠️ 全零那一拍 `src` 必须是 "pose"（不能写成 max()，那会取列表第一个
        #   → 级别 0 却报低头；这个错在演示 t=0 就复现过）。
        if st.l_fused <= 0:
            st.src = "pose"
        elif l_head == st.l_fused:
            st.src = "head"
        elif l_eye == st.l_fused:
            st.src = "eye"
        elif l_yawn == st.l_fused:
            st.src = "yawn"
        else:
            st.src = "face" if l_face > st.l1 else "pose"
        return st


# ---------------------------------------------------------------- CSV
class CsvSource:
    """回放 / 跟随。`live=False` 是回放，`live=True` 是跟着正在写的文件跑。"""

    def __init__(self, path: str | Path, live: bool = False,
                 speed: float = 1.0, loop: bool = True):
        self.path = Path(path)
        self.live = live
        self.speed = speed
        self.loop = loop
        self.rows: list[dict] = []
        self._size = 0
        self._fp = None
        self._t0 = None       # 回放用的起始墙上时刻
        self._file_t0 = None  # CSV 里第一行的 t

    # ---- 读 ----
    def _read_all(self):
        self.rows = []
        with self.path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            for row in csv.DictReader(f):
                self.rows.append(row)
        self._size = self.path.stat().st_size

    def _tail(self):
        """只读新增的部分。live 模式下 CSV 在长，不能每次整读。"""
        if not self.path.exists():
            return
        size = self.path.stat().st_size
        if size < self._size:          # 换文件了（新的一局），从头来
            self._size = 0
            self.rows = []
        if size == self._size:
            return
        if self._fp is None:
            self._read_all()
            self._fp = self.path.open("r", encoding="utf-8", errors="replace", newline="")
            self._fp.seek(self._size)   # 表头已经在 _read_all 里吃掉了
        else:
            self._fp.seek(self._size)
            for row in csv.DictReader(self._fp, fieldnames=self._cols()):
                self.rows.append(row)
            self._size = size

    def _cols(self):
        with self.path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            return next(csv.reader(f))

    def poll(self, now: float) -> State | None:
        if self.live:
            self._tail()
            if not self.rows:
                return None
            return row_to_state(self.rows[-1], "live")

        if not self.rows:
            if not self.path.exists():
                return None
            self._read_all()
            if not self.rows:
                return None
        if self._t0 is None:
            self._t0 = now
            self._file_t0 = _f(self.rows[0].get("t")) or 0.0

        want = self._file_t0 + (now - self._t0) * self.speed
        # 文件的时间列是递增的，二分找最后一个 <= want 的行
        lo, hi = 0, len(self.rows) - 1
        best = 0
        while lo <= hi:
            mid = (lo + hi) // 2
            tv = _f(self.rows[mid].get("t"))
            if tv is None or tv > want:
                hi = mid - 1
            else:
                best, lo = mid, mid + 1
        if best >= len(self.rows) - 1 and self.loop:
            span = (_f(self.rows[-1].get("t")) or 0.0) - self._file_t0
            self._t0 = now - (span / max(self.speed, 1e-6))   # 从头再来
            best = 0
        return row_to_state(self.rows[best], "replay")
