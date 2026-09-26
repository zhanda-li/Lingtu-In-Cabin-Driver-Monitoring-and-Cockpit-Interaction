"""把一个片段的骨骼 CSV 逐帧过模型，看概率随时间的走势。

为什么需要这个：训练脚本只给一个汇总准确率，看不出"错的都是哪几帧"。

读两个数，**别混**：
  · **合并为两类（清醒 / 疲劳）的段级正确率** —— 这才是产品的判据。
    `src/live.py` 的 `CLASS_LEVEL` 把 phone / fatigue 都落 L3，档位、闸门
    （`src/fuse.py` 只看 P(normal)）、配色、语音、推送**都不区分这两类**，
    所以现场会不会误报/漏报，只能读这个数。
  · **3 类逐帧正确率 + 混淆对概率** —— 诊断用。`fatigue` 和 `phone` 都是低头，
    唯一区别是周期性：如果模型其实在靠"低头幅度"这类静态量区分，换个坐姿就崩，
    而测试集上依然很高。混淆对低才说明它真在用周期性（但对档位无后果）。

窗口预测按**因果**方式落到窗口最后一帧（与实时推理一致），
所以每个片段前 WINDOW-1 帧没有输出。
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config as C
from build_dataset import DIR_CLASS, DIRS, load_pose_csv, normalize_sequence
from model import PoseTransformer

CHUNK = 512


def _mpl():
    """matplotlib 的中文字体必须显式设，否则中文全渲染成方块（豆腐块）。
    和 src/train.py 里保持同一套。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    return plt


def load_model(ckpt, device="cpu"):
    """checkpoint 是自包含的：cfg 描述结构，feat_mean/std 是训练时的标准化量。

    直接读它自己的统计量，而不是回头去读 npz——npz 重建过的话两者会不一致，
    而这种不一致的现象是"离线测着好、现场一坐就错"。
    """
    # 自己存的权重含 numpy 标量，weights_only=True 会拒收
    sd = torch.load(ckpt, map_location=device, weights_only=False)
    m = PoseTransformer(**sd["model_kwargs"]).to(device)
    m.load_state_dict(sd["state_dict"])
    m.eval()
    return m, (sd["feat_mean"], sd["feat_std"])


def predict_clip(model, csv_path, stat, device="cpu"):
    """返回 (T, n_class) 的逐帧概率，前 WINDOW-1 帧为 NaN（窗口还没填满）。"""
    seq = load_pose_csv(csv_path)
    feats = normalize_sequence(seq)
    mean, std = stat
    feats = ((feats - mean) / std).astype(np.float32)

    T = len(feats)
    n_win = T - C.WINDOW + 1
    if n_win <= 0:
        return np.full((T, len(C.CLASSES)), np.nan, np.float32)

    probs = np.full((T, len(C.CLASSES)), np.nan, np.float32)
    with torch.no_grad():
        for s in range(0, n_win, CHUNK):
            e = min(s + CHUNK, n_win)
            batch = np.stack([feats[i:i + C.WINDOW] for i in range(s, e)])
            logit = model(torch.from_numpy(batch).to(device))
            p = torch.softmax(logit, dim=1).cpu().numpy()
            # 因果落位：第 i 个窗口落在它的最后一帧
            probs[s + C.WINDOW - 1: e + C.WINDOW - 1] = p
    return probs


def trace_chars():
    """类别首字母当轨迹字符表，从 `config.CLASSES` 推导。

    写死过一次（四类时是 "nGpf"），改类别数就崩在 `IndexError` 上 ——
    而报错位置在几层函数里，看不出根因。首字母在现在的类别集下唯一
    （normal/fatigue → n/f），将来加类别也够用。
    """
    return "".join(c[0] for c in C.CLASSES)


