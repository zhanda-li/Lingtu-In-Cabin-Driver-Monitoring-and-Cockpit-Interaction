"""支路二实时观察器 —— 摄像头直出，看眼睛和嘴到底在说什么。

为什么要它：probe_b2.py 是离线的，跑完只给一个 71.4%，看不到"为什么"。
而支路二现在卡在一件事上 —— 那 71.4% 到底来自**眼睛**还是来自**头动**。
这个必须能一边做一边看，才知道闭眼时 PERCLOS 涨没涨、头动范围动没动。

屏上刻意把两个量并排显示：
    PERCLOS      眼睛指标的读数
    HEAD dPITCH  同期头动了多少   ← **对照量，判决全靠它**
闭眼时如果 PERCLOS 涨而 dPITCH 纹丝不动 → EAR 真在测眼睛，支路二活。
两者一起涨 → 又是头动的影子，支路二没救。

**2026-09-23 起，几何量/归一化/统计量全部搬到了 `src/face.py`，本文件 import 它们。**
搬的理由是 `src/fuse.py` 要同进程跑两条支路，而它**不能 import `_scratch/`**：
这份文件的最后一行是裸的 `main()`，import 就会开摄像头。既然要搬一份出去，
就干脆只留一份 —— 探针和主程序分头写特征函数，是"离线 65.7%、现场一坐上去
全错"这类静默降级的标准配方。

所以这里现在只保留**探针专属**的东西：空格标记、`analyze()` 判决、逐帧 CSV、
曲线与面板绘制。数学一行都不在这了。

模型仍然**当场从 `_ear_raw.npz` 拟合、不落盘**（`tools/fit_branch2.py` 才负责
产出 `models/branch2_lr.npz` 给主程序用）。留着这条独立路径是有意的：
它能在没有权重文件的情况下照样跑，而且用同一套 `face.clip_features`，
所以两边算出来的特征必然一致。

用法：
    python _scratch/live_face.py
    python _scratch/live_face.py --cam 0
    python _scratch/live_face.py --selftest    # 不开摄像头，只验模型那一半
    python _scratch/live_face.py --reanalyze _scratch/_face_live_20260922_235417.csv

按键：q / ESC 退出

⚠️ 归一化的坑（照抄 probe_b2.py 会中招），这段历史留在 `src/face.py` 的
`norm_by_time` docstring 里：probe_b2.py 用的是**居中**窗口 [t-5s, t+5s]，
实时没有"未来"，它在当前时刻会退化成**尾随 5 秒** —— 闭眼 3 秒就占满
5 秒窗的 60%，中位数直接翻到闭眼水平，基线一塌，而且失真方向是
"闭眼时假装一切正常"，正好把要验的东西抹掉。所以必须是**尾随 10 秒**，
且基线取 **p75 而不是中位**（中位是自我抑制的：闭得越多越读不出来）。
"""
import argparse
import os
import sys
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import config as C

import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

CACHE = ROOT / "_scratch" / "_ear_raw.npz"
FACE_TASK = C.MODELS_DIR / "face_landmarker.task"

# ── 以下全部来自 src/face.py，探针不再自己写一份 ─────────────────────
# 常量与几何量、归一化、秒数计段、逐段特征、实时缓冲。
# `points` 就是原来本地的 `_pts`（同名同义，换了个名字）。
sys.path.insert(0, str(ROOT / "src"))
from face import (BLINK_THR, FEATURE_NAMES, NEED, ROLL_WIN,  # noqa: E402
                  YAWN_MIN, YAWN_THR, YAWN_WIN, FaceBranch, clip_features, ear_of,
                  euler_of, feature_vector, mar_of, norm_by_time, points,
                  runs_sec, yawn_plateau, yawn_seconds)
# 注：NOD_DROP / NOD_MIN 不再需要 import —— 摇头次数现在由 face._features
# 在里面算，探针只从窗口统计量里读。探针里已经不剩任何"特征口径"的常量了，
# 这正是这次重构要达到的状态。

FPS = float(C.TARGET_FPS)        # 只用于**显示**（曲线长度、启动提示）
# 探针专属常量。凡是特征口径的量都不在这里了 —— 那必须只有一份。
YAWN_MIN_SPAN = YAWN_MIN + 0.5    # 缓冲区至少这么长才去判哈欠
CURVE_SEC = 20.0                  # 曲线显示多长

# 探针当场拟合模型用的特征列。**刻意用与 models/branch2_lr.npz 相同的
# `face.FEATURE_NAMES`**，而不是历史上那个含 YAWN 的 4 列版本：
# 那第 4 列的系数恒为 0.000（96 段训练片段上它是常数，见 src/face.py 的
# FEATURE_NAMES 注释），所以 3 列与 4 列**预测完全相同**，而 3 列
# 让探针显示的就是主程序实际在跑的那个模型。
PROBE_FEATS = tuple(FEATURE_NAMES)


