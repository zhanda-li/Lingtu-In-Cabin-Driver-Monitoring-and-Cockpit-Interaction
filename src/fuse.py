"""融合主程序：支路一（骨骼姿态）× 支路二（面部）同进程跑，按闸门合成一个预警级别。

── 为什么要融合，而不是拿支路二替掉支路一 ──────────────────────────
两条支路看的是**不同的东西**，各自都有对方没有的盲区：

    支路一  骨骼 33 点 → 45 帧窗口 → Transformer → 4 类 → L0~L3
            测**姿态周期性**（疲劳 = pitch 前倾-回弹）。看不见眼睛，
            所以"头还立着、眼睛已经在闭"这个阶段它没有证据 —— 实测那一段
            的峰值只有 0.64（`docs/技术方案.md` 的延迟分析）。
    支路二  FaceMesh → EAR/MAR/头姿 → 3 统计量 → 逻辑回归 → P(fatigue)
            测**眼睑闭合**。看不见分心，而且**疲劳时脸会丢**
            （fatigue 片段人脸检出中位仅 80.3%，见 `src/face.py` 开头）。

于是分工是：**分心交给支路一，闭眼交给支路二**，重叠时以支路一为准。

── 闸门：支路二只在支路一判"正视前方"时才投票 ──────────────────────
这是整个融合的核心设计。理由是一条实测：**扭头/低头时 EAR 会被头姿污染**，
离线跨片段 r(EAR_norm, pitch) = −0.56、r(PERCLOS, 头动范围) = +0.61；
而 2026-09-23 那场真人会话里，把"头不动且在中位姿态"的窗挑出来后
两个相关降到 +0.02 / +0.03 —— 污染是真的，而且**筛掉之后就干净了**。
所以：

    gate = argmax(b1.ema) == "normal"  且  b1.ema["normal"] >= GATE_MIN

`GATE_MIN = 1 - EXIT_TH = 0.60`，不是随手取的数：四类 EMA 和为 1 且各项非负，
所以 `ema["normal"] >= 0.60` 等价于「其余三类**每一个**都 <= 0.40 = EXIT_TH」。
即 —— **闸门开 ⟺ 支路一对任何非正常类的证据都低于它自己的退出阈值。**
（若取 0.40，闸门开着时某个非正常类可以高到 0.60，而那已经是支路一的
ENTER_TH，等于支路一在喊注意了却还让支路二投票。）

⚠️ 闸门关闭时**不往 FaceBranch 里写帧**，并且 `clear()` 掉已有缓冲。
不这么做的话，扭头期间那些被污染的 EAR 会留在窗口里，闸门一重开就立刻误报。
重开后必须重新攒满 HIST_SEC 秒才喂模型，屏上显示 `WARMING`。

── 融合规则 ────────────────────────────────────────────────────────
    L_fused = max(L1, min(L2, 2))          # 支路二封顶 L2，见 ScalarState
    L_fused = max(L_fused, 1 if 哈欠 else 0)   # 哈欠是规则，不进逻辑回归

**支路二封顶 L2**：L3 在本项目里是"疲劳驾驶"的终局判定，由支路一的姿态
周期性给出，那是过了 24 段四类数据验证的通路；支路二只有 5+5 段自己录的
标定集，证据量级不够撑起"紧急"。支路一照旧能到 L3。

**哈欠不进逻辑回归**：训练集只有 normal/glance/phone/fatigue 四组，
yawn/talking/yawn_open 从不进 LR，所以 `yawn` 那一列在 96 段训练片段上
恒等于 0、系数必然 0.000（`tools/ablate_feats.py` 实测：4 特征与 3 特征
平衡准确率完全同为 65.7%、错判同一批 21 段）。那是**常数**，不是**没用**。
标定记录与结论见 `src/face.py` 的 `YAWN_THR` 与 `tools/calib_yawn.py`。

── 用法 ────────────────────────────────────────────────────────────
    python src/fuse.py                      # 摄像头实时
    python src/fuse.py --replay a.mp4       # 回放（与摄像头同一条推理路径）
    python src/fuse.py --no-face            # 只跑支路一 = 逐帧复现 src/live.py
    python src/fuse.py --selftest a.mp4     # 两个 landmarker 的性能门禁
    python src/fuse.py --face-hz 7          # 面部降频（性能不够时的退路 A）

**空格 = 标记**（toggle）。标的是操作者的真值："我现在闭着眼、头没动。"
它不进任何判据，只写进 `--log-probs` 的 CSV，外加终端打一行时间。
用途只有一个：`tools/analyze_fuse_l4.py` 靠它判"支路二测的是眼睛还是头动" ——
那是支路二唯一验不了、只能靠真人的一条（离线片段全都短于 HIST_SEC，
见 `runs/fuse_replay_full.txt` 的自述）。

★ **2026-09-26 起闸门不再清缓冲**（原来这里写着"闸门一关 `fb.clear()`，支路二
27 秒热身全部清零"）。现在的规则是：**一直采集，闸门只决定投不投票**。所以
L4 会话里扭头/低头一次**不再**作废前面的热身 —— 倒计时要按墙上时钟读，
不要再按"上一次闸门关闭"去数。

⚠️ `--no-face` 不是调试开关而是**回归工具**：它把支路二整条路摘掉，
此时本脚本应当与 `src/live.py` 逐帧一致。L2 回归就靠它证明"支路一没被改坏"。

⚠️ `main()` 的最后一行必须是 `os._exit(0)`。这里现在有**两个** mediapipe
landmarker 实例，各自析构固定 42 秒 —— 漏掉就是退出时干等 84 秒。
"""

import argparse
import collections
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import config as C
from face import (BLINK_THR, CLOSE_EYE_SEC, FEATURE_NAMES, HEAD_DEG, HEAD_WIN,
                  HIST_SEC, ROLL_WIN, WIN_SEC, YAWN_MIN, YAWN_THR, FaceBranch,
                  FaceExtractor, HeadMotion, close_eye_seconds, feature_vector,
                  norm_by_time, yawn_seconds)
from live import (CLASS_LEVEL, DECIDE_HZ, EMA_ALPHA, ENTER_SEC, ENTER_TH,
                  EXIT_SEC, EXIT_TH, LEVEL_BLINK, LEVEL_CN, LEVEL_COLOR,
                  LEVEL_NOTE, SPEAK_FROM, VOICE_COOLDOWN, CameraSource,
                  Hysteresis, LightOutput, OnlineNormalizer, TTSWorker,
                  VideoSource, WarningState, draw_hud_offset, find_model,
                  load_infer_model)
from pose import PoseExtractor
from record import GREEN, RED, WHITE, YELLOW, draw_hud, draw_pose

# ── 闸门 ────────────────────────────────────────────────────────────
NORMAL_I = list(C.CLASSES).index("normal")
# 见模块开头：这是推导出来的，不是拍的。改 EXIT_TH 它跟着走。
GATE_MIN = 1.0 - EXIT_TH

# ── 支路二自己的迟滞 ────────────────────────────────────────────────
# 与 live 的迟滞体系同量级，但放宽了 enter_sec：支路二每帧出一个概率，
# 而它的出数节奏是决策节奏（10 Hz）而不是帧率，不需要 live 那么快的响应。
# ⚠️ B2_ENTER2 是**设计选择，不是标定结果** —— 支路二没有"L1/L2 各该是
# 多少概率"的标注数据（只有疲劳/非疲劳两类）。取 ENTER_TH + 0.25 的意思是
# "升 L2 要的证据比升 L1 多 0.25"，EXIT2 取 ENTER_TH 即"掉到 L1 的入门线才降"。
# 这四个数**必须在真人会话里调**（就是 live.py 那句老话：模型在录制数据上
# 峰值 0.9，在活人身上可能只有 0.6），所以全部开了命令行开关。
B2_ENTER = 0.60
B2_ENTER2 = 0.85
B2_EXIT = 0.40
B2_EXIT2 = 0.60
B2_ENTER_SEC = 0.5
B2_EXIT_SEC = 1.5
B2_MAX_LEVEL = 2         # 封顶。见模块开头。

