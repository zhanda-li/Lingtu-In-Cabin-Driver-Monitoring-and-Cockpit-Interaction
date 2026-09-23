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
print(f"{'片段':<12}{'类别':<9}{'yaw中位':>9}{'pitch中位':>10}{'|偏移|':>8}"
      f"{'down_IQR':>10}{'blink中位':>10}")
print("-"*70)
off, iqr, blk = [], [], []
for cls, name in PICKS:
    df = pd.read_csv(ROOT/"_facecsv"/f"{name}.csv").dropna()
    p = pd.read_csv(C.DATA_POSE/cls/f"{name}.csv")
    sw = np.sqrt(((p.x11-p.x12)*W)**2+((p.y11-p.y12)*H)**2).to_numpy()
    shy = ((p.y11+p.y12)/2*H).to_numpy(); shx = ((p.x11+p.x12)/2*W).to_numpy()
    pitch = sm(((p.y0.to_numpy()*H)-shy)/sw); yaw = sm(((p.x0.to_numpy()*W)-shx)/sw)
    n = min(len(df), len(pitch)); d = df.iloc[:n]
    down = sm(d[["eyeLookDownLeft","eyeLookDownRight"]].mean(axis=1).to_numpy())[:n]
    blink = sm(d[["eyeBlinkLeft","eyeBlinkRight"]].mean(axis=1).to_numpy())[:n]
    ym, pm = float(np.median(yaw[:n])), float(np.median(pitch[:n]))
    o = abs(ym)   # 俯仰的"中性"不是 0，用 yaw 偏移
    i = float(np.percentile(down,75)-np.percentile(down,25))
    print(f"{name:<12}{cls:<9}{ym:>+9.3f}{pm:>+10.3f}{o:>8.3f}{i:>10.3f}"
          f"{float(np.median(blink)):>10.3f}")
    off.append(o); iqr.append(i); blk.append(float(np.median(blink)))
print(f"\n|yaw偏移| vs down_IQR   Spearman = {spearmanr(off,iqr).statistic:+.2f}")
print(f"|yaw偏移| vs blink中位  Spearman = {spearmanr(off,blk).statistic:+.2f}")
