"""把 15 fps 片段降成 10 fps，用来复现"摄像头比 15 Hz 慢"的现场条件。"""
import cv2, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
CLIPS = [("fatigue","fatigue_16"),("fatigue","fatigue_01"),("fatigue","fatigue_09"),
         ("normal","normal_14"),("normal","normal_19")]
for cls, name in CLIPS:
    src = cv2.VideoCapture(str(ROOT/"data"/"raw"/cls/f"{name}.mp4"))
    fps = src.get(cv2.CAP_PROP_FPS); w, h = int(src.get(3)), int(src.get(4))
    out = cv2.VideoWriter(str(ROOT/"_scratch"/"_fps10"/f"{name}.mp4"),
                          cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (w, h))
    i = n = 0
    while True:
        ok, f = src.read()
        if not ok: break
        if i % 3 != 2:            # 15 帧里留 10 帧 -> 10 fps
            out.write(f); n += 1
        i += 1
    src.release(); out.release()
    print(f"{name}: {i} 帧 @{fps:.0f} -> {n} 帧 @10")
