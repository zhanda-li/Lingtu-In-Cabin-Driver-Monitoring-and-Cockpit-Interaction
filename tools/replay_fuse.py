"""L3：融合行为回放 —— 把 data/raw 下的片段喂给 **src/fuse.py 本体**，看闸门和级别。

── 为什么不能只靠"我读过代码，闸门是这么写的" ──────────────────────
`src/fuse.py` 的闸门、支路二迟滞、哈欠规则、来源感知文案分散在 40 多行的
决策块里，互相耦合（闸门关 → b2.reset() → l2=0 → 文案回落到支路一）。
读代码只能确认"我认为它会这样走"；这里是让它**自己走一遍**，然后拿
它写出来的 CSV 对账。两者不一致的地方，才是要看的。

── 对账的四条（对应方案 L3）────────────────────────────────────────
1. fatigue 片段：支路一应能把级别顶到 **L3**（支路二的权限封顶 L2，
   所以 L3 只可能来自支路一 —— 看到 L3 就同时证明了封顶没写反）。
2. glance / phone 片段：闸门应**大部分时间关闭**（这两类正是头在动的那两类），
   级别仍由支路一给 L1/L2，且**不应出现支路二的文案**。
3. normal 片段：闸门应**开着**，且支路二不应造假疲劳（l2 全程 0）。
   这一条是误报率的底线 —— 正常驾驶时报疲劳比漏报更糟。
4. yawn_open 片段：哈欠规则应触发并抬到 L1；talking 片段不应触发。
   这是哈欠规则的端到端验证 —— 之前的标定只验了 `_ear_raw.npz` 里的
   离线原始量，没验过"整条管线跑下来它到底抬没抬级别"。

用法：
    python tools/replay_fuse.py --per-class 3      # 四类各 3 段，先看脚本通不通
    python tools/replay_fuse.py                    # 默认四类各 5 段 + 哈欠类全跑
    python tools/replay_fuse.py --clips fatigue_02,glance_00
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
OUT = ROOT / "runs" / "fuse_replay"
YAWN_MIN = 1.0          # 与 src/face.py 一致（2026-09-26 第二次改小）；CSV 里 yawn_sec 超过它算触发
                        # ⚠️ 这里是**抄本**不是 import：`import face` 会把 mediapipe
                        #   拖进来（析构固定 42 s，见 _scratch 里那条记录），
                        #   而这个脚本只读 CSV。改 src/face.py 那个数要跟着改这里。


def read_log(p):
    with open(p, encoding="utf-8") as f:
        head = f.readline().strip().split(",")
        rows = [ln.strip().split(",") for ln in f if ln.strip()]
    if not rows:
        return {}
    cols = {}
    for j, name in enumerate(head):
        v = []
        for r in rows:
            s = r[j] if j < len(r) else ""
            try:
                v.append(float(s))
            except ValueError:
                v.append(np.nan)
        cols[name] = np.array(v)
    return cols


def run_clip(clip, tag, log):
    cmd = [PY, str(ROOT / "src" / "fuse.py"), "--replay", str(clip), "--fast",
           "--no-display", "--no-voice", "--quiet", "--log-probs", str(log)]
    r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.returncode, (r.stderr or "")[-600:]


def summarize(cls, name, c):
    """一段的 CSV → 一行结论。c 为空 = 没跑出东西。

    ⚠️ 这里有两个**必须分开**的量，混起来会得出错的结论：
      `b2_vote`  = l2 > 0 的帧数  —— 支路二（逻辑回归）真的投了票
      `yawn_up`  = l_fused > l1 且 l2 == 0 的帧数 —— 哈欠**规则**抬的级
    第一版把两者混成一个 `b2_alone`，于是 yawn_open 上那 15 帧被记成了
    「支路二抬级」—— 支路二其实一帧都没投。

    哈欠规则只要 2.5 秒缓冲、不需要逻辑回归热身，所以**理论上**它能在
    短片段上触发而支路二不能。第一版这里写的也是这句话 —— 但当时它是错的：
    fuse.py 的 yawn_sec 是从 `st` 里取的，而 `st` 要等 `fb.ready()`（10 秒）。
    本脚本的第一次运行就是这么把这个 bug 逼出来的（yawn_open_01 不触发，
    而它离线是 4.40 s）。修好之后这条注释才成立。
    """
    if not c or "l_fused" not in c:
        return None
    gate = c["gate"]
    l1 = np.nan_to_num(c["l1"], nan=0.0)
    l2 = np.nan_to_num(c["l2"], nan=0.0)
    lf = np.nan_to_num(c["l_fused"], nan=0.0)
    p_ok = int(np.isfinite(c["p_fat"]).sum())
    return dict(
        cls=cls, name=name, n=len(gate),
        gate_open=float(np.mean(gate > 0.5)) if len(gate) else float("nan"),
        l1_max=int(l1.max()) if len(gate) else 0,
        l2_max=int(l2.max()) if len(gate) else 0,
        lf_max=int(lf.max()) if len(gate) else 0,
        b2_vote=int(np.sum(l2 > 0)),
        yawn_up=int(np.sum((lf > l1) & (l2 == 0))),
        # p_fat 是有限值的帧数 = 支路二真正出了数的帧数。
        # 0 就表示**这一整段支路二没参与**，此时"没误报"是废话不是成绩。
        p_ok=p_ok,
        p_max=float(np.nanmax(c["p_fat"])) if p_ok else float("nan"),
        yawn=bool(np.nanmax(c["yawn_sec"]) >= YAWN_MIN) if len(gate) else False,
        yawn_sec=float(np.nanmax(c["yawn_sec"])) if len(gate) else 0.0,
        perclos=float(np.nanmax(c["perclos"])) if np.isfinite(c["perclos"]).any()
        else float("nan"),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-class", type=int, default=5)
    ap.add_argument("--clips", default=None,
                    help="逗号分隔的片段名（不带目录），覆盖 --per-class")
    ap.add_argument("--data", default=None)
    ap.add_argument("--classes", default="normal,glance,phone,fatigue,yawn_open,talking")
    args = ap.parse_args()

    raw = Path(args.data) if args.data else (ROOT / "data" / "raw")
    classes = args.classes.split(",")
    if args.clips:
        want = set(args.clips.split(","))
        picks = [p for p in sorted(raw.glob("*/*.mp4")) if p.stem in want]
    else:
        picks = []
        for cls in classes:
            got = sorted(raw.glob(f"{cls}/*.mp4"))
            if not got:
                continue
            n = args.per_class
            picks += got[:n]

    OUT.mkdir(parents=True, exist_ok=True)
    print(f"片段 {len(picks)} 个   输出 {OUT}\n")
    res = []
    for clip in picks:
        cls, name = clip.parent.name, clip.stem
        log = OUT / f"{cls}__{name}.csv"
        rc, err = run_clip(clip, "fuse.py", log)
        if rc != 0:
            print(f"{cls}/{name:<14}❌ fuse.py 退出码 {rc}")
            if err:
                print("   " + err.replace("\n", "\n   "))
            continue
        s = summarize(cls, name, read_log(log))
        if s is None:
            print(f"{cls}/{name:<14}❌ 日志为空")
            continue
        res.append(s)
        print(f"{cls}/{name:<14}帧 {s['n']:>4}  闸门开 {100*s['gate_open']:>5.1f}%  "
              f"L1max {s['l1_max']}  L2max {s['l2_max']}  "
              f"Lfused {s['lf_max']}  支路二投票 {s['b2_vote']:>3} 帧  "
              f"P出数 {s['p_ok']:>3} 帧  "
              + (f"Pmax {s['p_max']:.2f}  " if s["p_ok"] else "")
              + (f"哈欠抬级 {s['yawn_up']} 帧 ({s['yawn_sec']:.1f}s)"
                 if s["yawn"] else ""))

    print("\n" + "=" * 74)
    print("【对账】")
    by = {}
    for s in res:
        by.setdefault(s["cls"], []).append(s)
    ok = True

    # 0. ★ 全程最关键的一条：闸门到底开过没有。
    #    闸门要是**结构性关闭**（比如 GATE_MIN 写成 0.9，或 argmax 恒不等于 normal），
    #    那后面所有"支路二没误报"都是废话 —— 它压根没跑过。
    #    这个只能靠回放发现，真人不确定性太大；发现不了的话要等到现场演示才炸。
    n_open_clip = sum(1 for s in res if s["gate_open"] > 0.0)
    fr_open = sum(s["gate_open"] * s["n"] for s in res)
    fr_all = sum(s["n"] for s in res)
    print(f"  0. 闸门开过吗：{n_open_clip}/{len(res)} 个片段开过，"
          f"累计 {fr_open:.0f}/{fr_all} 帧（{100*fr_open/max(fr_all,1):.1f}%）")
    if n_open_clip == 0:
        print("     ❌ **一次都没开过** —— 支路二整条路是死的。")
        print("        先查 GATE_MIN 与 argmax(ema) 判据，别急着看别的。")
    else:
        print("     ✅ 闸门能开，支路二确实接到了帧。")
    ok &= n_open_clip > 0

    # 0.5 ★ 第二个"结构性"陷阱：闸门开了 ≠ 支路二出了数。
    #     支路二要先攒满 HIST_SEC(=27s) 才 `full()`，而训练片段普遍只有 10~17 秒
    #     （96 段中位 17.1 s）—— 于是**闸门全开的片段上 p_fat 也可以是全 NaN**，
    #     此时"支路二没有误报"是它没跑，不是它跑对了。
    #     这条直接决定后面 2/3 两条能不能算证据。
    p_ok_all = sum(s["p_ok"] for s in res)
    n_run = sum(1 for s in res if s["p_ok"] > 0)
    print(f"     （支路二出过数的帧：{p_ok_all} 帧 / {n_run} 个片段）")
    if p_ok_all == 0:
        print("     ⚠️ **支路二在这些片段上一次都没出数** —— 片段比 HIST_SEC=27 s 短，")
        print("        缓冲永远不满。所以下面的检查 2/3 是**结构性通过**，不是验证；")
        print("        支路二只能靠真人不间断跑 27 s 以上来验（L4）。")
        print("        唯一在短片段上真的跑起来的是哈欠**规则**（只要 2.5 s 缓冲）。")
    b2_live = p_ok_all > 0

    # 1. fatigue → L3 必须出现（只可能来自支路一）
    f = by.get("fatigue", [])
    if f:
        n3 = sum(1 for s in f if s["lf_max"] >= 3)
        print(f"  1. fatigue 片段到 L3 的：{n3}/{len(f)}"
              + ("   ✅" if n3 else "   ❌ 一段都没到 L3 —— 封顶写反了？"))
        ok &= n3 > 0
        # ⚠️ 这里原来写的是 `s['b2_alone']` —— 那个键在把 b2_alone 拆成
        #    b2_vote / yawn_up 的时候就没了，于是这行一跑就 KeyError，
        #    而且是在 print 里抛，**整个【对账】段都打不出来**。
        #    上一次没炸只是因为当时用 --clips 只跑了哈欠段，`by["fatigue"]` 是空的。
        #    两个量分开报，理由同 summarize() 的注释。
        print(f"     支路二在这些片段上单独投过票的帧数："
              f"{sum(s['b2_vote'] for s in f)}"
              f"（哈欠规则另抬 {sum(s['yawn_up'] for s in f)} 帧）"
              "（应远小于总数；疲劳片段的头也在动，闸门多半是关的）")

    # 2. glance / phone → 闸门多数关闭、无支路二投票
    #    ⚠️ 只有闸门**真的开过**时，"l2 恒 0"才是一条验证；
    #       闸门全程关闭时它是结构性的，不能打勾充数。
    for cls in ("glance", "phone"):
        g = by.get(cls, [])
        if not g:
            continue
        mo = float(np.mean([s["gate_open"] for s in g]))
        al = sum(s["b2_vote"] for s in g)
        if mo < 0.01:
            print(f"  2. {cls:<6} 闸门全程关闭（{100*mo:.1f}%）→ l2 恒 0 是"
                  f"**结构性的**，这条不构成支路二的验证")
        else:
            pm = float(np.nanmax([s["p_max"] for s in g]))
            print(f"  2. {cls:<6} 平均闸门开 {100*mo:>5.1f}%   支路二投票 "
                  f"{al} 帧   P(fat) 最高 {pm:.2f}"
                  + ("   ✅" if al == 0 else "   ⚠️ 闸门该开的时候投了票"))
            ok &= al == 0

    # 3. normal → 闸门开、没有假疲劳（误报底线）
    nm = by.get("normal", [])
    if nm:
        mo = float(np.mean([s["gate_open"] for s in nm]))
        bad = [s for s in nm if s["l2_max"] > 0]
        line = (f"  3. normal 平均闸门开 {100*mo:>5.1f}%   支路二投票 "
                f"{sum(s['b2_vote'] for s in nm)} 帧   l2max>0 的片段 "
                f"{len(bad)}/{len(nm)}")
        if not b2_live:
            print(line + "   ⚠️ 支路二未出数 —— **结构性通过，不算验证**")
        else:
            print(line + ("   ✅ 正常驾驶没有假疲劳" if not bad
                          else "   ❌ 正常片段上支路二报疲劳了"))
            ok &= not bad
        for s in bad:
            print(f"       {s['name']}: l2max {s['l2_max']} "
                  f"Pmax {s['p_max']:.2f} 闸门开 {100*s['gate_open']:.0f}%")

    # 4. 哈欠规则端到端
    yo = by.get("yawn_open", [])
    tk = by.get("talking", [])
    if yo:
        hit = sum(1 for s in yo if s["yawn"])
        print(f"  4. yawn_open 触发哈欠：{hit}/{len(yo)}"
              + ("   ✅" if hit == len(yo) else "   ❌ 漏了 —— 端到端和离线标定不一致"))
        ok &= hit == len(yo)
    if tk:
        fp = sum(1 for s in tk if s["yawn"])
        print(f"     talking   误触发：{fp}/{len(tk)}"
              + ("   ✅" if fp == 0 else "   ❌ 说话被当成哈欠"))
        ok &= fp == 0

    print("=" * 74)
    if not ok:
        print("❌ 有未过项，见上")
    elif not b2_live:
        print("🟡 无未过项，但**支路二本批一次没跑**（片段短于 HIST_SEC）。")
        print("   真被验到的：支路一的级别轨迹、闸门开合、哈欠规则端到端、")
        print("   以及「支路二没有被喂到帧」这件事本身。")
        print("   支路二本身仍然只能靠 L4 真人会话（不间断 27 s 以上）。")
    else:
        print("✅ 四条全过")
    sys.stdout.flush()
    os._exit(0 if ok else 1)


if __name__ == "__main__":
    main()
