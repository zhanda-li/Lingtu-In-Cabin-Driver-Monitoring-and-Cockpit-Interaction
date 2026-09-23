"""最后一问：捂嘴的哈欠，用"持续张开"这个特征能不能和说话分开？

前一轮量的是**峰值**。峰值是错的问法 —— 哈欠的本质不是"张得最大"，
是"张开并**保持**"。说话也能瞬间张到 0.87，但只保持一帧。

所以这里量三个候选特征，看跨组重不重叠：
  1. max 滚动均值（0.5 / 1.0 / 1.5 秒窗）  <- 生理上最对的那个
  2. jawOpen > 0.5 / > 0.7 的帧占比
  3. 最长连续"张开"时长（jawOpen > 0.5 的最长连通段）

只要 yawn 的最低值压不住 talking 的最高值，这条路就是死的。
"""
import os
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import config as C

GROUPS = ["yawn", "yawn_open", "talking"]
WINS = [0.5, 1.0, 1.5]


def roll_max(x, w):
    if len(x) < w:
        return float("nan")
    return float(np.max(np.convolve(x, np.ones(w) / w, mode="valid")))


def longest_run(mask):
    best = cur = 0
    for v in mask:
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return best / C.TARGET_FPS


def main():
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision

    lmk = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(
            model_asset_path=str(C.MODELS_DIR / "face_landmarker.task")),
        running_mode=vision.RunningMode.VIDEO, num_faces=1,
        output_face_blendshapes=True))

    hdr = (f"{'片段':<16}" + "".join(f"{'滚均'+str(w)+'s':>9}" for w in WINS)
           + f"{'>0.5占比':>10}{'>0.7占比':>10}{'最长张开':>10}")
    print(hdr)
    print("-" * len(hdr))

    feats = {g: [] for g in GROUPS}
    ts_base = 0
    for g in GROUPS:
        for video in sorted((C.DATA_RAW / g).glob("*.mp4")):
            cap = cv2.VideoCapture(str(video))
            src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            step = max(1, int(round(src_fps / C.TARGET_FPS)))
            jaw, n_read, k = [], 0, 0
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                i = n_read
                n_read += 1
                if i % step:
                    continue
                k += 1
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = mp.Image(image_format=mp.ImageFormat.SRGB,
                               data=np.ascontiguousarray(rgb))
                res = lmk.detect_for_video(
                    img, ts_base + int(k / C.TARGET_FPS * 1000))
                if not res.face_blendshapes:
                    continue
                jaw.append({c.category_name: c.score
                            for c in res.face_blendshapes[0]}.get("jawOpen", 0.0))
            cap.release()
            ts_base += int(k / C.TARGET_FPS * 1000) + 1000
            if len(jaw) < 20:
                print(f"{video.name:<16}   有效帧太少，跳过")
                continue
            x = np.array(jaw)
            row = ([roll_max(x, int(w * C.TARGET_FPS)) for w in WINS]
                   + [float((x > 0.5).mean()), float((x > 0.7).mean()),
                      longest_run(x > 0.5)])
            feats[g].append(row)
            print(f"{video.name:<16}" + "".join(f"{v:>9.3f}" for v in row[:3])
                  + f"{row[3]:>10.2f}{row[4]:>10.2f}{row[5]:>10.2f}")

    print("\n跨组对比（每组看最低值，因为判据是 yawn 的最低值要压住 talking 的最高值）：")
    names = [f"滚均{w}s" for w in WINS] + [">0.5占比", ">0.7占比", "最长张开(s)"]
    print(f"{'特征':<12}{'yawn 中位':>11}{'yawn 最低':>11}"
          f"{'talking 最高':>14}{'分得开?':>10}")
    for j, nm in enumerate(names):
        y = np.array([r[j] for r in feats["yawn"]])
        t = np.array([r[j] for r in feats["talking"]])
        sep = "✅ 分得开" if y.min() > t.max() else "❌ 重叠"
        print(f"{nm:<12}{np.median(y):>11.3f}{y.min():>11.3f}{t.max():>14.3f}{sep:>12}")

    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
