"""某个目录下的片段会被顶成 L3（重度）多少 —— **负对照**专用探针。

    python tools/probe_l3.py --model runs/fatigue3/best.pt --dirs normal glance
    python tools/probe_l3.py --model runs/fatigue2/best.pt --dirs normal glance phone fatigue

为什么需要它（2026-09-25，二类合并时写的）：
  `replay_clip.py` 只遍历 `build_dataset.DIR_CLASS` 里映射到类别的目录，
  **跑不了 `glance`**（那是退掉的类别，故意的，不然 `C.CLASSES.index` 会抛）。
  而"非正常、但不是疲劳"的动作（瞟后视镜、挠头、侧头看导航）恰恰是最容易把
  重度顶起来的一类输入 —— 二类合并之后 `ema[fatigue] > ENTER_TH` 与
  "闸门关闭"变成了同一件事，所以这条路径**必须单独量**，不能靠准确率蒙混。

量的是**梯子最终有没有到 L3**，不是"某一帧概率多高"：
  逐帧取"非 normal 那一侧的最大概率"作证据强度（三类下 = max(P(phone), P(fatigue))，
  二类下 = P(fatigue)），再原样走一遍 `src/live.py` 的 EMA + 两级迟滞
  （同样的 alpha / enter_th / exit_th / enter_sec / exit_sec）。
  ⚠️ 单看"过阈值的帧有多少"会**高估**：迟滞要求连续 ENTER_SEC 才升级，
  概率在阈值附近抖一下是不够的。

⚠️ 类别数从**检查点自己**读（`sd["classes"]`），不读 `config.CLASSES`：
  这样同一个脚本既能跑三类旧权重（做"改动前"的对照），也能跑二类新权重 ——
  而 `replay_clip.predict_clip` 写死了 `len(C.CLASSES)`，换个类数的权重就崩。

用法上的两个提醒：
  · `--model` **必须显式给**。`runs/` 下现在有 fatigue2 和 fatigue3 两个目录，
    而按 `sorted()` 取"最新"是**字典序**，fatigue3 > fatigue2 —— 不给参数会
    默默拿到三类那个。
  · 前 WINDOW-1 帧没有输出（窗口没填满），按**因果**落到窗口最后一帧，
    和实时推理一致。这几帧用第一个有效值前向填充，免得 EMA 被 NaN 带偏。
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config as C
from build_dataset import load_pose_csv, normalize_sequence
from model import PoseTransformer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def load_any(ckpt):
    """读检查点：权重 + 它**自己**的类别表 + 标准化量。"""
    sd = torch.load(ckpt, map_location="cpu", weights_only=False)
    m = PoseTransformer(**sd["model_kwargs"])
    m.load_state_dict(sd["state_dict"])
    m.eval()
    classes = [str(c) for c in sd["classes"]]      # 检查点自己的类别顺序
    return m, classes, (sd["feat_mean"], sd["feat_std"])


def predict(model, csv_path, stat, n_cls, chunk=512):
    """(T, n_cls) 逐帧概率，前 WINDOW-1 帧 NaN。不用 replay_clip 那份（它写死类数）。"""
    feats = normalize_sequence(load_pose_csv(csv_path))
    mean, std = stat
    feats = ((feats - mean) / std).astype(np.float32)
    T = len(feats)
    n_win = T - C.WINDOW + 1
    probs = np.full((T, n_cls), np.nan, np.float32)
    if n_win <= 0:
        return probs
    with torch.no_grad():
        for s in range(0, n_win, chunk):
            e = min(s + chunk, n_win)
            batch = np.stack([feats[i:i + C.WINDOW] for i in range(s, e)])
            p = torch.softmax(model(torch.from_numpy(batch)), dim=1).numpy()
            probs[s + C.WINDOW - 1: e + C.WINDOW - 1] = p
    return probs


class Ladder:
    """`src/live.py` 的 `WarningState` 在这一个量上的等价物（只关心"到没到 L3"）。

    刻意逐行照抄那边的三段逻辑：EMA → 目标级别 → 连续计时。数字全部从
    `live` 模块读，不另拍 —— 不然量出来的不是屏上跑的那个梯子。
    """

    def __init__(self, live, n_cls):
        self.h = live.Hysteresis()
        self.ema = 1.0 / n_cls
        self.level = 0
        self._pend = -1
        self._pend_t = 0.0

    def update(self, sig, now):
        h = self.h
        self.ema = h.alpha * sig + (1.0 - h.alpha) * self.ema
        # 目标级别：非 normal 那侧只有 L3 这一档，所以就是"过没过阈值"。
        # 当前已是 L3 时用较低的 EXIT_TH（迟滞下沿），否则用 ENTER_TH。
        th = h.exit_th if self.level >= 3 else h.enter_th
        tgt = 3 if self.ema > th else 0
        if tgt == self.level:
            self._pend = -1
            return self.level
        if tgt != self._pend:
            self._pend, self._pend_t = tgt, now
            return self.level
        need = h.enter_sec if tgt > self.level else h.exit_sec
        if now - self._pend_t < need:
            return self.level
        self.level = tgt
        self._pend = -1
        return self.level


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True,
                    help="**必给**：runs/ 下 fatigue2 与 fatigue3 并存，"
                         "默认按字典序取会拿到 fatigue3")
    ap.add_argument("--dirs", nargs="+", required=True,
                    help="data/pose 下的目录名，如 normal glance phone fatigue")
    args = ap.parse_args()

    import live                                   # 迟滞常数只认这一份

    ckpt = Path(args.model)
    model, classes, stat = load_any(ckpt)
    n_cls = len(classes)
    assert "normal" in classes, f"检查点里没有 normal 类：{classes}"
    non_norm = [k for k, c in enumerate(classes) if c != "normal"]

    print(f"模型 {ckpt.name}   {n_cls} 类 {classes}   "
          f"ENTER_TH={live.ENTER_TH}  EXIT_TH={live.EXIT_TH}  "
          f"α={live.EMA_ALPHA}  升{live.ENTER_SEC}s/降{live.EXIT_SEC}s\n")
    print(f"  证据强度 = {'max(' + ', '.join(classes[k] for k in non_norm) + ')'}"
          f"（非 normal 那一侧的最大概率）\n")

    print(f"{'目录':<9}{'片段':<14}{'最高级别':>9}{'L3 秒数':>9}"
          f"{'过阈值帧占比':>13}{'最长连续过阈值':>15}{'平均P(非正常)':>14}")
    print("-" * 92)

    per_dir = {}
    for d in args.dirs:
        dd = C.DATA_POSE / d
        clips = sorted(dd.glob("*.csv")) if dd.is_dir() else []
        if not clips:
            print(f"{d:<9}(没有 CSV，跳过)")
            continue
        reached = 0
        l3_secs = []
        for clip in clips:
            probs = predict(model, clip, stat, n_cls)
            valid = ~np.isnan(probs[:, 0])
            if valid.sum() < 2:
                print(f"{d:<9}{clip.stem:<14}  帧数不足，跳过")
                continue
            # 前 WINDOW-1 帧没有输出 —— 用第一个有效值前向填充，
            # 免得 EMA 被 NaN 带偏（实时那边这几帧根本还没判决）。
            p = probs.copy()
            p[:] = probs[valid][0]
            p[valid] = probs[valid]
            sig = p[:, non_norm].max(1)

            ts = pd.read_csv(clip, usecols=["timestamp_ms"])["timestamp_ms"].to_numpy(
                float) / 1000.0
            if len(ts) != len(sig):
                ts = np.arange(len(sig)) / C.TARGET_FPS

            lad = Ladder(live, n_cls)
            lvl = np.empty(len(sig), int)
            for i in range(len(sig)):
                lvl[i] = lad.update(float(sig[i]), float(ts[i]))

            dt = float(np.median(np.diff(ts))) if len(ts) > 2 else 1.0 / C.TARGET_FPS
            sec_l3 = float((lvl == 3).sum() * dt)
            ab = sig[valid] > live.ENTER_TH
            frac = float(ab.mean()) if len(ab) else 0.0
            # 最长连续过阈值（秒）—— 迟滞要连续 ENTER_SEC 才升级，
            # 所以这个数比"过阈值帧占比"更接近"会不会真的报警"。
            run = best = 0
            for v in ab:
                run = run + 1 if v else 0
                best = max(best, run)
            if (lvl == 3).any():
                reached += 1
            l3_secs.append(sec_l3)
            print(f"{d:<9}{clip.stem:<14}{int(lvl.max()):>9}{sec_l3:>9.1f}"
                  f"{frac * 100:>12.0f}%{best * dt:>14.1f}s"
                  f"{float(sig[valid].mean()):>14.3f}")
        if l3_secs:
            a = np.array(l3_secs)
            per_dir[d] = (reached, len(l3_secs), float(a.mean()), float(a.max()))

    print("-" * 92)
    print("★ 负对照（这些片段**不该**被判成重度疲劳）：")
    for d, (r, n, mean_s, max_s) in per_dir.items():
        print(f"  {d:<9} 顶成 L3 的片段 {r}/{n}   L3 秒数 均值 {mean_s:.1f}s "
              f"最长 {max_s:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
