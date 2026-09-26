# -*- coding: utf-8 -*-
"""把三条规则放到**真人真摄像头**的会话上量一遍 —— 回答用户 2026-09-26 的三问：

    ① 「我仰头为啥也算持续低头」
    ② 「我眨眼为啥说我持续闭眼」
    ③ 「为啥打哈欠需要我张嘴那么大才算」

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch\\_probe_live_rules.py

⚠️ 为什么**不能**用 `_ear_raw.npz` 回答这三问：那是 15 fps 的**录像**片段，而实时
   摄像头这台实测只有 ~10 fps（`norm_by_time` 的注释里记着 6~11）。帧率直接决定
   「连续闭眼」量出来多少秒 —— `runs_sec` 的每一段是**帧间隔**的整数倍，10 fps 下
   一帧就是 0.1 s。三问里有两条都是"实时和离线量出来的不是一回事"，所以必须用
   **实时速率**的真会话。
   本脚本只读 `_scratch/_face_live_*.csv`（`live_face.py` 的产物，真人 + 真摄像头、
   带空格标记 = 「我现在闭着眼」的**真值**），不重跑 FaceMesh、不开摄像头。

四条都要**先量再说**（项目的规矩：别让阈值决定判决，要直接量）：
  【1】帧率与跨度 —— 上面那个前提本身也要量，不能引用注释
  【2】闭眼规则：`en = ear / p75基线`，`en < 0.80` 连续多少秒？标记的真闭眼落在哪
  【3】低头规则：现在这个 `p95 − p5` 有多少次是**抬头**驱动的（拆成正负两半）
  【4】哈欠规则：MAR 到底到了多少、连续多久（用户说"要张那么大"）
"""
import glob
import os
import sys

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

from face import (BLINK_THR, HEAD_DEG, HEAD_WIN, NORM_Q, ROLL_WIN,   # noqa: E402
                  YAWN_MIN, YAWN_THR, norm_by_time, runs_sec, yawn_plateau)

SESSIONS = sorted(glob.glob(os.path.join(HERE, "_face_live_*.csv")))
COLS = ("t", "ear", "en", "mar", "pitch", "yaw", "roll", "perclos", "brate",
        "yawn", "dpitch", "prob", "mark", "face")


def load(path):
    out = {c: [] for c in COLS}
    for line in open(path, encoding="utf-8", errors="replace").read().splitlines()[1:]:
        f = line.split(",")
        if len(f) < len(COLS):
            continue
        for c, v in zip(COLS, f):
            try:
                out[c].append(float(v) if v not in ("", "-") else np.nan)
            except ValueError:
                out[c].append(np.nan)
    return {c: np.asarray(v, float) for c, v in out.items()}


def runs_with_time(ts, x, fn):
    """和 `face.runs_sec` 同一个判据，但**带起止时刻**（要拿它跟标记对表）。"""
    out, cur, t0 = [], False, 0.0
    for i, v in enumerate(x):
        if np.isfinite(v) and fn(v):
            if not cur:
                cur, t0 = True, ts[i]
        elif cur:
            cur = False
            out.append((t0, ts[i] - t0))          # (起点, 时长)
    if cur:
        out.append((t0, ts[-1] - t0))
    return out


def runs_gap(ts, x, fn, gap):
    """和 `runs_sec` 同一个判据，但**容忍中间丢 ≤ `gap` 秒的帧**（nan）。

    ★ 为什么需要它：`runs_sec` 里 `np.isfinite(v) and mask_fn(v)` 一假就断段，
      所以张嘴张到最大、`face` 恰好丢掉的那 0.2 s 会把一次真哈欠劈成两段
      **各不够 YAWN_MIN** 的碎片（实测见本脚本 【5】的对照行）。
    """
    tsa = np.asarray(ts, float)
    out, cur, t0, last = [], False, 0.0, 0.0
    for i, v in enumerate(x):
        good = np.isfinite(v)
        if good and fn(v):
            if not cur:
                cur, t0 = True, tsa[i]
            last = tsa[i]
        elif cur:
            if good:                       # 真的不满足 → 段结束（和 runs_sec 同口径）
                cur = False
                out.append((t0, tsa[i] - t0))
            elif tsa[i] - last > gap:      # 丢脸丢得太久 → 段结束
                cur = False
                out.append((t0, last - t0))
    if cur:
        out.append((t0, last - t0))
    return out


