"""D7 探针：analyze() 里那个窗数阈值该按名义帧率还是按实测帧率？

`live_face.py:352`：

    if s.sum() < int(W * FPS * 0.6):
        continue

FPS = C.TARGET_FPS = 15（名义）。W = 5.0 秒 → 阈值 45 帧。
但那段会话实测只有 **6.3 fps**，5 秒里平均才 31 帧 —— 也就是说
**按本意该保留的窗，一大半被这个滤网丢掉了**。

比"丢太多"更要紧的是**它丢得不随机**：帧率随曝光时间漂（曝光短=进光少），
所以这个滤网是按"画面那几秒多亮"在切窗 —— 而那和**头动**强相关。

⚠️ 这里我先猜过一句方向，猜反了，留在这里当记录：我写的是滤网"保留
'画面亮/动得快'的窗，而那些窗正好是**头在动**的窗"。实测（本脚本最后
一节）是反的 —— 保留组头动范围中位 **4.2°**，丢弃组 **12.9°**，
r(窗内帧数, 头动范围) = **−0.45**。也就是说滤网保留的是**头不动**的窗。

方向反了，但结论更难看，不是更好看：`【2】` 判的是"头不动时 PERCLOS
上不上得去"，而**这个滤网正好也在按'头动不动'筛** —— 判据的
分层变量和被筛掉的维度是同一个。于是 `【2】` 的分母被预先富集过，
保留组里头不动窗占 110/302=36%，不筛时只有 131/520=25%。
按四种阈值排下来，`【2】` 的 PERCLOS 中位是 0.386 / 0.330 / 0.300 / 0.200：
**滤得越狠，这个数越好看**，0.386 是四个里最漂亮的一个。

真正不带筛子的证据是 `【3】` 那个标记期 vs 未标记期的比较（0.694 vs
0.193，3.6 倍）—— 它**不需要给头动设线**，也就不吃这个筛子。

本探针不改 `live_face.py`，只把三种阈值下的判决数字并排打出来，
看它到底值多少 —— 值钱就改，不值钱就留着并写明。

用法：
    python _scratch/_d7_probe.py _scratch/_face_live_20260922_235417.csv
"""
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
import config as C
from face import BLINK_THR, ROLL_WIN, norm_by_time, runs_sec

W, S = 5.0, 1.0
STILL, NEUT = 6.0, 5.0
FPS_NOMINAL = float(C.TARGET_FPS)


