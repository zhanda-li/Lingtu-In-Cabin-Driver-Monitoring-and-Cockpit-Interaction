"""摄像头录制工具：边录边叠加骨骼，时间轴按真实秒对齐。

为什么需要它：录完再跑 extract_pose.py 才发现"人只占画面一角"或者
"光线太暗一半帧检测不到"，等于白录一轮。这个工具在预览里就把骨骼画出来，
检测率、关键点置信度、画面亮度实时显示，不合格当场重录。

关于帧率（**重要，别改回去**）：
    摄像头的实际帧率是**被自动曝光牵着走**的——光线暗，曝光时间就变长，
    帧率跟着掉。同一个摄像头实测：光线正常 30 fps、偏暗 10 fps、
    镜头完全被遮住（画面全黑）1 fps。而 cv2.VideoWriter 的帧率必须在
    建 writer 时写死，多数教程就是在这里直接填摄像头的名义帧率——
    结果是**视频的时间轴撒谎**：录 25.2 秒只存了 8.4 秒的画面（3 倍速）。

    这个谎言的后果是全链路失效：extract_pose.py 按视频帧率抽帧、
    config.WINDOW=60 帧被设计成 4 秒（一个完整的疲劳点头周期），
    一旦视频被加速，60 帧就不是 4 秒了，"疲劳点头"和"持续低头"
    就分不开——而这两类恰好都是重度风险的触发条件。

    所以这里**不信任摄像头的名义帧率**：录制过程中按墙上时钟把画面
    重采样到 config.TARGET_FPS（不够就重复上一帧，多了就丢），
    最后按 TARGET_FPS 写盘。视频时间轴因此严格等于真实时间，
    "60 帧 = 4 秒"在任何光照条件下都成立。

    帧先编码成 JPEG 存在内存里，停止时才写盘——因为真实时长只有录完
    才知道，而 mp4 的帧率必须提前定。20 秒的片段约 45 MB 内存，可接受。

用法：
    python tools/record.py
    python tools/record.py --cam 0 --size 1280x720
    python tools/record.py --selftest      # 不用摄像头，验时间轴对齐
    python tools/record.py --test-frames 60 --no-display   # 摄像头冒烟测试

按键：
    1 / 2 / 3 / 4   切换当前要录的类别
    空格            开始 / 结束一段录制（开始前有 3 秒倒计时）
    s               开关骨骼叠加显示
    q / ESC         退出

录好的视频存到 data/raw/<类别>/<类别>_NN.mp4，直接用 extract_pose.py 处理。
"""

import argparse
import os
import sys
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
import config as C
from pose import PoseExtractor

_T_START = time.perf_counter()   # 进程起点，用于 --test-frames 的分段计时
_T_TEST_TIMING = False           # 只在 --test-frames 下打开

# MediaPipe Pose 骨架连线（33 点）
POSE_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 7), (0, 4), (4, 5), (5, 6), (6, 8), (9, 10),
    (11, 12), (11, 13), (13, 15), (15, 17), (15, 19), (15, 21), (17, 19),
    (12, 14), (14, 16), (16, 18), (16, 20), (16, 22), (18, 20),
    (11, 23), (12, 24), (23, 24), (23, 25), (24, 26), (25, 27), (26, 28),
    (27, 29), (28, 30), (29, 31), (30, 32), (27, 31), (28, 32),
]

# 参与"画面能不能用"判定的关键点分组。
# 别拿全部 33 个点取最小值：坐着拍上半身时腿脚本来就在画面外，
# 置信度必然是 0，那样判据会恒假，把好素材全判成"建议重录"。
LM_HEAD = list(range(0, 11))      # 头面部：四类动作全靠它
LM_SHOULDER = [11, 12]            # 双肩：归一化的基准，丢了整个特征就没意义
LM_HAND = list(range(15, 23))     # 手部：只有 phone 类需要（要举着手机）

# 画面亮度的告警线（0-255 均值）。低于这个值基本是镜头被挡住或没开灯。
LUM_DARK = 40.0

# 缓冲安全阀：正常 10~20 秒的片段只用到 300 帧左右，这个值只是防止
# 万一忘了停止录制把内存吃光。
MAX_BUFFER_FRAMES = 3000

GREEN, RED, YELLOW, WHITE, GREY = ((0, 220, 0), (0, 0, 255), (0, 210, 255),
                                   (255, 255, 255), (170, 170, 170))


