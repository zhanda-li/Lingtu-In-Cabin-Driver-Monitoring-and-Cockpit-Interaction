import numpy as np, pandas as pd, torch, sys
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
from matplotlib.patches import Patch
sys.path.insert(0, "."); sys.path.insert(0, "src")
import config as C
from model import PoseTransformer

W, H, STR, WIN = 1280., 720., 15, 45
sd = torch.load("runs/20260922_200934/best.pt", map_location="cpu", weights_only=False)
m = PoseTransformer(**sd["model_kwargs"]); m.load_state_dict(sd["state_dict"]); m.eval()
z = np.load(C.DATA_DATASET / "dataset.npz", allow_pickle=True)
X, y, names = z["X_test"], z["y_test"], z["clip_test"]
with torch.no_grad():
    P = torch.softmax(m(torch.tensor(X)), 1).numpy()
pred = P.argmax(1)

COL = {"normal": "#7fbf7f", "glance": "#4c8fd6", "phone": "#e0a33e", "fatigue": "#d05a5a"}


def curves(nm, cls):
    df = pd.read_csv(C.DATA_POSE / cls / f"{nm}.csv")
    sw = np.sqrt(((df.x11 - df.x12) * W) ** 2 + ((df.y11 - df.y12) * H) ** 2).to_numpy()
    shy = ((df.y11 + df.y12) / 2 * H).to_numpy()
    shx = ((df.x11 + df.x12) / 2 * W).to_numpy()
    p = ((df.y0.to_numpy() * H) - shy) / sw
    q = ((df.x0.to_numpy() * W) - shx) / sw
    k = 7
    return np.convolve(p, np.ones(k) / k, "same"), np.convolve(q, np.ones(k) / k, "same")


picks = [("glance_16", "glance"), ("glance_24", "glance"),
         ("phone_01", "phone"), ("phone_19", "phone")]
fig, axes = plt.subplots(4, 1, figsize=(11.5, 10))
for ax, (nm, cls) in zip(axes, picks):
    p, q = curves(nm, cls); t = np.arange(len(p)) / 15
    ax.plot(t, q, color="#1f77b4", lw=1.3, label="yaw (head left/right)")
    ax.plot(t, p, color="#ff7f0e", lw=1.3, label="pitch (head down/up)")
    ax.axhline(0, color="#bbb", lw=.6)
    s = names == nm
    idx = np.where(s)[0]
    for off, pr in zip(idx, pred[s]):
        st = (off - idx[0]) * STR
        ax.axvspan(st / 15, (st + WIN) / 15, color=COL[C.CLASSES[pr]], alpha=.22, lw=0)
    acc = (pred[s] == y[s]).mean()
    ax.set_title(f"{nm} ({cls})  window acc {acc*100:.0f}%   bands = model verdict per window", fontsize=9)
    ax.set_ylabel("shoulder-width units", fontsize=8)
    ax.tick_params(labelsize=7); ax.grid(alpha=.25)
    if ax is axes[0]:
        ax.legend(fontsize=7, loc="lower right", ncol=2)
axes[-1].set_xlabel("time (s)", fontsize=8)
fig.legend(handles=[Patch(color=c, alpha=.45, label=n) for n, c in COL.items()],
           loc="lower center", ncol=4, fontsize=8, frameon=False, bbox_to_anchor=(.5, -.01))
plt.tight_layout(rect=[0, 0.03, 1, 1]); plt.savefig("_badclips.png", dpi=95)
print("saved _badclips.png")