def main():
    print("BLINK_THR=%.2f  NORM_Q=%.0f  ROLL_WIN=%.1f  HEAD_DEG=%.1f  HEAD_WIN=%.1f"
          "  YAWN_THR=%.2f" % (BLINK_THR, NORM_Q, ROLL_WIN, HEAD_DEG, HEAD_WIN,
                              YAWN_THR))
    for p in SESSIONS:
        d = load(p)
        ts = d["t"]
        if len(ts) < 30 or not np.isfinite(ts).any():
            continue
        span = float(ts[-1] - ts[0])
        dt = np.diff(ts[np.isfinite(ts)])
        dt = dt[dt > 1e-6]
        print("\n" + "=" * 78)
        print("%s" % os.path.basename(p))
        print("  【1】%d 帧 / %.1f s  →  %.2f fps（帧间隔 中位 %.3f s、最长 %.3f s）"
              % (len(ts), span, len(ts) / span if span else 0,
                 float(np.median(dt)) if len(dt) else 0,
                 float(dt.max()) if len(dt) else 0))

        ear = d["ear"]
        mk = np.isfinite(d["mark"]) & (d["mark"] > 0)
        if mk.any():
            segs = runs_with_time(ts, d["mark"], lambda v: v > 0)
            print("      空格标记（真值「我在闭眼」）%d 段，共 %.2f s：%s"
                  % (len(segs), float(np.nansum(d["mark"] * np.r_[np.diff(ts), 0] > 0)),
                     "  ".join("%.1f+%.2fs" % (t, s) for t, s in segs)))

        # ── 【2】闭眼规则 ────────────────────────────────────────────────
        if np.isfinite(ear).sum() > 30:
            en = ear / np.maximum(norm_by_time(ts, ear, ROLL_WIN), 1e-6)
            rs = runs_with_time(ts, en, lambda v: v < BLINK_THR)
            rs.sort(key=lambda x: -x[1])
            fire = [r for r in rs if r[1] >= 1.0]
            print("  【2】闭眼规则：`en < %.2f` 共 %d 段，最长 %.2f s；"
                  "其中 ≥1.0 s 的 %d 段 %s"
                  % (BLINK_THR, len(rs), rs[0][1] if rs else 0, len(fire),
                     " ".join("t=%.1f+%.2f" % r for r in fire[:8]) or "（无）"))
            print("      最长的六段：%s"
                  % "  ".join("t=%.1f+%.2fs" % r for r in rs[:6]))
            # 段长直方图 —— 「眨眼」和「真闭眼」在这里应该分成两堆
            bins = [(0, 0.2), (0.2, 0.4), (0.4, 0.7), (0.7, 1.0), (1.0, 2.0),
                    (2.0, 4.0), (4.0, 99)]
            hist = "  ".join("%.1f~%.1fs:%d" % (a, b, sum(a <= s < b for _, s in rs))
                             for a, b in bins)
            print("      段长分布：%s        （眨眼 0.1~0.4 s；≥1.0 s 才会响）" % hist)
            # ≥1.0 s 的那些段，**里面 en 有多低** —— 这是"真闭眼"和
            # "贴着阈值抖"的分水岭：贴着 0.80 抖的会长、但一点都不"闭"。
            prof = []
            for t0, dur in fire[:6]:
                m = (ts >= t0) & (ts <= t0 + dur)
                v = en[m]
                v = v[np.isfinite(v)]
                prof.append((float(np.min(v)), float(np.median(v)), t0, dur))
            for lo, md, t0, dur in prof:
                kind = "真闭眼" if md < 0.7 else ("**贴着阈值抖**" if md > 0.78 else "中等")
                print("        t=%6.1f + %.2fs：段内 en  最低 %.2f  中位 %.2f   %s"
                      % (t0, dur, lo, md, kind))

        # ── 【3】低头规则：p95−p5 是**无向**的，拆开看是谁在驱动 ────────
        pit = d["pitch"]
        if np.isfinite(pit).sum() > 30:
            ok = np.isfinite(pit)
            # 参考位：往前 ROLL_WIN 秒的 **p25**（最"抬头"的那一档 = 中性姿态）。
            # 用 p25 而不是中位，是照抄 EAR 那条的镜像（那边闭眼是"低"的一侧，
            # 所以基线取 p75）—— 这边低头是"高"的一侧，基线就得取低的一侧，
            # 否则持续低头会把基线自己拽上去（自我抑制）。
            ref = norm_by_time(ts, np.where(ok, pit, np.nan), ROLL_WIN, q=25)
            step, fires = 0.2, []
            t0 = ts[0]
            while t0 + HEAD_WIN <= ts[-1]:
                m = ok & (ts >= t0) & (ts <= t0 + HEAD_WIN)
                if m.sum() > 5:                                  # noqa: PLR2004
                    q = pit[m]
                    swing = float(np.percentile(q, 95) - np.percentile(q, 5))
                    r = float(ref[m][-1]) if np.isfinite(ref[m][-1]) else np.nan
                    if swing >= HEAD_DEG and np.isfinite(r):
                        fires.append((t0, swing, float(np.percentile(q, 95)) - r,
                                      r - float(np.percentile(q, 5))))
                t0 += step
            # 合并同一段里的连续触发（一遍低头会连着好几拍）
            segs = []
            for f in fires:
                if segs and f[0] - segs[-1][-1][0] <= step * 1.5:
                    segs[-1].append(f)
                else:
                    segs.append([f])
            up = [s for s in segs
                  if np.mean([f[3] > f[2] for f in s]) > 0.5]      # 抬头驱动
            print("  【3】低头规则（p95−p5 ≥ %.0f°）：%d 段触发，"
                  "其中**抬头驱动**的 %d 段" % (HEAD_DEG, len(segs), len(up)))
            for s in segs[:12]:
                dn = float(np.mean([f[2] for f in s]))
                up_ = float(np.mean([f[3] for f in s]))
                print("        t=%6.1f s  %5.2f s长  摆幅 %5.1f°  下探 %5.1f° / 上抬 %5.1f°"
                      "   %s" % (s[0][0], len(s) * step, float(np.mean([f[1] for f in s])),
                                 dn, up_, "←**抬头**" if up_ > dn else ""))
            fin = pit[ok]
            print("      pitch 全段 %6.1f ~ %6.1f°，中位 %6.1f°"
                  % (fin.min(), fin.max(), float(np.median(fin))))

        # ── 【4】哈欠规则：MAR 到多少、多久 ─────────────────────────────
        mar = d["mar"]
        if np.isfinite(mar).sum() > 30:
            fin = mar[np.isfinite(mar)]
            print("  【4】MAR 全段 中位 %.3f  最大 %.3f（阈值 YAWN_THR=%.2f）"
                  % (float(np.median(fin)), fin.max(), YAWN_THR))
            # ★ 生产判据（2026-09-26 起）：**1.5 s 滚动均值** > YAWN_THR。
            #   上面那行单帧统计只说明"MAR 到过多少"，判不判得出来看下面这行 ——
            #   `src/face.py` 的标定注释里引用的两次真哈欠秒数（7.79 / 3.79 s）
            #   就是在这里量出来的，所以它必须和 `yawn_seconds` 同一口径。
            prs = runs_with_time(ts, yawn_plateau(ts, mar), lambda v: v > YAWN_THR)
            prs.sort(key=lambda x: -x[1])
            print("       ★ 生产判据（滚均 1.5 s > %.2f）：%d 段，最长 %.2f s%s"
                  % (YAWN_THR, len(prs), prs[0][1] if prs else 0.0,
                     "  → **触发哈欠**（≥ YAWN_MIN=%.1f）" % YAWN_MIN
                     if prs and prs[0][1] >= YAWN_MIN else "  → 不触发"))
            print("        %s"
                  % ("  ".join("t=%.1f+%.2fs" % r for r in prs[:5]) or "（没有一段）"))
            for thr in (YAWN_THR, 0.55, 0.50, 0.45, 0.40):
                rs = runs_with_time(ts, mar, lambda v, t=thr: v > t)
                if rs:
                    rs.sort(key=lambda x: -x[1])
                    print("        > %.2f：%2d 段，最长 %5.2f s（%s）"
                          % (thr, len(rs), rs[0][1],
                             "  ".join("t=%.1f+%.2fs" % r for r in rs[:4])))
                else:
                    print("        > %.2f：一帧都没有" % thr)
            # MAR 的**形状**：最高的几处，嘴到底张了多久、张到多大。
            # 哈欠的判据是"持续"，所以这里要看的是**平台有多长**，不是峰值多高。
            top = np.argsort(np.where(np.isfinite(mar), mar, -9))[-3:][::-1]
            for i in sorted(top):
                m = (ts >= ts[i] - 0.6) & (ts <= ts[i] + 1.4)
                if not m.any():
                    continue
                tr = " ".join("%.2f" % v for v in mar[m])
                print("        峰 t=%.1f s（MAR %.3f）前后：%s" % (ts[i], mar[i], tr))
            yv = np.asarray([v for v in d["yawn"] if np.isfinite(v)], float)
            if len(yv):
                print("      管线自报的 yawn_sec：最大 %.2f s（>0 的帧 %d/%d），"
                      "perclos 最大 %.3f，prob 最大 %.3f"
                      % (yv.max(), int((yv > 0).sum()), len(yv),
                         float(np.nanmax(d["perclos"])), float(np.nanmax(d["prob"]))))

        # ── 【5】丢脸的帧：`runs_sec` 要求**连续**，中间一帧 nan 就把一段劈成两半 ──
        #    哈欠判据是"持续"，所以丢帧对它的伤害比对别的规则都大：
        #    张嘴张到最大的那几帧恰恰最容易丢（见下面）。
        nf = np.isfinite(d["face"]) & (d["face"] > 0)
        print("  【5】`face` 检不到脸的帧 %d/%d（%.1f%%）；最长连续丢脸 %.2f s"
              % (int((~nf).sum()), len(nf), 100.0 * (~nf).mean(),
                 max([s for _, s in runs_with_time(ts, nf.astype(float), lambda v: v < 1)]
                     or [0.0])))
        if np.isfinite(mar).sum() > 30:
            # 张嘴 > thr 的段：**允许丢脸 ≤ G 秒**时各有多长。G=0 就是现在的口径。
            # 最后一行是**生产判据**（滚均）配容差 —— 它才是"这段真哈欠报不报"
            # 的那一行，上面两行是单帧口径的对照。
            _pl = yawn_plateau(ts, mar)
            for name, arr in (("单帧", mar), ("★滚均1.5s（生产）", _pl)):
                row = []
                for G in (0.0, 0.2, 0.5, 1.0):
                    rs = runs_gap(ts, arr, lambda v, t=YAWN_THR: v > t, G)
                    rs.sort(key=lambda x: -x[1])
                    row.append("G=%.1f→%s" % (G, ("%.2fs" % rs[0][1]) if rs else "无"))
                print("        > %.2f（%s）最长一段：%s"
                      % (YAWN_THR, name, "  ".join(row)))
            for thr in (YAWN_THR, 0.50):
                row = []
                for G in (0.0, 0.2, 0.5, 1.0):
                    rs = runs_gap(ts, mar, lambda v, t=thr: v > t, G)
                    rs.sort(key=lambda x: -x[1])
                    row.append("G=%.1f→%s" % (G, ("%.2fs" % rs[0][1]) if rs else "无"))
                print("        > %.2f 最长一段（G = 容忍的丢脸秒数）：%s"
                      % (thr, "  ".join(row)))

    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
