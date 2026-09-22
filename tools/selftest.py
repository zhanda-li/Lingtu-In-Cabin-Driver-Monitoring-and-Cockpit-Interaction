"""端到端自检：合成骨骼数据 -> 建数据集 -> 短训 -> 查指标。

在真实视频录好之前，用它验证整条代码链路（归一化、切窗、按片段划分、
模型前向反向、评估出图）是通的。合成数据只是几个可区分的运动模式，
**它跑出来的准确率不代表真实性能**，只用来证明代码没写错。

用法：
    python tools/selftest.py
    python tools/selftest.py --clips 8 --epochs 8
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import config as C
import build_dataset as bd

# 一个粗略的直立人体，图像归一化坐标（x 向右，y 向下，z 为深度）
BASE = np.array([
    [0.500, 0.205, 0.00], [0.492, 0.198, 0.00], [0.488, 0.196, 0.00],
    [0.483, 0.195, 0.00], [0.508, 0.198, 0.00], [0.512, 0.196, 0.00],
    [0.517, 0.195, 0.00], [0.472, 0.200, 0.00], [0.528, 0.200, 0.00],
    [0.492, 0.222, 0.00], [0.508, 0.222, 0.00],
    [0.420, 0.330, 0.00], [0.580, 0.330, 0.00],
    [0.385, 0.455, 0.00], [0.615, 0.455, 0.00],
    [0.355, 0.565, 0.00], [0.645, 0.565, 0.00],
    [0.345, 0.585, 0.00], [0.655, 0.585, 0.00],
    [0.350, 0.590, 0.00], [0.650, 0.590, 0.00],
    [0.362, 0.578, 0.00], [0.638, 0.578, 0.00],
    [0.450, 0.620, 0.00], [0.550, 0.620, 0.00],
    [0.445, 0.800, 0.00], [0.555, 0.800, 0.00],
    [0.445, 0.960, 0.00], [0.555, 0.960, 0.00],
    [0.435, 0.975, 0.00], [0.565, 0.975, 0.00],
    [0.465, 0.985, 0.00], [0.535, 0.985, 0.00],
], dtype=np.float64)

HEAD = list(range(11))                       # 0..10 是头面部
NECK = np.array([0.500, 0.330, 0.00])        # 旋转支点取肩中点


def rot_pitch(pts, deg):
    """俯仰：绕颈点转到点 (y,z) 平面。正值 = 低头。"""
    t = np.deg2rad(deg)
    c, s = np.cos(t), np.sin(t)
    d = pts - NECK
    out = pts.copy()
    out[:, 1] = NECK[1] + d[:, 1] * c - d[:, 2] * s
    out[:, 2] = NECK[2] + d[:, 1] * s + d[:, 2] * c
    return out


def rot_yaw(pts, deg):
    """偏航：绕颈点转到点 (x,z) 平面。正值 = 扭头。"""
    t = np.deg2rad(deg)
    c, s = np.cos(t), np.sin(t)
    d = pts - NECK
    out = pts.copy()
    out[:, 0] = NECK[0] + d[:, 0] * c + d[:, 2] * s
    out[:, 2] = NECK[2] - d[:, 0] * s + d[:, 2] * c
    return out


def class_signal(cls, T, fps, rng):
    """给每个类别造一条 pitch/yaw 时间序列（度）。"""
    t = np.arange(T) / fps
    if cls == "normal":
        pitch = rng.normal(0, 3.0, T)
        yaw = 5.0 * np.sin(2 * np.pi * t / 6.0) + rng.normal(0, 2.0, T)
    elif cls == "glance":
        yaw = np.zeros(T)
        a, b = int(T * 0.2), int(T * 0.8)
        yaw[a:b] = 42.0                        # 持续扭头，静态保持
        yaw += rng.normal(0, 2.0, T)
        yaw = np.convolve(yaw, np.ones(5) / 5, mode="same")
        pitch = rng.normal(0, 3.0, T)
    elif cls == "phone":
        pitch = np.zeros(T)
        a, b = int(T * 0.15), int(T * 0.95)
        pitch[a:b] = 38.0                      # 持续低头，静态保持
        pitch += rng.normal(0, 2.0, T)
        pitch = np.convolve(pitch, np.ones(5) / 5, mode="same")
        yaw = rng.normal(0, 2.0, T)
    elif cls == "fatigue":
        # 周期性点头：这是和"持续低头"区分的唯一线索，周期 2.5 s
        pitch = 22.0 * (1 - np.cos(2 * np.pi * t / 2.5)) + rng.normal(0, 2.0, T)
        yaw = rng.normal(0, 3.0, T)
    else:
        raise ValueError(cls)
    return pitch, yaw


def synth_clip(cls, T, fps, rng):
    """造一个片段的 (T, 33, 4) 骨骼序列。"""
    pitch, yaw = class_signal(cls, T, fps, rng)

    # 每段随机坐姿偏移 + 随机远近，逼归一化去把这两样消掉
    off = rng.uniform(-0.08, 0.08, size=2)
    scale = rng.uniform(0.80, 1.25)

    seq = np.zeros((T, C.NUM_LANDMARKS, C.FEAT_PER_LANDMARK), dtype=np.float32)
    for i in range(T):
        pts = BASE.copy()
        h = rot_yaw(pts[HEAD], yaw[i])
        pts[HEAD] = rot_pitch(h, pitch[i])
        pts[:, :2] = (pts[:, :2] - 0.5) * scale + 0.5 + off
        pts[:, 2] *= scale
        pts += rng.normal(0, 0.004, pts.shape)
        seq[i, :, :3] = pts
        seq[i, :, 3] = rng.uniform(0.75, 0.99)
    return seq


def write_csv(seq, path, fps):
    cols = ["frame_idx", "timestamp_ms"] + [
        f"{ax}{i}" for i in range(C.NUM_LANDMARKS) for ax in ("x", "y", "z", "v")]
    rows = np.concatenate(
        [np.stack([np.arange(len(seq)), np.arange(len(seq)) / fps * 1000.0], axis=1),
         seq.reshape(len(seq), -1).astype(np.float64)], axis=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=cols).to_csv(path, index=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", type=int, default=8, help="每类合成几个片段")
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--epochs", type=int, default=10)
    ap.add_argument("--work", default=str(ROOT / "_selftest"))
    args = ap.parse_args()

    work = Path(args.work)
    if work.exists():
        shutil.rmtree(work)
    pose_dir = work / "pose"
    rng = np.random.RandomState(0)
    T = int(args.seconds * C.TARGET_FPS)

    print(f"[1/3] 合成骨骼数据：{len(C.CLASSES)} 类 x {args.clips} 段 x "
          f"{T} 帧（{args.seconds:.0f} s @ {C.TARGET_FPS} fps）")
    for cls in C.CLASSES:
        for k in range(args.clips):
            write_csv(synth_clip(cls, T, C.TARGET_FPS, rng),
                      pose_dir / cls / f"{cls}_{k:02d}.csv", C.TARGET_FPS)
    print(f"      -> {pose_dir}")

    print("[2/3] 构建数据集（按片段划分）")
    ds = work / "dataset.npz"
    stats, warns = bd.build(pose_dir, ds)
    for w in warns:
        print(f"      [warn] {w}")

    print(f"\n[3/3] 短训 {args.epochs} epoch 验证链路")
    run_dir = work / "run"
    cmd = [sys.executable, str(ROOT / "src" / "train.py"),
           "--data", str(ds), "--out", str(run_dir),
           "--epochs", str(args.epochs), "--quiet"]
    # 子进程也强制 UTF-8，否则它按 GBK 写、这边按 UTF-8 读，中文全变替换字符
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env)
    print(r.stdout)
    if r.returncode != 0:
        print(r.stderr)
        raise SystemExit(f"训练脚本退出码 {r.returncode}")

    m = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))

    print("=" * 62)
    ok = True

    if len(m["confusion_matrix"]) and not m["val_is_test_fallback"]:
        print("  [OK]   验证集非空，按片段划分生效")
    else:
        print("  [FAIL] 划分异常：验证集为空或退化成测试集")
        ok = False

    if m["test_acc"] >= 0.6:
        print(f"  [OK]   合成数据测试准确率 {m['test_acc']*100:.1f}% "
              f"（合成数据只验证代码，不代表真实性能）")
    else:
        print(f"  [FAIL] 合成数据测试准确率仅 {m['test_acc']*100:.1f}%，链路有问题")
        ok = False

    produced = ["best.pt", "metrics.json", "confusion_matrix.png",
                "confusion_matrix_norm.png", "curves.png", "history.json"]
    missing = [f for f in produced if not (run_dir / f).exists()]
    if missing:
        print(f"  [FAIL] 缺少产物：{missing}")
        ok = False
    else:
        print(f"  [OK]   产物齐全：{', '.join(produced)}")

    print("=" * 62)
    print("自检通过。" if ok else "自检失败，见上方 [FAIL]。")
    print(f"产物在 {run_dir}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
