"""实时推理主程序：摄像头 -> 骨骼 -> 4 秒滑窗 -> Transformer -> 分级预警。

三个必须守住的点，每个都对应一个已经踩过的坑：

1. **滑窗按 15 Hz 的墙上时钟节拍喂，不是"来一帧喂一帧"。**
   本机摄像头实测只有 10~11 fps，比 15 Hz 还慢。若来一帧塞一帧，60 帧窗口
   就变成 5.5 秒而不是 4 秒，和训练时的窗口长度对不上——而录制的视频已经按
   4 秒切好了，等于训练和推理处在两个时间尺度上。做法与 `record.ClipRecorder`
   完全对称：到点就取"当前最新的一帧"，摄像头慢就自然重复帧。

2. **归一化要在线复现训练时那一套**（原点=肩中点、尺度=3D 肩宽滑动中位数）。
   离线在 `build_dataset.normalize_sequence`，在线在 `OnlineNormalizer`。
   这是**唯一一处有意为之的差异**：训练时 `center=True` 能看到未来 7 帧，
   实时看不到。别假装两者完全相同，见 `OnlineNormalizer` 的注释。

3. **预警级别不能每帧都翻，要迟滞。** 阈值迟滞（进入 0.60 / 退出 0.40）
   加时间迟滞（升级 0.6 s / 降级 2.0 s）。没有这一层，现场灯光会随头部
   微动乱闪，看着像坏了。

用法：

    python src/live.py                        # 摄像头实时
    python src/live.py --replay a.mp4         # 回放视频（按视频自己的时间轴）
    python src/live.py --replay a.mp4 --fast  # 回放但不睡，尽快跑完（调试用）
    python src/live.py --no-voice --no-display

⚠️ `--replay` 走的是**和摄像头完全同一条**推理路径（同一个 extractor、同一个
15 Hz 调度器、同一个状态机），只是帧的来源不同。这是现场摄像头出问题时的
兜底方案，也是唯一能在没有摄像头的情况下把整条链路测一遍的办法。
"""

import argparse
import collections
import os
import queue
import subprocess
import sys
import threading
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
from model import PoseTransformer
from pose import PoseExtractor
from record import draw_hud, draw_pose, GREEN, RED, YELLOW, WHITE


# ---------------------------------------------------------------- 预警级别
# 级别升序 = 严重度升序。CLASS_LEVEL 把 4 个类别映到 0~3。
LEVEL_CN = ["正常", "注意", "警告", "紧急"]
LEVEL_NOTE = ["", "检测到视线偏移", "检测到持续低头看手机", "检测到疲劳驾驶"]
LEVEL_COLOR = [(60, 190, 60), (0, 215, 255), (0, 140, 255), (0, 0, 235)]  # BGR
LEVEL_BLINK = [0.0, 1.2, 3.0, 6.0]      # Hz，0 = 不闪
CLASS_LEVEL = {"normal": 0, "glance": 1, "phone": 2, "fatigue": 3}
# 只有 >= SPEAK_FROM 级才出声。1 级（偶尔瞟一眼后视镜）出声会把人烦死。
SPEAK_FROM = 2

# 迟滞参数的默认值。改过一轮：原本是 0.6/2.0/0.30/5Hz，用户实测"延迟太长"，
# 用 tools/lag_breakdown.py 量出来这几项加起来值 0.8 秒（升 3.7s -> 2.9s，
# 降 6.5s -> 5.0s），而剩下 2.9 秒是模型的概率爬升、只能靠缩短窗口砍。
# 提速后 24 个片段级别仍然全对、零误报（normal 片段最坏非真值概率 0.389，
# 只有阈值的 0.65 倍），所以放心调快。
ENTER_TH = 0.60         # 升级所需概率
EXIT_TH = 0.40          # 维持/降级阈值（迟滞下沿，比 ENTER_TH 低 0.2）
ENTER_SEC = 0.25        # 升级前要稳定这么久（原 0.6）
EXIT_SEC = 1.0          # 降级前要稳定这么久（原 2.0，故意比升级慢）
EMA_ALPHA = 0.55        # 概率指数平滑（原 0.30）
DECIDE_HZ = 10.0        # 状态机决策频率（原 5 Hz）
VOICE_COOLDOWN = 6.0    # 同一级别最快多久重念一次


