"""全库标定表：每个片段对 4 个类的平均概率和最大概率。

为什么需要它：`replay_clip.py` 只报 P(真值)，看不到**别的类**涨到哪了。
而现场"敏感度不够"的真正症状是——模型对 normal 输入也给出 P(glance)≈0.60，
也就是**擦着阈值过**：擦着过的时候概率在阈值附近来回抖，驻留计时被反复清零，
延迟成倍放大，而且随时可能误报。

这张表一眼能看出模型是真的分开了，还是四个类挤在 0.25~0.60 这一小段里。

判据：
  - 理想：真值那一列接近 1.0，其余三列接近 0
  - 危险：**非真值列的最大值**逼近 ENTER_TH —— 这是误报的直接来源
  - 危险：真值列的最大值只比 ENTER_TH 高一点点 —— 这是延迟的直接来源

按 ENTER_TH 画一条线，只看"每一行的最大值落在哪一列、离阈值多远"。
"""

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config as C
from build_dataset import DIR_CLASS, DIRS
from replay_clip import load_model, predict_clip


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None)
    ap.add_argument("--enter-th", type=float, default=None)
    args = ap.parse_args()

    import live
    enter_th = args.enter_th if args.enter_th is not None else live.ENTER_TH

    ckpt = Path(args.model) if args.model else sorted(
        p for p in Path(C.ROOT, "runs").iterdir() if p.is_dir())[-1] / "best.pt"
    model, stat = load_model(ckpt)

    # 划分清单：标出每段是 train/val/test，test 才算数
    import json
    split_of = {}
    man = C.DATA_DATASET / "dataset_manifest.json"
    if man.exists():
        m = json.loads(man.read_text(encoding="utf-8"))["clips"]
        for sp, per in m.items():
            for cls, names in per.items():
                for nm in names:
                    split_of[f"{cls}/{nm}"] = sp

    brief = " ".join(f"{c[:3]:>7}" for c in C.CLASSES)
    # ★ 2026-09-24：`others` 从"除真值外的所有类"改成"**另一侧**的类"。
    # 产品的判据只有两侧：清醒 / 疲劳（`src/live.py` 的 CLASS_LEVEL 把 phone 和
    # fatigue 都落 L3）。所以"误报"只指清醒段被读成**非正常**这一件事 ——
    # 一个看手机的人被判成 fatigue，档位、闸门、配色、语音、推送全都一样，
    # 那不是误报。按旧口径它会被列进来，看着吓人，其实对产品无后果。
    # 三类之间的混淆仍然逐段打出来（诊断用），只是不进 `danger`。
    norm_i = C.CLASSES.index("normal")
    print(f"模型 {ckpt.name}   ENTER_TH={enter_th}   窗口 {C.WINDOW} 帧\n")
    print(f"{'类别':<8}{'片段':<14}{'划分':<7}{'平均概率 ' + brief}"
          f"{'  最大(对面侧)':>14}{'真值峰值':>10}{'裕度':>8}")
    print("-" * 92)

    danger = []
    # ⚠️ 按**目录**遍历（`build_dataset.DIRS`），不按 `C.CLASSES`：
    # 二类之后 `phone` 是目录名、不是类别名，按 CLASSES 遍历会整整漏掉那 26 段，
    # 而表照样打印得很正常 —— 少了近一半样本这件事看不出来。
    # 类别由 `DIR_CLASS` 映射（phone 目录 -> fatigue 类）。
    for d in DIRS:
        cls = DIR_CLASS[d]
        for clip in sorted((C.DATA_POSE / d).glob("*.csv")):
            true_idx = C.CLASSES.index(cls)
            probs = predict_clip(model, clip, stat)
            p = probs[~np.isnan(probs[:, 0])]
            if len(p) == 0:
                continue
            mean_p = p.mean(0)
            others = [k for k in range(len(C.CLASSES))
                      if (k == norm_i) != (true_idx == norm_i)]
            other_max = float(p[:, others].max())          # 对面侧的最大概率
            own_peak = float(p[:, true_idx].max())
            sp = split_of.get(f"{d}/{clip.stem}", "--")    # 清单按**目录**键
            margin = own_peak - other_max                  # 真值比最像的别类高多少
            print(f"{d:<8}{clip.stem:<14}{sp:<7}"
                  + " ".join(f"{v:>7.3f}" for v in mean_p)
                  + f"{other_max:>14.3f}{own_peak:>10.3f}{margin:>8.3f}")
            if other_max > enter_th:
                danger.append((clip.stem, sp, C.CLASSES[others[int(
                    np.argmax([p[:, k].max() for k in others]))]], other_max))
        print()

    print("=" * 92)
    if danger:
        print(f"⚠️  有 {len(danger)} 段被读到了**对面侧**且越过 ENTER_TH "
              f"({enter_th})，即会误报/漏报：")
        for nm, sp, who, v in danger:
            print(f"     {nm:<14}[{sp}] 被读成 {who}  {v:.3f}")
        print("\n   这解释了两件事：误报源，以及为什么擦着阈值过会让延迟成倍放大。")
    else:
        print(f"✅ 没有任何段被读到对面侧并越过 ENTER_TH ({enter_th})")

    peaks = []
    for cls in C.CLASSES:
        for clip in sorted((C.DATA_POSE / cls).glob("*.csv")):
            k = C.CLASSES.index(cls)
            probs = predict_clip(model, clip, stat)
            p = probs[~np.isnan(probs[:, 0])]
            if len(p):
                peaks.append((float(p[:, k].max()), clip.stem))
    lo = sorted(peaks)[:3]
    print(f"\n真值峰值最低的三段（越接近 {enter_th} 越危险）：")
    for v, nm in lo:
        print(f"     {nm:<14}{v:.3f}   离阈值还差 {v - enter_th:+.3f}")


if __name__ == "__main__":
    main()
