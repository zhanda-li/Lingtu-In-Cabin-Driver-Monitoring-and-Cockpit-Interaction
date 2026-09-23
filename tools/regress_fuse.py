"""L2 回归：`src/fuse.py --no-face` 与 `src/live.py` 必须逐帧一致。

── 为什么需要这个，而不是"我没改 live.py 所以肯定没坏" ────────────────
`src/live.py` 本次确实一个字节都没动。但 `src/fuse.py` **把它的主循环抄了一遍**
（取帧 / 15 Hz 调度器 / 决策节拍 / 迟滞状态机 / 日志），抄就有抄错的可能：
少加一次 `n_fed`、`next_decide` 用错 dt、`frame_id` 和 `fed_id` 对不上……
这些都是**不会报错**的错，只会让概率序列慢慢偏，而现场看 HUD 是看不出来的。

`--no-face` 就是为这件事存在的：它把支路二整条路摘掉，此时 fuse.py 应当
与 live.py 输出**完全相同**的概率与级别序列。所以这条回归是**证明**，
不是假定。

── 注意别用"整个文件哈希"这类粗判据 ──────────────────────────────────
两个程序的 CSV **列数本来就不一样**（fuse 多 11 列），所以只能按**列名**
对齐比该比的那几列：4 个类别概率 + 级别。这正是本项目在另一个工程里
踩过的坑（拿 `.text` 整段哈希去验"只改了注释"，结果 SDK 把 `.rodata`
折进了 `.text`，文案一改必然变）——**比该比的字段**。

用法：
    python tools/regress_fuse.py               # 全部 data/raw 下的片段
    python tools/regress_fuse.py --limit 4     # 先跑几段看看
    python tools/regress_fuse.py --keep        # 保留 CSV 便于逐行看
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
OUT = ROOT / "runs" / "fuse_regress"
# 两边都必须相同的列（按列名取，不按位置取）
KEYS = ("normal", "glance", "phone", "fatigue", "level")
TOL = 1e-6


def read_log(p):
    """CSV -> (列名, {列名: np.array})。级别列两边叫法不同：live 叫 level，
    fuse 叫 l_fused —— 但 fuse 的日志头里也有 l1，这里显式映射成 level。"""
    with open(p, encoding="utf-8") as f:
        head = f.readline().strip().split(",")
        rows = [ln.strip().split(",") for ln in f if ln.strip()]
    if not rows:
        return head, {}
    cols = {}
    for j, name in enumerate(head):
        name = {"l_fused": "level", "l1": "level1"}.get(name, name)
        v = []
        for r in rows:
            s = r[j] if j < len(r) else ""
            try:
                v.append(float(s))
            except ValueError:
                v.append(np.nan)
        cols[name] = np.array(v)
    return head, cols


def run_one(args):
    clip, tag, out = args
    cmd = [PY, str(ROOT / "src" / tag[0]), "--replay", str(clip), "--fast",
           "--no-display", "--no-voice", "--quiet",
           "--log-probs", str(out)] + tag[1]
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stderr or "")[-800:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--keep", action="store_true")
    ap.add_argument("--data", default=None)
    args = ap.parse_args()

    raw = Path(args.data) if args.data else (ROOT / "data" / "raw")
    clips = sorted(raw.glob("*/*.mp4"))
    if not clips:
        raise SystemExit(f"{raw} 下没有片段")
    if args.limit:
        clips = clips[:args.limit]

    base_dir, after_dir = OUT / "base", OUT / "after"
    for d in (base_dir, after_dir):
        d.mkdir(parents=True, exist_ok=True)

    print(f"片段 {len(clips)} 个   输出 {OUT}")
    print(f"{'片段':<22}{'行数':>7}{'最大概率差':>12}{'级别不一致':>11}   结果")
    print("-" * 70)
    bad = []
    for clip in clips:
        name = f"{clip.parent.name}__{clip.stem}"
        fb, fa = base_dir / f"{name}.csv", after_dir / f"{name}.csv"
        rc, err = run_one((clip, ("live.py", []), fb))
        if rc != 0:
            print(f"{name:<22}{'':>7}{'':>12}{'':>11}   ❌ live.py 退出码 {rc}")
            bad.append((name, "live.py 跑失败", err))
            continue
        rc, err = run_one((clip, ("fuse.py", ["--no-face"]), fa))
        if rc != 0:
            print(f"{name:<22}{'':>7}{'':>12}{'':>11}   ❌ fuse.py 退出码 {rc}")
            bad.append((name, "fuse.py 跑失败", err))
            continue

        _, cb = read_log(fb)
        _, ca = read_log(fa)
        if not cb or not ca:
            bad.append((name, "空日志", ""))
            continue
        n = min(len(cb["level"]), len(ca["level"]))
        if len(cb["level"]) != len(ca["level"]):
            bad.append((name, f"行数不同 {len(cb['level'])} vs {len(ca['level'])}",
                        ""))
        dmax, lv_bad = 0.0, 0
        for k in ("normal", "glance", "phone", "fatigue"):
            d = float(np.nanmax(np.abs(cb[k][:n] - ca[k][:n]))) if n else 0.0
            dmax = max(dmax, d)
        lv_bad = int(np.nansum(cb["level"][:n] != ca["level"][:n]))
        ok = dmax <= TOL and lv_bad == 0 and len(cb["level"]) == len(ca["level"])
        print(f"{name:<22}{n:>7}{dmax:>12.2e}{lv_bad:>11}   "
              + ("✅" if ok else "❌"))
        if not ok:
            bad.append((name, f"概率差 {dmax:.2e} 级别不一致 {lv_bad} 行", ""))

    print("-" * 70)
    if not bad:
        print(f"✅ {len(clips)} 段全部逐帧一致 —— "
              f"fuse.py 里那套抄过来的主循环没有改变支路一的任何行为")
    else:
        print(f"❌ {len(bad)} 段不一致：")
        for n, why, err in bad:
            print(f"    {n:<22}{why}")
            if err:
                print("      " + err.replace("\n", "\n      "))

    if not args.keep:
        print(f"\n（CSV 留在 {OUT}，要清掉就删这个目录；--keep 只是不提示）")
    sys.stdout.flush()
    os._exit(0 if not bad else 1)


if __name__ == "__main__":
    main()
