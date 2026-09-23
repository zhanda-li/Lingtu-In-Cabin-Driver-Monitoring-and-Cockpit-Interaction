"""临时探针 3：段内相关性检验。

问：eyeLook*/eyeBlink* 这几路 blendshape，究竟携带的是"眼珠相对眼眶的方向"，
    还是只是"头部姿态"的一个读数？

做法：同一片段内，把 blendshape 序列和**同一片段**的头部 pitch/yaw 序列做
     Spearman 秩相关。段内驾驶意图基本不变，所以：
      - 若相关很强 -> blendshape 主要由头姿驱动，不是独立的视线信号
      - 若相关很弱 -> blendshape 另有来源（可能是真的眼动，也可能是噪声）

验完就删。
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import config as C
from scipy.stats import spearmanr

W, H = 1280.0, 720.0
FACE = ROOT / "_facecsv"

PICKS = [("normal", "normal_14"), ("normal", "normal_19"),
         ("glance", "glance_16"), ("glance", "glance_11"), ("glance", "glance_24"),
         ("phone", "phone_14"), ("phone", "phone_19"),
         ("fatigue", "fatigue_16"), ("fatigue", "fatigue_13")]

FEATS = [("blink", ("eyeBlinkLeft", "eyeBlinkRight"), "mean"),
         ("lookDown", ("eyeLookDownLeft", "eyeLookDownRight"), "mean"),
         ("lookUp", ("eyeLookUpLeft", "eyeLookUpRight"), "mean"),
         ("lookHorz", None, "horz"),
         ("squint", ("eyeSquintLeft", "eyeSquintRight"), "mean")]


def head_pitch_yaw(cls, name):
    df = pd.read_csv(C.DATA_POSE / cls / f"{name}.csv")
    sw = np.sqrt(((df.x11 - df.x12) * W) ** 2 + ((df.y11 - df.y12) * H) ** 2).to_numpy()
    shy = ((df.y11 + df.y12) / 2 * H).to_numpy()
    shx = ((df.x11 + df.x12) / 2 * W).to_numpy()
    pitch = ((df.y0.to_numpy() * H) - shy) / sw
    yaw = ((df.x0.to_numpy() * W) - shx) / sw
    k = 7
    sm = lambda v: np.convolve(v, np.ones(k) / k, "same")
    return sm(pitch), sm(yaw)


def smooth(v, k=7):
    return np.convolve(v, np.ones(k) / k, "same")


print("段内 Spearman 秩相关 |  blendshape   vs   头部姿态")
print(f"{'片段':<12}{'类别':<9}{'帧':>5} "
      f"{'blink~p':>9}{'blink~y':>9}{'down~p':>8}{'down~y':>8}"
      f"{'up~p':>7}{'up~y':>7}{'horz~p':>8}{'horz~y':>8}{'sq~p':>7}{'sq~y':>7}")
print("-" * 116)

allr = {k: [] for k, _, _ in FEATS}
for cls, name in PICKS:
    f = FACE / f"{name}.csv"
    if not f.exists():
        continue
    df = pd.read_csv(f)
    df = df.dropna()
    if len(df) < 30:
        print(f"{name:<12}{cls:<9}{len(df):>5}   有效帧太少，跳过")
        continue
    pitch, yaw = head_pitch_yaw(cls, name)
    n = min(len(df), len(pitch))
    pitch, yaw = smooth(pitch[:n]), smooth(yaw[:n])
    dd = df.iloc[:n]

    row, cells = f"{name:<12}{cls:<9}{n:>5} ", {}
    for label, cols, how in FEATS:
        if how == "horz":
            v = ((dd.eyeLookOutLeft + dd.eyeLookInRight) -
                 (dd.eyeLookInLeft + dd.eyeLookOutRight)).to_numpy()
        else:
            v = dd[list(cols)].mean(axis=1).to_numpy()
        v = smooth(v)
        rp = spearmanr(v, pitch).statistic
        ry = spearmanr(v, yaw).statistic
        cells[label] = (rp, ry)
        allr[label].extend([abs(rp), abs(ry)])
        row += f"{rp:>9.2f}{ry:>9.2f}" if label in ("blink", "down") else \
               (f"{rp:>7.2f}{ry:>7.2f}" if label in ("up", "sq") else
                f"{rp:>8.2f}{ry:>8.2f}")
    print(row)

print("\n各特征 |r| 的汇总（越大 = 越像头姿的读数）")
for label, vals in allr.items():
    v = np.array(vals)
    print(f"   {label:<10} 中位 |r| = {np.median(v):.2f}   "
          f"最大 |r| = {v.max():.2f}    >0.7 的比例 = {(v > 0.7).mean()*100:.0f}%")

sys.stdout.flush()
