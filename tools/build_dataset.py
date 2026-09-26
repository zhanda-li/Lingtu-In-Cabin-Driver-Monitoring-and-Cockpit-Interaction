"""骨骼 CSV -> 训练/验证/测试数据集（.npz）。

流程：
    1. 读入每个片段的 CSV（MediaPipe 原始输出）
    2. 归一化：原点取左右肩中点，尺度取 3D 肩宽（滑动中位数平滑）
       —— 消除人在画面里的位置和远近，只留姿态
    3. 滑窗切分：WINDOW 帧一个样本
    4. **按片段整体划分** train/val/test，绝不按窗口随机划分
    5. 标准化统计量只从训练集拟合，一并序列化进 npz 供推理复用

为什么第 4 步必须按片段划分：
    窗口步长 15 < 窗口长度 45，相邻窗口重叠 45 帧中的 30 帧（67%），几乎是
    同一条数据。若按窗口随机划分，训练集和测试集里会出现大量近乎重复的样本，
    测试准确率能刷到 95%+ 但现场一坐上去就崩。按片段划分，测试集里是
    模型完全没见过的人/坐姿/光线，才是真实水平。

用法：
    python tools/build_dataset.py
    python tools/build_dataset.py --pose-dir data/pose --out data/dataset/dataset.npz
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config as C


# ---------------------------------------------------------------- 读取
def load_pose_csv(path):
    """读一个片段的 CSV，返回 (T, 33, 4) 的 float32 数组。"""
    df = pd.read_csv(path)
    need = 2 + C.FEAT_DIM
    if df.shape[1] != need:
        raise ValueError(f"{path.name} 列数 {df.shape[1]}，期望 {need}")

    arr = df.iloc[:, 2:].to_numpy(dtype=np.float32)
    # 列序是 (landmark, axis) 展平的，直接 reshape 回去
    return arr.reshape(len(df), C.NUM_LANDMARKS, C.FEAT_PER_LANDMARK)


def check_fps(seq, timestamps_ms, path):
    """检查片段帧率是否和 TARGET_FPS 一致，不一致会导致时间尺度对不上。"""
    if len(timestamps_ms) < 3:
        return None
    dt = np.median(np.diff(timestamps_ms)) / 1000.0
    if dt <= 0:
        return None
    fps = 1.0 / dt
    if abs(fps - C.TARGET_FPS) > 1.0:
        print(f"  [warn] {path.name} 帧率 {fps:.1f} 与 TARGET_FPS "
              f"{C.TARGET_FPS} 不符，建议用 --overwrite 重新提取")
    return fps


# ---------------------------------------------------------------- 归一化
def normalize_sequence(seq):
    """(T, 33, 4) 原始 -> (T, 132) 归一化特征。

    原点 = 左右肩中点；尺度 = 3D 肩宽。
    单帧肩宽的检测抖动会被除法放大到所有坐标上，所以对肩宽序列做
    滑动中位数滤波；这既不丢掉"人变远了"这种慢变化，又能压掉单帧毛刺。
    """
    xyz = seq[:, :, :3].astype(np.float64)
    vis = seq[:, :, 3:4].astype(np.float32)

    origin = (xyz[:, C.L_SHOULDER] + xyz[:, C.R_SHOULDER]) * 0.5          # (T, 3)
    raw_scale = np.linalg.norm(xyz[:, C.L_SHOULDER] - xyz[:, C.R_SHOULDER],
                               axis=-1)                                    # (T,)
    raw_scale = np.maximum(raw_scale, 1e-4)

    scale = (pd.Series(raw_scale)
             .rolling(C.SCALE_SMOOTH_WIN, center=True, min_periods=1)
             .median()
             .to_numpy())
    scale = np.maximum(scale, 1e-4)[:, None]                               # (T, 1)

    norm = (xyz - origin[:, None, :]) / scale[:, None, :]
    out = np.concatenate([norm, vis], axis=-1)
    return out.reshape(len(seq), -1).astype(np.float32)


# ---------------------------------------------------------------- 切窗
def make_windows(seq, window=C.WINDOW, stride=C.STRIDE_TRAIN):
    """(T, 132) -> (N, window, 132)。不足一个窗口返回 0 个样本。"""
    T = len(seq)
    if T < window:
        return np.empty((0, window, seq.shape[1]), dtype=np.float32)
    starts = range(0, T - window + 1, stride)
    return np.stack([seq[s:s + window] for s in starts]).astype(np.float32)


# ---------------------------------------------------------------- 划分
# 目录 -> 类别。★ 2026-09-25 二类合并：`phone` 目录里的样本打 `fatigue` 标签
# （"看手机 = 持续低头 = 重度疲劳"，`src/live.py` 的 CLASS_LEVEL 里两者本来就同落 L3）。
# 目录**不删不搬**，只是标签变了 —— 想回三类就把这里 phone 改回 "phone"
# 并把 config.CLASSES 改回去。
DIR_CLASS = {"normal": "normal", "phone": "fatigue", "fatigue": "fatigue"}

# ⚠️ 这个**顺序**不是随便排的：它是"消费随机数"的顺序。
# 三类那一轮 `split_clips` 按 CLASSES = [normal, phone, fatigue] 逐类 shuffle 一次；
# 本表照抄同样的顺序、同样的**每目录**段数（27 / 26 / 26），于是 rng 状态逐次一致，
# 二类重训的 val/test 成员才会和三类那一轮**逐段相同**（受控对拍，不是换考卷）。
# 想改合并方式（比如 phone 归 normal）就得接受 val/test 换一批样本。
DIRS = ("normal", "phone", "fatigue")


def discover_clips(pose_dir):
    """{目录: [csv 路径, ...]}"""
    found = {}
    for name in DIRS:
        d = Path(pose_dir) / name
        found[name] = sorted(d.glob("*.csv")) if d.is_dir() else []
    return found


def split_clips(clips_by_dir, seed=C.SPLIT_SEED, ratio=C.SPLIT_RATIO):
    """按片段整体划分。返回 {split: [(path, cls), ...]} 和告警列表。

    同一片段的所有窗口只会进同一个 split —— 这是整个脚本最重要的一步。

    ★ 二类合并之后这里是**按目录划、再按类合并**，不是按类直接划：
    每个目录各 shuffle 一次、各自算 n_val/n_test，最后把同类的目录并到一起。
    换成"先把 phone+fatigue 合成 52 段再 shuffle"，随机数消耗的次数就变了，
    val/test 会换一批样本，重训结果和三类的合并读数（误报 0/27、漏报 0/52）
    就不再可比 —— 而"可比"正是这次重训的目的。
    """
    rng = np.random.RandomState(seed)
    out = {"train": [], "val": [], "test": []}
    warns = []
    per_dir = {}

    for name in DIRS:
        paths = list(clips_by_dir.get(name, []))
        n = len(paths)
        if n == 0:
            warns.append(f"目录 [{name}] 一个片段都没有，请先录视频并跑 extract_pose.py")
            per_dir[name] = {"train": [], "val": [], "test": []}
            continue
        if n < C.MIN_CLIPS_PER_CLASS:
            warns.append(f"目录 [{name}] 只有 {n} 段，建议至少 {C.MIN_CLIPS_PER_CLASS} 段，"
                         f"否则验证/测试集太薄，指标不可信")

        if n < 3:
            warns.append(f"目录 [{name}] 只有 {n} 段，全部划入训练集，"
                         f"该目录没有验证/测试样本")
            per_dir[name] = {"train": paths, "val": [], "test": []}
            continue

        rng.shuffle(paths)
        n_val = max(1, int(round(n * ratio[1])))
        n_test = max(1, int(round(n * ratio[2])))
        n_train = n - n_val - n_test

        per_dir[name] = {
            "train": paths[:n_train],
            "val": paths[n_train:n_train + n_val],
            "test": paths[n_train + n_val:n_train + n_val + n_test],
        }

    for split in ("train", "val", "test"):
        for name in DIRS:
            cls = DIR_CLASS[name]
            out[split] += [(p, cls) for p in per_dir[name][split]]

    # 合并之后的**类**总段数也要够，否则划分仍然太薄（目录数达标不代表类达标）
    for cls in C.CLASSES:
        n_cls = sum(1 for split in ("train", "val", "test")
                    for _, c in out[split] if c == cls)
        if 0 < n_cls < C.MIN_CLIPS_PER_CLASS:
            warns.append(f"类别 [{cls}] 合并后只有 {n_cls} 段，"
                         f"建议至少 {C.MIN_CLIPS_PER_CLASS} 段")

    return out, warns


# ---------------------------------------------------------------- 主流程
def build(pose_dir=C.DATA_POSE, out_path=None, stride=C.STRIDE_TRAIN,
          seed=C.SPLIT_SEED, verbose=True):
    """构建数据集并保存 npz，返回 (stats dict, 告警列表)。"""
    t0 = time.time()
    out_path = Path(out_path) if out_path else (C.DATA_DATASET / "dataset.npz")

    clips_by_dir = discover_clips(pose_dir)
    if verbose:
        for name in DIRS:
            print(f"  目录 {name:<8} {len(clips_by_dir[name]):>3} 个片段 -> 类别 "
                  f"{DIR_CLASS[name]}")
        for cls in C.CLASSES:
            tot = sum(len(v) for n2, v in clips_by_dir.items() if DIR_CLASS[n2] == cls)
            print(f"  类别 {cls:<8} {tot:>3} 个片段"
                  f"（合并自 {[n2 for n2 in DIRS if DIR_CLASS[n2] == cls]}）")

    splits, warns = split_clips(clips_by_dir, seed=seed)
    for w in warns:
        print(f"  [warn] {w}")
    if not splits["train"]:
        raise SystemExit("训练集为空，无法构建数据集。先录视频并跑 extract_pose.py。")

    # 逐片段 -> 归一化 -> 切窗
    data = {}
    clip_names = {}
    for split in ("train", "val", "test"):
        xs, ys, names = [], [], []
        for path, cls in splits[split]:
            seq = load_pose_csv(path)
            timestamps = pd.read_csv(path, usecols=["timestamp_ms"])["timestamp_ms"]
            check_fps(seq, timestamps.to_numpy(), path)

            feats = normalize_sequence(seq)
            win = make_windows(feats, C.WINDOW, stride)
            if len(win) == 0:
                if verbose:
                    print(f"  [warn] {path.name} 只有 {len(seq)} 帧，"
                          f"不足 {C.WINDOW} 帧，切不出样本")
                continue
            xs.append(win)
            ys.append(np.full(len(win), C.CLASSES.index(cls), dtype=np.int64))
            names += [path.stem] * len(win)

        if xs:
            data[split] = (np.concatenate(xs), np.concatenate(ys),
                           np.array(names, dtype=str))
        else:
            data[split] = (np.empty((0, C.WINDOW, C.FEAT_DIM), np.float32),
                           np.empty((0,), np.int64), np.array([], dtype=str))

    # 标准化统计量：只从训练集拟合
    xtr = data["train"][0]
    feat_mean = xtr.mean(axis=(0, 1)).astype(np.float32)
    feat_std = xtr.std(axis=(0, 1)).astype(np.float32)
    feat_std[feat_std < 1e-6] = 1.0

    def norm_split(split):
        x, y, n = data[split]
        if len(x) == 0:
            return x, y, n
        return ((x - feat_mean) / feat_std).astype(np.float32), y, n

    save = {}
    stats = {
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "window": C.WINDOW,
        "stride": stride,
        "feat_dim": C.FEAT_DIM,
        "target_fps": C.TARGET_FPS,
        "split_ratio_target": list(C.SPLIT_RATIO),
        "split_seed": seed,
        "classes": C.CLASSES,
        "clips": {},           # 按**目录**键（下游按路径段查，见下面那段注释）
        "clips_by_class": {},  # 按**类别**键（合并后的视图，给人看的）
        "windows": {},
        "class_windows": {},
    }

    for split in ("train", "val", "test"):
        x, y, n = norm_split(split)
        save[f"X_{split}"] = x
        save[f"y_{split}"] = y
        save[f"clip_{split}"] = n
        stats["windows"][split] = int(len(x))
        stats["class_windows"][split] = {
            cls: int((y == i).sum()) for i, cls in enumerate(C.CLASSES)
        }
        # ⚠️ `clips` **按目录**键，不是按类别键。
        # 三个读者（`tools/replay_clip.py:144`、`tools/calibration.py:50`、
        # `tools/lag_breakdown.py:133`）都把键当成**路径段**拼
        # `f"{键}/{片段名}"` 去查"这段落在哪个划分"。二类合并后 phone 目录的样本
        # 标签变成了 fatigue，若这里按类别键，那 26 段就会在"划分"那一列静默变成
        # `--`（查不到 ≠ 报错）。所以键保持目录名，另存一份按类的视图给汇总用。
        stats["clips"][split] = {}
        for name in DIRS:
            stats["clips"][split][name] = sorted(
                p.stem for p, c in splits[split] if DIR_CLASS[name] == c
            )
        stats["clips_by_class"][split] = {}
        for cls in C.CLASSES:
            stats["clips_by_class"][split][cls] = sorted(
                p.stem for p, c in splits[split] if c == cls
            )

    save["feat_mean"] = feat_mean
    save["feat_std"] = feat_std
    save["classes"] = np.array(C.CLASSES, dtype=str)
    save["window"] = np.int64(C.WINDOW)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out_path, **save)

    stats["out_path"] = str(out_path)
    stats["elapsed_s"] = round(time.time() - t0, 2)

    manifest = out_path.with_name(out_path.stem + "_manifest.json")
    manifest.write_text(json.dumps(stats, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    if verbose:
        print(f"\n  切分结果：")
        for split in ("train", "val", "test"):
            per = " ".join(f"{cls}={stats['class_windows'][split][cls]}"
                           for cls in C.CLASSES)
            print(f"    {split:<5} {stats['windows'][split]:>6} 窗口   {per}")
        print(f"    {Path(out_path).name}  ({Path(out_path).stat().st_size/1e6:.1f} MB)")
        print(f"    清单 {manifest.name}")
        print(f"  耗时 {stats['elapsed_s']} s")

    return stats, warns


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pose-dir", default=str(C.DATA_POSE))
    ap.add_argument("--out", default=str(C.DATA_DATASET / "dataset.npz"))
    ap.add_argument("--stride", type=int, default=C.STRIDE_TRAIN)
    ap.add_argument("--seed", type=int, default=C.SPLIT_SEED)
    args = ap.parse_args()

    print("构建数据集（按片段划分）")
    build(Path(args.pose_dir), Path(args.out), args.stride, args.seed)


if __name__ == "__main__":
    main()
