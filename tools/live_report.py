"""读 `live.py --log-probs` 写出的 CSV，判断**活人身上模型到底有没有把握**。

为什么单做这个：录制片段上真值概率是 0.88~0.93，而用户现场跑出来峰值只有 0.64。
这两个数差别很大，但光看控制台滚动的数字判断不了，因为：

  - 概率是**逐次决策**打的，滚动太快，人眼记不住峰值；
  - 录制时是摆拍、现场是自然坐姿，两者分布可能根本不同；
  - 最要命的是：0.64 这个数**和 normal_03（唯一"像疲劳"的正常片段）的峰值 0.639
    几乎是同一个数** —— 意味着没有阈值能把"活人正常"和"录制里的异常正常"分开。

所以要的结论只有一个：**真值那一列在活人身上能冲到多高**。

  >= 0.85  → 模型没问题，纯粹是阈值/迟滞没调好，用 live.py 的命令行旋钮现场解决
  ~0.6     → 模型在活人身上就是没把握，**调参救不了，必须补真实分布的样本**

用法（录的时候按固定顺序、每段固定时长，这个脚本才能自动切段）：

    live.bat --log-probs live.csv
    # 第一个决策行出现时立刻开始做第一个动作，每个动作保持 10 秒，依次做完
    python tools/live_report.py live.csv --labels normal,glance,phone,fatigue,normal --sec 10

`--sec` 和 `--labels` 必须和你实际做的一致；对不上就对不出结论（比不做还糟）。
"""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config as C

# 录制片段上的参照值，用来判断"活人身上是不是掉了"
RECORDED_REF = {"normal": 0.92, "glance": 0.92, "phone": 0.93, "fatigue": 0.92}


def load(path):
    rows = []
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            rows.append((float(r["t"]), [float(r[c]) for c in C.CLASSES],
                         int(r["level"])))
    return rows


def verdict_of(peak, recorded):
    """峰值和录制参照的比值决定结论。"""
    if peak >= 0.85:
        return "OK"
    if recorded and peak < 0.5 * recorded:
        return "没把握"
    return "偏低"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", help="live.py --log-probs 写出的文件")
    ap.add_argument("--labels", required=True,
                    help="按时间顺序做的动作，如 normal,glance,phone,fatigue,normal")
    ap.add_argument("--sec", type=float, required=True, help="每个动作保持多少秒")
    ap.add_argument("--th", type=float, default=None,
                    help="升级阈值，默认取 live.py 里的 ENTER_TH")
    args = ap.parse_args()

    import live
    th = args.th if args.th is not None else live.ENTER_TH

    rows = load(args.csv)
    if not rows:
        print("CSV 是空的——live.py 那次跑起来了吗？")
        return
    labels = args.labels.split(",")

    print(f"{args.csv}   {len(rows)} 次决策，跨 {rows[-1][0]:.1f}s")
    print(f"按每 {args.sec:g}s 一段切成 {len(labels)} 段：{','.join(labels)}")
    print(f"参照：录制片段上真值概率约 {RECORDED_REF['normal']:.2f}，"
          f"升级阈值 {th}\n")

    brief = " ".join(f"{c[:3]:>6}" for c in C.CLASSES)
    print(f"{'段':<4}{'动作':<9}{'时刻':>13}{'次数':>5}   {'平均概率 ' + brief}"
          f"{'真值峰值':>10}{'参照':>7}{'结论':>9}")
    print("-" * 88)

    bad = []
    for k, lab in enumerate(labels):
        t0, t1 = k * args.sec, (k + 1) * args.sec
        seg = [r for r in rows if t0 <= r[0] < t1]
        if not seg:
            print(f"{k:<4}{lab:<9}{f'{t0:g}~{t1:g}s':>13}{'—':>5}   "
                  f"这段时间没有决策（live.py 没在跑？）")
            continue
        ti = C.CLASSES.index(lab) if lab in C.CLASSES else 0
        mean_p = [sum(r[1][i] for r in seg) / len(seg)
                  for i in range(len(C.CLASSES))]
        peak = max(r[1][ti] for r in seg)
        ref = RECORDED_REF.get(lab, 0.0)
        v = verdict_of(peak, ref)
        if lab != "normal" and v != "OK":
            bad.append((lab, peak))
        print(f"{k:<4}{lab:<9}{f'{t0:g}~{t1:g}s':>13}{len(seg):>5}   "
              + " ".join(f"{m:>6.3f}" for m in mean_p)
              + f"{peak:>10.3f}{ref:>7.2f}{v:>9}")

    print("-" * 88)
    if bad:
        print(f"\n⚠️  {len(bad)} 个动作在活人身上没到 0.85："
              + "、".join(f"{l}({p:.2f})" for l, p in bad))
        print("   **这就是敏感度不够的根，而且调阈值救不了**：")
        print(f"   活人峰值和阈值 {th} 贴得太近，降阈值会立刻开始误报——")
        print("   活人正常 和 录制里那个像疲劳的正常片段，在概率上是同一个数。")
        print("\n   明天补数据时必须改三点：")
        print("   1. 用**现场那套**摄像头位置/高度/距离/光线（别换机位）")
        print("   2. 录**自然**坐姿，不要刻意摆（现在是摆拍，所以活人对不上）")
        print("   3. normal 要加倍补——它是唯一在短窗口下崩的一类")
    else:
        print("\n✅ 所有动作在活人身上都到了 0.85 以上。")
        print("   模型没问题，现场直接调旋钮就行，不用补数据：")
        print("     live.bat --enter-th 0.55 --enter-sec 0.2 --alpha 0.6")


if __name__ == "__main__":
    main()