# ── 离线：从缓存拟合模型（探针自己的路径，独立于 models/branch2_lr.npz）──
# ⚠️ 这里**只**重复了"拟合"那十几行，没有重复特征定义 —— 后者走
# `face.clip_features`，是危险的那一半。产出权威权重的是 tools/fit_branch2.py；
# 本函数存在的意义是"没有权重文件时探针照样能跑"。
def fit_model():
    z = np.load(CACHE, allow_pickle=True)
    keys = sorted({k.rsplit("|", 1)[0] for k in z.files})
    X, y = [], []
    for g in ("normal", "glance", "phone", "fatigue"):
        for k in [k for k in keys if k.startswith(g + "|")]:
            f, _why = clip_features(z, k, need=PROBE_FEATS)
            if f is None:
                continue
            X.append(f)
            y.append(1 if g == "fatigue" else 0)
    X, y = np.array(X, float), np.array(y, int)
    m = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=2000))
    m.fit(X, y)
    bal = loo_bal(X, y)
    coef = m[1].coef_[0].copy()
    return m, bal, coef, len(y), int(y.sum())


def loo_bal(X, y, C_=1.0):
    """留一片段预测。**按片段留出**，不是按窗口随机分（见 config.SPLIT_RATIO）。"""
    pred = np.zeros(len(y), dtype=int)
    for i in range(len(y)):
        tr = np.arange(len(y)) != i
        m = make_pipeline(StandardScaler(),
                          LogisticRegression(C=C_, max_iter=2000))
        m.fit(X[tr], y[tr])
        pred[i] = m.predict(X[[i]])[0]
    rec = (pred[y == 1] == 1).mean() if (y == 1).any() else np.nan
    spe = (pred[y == 0] == 0).mean() if (y == 0).any() else np.nan
    return 0.5 * (rec + spe)


