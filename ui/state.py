"""界面要的「一帧状态」——把 CSV 里那些列翻译成人看得懂的东西。

设计上和推理侧严格分开：**这里不做任何判断，只做翻译和映射**。
所有阈值都是从实测数据里量出来的（见 config.example.json 的 severity 段），
不在这里现拍——否则界面会自成一个体系，和 `src/fuse.py` 的真实行为对不上。

三条通道，别混（这是整个 UI 的设计原则）：

- **安全通道**：`level`（0~3，来自 `l_fused`）。**整页配色、大标题、警示条用它。**
  该报警就报警，不能因为"情感化"把红线让掉。
- **疲劳程度**：`severity`（normal / mild / moderate / severe）。「疲劳程度」那一行
  和小瑞的建议用它。
- **独立告警**：`alarms`，`kind` = `eyes` / `yawn` / `head`。**它绕开级别单独报一次**，
  见 `derive()` 里那一段的注释。⚠️ 闭眼那一条的**文案按来源分两句**
  （`NOTE_FACE` / `NOTE_FACE_MODEL`）—— 「持续闭眼」这话只有真数过时长的
  **闭眼规则**配说，模型那一路说的是它真量到的「闭眼时间变长」。

★ **2026-09-24 改：只做疲劳。** 用户原话「后端改一下 我们只做疲劳」「phone 直接归为
重度疲劳 fatigue依旧是疲劳 glance删掉」「轻度疲劳就是支路2的闭眼时间变成 打哈欠那些」
「重度疲劳就是点头 低头 头部倾倒这些」。于是：

  · `glance`（短暂扭头=分心）**整类删掉** —— 官方口径里没有分心，只有四个疲劳档。
    这也是上一版遗留问题的根：那时 `level` 的 L1 是"分心"、L2 是"看手机"，
    它是**类别**不是**程度**，和"轻度/中度/重度疲劳"那条程度轴对不上。
  · `phone`（持续低头看手机）**归入重度疲劳** —— 点头和低头是同一件事的两种姿态。
  · 因此**支路一只可能给 L0 / L3**（它的非正常类落 L3），
    L1 / L2 只可能来自支路二（闭眼变长 / 持续闭眼，`B2_*` 门槛、封顶 2）。
  · 四档的来源是**两支路分工**：**轻 / 中 ← 支路二**（perclos、p_fat、哈欠），
    **重 ← 支路一**（`l1 == 3`）。这是用户原话直接定的，不是我们拍的。

★ **2026-09-25 再改：三类并二类。** 用户原话「点头这个 直接 疲劳瞌睡点头和头部持续
低头变成一路吧」。于是 `CLASSES = ("normal", "fatigue")`，`phone` 目录的样本在
`tools/build_dataset.py` 的 `DIR_CLASS` 里打上 `fatigue` 标签（目录不删不搬）。

  · 合并的**理由**正是下面这条警告说的事：那两类模型本来就分不开，而分不开**对产品
    没有后果**（都落 L3）。既然如此，让界面并排显示两根分不开的条只是徒增一处误报。
  · 合并后 `p_normal + p_fatigue = 1`，于是 `ema[fatigue] > ENTER_TH(0.60)`
    **等价于**闸门关闭。合并**收紧**了重度触发（三类下是 `max(两类) > 0.60`，
    而 max ≤ 两者之和），实测 `glance` 的误报从 20/27 降到 14/27
    —— 见 `runs/_probe_l3_summary.md`。
  · 重训后"清醒 / 疲劳"两侧仍是 **79 段全对**：误报 0/27、漏报 0/52，
    val/test 成员与三类那一轮**逐段相同**（受控对拍）。

⚠️ **支路一的类别再也不能区分"低头"和"点头"了** —— 那正是合并的目的。
所以下面 `attention` 那一行"原因"文字**改由支路二的 `nod` / `d_pitch` 驱动**，
不再读类别概率。这两个量都是**免基线**的（相对本窗、相对本人），
不能用绝对 pitch 设阈值：那个坑记在 `ui/web/app.js` 的注释里（每人头部基线不同）。

★ **2026-09-26 加两条规则，上面 09-24 那两句"谁给哪一档"要打个补丁。** 用户拍板加了
「持续闭眼 → L2」（`src/fuse.py` 的 `EYE_LEVEL`）和「低头/点头 → L3」（`HEAD_LEVEL`），
两条都是**规则**、都不进逻辑回归、也都不看闸门（理由见 `src/fuse.py:134-157`）。

  · 09-24 那句「L1 / L2 只可能来自支路二」**不再成立**：L2 也可能是**闭眼规则**给的
    （那一刻 `l2` 常常只有 1）。这正是 `NOTE_FACE` / `NOTE_FACE_MODEL` 必须分家的原因
    —— 级别取两者**较高**的那个，而文案必须跟着**真正抬级的那个来源**（`src`）走。
  · "重 ← 支路一"也不完整了：低头规则直接给 L3，而那一刻 `l1` 往往还是 0
    （见 `derive()` 里 `l_fused >= 3` 那一段的注释）。
  · 支路一自己的取值范围没变，仍然只有 **L0 / L3**。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict

# ★ 2026-09-25 二类：`phone` 并进 `fatigue`（`config.py` 的 CLASSES 同款）。
# ⚠️ 这是**独立的一份**（`ui/` 不 import `src/` 也不 import `config`，见下面的
#   常量注释），改类别时**两处都要改**，漏一处不会报错、只会让 `probs` 少一个键
#   而概率条少一根。顺序即标签 id，名字不许改。
CLASSES = ("normal", "fatigue")

# 级别名字：安全通道。**四档疲劳，逐字就是官方口径那张表** ——
# `src/live.py` 的 `LEVEL_CN` 是同一份（src/ 那边给控制台和 `src/fuse.py` 的 TTS 用）。
LEVEL_NAMES = {0: "清醒", 1: "轻度疲劳", 2: "中度疲劳", 3: "重度疲劳"}

# 疲劳程度：情感通道。键是四个，名字和上面同源 —— 但**来源不同**
# （见模块 docstring 末段）：轻/中来自支路二的统计量 + 哈欠/闭眼规则，
# 重来自支路一的类别 **或低头规则**（2026-09-26 起，见 docstring 最后那个 ★）。
# ★ 2026-09-24：`moderate`（中度）是新加的一档，旧的是 normal/mild/severe 三值、
#   比官方口径少一档。config.json 里那两个阈值键也从 `severe_*` 改名成
#   `moderate_*` —— 因为**重度没有数值阈值**，它是一个类别，不是"更高的那个数"。
SEVERITY_NAMES = {"normal": "清醒", "mild": "轻度疲劳",
                  "moderate": "中度疲劳", "severe": "重度疲劳"}

# 支路二那两条独立告警的文案。**逐字抄 `src/fuse.py:161-162`**，别自己措辞 ——
# 这两句话在 live 模式下由 `src/fuse.py` 的 TTS 念、在 cam 模式下由界面显示，
# 同一次闭眼不该出现两种说法。那边是按级别取键（1 / 2）。
NOTE_FACE = {1: "检测到持续闭眼", 2: "检测到持续闭眼，疲劳征兆"}
# ★ 2026-09-26：**模型那条路另外给一句**。用户报的是「我只是眨眼，它凭什么说
#   "检测到持续闭眼"」—— 而 `l2` 是支路二的逻辑回归，它量的是**闭眼占了多少时间**
#   （`src/live.py:63-64`：L1 = perclos 过 18.7%，L2 = perclos 过 42.6% 或 p_fat 过
#   0.55），**它没有量"连续闭了多久"** —— 那句话只有**闭眼规则**有资格说：那条规则
#   真的在归一化 EAR 上数了「连续 ≥ `src/face.py` 的 CLOSE_EYE_SEC(1.0 s) 低于 0.80」。
#   所以文案按**谁发现的**分开：`src == "eye"` 走上面那张（真的数过时长），
#   只有模型那一路走下面这张（说的是它真量到的那个量）。
#   ⚠️ 措辞取自 `src/live.py` 的 `LEVEL_NOTE`（`["", "检测到打哈欠/闭眼变长",
#      "检测到持续闭眼", "检测到低头/点头"]`）—— 但那张表是**按级别**写的，
#     它**分不出来源**（L2 既可能是模型判的、也可能是闭眼规则顶的），所以这里
#      只是**用词跟它同族**，不是逐字抄：同一件事在控制台和界面上不该换一套说法。
#   ⚠️ 这条**不是**「模型说话不客气」的措辞问题，是**判据和文案要配对**：说"持续闭眼"
#      就等于宣称量过时长，而模型没有。少报一个词比多报一个词严重得多。
NOTE_FACE_MODEL = {1: "闭眼时间变长", 2: "闭眼时间明显变长"}
NOTE_YAWN = "检测到打哈欠"
# 低头/点头规则（2026-09-26）。逐字抄 `src/fuse.py:164` 的 `NOTE_HEAD` —— 同一次低头
# 不该因为"是控制台念还是界面显示"就换一种说法。
NOTE_HEAD = "检测到持续低头，请注意"

# 哈欠判据的兜底默认值。**它就是 `src/face.py` 的 `YAWN_MIN`**（2026-09-26 第二次改小 = 1.0），
# 运行时以 `ui/config.json` 的 `alarm.yawn_min` 为准，这里只是 config 缺键时
# 不至于判不出来。`ui/sources.py` 的 demo 也 import 它（demo 要按管线的同一条
# 式子算 l_fused，不能自己另拍一个数）。
# ⚠️ 1.0 这个数**只能配 `src/face.py` 的滚动均值判据用**（1.5 s 窗 + YAWN_THR 0.55）：
#    单帧那版判据下说话侧最长就有 0.87 s，1.0 是贴地的。别把这个数单独搬回去。
YAWN_MIN_DEFAULT = 1.0

# 支路二的**两道**门槛。它们是两件事，不是一个：
#   ROLL_WIN = 10 s   PERCLOS 自己的分母（p75 基线窗）攒够 —— 到这儿统计量就有
#                     真值，屏上就该出数
#   WARMUP_SEC = 27 s 模型判决 —— HIST_SEC = WIN_SEC(17) + ROLL_WIN(10)，窗口整个
#                     落在缓冲内才敢喂逻辑回归（`src/face.py:295-312` 的 docstring）
# ★ 2026-09-24 晚拆开：原来界面把这两级压成一个 `b2_ready`（27 s），于是 PERCLOS
#   明明第 10 秒就有真值，屏上却一直写「—」。用户的原话是「PERCLOS 的开启不要
#   27 秒」。**但 10 秒这一级不能再往前挪**：基线是"每个点往前 10 秒的 p75"，
#   短于 10 秒时分位数会被闭眼自己拽塌（`src/face.py:145-160`：p50 只撑到 50%
#   闭眼，p75 撑到 75%）—— 窗越短，PERCLOS 越对"持续闭眼"视而不见，早开出来
#   的是个**恒偏低的假数**，比「—」更糟。所以是 10 秒→27 秒两级，不是 0 秒。
ROLL_WIN = 10.0            # = src/face.py:64
WARMUP_SEC = 27.0          # = src/face.py:91 的 HIST_SEC

# `attention` 那一行（"专注 / 略有低头 / 头部持续低垂 / 疲劳点头"）的两条线。
# ★ 2026-09-25 起的依据是**支路二的实测行为量**，不是类别概率（类别只剩两个了）。
# 两条线都锚在 `src/face.py` 已经定义好的量上，不是现拍的：
#   HEAD_RANGE = `NOD_DROP`（face.py:80）—— 那边用它判"这一帧偏出本段中位姿态了"。
#                这里用它作"窗内 pitch 极差够大 = 头确实偏出过中性姿态"的线。
#   NOD_BUSY   = "窗内点头次数算频繁"的线。17 s 的窗里点头周期约 2.5 s
#                （`tools/selftest.py` 的合成疲劳信号就是这个周期），
#                所以≥5 次 ≈ 每 3.4 s 至少点一次头。
# ⚠️ 两条线只用在**显示**那一行文字上，**不参与任何判决** —— 档位来自 l1/l2，
#   这里判错最多是那句话说得糙。显示阈值与判决阈值分开，是这个项目一贯的做法。
HEAD_RANGE = 12.0          # = src/face.py:80 的 NOD_DROP
NOD_BUSY = 5.0


def _f(v) -> float | None:
    """CSV 里的空单元格是 `-` 或空串，统一变成 None。

    用 None 而不是 0 或 NaN：界面上"没有这个数"和"这个数是 0"完全是两回事，
    比如支路二没热身完时 perclos 应该是「—」而不是「0%」。
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return None if (isinstance(v, float) and math.isnan(v)) else float(v)
    s = str(v).strip()
    if s in ("", "-", "nan", "None"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


@dataclass
class State:
    """一帧。字段名和 CSV 列名对齐，方便回放源直接喂。"""

    t: float = 0.0

    # ---- 支路一（骨骼路）----
    probs: dict = field(default_factory=lambda: {c: 0.0 for c in CLASSES})
    ema_normal: float | None = None
    l1: int = 0

    # ---- 闸门 ----
    gate: bool = True

    # ---- 支路二（面部路）----
    p_fat: float | None = None
    perclos: float | None = None
    brate: float | None = None
    nod: float | None = None
    yawn_sec: float | None = None
    l2: int = 0

    # ---- 面部原始量 ----
    ear: float | None = None
    mar: float | None = None
    pitch: float | None = None
    d_pitch: float | None = None
    en_now: float | None = None

    # ---- 融合输出 ----
    l_fused: int = 0
    mark: bool = False
    # ---- 两条规则（2026-09-26）的量 + "是谁把级别抬起来的" ----
    # `src` 逐字来自融合器那一列（pose/face/yawn/eye/head），`derive()` 按它报
    # 「检测到持续闭眼 / 持续低头」。**这里不存任何阈值** —— 判决已经做完了，
    # 界面只负责把原因念出来（省掉一份会漂的抄本，见 state.py 里 YAWN_MIN 那段）。
    eye_sec: float | None = None      # 最长的一次"持续闭眼"（秒）
    head_swing: float | None = None   # 最近 2 秒头摆了多少度（免基线）
    src: str = ""

    # ---- 派生（下面 derive() 填）----
    severity: str = "normal"
    attention: str = "专注"
    level: int = 0
    level_name: str = "正常"
    severity_name: str = "正常"
    eyes: str = "open"        # open / closed / unknown
    # 支路二那两条独立告警：[{"kind": "eyes"|"yawn", "text": "检测到…"}]。
    # 空列表 = 没有告警。**前端不要自己按 level 推** —— 这一条就是为了让
    # "L1 是因为瞟了一眼后视镜"和"L1 是因为在打哈欠"能分开。
    alarms: list = field(default_factory=list)
    b2_ready: bool = False
    b2_warmup_left: float = WARMUP_SEC
    # 支路二的**另一半**：`1 - p_fat`。⚠️ 它**不是模型的第二个输出** ——
    # 支路二是个二分类，模型只有 `p_fat` 这一个数（外加按 0.60/0.85 定的档 `l2`）。
    # 首页 `#p5` 那块是**两根条**，另一根就是它。用户原话要的是"三类概率"，
    # 把"模型里没有第三个类"说明白之后，**他自己选的是"只上两个真数"**。
    # ★ 在这儿算、不在 app.js 里现减：两处各算一次迟早不一致，而那种错的形态是
    #   "同一块屏幕上两根条加起来不等于 100%"。`p_fat` 是 None 时它也是 None
    #   （界面写「—」，**不是 0%** —— "0% 疲劳"是一个判决，没数是另一件事）。
    b2_alert: float | None = None
    # 支路二的**统计量**（PERCLOS / 眨眼频率 / 点头次数 / EAR_norm）有没有数。
    # 比 `b2_ready` 早整整 WIN_SEC = 17 秒 —— 见上面 ROLL_WIN / WARMUP_SEC 那段。
    # 由 `derive()` 填（判据就是 perclos 非 None），数据源不用管它。
    pc_ready: bool = False
    pc_warm_left: float = ROLL_WIN
    # 基线已经攒了多少秒。**只有数据源知道**（cam 问 `FaceBranch.span`，demo 用
    # 演出时钟），所以它是 `None` 就退回用 `t` 估 —— 见 derive() 的倒计时那段。
    pc_span: float | None = None
    hr: float | None = None   # 心率（bpm）。★ 2026-09-26 起**是真的了**：
    #                            HPM5300EVK + MAX30102 走 I2C0 采原始 PPG，
    #                            从板载 FT2232 的 console 串口出板，PC 侧
    #                            `ui/serial_hr.py` 算成 BPM，由 `server.py` 的
    #                            `Hub.tick()` 在 derive 之前贴到这一帧上。
    #                            ⚠️ **只有那一处会写它**，`derive()` 不碰 ——
    #                            所以数据源（cam/live/demo）都不用管这一路。
    #                            量不出来时是 None（手指没按 / 串口没数据 /
    #                            心跳没攒够），界面显示「未接入」。**绝不填上一次
    #                            的数**：一个错的数字比「未接入」坏得多。
    # ★ 2026-09-26 加：心率这一路的另外几个量。**和 `hr` 同一个来源、同一个写法**
    #    （`serial_hr.apply_to_state` 一处写，`derive()` 不碰）。
    #   `hr_ac` 是**带通后的交流 RMS**（`_HrTracker.ac_rms()`）—— 单位是 ADC 计数，
    #     **没有标定**，所以界面上不给单位、只给数。★ 深夜新增，替掉界面上原来
    #     那一格 RMSSD：后者要 NN 连续跨度 ≥ 30 秒才有值，实测一场真实会话里
    #     **0.0% 的帧有数**，屏幕上永远是一根横杠（用户原话「换个一直有的」）。
    #   `hr_rmssd` 是 HRV-RMSSD（**毫秒**）—— 只从**连续**的 NN 间隔上算，
    #     跨度不到 30 秒给 None。⚠️ **界面上已经没有这一格了**（见上面那条），
    #     字段留着是因为 `snapshot()` 还给实时窗口的日志产它。别照它写界面。
    #   `hr_pi` 是 PI 灌注指数（**百分数**，0.16 就是 0.16%），看传感器信号质量。
    #   `hr_pi_hint` 是 PI 偏低时那句小字的**文案本身**（空串 = 不显示）。
    #     ⚠️ 文案由服务端给是刻意的：界面"只留标签和数字"那条红线。
    hr_ac: float | None = None
    hr_rmssd: float | None = None
    hr_pi: float | None = None
    hr_pi_hint: str = ""
    #   `hr_finger` 是"传感器上到底有没有手指"这个**事实本身**：`on` / `off` /
    #     `unknown`（串口没开、没数据、停了）。它是 `hr` 为 None 时那句文案
    #     **三档分岔的唯一依据**：有手指但还没攒够 → `--`；手指不在传感器上 →
    #     「未按压」；这一路本身不活 → 「未接入」。
    #     🔴 2026-09-26 补这一个字段：它**曾经整个漏接** —— `snapshot()` 一直在产
    #     `finger`，但 `apply_to_state()` 没往 State 上写、这里也没这个字段，
    #     而 `ui/web/live.js` 的 `XQ.hrText` 已经开始读 `s.hr_finger`。
    #     症状就是用户报的那一条：「我手不按着了 它就显示心率未接入 明明接入了
    #     只是我没按着」—— 读到 `undefined` 掉进默认那一支，三档退成一档。
    #     ⚠️ 注入式的检查脚本**抓不到**这一类：它注入的是它自己编的键，
    #     "注入 → 渲染 → 断言"自洽地通过，而真机上那个键从不出现。
    #     所以 `_check_hr_ui.py` 另有一条断言盯着它：**前端读的每个键，
    #     都要在服务端真发的那一帧里存在**。新增读 `s.xxx` 的地方记得同步那张表。
    hr_finger: str = "unknown"
    source: str = "demo"      # demo / replay / live —— 界面要标出来，别让人以为是实时
    note: str = ""            # 给界面的一句话解释（比如"支路二热身中"）

    def derive(self, sev_cfg: dict, alarm_cfg: dict | None = None) -> "State":
        """把原始列翻译成界面用的字段。纯函数，不碰 IO。"""
        alarm_cfg = alarm_cfg or {}
        # --- 疲劳程度：情感通道（四档）---
        pf, pc = self.p_fat, self.perclos
        # 轻/中两档的数值门槛来自需求文档：PERCLOS 18.7% / 42.6%、p_fat 0.35 / 0.55。
        # **重这一档没有数值门槛** —— 它是支路一的类别（下面 `l1 >= 3` 那一支）。
        mild_pc = sev_cfg.get("mild_perclos", 0.187)
        mild_pf = sev_cfg.get("mild_p_fat", 0.35)
        mod_pc = sev_cfg.get("moderate_perclos", 0.426)
        mod_pf = sev_cfg.get("moderate_p_fat", 0.55)
        # 哈欠：用户原话「轻度疲劳就是打哈欠啊 闭眼时间稍长啊」。**哈欠不进**支路二
        # 的逻辑回归（训练集里没有哈欠样本，见 `tools/fit_branch2.py`），它是规则
        # （`src/face.py` 的 `YAWN_MIN`）—— 所以这里单独认一条，和 perclos 并列。
        yawn_min = alarm_cfg.get("yawn_min", YAWN_MIN_DEFAULT)
        yawning = self.yawn_sec is not None and self.yawn_sec >= yawn_min

        if self.l_fused >= 3:
            # ★ 重度**只能**由"姿态性质"的证据给：用户原话「重度疲劳就是点头 低头
            #   头部倾倒这些」，这三件事支路二（眼睛/嘴）看不见。
            #   ★ 2026-09-26 从 `l1 >= 3` 改成 `l_fused >= 3`：低着头的人会被
            #     **低头规则**（`head_swing >= 10°`，`src/face.py` 的 `HEAD_DEG`；
            #     量是"最近 2 s pitch 的 p95 − 抬头位"，2026-09-26 第三次换的口径）
            #     抬到 L3，而支路一的 `l1` 那时可能还是 0 —— 如果这里继续只认 `l1`，
            #     屏上就会出现「级别：重度 / 疲劳程度：清醒」这种自相矛盾，
            #     而用户投诉的原话正是「我都快死了 还报我健康」。
            #     两条通道必须同升降，判据取**融合后的级别**。
            self.severity = "severe"
        elif (pc is not None and pc >= mod_pc) or (pf is not None and pf >= mod_pf):
            self.severity = "moderate"
        elif ((pc is not None and pc >= mild_pc)
              or (pf is not None and pf >= mild_pf) or yawning):
            self.severity = "mild"
        else:
            # ★ 2026-09-24：这里原本有个"冷启动兜底"——支路二一个数都没有时，
            #   拿支路一的 `ema_normal`（就是闸门那个量）猜档，`< 0.45` 写「重度」。
            #   那个猜法有个已知局限：**闸门关着时分不清是什么拿走了概率**，
            #   一个正在低头/扭头的人会被写成「重度疲劳」。现在**非重度一律不猜**：
            #   要么支路二给出数（上面三支），要么就写"清醒"、并在下面的 note 里
            #   写明"疲劳程度待判"。界面宁可说不知道，也不编一个数出来。
            #   而"重度"本来就有一条**真实**证据（`l1 >= 3`，上面那支），它不是猜的。
            self.severity = "normal"

        # --- 安全通道：直接用系统的融合级别，不重新判 ---
        self.level = int(self.l_fused)
        self.level_name = LEVEL_NAMES.get(self.level, "清醒")
        self.severity_name = SEVERITY_NAMES[self.severity]

        # --- 注意力 / 行为：**次要信息**，说明是什么行为把档位抬起来的 ---
        # ★ 2026-09-25 二类之后这一行**不再读类别概率**：`phone` 和 `fatigue`
        #   已经并成同一个类，「低头」和「点头」在概率上再也分不开了（那正是合并的
        #   目的）。改由**支路二的量**描述行为 —— 而且是**只**用其中的免基线的两个：
        #
        #     nod     窗内"|pitch − 本窗中位| > NOD_DROP(12°) 且持续 ≥0.5 s"的次数
        #     d_pitch 窗内 pitch 的 p95 − p5 极差
        #
        # ⚠️ **绝不用绝对 pitch 设阈值。** 这个坑本项目踩过并记在 `ui/web/app.js`
        #   的注释里：每个人有自己的头部基线（实测 session1 中位 7.5°、session2
        #   中位 7.0°），按绝对角判必然误判。上面两个量都是**相对本窗/本人的**，
        #   天然免基线 —— 这也是当初只让它们进特征向量的同一个理由。
        #
        # 物理上两者确实分得开，不是凑的：
        #   节律点头 → 反复偏出中位，`nod` **高**、极差大
        #   持续低头 → 低头后中位跟着挪过去，不再产生新的偏移事件，
        #              于是 `nod` **低**，而窗里"从正姿到低头"那段过渡仍让极差大
        # 档位不受这一行影响（重度那条证据是 `l1`，见上）。
        nod_n = self.nod if self.nod is not None else 0.0
        dp = self.d_pitch if self.d_pitch is not None else 0.0
        if nod_n >= NOD_BUSY and dp >= HEAD_RANGE:
            self.attention = "疲劳点头"
        elif dp >= HEAD_RANGE:
            # 头偏出中性姿态、但不是在节律性地点头 → 持续低垂。
            # ★ 2026-09-24 深夜这一格从「低头看手机」改成「头部持续低垂」，
            #   首页概率条那两行的标签同源；**这一行会被印在同一张卡底部那行小字里**
            #   （app.js 的 `注意力 …`），两处各叫一个名字就会自己打自己的脸。
            self.attention = "头部持续低垂"
        elif dp >= HEAD_RANGE * 0.5:
            self.attention = "略有低头"
        else:
            self.attention = "专注"

        # --- 眼睛开合：给界面上的示意头像用 ---
        if self.ear is None:
            self.eyes = "unknown"
        elif self.en_now is not None and self.en_now < 0.80:   # BLINK_THR
            self.eyes = "closed"
        else:
            self.eyes = "open"

        # --- 支路二那两条独立告警：绕开级别单独报一次 ---
        # 为什么需要这一条：哈欠和持续闭眼在管线里**都会**把 l_fused 抬起来
        # （`src/fuse.py:635-638` / `ui/cam.py:321-323`），但抬起来的后果混进了
        # 「注意」这个级别里 —— 而 L1 同样可能只是"瞟了一眼后视镜"。
        # 光看 L1 分不出这两件事，所以这里按支路二**自己的原始量**再报一条，
        # 带上原因。用户要的就是这个：支路二专门为这两件事训的。
        #
        # ⚠️ 判据只认支路二的量（`l2` / `yawn_sec`），**不看 level**。
        #   `l2` 已经隐含了闸门（闸门关时 fuse.py / cam.py 都把它归零），
        #   所以这里不用再判 `gate`。
        # ⚠️ `yawn_min` 必须和 `src/face.py` 的 `YAWN_MIN` 一致（2026-09-26 第二次
        #   改小起 = 1.0，且配的是**滚动均值**那版判据）。ui/ 不 import src/（会把 mediapipe 拖进 demo 模式），所以
        #   这个数只能写在 config 里，两边互相注释指着 —— **改一处必须五处一起改**：
        #   src/face.py · ui/config.json · ui/config.example.json ·
        #   ui/state.py（这里）· ui/web/live.js 的 `XQ.alarms.yawnMin` 兜底。
        #   漏掉任何一处，屏上的「打哈欠」横幅和融合器的判决就会**各判各的**。
        self.alarms = []
        yawn_min = alarm_cfg.get("yawn_min", YAWN_MIN_DEFAULT)
        if self.yawn_sec is not None and self.yawn_sec >= yawn_min:
            self.alarms.append({"kind": "yawn", "text": NOTE_YAWN})
        # ★ 2026-09-26：闭眼这条现在有**两个**来源 —— 支路二的逻辑回归（`l2`）和
        #   **持续闭眼规则**（融合器写的 `src == "eye"`）。两者说的是同一件事，
        #   所以合成**一条**，取两者里更高的那个级别决定文案 —— 各报一条会出现
        #   屏上挂着两条一模一样的「检测到持续闭眼」（改完第一次跑就是这样）。
        # ⚠️ 合成的**级别**取两者里高的那个，**文案**却不跟着级别走、跟着**来源**走：
        #   `src == "eye"` 说明规则真数过连续闭眼时长，才配说「检测到持续闭眼」；
        #   只有 `l2` 的话（模型量的闭眼占比）说的是另一句（见 `NOTE_FACE_MODEL`
        #   上面的注释）。同一个 kind、同一个位置，只有 `text` 分得开这两件事 ——
        #   这也是 `wechat.py` 和 `live.js` **都优先用告警自带的 `text`** 的原因，
        #   它们各自的兜底表（`KIND_LABEL` / `ICON_OF`）只认 kind，认不出这个区别。
        lv_eye = self.l2
        if self.src == "eye":
            lv_eye = max(lv_eye, 2)        # 规则只抬到 L2（见 src/fuse.py 的 EYE_LEVEL）
        if lv_eye >= 1:
            table = NOTE_FACE if self.src == "eye" else NOTE_FACE_MODEL
            self.alarms.append({"kind": "eyes",
                                "text": table.get(lv_eye, table[1])})
        # 低头/点头规则（`src == "head"`）。判据是融合器写的 `src`（"是谁把级别抬
        # 起来的"），**不是**在这里比阈值 —— 界面里没有 `CLOSE_EYE_SEC` / `HEAD_DEG`
        # 的第二份定义（刻意的：多一个抄本就多一个"同一块屏幕上两个判据各判各的"
        # 的机会）。`kind` 只是给前端挑图标用的（认不出的 kind 走 `alert`）。
        # ⚠️ 支路一自己也判低头（它给 L3），那时 `src` 是 `pose`、这里不报 ——
        #   级别**照样是重度**（`l_fused` 已经取过最大），缺的只是这一句"原因"。
        #   平局判给基线是**刻意**的：老的两条（基线/哈欠）在同样输入下要逐位复现
        #   改之前的行为，见 `src/fuse.py` 那个 `max(...)` 的注释。
        if self.src == "head":
            self.alarms.append({"kind": "head", "text": NOTE_HEAD})

        # --- 冷启动倒计时（两级，和 ROLL_WIN / WARMUP_SEC 对应）---
        # `pc_span` 优先于 `t`：闸门一关缓冲就 `clear()`，基线是**从零重攒**的，
        # 拿墙上时钟猜必然错。CSV 回放源给不出 span（行里没这一列），退回用 `t` ——
        # 日志文件都是从 0 秒开始的，只有"闸门中途关过"那一种情况倒计时不准，
        # 那时 `pc_ready` 本身仍然是对的（它判的是 perclos 有没有数）。
        span = self.pc_span if self.pc_span is not None else self.t
        self.pc_warm_left = max(0.0, ROLL_WIN - span)
        self.b2_warmup_left = max(0.0, WARMUP_SEC - span)
        # 这两个标志位是**推出来**的，不是数据源报的：有数就等于那一级到了。
        # ★ 2026-09-24 晚统一到这儿：原来 `pc_ready` 没有、`b2_ready` 由数据源各自
        #   维护（`sources.row_to_state` 一套、demo 的 `poll()` 又一套）—— 两份判据
        #   就是两个漂移入口，这次的 bug 正是"判决"那一级被当成了"有数"那一级。
        #   现在数据源只管给数（perclos / p_fat），就绪与否由这里判，只有一处。
        #   （cam 那边 perclos 非 None 当且仅当 `fb.ready()`、p_fat 非 None 当且仅当
        #   `fb.full()`；demo 那边由 `t` 决定。两种源都对得上。）
        self.pc_ready = self.perclos is not None
        self.b2_ready = self.p_fat is not None
        # 二分类的另一半。就放在"就绪"这两个标志旁边 —— 它俩同生共死，
        # 都是 `p_fat` 的函数（`b2_alert` 为 None 当且仅当 `b2_ready` 是 False）。
        self.b2_alert = (None if self.p_fat is None else 1.0 - self.p_fat)
        if self.note == "":
            if self.severity == "severe":
                # 支路一已经判了重度（低头/点头/倾倒），这不是"待判"——支路二缺席
                # 只说明"闭眼/哈欠"那条信息还没有，别拿热身倒计时盖掉已出的判决。
                self.note = ("支路一已判重度（姿态：低头 / 点头）"
                             + ("" if self.pc_ready else " · 支路二基线热身中"))
            elif not self.gate:
                # 闸门关着 = 支路二停投（它的输入是"正视前方"时的脸，缓冲会清空）。
                # 这时疲劳程度只剩支路一这一条证据，而它没给重度 —— 于是说"待判"。
                # 这是 2026-09-24 修掉那个"拿 ema_normal 猜档"的兜底之后的正确行为。
                self.note = "闸门关闭（未正视前方）· 支路二暂停投票，疲劳程度待判"
            elif not self.pc_ready:
                self.note = (f"支路二基线热身中 · 还需 {self.pc_warm_left:.0f} 秒"
                             f"（攒够 {ROLL_WIN:.0f} 秒才出 PERCLOS）")
            elif not self.b2_ready:
                self.note = (f"PERCLOS 已出 · 疲劳判决还需 "
                             f"{self.b2_warmup_left:.0f} 秒")
        return self

    def to_json(self) -> dict:
        d = asdict(self)
        d["probs"] = {k: round(float(v), 4) for k, v in self.probs.items()}
        return d
