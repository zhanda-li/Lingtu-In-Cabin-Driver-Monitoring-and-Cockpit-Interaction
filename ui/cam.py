"""摄像头实时源：**界面进程自己跑真模型**，把真画面和真判决一起给界面。

    python ui/cam.py --replay data/raw/fatigue/fatigue_02.mp4 --dump runs/_cam.csv
    python ui/cam.py                      # 摄像头

── 为什么要有它（以及它和 `src/fuse.py` 的关系）────────────────────

界面原来的三种数据源都是**读文件**：demo 是编的，replay/live 读 CSV。也就是说
驾驶员画面里那个头是画出来的，不是真脸。这个文件补的就是这一段。

摄像头是**独占设备**（本项目踩过：两个进程一起开，先开的那个变全黑 + 1 fps）。
所以"界面显示真画面"和"`src/fuse.py` 正在跑"这两件事**不能同时成立**。
本文件的立场是：**谁开摄像头谁跑模型**。cam 模式下界面进程开摄像头、跑推理，
此时**不要**再跑 `live_fuse.bat`。

── 为什么不直接调 `src/fuse.py` ────────────────────────────────

`src/fuse.py` 是支路一那条链路的**回归基线**（121 段逐帧一致），它不能改；
而它的全部逻辑都在 `main()` 里，没有可以挂帧回调的缝。

所以这里做的是：**把 `src/fuse.py:507~644` 的融合块原样搬过来**，其余一律
`import` 复用（`Hysteresis` / `WarningState` / `ScalarState` / `load_branch2` /
`FaceBranch` / `window_features` 全是原装的，一个都没重写）。
搬过来的只有那 60 行判据本身。

⚠️ **搬过来的那段是"抄写"，不是"参考"**：改语义要两边一起改，否则界面上的
数字会和 `src/fuse.py` 的真实行为对不上。这就是 `--dump` 存在的理由 ——
它对同一段视频跑一遍，产出的 CSV 应当与
`python src/fuse.py --replay 同一段 --log-probs ref.csv` **逐行一致**：

    python src/fuse.py --replay X.mp4 --log-probs runs/_ref.csv --no-display
    python ui/cam.py   --replay X.mp4 --dump        runs/_cam.csv
    python tools/cmp_cam_fuse.py runs/_ref.csv runs/_cam.csv

（`--fast` 那一路不能这么比：丢弃帧的时机和实速不一样。）
"""

from __future__ import annotations

import argparse
import collections
import os
import sys
import threading
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
# 倒着插，让优先级高的落到最前面（先 ui 后 src）。
# 不插 tools/：`import fuse` 自己会插，而 cam.py 用不到那边的脚本。
for _p in (str(ROOT / "src"), str(ROOT / "ui"), str(ROOT)):
    sys.path.insert(0, _p)

import config as C                                            # noqa: E402
from face import (CLOSE_EYE_SEC, FEATURE_NAMES, HEAD_DEG,     # noqa: E402
                  HEAD_WIN, HIST_SEC, ROLL_WIN, YAWN_MIN, FaceBranch,
                  FaceExtractor, HeadMotion, close_eye_seconds, feature_vector,
                  norm_by_time, yawn_seconds)
from live import (DECIDE_HZ, CameraSource, Hysteresis,        # noqa: E402
                  OnlineNormalizer, VideoSource, WarningState, find_model,
                  load_infer_model)
from pose import PoseExtractor                                # noqa: E402
import fuse as F                                              # noqa: E402
from sources import row_to_state                              # noqa: E402

# 闸门/支路二那几个常量**从 fuse 里取**，不在这里重写 —— 抄数字迟早会抄歪。
NORMAL_I = F.NORMAL_I
GATE_MIN = F.GATE_MIN
YAWN_HOLD = F.YAWN_HOLD
YAWN_ACTION = F.YAWN_ACTION
B2_MAX_LEVEL = F.B2_MAX_LEVEL
# 两条规则（2026-09-26）：判据的**量和阈值**都在 face.py（这里 import 进来），
# 融合策略（抬到几级、保持多久）在 fuse.py，同样取它的。**一个数都不在这儿重写。**
# ⚠️ `src/fuse.py` 走命令行时那几个开关（--eye-sec/--head-deg/…）能覆盖默认值，
#    而 cam 这条路没有命令行 —— 它用的是同一份默认值。改默认值两处同时生效。
EYE_HOLD = F.EYE_HOLD
EYE_LEVEL = F.EYE_LEVEL
HEAD_HOLD = F.HEAD_HOLD
HEAD_LEVEL = F.HEAD_LEVEL


