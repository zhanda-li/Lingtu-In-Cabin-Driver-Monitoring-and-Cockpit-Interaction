"""把"实时性不过关"拆成可以分别下手的几段，量出每一段各占多少秒。

用户实测的感受是"延迟太长了"。但"延迟"不是一个数，它是串联的几段：

    ① 窗口填充  前 WINDOW-1 帧根本没有输出
    ② 模型响应  窗口内容换了以后，概率要爬过 ENTER_TH（≈ 半个窗口）
    ③ EMA 平滑  α=0.30 在 5 Hz 下时间常数约 1/(5*0.30) ≈ 0.67 s
    ④ 时间驻留  连着 ENTER_SEC 秒满足条件才真的升上去

⚠️ **拿单个录制片段量不出真正的延迟。** 录制片段从头到尾就一个动作，
第一帧输出时概率就已经在顶上了（实测"原始过阈 0.0s"），于是量出来的只是
③+④，把最贵的①②全漏掉。所以这里默认走**拼接**模式：拿一段 normal 接一段
目标动作，造一个人为的阶跃，量的才是现场那一下"我一低头，灯多久亮"。

只跑留出的测试片段（模型没见过），因果落位，和 live.py 完全一致——
连阈值、α、驻留秒数都直接从 live.py 里 import，不抄一份常量（抄一份就会飘）。

顺手报"灵敏度"：整段里该类概率的最大值。用户现场日志显示活人身上 max 只有
0.64，而阈值就是 0.60——概率是"擦着阈值过"而不是"冲过去"。
擦着过的时候延迟会被成倍放大：概率在阈值附近抖，驻留计时反复清零。
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config as C
from build_dataset import load_pose_csv, normalize_sequence
from model import PoseTransformer
from replay_clip import load_model

CLASS_LEVEL = {"normal": 0, "glance": 1, "phone": 2, "fatigue": 3}


def probs_of_feats(model, feats, stat):
    """(T,132) 归一化好的特征 -> (T,4) 概率，前 WINDOW-1 帧 NaN（因果）。"""
    mean, std = stat
    x = ((feats - mean) / std).astype(np.float32)
    T = len(x)
    out = np.full((T, len(C.CLASSES)), np.nan, np.float32)
    n_win = T - C.WINDOW + 1
    if n_win <= 0:
        return out
    with torch.no_grad():
        for i in range(n_win):
            w = torch.from_numpy(x[i:i + C.WINDOW][None])
            out[i + C.WINDOW - 1] = torch.softmax(model(w), 1).numpy()[0]
    return out


def simulate(probs, cfg, reset_at=0.0, fps=C.TARGET_FPS):
    """照抄 live.py 的 WarningState，全程用**媒体时间**（i/fps）。

    `reset_at` 是阶跃发生的时刻：只有它**之后**的首次过阈才算"响应延迟"。
    阶跃**之前**的过阈单独返回（pre_*），那是误报——不分开的话，
    正常段就已经过阈的话，"首次过阈时刻"会被记成正常段的时刻，
    量出来的东西根本不是响应速度。这个坑我踩过一次。

    返回 (阶跃后首次达标 dict, 阶跃前首次过阈 dict, 级别轨迹)。
    """
    enter_th, exit_th, alpha, decide_hz, enter_sec, exit_sec = cfg
    decide_dt = 1.0 / decide_hz
    n_cls = len(C.CLASSES)
    # 只有 level>=1 的类才可能触发升级。**不能拿 p.max() 判过阈**——
    # normal 的概率本来就在 0.9 上下，用 p.max() 等于永远"已过阈"。
    nz = [k for k, c in enumerate(C.CLASSES) if CLASS_LEVEL[c] >= 1]

    ema = np.full(n_cls, 1.0 / n_cls)
    level, pend, pend_t = 0, -1, 0.0
    post = {"raw": None, "ema": None, "level": None}
    pre = {"raw": None, "ema": None, "level": None}
    trace = np.zeros(len(probs), np.int8)
    next_decide = 0.0

    def mark(d, key, t):
        if d[key] is None:
            d[key] = t

    for i in range(len(probs)):
        t = i / fps
        p = probs[i]
        trace[i] = level
        if np.isnan(p[0]):
            continue
        if max(p[k] for k in nz) > enter_th:
            mark(post if t >= reset_at else pre, "raw", t)
        if t < next_decide:
            continue
        next_decide = t + decide_dt
        ema = alpha * p + (1.0 - alpha) * ema
        if max(ema[k] for k in nz) > enter_th:
            mark(post if t >= reset_at else pre, "ema", t)

        tgt = 0
        for k, cls in enumerate(C.CLASSES):
            lv = CLASS_LEVEL[cls]
            if lv == 0:
                continue
            th = exit_th if lv <= level else enter_th
            if ema[k] > th:
                tgt = max(tgt, lv)
        if tgt == level:
            pend = -1
        elif tgt != pend:
            pend, pend_t = tgt, t
        else:
            if t - pend_t >= (enter_sec if tgt > level else exit_sec):
                prev, level = level, tgt
                pend = -1
                if level > prev:
                    mark(post if t >= reset_at else pre, "level", t)
    return post, pre, trace


def pick(clips_dir, cls, split=None):
    """挑一个片段。

    `split` 给 "test" 时**从清单里查**，而不是猜"排序最后一个"——
    猜错过一次：split_clips 的 test 未必是文件名的最后一个，
    结果我拿 train/val 片段量了半天延迟。
    """
    import json
    if split:
        man = C.DATA_DATASET / "dataset_manifest.json"
        if man.exists():
            m = json.loads(man.read_text(encoding="utf-8"))["clips"]
            names = m.get(split, {}).get(cls, [])
            if names:
                return clips_dir / cls / f"{names[0]}.csv"
    hits = sorted((clips_dir / cls).glob("*.csv"))
    return hits[-1] if hits else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None)
    ap.add_argument("--from", dest="src_cls", default="normal",
                    help="阶跃前是什么动作，默认 normal")
    ap.add_argument("--to", dest="dst_cls", default="all",
                    help="阶跃到哪个动作，默认每类都试")
    ap.add_argument("--seconds", type=float, default=8.0,
                    help="阶跃前后各放多少秒，默认 8")
    # 覆盖迟滞参数，用来做 A/B —— 不用改 live.py 就能试
    ap.add_argument("--enter-th", type=float, default=None)
    ap.add_argument("--exit-th", type=float, default=None)
    ap.add_argument("--enter-sec", type=float, default=None)
    ap.add_argument("--exit-sec", type=float, default=None)
    ap.add_argument("--alpha", type=float, default=None)
    ap.add_argument("--decide-hz", type=float, default=None)
    args = ap.parse_args()

    import live
    # 顺序必须和 simulate() 的解包顺序一致：enter_th, exit_th, alpha,
    # decide_hz, enter_sec, exit_sec。写成字典推导会按字典顺序排，
    # 那和这里不一样——alpha/decide_hz 会跟 enter_sec/exit_sec 换位，
    # 结果"调快"反而变慢，而且看不出错在哪。踩过一次。
    def or_default(v, name):
        return v if v is not None else getattr(live, name)
    cfg = (or_default(args.enter_th, "ENTER_TH"),
           or_default(args.exit_th, "EXIT_TH"),
           or_default(args.alpha, "EMA_ALPHA"),
           or_default(args.decide_hz, "DECIDE_HZ"),
           or_default(args.enter_sec, "ENTER_SEC"),
           or_default(args.exit_sec, "EXIT_SEC"))

    ckpt = Path(args.model) if args.model else sorted(
        p for p in Path(C.ROOT, "runs").iterdir() if p.is_dir())[-1] / "best.pt"
    model, stat = load_model(ckpt)

    n = int(args.seconds * C.TARGET_FPS)
    src = pick(C.DATA_POSE, args.src_cls, split="test")
    if src is None:
        print(f"没有 {args.src_cls} 片段"); return
    base = normalize_sequence(load_pose_csv(src))[:n]

    print(f"模型 {ckpt.name}   窗口 {C.WINDOW} 帧 = "
          f"{C.WINDOW / C.TARGET_FPS:.1f}s @ {C.TARGET_FPS}fps")
    print(f"状态机 进{cfg[0]} 退{cfg[1]} α={cfg[2]} {cfg[3]:.0f}Hz "
          f"升{cfg[4]}s 降{cfg[5]}s")
    print(f"阶跃：{src.stem}[test] {args.seconds:.0f}s -> 目标动作 {args.seconds:.0f}s"
          f"（拼接造出的阶跃，发生在媒体时间 t={args.seconds:.0f}s）")
    print(f"下表时刻都是**媒体时间**；'阶跃前' 一列是误报检查\n")

    print(f"{'目标动作':<9}{'阶跃前过阈':>10}{'  |':>3}{'原始过阈':>9}{'EMA过阈':>9}"
          f"{'升到L1':>8}{'  |':>3}{'回到L0':>8}{'  |':>3}{'峰值':>8}")
    print("-" * 82)
    for cls in (C.CLASSES[1:] if args.dst_cls == "all" else [args.dst_cls]):
        dst = pick(C.DATA_POSE, cls, split="test")
        if dst is None:
            continue
        feats = np.concatenate([base, normalize_sequence(load_pose_csv(dst))[:n]])
        probs = probs_of_feats(model, feats, stat)
        post, pre, trace = simulate(probs, cfg, reset_at=args.seconds)

        # 回落：目标动作在前、normal 在后，量降级要多久
        feats_r = np.concatenate(
            [normalize_sequence(load_pose_csv(dst))[:n], base])
        _, _, trace_r = simulate(probs_of_feats(model, feats_r, stat), cfg,
                                 reset_at=args.seconds)
        back = next((i / C.TARGET_FPS for i in range(len(trace_r))
                     if i / C.TARGET_FPS > args.seconds and trace_r[i] < 1), None)

        step = C.CLASSES.index(cls)
        seg = probs[n:, step]
        peak = float(np.nanmax(seg)) if not np.all(np.isnan(seg)) else float("nan")

        def f(x):
            return f"{x:>7.1f}s" if x is not None else "     --"
        # 阶跃后的响应延迟：相对阶跃时刻才直观
        def rel(x):
            return f"{x - args.seconds:>6.1f}s" if x is not None else "    --"
        print(f"{cls:<9}{f(pre['raw'])}{'  |':>3}{rel(post['raw'])}{rel(post['ema'])}"
              f"{rel(post['level'])}{'  |':>3}{rel(back)}{'  |':>3}{peak:>8.3f}")

    print("-" * 82)
    print(f"（表头'原始过阈/EMA过阈/升到L1/回到L0'都是**相对阶跃时刻**的秒数）")
    print(f"（冷启动另算：前 {C.WINDOW - 1} 帧没有输出，"
          f"即 {(C.WINDOW - 1) / C.TARGET_FPS:.1f}s，持续运行时不算这笔）")
    print("\n怎么用这几列：")
    print("  原始过阈  模型自身的响应速度，只跟窗口长度、训练质量有关")
    print("  EMA过阈   再减去上一列 = α 的滞后，调大 α 直接砍掉")
    print("  升到L1    再减去上一列 = 时间驻留，调小 ENTER_SEC 直接砍掉")
    print("  阶跃前过阈 非空 = **在正常动作上就已经越过阈值**，是误报")
    print("\n⚠️ 峰值若只比阈值高一点点（比如 0.65 对 0.60），说明是**擦着过**：")
    print("   概率在阈值附近来回抖，驻留计时被反复清零，实测会比理论值长几倍。")


if __name__ == "__main__":
    main()
