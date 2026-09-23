"""临时探针：量新录的 yawn / yawn_open / talking，看 jawOpen 到底上不上得去。

关键区别：这里看的是**峰值**（p90/p99/max），不是中位数。
哈欠是个瞬态事件，中位数会被"没打哈欠的那几秒"冲淡。

同时量三件事：
  1. jawOpen 峰值            —— 我原本提的那个信号
  2. MAR = |13-14|/|61-291|  —— 纯几何版本，和 blendshape 互为交叉验证
  3. 人脸检出率              —— 手捂上去会不会把脸整个搞丢

不是正式工具，验完就删。
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

LIP_UP, LIP_LO = 13, 14        # 上下内唇中点
CORNER_L, CORNER_R = 61, 291   # 嘴角
EYE_L, EYE_R = 33, 263         # 内外眼角（当尺度基准）


def pct(a, q):
    return float(np.percentile(a, q)) if len(a) else float("nan")


def probe(lmk, mp, video, ts_base):
    """返回 (每帧指标 dict of list, 读入帧数, 检出帧数, 新的 ts_base)"""
    cap = cv2.VideoCapture(str(video))
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(src_fps / C.TARGET_FPS)))
    col = {"jaw": [], "mar": [], "squint": [], "blink": [], "chin": []}
    n_read = n_face = k = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        i = n_read
        n_read += 1
        if i % step:
            continue
        k += 1
        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = mp.Image(image_format=mp.ImageFormat.SRGB,
                       data=np.ascontiguousarray(rgb))
        res = lmk.detect_for_video(img, ts_base + int(k / C.TARGET_FPS * 1000))
        if not res.face_blendshapes:
            continue
        n_face += 1
        bs = {c.category_name: c.score for c in res.face_blendshapes[0]}
        col["jaw"].append(bs.get("jawOpen", np.nan))
        col["squint"].append(0.5 * (bs.get("eyeSquintLeft", np.nan) +
                                    bs.get("eyeSquintRight", np.nan)))
        col["blink"].append(0.5 * (bs.get("eyeBlinkLeft", np.nan) +
                                   bs.get("eyeBlinkRight", np.nan)))

        lm = res.face_landmarks[0]
        px = lambda j: np.array([lm[j].x * w, lm[j].y * h])
        mouth_h = float(np.linalg.norm(px(LIP_UP) - px(LIP_LO)))
        mouth_w = float(np.linalg.norm(px(CORNER_L) - px(CORNER_R)))
        eye_w = float(np.linalg.norm(px(EYE_L) - px(EYE_R)))
        col["mar"].append(mouth_h / mouth_w if mouth_w > 1 else np.nan)
        col["chin"].append(float(np.linalg.norm(px(152) - px(10))) / eye_w
                           if eye_w > 1 else np.nan)
    cap.release()
    return col, n_read, n_face, ts_base + int(k / C.TARGET_FPS * 1000) + 1000


def main():
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision

    path = C.MODELS_DIR / "face_landmarker.task"
    if not path.exists():
        raise SystemExit(f"缺模型文件 {path}")

    lmk = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(path)),
        running_mode=vision.RunningMode.VIDEO,
        num_faces=1,
        output_face_blendshapes=True,
        min_face_detection_confidence=0.5,
        min_face_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    ))

    print(f"{'片段':<16}{'检出':>6}{'jaw p50':>9}{'p90':>7}{'p99':>7}"
          f"{'max':>7}   {'MAR p50':>8}{'max':>7}   {'眯眼 max':>8}{'闭眼 max':>8}")
    print("-" * 96)

    summary = {g: {} for g in GROUPS}
    ts_base = 0
    for g in GROUPS:
        for video in sorted((C.DATA_RAW / g).glob("*.mp4")):
            col, n_read, n_face, ts_base = probe(lmk, mp, video, ts_base)
            n_exp = max(n_read // max(1, int(round(
                (cv2.VideoCapture(str(video)).get(cv2.CAP_PROP_FPS) or 30.0)
                / C.TARGET_FPS))), 1)
            if not col["jaw"]:
                print(f"{video.name:<16}{0:>5.0f}%   全程没检出人脸  ← 手把脸挡住了？")
                continue
            jaw, mar = np.array(col["jaw"]), np.array(col["mar"])
            print(f"{video.name:<16}{n_face / n_exp * 100:>5.0f}%"
                  f"{pct(jaw,50):>9.3f}{pct(jaw,90):>7.3f}{pct(jaw,99):>7.3f}"
                  f"{jaw.max():>7.3f}   {pct(mar,50):>8.3f}{mar.max():>7.3f}   "
                  f"{pct(col['squint'],90):>8.3f}{pct(col['blink'],90):>8.3f}")
            for key, arr in (("jaw", jaw), ("mar", mar),
                             ("squint", col["squint"]), ("blink", col["blink"])):
                summary[g].setdefault(key, []).append(float(np.max(arr)))

    print("\n按组汇总（每段取自己的峰值，再跨段看分布）：")
    print(f"{'组':<12}{'n':>4}   {'jawOpen 峰值':>22}      {'MAR 峰值':>20}")
    print(f"{'':12}{'':4}   {'中位':>7}{'最高':>7}{'最低':>7}      "
          f"{'中位':>7}{'最高':>7}{'最低':>7}")
    for g in GROUPS:
        s = summary[g]
        if not s.get("jaw"):
            print(f"{g:<12}{0:>4}   （没有可用片段）")
            continue
        j, m = np.array(s["jaw"]), np.array(s["mar"])
        print(f"{g:<12}{len(j):>4}   {np.median(j):>7.3f}{j.max():>7.3f}{j.min():>7.3f}"
              f"      {np.median(m):>7.3f}{m.max():>7.3f}{m.min():>7.3f}")

    print("\n判据：yawn 的 jawOpen 峰值要明显高过 talking 的**最高**那一段才算分得开。")
    print("      跨组重叠 = 这个信号分不开 = 别做。")

    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
