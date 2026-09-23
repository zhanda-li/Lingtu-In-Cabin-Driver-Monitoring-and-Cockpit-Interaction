"""前置门禁：Pose(full) + Face 两个 landmarker 同进程，能不能撑住 15 Hz？

为什么必须先量：docs/技术方案.md §8 只量过 Pose **单独**的 16.6 ms——
两个 landmarker 放同一个进程、同一个循环里跑，从来没量过。
融合程序 src/fuse.py 的整个前提就是这个，所以这是门禁：
过不了就先启用 --face-hz 给面部降频，而不是先把融合写完再回头发觉喂不满。

判据：合计中位 <= 60 ms（即 >= 16.7 FPS，能喂满 15 Hz 调度器）。
参考：摄像头本身只有 10~11 fps，所以"够不够"的底线其实是摄像头那一侧。

用法：
    python _scratch/_perf_two_lmk.py
    python _scratch/_perf_two_lmk.py --clip data/raw/fatigue/fatigue_02.mp4
    python _scratch/_perf_two_lmk.py --clip xxx.mp4 --frames 300 --face-hz 7

⚠️ 两个 landmarker 各自析构固定 42 秒（见 src/pose.py 的 close()），
所以结尾必须 os._exit(0)——两个实例就是 84 秒。
"""
import argparse
import os
import statistics
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
import config as C
from pose import PoseExtractor

import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

FACE_TASK = C.MODELS_DIR / "face_landmarker.task"


def pct(a, q):
    return float(np.percentile(a, q)) if len(a) else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default="data/raw/fatigue/fatigue_02.mp4")
    ap.add_argument("--frames", type=int, default=0, help="0 = 整段")
    ap.add_argument("--warmup", type=int, default=10,
                    help="前 N 帧不计入统计（首次调用要初始化图）")
    ap.add_argument("--pose-model", default=None, help="lite / full")
    ap.add_argument("--face-hz", type=float, default=0.0,
                    help=">0 时模拟面部降频：面部只每 1/N 秒检测一次")
    args = ap.parse_args()

    path = Path(args.clip)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        raise SystemExit(f"找不到视频 {path}")
    if not FACE_TASK.exists():
        raise SystemExit(f"找不到模型 {FACE_TASK}")

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise SystemExit(f"打不开视频 {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    print(f"片段 {path.name}  {n_total} 帧 @ {fps:.1f} fps")
    print(f"pose 模型 {args.pose_model or C.POSE_MODEL_NAME}"
          + (f"   face 降频到 {args.face_hz:.1f} Hz" if args.face_hz > 0 else ""))

    print("建两个 landmarker（这一段是加载时间，不是推理时间）...")
    t_build = time.perf_counter()
    pose = PoseExtractor(args.pose_model, running_mode="VIDEO")
    face = vision.FaceLandmarker.create_from_options(
        vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(FACE_TASK)),
            running_mode=vision.RunningMode.VIDEO, num_faces=1,
            output_face_blendshapes=False,
            output_facial_transformation_matrixes=True))
    print(f"  加载 {time.perf_counter() - t_build:.2f} s")

    t_pose, t_face, t_all = [], [], []
    n = n_face_det = n_pose_det = 0
    face_period = (1.0 / args.face_hz) if args.face_hz > 0 else 0.0
    next_face = 0.0
    # 降频时"上一次的面部结果"要留着，但那不影响耗时统计——只影响调用次数
    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            break
        mt = n / fps                       # 媒体时间，和 src/live.py 同源
        ts = int(mt * 1000)

        t0 = time.perf_counter()
        lm = pose.detect(frame, ts)
        t1 = time.perf_counter()
        did_face = (face_period == 0.0) or (mt >= next_face)
        if did_face:
            if face_period:
                next_face = mt + face_period
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = mp.Image(image_format=mp.ImageFormat.SRGB,
                           data=np.ascontiguousarray(rgb))
            res = face.detect_for_video(img, ts)
            if res.face_landmarks:
                n_face_det += 1
        t2 = time.perf_counter()

        n += 1
        if lm is not None:
            n_pose_det += 1
        if n > args.warmup:
            t_pose.append((t1 - t0) * 1000)
            if did_face:
                t_face.append((t2 - t1) * 1000)
            t_all.append((t2 - t0) * 1000)
        if args.frames and n >= args.frames:
            break
    cap.release()

    if not t_all:
        print("没跑到帧")
        os._exit(1)

    med_pose, med_face = statistics.median(t_pose), statistics.median(t_face)
    med_all = statistics.median(t_all)
    p95_all = pct(t_all, 95)
    fps_all = 1000.0 / med_all if med_all > 0 else float("inf")

    print(f"\n统计 {len(t_all)} 帧（跳过前 {args.warmup} 帧预热）")
    print(f"  骨骼检出 {n_pose_det}/{n}   人脸检出 {n_face_det}/{n}"
          + ("（面部降频，检出数只统计实际跑过的帧）" if face_period else ""))
    print(f"\n{'环节':<12}{'中位':>9}{'p95':>9}")
    print("-" * 32)
    print(f"{'pose':<12}{med_pose:>8.1f}m{pct(t_pose, 95):>8.1f}m")
    print(f"{'face':<12}{med_face:>8.1f}m{pct(t_face, 95):>8.1f}m")
    print(f"{'每帧合计':<12}{med_all:>8.1f}m{p95_all:>8.1f}m")
    print(f"\n等效 {fps_all:.1f} FPS（按每帧合计中位）")

    LIMIT = 60.0
    if med_all <= LIMIT:
        print(f"\n✅ 合计中位 {med_all:.1f} ms <= {LIMIT:.0f} ms —— "
              f"撑得住 15 Hz，融合可以按原方案写")
    else:
        print(f"\n❌ 合计中位 {med_all:.1f} ms > {LIMIT:.0f} ms —— "
              f"触发退路：给面部降频（--face-hz 7 或更低）后重测")
        if face_period == 0:
            print("   现在就在降频模式下，说明还得再降，或者换 --pose-model lite")

    print("\n对照：docs/技术方案.md §8 记的 Pose 单独 = 16.6 ms/帧（60 FPS）；"
          "摄像头实测 10~11 fps，是原来的瓶颈。")
    sys.stdout.flush()
    sys.stderr.flush()
    # 两个 landmarker 各 42 秒析构，必须跳过
    os._exit(0)


if __name__ == "__main__":
    main()
