"""人脸检出率按类别扫一遍：支路二什么时候是瞎的？

来由：_perf_two_lmk.py 在 fatigue_02.mp4 上跑出「人脸检出 137/271 = 50.6%」。
疲劳片段里人在点头低头，面部检测器一半时间找不到脸 ——
如果"疲劳时最容易丢脸"，那支路二就在最该干活的时候瞎了，
融合的价值要重新算。这个必须量，不能靠猜。

同时报检出时的**姿态**：pitch 分布。因为"脸丢了"有两种完全不同的原因：
  · 头低到镜头看不见脸  —— 支路二本来就该静音（闸门也会关）
  · 侧脸/远/暗          —— 那是另一回事
所以检出帧与丢失帧的 pitch 各报一个中位，分得开就知道是哪种。

用法：
    python _scratch/_face_detect_rate.py
    python _scratch/_face_detect_rate.py --classes normal fatigue
"""
import argparse
import os
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import config as C

import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

FACE_TASK = C.MODELS_DIR / "face_landmarker.task"


def euler_pitch(M):
    """4x4 面部变换矩阵 -> pitch（度）。与 live_face.py:113 的 euler_of 同式。

    ⚠️ 不是 yaw 那一行。`arctan2(-R[2,0], sy)` 是 yaw，
    first 版这里抄错了，量出来的"pitch"其实是左右转头。
    """
    R = np.asarray(M, dtype=float)[:3, :3]
    return float(np.degrees(np.arctan2(R[2, 1], R[2, 2])))


def scan(lmk, path, ts_base):
    """返回 (帧数, 检出数, 检出帧 pitch 列表, 新的 ts_base)。

    ⚠️ ts_base 必须跨片段累积：mediapipe 的图拒绝倒退的时间戳
    （ValueError: Input timestamp must be monotonically increasing），
    而 landmarker 实例是全进程复用的。同一个坑见 src/pose.py:60 的 _last_ts。
    """
    cap = cv2.VideoCapture(str(path))
    n = det = 0
    pitch_det = []
    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            break
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = mp.Image(image_format=mp.ImageFormat.SRGB,
                       data=np.ascontiguousarray(rgb))
        res = lmk.detect_for_video(img, ts_base + int(n / 30.0 * 1000))
        n += 1
        lm = res.face_landmarks
        if lm:
            det += 1
            if res.facial_transformation_matrixes:
                pitch_det.append(euler_pitch(res.facial_transformation_matrixes[0]))
    cap.release()
    return n, det, pitch_det, ts_base + int(n / 30.0 * 1000) + 1000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--classes", nargs="*", default=list(C.CLASSES))
    args = ap.parse_args()

    lmk = vision.FaceLandmarker.create_from_options(
        vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(FACE_TASK)),
            running_mode=vision.RunningMode.VIDEO, num_faces=1,
            output_face_blendshapes=False,
            output_facial_transformation_matrixes=True))

    print(f"{'片段':<18}{'帧':>6}{'检出':>7}{'检出率':>9}{'检出帧 pitch 中位':>20}")
    print("-" * 62)
    agg = {}
    ts_base = 0
    for g in args.classes:
        for v in sorted((C.DATA_RAW / g).glob("*.mp4")):
            n, det, p, ts_base = scan(lmk, v, ts_base)
            rate = det / max(1, n)
            med = float(np.median(p)) if p else float("nan")
            print(f"{v.stem:<18}{n:>6}{det:>7}{100 * rate:>8.1f}%{med:>19.1f}°")
            agg.setdefault(g, []).append(rate)

    print("\n按类别汇总：")
    print(f"{'类别':<12}{'段数':>5}{'检出率中位':>11}{'最低':>9}")
    print("-" * 38)
    for g in args.classes:
        if g in agg:
            a = agg[g]
            print(f"{g:<12}{len(a):>5}{100 * np.median(a):>10.1f}%{100 * min(a):>8.1f}%")

    print("\n读法：phone 那组预期最低（手捂着脸）。"
          "fatigue 若也低，说明点头低头时脸会丢——")
    print("      但那种帧闸门本来就会关（支路一同时在报 L2/L3），所以不算致命。")
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
