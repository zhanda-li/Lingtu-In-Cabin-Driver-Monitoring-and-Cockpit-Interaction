"""眼区**图像纹理**能不能分开"捂嘴哈欠"和"说话"？

背景：文献（IEEE FG 2018 / Ibrahim 2015）测捂嘴哈欠用的是**图像纹理**
（眼周 HOG/LBP/Sobel 边缘），不是我们一直在用的几何量。我没试过这条路。

设计要点 —— 必须能证伪：
  训练：5 段捂嘴哈欠(正) + 5 段说话(负)
  留出：normal / glance 片段**完全不参与训练**。它们是"绝对不该被当成哈欠"的
        对照。如果它们也被判成哈欠，说明这个特征只是学到了"光照/人/场次"，
        不是哈欠 —— 直接判死。

特征（都是眼区裁剪图上的，手挡不住这一块）：
  LBP 直方图 256 维  —— 对光照单调变化不敏感，文献里的主力
  Sobel 边缘强度     —— "面部形变/皱纹"那个路子
裁剪图做逐帧对比度归一化，尽量不让光照泄进去。

不是正式工具，验完就删。
"""
import os
import sys
from pathlib import Path

import cv2
import numpy as np
from scipy.ndimage import sobel
from sklearn.svm import LinearSVC

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import config as C

# 眼睛区域的关键点（内外眼角 + 上下眼睑）
EYE_PTS = [33, 133, 159, 145, 362, 263, 386, 374]
ROI_PAD = 0.6          # 外扩比例，把眼周皱纹纳进来
CROP = (64, 32)        # (w, h)

FIRST = 999            # 取整段。取前 N 秒会漏掉哈欠的眯眼相位


def lbp_hist(g):
    """256 维 LBP 直方图。g: uint8 (H,W)"""
    c = g[1:-1, 1:-1]
    code = np.zeros(c.shape, dtype=np.uint8)
    for i, (dy, dx) in enumerate([(-1, -1), (-1, 0), (-1, 1), (0, 1),
                                  (1, 1), (1, 0), (1, -1), (0, -1)]):
        n = g[1 + dy:g.shape[0] - 1 + dy, 1 + dx:g.shape[1] - 1 + dx]
        code |= ((n >= c).astype(np.uint8) << i)
    h = np.bincount(code.ravel(), minlength=256).astype(np.float32)
    return h / (h.sum() + 1e-6)


def feat(crop):
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float32)
    g = (g - g.mean()) / (g.std() + 1e-6)          # 对比度归一化
    g8 = np.clip(g * 32 + 128, 0, 255).astype(np.uint8)
    e = np.hypot(sobel(g, 0), sobel(g, 1))
    return np.concatenate([lbp_hist(g8), [e.mean(), e.std()]])


def run(lmk, mp, video, ts_base):
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(fps / C.TARGET_FPS)))
    n_max = int(FIRST * C.TARGET_FPS)
    fs, n_read, k = [], 0, 0
    while len(fs) < n_max:
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
        res = lmk.detect_for_video(
            mp.Image(image_format=mp.ImageFormat.SRGB,
                     data=np.ascontiguousarray(rgb)),
            ts_base + int(k / C.TARGET_FPS * 1000))
        if not res.face_landmarks:
            continue
        lm = res.face_landmarks[0]
        P = np.array([[lm[j].x * w, lm[j].y * h] for j in EYE_PTS])
        x0, y0 = P.min(0)
        x1, y1 = P.max(0)
        bw, bh = x1 - x0, y1 - y0
        x0 = max(0, int(x0 - bw * ROI_PAD)); x1 = min(w, int(x1 + bw * ROI_PAD))
        y0 = max(0, int(y0 - bh * ROI_PAD)); y1 = min(h, int(y1 + bh * ROI_PAD))
        if x1 - x0 < 8 or y1 - y0 < 4:
            continue
        fs.append(feat(cv2.resize(frame[y0:y1, x0:x1], CROP)))
    cap.release()
    return np.array(fs), ts_base + int(k / C.TARGET_FPS * 1000) + 1000