class Hysteresis:
    """迟滞的全部旋钮。做成对象而不是散落的模块常量，是为了现场能边看边调。

    这六个数的默认值都能从命令行覆盖（`--enter-th` 等），因为"反应快不快"
    这件事**必须在现场对着真人调**：模型在录制数据上峰值 0.9 以上，
    在活人身上可能只有 0.6，同一组阈值在两种输入下的表现差远了。
    改代码重跑一轮要几分钟，现场没有这个时间。
    """

    def __init__(self, enter_th=ENTER_TH, exit_th=EXIT_TH, enter_sec=ENTER_SEC,
                 exit_sec=EXIT_SEC, alpha=EMA_ALPHA, decide_hz=DECIDE_HZ):
        self.enter_th = enter_th
        self.exit_th = exit_th
        self.enter_sec = enter_sec
        self.exit_sec = exit_sec
        self.alpha = alpha
        self.decide_hz = decide_hz

    @property
    def decide_dt(self):
        return 1.0 / self.decide_hz

    def __str__(self):
        return (f"进{self.enter_th:.2f}/退{self.exit_th:.2f} "
                f"α={self.alpha:.2f} {self.decide_hz:.0f}Hz "
                f"升{self.enter_sec:.2f}s/降{self.exit_sec:.2f}s")


def target_level(ema, cur, h):
    """按概率算出"证据支持的级别"。

    当前级别用较低的 EXIT_TH 判定（这样不会因为概率在 0.5 附近抖就掉级），
    比当前更严重的级别用较高的 ENTER_TH（要升上去得更有把握）。
    这一上一下的不对称就是阈值迟滞。
    """
    t = 0
    for k, cls in enumerate(C.CLASSES):
        lv = CLASS_LEVEL[cls]
        if lv == 0:
            continue
        th = h.exit_th if lv <= cur else h.enter_th
        if ema[k] > th:
            t = max(t, lv)
    return t


class WarningState:
    """概率 -> 级别。两级迟滞（阈值 + 时间），升级立刻、降级要等。"""

    def __init__(self, h=None):
        self.h = h or Hysteresis()
        self.ema = np.full(len(C.CLASSES), 1.0 / len(C.CLASSES), np.float64)
        self.level = 0
        self._pend = -1
        self._pend_t = 0.0
        self.spoken_at = {}          # 级别 -> 上次发声时刻
        self.updates = 0

    def update(self, probs, now):
        """返回 (级别, 是否刚升到新级别)。"""
        h = self.h
        self.ema = h.alpha * probs + (1.0 - h.alpha) * self.ema
        self.updates += 1
        tgt = target_level(self.ema, self.level, h)
        prev = self.level
        if tgt == self.level:
            self._pend = -1
            return self.level, False

        if tgt != self._pend:                  # 换了目标，计时重来
            self._pend, self._pend_t = tgt, now
            return self.level, False

        need = h.enter_sec if tgt > self.level else h.exit_sec
        if now - self._pend_t < need:
            return self.level, False

        self.level = tgt
        self._pend = -1
        return self.level, self.level > prev

    def should_speak(self, level, now):
        """升级到新级别必定出声；同一级别按冷却时间重念。"""
        if level < SPEAK_FROM:
            return False
        last = self.spoken_at.get(level)
        if last is not None and now - last < VOICE_COOLDOWN:
            return False
        self.spoken_at[level] = now
        return True


# ---------------------------------------------------------------- 在线归一化
class OnlineNormalizer:
    """(33,4) -> (132,) 归一化特征，与 build_dataset.normalize_sequence 同源。

    训练时的尺度平滑是 `rolling(15, center=True).median()`，会看到**未来** 7 帧；
    实时只能用过去 15 帧的滑动中位数。这是离线/在线**唯一一处有意为之的差异**。

    为什么可以接受：肩宽是慢变量（人不会在一秒内忽远忽近），15 帧窗口里挪动
    7 帧对中位数的影响远小于肩宽本身的检测抖动。而且两者用的都是**中位数**，
    对毛刺的鲁棒性一样。

    如果哪天发现现场表现异常，第一个该查的就是这里——把它改成因果的
    （`center=False`）重训一遍即可，代价是重跑一次提取和训练。
    """

    def __init__(self):
        self.scale_hist = collections.deque(maxlen=C.SCALE_SMOOTH_WIN)

    def push(self, lm):
        xyz = lm[:, :3].astype(np.float64)
        origin = (xyz[C.L_SHOULDER] + xyz[C.R_SHOULDER]) * 0.5
        raw = float(np.linalg.norm(xyz[C.L_SHOULDER] - xyz[C.R_SHOULDER]))
        self.scale_hist.append(max(raw, 1e-4))
        scale = max(float(np.median(self.scale_hist)), 1e-4)
        norm = (xyz - origin) / scale
        return np.concatenate([norm, lm[:, 3:4]],
                              axis=1).reshape(-1).astype(np.float32)

    def reset(self):
        self.scale_hist.clear()


