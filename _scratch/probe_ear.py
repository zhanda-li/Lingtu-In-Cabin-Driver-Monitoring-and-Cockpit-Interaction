"""EAR / MAR 探针 —— 支路二的第一块砖，也是唯一的生死判定。

三个问题：

Q1  眼镜反光会不会把 EAR 毁掉？
    eyeLook* 已经死在反光上，EAR 用的是同一块眼区，必须先验。
    判法：EAR（几何量）和 eyeBlink（MediaPipe 预训练输出）对相关性。
    两者来源独立 —— 相关说明 EAR 真的在测眼睛；不相关说明它是噪声。

Q2  眨眼阈值定多少？
    不抄文献。正常眨眼频率是生理常识（15~20 次/分），拿它当标尺：
      某个阈值算出的频率落在 15~20   → 这个阈值对
      算出几百次                     → 太低（把噪声当眨眼）
      算出个位数                     → 太高（漏掉真眨眼）
    这样不用人工标眨眼就能定阈值。

Q3  MAR 能不能替代 jawOpen？
    昨晚哈欠那条路是用 jawOpen（blendshape）量的，结论是
    "哈欠最长张嘴 4.3~8.3 s，说话 0.5~1.1 s，完全不重叠"。MAR 是几何量，
    要确认它给出同样的分离度，昨晚的结论才能直接搬过来。

顺带量：闭眼时长分布（PERCLOS 要用）、头部欧拉角。

跑一次把原始序列缓存到 _ear_raw.npz，之后改分析不用重跑 FaceMesh。
不是正式工具，验完就删。
"""
import os
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import config as C

CACHE = ROOT / "_scratch" / "_ear_raw.npz"

# ── 关键点 ────────────────────────────────────────────────────────────
# 眼睑按 MediaPipe 眼环上的**对跖点**配对（环上相差 8 个点），不是随便挑的：
#   左眼环 33,7,163,144,145,153,154,155,133,246,161,160,159,158,157,173
#         33↔133 眼角，145↔159 / 144↔160 / 153↔158 是三对上下眼睑
#   右眼环 362,398,384,385,386,387,388,466,263,249,390,373,374,380,381,382
#         362↔263 眼角，386↔374 / 385↔373 / 387↔380 是三对上下眼睑
EYE = {
    "l": dict(corner=(33, 133),
              pairs=((145, 159), (144, 160), (153, 158))),
    "r": dict(corner=(362, 263),
              pairs=((386, 374), (385, 373), (387, 380))),
}
MOUTH = dict(corner=(61, 291), inner=(13, 14), outer=(12, 15))

NEED = sorted({*EYE["l"]["corner"], *[p for pr in EYE["l"]["pairs"] for p in pr],
               *EYE["r"]["corner"], *[p for pr in EYE["r"]["pairs"] for p in pr],
               *MOUTH["corner"], *MOUTH["inner"], *MOUTH["outer"]})

# 眨眼的"闭眼"参考线。文献常见值，这里只用来画参考，最终阈值由 Q2 定。
REF_THR = [0.15, 0.20, 0.25, 0.30]

GROUPS = {"normal": 27, "fatigue": 26, "yawn": 5, "talking": 5,
          "yawn_open": 5, "glance": 0, "phone": 0}


def _pts(lm, w, h):
    return {j: np.array([lm[j].x * w, lm[j].y * h]) for j in NEED}


def _d(P, a, b):
    return float(np.hypot(P[a][0] - P[b][0], P[a][1] - P[b][1]))


def ear_of(P):
    """EAR = 上下眼睑距离均值 / 内外眼角距离，双眼取平均。尺度无关。"""
    out = []
    for e in ("l", "r"):
        c1, c2 = EYE[e]["corner"]
        w = _d(P, c1, c2)
        if w < 1e-6:
            continue
        v = float(np.mean([_d(P, a, b) for a, b in EYE[e]["pairs"]]))
        out.append(v / w)
    return float(np.mean(out)) if out else np.nan


def mar_of(P):
    """MAR = 上下唇距离 / 嘴角距离。内外唇各一对取平均。"""
    c1, c2 = MOUTH["corner"]
    w = _d(P, c1, c2)
    if w < 1e-6:
        return np.nan
    v = 0.5 * (_d(P, *MOUTH["inner"]) + _d(P, *MOUTH["outer"]))
    return float(v / w)