# ---------------------------------------------------------------- 画面上的叠加
# 这几组下标是 mediapipe FaceMesh 的规范索引，照抄官方 FACEMESH_* 定义。
# 只用得上 `face.NEED` 里那 22 个点（`FaceExtractor.detect` 只回这些），
# 所以眼睛画的是"上下眼睑各三对 + 两个眼角"连成的多边形 —— 是真点，不是装饰。
_EYE_POLY = {
    "r": (33, 144, 145, 153, 133, 158, 159, 160),     # 33/133 是眼角
    "l": (263, 373, 374, 380, 362, 387, 386, 385),
}
_MOUTH_IN = (61, 13, 291, 14)
_MOUTH_OUT = (61, 12, 291, 15)

# 姿态骨架：只画上半身，够表达"人在座舱里"，画全套会把脸盖住
_POSE_EDGES = ((11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
               (11, 7), (12, 8), (9, 10))


def _px(P, i):
    """NEED 里第 i 号关键点的像素坐标；不在里面就返回 None。"""
    v = P.get(i)
    return None if v is None else (int(v[0]), int(v[1]))


def draw_overlay(bgr, det, lm, head):
    """把**真的检测结果**画回画面：脸框、眼/嘴轮廓、骨架、一行 ASCII 状态。

    head 是这一拍的状态字典（可能是上一拍的）。中文一律不画 —— cv2 渲染不了
    中文，界面那边用 HTML 叠字，这里只出 ASCII。
    """
    import cv2

    h, w = bgr.shape[:2]

    # --- 骨架（暗一点，别抢脸）---
    if lm is not None:
        for a, b in _POSE_EDGES:
            if a >= len(lm) or b >= len(lm):
                continue
            if lm[a][3] < 0.35 or lm[b][3] < 0.35:      # 置信度太低就不画
                continue
            cv2.line(bgr,
                     (int(lm[a][0] * w), int(lm[a][1] * h)),
                     (int(lm[b][0] * w), int(lm[b][1] * h)),
                     (150, 120, 60), 1, cv2.LINE_AA)

    if det is not None:
        P = det["P"]
        pts = [v for v in P.values()]
        xs = [float(v[0]) for v in pts]
        ys = [float(v[1]) for v in pts]
        x0, x1 = max(0, int(min(xs)) - 26), min(w - 1, int(max(xs)) + 26)
        y0, y1 = max(0, int(min(ys)) - 34), min(h - 1, int(max(ys)) + 30)

        # 脸框四角括号（不画整框：整框在这类界面上太像"抓拍"）
        seg = int(min(x1 - x0, y1 - y0) * 0.20)
        col = (197, 215, 24)                            # BGR ≈ #18D7C5
        for (cx, cy, dx, dy) in ((x0, y0, 1, 1), (x1, y0, -1, 1),
                                 (x0, y1, 1, -1), (x1, y1, -1, -1)):
            cv2.line(bgr, (cx, cy), (cx + dx * seg, cy), col, 2, cv2.LINE_AA)
            cv2.line(bgr, (cx, cy), (cx, cy + dy * seg), col, 2, cv2.LINE_AA)

        # 眼睛 / 嘴：多边形顶点就是检测到的关键点本身
        for key in ("l", "r"):
            poly = [_px(P, i) for i in _EYE_POLY[key]]
            poly = [p for p in poly if p]
            if len(poly) >= 3:
                cv2.polylines(bgr, [np.array(poly)], True, (255, 240, 120), 1,
                              cv2.LINE_AA)
        for ids, color in ((_MOUTH_OUT, (120, 200, 255)), (_MOUTH_IN, (60, 160, 255))):
            poly = [p for p in (_px(P, i) for i in ids) if p]
            if len(poly) >= 3:
                cv2.polylines(bgr, [np.array(poly)], True, color, 1, cv2.LINE_AA)

        # 关键点本身（就是那 22 个真正参与 EAR/MAR 的点）
        for v in pts:
            cv2.circle(bgr, (int(v[0]), int(v[1])), 1, (255, 255, 255), -1,
                       cv2.LINE_AA)

    # --- 一行 ASCII 状态。数值全是这一拍的真值 ---
    bits = []
    if head:
        bits.append(f"L{head.get('l_fused', 0)}")
        bits.append("GATE OPEN" if head.get("gate") else "GATE SHUT")
        pc = head.get("perclos")
        bits.append("PC   -  " if pc is None else f"PC {pc * 100:5.1f}%")
        pf = head.get("p_fat")
        bits.append("PFAT -  " if pf is None else f"PFAT {pf:4.2f}")
    if bits:
        txt = "  ".join(bits)
        cv2.rectangle(bgr, (12, h - 40), (12 + 11 * len(txt), h - 14),
                      (0, 0, 0), -1)
        cv2.putText(bgr, txt, (18, h - 21), cv2.FONT_HERSHEY_SIMPLEX, 0.52,
                    (200, 235, 245), 1, cv2.LINE_AA)
    return bgr


# ---------------------------------------------------------------- 主管线
class CamSource:
    """和 `sources.DemoSource` / `CsvSource` 同形状：`poll(now) -> State | None`。

    额外多一个 `jpeg` / `seq` 给 MJPEG 那一路用。
    """

    def __init__(self, cfg: dict | None = None, replay: str | None = None,
                 cam: int = 0, fast: bool = False, out_w: int = 720,
                 log_probs: str | None = None, overlay: bool = True):
        cfg = cfg or {}
        cam_cfg = cfg.get("camera", {})
        self.out_w = int(out_w)
        self.overlay = overlay
        self.jpeg: bytes | None = None
        self.seq = 0
        self.frames = 0
        self.error: str | None = None
        self.latest = None
        self.head: dict = {}
        self._stop = threading.Event()
        self._fps_t = time.monotonic()
        self._fps_n = 0
        self.fps = 0.0

        # ---- 帧源：**先开，理由见下** ----
        # ★ 2026-09-25：这一段原来在权重和 landmarker **后面**。加界面上的
        #   「接入摄像头」按钮之后它就不行了：建这个对象要 load 两个 torch 权重
        #   + 两个 mediapipe landmarker，**实测量级是秒**；而用户点那颗按钮时
        #   十有八九是**没插摄像头**（他自己说的），于是"打不开摄像头 0"
        #   （src/live.py:361）要等好几秒才抛出来 —— 那几秒里界面只有
        #   「正在接入…」四个字，像卡死了。
        #   把开设备挪到最前面，失败就是**立刻**失败，一个权重都不用加载。
        #   ⚠️ 顺序变了但**语义没变**：成了的路径上两者互不相干（帧源不读权重，
        #      权重不读帧源）；没成的那条路上省下的全是白干的活。
        self.src = (VideoSource(replay, fast=fast) if replay
                    else CameraSource(cam, size=tuple(cam_cfg.get("size", (1280, 720)))))
        self.replay = replay

        # ⚠️ 上面把开设备挪到了最前面（理由见那段注释），于是**下面任何一步失败
        #   都会把一个开着没人管的摄像头留在进程里**。摄像头是**独占设备**：
        #   这个进程不退出，用户后来真插上摄像头也照样打不开（而且报的还是
        #   "打不开摄像头 0"，看起来像他的设备坏了）。所以这一整段必须兜住。
        #   原来不用兜 —— 开设备是最后一步，它自己抛了就没有设备要放。
        try:
            # ---- 支路一权重 ----
            ckpt = find_model(None)
            self.model, self.feat_mean, self.feat_std, classes, self.window = \
                load_infer_model(ckpt)
            # ⚠️ 窗口要从**权重**里读，不能从 config 读 —— 这两者历史上不一致过
            #   （见 dms-project 笔记：live.py 的窗口要从权重里读）。
            self.model_name = ckpt.name
            # ---- 支路二权重 ----
            self.model2 = F.load_branch2(None)

            self.hyst = Hysteresis()
            self.b2 = F.ScalarState()
            self.norm = OnlineNormalizer()
            self.state = WarningState(self.hyst)

            # ⚠️ 两个 landmarker 实例，各自析构固定 42 秒（mediapipe 1.0.1 的坑）。
            #   所以这个进程退出时**必须** os._exit(0)，否则 Ctrl+C 之后要干等 84 秒。
            self.pose = PoseExtractor(None, running_mode="VIDEO")
            self.face = FaceExtractor(running_mode="VIDEO")
            self.fb = FaceBranch()

            self._log_fp = open(log_probs, "w", encoding="utf-8", newline="") \
                if log_probs else None
            if self._log_fp:
                self._log_fp.write(
                    "t," + ",".join(C.CLASSES)
                    + ",l1,gate,ema_normal,p_fat,l2,perclos,brate,nod,"
                      "en_now,d_pitch,yawn_sec,eye_sec,head_swing,l_fused,src,"
                      "ear,mar,pitch,mark\n")
        except Exception:
            rel = getattr(self.src, "release", None)
            if callable(rel):
                try:
                    rel()
                except Exception:
                    pass
            raise

        self._th = threading.Thread(target=self._run, name="cam", daemon=True)
        self._th.start()

    # ------------------------------------------------------------ 主循环
    def _run(self):
        """`src/fuse.py:497~670` 的融合块，原样搬过来（见模块开头）。"""
        ring = collections.deque(maxlen=self.window)
        probs = np.full(len(C.CLASSES), 1.0 / len(C.CLASSES), np.float64)
        last_lm, last_lm_id, fed_id = None, -1, -1
        frame_id = 0
        next_feed = next_decide = 0.0
        first = True
        l2, l1, l_fused = 0, 0, 0
        p_fat = float("nan")
        st = None
        yawn_sec, yawn_until = 0.0, -1.0
        # 两条规则（2026-09-26）的状态，写法与 yawn 同款
        eye_sec, eye_until = 0.0, -1.0
        h_swing, head_until = float("nan"), -1.0
        eye_on = head_on = False
        src_of_level = "pose"
        # 头姿缓冲：独立于 fb、永远不看闸门（理由见 face.HeadMotion）
        hm = HeadMotion()
        gate = False
        feed_dt = 1.0 / C.TARGET_FPS
        decide_dt = 1.0 / DECIDE_HZ
        try:
            while not self._stop.is_set():
                frame, ok = self.src.read()
                if not ok or frame is None:
                    if self.replay:
                        self.error = "回放结束"
                        break
                    continue
                mt = self.src.media_time()
                frame_id += 1
                self.frames = frame_id

                lm = self.pose.detect(frame, mt * 1000.0)
                if lm is not None:
                    last_lm, last_lm_id = lm, frame_id

                gate = bool(np.argmax(self.state.ema) == NORMAL_I
                            and self.state.ema[NORMAL_I] >= GATE_MIN)

                ear = mar = pitch = float("nan")
                det = None
                d = self.face.detect(frame, mt * 1000.0)
                if d is not None:
                    det = d
                    ear, mar, pitch = d["ear"], d["mar"], d["pitch"]
                # ★ 一直采集，**不看闸门**（2026-09-26 改，与 src/fuse.py 同步）。
                #   原来闸门一关就 `clear()`，而低头正是关闸门的信号 —— 于是支路二
                #   的 27 秒热身在真人身上**从来攒不满**，界面上那个"还需 N 秒"
                #   也永远在重头数。理由详见 face.FaceBranch.clear() 的 docstring。
                self.fb.push(mt, ear, mar, pitch)
                # 头姿缓冲：同样不看闸门，而且它必须不看（低头就是关闸门的信号）
                hm.push(mt, pitch)

                if first:
                    next_feed = next_decide = mt
                    first = False
                elif next_feed < mt - 0.5:
                    next_feed = mt
                while next_feed <= mt:
                    if last_lm is not None:
                        ring.append(self.norm.push(last_lm))
                        fed_id = last_lm_id
                    next_feed += feed_dt

                if len(ring) == self.window and mt >= next_decide:
                    next_decide = mt + decide_dt
                    x = np.asarray(ring, np.float32)
                    x = (x - self.feat_mean) / self.feat_std
                    import torch
                    with torch.no_grad():
                        probs = torch.softmax(
                            self.model(torch.from_numpy(x[None])), dim=1)[0].numpy()
                    l1, _ = self.state.update(probs, mt)

                    gate = bool(np.argmax(self.state.ema) == NORMAL_I
                                and self.state.ema[NORMAL_I] >= GATE_MIN)
                    st = self.fb.snapshot() if (gate and self.fb.ready()) else None
                    p_fat = float("nan")
                    if gate and self.fb.full() and st is not None:
                        fv = np.array([feature_vector(st)], float)
                        if np.all(np.isfinite(fv)):
                            p_fat = float(self.model2.predict_proba(fv)[0, 1])
                            l2 = self.b2.update(p_fat, mt)
                        else:
                            l2 = 0
                    else:
                        l2 = 0
                        self.b2.reset()

                    yawn_sec = 0.0
                    eye_sec = 0.0
                    if self.fb.span >= YAWN_MIN + 0.5:
                        # ★ 只取一次 arrays()，两条规则共用（每拍一次 np.array(deque)）
                        _bt, _be, _bm, _ = self.fb.arrays()
                        yawn_sec = float(yawn_seconds(_bt, _bm))
                        # ---- 持续闭眼规则（与 src/fuse.py 逐行一致）----
                        # ⚠️ 不挂 ROLL_WIN(10 s)：基线从第一帧起就用"现有的历史"算，
                        #   量过代价（正常前 10 秒 0/27、疲劳 16/26 且最早 1.8 s）。
                        if self.fb.span >= CLOSE_EYE_SEC + 1.0:
                            _en = _be / np.maximum(
                                norm_by_time(_bt, _be, ROLL_WIN), 1e-6)
                            eye_sec = float(close_eye_seconds(_bt, _en))
                    if yawn_sec >= YAWN_MIN:
                        yawn_until = mt + YAWN_HOLD
                    yawn_on = mt < yawn_until
                    if eye_sec >= CLOSE_EYE_SEC:
                        eye_until = mt + EYE_HOLD
                    eye_on = mt < eye_until

                    # ---- 低头/点头规则（免基线，开机 HEAD_WIN=2 秒就能判）----
                    # 读 `hm` 不读 `fb`：低头会让闸门关上，而 fb 的语义归闸门管。
                    h_swing = hm.swing()
                    hit = bool(np.isfinite(h_swing) and h_swing >= HEAD_DEG)
                    if HEAD_HOLD <= 0.0:
                        # ★ **不锁存**（`HEAD_HOLD = 0.0`，2026-09-26 第四次）。与
                        #   `src/fuse.py:739` 那一段**逐行同构** —— 两条支都要有，
                        #   不能只留一条：`mt < mt` 恒假，规则会整条哑掉。
                        #   实测代价（真人 `runs/session9.csv`）：回正后多报 5.3 / 3.1 秒。
                        head_on = hit
                    else:
                        if hit:
                            head_until = mt + HEAD_HOLD
                        head_on = mt < head_until

                    # ---- 融合：四条来源取最大；平局取靠前的 → **规则赢基线** ----
                    # 平局只决定"念哪一句原因"，级别一模一样（同 src/fuse.py）。
                    l_face = min(l2, B2_MAX_LEVEL) if gate else 0
                    l_base = max(l1, l_face)
                    l_yawn = 1 if (yawn_on and YAWN_ACTION == "level") else 0
                    l_eye = EYE_LEVEL if eye_on else 0
                    l_head = HEAD_LEVEL if head_on else 0
                    l_fused = max(l_base, l_yawn, l_eye, l_head)
                    # ⚠️ 全零那一拍 `src` 必须是 "pose" —— 不能写成一个 max()，
                    #   那会返回列表第一个（"head"）→ 级别 0 却报低头。
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

                    head = self._cols(mt, probs, l1, gate, p_fat, l2, st,
                                      yawn_sec, eye_sec, h_swing, l_fused,
                                      src_of_level, ear, mar, pitch)
                    self.head = head
                    self.latest = row_to_state(head, "cam")
                    # 基线攒了多少秒 —— 界面的「基线热身中 · 还需 N 秒」照它算。
                    # ★ 2026-09-26 起这个数**从开机起单调增长**：闸门不再清缓冲
                    #   （见上面那段），所以低头一次不会让它跳回去 —— 用户投诉的
                    #   「等十几秒」正是它原来每次低头都重头数。
                    # **仍然只能问 FaceBranch**（它知道缓冲的真实跨度）。写在这儿
                    # 不是写进 `head`：CSV 的列名和顺序要和 `src/fuse.py` 对拍，
                    # 加一列就破了那个契约。
                    self.latest.pc_span = self.fb.span
                    if self._log_fp:
                        self._log_fp.write(
                            ",".join(str(v) for v in head.values()) + "\n")
                        self._log_fp.flush()

                # ---- 出图 ----
                if self.overlay:
                    try:
                        draw_overlay(frame, det, lm, self.head)
                    except Exception:
                        pass
                self._encode(frame)
                self._fps_n += 1
                now = time.monotonic()
                if now - self._fps_t >= 1.0:
                    self.fps = self._fps_n / (now - self._fps_t)
                    self._fps_t, self._fps_n = now, 0
        except Exception as e:                      # 线程里出错不能把服务打死
            self.error = f"{type(e).__name__}: {e}"
        finally:
            if self._log_fp:
                self._log_fp.close()
            try:
                self.src.release()
            except Exception:
                pass

    def _cols(self, mt, probs, l1, gate, p_fat, l2, st, yawn_sec, eye_sec,
              h_swing, l_fused, src_of_level, ear, mar, pitch):
        """列名和顺序与 `src/fuse.py` 的 --log-probs 完全一致（要能对拍）。"""
        def cell(v, fmt="{:.4f}"):
            try:
                f = float(v)
            except (TypeError, ValueError):
                return "-"
            return "-" if not np.isfinite(f) else fmt.format(f)

        d = {"t": f"{mt:.3f}"}
        for k, c in enumerate(C.CLASSES):
            d[c] = f"{probs[k]:.4f}"
        d.update(l1=str(l1), gate=str(int(gate)),
                 ema_normal=f"{self.state.ema[NORMAL_I]:.4f}", p_fat=cell(p_fat),
                 l2=str(l2))
        for k in FEATURE_NAMES:
            d[k] = cell(st[k]) if st else "-"
        d.update(en_now=cell(st["en_now"]) if st else "-",
                 d_pitch=cell(st["d_pitch"], "{:.2f}") if st else "-",
                 yawn_sec=f"{yawn_sec:.2f}", eye_sec=f"{eye_sec:.2f}",
                 head_swing=cell(h_swing, "{:.2f}"), l_fused=str(l_fused),
                 # `src` 是判据的一部分（ui/state.py 按它报哪条规则响的），
                 # 不是调试字段。camera 的 mark 恒 0（界面这条路没有空格标记）。
                 src=str(src_of_level),
                 ear=cell(ear), mar=cell(mar), pitch=cell(pitch, "{:.2f}"),
                 mark="0")
        return d

    # ------------------------------------------------------------ 出图
    def _encode(self, bgr):
        import cv2
        h, w = bgr.shape[:2]
        if w > self.out_w:
            s = self.out_w / w
            bgr = cv2.resize(bgr, (self.out_w, int(round(h * s))),
                             interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 76])
        if ok:
            self.jpeg = buf.tobytes()
            self.seq += 1

    # ------------------------------------------------------------ 对外
    def poll(self, now: float):
        return self.latest

    def info(self) -> dict:
        return {"frames": self.frames, "fps": round(self.fps, 1),
                "error": self.error, "replay": bool(self.replay),
                "model": self.model_name, "window": self.window}

    def stop(self):
        self._stop.set()
        self._th.join(timeout=1.5)


