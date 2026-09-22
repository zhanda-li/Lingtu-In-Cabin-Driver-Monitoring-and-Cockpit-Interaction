"""按窗口长度实测**阶跃响应延迟**，用来决定窗口该取多长。

和 `sweep_window.py` 的区别：那个只报"半窗口"这个理论值，而这个把模型真跑一遍，
量出"动作变了以后，灯到底多久才升上去"。理论值靠不住——实测下来模型自身的
概率爬升（0.9~3.7 s）比半窗口（2.0 s）要么快要么慢，跟类别关系很大。

每个窗口都重新训练一个模型（窗口变了权重就不能复用），然后：

  1. **阶跃响应**：normal 段接一段目标动作，量 L0 -> L1 用了多久。
     这一列才是用户说的"延迟"。
  2. **误报检查**：正常的 `normal` 片段单独跑一遍，看有没有自己升到 L1。
     短窗口确实会让 normal 被误判（实测 30 帧时 normal 那一类准确率掉到 0），
     而**误报比慢更致命**——现场坐着不动灯乱亮，比反应慢半拍难看多了。

判据不是"哪个最快"，是**在零误报的前提下哪个最快**。
"""

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config as C
from build_dataset import (discover_clips, load_pose_csv, normalize_sequence,
                           split_clips)
from lag_breakdown import pick, simulate
from sweep_window import build_for_window, train_one


def probs_at(model, feats, window, mean, std):
    """按给定窗口滑一遍，因果落位到窗口最后一帧。"""
    x = ((feats - mean) / std).astype(np.float32)
    T = len(x)
    out = np.full((T, len(C.CLASSES)), np.nan, np.float32)
    n_win = T - window + 1
    if n_win <= 0:
        return out
    with torch.no_grad():
        for i in range(n_win):
            w = torch.from_numpy(x[i:i + window][None])
            out[i + window - 1] = torch.softmax(model(w), 1).numpy()[0]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--windows", default="15,30,45,60")
    ap.add_argument("--epochs", type=int, default=C.EPOCHS)
    ap.add_argument("--seed", type=int, default=C.SEED)
    ap.add_argument("--seconds", type=float, default=8.0)
    # 迟滞旋钮，用来找"零误报前提下最快"的那组
    ap.add_argument("--enter-th", type=float, default=None)
    ap.add_argument("--exit-th", type=float, default=None)
    ap.add_argument("--enter-sec", type=float, default=None)
    ap.add_argument("--exit-sec", type=float, default=None)
    ap.add_argument("--alpha", type=float, default=None)
    ap.add_argument("--decide-hz", type=float, default=None)
    args = ap.parse_args()

    import live
    # 顺序必须和 lag_breakdown.simulate() 的解包顺序一致
    def or_default(v, name):
        return v if v is not None else getattr(live, name)
    cfg = (or_default(args.enter_th, "ENTER_TH"),
           or_default(args.exit_th, "EXIT_TH"),
           or_default(args.alpha, "EMA_ALPHA"),
           or_default(args.decide_hz, "DECIDE_HZ"),
           or_default(args.enter_sec, "ENTER_SEC"),
           or_default(args.exit_sec, "EXIT_SEC"))

    clips = discover_clips(C.DATA_POSE)
    splits, warns = split_clips(clips)
    for w in warns:
        print(f"  [warn] {w}")

    # 测试片段：模型没见过，量的延迟才有意义
    src = pick(C.DATA_POSE, "normal", split="test")
    targets = [pick(C.DATA_POSE, c, split="test") for c in C.CLASSES[1:]]
    n = int(args.seconds * C.TARGET_FPS)
    base = normalize_sequence(load_pose_csv(src))[:n]
    dst_feats = {p.parent.name: normalize_sequence(load_pose_csv(p))[:n]
                 for p in targets if p}
    normal_feats = normalize_sequence(load_pose_csv(src))

    print(f"阶跃源 {src.stem}[test]，目标 " + "  ".join(
        p.parent.name + ":" + p.stem for p in targets if p))
    print(f"状态机 进{cfg[0]} 退{cfg[1]} α={cfg[2]} {cfg[3]:.0f}Hz "
          f"升{cfg[4]}s 降{cfg[5]}s   阶跃前后各 {args.seconds:.0f}s\n")

    hdr = "  ".join(f"{c[:3]:>6}" for c in C.CLASSES[1:])
    print(f"{'窗口':>5}{'秒':>6}   升到L1延迟 {hdr}    {'平均':>6}"
          f"  |  normal 误报(升到)  最高非真值概率")
    print("-" * 86)

    rows = []
    for w in [int(x) for x in args.windows.split(",")]:
        t0 = time.perf_counter()
        data, mean, std = build_for_window(splits, w, C.STRIDE_TRAIN)
        if len(data["train"][0]) == 0:
            continue
        model, vloss, bep = train_one(data, w, args.epochs, args.seed)

        lags = []
        for cls, feats in dst_feats.items():
            probs = probs_at(model, np.concatenate([base, feats]), w, mean, std)
            post, pre, _ = simulate(probs, cfg, reset_at=args.seconds)
            lags.append(post["level"] - args.seconds
                        if post["level"] is not None else None)

        # 误报：正常片段自己跑，看升到几级、非真值概率最高多少
        pn = probs_at(model, normal_feats, w, mean, std)
        _, _, trace = simulate(pn, cfg)
        fp_level = int(trace.max())
        nz = [k for k, c in enumerate(C.CLASSES) if c != "normal"]
        fp_prob = float(np.nanmax(pn[:, nz]))

        def f(x):
            return f"{x:>5.1f}s" if x is not None else "    --"
        ok = [x for x in lags if x is not None]
        avg = np.mean(ok) if ok else float("nan")
        rows.append((w, avg, fp_level, fp_prob))
        flag = "  <<< 误报" if fp_level > 0 else ""
        print(f"{w:>5}{w / C.TARGET_FPS:>6.1f}   " + "  ".join(f(x) for x in lags)
              + f"    {avg:>5.1f}s  |     L{fp_level}{flag:<12}{fp_prob:>8.3f}"
              + f"   ({time.perf_counter() - t0:.0f}s)")

    print("-" * 86)
    good = [r for r in rows if r[2] == 0]
    if good:
        best = min(good, key=lambda r: r[1])
        print(f"=> 零误报里最快的是 {best[0]} 帧（{best[0] / C.TARGET_FPS:.1f} 秒），"
              f"平均升到 L1 用 {best[1]:.1f} 秒")
        cur = [r for r in rows if r[0] == C.WINDOW]
        if cur:
            print(f"   现在是 {C.WINDOW} 帧，平均 {cur[0][1]:.1f} 秒 —— "
                  f"能快 {cur[0][1] - best[1]:.1f} 秒")
    else:
        print("=> 每个窗口都有误报，说明 normal 那一类数据不够，先补录再压窗口")
    print("\n'最高非真值概率'要盯住：它离 ENTER_TH "
          f"({cfg[0]}) 越近，现场越容易误报。")


if __name__ == "__main__":
    main()