def euler_of(M):
    """从 4x4 面部变换矩阵取头部欧拉角（度）。M: (4,4)"""
    R = np.asarray(M)[:3, :3]
    sy = np.hypot(R[0, 0], R[1, 0])
    return np.degrees([np.arctan2(R[2, 1], R[2, 2]),      # pitch
                       np.arctan2(-R[2, 0], sy),          # yaw
                       np.arctan2(R[1, 0], R[0, 0])])     # roll


def run(lmk, mp, video, ts_base):
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(fps / C.TARGET_FPS)))
    ear, mar, blk, jaw, t, eu = [], [], [], [], [], []
    n_read = k = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        i = n_read
        n_read += 1
        if i % step:
            continue
        k += 1
        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        res = lmk.detect_for_video(
            mp.Image(image_format=mp.ImageFormat.SRGB,
                     data=np.ascontiguousarray(rgb)),
            ts_base + int(k / C.TARGET_FPS * 1000))
        if not res.face_landmarks:
            continue
        P = _pts(res.face_landmarks[0], w, h)
        bs = ({c.category_name: c.score for c in res.face_blendshapes[0]}
              if res.face_blendshapes else {})
        ear.append(ear_of(P))
        mar.append(mar_of(P))
        blk.append(0.5 * (bs.get("eyeBlinkLeft", np.nan) +
                          bs.get("eyeBlinkRight", np.nan)))
        jaw.append(bs.get("jawOpen", np.nan))
        t.append(k / C.TARGET_FPS)
        if res.facial_transformation_matrixes:
            eu.append(euler_of(res.facial_transformation_matrixes[0]))
    cap.release()
    ts_next = ts_base + int(k / C.TARGET_FPS * 1000) + 1000
    d = dict(ear=ear, mar=mar, blk=blk, jaw=jaw, t=t)
    if eu:
        d["euler"] = np.array(eu)
    return d, ts_next


def runs_below(x, thr):
    """x < thr 的所有连续段长度（帧）"""
    out, cur = [], 0
    for v in x:
        if np.isfinite(v) and v < thr:
            cur += 1
        elif cur:
            out.append(cur)
            cur = 0
    if cur:
        out.append(cur)
    return out


