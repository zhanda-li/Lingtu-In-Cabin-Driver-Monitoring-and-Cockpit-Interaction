"""把 fatigue 片段做时间压缩 = 模拟"点头点得更快"。周期 2.6s -> 1.7/1.3/0.9s"""
import cv2
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
SPEEDS = [1.5, 2.0, 3.0]
for name in ["fatigue_16", "fatigue_01"]:
    for sp in SPEEDS:
        step = int(round(sp))
        src = cv2.VideoCapture(str(ROOT/"data"/"raw"/"fatigue"/f"{name}.mp4"))
        w, h = int(src.get(3)), int(src.get(4))
        out = cv2.VideoWriter(str(ROOT/"_scratch"/"_fps10"/f"{name}_x{sp}.mp4"),
                              cv2.VideoWriter_fourcc(*"mp4v"), 15.0, (w, h))
        i = n = 0
        while True:
            ok, f = src.read()
            if not ok: break
            if i % step == 0:
                out.write(f); n += 1
            i += 1
        src.release(); out.release()
        print(f"{name} x{sp}: {i} -> {n} 帧, 新周期 ≈ {2.6/sp:.2f}s")
