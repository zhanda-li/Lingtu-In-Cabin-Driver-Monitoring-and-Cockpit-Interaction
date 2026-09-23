"""临时探针 2：眼睛区域裁图 + 逐帧 blendshape 落盘。

目的：用一个脚本同时拿到
  (1) 眼睛区域的可视化（肉眼验证 blendshape 的数字是不是在说真话）
  (2) 逐帧 blendshape CSV（后续做"去掉头部姿态后还剩多少信息"的回归分析）
  (3) 段内波动性（用户原话："疲劳视线飘忽、玩手机视线稳定"——这是动力学主张，
      中位数根本测不到，必须看段内方差）

验完就删。
"""
import csv
import os
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import config as C

OUT = ROOT / "_facecsv"
OUT.mkdir(exist_ok=True)

PICKS = [
    ("normal", "normal_14", "正坐 模型77%"),
    ("normal", "normal_19", "正坐 模型100%"),
    ("glance", "glance_16", "扭头大 100%"),
    ("glance", "glance_11", "扭头大 100%"),
    ("glance", "glance_24", "扭头小 12%错"),
    ("phone", "phone_01", "低头深 100%"),
    ("phone", "phone_14", "低头浅 100%"),
    ("phone", "phone_19", "低头浅+偏头 45%错"),
    ("fatigue", "fatigue_16", "点头 100%"),
    ("fatigue", "fatigue_13", "点头 100%"),
]

BLEND = ["eyeBlinkLeft", "eyeBlinkRight", "eyeLookDownLeft", "eyeLookDownRight",
         "eyeLookUpLeft", "eyeLookUpRight", "eyeLookInLeft", "eyeLookInRight",
         "eyeLookOutLeft", "eyeLookOutRight", "eyeSquintLeft", "eyeSquintRight",
         "jawOpen", "browDownLeft", "browDownRight", "mouthPressLeft",
         "mouthPressRight", "cheekSquintLeft", "cheekSquintRight"]

# FaceMesh 468 点里的眼角索引（左右由 mediapipe 命名决定，这里只用它们定位裁剪框）
EYE_PTS = [33, 133, 362, 263, 468, 473]


def crop_eyes(frame, lms):
    h, w = frame.shape[:2]
    px = [(int(lms[i].x * w), int(lms[i].y * h)) for i in EYE_PTS]
    xs = [p[0] for p in px]; ys = [p[1] for p in px]
    cx = (min(xs) + max(xs)) // 2
    cy = (min(ys) + max(ys)) // 2
    half_w = max(60, int((max(xs) - min(xs)) * 0.85))
    half_h = max(28, int(half_w * 0.38))
    x0, x1 = max(0, cx - half_w), min(w, cx + half_w)
    y0, y1 = max(0, cy - half_h), min(h, cy + half_h)
    if x1 - x0 < 20 or y1 - y0 < 10:
        return None
    c = frame[y0:y1, x0:x1]
    return cv2.resize(c, (360, 140), interpolation=cv2.INTER_CUBIC)


