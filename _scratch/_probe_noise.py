# 头动幅度 vs blendshape-姿态相关强度；顺带给出估计器的噪声底
import sys
from pathlib import Path
import numpy as np, pandas as pd
ROOT = Path(".").resolve(); sys.path.insert(0, str(ROOT))
import config as C
from scipy.stats import spearmanr
W, H = 1280.0, 720.0
PICKS = [("normal","normal_14"),("normal","normal_19"),("glance","glance_16"),
         ("glance","glance_11"),("glance","glance_24"),("phone","phone_14"),
         ("phone","phone_19"),("fatigue","fatigue_16"),("fatigue","fatigue_13")]
sm = lambda v,k=7: np.convolve(v, np.ones(k)/k, "same")
print(f"{'片段':<12}{'类别':<9}{'yaw范围':>9}{'pitch范围':>10}"
      f"{'max|r|(down)':>14}{'down_IQR':>10}")
print("-"*66)
xs, ys = [], []
for cls, name in PICKS:
    f = ROOT/"_facecsv"/f"{name}.csv"
    df = pd.read_csv(f).dropna()
    p = pd.read_csv(C.DATA_POSE/cls/f"{name}.csv")
    sw = np.sqrt(((p.x11-p.x12)*W)**2+((p.y11-p.y12)*H)**2).to_numpy()
    shy = ((p.y11+p.y12)/2*H).to_numpy(); shx = ((p.x11+p.x12)/2*W).to_numpy()
    pitch = sm(((p.y0.to_numpy()*H)-shy)/sw); yaw = sm(((p.x0.to_numpy()*W)-shx)/sw)
    n = min(len(df), len(pitch)); d = df.iloc[:n]
    down = sm(d[["eyeLookDownLeft","eyeLookDownRight"]].mean(axis=1).to_numpy())[:n]
    yaw_r = np.percentile(yaw[:n],95)-np.percentile(yaw[:n],5)
    pit_r = np.percentile(pitch[:n],95)-np.percentile(pitch[:n],5)
    r = max(abs(spearmanr(down, pitch[:n]).statistic),
            abs(spearmanr(down, yaw[:n]).statistic))
    iqr = np.percentile(down,75)-np.percentile(down,25)
    print(f"{name:<12}{cls:<9}{yaw_r:>9.3f}{pit_r:>10.3f}{r:>14.2f}{iqr:>10.3f}")
    xs.append(max(yaw_r, pit_r)); ys.append(r)
xs, ys = np.array(xs), np.array(ys)
print(f"\n头动幅度 vs |r| 的 Spearman = {spearmanr(xs, ys).statistic:+.2f}  (n={len(xs)})")