def main():
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision

    lim = {}
    for kv in sys.argv[1:]:
        if "=" in kv:
            g, a = kv.split("=", 1)
            lim[g] = int(a)
    lim = {g: lim.get(g, GROUPS[g]) for g in GROUPS}

    # 缓存增量合并：每次只抽 lim 里 n>0 的组，其余沿用缓存，不用重跑
    z = {}
    if CACHE.exists() and "--fresh" not in sys.argv:
        old = np.load(CACHE, allow_pickle=True)
        z = {k: old[k] for k in old.files}
        print(f"[缓存] 载入 {len(z)} 条")

    todo = [g for g in lim if lim[g] > 0]
    if todo:
        lmk = vision.FaceLandmarker.create_from_options(
            vision.FaceLandmarkerOptions(
                base_options=mp_python.BaseOptions(
                    model_asset_path=str(C.MODELS_DIR / "face_landmarker.task")),
                running_mode=vision.RunningMode.VIDEO, num_faces=1,
                output_face_blendshapes=True,
                output_facial_transformation_matrixes=True))
        ts_base = 0
        for g in todo:
            vids = sorted((C.DATA_RAW / g).glob("*.mp4"))[:lim[g]]
            print(f"\n── {g}: {len(vids)} 段")
            for v in vids:
                d, ts_base = run(lmk, mp, v, ts_base)
                if len(d["ear"]) < 20:
                    print(f"   [skip] {v.stem} 有效帧 {len(d['ear'])}")
                    continue
                for f_, arr in d.items():
                    z[f"{g}|{v.stem}|{f_}"] = np.asarray(arr)
                r = float(np.corrcoef(d["ear"], d["blk"])[0, 1])
                print(f"   {v.stem:<18} 帧 {len(d['ear']):>4}"
                      f"  EAR {np.nanmin(d['ear']):.2f}~{np.nanmax(d['ear']):.2f}"
                      f"  r(EAR,blink) {r:+.2f}")
        np.savez_compressed(CACHE, **z)
        print(f"\n[缓存] 写入 {CACHE.name}（共 {len(z)} 条）")

    files = set(z)
    keys = sorted({k.rsplit("|", 1)[0] for k in files})
    print(f"\n共 {len(keys)} 段\n" + "=" * 74)

    def get(key, field):
        return z[f"{key}|{field}"] if f"{key}|{field}" in files else None

    # ── Q1 ────────────────────────────────────────────────────────────
    print("\n【Q1】EAR 是不是真的在测眼睛？（与 eyeBlink 的相关性）")
    print("      eyeBlink 是预训练模型输出，EAR 是几何量，来源独立。")
    print(f"\n{'片段':<20}{'帧':>5}{'r(EAR,blink)':>14}{'EAR最低':>9}"
          f"{'EAR最高':>9}{'量程p95-p5':>12}{'blink最高':>11}")
    print("-" * 80)
    rs, amps = [], []
    for key in keys:
        if not key.startswith("normal"):
            continue
        e, b = get(key, "ear"), get(key, "blk")
        r = float(np.corrcoef(e, b)[0, 1])
        amp = float(np.percentile(e, 95) - np.percentile(e, 5))
        rs.append(r)
        amps.append(amp)
        print(f"{key.split('|')[1]:<20}{len(e):>5}{r:>+14.2f}"
              f"{np.nanmin(e):>9.2f}{np.nanmax(e):>9.2f}{amp:>12.3f}"
              f"{np.nanmax(b):>11.2f}")
    if rs:
        med = float(np.median(rs))
        meda = float(np.median(amps))
        print(f"\n   中位 r = {med:+.2f}   中位量程 = {meda:.3f}")
        print("   ⚠️ 相关高 + 量程小 = 假的好看。两者必须一起看："
              "量程太小说明这段根本没闭眼，r 是在噪声上算的。")
        print("   →  " + ("✅ 相关强且量程够，EAR 有效" if med < -0.4 and meda > 0.08
                         else "⚠️ 量程只有 {:.3f}，看不出闭眼有没有被捕捉到，"
                              "要看下面的分布".format(meda) if med < -0.4
                         else "❌ 相关性弱，EAR 大概率被反光/噪声污染"))

    # ── 分布：EAR 到底是不是双峰 ──────────────────────────────────────
    print("\n\n【Q1b】EAR 分布（双峰 = 睁眼一簇、闭眼一簇 = 阈值分得开）")
    bins = np.arange(0.00, 0.62, 0.02)
    hs = {}
    for g in ("normal", "fatigue"):
        arr = [get(k, "ear") for k in keys if k.startswith(g + "|")]
        hs[g] = np.histogram(np.concatenate(arr), bins)[0] if arr else None
    mx = max([h.max() for h in hs.values() if h is not None] + [1])
    print(f"\n{'EAR':>6}   {'normal':<42}{'fatigue':<42}")
    print("-" * 92)
    for i in range(len(bins) - 1):
        n = hs["normal"][i] if hs["normal"] is not None else 0
        f = hs["fatigue"][i] if hs["fatigue"] is not None else 0
        if n == 0 and f == 0:
            continue
        print(f"{bins[i]:>6.2f}   |{'#'*int(34*n/mx):<34}{n:>7}   "
              f"|{'#'*int(34*f/mx):<34}{f:>7}")

    # ── Q2 ────────────────────────────────────────────────────────────
    print("\n\n【Q2】眨眼阈值定多少？（拿「正常眨眼 15~20 次/分」当标尺）")
    nev = [k for k in keys if k.startswith("normal")]
    allE = np.concatenate([get(k, "ear") for k in nev])
    nE = sum(len(get(k, "ear")) for k in nev)
    dur_all = sum(float(get(k, "t")[-1] - get(k, "t")[0]) for k in nev)
    q = np.percentile(allE, [1, 5, 10, 25, 50, 75, 95])
    print(f"\n   正常段 EAR 分位: p1 {q[0]:.3f} | p5 {q[1]:.3f} | p10 {q[2]:.3f}"
          f" | p25 {q[3]:.3f} | p50 {q[4]:.3f} | p75 {q[5]:.3f} | p95 {q[6]:.3f}")
    print(f"   总时长 {dur_all/60:.1f} 分钟，共 {nE} 帧")
    print(f"   生理参考：这段时间里应该出现 {15*dur_all/60:.0f}~"
          f"{20*dur_all/60:.0f} 次眨眼\n")

    print(f"{'阈值':>6}{'眨眼次数':>10}{'次/分':>9}{'时长中位(s)':>13}"
          f"{'最长(s)':>9}{'闭眼占比':>10}  判定")
    print("-" * 76)
    for thr in np.round(np.arange(0.20, max(0.30, q[4]), 0.02), 2):
        tot, durs, frames = 0, [], 0
        for key in nev:
            e = get(key, "ear")
            rr = runs_below(e, thr)
            tot += len(rr)
            durs += rr
            frames += int(np.sum(e < thr))
        per_min = tot / (dur_all / 60.0) if dur_all else 0
        lo_ok, hi_ok = 15 * dur_all / 60, 20 * dur_all / 60
        ok = "✅ 和生理值吻合" if lo_ok * 0.7 <= tot <= hi_ok * 1.4 else (
            "❌ 太少，漏掉真眨眼" if tot < lo_ok * 0.7 else "❌ 太多，把噪声当眨眼")
        print(f"{thr:>6.2f}{tot:>10}{per_min:>9.1f}"
              f"{(np.median(durs)/C.TARGET_FPS if durs else 0):>13.2f}"
              f"{(max(durs)/C.TARGET_FPS if durs else 0):>9.2f}"
              f"{100*frames/max(1, nE):>9.1f}%  {ok}")

    # ── Q3 ────────────────────────────────────────────────────────────
    print("\n\n【Q3】MAR 能不能替代 jawOpen？")
    print(f"\n{'片段':<20}{'r(MAR,jaw)':>12}{'MAR最高':>9}{'jaw最高':>9}"
          f"{'最长张嘴(s)':>13}{'最长jaw(s)':>12}")
    print("-" * 76)
    sep = {"yawn": [], "talking": []}
    for key in keys:
        g = key.split("|")[0]
        if g not in ("yawn", "talking", "yawn_open"):
            continue
        m, j, t = get(key, "mar"), get(key, "jaw"), get(key, "t")
        r = float(np.corrcoef(m, j)[0, 1])
        rm = max(runs_below(-m, -0.5) or [0])
        rj = max(runs_below(-j, -0.5) or [0])
        sep[g].append((rm / C.TARGET_FPS, rj / C.TARGET_FPS, float(np.nanmax(m))))
        print(f"{key.split('|')[1]:<20}{r:>+12.2f}{np.nanmax(m):>9.2f}"
              f"{np.nanmax(j):>9.2f}{rm/C.TARGET_FPS:>13.2f}{rj/C.TARGET_FPS:>12.2f}")
    # 正例要用**不捂嘴**的 yawn_open。yawn 那组是捂嘴的，几何量必然塌，
    # 拿它当正例 = 自己制造"分不开"的结论。
    pos = sep["yawn_open"] or sep["yawn"]
    pname = "yawn_open 不捂嘴" if sep["yawn_open"] else "yawn 捂嘴(仅对照)"
    if pos and sep["talking"]:
        ym = min(x[0] for x in pos)
        tm = max(x[0] for x in sep["talking"])
        print(f"\n   正例 = {pname}（{len(pos)} 段）")
        print(f"   MAR  最长张嘴: 哈欠最低 {ym:.2f}s vs 说话最高 {tm:.2f}s  →  "
              + ("✅ 分得开，昨晚 jawOpen 的结论能直接搬" if ym > tm
                 else "❌ 重叠，MAR 和 jawOpen 不等价，要重新想"))
        yj = min(x[1] for x in pos)
        tj = max(x[1] for x in sep["talking"])
        print(f"   jaw  最长张嘴: 哈欠最低 {yj:.2f}s vs 说话最高 {tj:.2f}s  "
              f"（同一批段的 jawOpen 基线，对照用）")
    if sep["yawn"] and sep["yawn_open"]:
        print(f"\n   捂嘴 vs 不捂嘴（同一批人、同一晚）：")
        print(f"     捂嘴   MAR 峰值中位 {np.median([x[2] for x in sep['yawn']]):.2f}"
              f"   最长张嘴中位 {np.median([x[0] for x in sep['yawn']]):.2f}s")
        print(f"     不捂嘴 MAR 峰值中位 {np.median([x[2] for x in sep['yawn_open']]):.2f}"
              f"   最长张嘴中位 {np.median([x[0] for x in sep['yawn_open']]):.2f}s")

    # ── Q4 ────────────────────────────────────────────────────────────
    print("\n\n【Q4】最长闭眼时长（PERCLOS 用）")
    print(f"\n{'组':<10}{'段数':>6}{'闭眼>0.20最长(s)':>18}{'中位(s)':>10}")
    print("-" * 46)
    for g in ("normal", "fatigue", "yawn", "talking"):
        best = []
        for key in keys:
            if not key.startswith(g + "|"):
                continue
            e = get(key, "ear")
            best.append(max(runs_below(e, 0.20) or [0]) / C.TARGET_FPS)
        if best:
            print(f"{g:<10}{len(best):>6}{max(best):>18.2f}"
                  f"{np.median(best):>10.2f}")

    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
