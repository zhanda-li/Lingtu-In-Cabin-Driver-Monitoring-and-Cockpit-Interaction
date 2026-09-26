# -*- coding: utf-8 -*-
"""
心率：HPM5300 + MAX30102 → 板载 FT2232 的 console 串口 → 本进程 → 网页端。

板端固件在 `hr/firmware/`（独立工程，`build.bat` / `flash.bat`；
2026-09-26 从 `hpm_sdk\\hr_project` 复制进本项目，接线/协议/验收全在
`hr/README.md`），100 Hz 往外吐**原始计数**，一行一个样本：

    #<text>              状态/横幅（本模块只记日志）
    D,<t_ms>,<red>,<ir>  一个样本
    H,<t_ms>,<hr>,<rmssd>,<pi>   板端自己算的那三个量，1 Hz（★ 2026-09-26 加）
    E,<code>,<text>      错误

⚠️ `H` 行**只进「数据详情」页的原始行环**，页面上的三个数**不看它** ——
   页面认的始终是本模块算的那一份（五道门/频谱兜底/化石修复都验过），
   板端那份的用处是串口上看得见 + 验收 4.4 的交叉校验。

── 为什么算法在 PC 上，不在板子上 ──────────────────────────────────────
板子只负责"把 PPG 波忠实地送出来"。三个理由：
  1. **先要能看见波**。MAX30102 这个模块最容易踩的是环境光把光电二极管打饱和
     （说明书 FAQ 第 2 条），以及 LED 电流偏小导致交流分量淹没在量化噪声里。
     这两种情况都只能从原始波形上认出来 —— 板端直接算的话，PC 侧只拿到一个
     "心率=88"，是饱和还是真心率分不出来。
  2. 调参要改的是一个 Python 常量，不是一次编译 + 烧录。
  3. 板端固件因此可以很小、很容易验证（I2C + FIFO + 串口，没有算法状态）。
如果以后要"脱机也能显示"，把 `_HrTracker` 这一段照搬成 C 就行 —— 它没有
任何 numpy/第三方依赖，全是加减乘和一次比较。

── 数据源的关键约定：时间戳用板子给的 t_ms ──────────────────────────────
样本间隔的 10 ms 是芯片自己的采样时钟（板端按 100 Hz 回推），比"PC 收到这一行
的时刻"准得多 —— UART 缓冲会让到达时刻抖几十毫秒，而心跳间隔(I BI)就是靠
几十毫秒的分辨率算出来的。所以 IBI 全程用 t_ms 算。
⚠️ t_ms 是**开机以来的毫秒数**（32 位，49.7 天回绕），板子一复位就回到 0。
   本模块把"时间倒回去了"当成一次复位：清空心跳历史重来，而不是让它算出一个
   负的间隔。

── 什么时候**不给**数字 ────────────────────────────────────────────────
和全项目同一条规矩（见 `ui/state.py` 的 `hr` 字段注释）：量不出来就给 None，
页面上那格显示「未接入」，绝不拿上一次的数凑。触发 None 的四种情况：
  · 串口没开 / 没数据超过 `STALE_S`
  · 手指不在位（IR 直流低于 `FINGER_DC_MIN`）
  · **传感器上没有搏动**（带通后的交流低于 `AC_MIN_RMS`，见那一段）
  · **两条路都说不出话**（主路 `bpm()` 与兜底 `spec_bpm()` 同时给 None）

── 两条路 ──────────────────────────────────────────────────────────────
主路      峰值检测 + 间隔中位数 + 质量闸 + 时效（`_HrTracker.bpm`）。灵敏，首选。
频谱兜底  主路被质量闸拒时改用频域找基频（`_HrTracker.spec_bpm`）。
          2026-09-26 加：用户报「数字别老消失」（真人 30 秒里只有 6 秒有数）。
          查出来那道闸**分不开好和坏**（详见 `MAX_IBI_SPREAD` 下面那一大段），
          而多检/漏检这两种错在频域里不挪动基频的位置 —— 所以拿它兜底。
          ⚠️ 它有自己的毛病（运动幅度被低频调制时会自信地报错），**所以只兜底、
             不替换主路**：主路能出数就用主路。

── 三道门，谁管什么（2026-09-26 补后两道）──────────────────────────────
起因：用户报「现在心率还不是实时的」——`hr` 冻在 119.9 一动不动。
两道门各治一条独立的毛病，**都不能省**（详见各自的常量注释）：

  `ibi_fresh`  治**化石**。主路原来对自己的输入没有任何时效检查，8 个间隔
               不再进新值也照报不误 —— 屏幕上是一个不动的数，而 `finger` 还
               写着 on，且它非 None 就**把兜底挡住了**。
  `AC_MIN_RMS` 治**噪声里"找到"搏动**。峰值检波的阈值是 `PEAK_FRAC * env`，
               把自己的尺度归一化了，所以输入只剩噪声它也照样出数。
               时效救不了这一条 —— 噪声确实在不停产生搏动。
               它放在 `snapshot()` 的**出口**，两条路一起卡。

⚠️ **两条门都拦不住的一种**：真有大幅度的带内干扰（运动伪影、环境光闪烁）
   而且峰还规整 —— 它会报一个**会动的**错数。PPG 没有加速度计做参考运动消除，
   这件事靠阈值解决不了，得如实承认。
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque

# ============================================================================
# 常量
# ============================================================================

BAUD = 115200

# 板端采样率。改了要连带改 `hr/firmware/src/max30102.h` 的 SPO2 配置。
SAMPLE_RATE_HZ = 100

# 带通 0.65~3.5 Hz。上限 3.5 是给运动伪影/谐波留一点，再高就只剩噪声了。
# 下限 0.65 是**量出来的**，不是"PPG 基频不会低于这个数"那种推理 —— 见下面。
#
# ⚠️ 2026-09-26 的完整经过（走了两段弯路，都记着，免得再走）：
#
# ① 症状：真人手指第一次按上去，屏幕上一个数都不出。
# ② 第一段弯路：我离线比了 10 种前端（`_scratch/_hr_front.py`），**把原版自己
#    重写成一个"高通×1 + 低通×1"的 4 阶带通当基线**比。那不是同一个滤波器，
#    比出来的差异不算证据。（那一段的"现状"行是假的，脚本已标"拼"。）
# ③ 但**结论方向是对的**：原版是**一个 2 阶 RBJ 带通**（f0 = √(0.7×3.5) =
#    1.565 Hz，Q = f0/BW = 0.56），拿它自己当基线重测（`_scratch/_hr_ab_front.py`），
#    在**同一段真人录制**（runs/_hr_raw.txt，15 s）上只登记 5 拍 → 出不了数。
#    两个独立口径都说真值约 65 BPM：自相关 64.5、频谱峰 1.09 Hz = 65.4
#    （runs/_hr_look.log）。原版是**真的坏了**，不是"手指没按好"。
# ④ 换 4 阶巴特沃斯高通之后，同一段录：17 拍、离散度 0.032、64.7 BPM。
#    **拐点扫过 0.50~0.80**，0.65 是唯一两头都占的：
#      拐点 ≤0.60 → 真人那段开始漏拍（0.50 时只剩 13 拍，中间整段缺）
#      拐点 ≥0.70 → 60 BPM 的合成波被数成两次（间隔 0.40/0.60 来回跳）
#    为什么是"拐点"这个自由度：这段录里 0.53 Hz 那个 artifact 的幅度（201）比心跳
#    1.09 Hz（132）还大，拐点就是"滤完之后谁更大"的旋钮。两个数都是量出来的：
#    · 幅度 201 / 132 —— runs/_hr_look.log 的频谱；
#    · 4 阶巴特沃斯在各拐点上的增益 —— 见下表（transfer function 直接算的）。
#    要让心跳赢，artifact/heart 的增益比必须大过 201/132 = 1.52：
#
#        拐点    0.53 Hz 增益    1.09 Hz 增益    比值     谁赢
#        0.50      0.784          0.994         1.27    artifact  ← 真人那段在这儿漏拍
#        0.55      0.653          0.993         1.52    打平
#        0.60      0.520          0.991         1.91    心跳
#        0.65      0.404          0.988         2.44    心跳    ← 线上
#        0.70      0.312          0.981         3.14    心跳
#
#    比值越过 1.52 的点落在 **0.55 附近**，而实测的行为分界正好在那儿（0.50 漏拍、
#    0.70 起合成波被数成两次）—— 两边对得上，所以这个解释站得住。
#    ⚠️ 唯一还是推断的一步：把"0.53 Hz 的 DFT 峰"等同于那个 artifact 的来源。
#       幅度和增益是测量，这一步是解释。
# ⑤ 第二段弯路：给峰值判据加过"迟滞"（`RESET_FRAC`），想治"一次搏动数成两次"。
#    量完删了 —— 60 BPM 照样出不了数，反而把原版在"信噪比 2:1"那档从"正确不出数"
#    变成"给个 75.0"。
#
# 已知的、量出来的短板（不是 bug，是这套参数的边界）：
#   · 48 BPM（0.8 Hz）的合成波 → 不出数（拐点 0.65 只比基频高 1.23 倍，脉搏波形被
#     相移搞歪，舒张期小峰被当成一次搏动，间隔 0.4/0.6 跳 → 被质量闸拦下）。
#     是"拒绝回答"而不是"给个错数"，符合本项目"错的数比没有数坏"的口径。
BP_LOW_HZ = 0.65
BP_HIGH_HZ = 3.5

# 4 阶巴特沃斯的两个二阶节 Q。**这两个数是标准值，不是调出来的** —— 换了它们
# 就不是巴特沃斯了（通带不再最平，拐点附近会鼓起来或者塌下去）。
BW4_Q = (0.54119610, 1.30656296)

# 单个间隔的允许范围（秒）：0.33 s = 180 BPM，1.60 s = 37 BPM。
# 超出范围的不是心率，是漏检或多检。
MIN_IBI_S = 0.33
MAX_IBI_S = 1.60

# 中位数窗口。取 8 而不是 4：中位数只有在"坏值不过半"时才有用，
# 8 个里坏 3 个仍然稳。
BEATS_KEPT = 8
# 少于这个数就不出数（4 个间隔 = 至少 5 次心跳、约 4 秒）。
MIN_BEATS = 4

# 间隔离散度（MAD/中位间隔）的上限，超了就**不出数**。
#
# 中位数只挡得住**少数**坏间隔 —— 噪声当搏动当到过半时，中位数自己就跟着错了，
# 而且错得看不出来（屏幕上就是一个平滑的、看着很合理的心率）。所以需要一个
# "这串间隔到底像不像心跳"的判据，把那种情况变成「未接入」而不是一个假数字。
#
# 0.20 是量出来的（`_scratch/_check_hr_algo.py`，10 组合成波）：
#   弱信号/强噪声/基线漂移等**每一种单独出现**时   0.000 ~ 0.025
#   三者叠加（ac=250、σ=120，信噪比 2:1，已经没救了）   0.368
# 中间是 15 倍的空档，取 0.20 两头都留了余量。生理上的上界是呼吸性窦性心律不齐
# （相邻间隔差 ±5~10%），0.20 比它宽松一倍 —— 宁可偶尔不出数，也不出一个假数。
#
# ⚠️ **漏一次搏动不会触发它**（MAD 对单个离群值免疫：7 个 T 加 1 个 2T，
#    中位和 MAD 都不动）。漏检归中位数管，这一条只管"错到过半"。
MAX_IBI_SPREAD = 0.20

# ---- 主路的**时效**（2026-09-26 加）----
#
# 用户当场报「现在心率还不是实时的」—— 实测到 `hr` 冻在 119.9 一动不动
# （20 秒 159 帧、min=max=last；同一帧里 pitch/ear/mar 全都是 159 个不同的值，
# 所以 tick 是活的，冻的只有心率这一路）。
#
# 根因：`bpm()` 是**队列的纯函数**，里面一个时间项都没有。`ibis` 那 8 个间隔
# 一旦不再进新值，它就永远返回同一串间隔的中位数 —— 屏幕上是一个**化石**，
# 而 `finger` 仍然写着 on。更糟的是它非 None 就**把频谱兜底整个挡住了**。
#
# 离线复现（`_scratch/_hr_fossil.py`，真人录 15 s 后接"直流一样高、没有脉搏"）：
#   真人段 65.2 正常 → 信号一没，峰值检波照样在噪声里"找到"搏动，
#   报数一路飘 65→90.9→96.8→103.4→115.4，**从来不回 None**。
# 所以这不是"偶尔冻一下"，是"输入没了也照报不误"。
#
# 判据用**样本时间**（`self.last_t - self.last_ibi_t`）而不是墙钟：`last_ibi_t`
# 是板子时刻，两者必须在同一个钟上；而且这样离线脚本才能复现 ——
# `spec_bpm` 的节流用 `time.monotonic()`，离线跑 75 秒模拟只花几十毫秒墙钟，
# 于是永远命中缓存（`_hr_fossil.py` 第一版就打出过一串假 62.5，见该文件说明）。
#
# 窗取 `MAX_IBI_S * 2.5` = 4 s，和原来那个死代码 `stale_beats()` 同一个值：
# 正常攒满 8 拍约 4~8 s，4 秒没有任何**被采纳**的间隔就是"这一路说不出话了"。
IBI_FRESH_S = MAX_IBI_S * 2.5

# ---- 交流幅度下限：**唯一一个不看波形的判据**（2026-09-26 加）----
#
# 峰值检波有一条结构性弱点：阈值是 `PEAK_FRAC * env`，**它把自己归一化了**。
# 信号小到只剩噪声，包络跟着缩，阈值也跟着缩，于是噪声里照样能"找到"搏动。
# 这就是上面那段飘数字的来源 —— 光靠时效救不了它（噪声确实在不停产生搏动），
# 必须补一个**绝对尺度**上的判据：带通之后还剩多少交流。
#
# ⚠️ **先别拿合成噪声给自己找位置**（我差点这么干）：`_scratch/_hr_acfloor2.py`
#    里"没有脉搏"那组是**我随手挑 σ** 的白噪声，σ=100/200 那两档算出来的
#    24.9 / 49.8 会一直追到有脉搏那侧（最弱的 ac=200 是 54.2，只差 1.09 倍）——
#    但那只能说明"绝对阈值不是万能的"，**不能用来给阈值定位**，
#    否则就是拿自己的假设论证自己的阈值。
#
# 真实噪声量在 `_scratch/_hr_noise.py`：拿唯一那段真人录
# （`runs/_hr_raw.txt`）抠出 **10 Hz 以上**那部分（脉搏在 1 Hz 附近，到不了那儿）
# 直接量 ——
#     逐样本 σ ≈ 20 个数（MAD）/ 49（含尖刺），>10 Hz 实测 RMS 23.5 个数
#     投回 0.65~3.5 Hz 带通（带宽占比 5.7%） → **带内噪声只有 5.6 个数**
#     同段带内交流（脉搏+噪声）761 个数 → 信噪比约 136 倍
# 所以下限放在**实测噪声 5.6 的 3.6 倍**、**真手指 498 的 1/25** ——
# 两头都留着量级级的余量。有风险的是弱脉搏那侧，所以贴着噪声那头取。
#
# ⚠️ **没量的那一种**：以上全是"手指按着"时的噪声。**手指拿开、只有环境光**
#    时噪声多大，这份数据答不了（直流顶到满量程时 ADC 可能削顶，噪声变大变小
#    都可能）。真饱和若把带内噪声顶过 20，这道门就拦不住它 —— 那时还有
#    `ibi_fresh`、离散度闸、兜底的量程边拒三道兜着，最坏是一个**会动的**错数，
#    不是原来那种纹丝不动的化石。要坐实得占串口录一段空载高直流。
AC_MIN_RMS = 20.0

# ============================================================================
# 频谱兜底 —— 峰值法不肯出数时，改用频域给一个（2026-09-26 加）
# ============================================================================
# 起因：用户要「数字别老消失」。真人那 30 秒里只有 6 秒有数，其余全是「未接入」。
#
# 查出来两件事，都记在 `_scratch/_hr_agree.py` / `_hr_est_ab.py` / `_hr_spec.py`：
#
#   ① 「消失」的那段时间里，`MAX_IBI_SPREAD` 算出来是 0.11~0.48，而**下面的中位数
#      估出来的值误差只有 −2.4 BPM**（锚 = 同一段整段计数 61.3）。也就是说这道闸
#      在信号其实还能用的时候也在拒。
#   ② 更麻烦的是：**这道闸分不开好和坏**。合成波里散度 0.254 时误差 +9.5、
#      散度 0.314 时误差只有 −2.4 —— 两个方向都反着；换个"两个估法互相印证"的
#      判据也一样分不开（不一致度 1.6% 那档误差 +38，29% 那档误差 0）。
#
# 为什么分不开：多检和漏检**在间隔序列上长得一模一样**。运动把包络顶起来时，
# 一半的拍被数成两下、一半漏掉，凑出中位数 1.2 s 这种看着很合理的数 ——
# 到底哪一半赢，序列本身看不出来。
#
# **频域里这两件事都不改变基频的位置**（一个周期信号漏掉一个周期，它的 1/T
# 分量几乎不动），所以频谱法对这个失效模式天生免疫。实测（`_hr_spec.log`）：
#   · 峰值法被散度闸拒的那档「ac250 σ120 漂移2000」，频谱给 **75.0**（真值 75，误差 0）
#   · 真人那 15 秒录音：频谱 65.6~65.9（6/8/10/12 秒窗几乎不动），峰值法 64.5
#
# ⚠️ **只当兜底，不替换主路。** 频谱法有个相反的毛病：运动幅度被低频调制（AM）时
#    它会**很自信地**报错（合成"运动 3×"档频谱报 93.0，真值 75，而峰值法那档
#    正确地拒了）。主路能出数时主路更可信，所以顺序永远是：主路能用就用主路。
#
# 全程 12 秒窗。自相关也试过（同一件事的时域等价形式、更便宜），**更差**
# （"运动 3×"档误差 −43），所以用 DFT。抽取 ÷4 后结果**逐位不变**（实测），
# 抽完一次只要 ~250 点，读线程里算得动。
SPEC_WIN_S = 10.0
SPEC_LO_HZ = 0.80          # 48 BPM
SPEC_HI_HZ = 2.50          # 150 BPM
SPEC_STEP_HZ = 0.0025      # 频率网格步长（抛物线插值把它再细化 ~10 倍）
SPEC_DECIM = 4             # 每 4 个带通样本取一个（100 Hz → 25 Hz）
SPEC_MIN_S = 4.0           # 至少这么多秒的波形才算，少了不猜
SPEC_EVERY_S = 1.0         # 最快多久重算一次（state 每秒问好几次，必须节流）

# 峰值判据：滤波后的信号超过 `PEAK_FRAC × 幅值包络` 就算一次搏动。
# 包络按 τ≈2 s 缓慢衰减，所以它跟的是"当前这个人的脉搏强度"，不是固定阈值 ——
# 不同人、不同按压力度下幅度能差好几倍。
PEAK_FRAC = 0.45
ENV_DECAY = 0.995          # 每个样本，100 Hz 下 τ ≈ 2 s

# ⚠️ 曾经在这里加过一个 `RESET_FRAC`（迟滞：重新武装要落到更深的阈值以下），
#    想治"一次搏动被数成两次"。**量完删掉了**（`_scratch/_hr_ab_front.py`）：
#      · 拐点在 0.7 的那套，60 BPM 的间隔是 0.40/0.60 来回跳，加迟滞只把它变成
#        0.59/0.41/0.99 混着跳，**照样出不了数**（迟滞不是要害）；
#      · 反而把原版（单节带通）在"信噪比 2:1"那档从"正确不出数"变成"给个 75.0"。
#    真正的要害是**拐点离脉搏基频太近**（见下面 `BP_LOW_HZ` 的注释）——
#    换个地方治，别在这儿加阈值。

# 手指在位的判据：IR 直流的均值下限。**这个数是量出来的，不是拍的** ——
# 2026-09-26 空载实测 IR ≈ 8450（见 runs/_hr_sniff.log），手指按上去会高一个量级。
FINGER_DC_MIN = 20000.0
FINGER_DC_WIN_S = 1.0

# 多久没有新样本就认为"这一路死了"。
STALE_S = 1.5

# 串口打不开时的重试间隔。用户可能正开着串口助手占着这个口，所以必须能自己回来。
REOPEN_S = 3.0

# 「数据详情」页那一路要显示的**板子原始行**环长（`SerialHr.log_lines`）。
# `H` 行每条全留、`D` 行每秒抽 1 行 ⟹ 稳态约 2 行/秒，240 行 ≈ 2 分钟。
LOG_MAX = 240


# ============================================================================
# HRV-RMSSD 与 PI 灌注指数（2026-09-26 加）
# ============================================================================
# 🔴 **下面这四个常数是"共享常数"**：板端 `hr/firmware/src/hr_algo.h` 里有一份
#    **逐字相同**的拷贝，两边算出来的 RMSSD/PI 才可能一致（验收 4.4 要并排比）。
#    改这里必须同时改那边，否则交叉校验会**静默地**对不上，而"对不上"本身
#    看不出是哪边错了。
#
# ── RMSSD ──────────────────────────────────────────────────────────────
# 只从**连续**的 NN 间隔序列上算：`_register_beat` 会把超范围的间隔丢掉，所以
# 两个前后脚被采纳的间隔**未必来自相邻心跳**，中间可能夹着若干个被拒的。
# 直接把它们串起来算，相邻两项的差就不是 NN 差 —— RMSSD 会**算错但看着很合理**。
# 判据是精确的整数比较：这一段的**起点** == 上一段的**终点**（都是板子钟 ms）。
#
# 跨度门槛 30 s 是用户点名要的（「只等 30s 稳定之后才输出；前 30 秒区域显示 --」）。
HR_NN_NEED_MS = 30000

# NN 环深。**必须 ≥ 理论上限**：跨度 30 s、最短间隔 0.33 s ⟹ 最多 91 个。
# 取 128 留 37 个余量（0.33 s 是贴着下限的，真人不会正好卡在边界上）。
HR_NN_MAX = 128


# ── PI 灌注指数 ────────────────────────────────────────────────────────
# PI = 交流 / 直流 × 100%。交流用**带通之后的** RMS，直流用那个 1 秒均值。
#
# ⚠️ 为什么口径选 RMS，而不是峰值保持 / 峰峰值 —— 有一条**会把人带沟里**的判据
#    要先排除：如果拿"把交流按增益缩放"（按好了/轻按/很轻/空载）去比这三个口径，
#    会得到"三个完全一样"的结论。那不是巧合也不是 bug：按压力度在模型里是线性
#    缩放，而三者都是交流的线性泛函，**线性变换下比值恒等**。谁做这个实验都会
#    拿到一张漂亮的表然后得出不成立的结论。
#
#    真正能分开它们的是另外四条（要专门造数据量）：响应时间、离群敏感度、稳态
#    抖动、空载泄漏。选 RMS 还有一条**不靠测量**的理由：`AC_MIN_RMS` 是量出来的
#    阈，而量它的函数就是 `ac_rms()` —— **只有 RMS 和它同口径，那道闸可以直接搬**。
HR_PI_AC_WIN = 300          # 交流窗（样本数）= 3 s @100 Hz
HR_PI_AC_MIN_N = 32         # 不满这么多不给 PI（照抄 ac_rms 的"不该把它当没搏动"）

# PI 低到多少才提示「请调整手指按压位置」。**2026-09-26 标定过**，推导在下面。
#
# ⚠️ 临床上的"PI < 0.3% 灌注差"在这套硬件上**不适用** —— 7.2 mA LED + 廉价模块，
#    好按压本来就在 0.1~0.3% 这一带，搬临床阈 ⟹ 提示永远亮着、变成噪声。
#
# ── 标定数据（两段真人实录，`_scratch/_hr_pi_scan.py` 扫出）────────────────
#     A. `runs/_hr_nn_20260926_205912.txt`（90 s，稳态好按压，41 个窗）
#        dc ≈ 128300 恒定、峰频 0.92~1.10 Hz、搏动占比稳在 65~75%
#        ⟹ **PI = 0.092 ~ 0.211，中位 ≈ 0.115**
#     B. `runs/_hr_pi_cal.txt` 的轻按段（t=20~30 s）
#        dc ≈ 99900 ⟹ **PI = 0.225 ~ 0.299**（更轻的按压 PI 更高，见下）
#     C. 同录的漂移主导段（t=10~12 s）
#        dc ≈ 124000 ⟹ **PI = 0.056 ~ 0.069**，但那一窗的搏动占比只有 16~38%
#        （频谱峰落在 **0.60 Hz = 高通拐点**上）—— 那不是"灌注差"，是**按压力度
#        还在漂**。见下面那条口径警告。
#
# ── 取值规则（**先定规则再算数**，不是挑一个好看的数）──────────────────────
#     取相邻两档的**几何中点**：√(0.092 × 0.069) = 0.0797 ⟹ 0.08。
#     两边等比例余量：0.092/0.08 = 1.15×，0.08/0.069 = 1.16×。
#
# ── 三条必须一起讲的警告（少一条这个数就会被误用）──────────────────────────
#   ① **余量只有 1.15×，这是个弱判据。** 两档本来就挨在一起；而且只有两场
#      实录、n = 2 个不同的按压档。真要收紧它，需要再录一段"刻意重按并保持
#      20 s 以上"的数据（现在的 C 档是从爬升过程的尾巴上截的，不是稳态）。
#   ② **PI 在这里主要反映按压力度，不是灌注。** 两个都是"好按压"的状态
#      （A: dc 128300 → 0.115；B: dc 99900 → 0.27）差了 2.4×，只因为按的轻重
#      不同。所以它是**接触质量**指标：PI 掉下去时"请调整手指按压位置"这句话
#      是对的，**但别把它当生理量讲**（评委追问"这能看出灌注吗"的答案是"不能"）。
#   ③ 🔴 **PI 单独看与"信号质量"不单调。** 无手指时 dc ≈ 780，分母塌掉，
#      **PI 反而 = 1.9%**，高于任何有手指的状态。挡住它的是**手指闸**
#      （`FINGER_DC_MIN`）而不是 PI 本身 —— 谁要是把 PI 从手指闸里拿出来单独用
#      （比如"PI 高就算信号好"），拿到的就是"没按手指 = 信号最好"。
PI_LOW_PCT = 0.08

# PI 偏低时页面上那一行小字。**文案由服务端给**（这里），三个 .html/.js 里
# **不出现这句中文** —— 否则"界面只留标签和数字"那条红线的审计口径就破了。
# 这是用户**点名要的唯一一处**例外：现场演示容错用，评委能看到。
PI_HINT = "请调整手指按压位置"


# ============================================================================
# 二阶节（RBJ cookbook）。0.65~3.5 Hz 的带通由**三节**拼成：
# 两级高通（合起来是 4 阶巴特沃斯，−3 dB 点正好在 0.65）+ 一级低通。
# 为什么必须 4 阶、为什么是 0.65，见 `BP_LOW_HZ` 上面那一大段。
# ============================================================================
class _Biquad:
    """直Ⅱ型转置，逐样本推进。纯 float 运算，无依赖 —— 将来搬 C 就是这一段。"""

    def __init__(self, f0_hz: float, fs: float, kind: str, q: float):
        w0 = 2.0 * math.pi * f0_hz / fs
        cw = math.cos(w0)
        alpha = math.sin(w0) / (2.0 * q)

        if kind == 'hp':
            b0, b1, b2 = (1.0 + cw) / 2.0, -(1.0 + cw), (1.0 + cw) / 2.0
        elif kind == 'lp':
            b0, b1, b2 = (1.0 - cw) / 2.0, 1.0 - cw, (1.0 - cw) / 2.0
        else:
            raise ValueError('kind 只能是 hp / lp：%r' % (kind,))

        a0 = 1.0 + alpha
        self.b0 = b0 / a0
        self.b1 = b1 / a0
        self.b2 = b2 / a0
        self.a1 = (-2.0 * cw) / a0
        self.a2 = (1.0 - alpha) / a0

        self.x1 = self.x2 = self.y1 = self.y2 = 0.0

    def push(self, x: float) -> float:
        y = (self.b0 * x + self.b1 * self.x1 + self.b2 * self.x2
             - self.a1 * self.y1 - self.a2 * self.y2)
        self.x2, self.x1 = self.x1, x
        self.y2, self.y1 = self.y1, y
        return y

    def reset(self):
        self.x1 = self.x2 = self.y1 = self.y2 = 0.0


def _make_bp(fs: float = SAMPLE_RATE_HZ):
    """0.65~3.5 Hz 带通 = 4 阶巴特沃斯高通（两节）+ 一节低通。顺序接起来就行。

    单独一个函数是为了让离线复算脚本（`_scratch/_hr_wave.py`、
    `_scratch/_hr_ab_front.py`）用**同一个**构造，不然改了这里忘了那里，
    离线和线上就是两套前端 —— 那种偏差看不出来（2026-09-26 就栽在这上面）。
    """
    return [
        _Biquad(BP_LOW_HZ, fs, 'hp', BW4_Q[0]),
        _Biquad(BP_LOW_HZ, fs, 'hp', BW4_Q[1]),
        _Biquad(BP_HIGH_HZ, fs, 'lp', 0.7071),     # 巴特沃斯低通，单节就是最平的
    ]


class _HrTracker:
    """
    一个通道（只用 IR）的心率估计。逐样本推进，输出**逐搏更新**的心率。

    算法：直流用滑动均值去掉 → 4 阶巴特沃斯高通 + 低通（拼出 0.65~3.5 Hz 带通）
    → 幅值包络自适应阈值找峰 → 峰值时刻组成的间隔取中位数。三个地方是刻意选的：

    · **峰谷判据用包络而不是固定阈值**：手指按得轻一点信号就小一半，固定阈值
      要么漏检要么把噪声当心跳。
    · **只在"从阈值上方跌回下方"那一刻登记**，且登记的时间是**峰顶的时刻**
      （`peak_t`）不是穿越的时刻 —— 穿越时刻会晚几十毫秒，而 IBI 要的就是
      峰顶之间的时间。
    · **取中位数不取均值**：漏检一次会让某个间隔变成两倍，均值被它拽走，
      中位数没事。
    """

    def __init__(self, fs: float = SAMPLE_RATE_HZ):
        self.fs = fs
        self.bp = _make_bp(fs)

        self.dc_win = deque(maxlen=max(1, int(FINGER_DC_WIN_S * fs)))
        self.dc_sum = 0.0

        self.env = 0.0            # 幅值包络
        self.above = False
        self.peak_y = 0.0
        self.peak_t = 0.0
        # 峰顶的**整数毫秒**。`peak_t` 是秒（浮点），RMSSD 那一路要用整数做差才
        # 可能和板端逐位一致，所以同一个峰顶存两份，别让 RMSSD 去 round 浮点。
        self.peak_ms = 0

        self.ibis: deque[float] = deque(maxlen=BEATS_KEPT)
        self.last_beat_t: float | None = None
        # 最近一次**被采纳**的间隔的时刻（秒，板子钟）。和 `last_beat_t` 是两件事，
        # 差一个条件：`last_beat_t` **每一拍都推进**（哪怕间隔超范围被丢掉），
        # 所以它回答不了"这一路最近还出过数吗"。看 `ibi_fresh`。
        self.last_ibi_t: float | None = None
        # 最近一次 push 的样本时刻。时效判据两边都用样本钟，见 `IBI_FRESH_S` 那段。
        self.last_t: float | None = None
        self.last_sample_ms: int | None = None   # 同一个时刻的整数毫秒
        self.beats = 0            # 累计搏动次数（诊断用）
        # 最近 64 次搏动的**时刻**（诊断用）。有了它才能离线看出"某一拍是漏了还是
        # 数重了" —— 只看间隔的中位数分不出这两种。`_reset_beats` 会清掉。
        self.beat_times: deque[float] = deque(maxlen=64)

        # ---- RMSSD 的 NN 环（整数毫秒，只看**连续**的那一段）----
        # 见 `HR_NN_NEED_MS` 上面那段：连续性的判据是"这一段的起点 == 上一段的
        # 终点"，所以除了环本身还要维护 `nn_span_ms`（滑动和）和 `nn_end_ms`。
        # ⚠️ 跨度**不存时刻**：连续 NN 满足 `t_last − t_first = Σ ibi`，一个滑动和
        #    就够了，存时刻反而多一份要对齐的东西。
        self.nn_ms: deque[int] = deque(maxlen=HR_NN_MAX)
        self.nn_span_ms = 0
        self.nn_seeded = False        # 环里攒的是不是一段"从某拍起连续"的 NN
        self.nn_end_ms = 0            # 这段最后一个 NN 的**终点**（板子钟 ms）
        self.last_beat_ms: int | None = None   # 上一拍的整数 ms（每一拍都推进）

        # ---- PI 的交流窗（带通之后、100 Hz）----
        # ⚠️ 和 `slow` **不是同一个**：`slow` 是抽到 25 Hz、10 秒（频谱兜底用），
        #    这个是 100 Hz、3 秒（PI 用）。两者不通用 —— 用 `slow` 算 PI 的话，
        #    样本数差 4 倍、窗长差 3 倍，交叉校验时和板端对不上还找不着原因。
        self.pi_ac: deque[float] = deque(maxlen=HR_PI_AC_WIN)

        # ---- 频谱兜底的缓冲（见 SPEC_WIN_S 那段注释）----
        # 存的是**带通之后**的样本、且每 SPEC_DECIM 个只留一个。
        # 放带通之后的：对原始 IR 做频谱会被 1/f 漂移压死（和自相关踩过的是同一个坑）。
        self.slow: deque[float] = deque(maxlen=max(1, int(SPEC_WIN_S * fs / SPEC_DECIM)))
        self._n = 0                    # 推进了多少个样本（决定该不该抽一个进 slow）
        # 缓存 (算出来的值, 算它的时刻)。**按时间节流**：state 每秒问好几次，
        # 而一次 DFT 要几十毫秒，不节流就等于白烧 CPU。见 `spec_bpm`。
        self._spec_t = -1e9
        self._spec_v: float | None = None

    # ---- 内部 ----
    def _reset_beats(self):
        """把"攒搏动"这一步清空，滤波器状态一起清（不清的话它自己的历史还在
        往下淌，前几拍照样是脏的）。**唯一调用者是 `SerialHr._feed` 的手指到达
        判据** —— 诊断计数器 `beats` 故意不清，它是"这个 tracker 一共数了多少下"，
        清掉就没法从数上看出来"手指上来之前噪声数了多少"。"""
        self.ibis.clear()
        self.beat_times.clear()
        self.last_beat_t = None
        self.last_ibi_t = None
        self.last_beat_ms = None
        # NN 环一起断：手指上来之前/之后是两个不同的人，跨过这个断点算 NN 差没有意义。
        self._nn_break()
        # PI 的交流窗一起清：里面装的是手指上来之前的空载噪声，留着会让 PI 从
        # 一个偏小（甚至偏大）的值开始爬。清了之后 PI 要 3 秒才回来，如实。
        self.pi_ac.clear()
        for sec in self.bp:
            sec.reset()
        self.env = 0.0
        self.above = False
        # 频谱缓冲一起清：里面装的还是"手指上来之前"的空载噪声、以及直流阶跃
        # 过高通后的那串振铃 —— 留着会让兜底的值从一开始就是错的。
        self.slow.clear()
        self._spec_v = None
        self._spec_t = -1e9

    def push_dc(self, ir: float) -> float:
        """喂一个直流样本，返回最近 1 秒的均值（手指在位判据就用它）。"""
        if len(self.dc_win) == self.dc_win.maxlen:
            self.dc_sum -= self.dc_win[0]
        self.dc_win.append(ir)
        self.dc_sum += ir
        return self.dc_sum / len(self.dc_win)

    def push(self, t_s: float, ir: float, t_ms: int | None = None):
        """喂一个样本。t_s 是板子的 t_ms/1000（秒）。

        `t_ms` 是板子那一列的**整数毫秒**。为什么要单独传而不是从 `t_s` 反算：
        RMSSD 那一路要求两边（PC 与板端）用**同一串整数**做差，反算虽然这里也
        逐位对得上（`round(t_ms/1000*1000)` 的绝对误差 ~1e-10 ms），但那是"靠
        浮点精度够用"，不是"结构上就是整数"—— 后者才不会哪天被人改坏。
        """
        if t_ms is None:
            t_ms = int(round(t_s * 1000.0))
        else:
            t_ms = int(t_ms)
        self.last_t = t_s
        self.last_sample_ms = t_ms
        dc = self.push_dc(ir)
        y = ir - dc
        for sec in self.bp:
            y = sec.push(y)

        # 频谱兜底：每 SPEC_DECIM 个带通样本留一个。**抽取放在带通之后**，
        # 因为带通里已经有一节 3.5 Hz 低通在做抗混叠（25 Hz 的 Nyquist 是 12.5 Hz，
        # 实测抽完的结果和不抽逐位相同，见 runs/_hr_spec.log）。
        self._n += 1
        if self._n % SPEC_DECIM == 0:
            self.slow.append(y)

        # PI 的交流窗：**不抽取、100 Hz 满速**，和板端 `HR_PI_AC_WIN` 一个口径。
        self.pi_ac.append(y)

        # 包络：只往上跟得快、往下衰减慢（标准的峰值保持）
        a = abs(y)
        self.env = a if a > self.env else self.env * ENV_DECAY

        thr = PEAK_FRAC * self.env
        if thr <= 0.0:
            return

        if y > thr:
            if not self.above:
                self.above = True
                self.peak_y = y
                self.peak_t = t_s
                self.peak_ms = t_ms
            elif y > self.peak_y:
                self.peak_y = y
                self.peak_t = t_s
                self.peak_ms = t_ms
        elif self.above:
            self.above = False
            self._register_beat(self.peak_t, self.peak_ms)

    def _register_beat(self, t: float, t_ms: int | None = None):
        if t_ms is None:
            t_ms = int(round(t * 1000.0))
        else:
            t_ms = int(t_ms)
        self.beats += 1
        self.beat_times.append(t)
        if self.last_beat_t is not None:
            ibi = t - self.last_beat_t
            ibi_ms = t_ms - self.last_beat_ms
            # 只有落在生理范围内、且不小于不应期的间隔才算数。
            # 太短的 = 一个波被劈成两个；太长的 = 漏检。
            if MIN_IBI_S <= ibi <= MAX_IBI_S:
                self.ibis.append(ibi)
                self.last_ibi_t = t
                self._nn_push(ibi_ms, t_ms)
            else:
                # ★ 这一拍被判成"漏检或多检"⟹ **连续性到此为止**。
                #   不断开的话，下一个被采纳的间隔会和隔着一个断点的前一个相邻，
                #   两者之差不是 NN 差，RMSSD 会**算错却看着很合理**。
                self._nn_break()
        # ⚠️ 这一行在 `if` **外面**，是刻意的（这一拍是不是有用都算"见到了搏动"），
        #    所以它不能拿来判时效 —— 见 `ibi_fresh`。
        self.last_beat_t = t
        self.last_beat_ms = t_ms

    # ---- NN 环（RMSSD 的输入）----
    def _nn_break(self):
        """把 NN 环清空 ="这一段到此为止"。下一拍会从它自己重新起一段。"""
        self.nn_ms.clear()
        self.nn_span_ms = 0
        self.nn_seeded = False
        self.nn_end_ms = 0

    def _nn_push(self, ibi_ms: int, end_ms: int):
        """把一个**被采纳**的间隔追加进 NN 环。

        连续性用整数精确判：这一段的**起点**（`end_ms − ibi_ms`）必须等于上一段的
        **终点**（`nn_end_ms`）。⚠️ 这个判据在 `_register_beat` 已经把被拒的间隔
        `_nn_break()` 掉之后，正常情况永远成立 —— 留着它是**保险**：连续性一旦漏掉，
        RMSSD 会算错但看着很合理，是这套东西里最难发现的一类错。
        """
        start_ms = end_ms - ibi_ms
        if self.nn_seeded and start_ms != self.nn_end_ms:
            self._nn_break()
        if not self.nn_seeded:
            self.nn_ms.clear()
            self.nn_span_ms = 0
            self.nn_seeded = True
        self.nn_ms.append(ibi_ms)
        self.nn_span_ms += ibi_ms
        self.nn_end_ms = end_ms
        # 只留"刚好过门槛"的那一小段：跨度够了就从头丢，丢到不够为止。
        # **两边（PC 与板端）必须是同一条规则**，否则交叉校验比的是两个不同的量。
        # 好处是窗口有界（最多 HR_NN_MAX 项），而且它跟的是**最近**这 30 秒。
        while len(self.nn_ms) >= 2 and (self.nn_span_ms - self.nn_ms[0]) >= HR_NN_NEED_MS:
            self.nn_span_ms -= self.nn_ms.popleft()

    # ---- 对外 ----
    def ibi_spread(self) -> float | None:
        """
        间隔的**相对离散度** = MAD / 中位间隔。这是"这串间隔像不像一个人的心跳"。

        要它是因为中位数只挡得住**少数**坏间隔：8 个里有 3 个坏照样稳，坏到过半
        就整个跟着错。而"坏到过半"这件事本身是可测的 —— 噪声当搏动时，检出的间隔
        会一半是 T、一半是 T/2，离散度直接翻几倍；真人静息时相邻间隔只差几个百分点
        （呼吸性窦性心律不齐也就 ±5~10%）。

        用 MAD 而不是标准差：**一个离谱的间隔就能把标准差拽走**，而这里要测的正是
        "有没有离谱的间隔"，不能用一个会被它污染的尺子。
        """
        if len(self.ibis) < MIN_BEATS:
            return None
        s = sorted(self.ibis)
        med = s[len(s) // 2]
        if med <= 0.0:
            return None
        mad = sorted(abs(x - med) for x in self.ibis)[len(s) // 2]
        return mad / med

    def ibi_fresh(self) -> bool:
        """这一路最近还出过数吗 —— 最后一个**被采纳**的间隔到现在隔了多久。

        ★ 2026-09-26 加，治「心率不是实时的」。**不要用 `last_beat_t`**：那一拍
        哪怕间隔超范围被丢掉也会推进它，于是"搏动登记了、但没有一个是有效间隔"
        这种情形下它永远显示"新鲜" —— 原来那个 `stale_beats()` 就是这么写的，
        而且从来没被调用过（死代码），一起删了。

        两边都是**样本钟**（`push` 进来的板子时刻），因为要比的是"信号停了多久"，
        不是"墙钟过了多久"。窗见 `IBI_FRESH_S`。
        """
        if self.last_ibi_t is None or self.last_t is None:
            return False
        return (self.last_t - self.last_ibi_t) <= IBI_FRESH_S

    def ac_rms(self) -> float | None:
        """带通之后的**交流 RMS** —— 绝对尺度上的"这里到底有没有在搏动"。

        ★ 2026-09-26 加。为什么非要有它：峰值检波的阈值是 `PEAK_FRAC * env`，
        把自己的尺度归一化掉了，所以**输入只剩噪声它也照样"找到"搏动**
        （`_scratch/_hr_fossil.py` 实测：真人段结束后噪声里一路飘 65~115 BPM，
        从不回 None）。时效管不了这个 —— 噪声确实在不停产生搏动。判据见 `AC_MIN_RMS`。

        取的就是 `slow`（`spec_bpm` 看的同一个缓冲），所以量的是同一件事；
        不足 8 个点（< 0.32 s）时给 None = "还判不了"，调用方不该拿它当"没有搏动"。
        """
        n = len(self.slow)
        if n < 8:
            return None
        m = sum(self.slow) / n
        return math.sqrt(sum((v - m) ** 2 for v in self.slow) / n)

    def dc_mean(self) -> float:
        """最近 1 秒的 IR 均值（手指闸、以及 PI 的分母都用它）。"""
        return (self.dc_sum / len(self.dc_win)) if self.dc_win else 0.0

    def rmssd(self) -> float | None:
        """HRV-RMSSD（**毫秒**）。跨度不到 `HR_NN_NEED_MS` 时给 None。

        ★ 2026-09-26 加。这就是用户要的那个「已稳定 30 秒」的量：`None` 时页面上
        显示 `--` 横杠（`snapshot` 那边把它变成 None，界面照既有规矩显示横杠）。

        口径：**只从连续的那一段 NN 上算**（见 `HR_NN_NEED_MS`），取
        `sqrt(mean(diff(nn)^2))`。整条路零浮点直到最后那个 `sqrt` —— 差的平方和是
        精确整数，所以只要板端用同一串整数毫秒做同样的差，**两边逐位相同**。

        ⚠️ **别把它当疲劳判据**。RMSSD 反映的是**迷走（副交感）张力**：RMSSD 变小
        = 迷走撤退、交感相对占优，**方向与"疲劳/负荷升高"一致**；写成"副交感活跃"
        是反的。而且单靠 RMSSD 判疲劳在文献上**有争议**（受呼吸、体动、个体差异
        影响极大），它只能当**辅助**生理指标。

        ⚠️ **实测的两条后果**（2026-09-26 深夜，`_scratch/_hr_jitter.py` 复算
        `runs/_hr_nn_20260926_205912.txt`，完整记录见 `hr/README.md`）：

        ① **要按住 66 秒才第一次看得到数。** 90 秒的实录里链最长 31.0 秒、断 2 次，
           而**第一次够格是 t=66 秒**。现场按不到一分钟 / 中途动一下就从零攒 ⟹
           屏幕上永远是 `--`。**那是"还没攒够"，不是"算不出来"。**
        ② **这个量对单次异常拍极度敏感。** 那是平方和：实测那个 251.3 ms 里，
           **3 个一阶差分就占了 Σd² 的 91%**，而它们全出自一对 `350→1470`。
           把跨过那一对的三个差分剔掉还剩 **143.3 ms** —— 所以**不是"剔掉一下就
           好了"**，其余那些拍本身也不算干净。**别指望加个过滤器就能救回来。**
        """
        if self.nn_span_ms < HR_NN_NEED_MS:
            return None
        if len(self.nn_ms) < 2:
            return None
        n = len(self.nn_ms)
        s = 0
        for i in range(n - 1):
            d = self.nn_ms[i + 1] - self.nn_ms[i]
            s += d * d
        return math.sqrt(s / (n - 1))

    def nn_span_s(self) -> float:
        """当前连续 NN 跨度（秒）。**给诊断用** —— 它是 RMSSD 出不出数的判据值，
        只看 `--` 分不出"还差 2 秒"和"一直没连起来"。"""
        return self.nn_span_ms / 1000.0

    def perfusion(self) -> float | None:
        """PI（**百分数**，0.12 就是 0.12%）。量不出来给 None。

        `PI = 交流 / 直流 × 100%`：交流是带通之后的 RMS（3 秒窗，`HR_PI_AC_WIN`），
        直流是那个 1 秒均值。口径为什么选 RMS、以及"按压力度缩放三个候选分离度
        恒等"那个坑，见 `HR_PI_AC_WIN` 上面那一大段。

        ⚠️ **名字叫灌注指数，但在这套硬件上它主要量的是按压力度/接触质量。**
        两个都算"好按压"的状态差了 2.4×（dc 99900 → 0.27 / dc 128300 → 0.115），
        差别只来自按的轻重。实测范围、阈值推导和三条警告见 `PI_LOW_PCT`。
        对外讲成"信号/接触质量"可以，讲成"灌注"不行。

        不满 `HR_PI_AC_MIN_N` 个样本时给 None = "还判不了"，**不是"灌注是 0"**。
        """
        dc = self.dc_mean()
        if dc <= 0.0:
            return None
        n = len(self.pi_ac)
        if n < HR_PI_AC_MIN_N:
            return None
        m = sum(self.pi_ac) / n
        ac = math.sqrt(sum((v - m) ** 2 for v in self.pi_ac) / n)
        return ac / dc * 100.0

    def bpm(self) -> float | None:
        """出数 or None。**None 是结论，不是错误** —— 见文件头那段口径。

        三道门，顺序有讲究：**先看输入还在不在（时效）**，再看这串间隔像不像
        心跳（离散度），最后才取中位数。时效必须放最前面 —— 前两道门问的都是
        "这串数好不好"，而化石的问题是"这串数**是老的**"，它再好也是老的。
        """
        if not self.ibi_fresh():
            return None
        if len(self.ibis) < MIN_BEATS:
            return None
        spr = self.ibi_spread()
        if spr is None or spr > MAX_IBI_SPREAD:
            return None
        med = sorted(self.ibis)[len(self.ibis) // 2]
        if med <= 0.0:
            return None
        return 60.0 / med

    def spec_bpm(self) -> float | None:
        """**兜底**：不数波峰了，直接在频域里找脉搏基频。`bpm()` 给 None 时才用它。

        为什么要在频域里找一遍 —— 见 `SPEC_WIN_S` 上面那一大段：峰值法被拒的
        理由（间隔不规整）和"这个率准不准"**不是一回事**，而多检/漏检这两种错
        在频域里都不挪动基频的位置。

        做法：带通后抽到 25 Hz（`self.slow`）→ 减均值 → Hann 窗 → 在
        0.8~2.5 Hz 上按 `SPEC_STEP_HZ` 直接算 DFT → 取最大 → 抛物线插值。
        频率网格只有 680 个点、每点 ~250 次乘加，一次几十毫秒；按 `SPEC_EVERY_S`
        节流之后可以忽略。

        **不做质量判断** —— 兜底的意义就是"主路说不出话时替它说"。什么时候
        连兜底也不给，由调用方（`SerialHr.snapshot`）按手指/时长判。
        """
        now = time.monotonic()
        if self._spec_v is not None and (now - self._spec_t) < SPEC_EVERY_S:
            return self._spec_v

        need = int(SPEC_MIN_S * self.fs / SPEC_DECIM)
        if len(self.slow) < need:
            return None

        seg = list(self.slow)
        n = len(seg)
        m = sum(seg) / n
        # Hann 窗：不加上主瓣两侧的旁瓣会把远处（基线漂移那种）的强分量漏进来
        w = [0.5 - 0.5 * math.cos(2.0 * math.pi * i / (n - 1)) for i in range(n)]
        x = [(seg[i] - m) * w[i] for i in range(n)]

        f_lo, f_hi, df = SPEC_LO_HZ, SPEC_HI_HZ, SPEC_STEP_HZ
        nf = int(round((f_hi - f_lo) / df)) + 1
        mags = [0.0] * nf
        best_k, best_m = 0, -1.0
        for j in range(nf):
            om = 2.0 * math.pi * (f_lo + j * df) / (self.fs / SPEC_DECIM)
            cr, ci = math.cos(om), math.sin(om)
            pr, pi = 1.0, 0.0
            re = im = 0.0
            for v in x:
                re += v * pr
                im += v * pi
                pr, pi = pr * cr - pi * ci, pr * ci + pi * cr
            mg = re * re + im * im
            mags[j] = mg
            if mg > best_m:
                best_m, best_k = mg, j

        if best_k == 0 or best_k == nf - 1:      # 峰落在量程边上 = 不是脉搏
            self._spec_v, self._spec_t = None, now
            return None
        a, b, c = mags[best_k - 1], mags[best_k], mags[best_k + 1]
        den = a - 2.0 * b + c
        off = 0.5 * (a - c) / den if abs(den) > 1e-12 else 0.0
        bpm = 60.0 * (f_lo + (best_k + off) * df)

        # 生理范围之外的不要（和主路的 MIN/MAX_IBI 同一个量程）
        if not (60.0 / MAX_IBI_S <= bpm <= 60.0 / MIN_IBI_S):
            bpm = None
        self._spec_v, self._spec_t = bpm, now
        return bpm

    def diag(self) -> dict:
        """裸量，**只给验收脚本看**（界面上不出现）。

        ★ 2026-09-26 加。起因：`FINGER_DC_MIN = 20000` 这个门槛、以及 LED 电流
        该不该调，验收时**没有地方能看到那两个数**——`snapshot()` 只给结论
        （`finger=off` / `攒心跳中`），看不见"差多少"。手指按上去第一件事就是
        看 IR 直流落在哪、交流幅度有多大，这两个数不露出来，调 LED_PA 就是盲调。

          · `dc`      —— 最近 1 秒 IR 均值。**手指闸的判据就是它**；
          · `env`     —— 幅值包络，约等于当前交流幅度（≈ 血流脉动的峰峰值一半）；
          · `peak_y`  —— 最近一次被登记的波峰高度（带通之后）。
                        手指按得轻 → 这三个数一起变小；按得太死/环境光太强 →
                        dc 顶到几十万。两种都该调 LED_PA 或换个按法。
          · `spread`  —— 质量门的判据值（> MAX_IBI_SPREAD 就不出数）。
          · `ac_rms`  —— 带通后的交流 RMS。**交流下限的判据就是它**（< AC_MIN_RMS
                         = 传感器上没有搏动）。上面那几个是"信号多强"的三种相对
                        尺度，这个是唯一一个**绝对**尺度 —— 只有它能回答
                        "这里到底有没有搏动"，见 `AC_MIN_RMS` 那段。
          · `ibi_age` —— 最后一个有效间隔距今多少秒（样本钟）。主路时效的判据值
                        （> IBI_FRESH_S 就不出数）。**化石就是它顶掉了**：
                        2026-09-26 屏幕上冻住的 119.9 会在这里显示成一个很大的数。
          · `slow`    —— **波形本身**（带通之后、抽取到 25 Hz），最近 SPEC_WIN_S 秒。
                        上面那些都是标量，"这个数是从什么样的一条波上摘下来的"
                        只有波形能回答。实时调试窗口（`_scratch/_hr_live_win.py`）
                        要画的就是它。⚠️ 是抽取后的：25 Hz，不是 100 Hz。
        """
        dc = (self.dc_sum / len(self.dc_win)) if self.dc_win else 0.0
        med = sorted(self.ibis)[len(self.ibis) // 2] if self.ibis else None
        spr = self.ibi_spread()
        m = self.bpm()
        return {
            "dc": round(dc, 1),
            "env": round(self.env, 1),
            "peak_y": round(self.peak_y, 1),
            "beats": self.beats,
            "n_ibi": len(self.ibis),
            "ibi_med_s": (round(med, 4) if med else None),
            "spread": (round(spr, 4) if spr is not None else None),
            # ★ 2026-09-26 加：兜底那条路的裸量。验收时要能分清屏幕上那个数是
            #   "主路给的"还是"频谱给的" —— 两者混在一起而看不见来源的话，
            #   "兜底在救命"和"兜底在瞎报"在界面上长得一模一样。
            "spec_bpm": self.spec_bpm(),
            "spec_n": len(self.slow),
            # ★ 2026-09-26 加：波形本身（`spec_n` 是同一个缓冲的长度）。
            #   实时调试窗口要画的是它，见 docstring 里 `slow` 那条。
            "slow": [round(v, 1) for v in self.slow],
            # ★ 2026-09-26 加：交流下限与主路时效各自的**判据值**（不是结论）。
            #   和上面 `dc`/`spread` 一个道理 —— 只报结论看不见"差多少"。
            "ac_rms": (lambda v: round(v, 1) if v is not None else None)(self.ac_rms()),
            "ibi_fresh": self.ibi_fresh(),
            "ibi_age": ((round(self.last_t - self.last_ibi_t, 3)
                         if (self.last_t is not None and self.last_ibi_t is not None)
                         else None)),
            # 主路（过了质量闸的）原值。屏幕上那个数是谁给的靠这两个字段判：
            #   main_bpm 有值        → 主路给的
            #   main_bpm None 而 spec 有值 → 兜底撑的
            # ⚠️ 必须**各算一次**存下来，不能让 `snapshot()` 那边自己再判一遍 ——
            #    两次调用之间闸的状态可能已经变了，会出现"用兜底出的数、却记成主路"。
            "main_bpm": m,
            # ★ 2026-09-26 加：**间隔本身**，不只是中位数。
            #   为什么：中位数 1.2 s 有两个来路 —— "这个人心率就是 50" 和 "每两拍
            #   漏一拍（真值 100）"，中位数**长得一样**。看列表才分得开：漏拍是
            #   T/2T 交替，本来就慢是全都一样长。`beat_times` 比 `ibis` 多留了
            #   被范围闸拒掉的间隔，连"拒了哪些"都看得见。
            "ibis": [round(x, 3) for x in self.ibis],
            "beat_times": [round(t, 3) for t in self.beat_times],
            # ★ 2026-09-26 加：RMSSD 那一组的裸量与**判据值**。
            #    `nn_span_s` 是"出不出数"的判据值 —— 只看页面上那个 `--` 分不出
            #    "还差 2 秒"和"从来就没连起来过"，而这两件事的处置完全不同
            #    （前者等着就行，后者要去治信号质量）。
            "rmssd": (lambda v: round(v, 1) if v is not None else None)(self.rmssd()),
            "nn_span_s": round(self.nn_span_s(), 3),
            "nn_n": len(self.nn_ms),
            "nn_ms": list(self.nn_ms),
            # ★ 2026-09-26 加：PI。`pi_ac_n` 同理是"够不够算"的判据值。
            "pi": (lambda v: round(v, 4) if v is not None else None)(self.perfusion()),
            "pi_ac_n": len(self.pi_ac),
        }


# ============================================================================
# 串口读线程
# ============================================================================
class SerialHr:
    """
    守护线程读串口 + 逐样本推进算法。`snapshot()` 是给 UI 取数的唯一入口。

    ⚠️ 串口是**独占设备**（和摄像头一样）。用户开着串口助手/PortHelper 的时候
    本模块打不开，这时它不抛异常、只在 `error` 里留一句话并每 `REOPEN_S` 秒重试
    —— 关掉那个助手之后会自己回来，不需要重启 UI。
    """

    def __init__(self, port: str | None = None, baud: int = BAUD, enabled: bool = True):
        self.port_want = port or "auto"
        self.baud = baud
        self.enabled = enabled

        self.port: str | None = None
        self.error: str = "" if enabled else "未启用"
        self.lines = 0
        self.bad_lines = 0
        self.last_rx: float | None = None      # time.monotonic()
        self.last_t_ms: int | None = None
        self.finger: str = "unknown"           # on / off / unknown
        self.board_errors: list[str] = []
        # ★ 2026-09-26：「数据详情」页要看的**板子原始行**。这是本模块第一次
        #   留下原始行本身 —— `_handle()` 原来把行 strip 完就扔，
        #   `board_errors` 只留最后 20 条 `E`，`D` 行一个字都不留。
        self.log_lines: list[str] = []
        self.h_lines = 0                       # 板端自己算的那一行收了几条
        self._d_sec: int | None = None         # `D` 行抽样用：上一次记下的板子秒

        self._tracker = _HrTracker()
        self._settle_left = 0                  # 手指刚上来之后的"静默样本"还差几个
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._th = threading.Thread(target=self._run, name="serial-hr", daemon=True)

    # ---- 生命周期 ----
    def start(self):
        if self.enabled and not self._th.is_alive():
            self._th.start()

    def close(self):
        self._stop.set()

    # ---- 取数 ----
    def snapshot(self) -> dict:
        """(hr, finger, note, ac, rmssd, pi, pi_hint) 一次给全。

        `hr` / `ac` / `rmssd` / `pi` 为 None 时界面显示 `--`（照 `ui/state.py`
        那条"量不出来就给 None，绝不拿上一次的数凑"）。

        ★ 2026-09-26 深夜加 `ac`（= `_HrTracker.ac_rms()`，带通后的交流 RMS）。
        它替掉界面上的 `rmssd` 那一格：RMSSD 要 NN 连续跨度 ≥ 30 秒才有值，
        实测那场会话里 **0.0% 的帧有数**（`runs/_hr_live_20260926_223242.log`），
        屏幕上永远是一根横杠 —— 用户的原话是「换个一直有的」，这个是 **100%**
        （同一场日志里 `pi` 100%、`beats` 100%、`dc` 100%）。选它没选 `beats`/`dc`
        的理由：`ac_rms` 和心率**独立**（r=−0.20），与 PI 只是中度相关（r=+0.55，
        PI 就是它除以直流），换上去不重复已有两格的含义。

        ⚠️ `rmssd` 这个键**留着**（不删）：实时窗口 `_scratch/_hr_live_win.py`
        的 `S` 行日志一直记着它，那条诊断线索比页面上那一格值钱。只是界面上
        不再有它的位置。

        ⚠️ `rmssd` / `pi` **只在"这一路是活的"那几个出口才有值**。这条不是顺手
        加的：`ibi_fresh`/`AC_MIN_RMS` 两道门当初就是为了消灭「屏幕上冻着一个
        不动的数」才加的，如果 RMSSD 在串口停了/手指拿开了之后还照报上一段的值，
        等于把化石从心率那一格搬到 RMSSD 这一格 —— 同一只虫子换个房间而已。
        """
        with self._lock:
            tr = self._tracker

            def out(hr, finger, note, live=False):
                """**所有出口都走它**。新加的三个键在每个出口都得一致，散着写
                六份迟早漏掉一个 —— 而漏掉的那个出口在页面上就是"这一格凭空没了"，
                现场没人能当场看出是哪一种。`live=False` 的那几个出口（没启用/
                没数据/串口停/手指不在）一律不给 RMSSD 和 PI，理由见 docstring。"""
                if not live:
                    return {"hr": hr, "finger": finger, "note": note, "ac": None,
                            "rmssd": None, "pi": None, "pi_hint": ""}
                pi = tr.perfusion()
                # 文案**由服务端给**：三个 .html/.js 里不出现这句中文，
                # 否则"界面只留标签和数字"那条红线的审计口径就破了。
                hint = PI_HINT if (pi is not None and pi < PI_LOW_PCT) else ""
                return {"hr": hr, "finger": finger, "note": note,
                        "ac": tr.ac_rms(), "rmssd": tr.rmssd(),
                        "pi": pi, "pi_hint": hint}

            if not self.enabled:
                return out(None, "unknown", self.error)
            if self.last_rx is None:
                return out(None, "unknown", self.error or "串口无数据")
            age = time.monotonic() - self.last_rx
            if age > STALE_S:
                return out(None, "unknown", "串口停了 %.1fs" % age)
            if tr.dc_win and (tr.dc_sum / len(tr.dc_win)) < FINGER_DC_MIN:
                return out(None, "off", "")
            # 主路（峰值 + 中位 + 质量闸 + 时效）能用就用它 —— 它更灵敏，而且它拒掉的
            # 那些段里确实有的是真没救（合成"运动 3×"档频谱会自信地报错、主路正确地拒）。
            bpm = tr.bpm()
            if bpm is None:
                # 主路说不出话 → 频域兜底。兜底**不做质量判断**是刻意的（它的意义
                # 就是替主路说话），所以下面那道交流下限对两条路**一起**卡。
                bpm = tr.spec_bpm()
            # ★ 最后一道，卡的是"传感器上到底有没有在搏动"。放在**出口**而不是两条路
            #   里面：它是信号级的事实，和用哪条路估无关；而且缓冲还没攒够（ac 是
            #   None）时不否决，免得手指刚按上就报「没搏动」。
            ac = tr.ac_rms()
            no_pulse = ac is not None and ac < AC_MIN_RMS
            if bpm is not None:
                if no_pulse:
                    return out(None, "on", "没搏动", live=True)
                return out(round(bpm, 1), "on", "", live=True)
            if no_pulse:
                # 两条路都说不出话，但"没搏动"是量出来的事实，比「攒心跳中」准。
                # **PI 照样给** —— 它正是"信号质量"那个指标，这时候最该看见它。
                return out(None, "on", "没搏动", live=True)
            # **不给「攒心跳中」以外的任何提示文字**（界面只留标签和数字）。
            return out(None, "on", "攒心跳中", live=True)

    def info(self) -> dict:
        with self._lock:
            return {"port": self.port, "error": self.error,
                    "lines": self.lines, "bad": self.bad_lines,
                    "finger": self.finger, "beats": self._tracker.beats}

    def raw_lines(self) -> list[str]:
        """最近那几行板子原文，给「数据详情」页。

        `H` 行**每条全留**（1 Hz，一行就是心率 / RMSSD / PI 三列 —— 用户点名的
        "心率串口输出的那几列"）；`D` 行**每秒抽 1 行**（100 Hz 的原始计数流
        攒满一屏只要 4 秒，对人没有信息量；留一个是为了让"板子还在按 10 ms
        一个样本地吐"这件事看得见）。
        """
        with self._lock:
            return list(self.log_lines)

    def diag(self) -> dict:
        """裸量（直流/幅度/离散度），给验收脚本用。见 `_HrTracker.diag`。"""
        with self._lock:
            d = self._tracker.diag()
            d["finger"] = self.finger
            return d

    # ---- 线程 ----
    def _run(self):
        try:
            import serial                     # pyserial，requirements.txt 里已有
            from serial.tools import list_ports
        except ImportError as e:              # pragma: no cover
            with self._lock:
                self.error = "没装 pyserial（%s）" % e
            return

        while not self._stop.is_set():
            port = self._pick_port(list_ports)
            if not port:
                with self._lock:
                    self.error = "没找到 FT2232 串口（板子没插？）"
                self._stop.wait(REOPEN_S)
                continue
            try:
                ser = serial.Serial(port, self.baud, timeout=0.2)
            except Exception as e:
                # 最常见的一种：用户自己开着串口助手占着这个口（独占）
                with self._lock:
                    self.error = "%s 打不开：%s" % (port, e)
                self._stop.wait(REOPEN_S)
                continue

            with self._lock:
                self.port, self.error = port, ""
            try:
                self._read_loop(ser)
            except Exception as e:
                with self._lock:
                    self.error = "读串口断了：%s" % e
            finally:
                try:
                    ser.close()
                except Exception:
                    pass
            if not self._stop.is_set():
                self._stop.wait(REOPEN_S)

    def _pick_port(self, list_ports) -> str | None:
        if self.port_want and self.port_want != "auto":
            return self.port_want
        # 认 VID:PID 而不是 COM 号：COM 号会随插拔变，写死迟早变成"打不开"。
        # 0x0403:0x6010 = FT2232H，HPM5300EVK 板载调试器，channel B 就是这个 console 口。
        for p in list_ports.comports():
            if p.vid == 0x0403 and p.pid == 0x6010:
                return p.device
        return None

    def _read_loop(self, ser):
        while not self._stop.is_set():
            raw = ser.readline()
            if not raw:
                continue
            try:
                line = raw.decode("ascii", "replace").strip()
            except Exception:
                continue
            if not line:
                continue
            with self._lock:
                self.lines += 1
                self.last_rx = time.monotonic()
            self._handle(line)

    def _handle(self, line: str):
        if line[0] == "D":
            f = line.split(",")
            if len(f) != 4:
                with self._lock:
                    self.bad_lines += 1
                return
            try:
                t_ms, red, ir = int(f[1]), int(f[2]), int(f[3])
            except ValueError:
                with self._lock:
                    self.bad_lines += 1
                return
            self._feed(t_ms, ir)
            # 抽样记原文。按**板子的样本钟**分秒，不是"每收 100 行丢 99 行"：
            # 掉线一段再回来时墙上过了几秒而板子钟只走了几十毫秒，按行数抽会把
            # 刚回来的那一段整个抽没 —— 而那一段恰恰是最该看的。
            self._log_raw(line, sec=t_ms // 1000)
        elif line[0] == "H":
            # ★ 板端自己算的那一行（`H,<t_ms>,<hr>,<rmssd>,<pi>`，1 Hz）。
            #   ⚠️ 页面上的三个数**不看它**，只认本模块算的那一份（口径见
            #   `hr/README.md`）；它在这里的用处是「数据详情」页的原始行，
            #   以及验收 4.4 把两边并排打出来比。
            #   ⚠️ 老版 `_handle` 只认 `D`/`E`，`H` 会落进最后那条"只计数"的
            #   注释分支 —— **不进 `bad_lines`**（那是 `D` 分支内部的判据，不是
            #   靠 `line[0]` 拦的），但也不会被任何地方看见。
            with self._lock:
                self.h_lines += 1
            self._log_raw(line)
        elif line[0] == "E":
            # 板子报的错（芯片没答话 / FIFO 溢出 / I2C 读失败）——留在日志里，
            # 页面上不出，见文件头"不写解释文字"。
            with self._lock:
                self.board_errors.append(line)
                del self.board_errors[:-20]
        # '#' 开头的横幅/配置行：只计数，不显示

    def _log_raw(self, line: str, sec: int | None = None):
        """往原始行环里放一行（环封顶 `LOG_MAX`，满了丢最老的）。

        `sec is None` ⟹ 不抽样（`H` 行全留）；给了 `sec` ⟹ 同一个 `sec` 只留第一行
        —— 调用方传的是 `t_ms // 1000`，所以这是"板子的每一秒留一行"。
        """
        with self._lock:
            if sec is not None:
                if sec == self._d_sec:
                    return
                self._d_sec = sec
            self.log_lines.append(line)
            del self.log_lines[:-LOG_MAX]

    def _feed(self, t_ms: int, ir: int):
        with self._lock:
            if self.last_t_ms is not None and t_ms < self.last_t_ms - 1000:
                # 板子复位了（t_ms 回到 0）。**清空重来** —— 不复位的话
                # 复位前后两个时刻会算出一个负的间隔，中位数被它带偏。
                self._tracker = _HrTracker()
                self._settle_left = 0     # 整个换了个新 tracker，静默计数跟着归零
                self.board_errors.append("板子复位，心率重新计时")
                del self.board_errors[:-20]
                self.last_t_ms = None
            self.last_t_ms = t_ms

            tr = self._tracker
            was_on = self.finger == "on"
            # 第三个参数是**整数毫秒**：RMSSD 那一路两边（PC 与板端）必须用同一串
            # 整数做差才可能逐位一致，见 `_HrTracker.push` 的 docstring。
            tr.push(t_ms / 1000.0, float(ir), t_ms)
            dc = (tr.dc_sum / len(tr.dc_win)) if tr.dc_win else 0.0
            self.finger = "on" if dc >= FINGER_DC_MIN else "off"

            # 手指从"不在位"到"在位"的那一刻，算法状态是脏的，而且脏得刚好落在
            # 数字第一次出现的那一瞬间 —— 两处：
            #   · 空载时（IR ≈ 8450）噪声也会过阈值，攒下的"搏动"正躺在那 8 个
            #     间隔的窗口里，前几拍的数字就是它们算出来的；
            #   · 手指一按，直流从 8450 跳到 12 万，这个阶跃过 4 阶高通是一串振铃，
            #     它的第一个鼓包会被登记成一次搏动。
            # 所以：先等直流窗整个换成手指样本（≈1 s，阶跃走到窗尾就没了），
            # 再把搏动历史清空重来。**只有真正的 off→on 才清** —— 中途按松一点
            # 导致 finger 抖一下不值得把已经攒好的数字丢掉。
            if self.finger == "on":
                if not was_on:
                    self._settle_left = tr.dc_win.maxlen
                if self._settle_left > 0:
                    self._settle_left -= 1
                    if self._settle_left == 0:
                        tr._reset_beats()
            else:
                self._settle_left = 0


# ============================================================================
# 与 UI 的接缝
# ============================================================================
def make_hr_reader(cfg: dict | None) -> SerialHr:
    """
    按 config.json 的 `serial_hr` 段建一个读数器。**永远返回一个对象**：
    没配、配错、串口不在，都在对象内部表现为 `enabled=False` 或 `error` 里的一句话
    —— 心跳这一路坏掉不该让整个界面起不来。
    """
    sec = (cfg or {}).get("serial_hr") or {}
    enabled = bool(sec.get("enabled", True))
    dev = SerialHr(port=sec.get("port"), baud=int(sec.get("baud", BAUD)),
                   enabled=enabled)
    dev.start()
    # 开串口是读线程干的，而启动横幅紧接着就要问 `info()['port']` —— 不等一下的话
    # 存在一个几十毫秒的窗口，横幅会把"还没来得及"打成"没找到串口"，用户就会去
    # 拔插一遍板子。**有界等待**：最多 0.5 s，等不到就照实说没打开，不在这儿死等。
    t0 = time.monotonic()
    while time.monotonic() - t0 < 0.5 and dev.port is None and not dev.error:
        time.sleep(0.02)
    return dev


def apply_to_state(hr: SerialHr, st) -> None:
    """
    把心跳这一路的量贴到这一帧的 State 上。

    `ui/state.py` 的 `derive()` 不碰这几个字段，而 `to_json()` 是 `asdict()`
    —— 所以**WS 通道一行都不用改**，加字段自动就进帧了。

    ⚠️ 这里原本**只写 `st.hr` 一个字段**，而 `snapshot()` 早就在产 `finger`/`note`
    两个键、被这一行整个丢掉了。不是 bug（那两个键当时没有消费方），但它是这次
    新字段最容易重蹈的坑：snapshot 给了、这里忘了接，症状是"页面那一格永远是 --"。
    """
    snap = hr.snapshot()
    st.hr = snap["hr"]
    st.hr_ac = snap["ac"]
    st.hr_rmssd = snap["rmssd"]
    st.hr_pi = snap["pi"]
    st.hr_pi_hint = snap["pi_hint"]
    # ★ 2026-09-26 补：`finger` **接上了**。下面原来那句"`finger` 目前也没有消费方"
    #   在写下的一刻是对的，但同一天晚些时候 `ui/web/live.js` 的 `XQ.hrText`
    #   开始读 `s.hr_finger` 来分三档文案 —— **那句话就此过期，而没人回头改它**，
    #   这正是用户那条「手指拿开了还写未接入」的成因。注释会过期这件事本身
    #   没法根治，但"新增读 `s.xxx` 的地方要同步那张键表"可以（见下面的检查）。
    st.hr_finger = snap["finger"]
    # ⚠️ `note` 仍然**有意不接**：它就是被红线禁掉的"解释文字"（"攒心跳中"/
    #    "没搏动"），塞进 State 等于给了它一条上屏幕的路。这一条原判断没问题。
