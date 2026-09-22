"""训练轻量时序 Transformer，并在测试集上评估。

产物（默认落在 runs/<时间戳>/）：
    best.pt                 最优权重 + 模型结构 + 标准化统计量（推理自包含）
    metrics.json            准确率、macro-F1、逐类指标、混淆矩阵原始数值
    confusion_matrix.png    混淆矩阵（样本数），PPT 素材
    confusion_matrix_norm.png  按行归一化的混淆矩阵，看"哪类被误判成哪类"更清楚
    curves.png              loss / 准确率曲线
    history.json           逐 epoch 记录

用法：
    python src/train.py
    python src/train.py --epochs 100 --d-model 96 --n-layer 4
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import config as C
from model import PoseTransformer


def set_seed(seed):
    import random
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def load_npz(path):
    """读数据集。存的时候用的是 str/数值 dtype，不需要 allow_pickle。"""
    d = np.load(path, allow_pickle=False)
    out = {}
    for split in ("train", "val", "test"):
        out[f"X_{split}"] = d[f"X_{split}"]
        out[f"y_{split}"] = d[f"y_{split}"]
        out[f"clip_{split}"] = d[f"clip_{split}"]
    out["feat_mean"] = d["feat_mean"]
    out["feat_std"] = d["feat_std"]
    out["classes"] = [str(s) for s in d["classes"]]
    out["window"] = int(d["window"])
    return out


@torch.no_grad()
def evaluate(model, loader, criterion, device):
    model.eval()
    tot = n = 0
    loss_sum = 0.0
    probs, labels = [], []
    for xb, yb in loader:
        xb, yb = xb.to(device), yb.to(device)
        logits = model(xb)
        loss = criterion(logits, yb)
        loss_sum += loss.item() * len(yb)
        probs.append(torch.softmax(logits, dim=-1).cpu().numpy())
        labels.append(yb.cpu().numpy())
        tot += (logits.argmax(1) == yb).sum().item()
        n += len(yb)
    if n == 0:
        return 0.0, 0.0, np.zeros((0, C.NUM_CLASSES)), np.zeros(0, np.int64)
    return loss_sum / n, tot / n, np.concatenate(probs), np.concatenate(labels)


def plot_confusion(cm, classes_cn, path, normalize=False, title=""):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    m = cm.astype(np.float64)
    if normalize:
        rs = m.sum(axis=1, keepdims=True)
        m = np.divide(m, rs, out=np.zeros_like(m), where=rs > 0)

    fig, ax = plt.subplots(figsize=(6.4, 5.4), dpi=160)
    im = ax.imshow(m, cmap="Blues", vmin=0, vmax=m.max() if m.max() > 0 else 1)
    ax.set_xticks(range(len(classes_cn)))
    ax.set_yticks(range(len(classes_cn)))
    ax.set_xticklabels(classes_cn, rotation=20, ha="right", fontsize=9)
    ax.set_yticklabels(classes_cn, fontsize=9)
    ax.set_xlabel("预测", fontsize=11)
    ax.set_ylabel("真实", fontsize=11)
    ax.set_title(title, fontsize=12, pad=12)

    thr = m.max() * 0.6 if m.max() > 0 else 1
    for i in range(m.shape[0]):
        for j in range(m.shape[1]):
            txt = f"{m[i, j]:.2f}" if normalize else f"{int(m[i, j])}"
            ax.text(j, i, txt, ha="center", va="center", fontsize=10,
                    color="white" if m[i, j] > thr else "#1f2937")
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def plot_curves(history, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    ep = [h["epoch"] for h in history]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), dpi=160)

    axes[0].plot(ep, [h["train_loss"] for h in history], label="训练")
    axes[0].plot(ep, [h["val_loss"] for h in history], label="验证")
    axes[0].set_xlabel("epoch")
    axes[0].set_ylabel("loss")
    axes[0].set_title("损失曲线")
    axes[0].legend()
    axes[0].grid(alpha=0.3)

    axes[1].plot(ep, [h["train_acc"] for h in history], label="训练")
    axes[1].plot(ep, [h["val_acc"] for h in history], label="验证")
    axes[1].set_xlabel("epoch")
    axes[1].set_ylabel("准确率")
    axes[1].set_title("准确率曲线")
    axes[1].legend()
    axes[1].grid(alpha=0.3)

    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(C.DATA_DATASET / "dataset.npz"))
    ap.add_argument("--out", default=None, help="输出目录，默认 runs/<时间戳>")
    ap.add_argument("--epochs", type=int, default=C.EPOCHS)
    ap.add_argument("--batch-size", type=int, default=C.BATCH_SIZE)
    ap.add_argument("--lr", type=float, default=C.LR)
    ap.add_argument("--weight-decay", type=float, default=C.WEIGHT_DECAY)
    ap.add_argument("--d-model", type=int, default=C.D_MODEL)
    ap.add_argument("--n-head", type=int, default=C.N_HEAD)
    ap.add_argument("--n-layer", type=int, default=C.N_LAYER)
    ap.add_argument("--dropout", type=float, default=C.DROPOUT)
    ap.add_argument("--label-smooth", type=float, default=C.LABEL_SMOOTH)
    ap.add_argument("--patience", type=int, default=15, help="验证损失不降就早停")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--seed", type=int, default=C.SEED)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    set_seed(args.seed)
    device = torch.device(args.device)

    out_dir = Path(args.out) if args.out else (C.RUNS / time.strftime("%Y%m%d_%H%M%S"))
    out_dir.mkdir(parents=True, exist_ok=True)

    d = load_npz(args.data)
    classes = d["classes"]
    print(f"数据集 {args.data}")
    for split in ("train", "val", "test"):
        y = d[f"y_{split}"]
        per = " ".join(f"{classes[i]}={int((y == i).sum())}" for i in range(len(classes)))
        print(f"  {split:<5} {len(y):>6} 样本   {per}")

    Xtr, ytr = d["X_train"], d["y_train"]
    Xva, yva = d["X_val"], d["y_val"]
    Xte, yte = d["X_test"], d["y_test"]

    if len(Xtr) == 0:
        raise SystemExit("训练集为空。先按 README 录制视频，再跑 extract_pose.py / build_dataset.py")

    val_is_test_fallback = False
    if len(Xva) == 0:
        print("  [warn] 验证集为空，暂用测试集做模型选择 —— "
              "最终测试指标会偏乐观，务必补录片段")
        Xva, yva = Xte, yte
        val_is_test_fallback = True

    mk = lambda X, y: DataLoader(
        TensorDataset(torch.from_numpy(X), torch.from_numpy(y)),
        batch_size=args.batch_size, shuffle=True,
        generator=torch.Generator().manual_seed(args.seed))
    train_loader = mk(Xtr, ytr)
    val_loader = mk(Xva, yva)
    test_loader = mk(Xte, yte)

    # 类别不均衡时给少数类加权
    counts = np.bincount(ytr, minlength=len(classes)).astype(np.float64)
    counts = np.maximum(counts, 1.0)
    cls_w = counts.sum() / (len(classes) * counts)
    criterion = nn.CrossEntropyLoss(
        weight=torch.tensor(cls_w, dtype=torch.float32, device=device),
        label_smoothing=args.label_smooth)

    model = PoseTransformer(
        feat_dim=d["X_train"].shape[-1], window=d["window"], n_class=len(classes),
        d_model=args.d_model, n_head=args.n_head, n_layer=args.n_layer,
        dropout=args.dropout).to(device)

    print(f"模型参数量 {model.n_params():,}  |  设备 {device}")
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr,
                            weight_decay=args.weight_decay)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs)

    # 按**验证损失**选最优、按验证损失早停，不按准确率。
    # 准确率会饱和：验证集只有 4 个片段、题目又简单，第 3 轮就顶到 1.0000，
    # 之后再也不可能"提升"。曾因此白等 15 轮停在第 18 轮，还保存了**第 3 轮**
    # 的权重——而那一轮 val loss 是 0.64，第 18 轮已经降到 0.30。
    # 现象很隐蔽：准确率仍报 100%，但模型置信度只有 0.55，
    # 现场换个坐姿就在 0.25 的瞎猜线附近抖。--replay 里 P(真值) 只有 0.5x 就是这个。
    best_loss, best_acc, best_epoch, best_state = float("inf"), -1.0, -1, None
    min_delta = 1e-4          # 防止验证损失的自然抖动被当成"提升"
    history = []
    t0 = time.time()

    for ep in range(1, args.epochs + 1):
        model.train()
        ls = 0.0
        correct = n = 0
        for xb, yb in train_loader:
            xb, yb = xb.to(device), yb.to(device)
            opt.zero_grad(set_to_none=True)
            logits = model(xb)
            loss = criterion(logits, yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            ls += loss.item() * len(yb)
            correct += (logits.argmax(1) == yb).sum().item()
            n += len(yb)
        sched.step()

        tr_loss, tr_acc = ls / max(n, 1), correct / max(n, 1)
        va_loss, va_acc, _, _ = evaluate(model, val_loader, criterion, device)

        history.append({"epoch": ep, "train_loss": tr_loss, "train_acc": tr_acc,
                        "val_loss": va_loss, "val_acc": va_acc,
                        "lr": opt.param_groups[0]["lr"]})

        if va_loss < best_loss - min_delta:
            best_loss, best_acc, best_epoch = va_loss, va_acc, ep
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}

        if not args.quiet:
            print(f"  ep {ep:>3}/{args.epochs}  "
                  f"train loss {tr_loss:.4f} acc {tr_acc:.3f}  |  "
                  f"val loss {va_loss:.4f} acc {va_acc:.3f}"
                  + ("  *" if ep == best_epoch else ""))

        if ep - best_epoch >= args.patience:
            print(f"  验证损失连续 {args.patience} 轮没降，早停于 epoch {ep}")
            break

    train_time = time.time() - t0

    # ---- 用最优权重在测试集评估 ----
    model.load_state_dict(best_state)
    te_loss, te_acc, probs, labels = evaluate(model, test_loader, criterion, device)

    from sklearn.metrics import classification_report, confusion_matrix
    preds = probs.argmax(1) if len(probs) else np.zeros(0, np.int64)
    cm = (confusion_matrix(labels, preds, labels=list(range(len(classes))))
          if len(labels) else np.zeros((len(classes), len(classes)), np.int64))
    report = (classification_report(labels, preds, labels=list(range(len(classes))),
                                    target_names=classes, digits=4, zero_division=0)
              if len(labels) else "（测试集为空，无法评估）")

    names_cn = [C.CLASS_NAMES_CN[classes.index(c)] if c in C.CLASSES else c
                for c in classes]
    plot_confusion(cm, names_cn, out_dir / "confusion_matrix.png",
                   normalize=False,
                   title=f"混淆矩阵（样本数）  测试准确率 {te_acc*100:.2f}%")
    plot_confusion(cm, names_cn, out_dir / "confusion_matrix_norm.png",
                   normalize=True, title="混淆矩阵（按真实类别归一化）")
    plot_curves(history, out_dir / "curves.png")

    ckpt = {
        "state_dict": best_state,
        "model_kwargs": {"feat_dim": int(d["X_train"].shape[-1]),
                         "window": int(d["window"]),
                         "n_class": len(classes),
                         "d_model": args.d_model, "n_head": args.n_head,
                         "n_layer": args.n_layer, "dropout": args.dropout},
        "classes": classes,
        "feat_mean": d["feat_mean"],
        "feat_std": d["feat_std"],
        "window": int(d["window"]),
        "test_acc": te_acc,
        "best_epoch": best_epoch,
        "best_val_loss": best_loss,
        "best_val_acc": best_acc,
        "classes": classes,
    }
    torch.save(ckpt, out_dir / "best.pt")

    metrics = {
        "data": str(args.data),
        "out_dir": str(out_dir),
        "n_params": model.n_params(),
        "epochs_run": len(history),
        "best_epoch": best_epoch,
        "best_val_loss": best_loss,
        "best_val_acc": best_acc,
        "test_loss": te_loss,
        "test_acc": te_acc,
        "val_is_test_fallback": val_is_test_fallback,
        "confusion_matrix": cm.tolist(),
        "classes": classes,
        "classification_report": report,
        "train_time_s": round(train_time, 2),
        "args": vars(args),
    }
    (out_dir / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "history.json").write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    np.save(out_dir / "confusion_matrix.npy", cm)

    print(f"\n最优 epoch {best_epoch}  验证损失 {best_loss:.4f}  "
          f"验证准确率 {best_acc:.4f}")
    print(f"测试集准确率 {te_acc*100:.2f}%   测试损失 {te_loss:.4f}")
    print("提示：准确率会饱和，看不出模型有多自信。跑 tools/replay_clip.py "
          "看 P(真值) 和混淆对的概率。")
    print(f"训练耗时 {train_time:.1f} s")
    print("\n" + report)
    print(f"产物目录：{out_dir}")


if __name__ == "__main__":
    main()