def verdict(t, en, pitch, mark, keep, tag):
    """keep: 布尔数组 —— 每个候选窗是否保留。返回判决数字 dict。"""
    p_ref = float(np.median(pitch))
    h0 = (t > t[0] + 10.0) & (mark == 0)
    if h0.sum() > 30:
        p_ref = float(np.median(pitch[h0]))
    wr, wp, wn, wm = [], [], [], []
    for i, st in enumerate(np.arange(t[0], t[-1] - W, S)):
        if not keep[i]:
            continue
        s = (t >= st) & (t < st + W)
        if s.sum() < 2:            # "不筛"那一档会放进完全空的窗
            continue
        p, e, ts_ = pitch[s], en[s], t[s]
        wr.append(float(np.percentile(p, 95) - np.percentile(p, 5)))
        wp.append(float(np.mean(e < BLINK_THR)))
        wn.append(max(runs_sec(ts_, e, lambda v: v < BLINK_THR) or [0.0]))
        wm.append(float(np.median(p)))
    wr, wp, wn, wm = map(np.array, (wr, wp, wn, wm))
    st_w = (wr < STILL) & (np.abs(wm - p_ref) < NEUT)
    mk = mark > 0
    pc_m = float(np.mean(en[mk] < BLINK_THR)) if mk.any() else float("nan")
    pc_u = float(np.mean(en[~mk] < BLINK_THR)) if (~mk).any() else float("nan")
    hr_m = (float(np.percentile(pitch[mk], 95) - np.percentile(pitch[mk], 5))
            if mk.sum() > 15 else float("nan"))
    return dict(
        tag=tag, n_win=len(wr), n_still=int(st_w.sum()),
        r_all=float(np.corrcoef(wp, wr)[0, 1]) if len(wr) > 2 else float("nan"),
        pc_med=float(np.median(wp)), pc_max=float(wp.max()),
        wr_med=float(np.median(wr)),
        pc_still_med=float(np.median(wp[st_w])) if st_w.any() else float("nan"),
        pc_still_max=float(wp[st_w].max()) if st_w.any() else float("nan"),
        close_max=float(wn[st_w].max()) if st_w.any() else float("nan"),
        pc_m=pc_m, pc_u=pc_u, hr_m=hr_m,
        ratio=pc_m / max(pc_u, 1e-6))


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else \
        str(ROOT / "_scratch" / "_face_live_20260922_235417.csv")
    a = np.genfromtxt(path, delimiter=",", names=True)
    t, ear, pitch, mark = a["t"], a["ear"], a["pitch"], a["mark"]
    ok = np.isfinite(ear) & np.isfinite(pitch)
    t, ear, pitch, mark = t[ok], ear[ok], pitch[ok], mark[ok]
    en = ear / np.maximum(norm_by_time(t, ear, ROLL_WIN), 1e-6)
    dur = float(t[-1] - t[0])
    fps_meas = len(t) / dur
    print(f"{Path(path).name}   {dur:.1f} s   {len(t)} 帧   "
          f"实测 {fps_meas:.1f} fps   名义 {FPS_NOMINAL:.0f} fps\n")

    starts = np.arange(t[0], t[-1] - W, S)
    n_each = np.array([int(((t >= s) & (t < s + W)).sum()) for s in starts])
    spans = np.array([(lambda ts_: float(ts_[-1] - ts_[0]) if len(ts_) > 1 else 0.0)(
        t[(t >= s) & (t < s + W)]) for s in starts])
    print(f"候选窗 {len(starts)} 个   窗内帧数：中位 {np.median(n_each):.0f}  "
          f"p10 {np.percentile(n_each,10):.0f}  p90 {np.percentile(n_each,90):.0f}  "
          f"max {n_each.max()}")
    print(f"                窗内实际跨度：中位 {np.median(spans):.1f} s  "
          f"最小 {spans.min():.1f} s\n")

    variants = [
        ("旧：名义帧率 15 → >=45 帧", n_each >= int(W * FPS_NOMINAL * 0.6)),
        ("实测帧率 → >=%.0f 帧" % (W * fps_meas * 0.6),
         n_each >= int(W * fps_meas * 0.6)),
        ("按跨度 → 窗内采样覆盖 >=80%", spans >= 0.8 * W),
        ("不筛（全要）", np.ones(len(starts), bool)),
    ]
    res = [verdict(t, en, pitch, mark, k, tag) for tag, k in variants]

    print(f"{'阈值':<26}{'窗数':>6}{'头不动窗':>9}{'r(PC,头动)':>11}"
          f"{'PC中位':>8}{'PC最高':>8}")
    print("-" * 70)
    for r in res:
        print(f"{r['tag']:<26}{r['n_win']:>6}{r['n_still']:>9}"
              f"{r['r_all']:>+11.2f}{r['pc_med']:>8.3f}{r['pc_max']:>8.3f}")

    print(f"\n{'阈值':<26}{'头不动PC中位':>13}{'最高':>8}{'最长闭眼':>10}"
          f"{'标记期PC':>10}{'未标记':>8}{'倍数':>7}{'标记期头动':>11}")
    print("-" * 96)
    for r in res:
        print(f"{r['tag']:<26}{r['pc_still_med']:>13.3f}{r['pc_still_max']:>8.3f}"
              f"{r['close_max']:>10.2f}{r['pc_m']:>10.3f}{r['pc_u']:>8.3f}"
              f"{r['ratio']:>7.1f}{r['hr_m']:>11.1f}")

    # ── 那个滤网到底偏向哪一边？**量出来，不要猜** ────────────────────
    # 我在 `live_face.py` 的 D7 注释里写过一句机制："被留下的系统性地是
    # 画面亮/动得快的窗 —— 恰好是头在动的窗"。改完 D7 后跑出来的是
    # 头动范围**最大** 26.8° → 61.4°（放宽后反而变大），和那句话正好相反。
    # 所以把每个候选窗的三个量并排量一次，看旧滤网保留/丢掉的分別是什么。
    print("\n【旧滤网偏向哪边】按旧阈值（>=45 帧）分保留 / 丢弃两组：")
    nf, pcw, hrw = [], [], []
    for st in starts:
        s = (t >= st) & (t < st + W)
        if s.sum() < 2:
            continue
        p, e = pitch[s], en[s]
        nf.append(int(s.sum()))
        pcw.append(float(np.mean(e < BLINK_THR)))
        hrw.append(float(np.percentile(p, 95) - np.percentile(p, 5)))
    nf, pcw, hrw = map(np.array, (nf, pcw, hrw))
    kept = nf >= int(W * FPS_NOMINAL * 0.6)
    print(f"  {'':<8}{'窗数':>6}{'帧数中位':>10}{'PERCLOS中位':>13}"
          f"{'头动范围中位':>14}{'头动最大':>10}")
    for tag, k in (("保留", kept), ("丢弃", ~kept)):
        if not k.any():
            continue
        print(f"  {tag:<8}{int(k.sum()):>6}{np.median(nf[k]):>10.0f}"
              f"{np.median(pcw[k]):>13.3f}{np.median(hrw[k]):>14.1f}"
              f"{hrw[k].max():>10.1f}")
    print(f"  r(窗内帧数, PERCLOS)  = {np.corrcoef(nf, pcw)[0,1]:+.2f}")
    print(f"  r(窗内帧数, 头动范围) = {np.corrcoef(nf, hrw)[0,1]:+.2f}")
    print("  → 读法：帧数多 = 摄像头那几秒快 = 曝光短 = 画面亮。")
    print("    若 r(帧数,PERCLOS) 为正，说明这个滤网**挑高了 PERCLOS**，")
    print("    那样 0.386 就是筛出来的，不是数出来的；")
    print("    真正不带筛子的结论只有【3】那个标记期 vs 未标记期的比较。")

    print("\n【判据】旧阈值下【3】那段为什么什么都没打印（D1）：")
    print(f"  pc_m={res[0]['pc_m']:.3f} > 0.5 成立，但 hr_m={res[0]['hr_m']:.1f} < 8 "
          f"不成立（差 {res[0]['hr_m']-8:.1f}°）；")
    print(f"  pc_m <= pc_u*1.3 = {res[0]['pc_u']*1.3:.3f} 也不成立。"
          f"两条全落空 → 静默。")
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