# ── 哈欠 ────────────────────────────────────────────────────────────
YAWN_HOLD = 5.0          # 哈欠事件短，抬到 L1 后保持几秒才看得见
YAWN_ACTION = "level"    # "level" = 抬到 L1（标定成功，tools/calib_yawn.py）
                         # "display" = 只显示 + 只写日志，不动级别（兜底）
# 哈欠在 L1 也出声。SPEAK_FROM=2 是为了挡"偶尔瞟一眼后视镜"（live.py:64），
# 而哈欠是真实疲劳征兆、不是瞟一眼，压着不出声反而丢掉了最有用的那条提示。
# 仍然受同一个 VOICE_COOLDOWN 约束：哈欠保持 5 s、冷却 6 s，一次哈欠最多念一句。
SPEAK_FROM_YAWN = 1

# ── 持续闭眼 / 低头点头：两条**规则**，都不进逻辑回归 ────────────────
# 2026-09-26 用户拍板加的，起因是同一句话的两个方向：
#   「支路二 在我低一点头的时候应该也可以看见我的眼啊 这些都要一直采集着啊
#     我打开摄像头就应该开始采集了啊而不是等十几秒」
#   「点头低头 为啥有时候不报 还报我健康」「只要我低头就应该报」
#
# 结构上的原因：`l2` 要等 `fb.full()`（27 秒）才有值，而**支路一只会给 L0 或 L3**
# （`live.CLASS_LEVEL = {normal: 0, fatigue: 3}`）—— 于是开机后那 27 秒里屏幕上
# 只可能是「清醒」或「重度」，中间两档**结构上到不了**。规则就是补这一段的：
#   · 闭眼规则：最早第 ROLL_WIN + 一点 ≈ 11 秒响（基线要 10 秒，这段不能省 —— 见
#     `face.CLOSE_EYE_SEC` 的注释；拆掉 ROLL_WIN 会让 p75 被闭眼自己拽塌）
#   · 低头规则：**不需要基线**，`HEAD_WIN`(2 秒) 就能响 —— 量过最早 1.8 秒
#
# ⚠️ 两条都**不看闸门**：闸门是"支路一是否判非正常"，而闭合眼/低头**恰恰会**让它
#   关上 —— 挂在闸门上等于让规则在被触发的那一刻失效。哈欠规则当初就是这个道理
#   （见下面哈欠规则那段的注释）。
EYE_HOLD = 3.0           # 闭眼是持续状态，抬级后保持几秒
EYE_LEVEL = 2            # 抬到 L2 —— 正好是 B2_MAX_LEVEL，不越支路二自己的顶
HEAD_HOLD = 0.0          # ★ **0 = 不锁存**（2026-09-26 第四次，用户原话「不要锁存」）。
                         #   判据怎么判就怎么报：`head_swing >= HEAD_DEG` 那一拍抬到 L3，
                         #   下一拍掉回 10° 以下就**当场摘掉**，不再"再保持 N 秒"。
                         #   ★ 为什么可以不要它：锁存当初是为了"别闪"，可判据自己**已经**
                         #     带 2 秒记忆（`HEAD_WIN` 的 p95）—— 回正后它自己要走 ≈2 秒
                         #     才落下来。那 2 秒就是自然拖尾，锁存叠在上面**全是多报**。
                         #     实测这 5 秒有多贵（`runs/session9.csv`，真人一场）：
                         #       低头1 回平视 t=16.57 → 判据 t≈16.2 已 < 10（松了），
                         #             屏幕上的 L3 却挂到 t=21.85 —— **多报 5.3 秒**；
                         #       低头2 回平视 t=44.54 → 挂到 t=47.68 —— **多报 3.1 秒**。
                         #     用户第二次报延迟的原话就是「我低头回正后还有很长一段时间
                         #     报重度疲劳」—— 这一条是它的**主因**，不是支路二。
                         #   ⚠️ 只把这个数写成 0.0、**不动下面那段代码，是个陷阱**：
                         #     `head_until = mt + 0` 之后 `mt < head_until` **恒为假**，
                         #     规则会**整条哑掉**（不是"变快"，是再也不报）。所以
                         #     `:739` 那段里 `head_hold <= 0` 走的是**另一条支**（纯跟随）。
                         #     改这个数之前先读那段。
                         #   ⚠️ 上游还有一条，同一天一起修的：判据自己**不能**在持续
                         #     低头里松掉（`face.head_ref` 的短窗项被低头拖动）。锁存
                         #     去了之后，"判据自己撑得住"就成了唯一的防线 —— 两条
                         #     是一件事的两半，别只改一条。
                         #   ⚠️ 没锁存了，`l_head` 会跟着 `h_swing` 在阈值附近抖。
                         #     这是**有意的**：屏幕上那个级别的抖动由下游
                         #     `WarningState`(ENTER_SEC/EXIT_SEC) 兜住，而"多报 5 秒"
                         #     是它兜不住的。
HEAD_LEVEL = 3           # ★ **故意**给出 B2_MAX_LEVEL 以上的级别，理由：
#   `B2_MAX_LEVEL` 封的是**支路二的逻辑回归**（只有两类标注、证据弱，不该单独顶格）；
#   而低头/点头是用户点名的重度征兆（「重度疲劳就是点头 低头 头部倾倒这些」），
#   并且他明确要求「12° 就报」「报警」。这是**产品口径**，不是模型的能力上限。
#   闭眼只给 L2、低头给 L3，差别就在这里 —— 不是随手定的。

# 语音**按来源分文案**。live.LEVEL_NOTE[2] 是"检测到持续低头看手机" ——
# 级别若是支路二抬上来的（持续闭眼），念那句就是错的。
NOTE_FACE = {1: "检测到持续闭眼", 2: "检测到持续闭眼，疲劳征兆"}
NOTE_YAWN = {1: "检测到打哈欠"}
# 低头/点头规则（见下面 EYE_*/HEAD_* 那段）。只在 L3 出声 —— 它是重度征兆。
NOTE_HEAD = {3: "检测到持续低头，请注意"}


class ScalarState:
    """标量概率 → 级别（0~cap）。与 `WarningState` 同构，但只盯一个量。

    为什么不复用 `WarningState`：那个是**多类**的，判级别靠 `target_level`
    扫 4 个类别取最大；支路二只有一个概率（P(fatigue)），套进去要点
    假造 3 个恒 0 的类，比写这 40 行更难读。

    两级同一套迟滞逻辑（进入用 enter、已在级上用 exit、再叠时间迟滞），
    所以"抖动 → 级别乱翻"这件事和支路一是同一个解法。
    """

    def __init__(self, enter=B2_ENTER, enter2=B2_ENTER2, exit1=B2_EXIT,
                 exit2=B2_EXIT2, enter_sec=B2_ENTER_SEC, exit_sec=B2_EXIT_SEC,
                 cap=B2_MAX_LEVEL):
        self.enter, self.enter2 = float(enter), float(enter2)
        self.exit1, self.exit2 = float(exit1), float(exit2)
        self.enter_sec, self.exit_sec = float(enter_sec), float(exit_sec)
        self.cap = int(cap)
        self.level = 0
        self._pend, self._pend_t = -1, 0.0

    def target(self, p):
        t = 0
        for lv, (e, x) in enumerate(((self.enter, self.exit1),
                                     (self.enter2, self.exit2)), start=1):
            if lv > self.cap:
                break
            th = x if lv <= self.level else e
            if p > th:
                t = max(t, lv)
        return t

    def update(self, p, now):
        tgt = self.target(p)
        if tgt == self.level:
            self._pend = -1
            return self.level
        if tgt != self._pend:               # 换了目标，计时重来
            self._pend, self._pend_t = tgt, now
            return self.level
        need = self.enter_sec if tgt > self.level else self.exit_sec
        if now - self._pend_t < need:
            return self.level
        self.level = tgt
        self._pend = -1
        return self.level

    def reset(self):
        """闸门关闭时立即归零，**不保持**。闸门关 = 支路一的证据说人在
        扭头/低头，此时支路二的输入是污染的，它之前那点"闭眼"结论
        也就没有立足之地了。"""
        self.level, self._pend = 0, -1