# ---------------------------------------------------------------- 语音
class TTSWorker:
    """后台线程念稿，**绝不阻塞推理循环**。

    走 PowerShell 的 System.Speech：零依赖（pywin32 / pyttsx3 本机都没装），
    实测一条 3.3 秒——大部分是朗读本身的时长。因为在线程里跑，多慢都无所谓。

    队列有界且满就丢：宁可少念一句，也不能让念稿把滑窗喂帧拖住。
    """

    def __init__(self, rate=2, enabled=True):
        self.enabled = enabled
        self.rate = rate
        self.q = queue.Queue(maxsize=2)
        self.spoken = 0
        self.dropped = 0
        self.last_error = None
        if enabled:
            threading.Thread(target=self._run, daemon=True).start()

    def say(self, text):
        if not self.enabled:
            return
        try:
            self.q.put_nowait(text)
        except queue.Full:
            self.dropped += 1

    def _run(self):
        while True:
            text = self.q.get()
            # 单引号在 PowerShell 里靠翻倍转义；念的稿子都是固定常量，
            # 但别养成不转义就往 shell 里拼字符串的习惯。
            safe = str(text).replace("'", "''")
            ps = ("Add-Type -AssemblyName System.Speech; "
                  "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                  "try { $s.SelectVoice('Microsoft Huihui Desktop') } catch {}; "
                  f"$s.Rate = {int(self.rate)}; $s.Speak('{safe}')")
            try:
                subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                               timeout=20, capture_output=True)
                self.spoken += 1
            except Exception as e:                      # 出声失败不该拖垮主循环
                self.last_error = f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------- 灯光输出
class LightOutput:
    """分级灯光。现在只有屏幕模拟，硬件到了加一个串口实现。

    级别**变化时**调用 set_level()——将来接 Arduino 就发在这里，
    不要每帧都发，串口受不了，也没必要。
    """

    def __init__(self, serial_port=None, baud=115200, enabled=True):
        self.level = 0
        self.changed_at = time.perf_counter()
        self.enabled = enabled
        self.ser = None
        self.send_error = None
        if serial_port:
            try:
                import serial
                self.ser = serial.Serial(serial_port, baud, timeout=0.05)
                time.sleep(1.5)      # Arduino 复位后要等一下才能收命令
            except Exception as e:
                self.send_error = f"串口打不开 {serial_port}: {e}"
                print(f"  [warn] {self.send_error}，退回屏幕模拟")

    def set_level(self, level, now):
        if level == self.level:
            return
        self.level = level
        self.changed_at = now
        if self.ser is not None:
            try:
                self.ser.write(f"L{level}\n".encode())
            except Exception as e:
                self.send_error = f"串口写失败: {e}"

    def blink_on(self, now):
        """当前级别在这一瞬间该亮还是灭。0 Hz = 常亮。"""
        f = LEVEL_BLINK[self.level]
        if f <= 0:
            return True
        return (now - self.changed_at) * f % 1.0 < 0.5

    def draw(self, bgr, now, height=46):
        """在画面顶部画一条色带，模拟灯带。"""
        h, w = bgr.shape[:2]
        col = LEVEL_COLOR[self.level]
        on = self.blink_on(now)
        band = (col if on else (int(col[0] * 0.18), int(col[1] * 0.18),
                                int(col[2] * 0.18)))
        cv2.rectangle(bgr, (0, 0), (w, height), band, -1)
        txt = f" LIGHT L{self.level}  {LEVEL_CN[self.level]} "
        if LEVEL_BLINK[self.level] > 0:
            txt += f"{LEVEL_BLINK[self.level]:.1f} Hz "
        cv2.putText(bgr, txt, (12, height - 14), cv2.FONT_HERSHEY_SIMPLEX,
                    0.72, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(bgr, txt, (12, height - 14), cv2.FONT_HERSHEY_SIMPLEX,
                    0.72, (255, 255, 255), 1, cv2.LINE_AA)
        return height


# ---------------------------------------------------------------- 帧来源
class CameraSource:
    """摄像头。media_time() = 真实流逝的秒数。"""

    def __init__(self, cam=0, size=(1280, 720)):
        self.cap = cv2.VideoCapture(cam, cv2.CAP_DSHOW)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, size[0])
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, size[1])
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.frames = 0
        self.t0 = None
        if not self.cap.isOpened():
            raise RuntimeError(f"打不开摄像头 {cam}")

    def read(self):
        ok, frame = self.cap.read()
        if not ok or frame is None:
            return None, False
        # 第一帧到手才开始计时，别把摄像头启动开销算进时间轴
        if self.t0 is None:
            self.t0 = time.perf_counter()
        self.frames += 1
        return frame, True

    def media_time(self):
        return 0.0 if self.t0 is None else time.perf_counter() - self.t0

    def release(self):
        self.cap.release()