# ── 画 ────────────────────────────────────────────────────────────────
def panel(img, lines, x, y, fs=0.58, lh=27):
    """半透明底 + 多行文字。cv2 画不了中文，全部 ASCII。"""
    tw = max(cv2.getTextSize(t, cv2.FONT_HERSHEY_SIMPLEX, fs, 1)[0][0]
             for t, _ in lines)
    w, h = tw + 26, lh * len(lines) + 18
    sub = img[y:y + h, x:x + w]
    if sub.size:
        sub[:] = (sub * 0.22).astype(sub.dtype)
    yy = y + lh
    for t, col in lines:
        cv2.putText(img, t, (x + 13, yy), cv2.FONT_HERSHEY_SIMPLEX, fs,
                    (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(img, t, (x + 13, yy), cv2.FONT_HERSHEY_SIMPLEX, fs,
                    col, 1, cv2.LINE_AA)
        yy += lh


def draw_curve(img, hist, thr, x0, y0, w, h):
    """hist 是最新在右的 EAR_norm 序列。"""
    cv2.rectangle(img, (x0, y0), (x0 + w, y0 + h), (28, 28, 28), -1)
    vmin, vmax = 0.40, 1.30

    def py(v):
        f = (np.clip(v, vmin, vmax) - vmin) / (vmax - vmin)
        return int(y0 + h - f * h)

    ythr = py(thr)
    cv2.line(img, (x0, ythr), (x0 + w, ythr), (0, 170, 255), 1, cv2.LINE_AA)
    cv2.putText(img, f"thr {thr:.2f}", (x0 + 8, ythr - 7),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 170, 255), 1, cv2.LINE_AA)
    cv2.putText(img, "EAR_norm  (last 20 s)", (x0 + 8, y0 + 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (190, 190, 190), 1, cv2.LINE_AA)

    N = max(1, int(CURVE_SEC * FPS))
    a = list(hist)[-N:]
    off = N - len(a)
    prev = None
    for i, v in enumerate(a):
        if not np.isfinite(v):
            prev = None
            continue
        p = (x0 + int(w * (off + i + 1) / N), py(v))
        if prev is not None:
            col = (90, 90, 255) if v < thr else (90, 240, 90)
            cv2.line(img, prev, p, col, 2, cv2.LINE_AA)
        prev = p


def analyze(path_csv, path_png, win_thr="time"):
    """会话结束后的判决 —— 就是 probe_b2 的 D1/D2，只是数据换成一段实时会话。

    判法：把整段按 5 秒滑窗切开，每个窗算两个量：
        头动范围 = 窗内 pitch 的 p95-p5
        PERCLOS  = 窗内归一化 EAR 低于阈值的帧占比
    然后看**头不动的那些窗**里 PERCLOS 能不能上去。

    这是整件事的关键：离线那 26 段疲劳素材头动全 >10°，所以分不开。
    如果一段实时会话里能出现「头动很小 而 PERCLOS 很高」的窗，
    就说明 EAR 确实在测眼睛，而不是头动的影子。
    """
    a = np.genfromtxt(path_csv, delimiter=",", names=True)
    if a.size == 0:
        print("日志是空的，没得分析。")
        return
    # ⚠️ 从原始 ear **重算** en，不能用 CSV 里那一列 ——
    # 那一列是录制当时按当时的归一化算的。不重算的话，改了方法再
    # --reanalyze 会拿着旧结果打新结论，等于白改。
    t, ear, pitch, mark = a["t"], a["ear"], a["pitch"], a["mark"]
    ok = np.isfinite(ear) & np.isfinite(pitch)
    t, ear, pitch, mark = t[ok], ear[ok], pitch[ok], mark[ok]
    en = ear / np.maximum(norm_by_time(t, ear, ROLL_WIN), 1e-6)
    # 判据一律用**真实秒数**。按帧数除以 15 会把 10 fps 的会话算短 1.5 倍 ——
    # 这个坑在上面实时窗那里刚踩过一次，别在分析里再踩一遍
    dur = float(t[-1] - t[0])
    if dur < 10.0:
        print(f"有效数据只有 {dur:.1f} s，太短（要 ≥10 s，且不含前 10 秒预热）。")
        print("跑一次至少 25 秒。")
        return
    print("\n" + "=" * 62)
    print(f"会话判决   {dur:.1f} s   有效帧 {len(t)}   "
          f"实测 {len(t)/dur:.1f} fps")

    # ── 5 秒滑窗（四个量在同一个循环里算，保证逐窗对齐） ──────────────
    # ⚠️ D7：这里原本是 `if s.sum() < int(W * FPS * 0.6)`，FPS 是**名义** 15。
    #    阈值 45 帧 / 5 秒 = 9 fps，而这段会话实测只有 6.3 fps、窗内帧数中位 41。
    #    647 个候选窗里它丢掉 345 个（其中 127 个是完全空的，那种本来就该丢，
    #    剩下 218 个有帧但不满 45），**而且丢得不随机**。
    #    实测（_scratch/_d7_probe.py 的【旧滤网偏向哪边】一节）：
    #        保留组 头动范围中位  4.2°   丢弃组 12.9°   r(帧数, 头动范围) = −0.45
    #        保留组 PERCLOS 中位 0.120   丢弃组 0.159  r(帧数, PERCLOS)  = +0.01
    #    即：滤网保留的是**头不动**的窗，而对 PERCLOS 本身几乎中立（+0.01）。
    #    这里我原先写的机制是反的（写成"保留头在动的窗"，见 _d7_probe.py 的更正）。
    #    方向反了结论反而更难看：下面【2】判的正是"头不动时 PERCLOS 上不上得去"，
    #    **而滤网也在按'头动不动'筛** —— 判据的分层变量和被筛掉的维度是同一个，
    #    【2】的分母被预先富集（不动窗占 110/302=36%，不筛时 131/520=25%）。
    #    按四种阈值排下来【2】的 PERCLOS 中位是 0.386/0.330/0.300/0.200，
    #    滤得越狠这个数越好看 —— 所以 0.386 是四个里最漂亮的一个，别当门面数。
    #    改成按**采样跨度**筛（与帧率无关）：窗内有效采样至少要覆盖窗长的 80%，
    #    也就是"中间没有大洞"。`--win-thr frames` 可以退回旧口径做对照。
    W, S = 5.0, 1.0
    p_ref = float(np.median(pitch))
    wr, wp, wn, wm = [], [], [], []   # 头动范围 / PERCLOS / 闭眼最长 / 窗中位姿态
    n_cand = n_drop = 0
    for st in np.arange(t[0], t[-1] - W, S):
        s = (t >= st) & (t < st + W)
        n_cand += 1
        if s.sum() < 5:
            n_drop += 1
            continue
        p, e, ts_ = pitch[s], en[s], t[s]
        if win_thr == "frames":
            keep = s.sum() >= int(W * FPS * 0.6)          # 旧口径，仅供对照
        elif win_thr == "none":
            keep = True
        else:
            keep = float(ts_[-1] - ts_[0]) >= 0.8 * W     # 默认：无大洞
        if not keep:
            n_drop += 1
            continue
        wr.append(float(np.percentile(p, 95) - np.percentile(p, 5)))
        wp.append(float(np.mean(e < BLINK_THR)))
        wn.append(max(runs_sec(ts_, e, lambda v: v < BLINK_THR) or [0.0]))
        wm.append(float(np.median(p)))
    wr, wp, wn, wm = (np.array(wr), np.array(wp), np.array(wn), np.array(wm))
    print(f"      滑窗口径 win_thr={win_thr}：候选 {n_cand} 个，"
          f"保留 {len(wr)}，丢弃 {n_drop}")
    if len(wr) < 4:
        print("滑窗太少，跳过。")
        return

    # 自我否证：整段 EAR_norm 和 pitch 的逐帧相关。
    # 离线那 95 段量到过 −0.56 —— 一段会话如果也是这个量级，它自己就作废了，
    # 不用等判决表：EAR 掉下去的时候头也在动，两件事分不开。
    r_ep = float(np.corrcoef(en, pitch)[0, 1])
    # 中性姿态基准 = **跳过开头 10 秒、且排除标记帧** 之后的 pitch 中位。
    # 两个坑都踩过，别再改回去：
    #   · 用"整段中位"不行 —— 一整段大部分时间低着头时，中位就是那个低头姿态，
    #     拿它当基准等于把"低头"当成"正常"，低头的窗全会被判成"在中位附近"
    #   · 用"开头 3 秒"也不行 —— 那正好是人在启动脚本、手还在键盘上的时候，
    #     实测开头 3 秒 pitch 14.1°，而看屏幕时只有 5.5°。
    #     开头几秒是最不中性的时刻，偏偏看起来最像"基准"
    h0 = (t > t[0] + 10.0) & (mark == 0)
    p_ref = (float(np.median(pitch[h0])) if h0.sum() > 30
             else float(np.median(pitch)))

    r_all = float(np.corrcoef(wp, wr)[0, 1])
    print(f"\n【0】自我否证：整段 r(EAR_norm, pitch) = {r_ep:+.2f}")
    # ⚠️ D2：这行文案原来是"开头 3 秒的 pitch 中位"，和上面代码正好相反 ——
    #    代码用的是**跳过开头 10 秒且排除标记帧**之后的中位。代码是对的，
    #    理由见上面那两条（开头几秒是人在启动脚本，最不中性）。文案跟着代码改。
    print(f"      中性姿态基准 = 跳过开头 10 s、排除标记帧后的 pitch 中位"
          f" = {p_ref:.1f}°")
    if abs(r_ep) >= 0.6:
        print("      ❌ 这个相关太高了 —— 这段会话的 EAR 基本在跟着头姿走，")
        print("         闭眼和低头分不开。**本次数据不能作为证据**，重录。")
    elif abs(r_ep) >= 0.35:
        print("      ⚠️ 中等相关，数据可疑 —— 只有空格标记过的片段算数。")
    else:
        print("      ✅ 相关低，EAR 不是头姿的影子。")

    print(f"\n【1】整段  r(PERCLOS, 头动范围) = {r_all:+.2f}   "
          f"（{len(wr)} 个 5 秒窗）")
    print(f"      PERCLOS 中位 {np.median(wp):.3f}   最高 {wp.max():.3f}")
    print(f"      头动范围 中位 {np.median(wr):.1f}°  最高 {wr.max():.1f}°")
    print("      离线那 95 段里这个 r 是 +0.61 —— 实时这一段如果也很高，")
    print("      说明 PERCLOS 还是跟着头走。")
    # 短闭眼（正常眨眼，0.1~0.3 s）有没有被看见 —— 这是 EAR 有没有响应的底线。
    # 一次都测不到就说明 EAR 根本没在动，后面所有讨论都没意义。
    n_short = int(np.sum((wn > 0.05) & (wn < 0.6)))
    print(f"      5 秒窗里出现过闭眼事件的窗：{n_short}/{len(wn)} 个"
          f"（正常眨眼约 11.6 次/分）")

    # ── 判决：头不动的窗里 PERCLOS 够不够高 ─────────────────────────
    # ⚠️ 只看"窗内 range 小"是不够的，这踩过一次坑：
    # 一段实测里，人把头**稳稳低着 22°** 保持了 5 秒 ——
    # 窗内 range 只有 4°，判据说"头不动"，于是把它算成了成功证据。
    # 但 EAR_norm 崩掉是因为低头本身（几何投影压扁了眼睑距离），不是闭眼。
    # 滚动中位也救不了：头是 1 秒内低下去的，10 秒尾随中位要 10 秒才吸收完，
    # 这 10 秒里基线还是旧的抬头基线，长得跟闭眼一模一样。
    # 所以必须**两条都满足**：窗内不怎么动，且头大致在它自己的中位姿态上。
    STILL, NEUT = 6.0, 5.0
    neutral = np.abs(wm - p_ref) < NEUT
    st_w = (wr < STILL) & neutral
    print(f"\n【2】头不动 **且在中位姿态附近** 的窗（{st_w.sum()}/{len(wr)} 个）")
    print(f"      判据：窗内 pitch 范围 < {STILL:.0f}° 且 |窗中位 pitch − "
          f"中性基准 {p_ref:.1f}°| < {NEUT:.0f}°")
    print("      光看「范围小」会中招：把头稳稳低着 20°+ 不动，"
          "窗内范围照样很小")
    if st_w.sum() == 0:
        print("      ❌ 一个都没有。整段要么头在动，要么头一直没回中位 ——")
        print("         这次证不了任何事。重来：坐正、头别动，只闭眼。")
    else:
        pw = wp[st_w]
        print(f"      PERCLOS 中位 {np.median(pw):.3f}   最高 {pw.max():.3f}")
        print(f"      闭眼最长段 中位 {np.median(wn[st_w]):.2f} s   "
              f"最高 {wn[st_w].max():.2f} s")
        # 先把"没做实验"和"实验失败"分开 —— 不然会把没闭眼读成 EAR 不灵
        if wn.max() < 1.5:
            print(f"      ⚠️ 整段没有超过 1.5 秒的闭眼事件（最长的只有 "
                  f"{wn.max():.2f} s）—— **这次协议没做**，结论无效。")
            print("         看图分清是哪种：闭眼时 EAR_norm 掉下去了 = 协议没做，")
            print("         补一次就行；纹丝不动 = EAR 没抓到，那才是坏消息。")
        elif pw.max() >= 0.25:
            print("      ✅ 头基本不动时 PERCLOS 也能上去 ——")
            print("         EAR 在测眼睛，不是在测头。支路二有救。")
            # ⚠️ 但这个中位数是被滑窗筛过一遍的，别当门面数报（D7）：
            #    本判决的分层变量是头动，而旧滤网也在按头动筛（r(帧数,头动)=−0.45），
            #    于是"头不动"这一层被预先富集。同一份数据按四种阈值排下来，
            #    这个中位是 0.386/0.330/0.300/0.200 —— 滤得越狠越好看。
            print(f"         注意这个中位是**筛过一轮**的（win_thr={win_thr}）："
                  f"四种阈值下它是 0.386/0.330/0.300/0.200，")
            print("         而滤网保留的正是头不动的窗（r(帧数,头动) = −0.45）。"
                  "要不吃筛子的结论，看【3】。")
        elif pw.max() >= 0.10:
            print("      ⚠️ 中间地带。头不动的窗里 PERCLOS 最高只有 "
                  f"{pw.max():.3f}，够不够要看闭眼有没有按协议做。")
        else:
            print("      ❌ 头不动时 PERCLOS 上不去。要么没真闭眼，要么")
            print("         归一化把闭眼当成了基线漂移 —— 支路二危险。")

    # ── 空格标记（可选，但最硬） ─────────────────────────────────────
    if mark.max() > 0:
        mk = mark > 0
        pc_m = float(np.mean(en[mk] < BLINK_THR))
        pc_u = float(np.mean(en[~mk] < BLINK_THR))
        hr_m = (float(np.percentile(pitch[mk], 95) - np.percentile(pitch[mk], 5))
                if mk.sum() > 15 else float("nan"))
        # ⚠️ D6：原来是 `mk.sum()/FPS`，除以**名义** 15 fps。这段会话实测 6.3 fps，
        #    于是 44.6 秒的标记被报成 29.8 秒。帧率会漂，绝不能除以常数 ——
        #    和 runs_sec 那条一样（见 src/face.py）。按真实秒数算，并数出段数。
        mk_seg = runs_sec(t, mark.astype(float), lambda v: v > 0)
        mk_sec = float(sum(mk_seg))
        print(f"\n【3】按空格标记的「我在闭眼」共 {mk_sec:.1f} s"
              f"（{len(mk_seg)} 段，{mk.sum()} 帧 / 实测 {len(t)/dur:.1f} fps）")
        print(f"      标记期   PERCLOS {pc_m:.3f}   头动范围 {hr_m:.1f}°")
        print(f"      未标记期 PERCLOS {pc_u:.3f}")
        print(f"      → 标记期 PERCLOS 高出 {pc_m/max(pc_u,1e-6):.1f} 倍，"
              f"而头动范围只有 {hr_m:.1f}°")
        if pc_m > 0.5 and hr_m < 8:
            print("      ✅ 闭眼时 PERCLOS 高、头没动 —— 这一条最硬，支路二成立。")
        elif pc_m <= pc_u * 1.3:
            print("      ❌ 闭眼时 PERCLOS 没比睁眼高多少 —— EAR 没抓到闭眼。")
        else:
            # ⚠️ D1：原来这里**没有 else**，两个条件都不满足时静默通过。
            #    2026-09-22 那场会话正好落进这条缝：pc_m=0.694 > 0.5 成立，
            #    但 hr_m=8.2 < 8 差 0.2° 不成立，pc_m <= pc_u*1.3 也不成立 ——
            #    整场会话最硬的一条证据，判决是空的。
            print(f"      ⚠️ 中间地带 —— **不静默通过**：PERCLOS 确实抬起来了"
                  f"（{pc_m:.3f} vs 未标记 {pc_u:.3f}，"
                  f"{pc_m/max(pc_u,1e-6):.1f} 倍），")
            print(f"         但标记期头动 {hr_m:.1f}° 越过了 8° 这条线。")
            print("         注意那条 8° 是**拍的，不是标定的** —— 8.2° 和 7.9° "
                  "没有任何实质区别，")
            print("         而 0.694 vs 0.193 这个 3.6 倍的差距不需要给头动设线。")
            print("         结论立在不带阈值的那个比较上；"
                  "要收紧就把头动判据改成标定的。")

    # ── 图 ────────────────────────────────────────────────────────────
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(3, 1, figsize=(12, 8), sharex=True)
    ax[0].plot(t, en, lw=0.8)
    ax[0].axhline(BLINK_THR, color="orange", ls="--", lw=1,
                  label=f"thr {BLINK_THR}")
    ax[0].set_ylabel("EAR_norm")
    ax[0].legend(loc="upper right", fontsize=8)
    ax[1].plot(t, pitch, lw=0.8, color="green")
    ax[1].set_ylabel("pitch (deg)")
    ax[1].set_title("HEAD POSE - the control variable", fontsize=9)
    #    判据挂在**滚动均值**上（2026-09-26 起），所以这条阈值线必须配着那条曲线看：
    #    画在单帧 MAR 上的话，真人一眼看到自己的 MAR 一直在 0.55 以下，会以为
    #    哈欠判据坏了 —— 这正是本项目最忌讳的那种"图在撒谎"。
    _yp = yawn_plateau(t, a["mar"])
    ax[2].plot(t, a["mar"][ok], lw=0.8, color="purple", alpha=0.45,
               label="MAR (单帧)")
    ax[2].plot(t, _yp, lw=1.2, color="purple", label=f"滚动均值 {YAWN_WIN}s")
    ax[2].axhline(YAWN_THR, color="red", ls="--", lw=1,
                  label=f"yawn 判据 {YAWN_THR}（比这条线）")
    ax[2].set_ylabel("MAR")
    ax[2].legend(loc="upper right", fontsize=8)
    ax[2].set_xlabel("time (s)")
    if mark.max() > 0:
        for x in ax:
            x.fill_between(t, *x.get_ylim(), where=mark > 0, alpha=0.12,
                           color="blue")
    fig.suptitle("branch2 live session  (blue = space-marked)", fontsize=10)
    fig.tight_layout()
    fig.savefig(path_png, dpi=110)
    print(f"\n图存到 {path_png}")
    print("=" * 62)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cam", type=int, default=0)
    ap.add_argument("--size", default="1280x720")
    ap.add_argument("--selftest", action="store_true",
                    help="不开摄像头，只验模型那一半")
    ap.add_argument("--test-secs", type=float, default=0.0,
                    help="开摄像头跑这么多秒就退出（冒烟测试）")
    ap.add_argument("--no-display", action="store_true")
    ap.add_argument("--log", default=None,
                    help="逐帧 CSV 路径，默认 _scratch/_face_live_<时间>.csv")
    ap.add_argument("--no-log", action="store_true")
    ap.add_argument("--reanalyze", default=None, metavar="CSV",
                    help="不开摄像头，拿之前存下的日志重跑判决")
    ap.add_argument("--win-thr", default="time", choices=("time", "frames", "none"),
                    help="滑窗的有效性判据：time=窗内跨度>=80%%（默认）；"
                         "frames=旧口径，按**名义**15fps 要求>=45帧；none=不筛")
    args = ap.parse_args()

    if args.reanalyze:
        p = Path(args.reanalyze)
        analyze(p, p.with_suffix(".png"), args.win_thr)
        sys.stdout.flush()
        os._exit(0)
    W, H = (int(v) for v in args.size.lower().split("x"))

    print("拟合支路二模型（从 _ear_raw.npz 当场拟合，不落盘）...")
    model, bal, coef, n_clip, n_pos = fit_model()
    # 只列模型真正在用的那几列，顺序必须跟着 PROBE_FEATS 走 ——
    # 原来硬编码 4 个名字，而去掉哈欠后 coef 只有 3 个，会张冠李戴。
    fn = [{"perclos": "PERCLOS", "brate": "BLINK/min", "nod": "NOD/min"}[k]
          for k in PROBE_FEATS]
    print(f"  训练片段 {n_clip}（疲劳 {n_pos}）   "
          f"留一验证 平衡准确率 {100*bal:.1f}%")
    print("  标准化系数：")
    for i in np.argsort(-np.abs(coef)):
        print(f"    {fn[i]:<10} {coef[i]:+.3f}")
    print(f"  ⚠️ 这个 {100*bal:.1f}% 和头动范围相关 0.6+，分不清是眼睛还是头动 ——")
    print("     这个数**不能**当作支路二有效的证据。真正算数的证据是：")
    print("     头不动时闭眼，PERCLOS 会不会涨（本次实时观察就是干这个的）。")

    if args.selftest:
        print("\n--selftest：不开摄像头，到此为止。")
        sys.stdout.flush()
        os._exit(0)

    cap = cv2.VideoCapture(args.cam, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, H)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    if not cap.isOpened():
        print(f"打不开摄像头 {args.cam}")
        os._exit(1)

    lmk = vision.FaceLandmarker.create_from_options(
        vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(FACE_TASK)),
            running_mode=vision.RunningMode.VIDEO, num_faces=1,
            output_face_blendshapes=False,
            output_facial_transformation_matrixes=True))

    # ── 逐帧日志 ─────────────────────────────────────────────────────
    # 实时屏只适合当场看，回头没法分析 —— 上一轮跑完 631 帧什么都没留下。
    # 存盘 + 退出时自动判决，才是这个工具真正的产出。
    log_path = None
    if not args.no_log:
        log_path = (Path(args.log) if args.log else
                    ROOT / "_scratch" /
                    f"_face_live_{time.strftime('%Y%m%d_%H%M%S')}.csv")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            "t,ear,en,mar,pitch,yaw,roll,perclos,brate,yawn,dpitch,prob,"
            "mark,face\n", encoding="utf-8")
    log_rows = []

    def flush_log():
        if not log_path or not log_rows:
            return
        with open(log_path, "a", encoding="utf-8") as f:
            for r in log_rows:
                f.write(",".join(
                    "" if (isinstance(v, float) and not np.isfinite(v))
                    else (f"{v:.5f}" if isinstance(v, float) else str(v))
                    for v in r) + "\n")
        log_rows.clear()

    print("\n" + "=" * 62)
    print("坐正，头别动，闭眼 2~3 秒再睁开，反复几次。")
    print("盯两行：PERCLOS 涨了，而 HEAD dPITCH 没动 → 支路二成立。")
    print("两者一起涨 → 又只是头动的影子。")
    print("【空格】闭眼时按一下做标记（可选，但判据最硬）")
    print("q / ESC 退出，退出时自动出判决。")
    print("=" * 62)

    # 支路二的实时缓冲交给 src/face.py 的 FaceBranch —— 探针里不再自己维护
    # deque 的裁剪规则。原来这里按**帧数**封顶（NBUF = 120*FPS），但帧率实测
    # 漂在 6~11，所谓"120 秒缓冲"实际是 100~200 秒；FaceBranch 按**时间**裁。
    fb = FaceBranch()
    curve = deque(maxlen=int(CURVE_SEC * FPS))
    t0 = time.perf_counter()
    last_ts, next_proc, fail = -1, 0.0, 0
    n_frames = 0        # 检测到人脸的帧
    n_proc = 0          # 处理过的帧
    mark_on = False     # 空格：标记"我现在闭着眼"（可选，判据最硬）

    while True:
        ok, frame = cap.read()
        if not ok:
            fail += 1
            if fail > 60:
                print("摄像头连续读不到帧，退出")
                break
            continue
        fail = 0
        now = time.perf_counter() - t0
        if now < next_proc:
            continue
        next_proc = now + 1.0 / FPS

        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        ts = int(now * 1000)
        if ts <= last_ts:
            ts = last_ts + 1
        last_ts = ts
        res = lmk.detect_for_video(
            mp.Image(image_format=mp.ImageFormat.SRGB,
                     data=np.ascontiguousarray(rgb)), ts)

        vis = frame
        ear = mar = pitch = yaw = roll = np.nan
        if res.face_landmarks:
            P = points(res.face_landmarks[0], w, h)
            ear, mar = ear_of(P), mar_of(P)
            if res.facial_transformation_matrixes:
                pitch, yaw, roll = euler_of(res.facial_transformation_matrixes[0])
            for j in NEED:
                cv2.circle(vis, tuple(np.int32(P[j])), 2, (0, 220, 255), -1)
            n_frames += 1

        # 四路装**同一个** deque（FaceBranch 内部的道理：分成三个 deque，某帧检不到
        # 脸就会错位，而闭眼时正好最容易丢帧）。没检到脸也塞 NaN，不跳过 ——
        # 跳过等于把"看不见"从统计里抹掉。
        fb.push(now, ear, mar, pitch)

        # ── 实时统计一律走 window_features，探针里不再自己算一遍 ──────────
        # 原来这段是自己拼的：PERCLOS 用「最近 10 秒的中位」做基线（而 offline /
        # analyze() 用的是 norm_by_time 的 **p75**），brate 除以真实窗长而
        # yawns / nods 除以常量 WIN_SEC/60 —— 一个窗里两种口径、两种基线。
        # 所以那次会话屏上看到的 EAR_norm 和现在 analyze() 复算出来的**不是同一个量**。
        # 现在两边共用 _features，唯一的差别只剩缓冲长度。
        st = fb.snapshot()
        warm = fb.ready()
        en_now = st["en_now"] if st else np.nan
        perclos = st["perclos"] if st else np.nan
        brate = st["brate"] if st else np.nan
        d100 = st["d_pitch"] if st else 0.0

        # 哈欠：MAR 持续张开（按真实秒数，不按帧数）
        # ⚠️ 2026-09-26：这里原来是**抄了一遍**单帧判据（`runs_sec(... v > YAWN_THR)`）。
        #   判据换成「1.5 s 滚动均值」之后，抄本就成了第二个口径 —— 屏上画的曲线
        #   （下面 ax[2] 的 axhline 还是单帧口径）跟这一行报的数会是两回事。
        #   所以这里改成直接调 `face.yawn_seconds`，口径只留一份在 src/face.py。
        yawn_s = 0.0
        if fb.span >= YAWN_MIN_SPAN:
            bt, _, bm, _ = fb.arrays()
            yawn_s = yawn_seconds(bt, bm)

        # LR 概率：只在 full() 时喂 —— 窗口整个落在缓冲里，基线才没被截断。
        # 早喂的代价不是报错，是概率整体偏低，然后你会以为模型不行。
        prob = np.nan
        if st is not None and fb.full() and all(np.isfinite(st[k])
                                                for k in PROBE_FEATS):
            fv = np.array([feature_vector(st, PROBE_FEATS)])
            prob = float(model.predict_proba(fv)[0, 1])

        if np.isfinite(en_now):
            curve.append(en_now)

        if log_path:
            log_rows.append((now, ear, en_now, mar, pitch, yaw, roll, perclos,
                             brate, yawn_s, d100, prob, 1 if mark_on else 0,
                             1 if np.isfinite(ear) else 0))
            if len(log_rows) >= 30:
                flush_log()

        lines = [
            ("BRANCH 2  FACE   [probe - math shared with src/face.py]" +
             ("          * MARK ON *" if mark_on else ""),
             (255, 120, 120) if mark_on else (255, 255, 255)),
        ]
        if warm:
            lines += [
                (f"EAR_norm    {en_now:6.3f}   thr {BLINK_THR:.2f}",
                 (90, 240, 90) if en_now >= BLINK_THR else (90, 90, 255)),
                (f"PERCLOS     {perclos:6.3f}", (0, 220, 255)),
                (f"BLINK/min   {brate:6.1f}", (0, 220, 255)),
                (f"YAWN        "
                 f"{'YES %.1fs' % yawn_s if yawn_s >= YAWN_MIN else '-':>6}",
                 (0, 120, 255) if yawn_s >= YAWN_MIN else (150, 150, 150)),
                (f"HEAD dPITCH {d100:6.1f} deg   <-- control", (90, 240, 90)),
                (f"LR P(fat)   {prob:6.3f}" if np.isfinite(prob) else
                 "LR P(fat)      -", (255, 200, 90)),
            ]
        else:
            lines.append((f"WARMING UP   {max(0.0, ROLL_WIN - fb.span):4.1f} s"
                          f"   (building baseline)", (150, 150, 150)))
        # 「基线够了」和「窗口整个落在缓冲里」是两件事，屏上必须分开显示 ——
        # 差这一级时 PERCLOS 已经画得出来，但还不能喂模型（见 face.FaceBranch）。
        if warm and not fb.full():
            lines.append((f"  need {fb.warm_left():4.1f} s more before "
                          f"P(fat) is valid", (150, 150, 150)))
        panel(vis, lines, 10, 10)
        draw_curve(vis, curve, BLINK_THR, 0, vis.shape[0] - 150, vis.shape[1], 150)

        if not np.isfinite(ear):
            cv2.putText(vis, "NO FACE", (12, H - 170),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2, cv2.LINE_AA)

        if not args.no_display:
            cv2.imshow("branch2 live", vis)
            k = cv2.waitKey(1) & 0xFF
            if k in (27, ord("q")):
                break
            if k == ord(" "):
                mark_on = not mark_on
                print(f"  标记 {'ON' if mark_on else 'OFF'}  t={now:.1f}s")
        n_proc += 1
        if args.test_secs and now >= args.test_secs:
            break

    cap.release()
    if not args.no_display:
        cv2.destroyAllWindows()
    print(f"\n处理 {n_proc} 帧 / 检测到人脸 {n_frames} 帧"
          f"（{100 * n_frames / max(1, n_proc):.1f}%）")
    flush_log()
    if log_path and log_path.exists():
        print(f"逐帧日志 {log_path}")
        try:
            analyze(log_path, log_path.with_suffix(".png"))
        except Exception as e:
            print(f"分析失败（数据已经存下来了）：{type(e).__name__}: {e}")
    sys.stdout.flush()
    # MediaPipe 析构固定 42 秒，必须 os._exit —— 见 memory/mediapipe-1x-notes
    os._exit(0)


main()
