"""临时探针：在这几个关键片段上导出 FaceMesh blendshape，看 eyeLook* 有没有区分度。

不是正式工具，验完就删。
"""
import os
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import config as C

WANT = ["eyeBlinkLeft", "eyeBlinkRight",
        "eyeLookDownLeft", "eyeLookDownRight",
        "eyeLookUpLeft", "eyeLookUpRight",
        "eyeLookInLeft", "eyeLookInRight",
        "eyeLookOutLeft", "eyeLookOutRight",
        "eyeSquintLeft", "eyeSquintRight", "jawOpen"]

# (类别, 片段名, 说明)
PICKS = [
    ("glance", "glance_16", "扭头幅度大  模型100%对"),
    ("glance", "glance_11", "扭头幅度大  模型100%对"),
    ("glance", "glance_24", "扭头幅度小  模型12%错"),
    ("phone", "phone_01", "低头深      模型100%对"),
    ("phone", "phone_14", "低头浅      模型100%对"),
    ("phone", "phone_19", "低头浅+偏头 模型45%错"),
    ("normal", "normal_14", "正坐对照    模型77%"),
    ("normal", "normal_19", "正坐对照    模型100%对"),
]


def main():
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision

    path = C.MODELS_DIR / "face_landmarker.task"
    if not path.exists():
        raise SystemExit(f"缺模型文件 {path}")

    opts = vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(path)),
        running_mode=vision.RunningMode.VIDEO,
        num_faces=1,
        output_face_blendshapes=True,          # <-- 关键开关
        min_face_detection_confidence=0.5,
        min_face_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    lmk = vision.FaceLandmarker.create_from_options(opts)

    print(f"{'片段':<11}{'帧数':>5}{'检出率':>8}   " +
          "".join(f"{k[:9]:>10}" for k in
                  ["eyeBlinkAvg", "eyeLookDown", "eyeLookUp", "eyeSquint", "jawOpen"]))
    print("-" * 108)
    rows = {}
    # 时间戳必须全进程单调递增，跨片段也不能重置 —— 见 src/pose.py 的 _last_ts
    ts_base = 0
    for cls, name, note in PICKS:
        video = C.DATA_RAW / cls / f"{name}.mp4"
        cap = cv2.VideoCapture(str(video))
        src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        step = max(1, int(round(src_fps / C.TARGET_FPS)))
        vals, n_read, n_face = [], 0, 0
        k = 0
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
            res = lmk.detect_for_video(img, ts_base + int(k / C.TARGET_FPS * 1000))
            if not res.face_blendshapes:
                continue
            n_face += 1
            vals.append({c.category_name: c.score for c in res.face_blendshapes[0]})
        cap.release()
        ts_base += int(k / C.TARGET_FPS * 1000) + 1000

        if not vals:
            print(f"{name:<11}{n_read:>5}{0:>7.0f}%   全程没检出人脸")
            rows[name] = None
            continue

        def med(*keys):
            return float(np.median([np.mean([v[k] for k in keys]) for v in vals]))

        blink = med("eyeBlinkLeft", "eyeBlinkRight")
        down = med("eyeLookDownLeft", "eyeLookDownRight")
        up = med("eyeLookUpLeft", "eyeLookUpRight")
        squint = med("eyeSquintLeft", "eyeSquintRight")
        jaw = med("jawOpen")
        rows[name] = {"blink": blink, "down": down, "up": up,
                      "squint": squint, "jaw": jaw, "vals": vals,
                      "note": note, "cls": cls}
        print(f"{name:<11}{n_face:>5}{n_face/max(n_read//step,1)*100:>7.0f}%   "
              f"{blink:>10.3f}{down:>10.3f}{up:>10.3f}{squint:>10.3f}{jaw:>10.3f}")

    # 眼珠在眼眶里的水平位置（正 = 眼珠偏向人的左侧）
    print("\n眼珠水平偏移（eyeLookOut_L + eyeLookIn_R  -  eyeLookIn_L - eyeLookOut_R）：")
    for name, r in rows.items():
        if not r:
            continue
        h = float(np.median([
            (v["eyeLookOutLeft"] + v["eyeLookInRight"]) -
            (v["eyeLookInLeft"] + v["eyeLookOutRight"]) for v in r["vals"]]))
        print(f"   {name:<11}{h:>+8.3f}   ({r['cls']}, {r['note']})")

    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)          # FaceLandmarker 析构同样很慢，见 src/pose.py


if __name__ == "__main__":
    main()