# ---------------------------------------------------------------- 单独跑
def main():
    ap = argparse.ArgumentParser(description="界面用的实时推理源")
    ap.add_argument("--cam", type=int, default=0)
    ap.add_argument("--replay", default=None, help="跑视频而不是摄像头")
    ap.add_argument("--fast", action="store_true")
    ap.add_argument("--dump", default=None, help="逐次决策写 CSV（用于对拍 fuse.py）")
    ap.add_argument("--seconds", type=float, default=None)
    ap.add_argument("--no-overlay", action="store_true")
    a = ap.parse_args()

    src = CamSource(replay=a.replay, cam=a.cam, fast=a.fast,
                    log_probs=a.dump, overlay=not a.no_overlay)
    print(f"源       : {'回放 ' + a.replay if a.replay else f'摄像头 {a.cam}'}")
    print(f"支路一   : {src.model_name}  窗口 {src.window} 帧")
    print(f"支路二   : 窗口 {F.WIN_SEC:.0f} s  缓冲 {HIST_SEC:.0f} s")
    t0 = time.time()
    try:
        while src.error is None or src.frames == 0:
            time.sleep(0.25)
            if a.seconds and time.time() - t0 > a.seconds:
                break
            h = src.head
            if h:
                print(f"\r  [{h['t']:>7}s] L{h['l_fused']} gate={h['gate']} "
                      f"pc={h['perclos']} pfat={h['p_fat']} "
                      f"{src.fps:4.1f} fps   ", end="")
    except KeyboardInterrupt:
        pass
    print(f"\n结束：{src.error or '跑满 %s s' % a.seconds}  共 {src.frames} 帧")
    src.stop()
    if a.dump:
        print(f"已写出 {a.dump}")
    # 两个 landmarker 各析构 42 秒，必须硬退（见 src/fuse.py 的同款注释）
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