# ---------------------------------------------------------------- 画
def panel(img, lines, x, y, fs=0.58, lh=26):
    """半透明底 + 多行文字，画在 (x, y)。

    从 `_scratch/live_face.py:264` 抄来的：那份文件最后一行是裸的 `main()`，
    import 就会开摄像头，所以不能 `from live_face import panel`。
    抄一份 15 行的绘图函数，比为了复用去重构一个已验证的探针安全得多。
    """
    x = max(0, min(x, img.shape[1] - 40))
    tw = max(cv2.getTextSize(t, cv2.FONT_HERSHEY_SIMPLEX, fs, 1)[0][0]
             for t, _ in lines)
    w, h = tw + 26, lh * len(lines) + 18
    w = min(w, img.shape[1] - x)
    h = min(h, img.shape[0] - y)
    sub = img[y:y + h, x:x + w]
    if sub.size:
        sub[:] = (sub * 0.22).astype(sub.dtype)
    yy = y + lh
    for t, col in lines:
        cv2.putText(img, t, (x + 13, yy), cv2.FONT_HERSHEY_SIMPLEX, fs,
                    (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(img, t, (x + 13, yy), cv2.FONT_HERSHEY_SIMPLEX, fs,
                    col, 1, cv2.LINE_AA)
        yy += lh


def _cell(v, fmt="{:.4f}"):
    """CSV 单元格。NaN / None 一律写 `-`，**不要写 `nan`**：
    这个日志是留着事后拿 Excel 或 pandas 读的，`nan` 会被读成字符串
    再毒化整列，而 `-` 一眼就知道是"没有"。"""
    if v is None:
        return "-"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return fmt.format(f) if np.isfinite(f) else "-"


def draw_curve(bgr, vals, thr, y0, h, color=(0, 220, 255)):
    """EAR_norm 的走势 + 阈值横线。画在最底下，不与 HUD 抢地方。"""
    h_img, w_img = bgr.shape[:2]
    y0 = max(0, min(y0, h_img - 10))
    h = max(10, min(h, h_img - y0))
    sub = bgr[y0:y0 + h, :]
    sub[:] = (sub * 0.25).astype(sub.dtype)

    def to_y(v):
        return int(y0 + h - 6 - min(max(v, 0.0), 1.6) / 1.6 * (h - 12))

    ty = to_y(thr)
    cv2.line(bgr, (0, ty), (w_img, ty), (120, 120, 120), 1)
    cv2.putText(bgr, f"{thr:.2f}", (4, ty - 4), cv2.FONT_HERSHEY_SIMPLEX,
                0.45, (170, 170, 170), 1, cv2.LINE_AA)
    v = [x for x in vals if np.isfinite(x)]
    if len(v) < 2:
        return
    n = len(v)
    pts = np.array([[int(i / (n - 1) * (w_img - 1)), to_y(x)]
                    for i, x in enumerate(v)], np.int32)
    cv2.polylines(bgr, [pts], False, color, 2, cv2.LINE_AA)


# ---------------------------------------------------------------- 性能门禁
def selftest(clip, model, feat_mean, feat_std, window, n_max=200):
    """两个 landmarker 同进程跑，量 pose / face / infer 三段耗时。

    这是**写融合代码之前的门禁**（性能不过就不该继续）：Pose(full) + Face
    同进程跑 15 Hz 是最大的未知数。参考基线见 `docs/技术方案.md` §8 ——
    MediaPipe `full` 纯推理 16.6 ms/帧，而摄像头本身只有 10~11 fps。
    通过判据：三段合计中位 <= 60 ms（>= 16.7 FPS，能喂满 15 Hz 调度器）。
    """
    pose = PoseExtractor(None, running_mode="VIDEO")
    face = FaceExtractor(running_mode="VIDEO")
    cap = cv2.VideoCapture(str(clip))
    if not cap.isOpened():
        print(f"打不开 {clip}")
        os._exit(1)
    p_ms, f_ms, i_ms = [], [], []
    ring = collections.deque(maxlen=window)
    norm = OnlineNormalizer()
    last_lm = None
    k = 0
    while k < n_max:
        ok, frame = cap.read()
        if not ok or frame is None:
            break
        mt = k / 30.0
        t = time.perf_counter()
        last_lm = pose.detect(frame, mt * 1000.0)
        p_ms.append((time.perf_counter() - t) * 1000)
        t = time.perf_counter()
        face.detect(frame, mt * 1000.0)
        f_ms.append((time.perf_counter() - t) * 1000)
        if last_lm is not None:
            ring.append(norm.push(last_lm))
        if len(ring) == window:
            x = (np.asarray(ring, np.float32) - feat_mean) / feat_std
            t = time.perf_counter()
            with torch.no_grad():
                model(torch.from_numpy(x[None]))
            i_ms.append((time.perf_counter() - t) * 1000)
        k += 1
    cap.release()

    def rep(tag, a):
        if not a:
            print(f"  {tag:<8} 无数据")
            return 0.0
        print(f"  {tag:<8} 中位 {np.median(a):6.1f} ms   "
              f"p95 {np.percentile(a, 95):6.1f} ms   n={len(a)}")
        return float(np.median(a))

    print(f"\n性能自检  {Path(clip).name}  {k} 帧")
    mp = rep("pose", p_ms)
    mf = rep("face", f_ms)
    mi = rep("infer", i_ms)
    tot = mp + mf
    print(f"  {'合计':<8} 中位 {tot:6.1f} ms  ->  {1000.0 / max(tot, 1e-6):5.1f} FPS"
          f"（推理另算 {mi:.1f} ms，不在同一帧里阻塞）")
    if tot <= 60.0:
        print(f"  ✅ 通过（判据 <= 60 ms = 16.7 FPS）")
    else:
        print(f"  ❌ 超了 —— 用 --face-hz 7 重测，见本脚本 --face-hz 的说明")
    sys.stdout.flush()
    os._exit(0)


# ---------------------------------------------------------------- 主循环
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None, help="支路一权重，默认 runs/ 下最新 best.pt")
    ap.add_argument("--model2", default=None,
                    help="支路二权重，默认 models/branch2_lr.npz")
    ap.add_argument("--cam", type=int, default=0)
    ap.add_argument("--replay", default=None, help="回放视频而不是开摄像头")
    ap.add_argument("--fast", action="store_true", help="回放时不按真实时间配速")
    ap.add_argument("--no-display", action="store_true")
    ap.add_argument("--no-voice", action="store_true")
    ap.add_argument("--serial", default=None, help="灯带串口，如 COM3")
    ap.add_argument("--pose-model", default=None, help="lite / full")
    ap.add_argument("--quiet", action="store_true", help="不打印每帧决策")
    ap.add_argument("--seconds", type=float, default=None, help="跑满这么多秒自动停")
    ap.add_argument("--no-face", action="store_true",
                    help="摘掉支路二，此时本脚本应逐帧复现 src/live.py（回归工具）")
    ap.add_argument("--face-hz", type=float, default=C.TARGET_FPS,
                    help=f"面部检测频率上限，默认 {C.TARGET_FPS}（=不降频）。"
                         f"性能不够时用 7：支路二本来就按时间戳统计，"
                         f"且已在 6.3 fps 的真人会话里验证过")
    ap.add_argument("--gate-min", type=float, default=GATE_MIN,
                    help=f"闸门概率下限，默认 {GATE_MIN}=1-EXIT_TH")
    ap.add_argument("--yawn-action", choices=("level", "display"),
                    default=YAWN_ACTION,
                    help=f"哈欠标定成功则 level（抬到 L1），否则 display（只显示）")
    ap.add_argument("--yawn-hold", type=float, default=YAWN_HOLD)
    # 两条规则的开头（见上面 EYE_*/HEAD_* 那段）。全开成开关的理由和哈欠一样：
    # 阈值是在录制数据上标定的，真人身上要不要更松/更紧只能现场调。
    ap.add_argument("--eye-sec", type=float, default=CLOSE_EYE_SEC,
                    help=f"归一化 EAR 连续低于 {BLINK_THR:.2f} 多少秒算一次"
                         f"持续闭眼（默认 {CLOSE_EYE_SEC}）")
    ap.add_argument("--eye-hold", type=float, default=EYE_HOLD)
    ap.add_argument("--eye-level", type=int, default=EYE_LEVEL)
    ap.add_argument("--head-deg", type=float, default=HEAD_DEG,
                    help=f"最近 {HEAD_WIN:.0f} 秒内头上下摆多少度算低头/点头"
                         f"（默认 {HEAD_DEG} 度）")
    ap.add_argument("--head-hold", type=float, default=HEAD_HOLD)
    ap.add_argument("--head-level", type=int, default=HEAD_LEVEL)
    ap.add_argument("--selftest", default=None, metavar="CLIP",
                    help="只跑性能门禁然后退出")

    # ---- 支路一迟滞旋钮（与 live.py 同名同义）----
    ap.add_argument("--enter-th", type=float, default=ENTER_TH)
    ap.add_argument("--exit-th", type=float, default=EXIT_TH)
    ap.add_argument("--enter-sec", type=float, default=ENTER_SEC)
    ap.add_argument("--exit-sec", type=float, default=EXIT_SEC)
    ap.add_argument("--alpha", type=float, default=EMA_ALPHA)
    ap.add_argument("--decide-hz", type=float, default=DECIDE_HZ)
    # ---- 支路二迟滞旋钮（现场对着真人调，不用改代码重跑）----
    ap.add_argument("--b2-enter", type=float, default=B2_ENTER)
    ap.add_argument("--b2-enter2", type=float, default=B2_ENTER2)
    ap.add_argument("--b2-exit", type=float, default=B2_EXIT)
    ap.add_argument("--b2-exit2", type=float, default=B2_EXIT2)
    ap.add_argument("--b2-enter-sec", type=float, default=B2_ENTER_SEC)
    ap.add_argument("--b2-exit-sec", type=float, default=B2_EXIT_SEC)
    ap.add_argument("--log-probs", default=None, help="逐次决策写进 CSV")
    args = ap.parse_args()

    # ---- 支路一权重 ----
    ckpt_path = find_model(args.model)
    model, feat_mean, feat_std, classes, window = load_infer_model(ckpt_path)
    if list(classes) != list(C.CLASSES):
        print(f"  [warn] 权重里的类别 {classes} 与 config.CLASSES {C.CLASSES} 不一致")
    if window != C.WINDOW:
        print(f"  [warn] 权重是按 {window} 帧窗口训的，config.WINDOW 是 "
              f"{C.WINDOW} —— 按权重走。要一致就改 config 后重训。")
    print(f"支路一 {ckpt_path.name}  参数 {model.n_params():,}  "
          f"窗口 {window} 帧 = {window / C.TARGET_FPS:.1f} s")

    # ---- 支路二权重 ----
    model2 = None
    if not args.no_face:
        model2 = load_branch2(args.model2)
    if args.selftest:
        if model2 is None:
            print("--selftest 需要支路二，别和 --no-face 一起用")
            os._exit(1)
        selftest(args.selftest, model, feat_mean, feat_std, window)

    hyst = Hysteresis(args.enter_th, args.exit_th, args.enter_sec,
                      args.exit_sec, args.alpha, args.decide_hz)
    b2 = ScalarState(args.b2_enter, args.b2_enter2, args.b2_exit,
                     args.b2_exit2, args.b2_enter_sec, args.b2_exit_sec)
    print(f"迟滞 {hyst}")
    print(f"闸门 argmax(b1.ema)==normal 且 ema[normal] >= {args.gate_min:.2f}"
          f"（= 1-EXIT_TH）")
    if model2 is not None:
        print(f"支路二 窗口 {WIN_SEC:.0f} s（离线片段中位 17.1 s）"
              f"  缓冲 {HIST_SEC:.0f} s  封顶 L{B2_MAX_LEVEL}"
              f"  升 {args.b2_enter:.2f}/{args.b2_enter2:.2f} "
              f"降 {args.b2_exit:.2f}/{args.b2_exit2:.2f}")
        print(f"哈欠 >{YAWN_THR:.2f} 持续 {YAWN_MIN:.1f} s -> "
              + ("抬到 L1，保持 %.0f s" % args.yawn_hold
                 if args.yawn_action == "level" else "只显示（不动级别）"))
    else:
        print("支路二已摘除（--no-face），应当逐帧复现 src/live.py")
    # ★ 这两条**不依赖支路二的模型**（`--no-face` 时一条都不响：闭眼要 EAR、
    #   低头要 pitch，两个都来自 FaceExtractor），所以印在 if/else 外面。
    print(f"规则（都不看闸门）  持续闭眼 >={args.eye_sec:.1f} s -> L{args.eye_level}"
          f" 保持 {args.eye_hold:.0f} s"
          f"   |   头摆 >={args.head_deg:.0f}° / {HEAD_WIN:.0f} s -> "
          f"L{args.head_level} "
          + (f"保持 {args.head_hold:.0f} s" if args.head_hold > 0
             else "**不锁存**（判据掉下来当场摘）"))

    norm = OnlineNormalizer()
    state = WarningState(hyst)
    tts = TTSWorker(enabled=not args.no_voice)
    light = LightOutput(serial_port=args.serial)
    ring = collections.deque(maxlen=window)

    pose = PoseExtractor(args.pose_model, running_mode="VIDEO")
    face = None if args.no_face else FaceExtractor(running_mode="VIDEO")
    fb = FaceBranch()
    if args.replay:
        src = VideoSource(args.replay, fast=args.fast)
        print(f"回放 {args.replay}  {src.n} 帧 @ {src.fps:.1f} fps"
              + ("  [fast]" if args.fast else ""))
    else:
        src = CameraSource(args.cam)
        print(f"摄像头 {args.cam}  按 {C.TARGET_FPS} Hz 节拍取最新帧")

    feed_dt = 1.0 / C.TARGET_FPS
    decide_dt = hyst.decide_dt
    # 面部降频用**整数步长**，不用时间戳（理由见主循环里那段注释：
    # face_hz 默认 = 名义帧率时，按时间戳判会退化成浮点等号比较，会丢帧）。
    # face_hz >= 名义帧率 → 步长 1，也就是**不降频**。
    face_step = (1 if args.face_hz >= C.TARGET_FPS
                 else max(2, int(round(C.TARGET_FPS / max(args.face_hz, 1e-6)))))
    display = not args.no_display
    log_fp = open(args.log_probs, "w", encoding="utf-8", newline="") \
        if args.log_probs else None
    if log_fp:
        log_fp.write("t," + ",".join(C.CLASSES)
                     + ",l1,gate,ema_normal,p_fat,l2,perclos,brate,nod,"
                       "en_now,d_pitch,yawn_sec,eye_sec,head_swing,l_fused,src,"
                       "ear,mar,"
                       # ⚠️ pitch 是**绝对**俯仰角。另有**两个**从它派生的极差量，
                       #   它们**不是**一回事，也不能互相换算（极差回推不出绝对值）：
                       #     d_pitch    窗内(WIN_SEC=17 s) p95−p5，要 10 秒基线，
                       #                且**拖尾**（半分钟前点过的头还拉着它）
                       #     head_swing 最近 HEAD_WIN=2 s 的 p95−p5，**免基线**，
                       #                开机 2 秒就有数 —— 低头规则的判据就是它
                       #   L4 判决的【0】自我否证要 r(en_norm, pitch)，【2】分层要
                       #   "窗中位贴近中性姿态"，都只有绝对 pitch 才做得出
                       #   （见 tools/analyze_fuse_l4.py）。
                       # mark = 空格标记，验支路二"闭眼而头不动"时最硬的一条真相。
                       # src = **是哪条来源把 l_fused 抬起来的**（pose/face/yawn/
                       #   eye/head）。界面按它报「检测到持续闭眼 / 持续低头」，
                       #   所以这个字符串是**判据的一部分**，不是调试字段 ——
                       #   改了它，ui/state.py 的告警就跟着变（ui/ 里没有第二份阈值）。
                       "pitch,mark\n")

    last_lm = None
    last_lm_id = -1
    fed_id = -1
    next_feed = 0.0
    next_decide = 0.0
    first = True
    n_fed = n_dup = n_lost = n_infer = 0
    n_face = n_face_lost = 0
    n_gate_open = 0
    n_decide = 0
    n_b2_up = 0
    n_yawn = 0
    n_eye = n_head = 0
    infer_ms = collections.deque(maxlen=60)
    py_ms = collections.deque(maxlen=60)
    probs = np.full(len(C.CLASSES), 1.0 / len(C.CLASSES))
    frame_id = 0
    # 空格标记：按住/松开都太费事，做成 toggle（照搬 _scratch/live_face.py:635）。
    # 标记的是**操作者的真值**："我现在闭着眼、头没动"。不写进逻辑，只进 CSV ——
    # 它是事后判决最硬的一条证据（见 tools/analyze_fuse_l4.py 的【3】）。
    mark_on = False
    n_mark = 0
    l2 = 0
    p_fat = float("nan")
    st = None
    en_hist = collections.deque(maxlen=600)
    spoken_at = {}
    yawn_until = -1.0
    # ⚠️ 这几个必须在循环**之前**给初值：HUD 的预热分支现在也画 YAWN/EYE/HEAD，
    #   而 HUD 每帧都跑、决策块要等 `len(ring) == window` 才第一次赋值 ——
    #   不初始化的话第一拍之前引用就是 UnboundLocalError（改完第一次跑就崩了）。
    yawn_on = False
    yawn_sec = 0.0
    # 两条新规则的状态（写法与 yawn 同款：一个 until 时间戳 + 一个布尔 + 一个量）
    eye_until = -1.0
    head_until = -1.0
    eye_on = False
    head_on = False
    eye_sec = 0.0
    h_swing = float("nan")
    l_eye = l_head = 0
    src_of_level = "pose"
    why = ""
    # ★ 头姿缓冲：**独立于 fb、永远不看闸门**（理由见 face.HeadMotion 的 docstring）
    hm = HeadMotion()

    def should_speak(level, now, forced=False):
        """按级别冷却地决定要不要出声。

        没有复用 `state.should_speak`：那个是按**支路一的级别**记冷却的，
        而这里要念的级别可能来自支路二或哈欠规则，支路一自己的状态机
        并不知道那些级别的存在 —— 复用它会让"支路二抬到 L2"这件事
        因为"支路一上次在 L2 已经念过了"而静音。
        """
        if level < (SPEAK_FROM_YAWN if forced else SPEAK_FROM):
            return False
        last = spoken_at.get(level)
        if last is not None and now - last < VOICE_COOLDOWN:
            return False
        spoken_at[level] = now
        return True

    t0 = time.perf_counter()
    try:
        while True:
            frame, _ = src.read()
            if frame is None:
                print("\n帧源结束。")
                break
            wall = time.perf_counter() - t0
            if args.seconds is not None and wall >= args.seconds:
                print(f"\n跑满 {args.seconds} s，停。")
                break
            mt = src.media_time()      # 媒体时间：两条支路用同一个时间轴
            frame_id += 1

            lm = pose.detect(frame, mt * 1000.0)
            if lm is None:
                n_lost += 1
            else:
                last_lm, last_lm_id = lm, frame_id

            # ---- 闸门：支路二只在支路一判"正视前方"时才有发言权 ----
            # 用上一次决策的 EMA。滞后一个决策周期（0.1 s），无所谓。
            gate = bool(np.argmax(state.ema) == NORMAL_I
                        and state.ema[NORMAL_I] >= args.gate_min)

            # ---- 支路二：检脸 → 推缓冲 ----
            # ⚠️ 这里原来按时间戳判：`mt >= next_face`，`next_face += 1/face_hz`。
            #   而 face_hz 默认 = TARGET_FPS = 视频的 15 fps，于是判据退化成
            #   `k/15 >= (k-1)/15 + 1/15` —— 一个**浮点等号**比较，累加误差让它
            #   偶尔不成立。实测 yawn_open_03 上 242 帧只送进检测器 228 帧
            #   （摘要里「检到脸 228 / 丢失 0」—— 不是没检到，是压根没送去检）。
            #   默认档位下悄悄丢掉 6% 的帧，不是 `--face-hz` 想做的事。
            #   改成**整数步长**：face_hz >= 名义帧率时不降频（每帧都做），
            #   否则每 face_step 帧做一次。确定性的，没有浮点边界。
            #   代价：真正的检测频率跟着摄像头走（相机 8 fps、face_hz 7 → 步长 2
            #   → 实际 4 Hz），比请求的更省 —— 对一个"性能不够时的退路"是安全方向。
            #
            #   ⚠️ 一条**没有**验证的因果，写在这里免得下次又有人这么推：
            #   同一段 yawn_open_03 的 yawn_sec，离线 3.20 s 而在线报 4.13～5.53 s，
            #   我一开始归因于"丢帧把两次张嘴并成了一次"。**那是错的。**
            #   加容差改掉丢帧之后数字照样是 5.53；把 fuse 的 mar 写进日志
            #   逐帧比才发现：真正的差别在 **MAR 本身**，两趟检测器在同一时间戳上
            #   差到第三位小数（t=10.600：离线 0.6614 / 在线 0.6226），
            #   而这段的 MAR 有 20/242 帧落在 0.60±0.02 里（其它段只有 4/227、
            #   4/186，talking 0/198），于是"这一段到底算不算一次连续张嘴"
            #   在两次运行之间是**不稳定**的。两种结果都 ≥ YAWN_MIN=1.2，
            #   所以**判决是稳的，数字不是**（见 face.yawn_seconds 的注释）。
            #   丢帧这个改动仍然值得做，但它是另一件事，不是这个数字的原因。
            # 每帧先给 NaN：`--no-face` 时下面整段不执行，而日志要写这两列。
            ear = mar = pitch = float("nan")
            if face is not None and (face_step == 1 or frame_id % face_step == 0):
                d = face.detect(frame, mt * 1000.0)
                if d is None:
                    n_face_lost += 1
                    ear = mar = pitch = float("nan")
                else:
                    n_face += 1
                    ear, mar, pitch = d["ear"], d["mar"], d["pitch"]
                # ★ 一直采集，**不看闸门**（2026-09-26 改；原来是 `if gate: push
                #   else: clear()`）。用户原话：「这些都要一直采集着啊 我打开摄像头
                #   就应该开始采集了啊而不是等十几秒」。
                #   原来那条的理由写在 `face.FaceBranch.clear()` 的 docstring 里，
                #   属于中位归一化时代；p75 滚动基线之后头姿污染已被除法本身消掉
                #   （实测 phone 18 段归一化后最长"闭眼"中位 0.20 s、EAR/MAR
                #   有效率 100%），而代价是**低头这个动作本身就会关闸门** ——
                #   于是缓冲和界面上那个倒计时每次低头都从零重攒，越像疲劳的人
                #   越攒不满 27 秒。闸门的作用**只剩"投不投票"**（下面 l_face
                #   仍然要求 `gate`），不再是"收不收集"。
                # 没检到脸也塞 NaN（保持 perclos 分母完整，见 FaceBranch.push）
                fb.push(mt, ear, mar, pitch)
                # 头姿缓冲：同样不看闸门，而且它**必须**不看 —— 低头就是关闸门的
                # 信号，挂在闸门上等于让低头规则在被触发的那一刻失效。
                hm.push(mt, pitch)

            # ---- 15 Hz 节拍：到点就取"当前最新的一帧" ----
            if first:
                next_feed = mt
                next_decide = mt
                first = False
            elif next_feed < mt - 0.5:
                next_feed = mt             # 卡顿后重新对表
            while next_feed <= mt:
                if last_lm is not None:
                    ring.append(norm.push(last_lm))
                    n_fed += 1
                    if last_lm_id == fed_id:
                        n_dup += 1
                    fed_id = last_lm_id
                next_feed += feed_dt

            # ---- 决策 ----
            if len(ring) == window and mt >= next_decide:
                next_decide = mt + decide_dt
                n_decide += 1
                x = np.asarray(ring, np.float32)
                x = (x - feat_mean) / feat_std
                with torch.no_grad():
                    ti = time.perf_counter()
                    probs = torch.softmax(
                        model(torch.from_numpy(x[None])), dim=1)[0].numpy()
                    infer_ms.append((time.perf_counter() - ti) * 1000)
                n_infer += 1
                l1, _rose = state.update(probs, mt)

                # ---- 支路二：统计 → 概率 → 级别 ----
                # gate 要用刚更新过的 EMA 重算一遍，否则这一拍用的是上一拍的门。
                gate = bool(np.argmax(state.ema) == NORMAL_I
                            and state.ema[NORMAL_I] >= args.gate_min)
                n_gate_open += 1 if gate else 0
                st = fb.snapshot() if (gate and fb.ready()) else None
                p_fat = float("nan")
                if gate and fb.full() and st is not None:
                    fv = np.array([feature_vector(st)], float)
                    if np.all(np.isfinite(fv)):
                        ti = time.perf_counter()
                        p_fat = float(model2.predict_proba(fv)[0, 1])
                        py_ms.append((time.perf_counter() - ti) * 1000)
                        lv = b2.update(p_fat, mt)
                        if lv > l2:
                            n_b2_up += 1
                        l2 = lv
                    else:
                        l2 = 0
                else:
                    l2 = 0
                    b2.reset()          # 闸门关/没热身 → 归零，不保持

                # ---- 哈欠规则（不进逻辑回归，见模块开头）----
                # ★ 从**缓冲**直接算，不从 `st` 里取。
                #   `st` 是 window_features 的输出，要等 `fb.ready()`
                #   （缓冲满 ROLL_WIN = 10 秒）才非 None。哈欠判据本身只要
                #   YAWN_MIN + 一点点缓冲 —— 挂在 st 上等于让**逻辑回归的热身
                #   去管规则**，两个东西的暖机时间本来不一样。
                #   代价不是"晚 10 秒"，是**短片段上永远不响**：
                #   端到端回放在 yawn_open_01（12.3 s）上 0 帧触发，
                #   而它的哈欠离线量是 4.40 s，A/B/C 三条路径完全一致
                #   （_scratch/_yawn_e2e_probe.py）。这一条就是那么发现的。
                yawn_sec = 0.0
                eye_sec = 0.0
                if fb.span >= YAWN_MIN + 0.5:
                    # ★ 只取一次 arrays()，两条规则共用（每拍一次 np.array(deque)）
                    _bt, _be, _bm, _ = fb.arrays()
                    yawn_sec = float(yawn_seconds(_bt, _bm))
                    # ---- 持续闭眼规则 ----
                    # ★ **不挂在 ROLL_WIN(10 s) 上**。基线（p75）从第一帧起就用
                    #   "现有的历史"算（`norm_by_time` 的窗是 [j, i]，只看过去），
                    #   量过代价：取 N=1.0 s 时正常 27 段在**前 10 秒内**触发 0 段、
                    #   说话 0/5，而疲劳 21 段里有 **16 段在前 10 秒内**就抓到、
                    #   最早 1.8 秒（`_calib_closeeye.py` + 2026-09-26 那次补测）。
                    #   所以这里只要求"缓冲里有两个量级以上的样本"，不等热身 ——
                    #   用户原话「我打开摄像头就应该开始采集了啊而不是等十几秒」。
                    #   ⚠️ 唯一不能省的是**基线长度** ROLL_WIN：窗短于 10 秒时 p75
                    #     会被闭眼自己拽塌、`ear/基线` 恒为 1（见 norm_by_time）。
                    #     这里没有省它 —— 省的是"等 10 秒才允许判"。
                    if fb.span >= CLOSE_EYE_SEC + 1.0:
                        _en = _be / np.maximum(
                            norm_by_time(_bt, _be, ROLL_WIN), 1e-6)
                        eye_sec = float(close_eye_seconds(_bt, _en))
                if yawn_sec >= YAWN_MIN:
                    if mt >= yawn_until:            # 新的一次哈欠（不是同一次保持）
                        n_yawn += 1
                    yawn_until = mt + args.yawn_hold
                yawn_on = mt < yawn_until
                if eye_sec >= args.eye_sec:
                    if mt >= eye_until:
                        n_eye += 1
                    eye_until = mt + args.eye_hold
                eye_on = mt < eye_until

                # ---- 低头/点头规则（免基线，开机 HEAD_WIN=2 秒就能判）----
                # 判据 = 最近 HEAD_WIN 秒 pitch 的 p95−p5 >= HEAD_DEG。标定见
                # `face.HEAD_DEG` 的注释（正常 2/27 误报是用户选"最敏感"那档的代价）。
                # ⚠️ 读 `hm`（独立缓冲）**不是** `fb`：低头会让闸门关上，而 `fb` 的
                #   语义正被闸门管着；`hm` 永远收、永远不清。
                # ⚠️ 也不读 `st["d_pitch"]`：那个要 10 秒基线、窗 17 秒且拖尾。
                h_swing = hm.swing()
                hit = bool(np.isfinite(h_swing) and h_swing >= args.head_deg)
                if args.head_hold <= 0.0:
                    # ★ **不锁存**（默认，`HEAD_HOLD = 0.0`；理由和实测数字见那个常数的
                    #   注释）。判据这一拍成立就抬、这一拍不成立就摘 —— 纯跟随。
                    #   ⚠️ 这里**必须**是单独一条支，不能靠"把 head_hold 设成 0"：
                    #     那条路算出来是 `mt < mt` 恒假，规则整条哑掉。
                    #   ⚠️ `n_head` 改数**上升沿**：不锁存时每一拍都成立，按老写法
                    #     （`mt >= head_until`）持续低头会被数成每拍一次，而这个数
                    #     要打到屏幕上（`:989` 的收尾汇总）。
                    if hit and not head_on:
                        n_head += 1
                    head_on = hit
                else:
                    # `--head-hold N`（N>0）= 老口径，抬到 L3 后再保持 N 秒。
                    # ★ 保留它是为了能**A/B**：`--head-hold 5` 逐拍复现 2026-09-26
                    #   之前的行为。两条支对 N>0 是逐字等价的（下面这几行原来就在这儿）。
                    if hit and mt >= head_until:
                        n_head += 1
                    if hit:
                        head_until = mt + args.head_hold
                    head_on = mt < head_until

                # ---- 融合 ----
                l_face = min(l2, B2_MAX_LEVEL) if (face is not None and gate) else 0
                l_base = max(l1, l_face)
                l_yawn = 1 if (yawn_on and args.yawn_action == "level") else 0
                l_eye = args.eye_level if eye_on else 0
                l_head = args.head_level if head_on else 0
                # ★ 四条来源取最大。**平局时 `max()` 返回列表里靠前的那个**，
                #   所以这个顺序就是优先级：**规则赢基线**（低头 > 闭眼 > 哈欠 > 基线票）。
                # ⚠️ 平局只决定"念哪一句原因"，**级别一模一样** —— `l_fused` 在
                #   任何平局下都等于那个相等的值，改顺序不会让级别动一下。
                #   之所以让规则赢：用户要的就是"为什么报"这句话。低头时支路一
                #   往往**也**给 L3（它本来就判低头），若平局判给基线，屏上就永远
                #   看不到「检测到持续低头」，而那正是他点名要的那条（演示里
                #   `l1=3` 与 `l_head=3` 同时成立，就是这么被吞掉的）。
                # ⚠️ 与 2026-09-26 之前的唯一差别：`yawn_on` 且 `l_base == 1` 时，
                #   `src` 从 "pose" 变成 "yawn"、语音改念「检测到打哈欠」（旧式子是
                #   `yawn_on and 1 > l_base`，平局判给基线）。级别不变，界面告警也
                #   不变（那条走 `yawn_sec` 列，与 `src` 无关）。
                # ⚠️ **别把这四行写成一个 `max((元组), key=…)`。** 我第一版就是那么
                #   写的，全零那一拍 `max` 返回列表**第一个** → `src="head"`，
                #   于是级别 0 却在屏上报「检测到持续低头」（演示 t=0 就复现了）。
                #   平局规则只在**有级别**时才该生效，所以 `l_fused <= 0` 单独一支。
                l_fused = max(l_base, l_yawn, l_eye, l_head)
                if l_fused <= 0:
                    src_of_level = "pose"
                elif l_head == l_fused:
                    src_of_level = "head"
                elif l_eye == l_fused:
                    src_of_level = "eye"
                elif l_yawn == l_fused:
                    src_of_level = "yawn"
                else:
                    src_of_level = "face" if l_face > l1 else "pose"

                light.set_level(l_fused, mt)
                if log_fp:
                    # ⚠️ 这里**必须**一格一格 append，不能写成
                    #   `A + f"..." if st else ","` —— 条件表达式优先级低于 `+`，
                    #   那样解析出来是 `(A + f"...") if st else ","`，
                    #   st 为 None 时整行只剩一个逗号，而且不报错。
                    cols = ([f"{mt:.3f}"] + [f"{v:.4f}" for v in probs]
                            + [str(l1), str(int(gate)),
                               f"{state.ema[NORMAL_I]:.4f}", _cell(p_fat),
                               str(l2)])
                    cols += [_cell(st[k]) if st else "-" for k in FEATURE_NAMES]
                    cols += [_cell(st["en_now"]) if st else "-",
                             _cell(st["d_pitch"], "{:.2f}") if st else "-",
                             f"{yawn_sec:.2f}", f"{eye_sec:.2f}",
                             _cell(h_swing, "{:.2f}"), str(l_fused),
                             # `src` 是判据的一部分（界面按它报哪条规则响的），
                             # 不是调试字段 —— 见上面表头那段。
                             str(src_of_level),
                             # 原始两路也写下来：L4 现场事后复盘时，"哈欠/闭眼
                             # 到底有没有被采到"只能靠这两列回答（阈值判据都是
                             # 从它们算的）。_scratch/live_face.py 一直这么做。
                             _cell(ear, "{:.4f}"), _cell(mar, "{:.4f}"),
                             # 绝对 pitch：上面的 d_pitch 只是窗内极差，回推不出
                             # 它。没检到脸的那一拍是 NaN → 写 `-`。
                             _cell(pitch, "{:.2f}"),
                             # 空格标记。**这一拍的最新值**，不是"这一拍按下过"——
                             # 决策频率 10 Hz 而按键随时发生，够用了。
                             str(int(mark_on))]
                    log_fp.write(",".join(cols) + "\n")
                if not args.quiet:
                    top = int(np.argmax(state.ema))
                    tail = ""
                    if face is not None:
                        tail = (f"  | gate {'OPEN ' if gate else 'shut'} "
                                f"L2={l2}"
                                + (f" P={p_fat:.2f}" if np.isfinite(p_fat) else " P=  -")
                                + (f" pc={st['perclos']:.2f}" if st else " pc= -")
                                + (" YAWN" if yawn_on else "")
                                + (f" EYE={eye_sec:.1f}s" if eye_on else "")
                                + (f" HEAD={h_swing:.0f}°" if head_on else ""))
                    print(f"  [{mt:6.1f}s] L{l_fused} {LEVEL_CN[l_fused]:<2}"
                          f" <{src_of_level[:4]:<4}> "
                          + " ".join(f"{c[:3]}={probs[k]:.2f}"
                                     for k, c in enumerate(C.CLASSES))
                          + f"  ema({C.CLASSES[top][:3]})={state.ema[top]:.2f}"
                          + tail)
                # 级变才念，且按来源选文案
                if l_fused > 0:
                    if src_of_level == "face":
                        why = NOTE_FACE.get(l_fused, LEVEL_NOTE[l_fused])
                    elif src_of_level == "yawn":
                        why = NOTE_YAWN.get(l_fused, "")
                    elif src_of_level == "head":
                        # 低头/点头是产品口径里的重度征兆，文案自己一份 ——
                        # `LEVEL_NOTE[3]` 是"检测到头部持续低垂/倾倒"，用在这是对的，
                        # 但用户要的是"就报"，所以给一句更直接的。
                        why = NOTE_HEAD.get(l_fused, LEVEL_NOTE[l_fused])
                    elif src_of_level == "eye":
                        # 复用支路二那条闭眼文案（`NOTE_FACE`），不另起一句：
                        # 同一次闭眼不该因为"是规则发现的"就换一种说法。
                        why = NOTE_FACE.get(l_fused, LEVEL_NOTE[l_fused])
                    else:
                        why = LEVEL_NOTE[l_fused] or LEVEL_CN[l_fused]
                # 只有哈欠强制出声（它保持 5 s、冷却 6 s，不会被重复刷）；
                # 低头/闭眼是**持续**状态，强制出声会每拍都念一遍 —— 不强制。
                if should_speak(l_fused, mt, forced=(src_of_level == "yawn")):
                    if not args.quiet:
                        print(f"  [{mt:6.1f}s] >>> 语音({src_of_level})：{why}")
                    tts.say(why)

                if st is not None:
                    en_hist.append(st["en_now"])

            # ---- HUD ----
            vis = frame.copy()
            if last_lm is not None:
                draw_pose(vis, last_lm)
            y0 = light.draw(vis, mt)
            native = frame_id / wall if wall > 0 else 0.0
            ms = float(np.median(infer_ms)) if infer_ms else 0.0
            lines = [
                ("  ".join(f"{c[:3]}:{probs[k]:.2f}"
                           for k, c in enumerate(C.CLASSES)), WHITE),
                (f"level L{state.level} {LEVEL_CN[state.level]}"
                 f"   (enter {ENTER_TH} exit {EXIT_TH})",
                 LEVEL_COLOR[state.level]),
                (f"cam {native:4.1f} fps -> feed {C.TARGET_FPS} Hz"
                 f"   dup {n_dup}  lost {n_lost}",
                 GREEN if native >= C.TARGET_FPS * 0.6 else YELLOW),
                (f"infer {ms:4.1f} ms  x{n_infer}   "
                 f"pose {'OK' if last_lm is not None else 'LOST'}",
                 GREEN if last_lm is not None else RED),
            ]
            draw_hud_offset(vis, lines, y0 + 6)

            if face is not None:
                if st is None:
                    # 热身期间也要显示**三条规则** —— 它们比这张表上的其它量都早
                    # （LR 的概率要等 full()=27 s）：哈欠 2.5 s 缓冲就能判、低头只要
                    # HEAD_WIN=2 s、闭眼要 CLOSE_EYE_SEC+1 s。★ 2026-09-26 起这个
                    # `fb.warm_left()` 是**从开机起单调往下数**的：闸门不再清缓冲，
                    # 所以低头一次不会让它跳回去（原来是"低头一次就重头数"）。
                    fl = [(f"BRANCH 2   WARMING {fb.warm_left():4.1f}s", (150, 150, 150)),
                          (f"gate {'OPEN' if gate else 'closed'}", (90, 240, 90)
                           if gate else (120, 120, 255)),
                          (f"YAWN      " + (f"YES {yawn_sec:4.1f}s" if yawn_on else "  -"),
                           (0, 120, 255) if yawn_on else (150, 150, 150)),
                          (f"EYE  {eye_sec:4.1f}s thr {args.eye_sec:.1f}",
                           (0, 160, 255) if eye_on else (150, 150, 150)),
                          (f"HEAD {h_swing:5.1f}° thr {args.head_deg:.0f}",
                           (255, 120, 0) if head_on else (150, 150, 150))]
                else:
                    pm = float(np.median(py_ms)) if py_ms else 0.0
                    fl = [
                        (f"BRANCH 2   gate {'OPEN' if gate else 'CLOSED'}"
                         + ("  WARMING" if not fb.full() else ""),
                         (90, 240, 90) if gate else (120, 120, 255)),
                        (f"EAR_norm  {st['en_now']:6.3f}  thr {BLINK_THR:.2f}",
                         (90, 240, 90) if st["en_now"] >= BLINK_THR else (90, 90, 255)),
                        (f"PERCLOS   {st['perclos']:6.3f}", (0, 220, 255)),
                        (f"BLINK/min {st['brate']:6.1f}   NOD {st['nod']:5.1f}",
                         (0, 220, 255)),
                        (f"dPITCH    {st['d_pitch']:6.1f} deg  (17 s, 要基线)",
                         (90, 240, 90)),
                        # ⚠️ 上面 d_pitch 是 17 秒窗、要基线、拖尾；下面是 2 秒窗、
                        #   免基线 —— 两个数**不一样**，低头规则用的是下面这个。
                        (f"SWING     {h_swing:6.1f} deg  (2 s, 免基线)",
                         (255, 120, 0) if head_on else (90, 240, 90)),
                        (f"YAWN      " + (f"YES" if yawn_on else "  -")
                         + (f"  L2={l2}" if l2 else ""),
                         (0, 120, 255) if yawn_on else (150, 150, 150)),
                        (f"EYE       " + (f"YES {eye_sec:4.1f}s" if eye_on else "  -"),
                         (0, 160, 255) if eye_on else (150, 150, 150)),
                        (f"HEAD      " + (f"YES {h_swing:4.1f}°" if head_on else "  -"),
                         (255, 120, 0) if head_on else (150, 150, 150)),
                        (f"P(fat)    {p_fat:6.3f}" if np.isfinite(p_fat)
                         else "P(fat)        -", (255, 200, 90)),
                        (f"-> L{l_fused}  <{src_of_level}>  ({pm:.1f} ms)",
                         LEVEL_COLOR[l_fused]),
                    ]
                # 标记行放在两条分支**之外**：热身期间（st is None）也要能看见
                # 自己标没标上 —— 那一段恰恰最需要确认键按对了。
                # ⚠️ 屏上文字只能 ASCII：cv2.putText 画不出中文，会糊成一串'?'。
                fl.append((f"MARK      {'ON' if mark_on else '  -'}",
                           (255, 0, 255) if mark_on else (130, 130, 130)))
                panel(vis, fl, max(10, vis.shape[1] - 330), 120)
                draw_curve(vis, list(en_hist), BLINK_THR, vis.shape[0] - 120,
                           120)
                # 归一化后的 EAR 是 NaN = 缓冲末尾那几帧压根没检到脸。
                # 判 st 而不是判 en_hist[-1]：st 为 None 是"还没热身"，
                # 那是 WARMING 的事，不该在这画 NO FACE。
                if st is not None and not np.isfinite(st["en_now"]):
                    cv2.putText(vis, "NO FACE", (12, vis.shape[0] - 130),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2,
                                cv2.LINE_AA)

            if display:
                cv2.imshow("fuse", vis)
                k = cv2.waitKey(1) & 0xFF
                if k in (27, ord("q")):
                    break
                if k == ord(" "):
                    mark_on = not mark_on
                    n_mark += 1
                    # 打点到终端：CSV 是 10 Hz 采样，标记边界落在哪一秒只有这条
                    # 打印能对上（这也是 _scratch/live_face.py:637 的做法）。
                    print(f"  ★ 标记 {'ON ' if mark_on else 'OFF'}  "
                          f"t={mt:6.1f}s  （第 {n_mark} 次切换）")
                    if log_fp:
                        # 标记点顺手 flush：真跑崩了也能保住到标记处为止的日志，
                        # 而标记边界正是复盘时最想留的那几行。
                        log_fp.flush()
    except KeyboardInterrupt:
        print("\n用户中断。")
    finally:
        src.release()
        if log_fp:
            log_fp.close()          # os._exit 不会帮你 flush，所以显式关

    dt = time.perf_counter() - t0
    print(f"\n跑了 {dt:.1f} s   喂帧 {n_fed}（重复 {n_dup}）  丢失 {n_lost}   "
          f"决策 {n_infer} 次")
    print(f"末级 L{light.level} {LEVEL_CN[light.level]}   "
          f"语音 {tts.spoken} 条（丢弃 {tts.dropped}）")
    if face is not None:
        print(f"支路二  检到脸 {n_face} / 丢失 {n_face_lost}"
              f"（{100 * n_face / max(1, n_face + n_face_lost):.1f}%）   "
              f"闸门开 {n_gate_open}/{n_decide}"
              f"  闭眼 {n_eye}  低头 {n_head}"
              f"（{100 * n_gate_open / max(1, n_decide):.0f}%）")
        print(f"        抬级 {n_b2_up} 次   哈欠 {n_yawn} 次   "
              f"推理 {float(np.median(py_ms)) if py_ms else 0:.2f} ms")
        # 标记数要报出来：L4 判决最硬的一节全靠它，按了 0 次等于白跑一趟。
        print(f"        空格标记 {n_mark} 次"
              + ("" if log_fp else "   ⚠️ 但没开 --log-probs，标记没被记下来"))
        if n_mark % 2:
            print("        ⚠️ 结尾停在第奇数次切换 = 还处于标记 ON，"
                  "最后那一段的边界只能靠终端那行打印来补。")

    if tts.last_error:
        print(f"  [warn] 语音报错：{tts.last_error}")
    if light.send_error:
        print(f"  [warn] 串口：{light.send_error}")
    if n_fed and n_dup / n_fed > 0.5:
        print("  [warn] 超过一半的喂帧是重复的——摄像头比 15 Hz 慢太多，"
              "时间轴是对的但数据很粗糙，建议补光或调小分辨率")

    # 必须是 main() 的最后一行：现在有**两个** landmarker，各自析构固定 42 秒，
    # 而 pose / face 是 main() 的局部变量，main() 一返回它们就开始析构。
    # os._exit 永不返回 => 函数不返回 => 不析构。见 src/pose.py 的 close()。
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


def load_branch2(path=None):
    """加载支路二模型，并核对它训练时的常量与 `src/face.py` 当前的一致。

    这一步不是形式主义：特征口径改一处（比如 NORM_Q 从 50 改 75、BLINK_THR
    从 0.84 改 0.80），旧权重就会静默降级 —— 不报错，只是概率整体偏。
    当年 `_scratch/live_face.py` 的笔记本上专门写过这句：
    「换归一化必须重标定，不能沿用」。
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    import face as F

    p = Path(path) if path else (C.MODELS_DIR / "branch2_lr.npz")
    if not p.exists():
        raise SystemExit(f"找不到支路二权重 {p}\n先跑 tools/fit_branch2.py 生成它。")
    z = np.load(p, allow_pickle=True)
    need = tuple(str(x) for x in z["features"])
    cur = dict(ROLL_WIN=F.ROLL_WIN, NORM_Q=F.NORM_Q, BLINK_THR=F.BLINK_THR,
               YAWN_THR=F.YAWN_THR, YAWN_MIN=F.YAWN_MIN, NOD_DROP=F.NOD_DROP,
               NOD_MIN=F.NOD_MIN, WIN_SEC=F.WIN_SEC)
    if "const" in z.files:
        for k, v in dict(z["const"].tolist()).items():
            if k in cur and abs(float(v) - float(cur[k])) > 1e-9:
                print(f"  [warn] 支路二权重的 {k}={v} 与 face.py 现在的 "
                      f"{cur[k]} 不一致 —— 特征口径变了，"
                      f"概率会静默偏。重跑 tools/fit_branch2.py。")
    if need != tuple(F.FEATURE_NAMES):
        print(f"  [warn] 权重用的是特征列 {need}，face.py 是 {F.FEATURE_NAMES}")

    m = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=2000))
    m[0].mean_ = np.asarray(z["mean"], float)
    m[0].scale_ = np.asarray(z["scale"], float)
    m[0].n_features_in_ = len(need)
    m[1].coef_ = np.asarray(z["coef"], float)
    m[1].intercept_ = np.asarray(z["intercept"], float)
    m[1].classes_ = np.array([0, 1])
    m[1].n_features_in_ = len(need)
    return m


if __name__ == "__main__":
    main()