def main():
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision

    opts = vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(
            model_asset_path=str(C.MODELS_DIR / "face_landmarker.task")),
        running_mode=vision.RunningMode.VIDEO,
        num_faces=1,
        output_face_blendshapes=True,
        min_face_detection_confidence=0.5,
        min_face_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    lmk = vision.FaceLandmarker.create_from_options(opts)

    ts_base = 0
    stats, sheets = {}, {}

    for cls, name, note in PICKS:
        cap = cv2.VideoCapture(str(C.DATA_RAW / cls / f"{name}.mp4"))
        src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        step = max(1, int(round(src_fps / C.TARGET_FPS)))
        recs, shots, k, i = [], [], 0, 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            idx = i; i += 1
            if idx % step:
                continue
            k += 1
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            res = lmk.detect_for_video(
                mp.Image(image_format=mp.ImageFormat.SRGB,
                         data=np.ascontiguousarray(rgb)),
                ts_base + int(k / C.TARGET_FPS * 1000))
            if not res.face_blendshapes:
                recs.append(None)
                continue
            recs.append({c.category_name: c.score for c in res.face_blendshapes[0]})
            crop = crop_eyes(frame, res.face_landmarks[0])
            if crop is not None:
                shots.append((k, crop))
        cap.release()
        ts_base += int(k / C.TARGET_FPS * 1000) + 1000

        good = [r for r in recs if r]
        if not good:
            stats[name] = None
            continue

        # 逐帧落盘
        with open(OUT / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
            wr = csv.writer(f)
            wr.writerow(["frame"] + BLEND)
            for n, r in enumerate(recs):
                wr.writerow([n] + ([""] * len(BLEND) if not r
                                   else [f"{r.get(b, float('nan')):.5f}" for b in BLEND]))

        arr = {b: np.array([r[b] for r in good]) for b in BLEND}
        down = (arr["eyeLookDownLeft"] + arr["eyeLookDownRight"]) / 2
        horz = ((arr["eyeLookOutLeft"] + arr["eyeLookInRight"]) -
                (arr["eyeLookInLeft"] + arr["eyeLookOutRight"]))
        blink = (arr["eyeBlinkLeft"] + arr["eyeBlinkRight"]) / 2
        stats[name] = {
            "cls": cls, "note": note,
            "det": len(good) / max(len(recs), 1),
            "down_med": float(np.median(down)), "down_iqr": float(
                np.percentile(down, 75) - np.percentile(down, 25)),
            "horz_med": float(np.median(horz)), "horz_iqr": float(
                np.percentile(horz, 75) - np.percentile(horz, 25)),
            "blink_med": float(np.median(blink)),
        }
        # 每个片段挑 4 个时间点（在检到人脸的帧里均匀取）
        if len(shots) >= 4:
            sel = [shots[int(round(t))] for t in np.linspace(0, len(shots) - 1, 4)]
            sheets[name] = [s[1] for s in sel]

    print(f"{'片段':<12}{'类别':<9}{'检出':>5}  {'down中位':>9}{'down_IQR':>9}"
          f"{'horz中位':>10}{'horz_IQR':>9}{'blink中位':>10}   说明")
    print("-" * 104)
    for name, s in stats.items():
        if not s:
            print(f"{name:<12}{'':<9}{'0%':>5}   {'--':>9}{'--':>9}{'--':>10}{'--':>9}{'--':>10}"
                  f"   全程没检出人脸")
            continue
        print(f"{name:<12}{s['cls']:<9}{s['det']*100:>4.0f}%  "
              f"{s['down_med']:>9.3f}{s['down_iqr']:>9.3f}"
              f"{s['horz_med']:>+10.3f}{s['horz_iqr']:>9.3f}"
              f"{s['blink_med']:>10.3f}   {s['note']}")

    # 拼图：每行一个片段，4 个时间点的眼部裁剪
    rows = [(n, sheets[n]) for n, _ in [(p[1], 0) for p in PICKS] if n in sheets]
    if rows:
        cols = 4
        cell_w, cell_h = 360, 140
        sheet = np.full((len(rows) * (cell_h + 22), cols * cell_w, 3), 30, np.uint8)
        for r, (n, imgs) in enumerate(rows):
            y = r * (cell_h + 22)
            cv2.putText(sheet, f"{n}  ({stats[n]['note']})", (6, y + 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1, cv2.LINE_AA)
            for c in range(min(cols, len(imgs))):
                sheet[y + 22:y + 22 + cell_h, c * cell_w:(c + 1) * cell_w] = imgs[c]
                cv2.line(sheet, (c * cell_w, y + 22), (c * cell_w, y + 22 + cell_h),
                         (90, 90, 90), 1)
        cv2.imwrite(str(ROOT / "_eyes.png"), sheet)
        print(f"\n眼部拼图 -> _eyes.png  ({sheet.shape[1]}x{sheet.shape[0]})")
    print(f"逐帧 blendshape -> {OUT}/")

    sys.stdout.flush(); sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