class VideoSource:
    """回放视频。按视频自己的帧率配速，除非 --fast。

    media_time() 返回**视频自己的时间轴**，不是墙上时间。这个区分很要紧：
    `--fast` 只跳过配速，墙上时间就不再和视频时间一致了；如果调度器读墙上
    时钟，`--fast` 下 60 帧窗口会横跨大半个片段，等于在测一个假的配置。
    跟着帧源的时间轴走，`--fast` 才是"把整段视频快速过一遍完整链路"，
    结果和实速回放**逐帧一致**，只是快。

    重采样本身由上层那个 15 Hz 调度器做，和摄像头走的是同一条路径。
    """

    def __init__(self, path, fast=False):
        self.cap = cv2.VideoCapture(str(path))
        if not self.cap.isOpened():
            raise RuntimeError(f"打不开视频 {path}")
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.n = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fast = fast
        self.frames = 0
        self.t0 = time.perf_counter()

    def read(self):
        ok, frame = self.cap.read()
        if not ok or frame is None:
            return None, False
        self.frames += 1
        if not self.fast and self.fps > 1:
            lag = self.frames / self.fps - (time.perf_counter() - self.t0)
            if lag > 0:
                time.sleep(lag)
        return frame, True

    def media_time(self):
        return (self.frames - 1) / self.fps if self.fps > 1 else 0.0

    def release(self):
        self.cap.release()


# ---------------------------------------------------------------- 主循环
def find_model(explicit=None):
    if explicit:
        return Path(explicit)
    runs = sorted((p for p in (ROOT / "runs").iterdir() if p.is_dir()),
                  key=lambda p: p.stat().st_mtime)
    for d in reversed(runs):
        if (d / "best.pt").exists():
            return d / "best.pt"
    raise FileNotFoundError("runs/ 下没有 best.pt，先跑 src/train.py")


