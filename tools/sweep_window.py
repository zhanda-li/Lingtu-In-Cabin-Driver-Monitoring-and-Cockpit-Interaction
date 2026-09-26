"""窗口长度扫描：把 WINDOW 从 60 往下压，看 fatigue/phone 还能不能分开。

为什么做这个：`WINDOW=60`（4 秒）当初是按"必须装下一个完整点头周期
（1~4 秒）"**推理**出来的，从没实测过。而窗口长度直接决定响应延迟——
滑动窗口要有一半换成新动作，结论才会动，所以起步和回落都滞后约半个窗口。
现场实测的感受就是"一动它不动、一停它不停"，4 秒窗口下滞后 2~3 秒。

如果更短的窗口也能把 fatigue 和 phone 分开，那延迟就能直接砍掉，
这是唯一能显著改善实时性的办法（换模型、调阈值都没用——滞后来自窗口）。

判据只有一个：**混淆对的概率**。P(phone | fatigue 段) 和 P(fatigue | phone 段)
必须仍然很低。只比准确率会被骗——准确率在 60 帧窗口下早就饱和了。

不动 config.py，不覆盖 dataset.npz，全部在内存里重切。
"""

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config as C
from build_dataset import discover_clips, load_pose_csv, normalize_sequence, split_clips
from model import PoseTransformer


def make_windows(seq, window, stride):
    T = len(seq)
    if T < window:
        return np.empty((0, window, seq.shape[1]), np.float32)
    starts = range(0, T - window + 1, stride)
    return np.stack([seq[s:s + window] for s in starts]).astype(np.float32)


def build_for_window(splits, window, stride):
    """按给定 window 重切。标准化统计量只从训练集拟合，和 build_dataset 一致。"""
    out = {}
    for split in ("train", "val", "test"):
        xs, ys = [], []
        for path, cls in splits[split]:
            feats = normalize_sequence(load_pose_csv(path))
            w = make_windows(feats, window, stride)
            if len(w):
                xs.append(w)
                ys.append(np.full(len(w), C.CLASSES.index(cls), np.int64))
        out[split] = (np.concatenate(xs), np.concatenate(ys)) if xs else (
            np.empty((0, window, C.FEAT_DIM), np.float32), np.empty(0, np.int64))
    mean = out["train"][0].mean(axis=(0, 1)).astype(np.float32)
    std = out["train"][0].std(axis=(0, 1)).astype(np.float32)
    std[std < 1e-6] = 1.0
    for split in out:
        x, y = out[split]
        out[split] = (((x - mean) / std).astype(np.float32), y)
    return out, mean, std


def train_one(data, window, epochs, seed):
    torch.manual_seed(seed)
    np.random.seed(seed)
    xtr, ytr = data["train"]
    xva, yva = data["val"]

    model = PoseTransformer(C.FEAT_DIM, window, len(C.CLASSES))
    opt = torch.optim.AdamW(model.parameters(), lr=C.LR,
                            weight_decay=C.WEIGHT_DECAY)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)
    crit = nn.CrossEntropyLoss(label_smoothing=C.LABEL_SMOOTH)

    Xtr = torch.from_numpy(xtr); Ytr = torch.from_numpy(ytr)
    Xva = torch.from_numpy(xva); Yva = torch.from_numpy(yva)

    # 按验证损失选最优 + 早停（不按准确率——准确率会饱和，这个坑踩过）
    best_loss, best_state, best_ep, bad = float("inf"), None, -1, 0
    for ep in range(1, epochs + 1):
        model.train()
        perm = torch.randperm(len(Xtr))
        for s in range(0, len(Xtr), C.BATCH_SIZE):
            idx = perm[s:s + C.BATCH_SIZE]
            opt.zero_grad(set_to_none=True)
            loss = crit(model(Xtr[idx]), Ytr[idx])
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
        sched.step()

        model.eval()
        with torch.no_grad():
            vl = crit(model(Xva), Yva).item()
        if vl < best_loss - 1e-4:
            best_loss, best_ep, bad = vl, ep, 0
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= 15:
                break
    model.load_state_dict(best_state)
    model.eval()
    return model, best_loss, best_ep


