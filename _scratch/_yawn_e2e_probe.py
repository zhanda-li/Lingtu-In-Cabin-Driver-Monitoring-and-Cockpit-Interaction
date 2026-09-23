"""哈欠规则：离线标定说 5/5，端到端回放却漏了一个。到底是哪一段不一致？

`tools/replay_fuse.py` 在 yawn_open_01 上报「哈欠没触发」，而
`tools/calib_yawn.py` 在 `_ear_raw.npz` 上说 5/5 全中。同一批视频、
同一套 `runs_sec`，所以差异只可能出在**喂进去的 MAR 序列**上。

三种可能的来源，本探针把它们并排量出来：

  A. `_ear_raw.npz` 里存的 MAR（离线标定用的那个）
  B. 现在用 `src/face.py` 的 `FaceExtractor` 重新跑一遍同一段 mp4 的 MAR
  C. B 再走 `FaceBranch` 的 push/裁剪规则（按时间裁到 HIST_SEC）

A vs B：说明 npz 是怎么造出来的 —— 如果当初不是用正式 `FaceExtractor`
        （比如换了 running_mode、换了缩放、或者每 N 帧抽一帧），那离线
        标定和现场跑的根本不是同一个量，标定值就不能拿来当现场依据。
B vs C：说明缓冲裁剪有没有吃掉哈欠的起点（哈欠长 3 秒，缓冲 27 秒，
        不该吃 —— 但如果 C 比 B 短，就是 `FaceBranch` 的 bug）。

用法：
    python _scratch/_yawn_e2e_probe.py --cls yawn_open
    python _scratch/_yawn_e2e_probe.py --cls yawn_open --clip yawn_open_01
"""
import argparse
import os
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from face import (HIST_SEC, YAWN_MIN, YAWN_THR, FaceBranch,  # noqa: E402
                  FaceExtractor, runs_sec)

CACHE = ROOT / "_scratch" / "_ear_raw.npz"


def longest(ts, mar):
    """最长连续 MAR > YAWN_THR 的真实秒数（与 face.yawn_seconds 同口径）。"""
    seg = runs_sec(np.asarray(ts, float), np.asarray(mar, float),
                   lambda v: v > YAWN_THR)
    return max(seg) if seg else 0.0


def from_npz(z, clip):
    """npz 里字段是**分开存的**（`<key>|ear` / `|t` / `|mar` / `|euler`），
    不是一张矩阵 —— 见 `face.clip_features` 的 `g()`。第一版按矩阵第 2 列取
    mar，那是猜的列序，取出来的是别的量。"""
    key = f"{clip.parent.name}|{clip.stem}"
    def g(f):
        k = f"{key}|{f}"
        return z[k].astype(float) if k in z.files else None
    ts, mar = g("t"), g("mar")
    if ts is None or mar is None:
        return None
    ok = np.isfinite(ts) & np.isfinite(mar)
    return ts[ok], mar[ok]


def from_video(path, fb, t_base):
    """跑一遍 mp4。`fb` 由调用方给（复用同一个 FaceExtractor —— 每建一个
    实例析构就是固定 42 秒），`t_base` 是本段的起始时间**秒**偏移。

    ⚠️ 每段必须给不同的 t_base，而且不能从头算 0：`FaceExtractor._last_ts`
    是全进程单调的（跨视频**不**重置，这是对的），如果每段都从 0 开始，
    第二段以后的 ts 全都会被守卫推到 `_last_ts+1` 毫秒 —— 整段的秒数被压扁，
    哈欠的 3 秒就变成 3 毫秒级的东西，`runs_sec` 什么都测不到。
    """
    cap = cv2.VideoCapture(str(path))
    ts, mar = [], []
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        mt = t_base + i / 15.0             # 名义 15 fps，与抽取脚本一致
        g = fb.detect(frame, int(mt * 1000))
        if g is not None:
            ts.append(mt)
            mar.append(g["mar"])
        i += 1
    cap.release()
    return np.array(ts), np.array(mar)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cls", default="yawn_open")
    ap.add_argument("--clip", default=None)
    ap.add_argument("--data", default=None)
    args = ap.parse_args()

    raw = Path(args.data) if args.data else (ROOT / "data" / "raw")
    clips = sorted(raw.glob(f"{args.cls}/*.mp4"))
    if args.clip:
        clips = [c for c in clips if c.stem == args.clip]
    if not clips:
        raise SystemExit("没找到片段")
    z = np.load(CACHE, allow_pickle=True)

    print(f"YAWN_THR={YAWN_THR}  YAWN_MIN={YAWN_MIN}  HIST_SEC={HIST_SEC}\n")
    print(f"{'片段':<16}{'A npz':>9}{'B 重跑':>9}{'C 过缓冲':>10}"
          f"{'A帧数':>8}{'B帧数':>8}   A/B   B/C")
    print("-" * 74)
    fb = FaceExtractor()          # 只建一个；析构固定 42 秒，别关它，靠 os._exit
    for idx, clip in enumerate(clips):
        a = from_npz(z, clip)
        A = longest(a[0], a[1]) if a else float("nan")
        na = len(a[0]) if a else 0
        # 每段给 1000 秒的时间偏移，避开 _last_ts 的单调守卫（见 from_video）
        ts, mar = from_video(clip, fb, t_base=1000.0 * idx)
        B = longest(ts, mar)
        br = FaceBranch()
        for k in range(len(ts)):
            br.push(ts[k], np.nan, mar[k], np.nan)   # 只判哈欠，ear/pitch 用不上
        bt, _, bm, _ = br.arrays() if len(br.buf) else (np.zeros(0),) * 4
        C = longest(bt, bm) if len(bt) > 2 else float("nan")
        flag = ("  ✅" if min(B, C) >= YAWN_MIN else "  ❌")
        print(f"{clip.stem:<16}{A:>9.2f}{B:>9.2f}{C:>10.2f}{na:>8}{len(ts):>8}"
              f"{'  A<MIN' if A < YAWN_MIN else '      '}"
              f"{'  B<MIN' if B < YAWN_MIN else '      '}{flag}")
    print("\nA = _ear_raw.npz 里存的（离线标定用的）")
    print("B = 现在用 src/face.py FaceExtractor 重跑同一段 mp4")
    print("C = B 再走 FaceBranch 的时间裁剪 + window/缓冲规则")
    print("A 与 B 差得多 → 离线标定和现场跑的**不是同一个量**，标定值不能当现场依据")
    print("B 与 C 差得多 → FaceBranch 的裁剪吃掉了哈欠")
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