def load_infer_model(path, device="cpu"):
    # 自己存的权重含 numpy 标量，weights_only=True 会拒收
    sd = torch.load(path, map_location=device, weights_only=False)
    model = PoseTransformer(**sd["model_kwargs"]).to(device)
    model.load_state_dict(sd["state_dict"])
    model.eval()
    # 窗口长度从**权重**里读，不从 config 读。config.WINDOW 和权重不一致时
    # （改了 config 但没重训，或者反过来），用 config 会拿 60 帧喂给 45 帧的
    # 模型——报的错是形状不匹配，但根因看不出来。权重才是唯一事实来源。
    return (model, sd["feat_mean"], sd["feat_std"],
            sd.get("classes", C.CLASSES), int(sd["model_kwargs"]["window"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None, help="默认 runs/ 下最新的 best.pt")
    ap.add_argument("--cam", type=int, default=0)
    ap.add_argument("--replay", default=None, help="回放视频而不是开摄像头")
    ap.add_argument("--fast", action="store_true", help="回放时不按真实时间配速")
    ap.add_argument("--no-display", action="store_true")
    ap.add_argument("--no-voice", action="store_true")
    ap.add_argument("--serial", default=None, help="灯带串口，如 COM3")
    ap.add_argument("--pose-model", default=None, help="lite / full")
    ap.add_argument("--quiet", action="store_true", help="不打印每帧决策")
    ap.add_argument("--seconds", type=float, default=None,
                    help="跑满这么多秒自动停（测试和现场限时演示用）")
    # ---- 迟滞旋钮：现场对着真人调，不用改代码重跑 ----
    ap.add_argument("--enter-th", type=float, default=ENTER_TH,
                    help=f"升级所需概率，默认 {ENTER_TH}")
    ap.add_argument("--exit-th", type=float, default=EXIT_TH,
                    help=f"降级阈值，默认 {EXIT_TH}")
    ap.add_argument("--enter-sec", type=float, default=ENTER_SEC,
                    help=f"升级前需稳定的秒数，默认 {ENTER_SEC}；调小=反应更快")
    ap.add_argument("--exit-sec", type=float, default=EXIT_SEC,
                    help=f"降级前需稳定的秒数，默认 {EXIT_SEC}")
    ap.add_argument("--alpha", type=float, default=EMA_ALPHA,
                    help=f"概率 EMA 系数，默认 {EMA_ALPHA}；调大=反应更快但更抖")
    ap.add_argument("--decide-hz", type=float, default=DECIDE_HZ,
                    help=f"状态机决策频率，默认 {DECIDE_HZ}")
    ap.add_argument("--log-probs", default=None,
                    help="把逐次决策写进 CSV，现场跑完可以回来看概率到底涨到多高")
    args = ap.parse_args()

    ckpt_path = find_model(args.model)
    model, feat_mean, feat_std, classes, window = load_infer_model(ckpt_path)
    if list(classes) != list(C.CLASSES):
        print(f"  [warn] 权重里的类别 {classes} 与 config.CLASSES {C.CLASSES} 不一致")
    if window != C.WINDOW:
        print(f"  [warn] 权重是按 {window} 帧窗口训的，config.WINDOW 是 "
              f"{C.WINDOW} —— 按权重走。要一致就改 config 后重训。")
    print(f"模型 {ckpt_path.name}  参数 {model.n_params():,}  "
          f"窗口 {window} 帧 = {window / C.TARGET_FPS:.1f} s")

    hyst = Hysteresis(args.enter_th, args.exit_th, args.enter_sec,
                      args.exit_sec, args.alpha, args.decide_hz)
    print(f"迟滞 {hyst}")
    if args.log_probs:
        print(f"逐次决策 -> {args.log_probs}")

    norm = OnlineNormalizer()
    state = WarningState(hyst)
    tts = TTSWorker(enabled=not args.no_voice)
    light = LightOutput(serial_port=args.serial)
    ring = collections.deque(maxlen=window)

    pose = PoseExtractor(args.pose_model, running_mode="VIDEO")
    if args.replay:
        src = VideoSource(args.replay, fast=args.fast)
        print(f"回放 {args.replay}  {src.n} 帧 @ {src.fps:.1f} fps"
              + ("  [fast]" if args.fast else ""))
    else:
        src = CameraSource(args.cam)
        print(f"摄像头 {args.cam}  按 15 Hz 节拍取最新帧")

    feed_dt = 1.0 / C.TARGET_FPS
    decide_dt = hyst.decide_dt
    display = not args.no_display
    log_fp = open(args.log_probs, "w", encoding="utf-8", newline="") \
        if args.log_probs else None
    if log_fp:
        log_fp.write("t," + ",".join(C.CLASSES) + ",level\n")

    last_lm = None
    last_lm_id = -1          # last_lm 是哪一帧取到的，用来数重复喂帧
    fed_id = -1
    next_feed = 0.0
    next_decide = 0.0
    first = True
    n_fed = 0
    n_dup = 0
    n_lost = 0
    n_infer = 0
    infer_ms = collections.deque(maxlen=60)
    probs = np.full(len(C.CLASSES), 1.0 / len(C.CLASSES))
    frame_id = 0

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
            mt = src.media_time()      # 媒体时间：逻辑一律用它，不用墙上时间
            frame_id += 1

            lm = pose.detect(frame, mt * 1000.0)
            if lm is None:
                n_lost += 1
            else:
                last_lm, last_lm_id = lm, frame_id

            # ---- 15 Hz 节拍：到点就取"当前最新的一帧" ----
            # 摄像头/视频慢就自然重复帧，快就丢帧。窗口长度因此恒为 4 秒，
            # 与训练时严格一致。这一段是 record.ClipRecorder 的镜像。
            if first:
                next_feed = mt             # 别把启动开销算成一片积压
                next_decide = mt
                first = False
            elif next_feed < mt - 0.5:
                next_feed = mt             # 卡顿后重新对表，避免一次性补几百帧
            while next_feed <= mt:
                if last_lm is not None:
                    ring.append(norm.push(last_lm))
                    n_fed += 1
                    if last_lm_id == fed_id:
                        n_dup += 1
                    fed_id = last_lm_id
                next_feed += feed_dt

            # ---- 决策（不必每帧，5 Hz 足够且更稳）----
            if len(ring) == window and mt >= next_decide:
                next_decide = mt + decide_dt
                x = np.asarray(ring, np.float32)
                x = (x - feat_mean) / feat_std
                with torch.no_grad():
                    ti = time.perf_counter()
                    probs = torch.softmax(
                        model(torch.from_numpy(x[None])), dim=1)[0].numpy()
                    infer_ms.append((time.perf_counter() - ti) * 1000)
                n_infer += 1
                lv, _rose = state.update(probs, mt)
                light.set_level(lv, mt)
                if log_fp:
                    log_fp.write(f"{mt:.3f},"
                                 + ",".join(f"{v:.4f}" for v in probs)
                                 + f",{lv}\n")
                if not args.quiet:
                    # 决策用的是 EMA 而不是原始概率，所以两个都打出来。
                    # 调阈值时盯的是 EMA：它才是跟 enter_th 比的那个数。
                    top = int(np.argmax(state.ema))
                    print(f"  [{mt:6.1f}s] L{lv} {LEVEL_CN[lv]:<2}"
                          f"  " + " ".join(f"{c[:3]}={probs[k]:.2f}"
                                           for k, c in enumerate(C.CLASSES))
                          + f"   ema({C.CLASSES[top][:3]})={state.ema[top]:.2f}")
                if state.should_speak(lv, mt):
                    why = LEVEL_NOTE[lv] or LEVEL_CN[lv]
                    if not args.quiet:
                        print(f"  [{mt:6.1f}s] >>> 语音：{why}")
                    tts.say(why)

            # ---- HUD ----
            # 构造和渲染**刻意分开**：--no-display / --fast 下也要走一遍构造。
            # record.py 里因为把两者合在一个 if display: 里，漏掉过一个
            # AttributeError（HUD 取了不存在的属性，一按空格就崩）。
            vis = frame.copy()
            if last_lm is not None:
                draw_pose(vis, last_lm)
            y0 = light.draw(vis, mt)
            native = frame_id / wall if wall > 0 else 0.0
            bars = "  ".join(
                f"{c[:3]}:{probs[k]:.2f}" for k, c in enumerate(C.CLASSES))
            ms = float(np.median(infer_ms)) if infer_ms else 0.0
            lines = [
                (f"{bars}", WHITE),
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
            if display:
                cv2.imshow("live", vis)
                if (cv2.waitKey(1) & 0xFF) in (27, ord("q")):
                    break
    except KeyboardInterrupt:
        print("\n用户中断。")
    finally:
        src.release()
        if log_fp:
            log_fp.close()          # os._exit 不会帮你 flush，所以显式关

    dt = time.perf_counter() - t0
    print(f"\n跑了 {dt:.1f} s   喂帧 {n_fed}（其中重复 {n_dup}）  "
          f"丢失 {n_lost}   推理 {n_infer} 次")
    print(f"末级 L{state.level} {LEVEL_CN[state.level]}   "
          f"语音 {tts.spoken} 条（丢弃 {tts.dropped}）")
    if tts.last_error:
        print(f"  [warn] 语音报错：{tts.last_error}")
    if light.send_error:
        print(f"  [warn] 串口：{light.send_error}")
    if n_fed and n_dup / n_fed > 0.5:
        print("  [warn] 超过一半的喂帧是重复的——摄像头比 15 Hz 慢太多，"
              "时间轴是对的但数据很粗糙，建议补光或调小分辨率")

    # 必须是 main() 的最后一行：mediapipe 的 landmarker 析构固定 42 秒，
    # 而 pose 是 main() 的局部变量，main() 一返回它就开始析构。
    # os._exit 永不返回 => 函数不返回 => 不析构。见 src/pose.py 的 close()。
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


def draw_hud_offset(bgr, lines, y0):
    """把 record.draw_hud 整体下移 y0 像素，免得压在灯带上。

    draw_hud 的起始 y 写死在它自己里面，所以这里先画到一张空的同尺寸画布上，
    再把非零像素搬到目标位置。用 mask 而不是整块覆盖，否则会把骨架擦掉。
    """
    tmp = np.zeros_like(bgr)
    draw_hud(tmp, lines)
    m = tmp.any(axis=2)
    h = min(bgr.shape[0] - y0, tmp.shape[0])
    if h <= 0:
        return
    dst, src_m = bgr[y0:y0 + h], m[:h]        # 基本切片 -> 视图，能写回去
    dst[src_m] = tmp[:h][src_m]


if __name__ == "__main__":
    main()