def ascii_trace(trace, per_char=8):
    """一字符约 per_char 帧（15 fps 下 8 帧 ≈ 0.53 s）。"""
    chars = []
    table = trace_chars()
    for s in range(0, len(trace), per_char):
        seg = [x for x in trace[s:s + per_char] if x >= 0]
        if not seg:
            chars.append(".")
            continue
        vals, cnt = np.unique(seg, return_counts=True)
        chars.append(table[int(vals[cnt.argmax()])])
    return "".join(chars)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None, help="默认用 runs/ 下最新一个")
    ap.add_argument("--clip", default=None, help="单个 CSV，如 data/pose/fatigue/fatigue_00.csv")
    ap.add_argument("--all", action="store_true", help="所有片段都跑一遍")
    ap.add_argument("--plot", action="store_true", help="存概率走势图")
    args = ap.parse_args()

    if args.model:
        ckpt = Path(args.model)
    else:
        runs = sorted(p for p in Path(C.ROOT, "runs").iterdir() if p.is_dir())
        ckpt = runs[-1] / "best.pt"
    model, stat = load_model(ckpt)
    print(f"模型 {ckpt}  参数 {model.n_params():,}")
    legend = " / ".join(f"{c[0]} {c}" for c in C.CLASSES)
    print(f"每字符 ≈ {8} 帧 ≈ {8 / C.TARGET_FPS:.2f} s   "
          f"图例 . 无输出 / {legend}\n")

    if args.clip:
        clips = [Path(args.clip)]
    else:
        # 只遍历**映射到某个类别的目录**（`build_dataset.DIR_CLASS` 的键），
        # **不 glob 整个 data/pose**：`data/pose/glance/` 仍留在盘上（故意的，
        # 非破坏性），glob 会把它捡进来然后在 `C.CLASSES.index(...)` 上抛
        # ValueError —— 报的错是"glance is not in list"，看不出根因。
        #
        # ⚠️ 这里**不能**遍历 `C.CLASSES`（2026-09-25 二类合并踩过）：
        # 二类之后 `phone` 不再是类别名而是一个**目录名**，照 CLASSES 遍历会
        # 整整漏掉那 26 段 —— 而汇总表照样打印"漏报 0/26"，看起来是全绿，
        # 实际少了近一半样本。遍历目录名才覆盖得全：
        #   normal(27) + phone(26) + fatigue(26) = 79 段，与三类时代一致。
        clips = [p for d in DIRS
                 for p in sorted((C.DATA_POSE / d).glob("*.csv"))]

    # 片段落在哪个划分里，读清单；不在清单里的（比如刚录的）标 --
    split_of = {}
    man = C.DATA_DATASET / "dataset_manifest.json"
    if man.exists():
        m = json.loads(man.read_text(encoding="utf-8"))["clips"]
        for sp, per_cls in m.items():
            for cls, names in per_cls.items():
                for nm in names:
                    split_of[f"{cls}/{nm}"] = sp

    summary = []
    for clip in clips:
        # 目录 -> 类别（二类之后 `phone` 目录的样本标签是 `fatigue`，见 DIR_CLASS）
        if clip.parent.name not in DIR_CLASS:
            print(f"{clip.name}: 目录 {clip.parent.name} 没有映射到任何类别"
                  f"（`build_dataset.DIR_CLASS`），跳过")
            continue
        true_idx = C.CLASSES.index(DIR_CLASS[clip.parent.name])
        probs = predict_clip(model, clip, stat)
        valid = ~np.isnan(probs[:, 0])
        pred = probs[valid].argmax(1)
        if len(pred) == 0:
            print(f"{clip.name}: 帧数不足一个窗口，跳过")
            continue
        acc = float((pred == true_idx).mean())
        maj = int(np.bincount(pred, minlength=len(C.CLASSES)).argmax())
        mean_p = probs[valid].mean(0)
        # ---- 合并成两类（清醒 / 疲劳）后的正确率：**这才是产品的判据** ----
        # `src/live.py` 的 CLASS_LEVEL 把 phone 和 fatigue 都落 L3，于是档位、
        # 闸门（fuse 只看 P(normal)）、配色、语音、推送**全都不区分这两类**，
        # 只有 `attention` 那一行文字区分。所以"现场会不会误报/漏报"要读这个数，
        # 3 类正确率只是诊断（看模型到底在拿什么区分）。
        norm_i = C.CLASSES.index("normal")
        side = (pred == norm_i)                    # True = 判成清醒
        true_side = (true_idx == norm_i)
        macc = float((side == true_side).mean())
        mok = bool(macc >= 0.5)                    # 段级：多数帧站在真值那一侧
        # 混淆对：fatigue 段看 P(phone)，phone 段看 P(fatigue)。
        # 合并成两类后没有这一对，所以要判在不在、不是一个 `index` 抛出来。
        conf, other = None, None
        if "phone" in C.CLASSES and "fatigue" in C.CLASSES \
                and clip.parent.name in ("fatigue", "phone"):
            other = C.CLASSES.index("phone" if true_idx == C.CLASSES.index("fatigue")
                                    else "fatigue")
            conf = float(mean_p[other])
        sp = split_of.get(f"{clip.parent.name}/{clip.stem}", "--")
        summary.append((clip.parent.name, clip.stem, acc, maj, conf, sp,
                        float(mean_p[true_idx]), macc, mok))

        print(f"{clip.parent.name:<8} {clip.stem:<14} [{sp:<5}] 正确率 {acc * 100:5.1f}%  "
              f"合并 {macc * 100:5.1f}%  P({C.CLASSES[true_idx]})={mean_p[true_idx]:.3f}"
              + (f"  P({C.CLASSES[other]})={conf:.3f}" if conf is not None else ""))
        print(f"         {ascii_trace(pred)}")

        if args.plot:
            plt = _mpl()
            fig, ax = plt.subplots(figsize=(11, 3))
            t = np.arange(len(probs)) / C.TARGET_FPS
            for k, name in enumerate(C.CLASSES):
                ax.plot(t, probs[:, k], label=name,
                        lw=2 if k == true_idx else 1,
                        alpha=1.0 if k == true_idx else 0.55)
            ax.set_xlabel("秒"); ax.set_ylabel("概率")
            ax.set_title(f"{clip.stem}（真值 {C.CLASSES[true_idx]}）")
            ax.set_ylim(-0.02, 1.02); ax.legend(ncol=4, fontsize=8)
            ax.grid(alpha=0.25)
            out = ckpt.parent / f"replay_{clip.stem}.png"
            fig.tight_layout(); fig.savefig(out, dpi=110); plt.close(fig)
            print(f"         图 -> {out}")

    if args.all or not args.clip:
        print("\n" + "=" * 78)
        print(f"{'类别':<8}{'片段':<16}{'划分':<7}{'正确率':>9}{'众数':>10}"
              f"{'P(真值)':>9}{'P(易混类)':>11}")
        for cls, name, acc, maj, conf, sp, pt, macc, mok in summary:
            c = f"{conf:.3f}" if conf is not None else "-"
            print(f"{cls:<8}{name:<16}{sp:<7}{acc * 100:>8.1f}%{C.CLASSES[maj]:>10}"
                  f"{pt:>9.3f}{c:>11}")

        for sp in ("train", "val", "test"):
            sel = [s for s in summary if s[5] == sp]
            if sel:
                print(f"  [{sp}] {len(sel)} 段，平均逐帧正确率 "
                      f"{np.mean([s[2] for s in sel]) * 100:.1f}%")

        # ---------------- 产品判据：合并成两类（清醒 / 疲劳） ----------------
        print("\n合并为两类（清醒 / 疲劳）—— 档位、闸门、配色、语音、推送都只看这一层")
        for sp in ("train", "val", "test", "--"):
            sel = [s for s in summary if s[5] == sp]
            if not sel:
                continue
            good = [s for s in sel if s[8]]
            print(f"  [{sp:<5}] {len(good)}/{len(sel)} 段判对，"
                  f"逐帧平均正确率 {np.mean([s[7] for s in sel]) * 100:.1f}%")
        norm_i = C.CLASSES.index("normal")
        false_pos = [s for s in summary if s[0] == "normal" and not s[8]]
        miss = [s for s in summary if s[0] != "normal" and not s[8]]
        n_norm = len([s for s in summary if s[0] == "normal"])
        n_fat = len(summary) - n_norm
        print(f"  误报（清醒段判成疲劳）{len(false_pos)}/{n_norm} 段"
              + (": " + ", ".join(s[1] for s in false_pos) if false_pos else ""))
        print(f"  漏报（疲劳段判成清醒）{len(miss)}/{n_fat} 段"
              + (": " + ", ".join(s[1] for s in miss) if miss else ""))
        # 只有"误报/漏报"和 `attention` 那一行文字看得出来；`C.CLASSES[norm_i]`
        # 之外的类之间怎么混，对产品没有后果 —— 但它是模型在靠什么区分 的低成本探针。
        fat = [s for s in summary if s[0] == "fatigue" and s[4] is not None]
        pho = [s for s in summary if s[0] == "phone" and s[4] is not None]
        if fat and pho:
            print(f"\n混淆对概率（诊断用，两类同落 L3，对档位无后果）")
            print(f"  fatigue 段 的平均 P(phone)  = {np.mean([s[4] for s in fat]):.4f}"
                  f"   最大 {max(s[4] for s in fat):.4f}")
            print(f"  phone   段 的平均 P(fatigue)= {np.mean([s[4] for s in pho]):.4f}"
                  f"   最大 {max(s[4] for s in pho):.4f}")
            print("  两类的低头幅度是一样的，这两个数低才说明模型真在用周期性区分。")

        if args.plot:
            _summary_plot(summary, ckpt.parent)