def draw_pose(bgr, lm, thr=C.VIS_THRESHOLD):
    """在图上画骨骼。置信度不达标的点画成红色，直观看出哪里丢了。"""
    h, w = bgr.shape[:2]
    pts = [(int(lm[i, 0] * w), int(lm[i, 1] * h)) for i in range(C.NUM_LANDMARKS)]
    for a, b in POSE_CONNECTIONS:
        if lm[a, 3] >= thr and lm[b, 3] >= thr:
            cv2.line(bgr, pts[a], pts[b], GREEN, 2, cv2.LINE_AA)
    for i, (x, y) in enumerate(pts):
        cv2.circle(bgr, (x, y), 3, GREEN if lm[i, 3] >= thr else RED, -1, cv2.LINE_AA)


def draw_hud(bgr, lines):
    """叠字。先描黑边再上色，保证在任何背景上都看得清。"""
    y = 26
    for txt, col in lines:
        cv2.putText(bgr, txt, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(bgr, txt, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.62, col, 1, cv2.LINE_AA)
        y += 28


def next_path(cls):
    """给这一类的下一段起名，挑最小的没被占用的编号。"""
    d = C.DATA_RAW / cls
    d.mkdir(parents=True, exist_ok=True)
    used = set()
    for p in d.glob(f"{cls}_*.mp4"):
        tail = p.stem.rsplit("_", 1)[-1]
        if tail.isdigit():
            used.add(int(tail))
    i = 0
    while i in used:
        i += 1
    return d / f"{cls}_{i:02d}.mp4"


class ClipRecorder:
    """按墙上时钟把摄像头帧重采样到 target_fps，停止时一次性写盘。

    摄像头给多少帧不重要：这里只关心"从开始录到现在过了多少真实秒"，
    到点就从最近一帧取一份输出。摄像头快于目标就丢帧，慢于目标就重复，
    两种情况视频的时间轴都等于真实时间。
    """

    def __init__(self, path, size, target_fps):
        self.path = Path(path)
        self.size = (int(size[0]), int(size[1]))
        self.target_fps = float(target_fps)

        self.buf = []                 # 逐输出帧的 JPEG 字节
        self.t0 = time.perf_counter()
        self.next_out = 0.0           # 下一个输出帧对应的时刻（秒）
        self.n_captured = 0
        self.n_out = 0
        self.overflow = 0             # 撞到安全阀丢掉的输出帧数

        self._src_id = -1
        self._jpg = None

        # 质量统计
        self.det_all = 0
        self.det_ok = 0
        self.vis_head = 1.0
        self.vis_shoulder = 1.0
        self.vis_hand = 1.0
        self.lum_sum = 0.0
        self.lum_min = 255.0

    # -- 派生指标 -------------------------------------------------------
    # 录制过程中 HUD 要实时显示，所以做成属性；finish() 的报告字典也复用它们，
    # 免得两处各算一遍、算法还不一致。
    @property
    def det_rate(self):
        return self.det_ok / max(self.det_all, 1) * 100.0

    @property
    def lum_mean(self):
        return self.lum_sum / max(self.n_captured, 1)

    # -- 录制中 ---------------------------------------------------------
    def feed(self, frame, frame_id, lm):
        """送进一帧刚采到的画面，按当前时刻补齐应有的输出帧。"""
        now = time.perf_counter()
        self.n_captured += 1

        lum = float(frame.mean())
        self.lum_sum += lum
        self.lum_min = min(self.lum_min, lum)

        self.det_all += 1
        if lm is not None:
            self.det_ok += 1
            self.vis_head = min(self.vis_head, float(lm[LM_HEAD, 3].min()))
            self.vis_shoulder = min(self.vis_shoulder,
                                    float(min(lm[11, 3], lm[12, 3])))
            self.vis_hand = min(self.vis_hand, float(lm[LM_HAND, 3].min()))

        # 同一帧被重复输出时只编码一次
        if frame_id != self._src_id or self._jpg is None:
            ok, jpg = cv2.imencode(".jpg", frame,
                                   [int(cv2.IMWRITE_JPEG_QUALITY), 95])
            if not ok:
                return
            self._jpg = jpg
            self._src_id = frame_id

        elapsed = now - self.t0
        while self.next_out <= elapsed:
            if len(self.buf) >= MAX_BUFFER_FRAMES:
                # 安全阀触发：丢掉积压，重新对齐到当前时刻。
                self.overflow += 1
                self.next_out = elapsed + 1.0 / self.target_fps
                break
            self.buf.append(self._jpg)
            self.n_out += 1
            self.next_out += 1.0 / self.target_fps

    # -- 收尾 -----------------------------------------------------------
    def finish(self):
        """按 target_fps 写盘，返回这一段的质量报告。"""
        wall = time.perf_counter() - self.t0
        n = len(self.buf)

        w = cv2.VideoWriter(str(self.path),
                            cv2.VideoWriter_fourcc(*"mp4v"),
                            self.target_fps, self.size)
        if not w.isOpened():
            raise RuntimeError(f"建不了 VideoWriter：{self.path}")
        for jpg in self.buf:
            w.write(cv2.imdecode(jpg, cv2.IMREAD_COLOR))
        w.release()
        self.buf.clear()

        rep = {
            "path": self.path,
            "wall_seconds": wall,                       # 真实录了多久
            "video_seconds": n / self.target_fps,       # 写出来的视频多长
            "frames": n,
            "fps": self.target_fps,
            "native_fps": self.n_captured / wall if wall > 0 else 0.0,
            "det_rate": self.det_rate,
            "vis_head": self.vis_head,
            "vis_shoulder": self.vis_shoulder,
            "vis_hand": self.vis_hand,
            "lum_mean": self.lum_sum / max(self.n_captured, 1),
            "lum_min": self.lum_min,
            "overflow": self.overflow,
        }
        return rep


def clip_problems(rep, cls, min_seconds):
    """把质量报告翻译成人能看懂的问题列表。没有就返回空。"""
    out = []
    if rep["wall_seconds"] < min_seconds:
        out.append(f"只录了 {rep['wall_seconds']:.1f} s，短于 {min_seconds:.0f} s，"
                   f"切不出足够窗口")

    if rep["lum_mean"] < LUM_DARK:
        out.append(f"画面几乎全黑（平均亮度 {rep['lum_mean']:.1f}/255）——"
                   f"检查镜头有没有被挡住、环境灯开了没、"
                   f"是不是被别的程序占用着摄像头")

    if rep["det_rate"] < 95:
        out.append(f"检测率 {rep['det_rate']:.1f}%，偏低——检查光线和取景，"
                   f"人是不是出画了")

    # 只对"真正要紧的部位"下判断。腿脚、髋部在坐姿上半身的取景里
    # 本来就在画面外，置信度恒为 0，拿它们判会误伤全部素材。
    if rep["vis_shoulder"] < 0.7:
        out.append(f"双肩置信度只有 {rep['vis_shoulder']:.2f}——双肩是归一化的基准，"
                   f"丢了整个特征就没意义，这条必须重录")
    elif rep["vis_head"] < 0.5:
        out.append(f"头面部置信度只有 {rep['vis_head']:.2f}——四类动作全靠头部姿态，"
                   f"建议重录")

    if cls == "phone" and rep["vis_hand"] < 0.5:
        out.append(f"手部置信度只有 {rep['vis_hand']:.2f}——phone 类靠举手机的动作，"
                   f"手必须进画面")

    if rep["native_fps"] < C.TARGET_FPS * 0.6:
        out.append(f"摄像头实际只有 {rep['native_fps']:.1f} fps（低于目标 "
                   f"{C.TARGET_FPS}）——多半是光线太暗把自动曝光拖长了。"
                   f"时间轴已经自动对齐，不用担心；但补个光数据质量会好很多")

    if rep["overflow"]:
        out.append(f"缓冲触顶丢帧 {rep['overflow']} 次，片段太长或中途卡住了")

    return out


def open_camera(cam, size, fps):
    cap = cv2.VideoCapture(cam, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(cam)
    if not cap.isOpened():
        raise SystemExit(f"打不开摄像头 {cam}。用 --cam 换一个序号试试。")
    if size:
        w, h = (int(v) for v in size.lower().split("x"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
    cap.set(cv2.CAP_PROP_FPS, fps)
    return cap


def print_camera_report(rep, cls, min_seconds):
    native = rep["native_fps"]
    print(f"停止录制：{rep['path'].name}")
    print(f"  真实时长 {rep['wall_seconds']:.1f} s -> 视频 {rep['video_seconds']:.1f} s "
          f"@ {rep['fps']:.0f} fps（{rep['frames']} 帧）")
    print(f"  摄像头实际帧率 {native:.1f} fps"
          + ("  <- 被自动曝光拖慢了" if native < C.TARGET_FPS * 0.6 else ""))
    print(f"  检测率 {rep['det_rate']:.1f}%   亮度 {rep['lum_mean']:.0f}/255"
          f"（最低 {rep['lum_min']:.0f}）")
    print(f"  置信度  双肩 {rep['vis_shoulder']:.2f}   头面 {rep['vis_head']:.2f}   "
          f"手部 {rep['vis_hand']:.2f}")

    probs = clip_problems(rep, cls, min_seconds)
    if probs:
        for p in probs:
            print(f"  [warn] {p}")
        print("  => 建议重录这一段")
    else:
        print("  => 合格")

    n = len(list((C.DATA_RAW / cls).glob("*.mp4")))
    print(f"  已录 {n} 段 {cls}")


def selftest():
    """不用摄像头，验证时间轴对齐。

    用 10 fps 造 4 秒的帧（模拟"光线偏暗、摄像头掉到 10 fps"这个真实场景），
    检查写出来的 mp4 是不是 15 fps、时长是不是仍然 ≈ 4 秒。
    修 bug 之前这里会是 2.7 秒——正是用户那段 25.2 s -> 8.4 s 的成因。
    """
    path = C.DATA_RAW / C.CLASSES[0] / "_TIMEAXIS_SELFTEST.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)

    sim_fps, sim_seconds = 10.0, 4.0
    n_sim = int(sim_fps * sim_seconds)
    w, h = 640, 360

    def make(i):
        f = np.zeros((h, w, 3), np.uint8)
        f[:, :, 1] = ((np.arange(w)[None, :] // 24) % 2) * 70   # 静态纹理
        x = int((i * 11) % (w - 60))
        cv2.rectangle(f, (x, 90), (x + 50, 250), (210, 210, 210), -1)
        cv2.putText(f, f"sim {i}", (12, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                    (255, 255, 255), 2)
        return f

    print(f"[自检] 造 {sim_fps:.0f} fps 的画面，录 {sim_seconds:.0f} 秒"
          f"（{n_sim} 帧），目标输出 {C.TARGET_FPS} fps")
    rec = ClipRecorder(path, (w, h), C.TARGET_FPS)
    t0 = time.perf_counter()
    for i in range(n_sim):
        rec.feed(make(i), i, None)
        slack = t0 + (i + 1) / sim_fps - time.perf_counter()
        if slack > 0:
            time.sleep(slack)
    wall = time.perf_counter() - t0
    rep = rec.finish()

    cap = cv2.VideoCapture(str(path))
    got_fps = cap.get(cv2.CAP_PROP_FPS)
    got_n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    ok, fr = cap.read()
    cap.release()
    got_sec = got_n / got_fps if got_fps else 0.0

    print(f"[自检] 真实耗时 {wall:.2f} s")
    print(f"[自检] 写出的视频 {got_n} 帧 @ {got_fps:.1f} fps = {got_sec:.2f} s，"
          f"分辨率 {fr.shape if ok else '读不到'}")

    checks = [
        (abs(got_fps - C.TARGET_FPS) < 0.01,
         f"视频帧率应为 {C.TARGET_FPS}，实际 {got_fps:.1f}"),
        (abs(got_sec - wall) < 0.4,
         f"视频时长应等于真实耗时 {wall:.2f} s，实际 {got_sec:.2f} s"
         f"（差 {got_sec - wall:+.2f} s）"),
        (abs(rep["wall_seconds"] - wall) < 0.01, "报告里的时长不对"),
        (ok and fr.shape[:2] == (h, w), f"分辨率应为 {(h, w)}"),
    ]
    # 旧行为对照：驱动会报一个名义帧率（DSHOW 下实测恒报 30），
    # 老代码直接拿它当写盘帧率。真实只采到 10 fps，于是视频被加速 3 倍——
    # 用户那段"停止录制 25.2 s / 视频只有 253 帧 = 8.4 s"就是这么来的。
    nominal = 30.0
    naive_sec = n_sim / nominal
    print(f"[对照] 老写法：驱动名义报 {nominal:.0f} fps，直接拿它写盘，"
          f"{n_sim} 帧只写出 {naive_sec:.2f} s 的视频，"
          f"而真实过了 {sim_seconds:.1f} s => 播放快 "
          f"{nominal / sim_fps:.1f} 倍，60 帧窗口不再是 4 秒")

    bad = [msg for good, msg in checks if not good]

    # --- 第二段：判据逻辑自检 -------------------------------------------
    # clip_problems() 只在按空格停止录制时才会被调用，无头模式走不到，
    # 而"最低置信度 0.00 误报"最初就出在这里。构造报告字典直接测它。
    print("[自检] 判据函数 clip_problems()：")

    def mk(**kw):
        base = dict(path=Path("x"), wall_seconds=12.0, video_seconds=12.0,
                    frames=180, fps=15.0, native_fps=15.0, det_rate=99.0,
                    vis_head=0.95, vis_shoulder=0.99, vis_hand=0.90,
                    lum_mean=110.0, lum_min=90.0, overflow=0)
        base.update(kw)
        return base

    cases = [
        # (说明, 报告, 类别, 期望出现的告警关键字)
        ("正常片段应无告警",        mk(), "normal", []),
        ("normal 手没进画面也别告警", mk(vis_hand=0.10), "normal", []),
        ("全黑画面",                mk(lum_mean=0.0, lum_min=0.0, native_fps=1.0,
                                      det_rate=0.0), "normal", ["几乎全黑"]),
        ("双肩丢了（归一化基准）",   mk(vis_shoulder=0.30), "normal", ["双肩置信度"]),
        ("头面部不稳",              mk(vis_head=0.20), "normal", ["头面部置信度"]),
        ("phone 手没进画面",        mk(vis_hand=0.10), "phone", ["手部置信度"]),
        ("时长不足",                mk(wall_seconds=4.0), "normal", ["切不出足够窗口"]),
        ("摄像头被拖慢",            mk(native_fps=5.0), "normal", ["摄像头实际只有"]),
    ]
    for name, rep, cls, expect in cases:
        got = clip_problems(rep, cls, 10.0)
        hit = [e for e in expect if not any(e in g for g in got)]
        if hit:
            bad.append(f"{name}：期望告警含 {hit}，实际 {got}")
        if not expect and got:
            bad.append(f"{name}：期望无告警（误报就是这个 bug），实际 {got}")
        flag = "OK " if not hit and (expect or not got) else "BAD"
        print(f"    [{flag}] {name:<22} -> {len(got)} 条告警")

    for msg in bad:
        print(f"[自检] FAIL: {msg}")
    print("[自检] " + ("全部通过" if not bad else f"{len(bad)} 项失败"))

    path.unlink(missing_ok=True)
    print("[自检] 已删除测试文件")
    return 0 if not bad else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cam", type=int, default=0, help="摄像头序号")
    ap.add_argument("--size", default="1280x720", help="期望分辨率，如 1280x720")
    ap.add_argument("--fps", type=int, default=30, help="向摄像头申请的帧率")
    ap.add_argument("--min-seconds", type=float, default=10.0, help="短于此时长会告警")
    ap.add_argument("--selftest", action="store_true",
                    help="不用摄像头，验证时间轴对齐后退出")
    ap.add_argument("--test-frames", type=int, default=0,
                    help="无头自检：跑这么多帧就退出，不等人按键")
    ap.add_argument("--no-display", action="store_true", help="不开预览窗口")
    args = ap.parse_args()

    global _T_TEST_TIMING
    _T_TEST_TIMING = bool(args.test_frames)

    # HUD 的构造与渲染分开：无头自检也要走一遍 HUD 构造（只是不开窗口），
    # 否则这条路径永远测不到。display 后面会被测试模式改成 False，所以
    # 这里按 args 算，不受影响。
    draw_preview = (not args.no_display) or bool(args.test_frames)

    if args.selftest:
        raise SystemExit(selftest())

    # --test-frames 模式下分段计时，排查"跑 4 帧却要 50 秒"这类固定开销。
    _t = {"last": _T_START}

    def tick(tag):
        if not args.test_frames:
            return
        now = time.perf_counter()
        print(f"  [计时] {tag:<24} {now - _t['last']:7.2f} s", flush=True)
        _t["last"] = now

    cap = open_camera(args.cam, args.size, args.fps)
    tick("启动+开摄像头")
    real_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    real_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"摄像头 {args.cam}：{real_w}x{real_h}，"
          f"名义 {cap.get(cv2.CAP_PROP_FPS) or args.fps:.1f} fps"
          f"（实际帧率会被自动曝光拖慢，录制时按真实时间对齐到 {C.TARGET_FPS} fps）")
    print(f"输出目录：{C.DATA_RAW}")

    # 全程只建一个 extractor，退出时不要 close()（见 src/pose.py 的说明）
    pose = PoseExtractor()
    tick("构造 PoseExtractor")

    cls_idx = 0
    show_skel = True
    state = "idle"                    # idle | countdown | recording
    countdown_end = 0.0
    rec = None

    # 采集帧率的滚动估计，只用于显示。窗口取 45 帧，约 1.5~4.5 秒。
    cap_ts = deque(maxlen=45)
    t_begin = time.perf_counter()
    frame_i = 0
    display = not args.no_display

    if args.test_frames:
        cls = C.CLASSES[0]
        p = C.DATA_RAW / cls / "_RECORDTEST.mp4"
        p.parent.mkdir(parents=True, exist_ok=True)
        rec = ClipRecorder(p, (real_w, real_h), C.TARGET_FPS)
        state = "recording"
        display = False
        print(f"[自检] 录 {args.test_frames} 帧到 {p}")

    print("\n按键： 1/2/3/4 切类别   空格 开始/结束录制   s 开关骨骼   q 退出")
    print("当前类别：" + "  ".join(f"{i+1}={c}" for i, c in enumerate(C.CLASSES)) + "\n")

    while True:
        ok, frame = cap.read()
        if not ok:
            print("[warn] 读不到画面，重试")
            time.sleep(0.05)
            continue

        if frame.shape[1] != real_w or frame.shape[0] != real_h:
            frame = cv2.resize(frame, (real_w, real_h))

        now = time.perf_counter()
        cap_ts.append(now)
        native_fps = 0.0
        if len(cap_ts) > 1:
            span = cap_ts[-1] - cap_ts[0]
            if span > 0:
                native_fps = (len(cap_ts) - 1) / span

        ts_ms = (now - t_begin) * 1000.0
        lm = pose.detect(frame, ts_ms)

        if state == "countdown" and now >= countdown_end:
            cls = C.CLASSES[cls_idx]
            path = next_path(cls)
            rec = ClipRecorder(path, (real_w, real_h), C.TARGET_FPS)
            state = "recording"
            print(f"开始录制 -> {path.name}")

        if state == "recording":
            rec.feed(frame, frame_i, lm)

        # 预览：画骨骼 + HUD（画在副本上，录制存的是未叠加的原始帧）
        # 走 draw_preview 而不是 display：--test-frames 无头模式下也执行这段，
        # 只是不 imshow。否则 HUD 的计算逻辑永远进不了测试——
        # det_rate 属性名写错就是这么漏过去的（一按空格开始录就崩）。
        if draw_preview:
            vis = frame.copy()
            if show_skel and lm is not None:
                draw_pose(vis, lm)
            lines = []
            if state == "countdown":
                lines.append((f"GET READY  {countdown_end - now:.1f}", YELLOW))
            elif state == "recording":
                lines.append((f"* REC  {now - rec.t0:5.1f} s  "
                              f"-> {rec.n_out} 帧", RED))

            rate = rec.det_rate if rec else 100.0
            sh = rec.vis_shoulder if rec else 1.0
            hd = rec.vis_head if rec else 1.0
            lum = rec.lum_mean if rec else float(frame.mean())
            lines += [
                (f"class: {C.CLASSES[cls_idx]}  (press 1-4)", WHITE),
                (f"cam {native_fps:4.1f} fps -> out {C.TARGET_FPS} fps"
                 f"   bright {lum:3.0f}",
                 GREEN if native_fps >= C.TARGET_FPS * 0.6 and lum >= LUM_DARK else YELLOW),
                (f"detect {rate:5.1f}%   shoulder {sh:.2f}  head {hd:.2f}",
                 GREEN if rate >= 95 and sh >= 0.7 and hd >= 0.5
                 else (YELLOW if rate >= 80 else RED)),
                (f"pose: {'OK' if lm is not None else 'LOST'}"
                 f"   skel: {'on' if show_skel else 'off'}",
                 GREEN if lm is not None else RED),
            ]
            if rec and rec.n_captured and native_fps < C.TARGET_FPS * 0.6:
                lines.append(("slow camera: exposure too long, add light", YELLOW))
            draw_hud(vis, lines)
            if display:
                cv2.imshow("record", vis)

        frame_i += 1
        if args.test_frames and frame_i >= args.test_frames:
            break

        if display:
            key = cv2.waitKey(1) & 0xFF
        else:
            key = 0xFF
            time.sleep(1.0 / max(C.TARGET_FPS, 1))

        if key in (ord("q"), 27):
            break
        elif key in (ord("1"), ord("2"), ord("3"), ord("4")):
            cls_idx = key - ord("1")
            print(f"当前类别 -> {C.CLASSES[cls_idx]}")
        elif key == ord("s"):
            show_skel = not show_skel
        elif key == ord(" "):
            if state == "recording":
                cls = C.CLASSES[cls_idx]
                rep = rec.finish()
                print_camera_report(rep, cls, args.min_seconds)
                rec = None
                state = "idle"
            elif state == "countdown":
                state = "idle"
                print("已取消")
            elif state == "idle":
                countdown_end = time.perf_counter() + 3.0
                state = "countdown"
                print(f"准备录 {C.CLASSES[cls_idx]}，3 秒后开始...")

    tick("喂帧主循环")

    # 退出时还在录：先把缓冲落盘，别丢
    if state == "recording" and rec is not None:
        rep = rec.finish()
        if args.test_frames:
            print(f"[自检] 真实 {rep['wall_seconds']:.1f} s -> "
                  f"视频 {rep['video_seconds']:.1f} s @ {rep['fps']:.0f} fps，"
                  f"采集帧率 {rep['native_fps']:.1f} fps，"
                  f"亮度 {rep['lum_mean']:.0f}/255，检测率 {rep['det_rate']:.1f}%")
        else:
            print("[warn] 退出时还在录制，已保存")
            print_camera_report(rep, C.CLASSES[cls_idx], args.min_seconds)
    cap.release()
    if display:
        cv2.destroyAllWindows()
    tick("保存+释放摄像头")

    if args.test_frames:
        p = rec.path if rec else (C.DATA_RAW / C.CLASSES[0] / "_RECORDTEST.mp4")
        print(f"\n[自检] 产出 {p}  存在={p.exists()}  "
              f"大小={p.stat().st_size if p.exists() else 0} 字节")
        if p.exists():
            c = cv2.VideoCapture(str(p))
            n = int(c.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = c.get(cv2.CAP_PROP_FPS)
            ok2, fr = c.read()
            c.release()
            print(f"[自检] 读回：{n} 帧 @ {fps:.1f} fps，分辨率 {fr.shape if ok2 else '读不到'}")
            p.unlink(missing_ok=True)
            print("[自检] 已删除测试文件")
        tick("读回校验")
    else:
        print("\n各目录已录段数：")
        for cls in C.CLASSES:
            n = len(list((C.DATA_RAW / cls).glob("*.mp4")))
            mark = "OK" if n >= 8 else f"还差 {8 - n} 段"
            print(f"  {cls:<8} {n:>2} 段   {mark}")
        print("\n录够了就跑： python tools/extract_pose.py")

    # 必须是 main() 的最后一行，不能放到 if __name__ 里。
    # pose 是 main() 的局部变量，main() 一返回它就析构，而 mediapipe 的
    # 析构固定要 42 秒。放在外面等于等析构跑完才退出，白等。
    _exit_now()


def _exit_now():
    """跳过解释器清理，直接退出进程。

    mediapipe 的 landmarker 析构固定耗时 **42 秒**，而且**躲不掉**——
    调不调 close() 只决定它什么时候发生：

      - 显式调 close()  → 立刻付这 42 秒；
      - 不调，靠对象回收 → main() 返回、局部变量 pose 析构时付这 42 秒。

    实测账目：一次 `--test-frames 4` 的录制流程，各阶段计时加起来 7.6 秒，
    而 Python 自己报的进程内耗时是 50.4 秒 —— 差额 42.8 秒全在
    main() 返回的那一瞬间。

    所以这个函数**必须作为 main() 的最后一行被调用**：os._exit 永不返回，
    main() 就不会返回，局部变量就不会析构。放到 if __name__ 块里是错的，
    那时析构已经跑完了。

    上面该释放的（摄像头、VideoWriter、文件句柄）都已经显式释放过，
    跳过解释器清理是安全的。
    """
    if _T_TEST_TIMING:
        print(f"  [计时] _exit_now() 处的进程内耗时 "
              f"{time.perf_counter() - _T_START:.2f} s（之后就是 os._exit）",
              flush=True)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