def evaluate(model, data, mean, std):
    """返回 (总准确率, 每类平均概率矩阵, 每类准确率)。

    每类准确率是必须看的：测试集每类只有 1 个片段，总数被某一类拖垮时
    完全看不出是哪一类——而 normal 和 glance 混、跟 fatigue 和 phone 混，
    严重程度差得远。
    """
    xte, yte = data["test"]
    n_cls = len(C.CLASSES)
    if len(xte) == 0:
        return 0.0, np.zeros((n_cls, n_cls)), np.zeros(n_cls)
    with torch.no_grad():
        p = torch.softmax(model(torch.from_numpy(xte)), dim=1).numpy()
    hit = p.argmax(1) == yte
    prof = np.zeros((n_cls, n_cls))
    per_cls = np.zeros(n_cls)
    for k in range(n_cls):
        m = yte == k
        if m.any():
            prof[k] = p[m].mean(0)
            per_cls[k] = float(hit[m].mean())
    return float(hit.mean()), prof, per_cls


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--windows", default="15,20,30,45,60")
    ap.add_argument("--stride", type=int, default=C.STRIDE_TRAIN)
    ap.add_argument("--epochs", type=int, default=C.EPOCHS)
    ap.add_argument("--seed", type=int, default=C.SEED)
    args = ap.parse_args()

    clips = discover_clips(C.DATA_POSE)
    splits, warns = split_clips(clips)
    for w in warns:
        print(f"  [warn] {w}")
    n = {s: len(splits[s]) for s in splits}
    print(f"片段划分：train {n['train']}  val {n['val']}  test {n['test']}"
          f"   （每个窗口都会重新切一遍）\n")

    # ★ 2026-09-25 二类之后没有"phone vs fatigue"这一对可看了（两个类已经并成
    # 一个），改看**两侧读法**的错分率 —— 这也正是产品口径本身：
    #   误报 = 真值 normal 却被判成任一非正常类（清醒被读成疲劳）
    #   漏报 = 真值非 normal 却被判成 normal（疲劳被读成清醒）
    # 用"整行/整列减去对角"算，对**任意类别数**都成立，类别再变一次也不用改这里。
    ni = C.CLASSES.index("normal")
    windows = [int(x) for x in args.windows.split(",")]

    brief = " ".join(c[:3] for c in C.CLASSES)
    print(f"{'窗口':>5}{'秒':>6}{'窗口数(训/测)':>15}{'滞后':>7}{'总准确率':>10}"
          f"{'各类准确率 ' + brief:>26}{'误报':>10}{'漏报':>10}")
    rows = []
    for w in windows:
        t0 = time.perf_counter()
        data, mean, std = build_for_window(splits, w, args.stride)
        # 注意 data[split] 是 (x, y) 二元组，len() 恒为 2——
        # 要的是窗口数，得取 [0] 再 len。
        n_tr, n_te = len(data["train"][0]), len(data["test"][0])
        if n_tr == 0 or len(data["val"][0]) == 0:
            print(f"{w:>5}  样本不足，跳过")
            continue
        model, vloss, bep = train_one(data, w, args.epochs, args.seed)
        acc, prof, per_cls = evaluate(model, data, mean, std)

        fa = float(prof[ni, :].sum() - prof[ni, ni])     # 误报率
        miss = float(prof[:, ni].sum() - prof[ni, ni])   # 漏报率

        # 滞后 ≈ 半个窗口（秒）+ 迟滞。这是理论值，用来横向比较不同窗口。
        lag = w / C.TARGET_FPS / 2 + 0.6
        rows.append((w, acc, fa, miss, lag))
        cls_str = " ".join(f"{v * 100:5.1f}" for v in per_cls)
        print(f"{w:>5}{w / C.TARGET_FPS:>6.1f}{n_tr:>8}/{n_te:<6}{lag:>6.1f}s"
              f"{acc * 100:>9.1f}%{cls_str:>26}"
              f"{fa:>10.3f}{miss:>10.3f}"
              f"   ({time.perf_counter() - t0:.0f}s, ep {bep})")

    print(f"\n{'=' * 78}")
    print("怎么看：滞后越小越好，但误报/漏报必须仍然很低。")
    print("只压窗口不管错分 = 把清醒的人误报成疲劳（或反过来），比慢更糟。")
    ok = [r for r in rows if r[2] < 0.10 and r[3] < 0.10 and r[1] > 0.95]
    if ok:
        best = min(ok, key=lambda r: r[0])
        print(f"\n=> 最短可用的窗口是 {best[0]} 帧（{best[0] / C.TARGET_FPS:.1f} 秒），"
              f"滞后约 {best[4]:.1f} 秒")
        if best[0] < C.WINDOW:
            print(f"   比现在的 {C.WINDOW} 帧（滞后约 "
                  f"{C.WINDOW / C.TARGET_FPS / 2 + 0.6:.1f} 秒）快 "
                  f"{(C.WINDOW - best[0]) / C.TARGET_FPS / 2:.1f} 秒")
    else:
        print("\n=> 没有一个窗口同时满足条件，需要放宽判据或补数据")


if __name__ == "__main__":
    main()