def _summary_plot(summary, out_dir):
    """答辩那张图：左 = 每段的 P(真值)，右 = fatigue/phone 的混淆对。

    比单段的概率走势有用得多——单段走势是一条平线（4 秒窗口必然含一个完整
    周期，模型读的是布尔量），看不出门道；而"两类之间"的分离才是真本事。
    """
    plt = _mpl()
    # 按 config 里的严重度顺序排（normal/glance/phone/fatigue），不是字母序
    cls_list = [c for c in C.CLASSES if any(s[0] == c for s in summary)]
    colors = {"normal": "#4a90d9",
              "phone": "#d9663d", "fatigue": "#c0392b"}
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.6), dpi=150,
                             gridspec_kw={"width_ratios": [2.1, 1]})

    # 左：每段 P(真值)
    ax = axes[0]
    xs, ys, cs, labels = [], [], [], []
    i = 0
    for cls in cls_list:
        for s in [x for x in summary if x[0] == cls]:
            xs.append(i); ys.append(s[6]); cs.append(colors[cls])
            labels.append(s[1].replace(f"{cls}_", ""))
            i += 1
        i += 0.8                       # 类别之间留缝
    ax.bar(xs, ys, color=cs, width=0.8)
    ax.axhline(0.25, ls="--", lw=1, c="#888")
    ax.text(-0.6, 0.262, "瞎猜线 0.25", fontsize=8, color="#666")
    ax.set_ylim(0, 1.28)               # 留出放图例的高度
    ax.set_ylabel("P(真值) 的平均")
    ax.set_title("模型对每个片段的置信度（满分 1.0）", fontsize=11)
    ax.set_xticks(xs); ax.set_xticklabels(labels, fontsize=7, rotation=90)
    handles = [plt.Rectangle((0, 0), 1, 1, color=colors[c]) for c in cls_list]
    ax.legend(handles, cls_list, fontsize=9, ncol=4, loc="upper center",
              framealpha=0.9)
    ax.grid(axis="y", alpha=0.25)

    # 右：混淆对
    ax = axes[1]
    fat = [s for s in summary if s[0] == "fatigue" and s[4] is not None]
    pho = [s for s in summary if s[0] == "phone" and s[4] is not None]
    if fat and pho:
        vals = [np.mean([s[6] for s in fat]), np.mean([s[6] for s in pho]),
                np.mean([s[4] for s in fat]), np.mean([s[4] for s in pho])]
        labs = ["fatigue 段\nP(fatigue)", "phone 段\nP(phone)",
                "fatigue 段\nP(phone)", "phone 段\nP(fatigue)"]
        ax.bar(range(4), vals, color=["#c0392b", "#d9663d", "#c9c9c9", "#c9c9c9"])
        for k, v in enumerate(vals):
            ax.text(k, v + 0.02, f"{v:.3f}", ha="center", fontsize=9)
        ax.set_xticks(range(4)); ax.set_xticklabels(labs, fontsize=8)
        ax.set_ylim(0, 1.05)
        ax.set_title("低头幅度相同，只靠周期性区分\n左两柱越高、右两柱越低越好",
                     fontsize=10)
        ax.grid(axis="y", alpha=0.25)

    out = out_dir / "replay_summary.png"
    fig.tight_layout(); fig.savefig(out); plt.close(fig)
    print(f"\n汇总图 -> {out}")


if __name__ == "__main__":
    main()
