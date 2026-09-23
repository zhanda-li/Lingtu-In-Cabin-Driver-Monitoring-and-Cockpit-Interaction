"""追一件事：jawOpen 分不开捂嘴哈欠和说话，但 eyeBlink 看着能分开。

疑点：talking 五段的 eyeBlink 最高只有 0.12~0.16，
      可老数据里 normal 片段正常眨眼能到 0.69~0.72。
      两个都是"没打哈欠"的活动，差 4.5 倍 —— 这不正常。

两种可能：
  A. 真的是哈欠眼反射：捂嘴哈欠时 eyeBlink 会跟着抬起来，说话不会 → 有戏
  B. 纯粹是"这几段没眨眼"：talking 录得短、人说话时刚好没眨 → 是假象

分不清就是假结论。要查两件事：
  Q1 talking 段里到底有没有眨眼？（时长、闭眼帧数）
  Q2 yawn 段里 eyeBlink 是不是和 jawOpen **同时**抬起来？（时序相关性）
     同时 → A；各抬各的 → B。
"""
import os
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import config as C

GROUPS = ["normal", "glance", "phone", "fatigue", "yawn", "yawn_open", "talking"]
NEW = {"yawn", "yawn_open", "talking"}
BLINK_HI = 0.40          # 超过它算"闭了眼"


def run(lmk, mp, video, ts_base):
    cap = cv2.VideoCapture(str(video))
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(src_fps / C.TARGET_FPS)))
    jaw, blink, ts = [], [], []
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
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = mp.Image(image_format=mp.ImageFormat.SRGB,
                       data=np.ascontiguousarray(rgb))
        res = lmk.detect_for_video(img, ts_base + int(k / C.TARGET_FPS * 1000))
        if not res.face_blendshapes:
            continue
        n_face += 1
        bs = {c.category_name: c.score for c in res.face_blendshapes[0]}
        jaw.append(bs.get("jawOpen", np.nan))
        blink.append(0.5 * (bs.get("eyeBlinkLeft", np.nan) +
                            bs.get("eyeBlinkRight", np.nan)))
        ts.append(k / C.TARGET_FPS)
    cap.release()
    return (np.array(jaw), np.array(blink), np.array(ts), n_read, n_face,
            ts_base + int(k / C.TARGET_FPS * 1000) + 1000)


def main():
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision

    lmk = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(
            model_asset_path=str(C.MODELS_DIR / "face_landmarker.task")),
        running_mode=vision.RunningMode.VIDEO, num_faces=1,
        output_face_blendshapes=True))

    print(f"{'片段':<16}{'时长':>6}{'帧':>5}{'闭眼帧':>7}{'闭眼次':>7}"
          f"{'blink峰值':>10}{'jaw峰值':>9}{'r(jaw,blink)':>14}")
    print("-" * 84)
    store = {}
    ts_base = 0
    for g in GROUPS:
        n = 5 if g in NEW else 999
        for video in sorted((C.DATA_RAW / g).glob("*.mp4"))[:n]:
            jaw, blink, ts, n_read, n_face, ts_base = run(lmk, mp, video, ts_base)
            if len(jaw) < 5:
                print(f"{video.name:<16}   全程没检出人脸")
                continue
            above = blink > BLINK_HI
            n_ev = int(np.sum(np.diff(above.astype(int)) == 1)) + int(above[0])
            r = float(np.corrcoef(jaw, blink)[0, 1]) if jaw.std() > 1e-6 and blink.std() > 1e-6 else float("nan")
            dur = float(ts[-1]) if len(ts) else 0.0
            print(f"{video.name:<16}{dur:>6.1f}{len(jaw):>5}{int(above.sum()):>7}"
                  f"{n_ev:>7}{blink.max():>10.3f}{jaw.max():>9.3f}{r:>+14.2f}")
            store[video.name] = (g, jaw, blink, ts)

    # Q2：yawn 段里两路信号是不是同时抬起来
    print("\n哈欠段：jawOpen 高的时候，eyeBlink 在不在高位？（每段取 jawOpen 前 25% 的帧）")
    for name, (g, jaw, blink, ts) in store.items():
        if g not in ("yawn", "yawn_open"):
            continue
        thr = np.percentile(jaw, 75)
        hi = jaw >= thr
        print(f"  {name:<16} jaw 高的帧 n={int(hi.sum()):>3}  "
              f"那些帧的 blink 均值 {blink[hi].mean():.3f}   "
              f"jaw 低的帧 {blink[~hi].mean():.3f}   "
              f"（全体 {blink.mean():.3f}）")

    # 时间线：看两段的实际波形
    for name in ("yawn_02.mp4", "talking_02.mp4"):
        if name not in store:
            continue
        g, jaw, blink, ts = store[name]
        print(f"\n{name} 波形（每 0.4 s 一个点，J=jawOpen  B=eyeBlink）：")
        for i in range(0, len(jaw), max(1, int(0.4 * C.TARGET_FPS))):
            bar_j = "#" * int(jaw[i] * 30)
            bar_b = "*" * int(blink[i] * 30)
            print(f"  t={ts[i]:5.1f}s  J{jaw[i]:5.2f}|{bar_j:<31}B{blink[i]:5.2f}|{bar_b}")

    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