def main():
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision

    lmk = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(
            model_asset_path=str(C.MODELS_DIR / "face_landmarker.task")),
        running_mode=vision.RunningMode.VIDEO, num_faces=1))

    groups = [("yawn", "pos"), ("talking", "neg"), ("yawn_open", "pos"),
              ("normal", "hold"), ("glance", "hold"), ("phone", "hold")]
    clips = {}
    ts_base = 0
    for g, role in groups:
        vids = sorted((C.DATA_RAW / g).glob("*.mp4"))[:5]
        for v in vids:
            f, ts_base = run(lmk, mp, v, ts_base)
            if len(f) < 20:
                print(f"[skip] {v.name} 有效帧 {len(f)}")
                continue
            # 每段取整段的 90 分位（"最像眯眼的那一刻"）当该段的描述子
            clips[v.stem] = (g, role, np.percentile(f, 90, axis=0))
            print(f"  {v.stem:<16} {role:<5} 帧 {len(f):>4}  dim {f.shape[1]}")

    names = list(clips)
    X = np.stack([clips[n][2] for n in names])
    X = (X - X.mean(0)) / (X.std(0) + 1e-6)
    np.savez(ROOT / "_scratch" / "_tex_feat.npz", X=X, names=np.array(names),
             role=np.array([clips[n][1] for n in names]))

    tr = [i for i, n in enumerate(names) if clips[n][1] in ("pos", "neg")]
    te = [i for i, n in enumerate(names) if clips[n][1] == "hold"]
    y = np.array([1 if clips[names[i]][1] == "pos" else 0 for i in tr])

    def loo(labels, idx=None):
        idx = tr if idx is None else idx
        hit = []
        for j in range(len(idx)):
            keep = [idx[i] for i in range(len(idx)) if i != j]
            m = LinearSVC(C=1.0, max_iter=5000).fit(X[keep], np.delete(labels, j))
            hit.append(int(m.predict(X[[idx[j]]])[0] == labels[j]))
        return np.array(hit)

    hit = loo(y)
    print(f"\n[1] 留一交叉验证（{len(tr)} 段：哈欠 vs 说话/其它）:"
          f" {hit.sum()}/{len(tr)} = {100*hit.mean():.0f}%")
    print("    逐段：")
    for i, j in enumerate(tr):
        print(f"      {names[j]:<16} ({clips[names[j]][0]:<9}) "
              f"{'✅' if hit[i] else '❌ 错'}")

    # 置换检验：把标签打乱，看"乱猜"能到多少。
    # 15 段 / 258 维，线性 SVM 靠噪声也能到 80%+，不做这一步 87% 毫无意义。
    rng = np.random.default_rng(0)
    null = np.array([loo(y[rng.permutation(len(y))]).mean() for _ in range(300)])
    p = float((null >= hit.mean()).mean())
    print(f"\n[2] 置换检验（300 次打乱标签）:")
    print(f"    真实 {100*hit.mean():.0f}%   乱猜均值 {100*null.mean():.0f}%"
          f"   乱猜 95 分位 {100*np.percentile(null,95):.0f}%"
          f"   乱猜最高 {100*null.max():.0f}%")
    print(f"    p = {p:.3f}  ->  "
          + ("✅ 真信号（乱猜达不到）" if p < 0.05
             else "❌ 不显著：87% 靠乱猜也能到，这个特征没学到哈欠"))

    # 关键：留出组会不会误报
    m = LinearSVC(C=1.0, max_iter=5000).fit(X[tr], y)
    print(f"\n[3] 用全部 {len(tr)} 段训练后，测**没参与训练**的片段：")
    fake = 0
    for i in te:
        pr = m.predict(X[[i]])[0]
        fake += int(pr == 1)
        print(f"    {names[i]:<16} ({clips[names[i]][0]:<8}) -> "
              f"{'判成哈欠 ❌' if pr == 1 else '正常 ✅'}")
    print(f"    留出组误报 {fake}/{len(te)}")

    sys.stdout.flush(); sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
