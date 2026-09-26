# -*- coding: utf-8 -*-
"""唤醒词自测：喂 wav，看「你好，小瑞」到底叫不叫得醒。

    python _scratch/_check_wake.py                 # 全部样本
    python _scratch/_check_wake.py --nb 2          # 换个 num_trailing_blanks 再跑

两组样本，缺一不可：

  A 自己合成的（`_scratch/_make_wake_wavs.py`，SAPI 离线）
      pos_*  说了唤醒词 —— **必须叫醒**
      neg_*  没说到 —— **必须不叫醒**。反样本才是唤醒词真正难的地方：
             「你好，**小心**前面那辆车」和「你好，**小瑞**」差一个韵母，
             只看正样本的话，一个"永远返回命中"的实现也能全过。

  B 模型自带的 `test_wavs/*.wav` —— **真人录音**（包里附的关键词是
    小爱同学/女儿/法国…，都不是我们的词）。用来量**误唤醒**：SAPI 合成音
    干净得像实验室，真人说话带口音、语速、连读，才是真实工况。

判据是**读回来的命中**，不是"跑通了"：每一行都打出"第几毫秒叫醒的"和
"每 100 ms 一帧解了多久"（后者就是常听要占的 CPU）。
"""
import argparse
import glob
import os
import sys
import time
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ui"))
sys.path.insert(0, str(ROOT / "ui" / "voice"))

import asr                                    # noqa: E402  只借它的 wav 解析
from kws import WakeWord, SR                  # noqa: E402

CHUNK = 1600                                  # 100 ms，和线上一样的喂法
FAILS = []


def check(ok, msg, detail=""):
    print("  %s %s%s" % ("✅" if ok else "❌", msg, ("  <- " + detail) if detail else ""))
    if not ok:
        FAILS.append(msg)
    return ok


def feed_wav(w: WakeWord, path: str):
    """把一段 wav 按 100 ms 喂进去，返回 (命中的词, 第几毫秒命中, 每帧毫秒)。"""
    blob = open(path, "rb").read()
    x = asr.wav_bytes_to_float32(blob, want_sr=SR)
    hits, at, t_frame = [], None, []
    for i in range(0, len(x), CHUNK):
        t0 = time.perf_counter()
        for d in w.feed(x[i:i + CHUNK]):
            hits.append(d)
            if at is None:
                at = (i + CHUNK) / SR * 1000.0     # 命中发生在这一帧的末尾
        t_frame.append((time.perf_counter() - t0) * 1000.0)
    per = sum(t_frame) / max(len(t_frame), 1)
    return hits, at, per, len(x) / SR


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nb", type=int, default=None, help="num_trailing_blanks")
    ap.add_argument("--th", type=float, default=None, help="keywords_threshold")
    ap.add_argument("--only", default="", help="只跑名字里含这个字的样本")
    a = ap.parse_args()

    cfg = {}
    if a.nb is not None:
        cfg["num_trailing_blanks"] = a.nb
    if a.th is not None:
        cfg["keywords_threshold"] = a.th

    # ⚠️ 建实例前先量一次启动耗时 —— 这个数会出现在"常听占多少"的说法里
    t0 = time.perf_counter()
    w = WakeWord(cfg)
    boot_ms = (time.perf_counter() - t0) * 1000
    print("=" * 76)
    print("唤醒词自测：%s" % ("、".join(w.keywords) or "（没有唤醒词！）"))
    print("  模型      %s" % (w.model_dir.name if w.model_dir else "（没找到）"))
    print("  词表      %s" % w.keywords_file)
    print("  参数      num_trailing_blanks=%s  threshold=%s"
          % (w.cfg["num_trailing_blanks"], w.cfg["keywords_threshold"]))
    print("  加载耗时  %.0f ms" % boot_ms)
    print("=" * 76)
    if not w.ready:
        print("❌ 唤醒器不可用：%s" % w.why)
        return 1

    groups = []
    sdir = ROOT / "runs" / "wake_samples"
    if sdir.is_dir():
        groups.append(("A 自己合成的", sorted(glob.glob(str(sdir / "*.wav"))),
                       lambda p: os.path.basename(p).startswith("pos_")))
    tdir = w.model_dir / "test_wavs"
    if tdir.is_dir():
        groups.append(("B 模型自带真人录音（都不是我们的词）",
                       sorted(glob.glob(str(tdir / "*.wav"))), lambda p: False))

    total_frames_ms = []
    # ★ 分档统计：正样本的**唤醒率**和反样本的**误唤醒率**要分开算，而且反样本
    #   必须**按音频秒数**算一遍 —— "0/11" 里的 11 前面有 3 个是合成的短句，
    #   拿"11 个样本"当分母会让人以为验了很多，实际反样本只有几十秒音频。
    #   （车上的误唤醒率得用真人/真环境录一整天才有意义，这里给的只是**下界**。）
    stat = {}
    for title, files, is_pos in groups:
        print("\n" + "-" * 76)
        print(title)
        print("-" * 76)
        for p in files:
            name = os.path.basename(os.path.splitext(p)[0])
            if a.only and a.only not in name:
                continue
            # ⚠️ 每个样本之前清一次去抖：离线回放把时间压扁了，不清的话
            #    后面每个样本都落在上一个命中的 1 s 窗口里，全被吃掉
            #    （症状是"一整场只报第一个样本"，见 _scratch/_wake_reset.py）。
            w.clear_debounce()
            hits, at, per, dur = feed_wav(w, p)
            total_frames_ms.append(per)
            want = is_pos(p)
            d = stat.setdefault(("pos" if want else "neg", title[0]), [0, 0, 0.0])
            d[0] += 1                       # 样本数
            d[1] += 1 if hits else 0        # 命中的
            d[2] += dur                     # 音频秒数
            ok = bool(hits) == want
            print("  %s %-26s %5.2fs  命中=%-6s %s  解码 %.1f ms/帧"
                  % ("✅" if ok else "❌", name, dur,
                     ("%s @%.0fms" % (hits[0], at)) if hits else "没有",
                     "" if ok else ("!! 该叫醒却没叫醒" if want else "!! 误唤醒"),
                     per))
            if not ok:
                FAILS.append("%s（%s）" % (name, "漏唤醒" if want else "误唤醒"))

    print("\n" + "=" * 76)
    print("结论")
    print("=" * 76)
    # 唤醒率 / 误唤醒率。⚠️ 分母写清楚（几段音频、几秒音频）—— 这两个数**不能**
    # 单独拿出去当"车上也这样"：样本是合成的 + 一小段真人录音，见文件头。
    pos_n = sum(v[0] for k, v in stat.items() if k[0] == "pos")
    pos_hit = sum(v[1] for k, v in stat.items() if k[0] == "pos")
    neg_n = sum(v[0] for k, v in stat.items() if k[0] == "neg")
    neg_hit = sum(v[1] for k, v in stat.items() if k[0] == "neg")
    neg_s = sum(v[2] for k, v in stat.items() if k[0] == "neg")
    LABEL = {"A": "A 自己合成的", "B": "B 真人录音"}
    if pos_n:
        print("  唤醒率    %d/%d = %.0f%%（正样本：自己合成的，SAPI 离线）"
              % (pos_hit, pos_n, pos_hit / pos_n * 100))
    if neg_n:
        print("  误唤醒    %d/%d 段 = %.0f%%（反样本合计 %.0f 秒音频）"
              % (neg_hit, neg_n, neg_hit / neg_n * 100, neg_s))
        for k in sorted(stat):
            if k[0] == "neg":
                print("              %-14s %d 段 / %.0f 秒，命中 %d"
                      % (LABEL.get(k[1], k[1]), stat[k][0], stat[k][2], stat[k][1]))
        print("  ⚠️ 反样本只有 %.0f 秒，误唤醒率只是**下界**（0 次 ≠ 车里也不会"
              "误唤醒）；\n"
              "     车上的数要用真人/真环境录一整天才有意义。" % neg_s)
    if total_frames_ms:
        m = sum(total_frames_ms) / len(total_frames_ms)
        print("  每 100 ms 一帧的平均解码耗时 = %.2f ms  →  实时占比约 %.1f%%（单核）"
              % (m, m / 100.0 * 100))
        print("  （这就是「常听」的代价：%.1f%% 的一颗核，一直开着。）" % (m / 100.0 * 100))
    print("  加载耗时 %.0f ms，模型 3.3 MB，全程离线。" % boot_ms)
    if FAILS:
        print("\n  ❌ %d 条不对：" % len(FAILS))
        for f in FAILS:
            print("     · %s" % f)
        print("\n  调参提示：漏唤醒 → 降 keywords_threshold（或加个近似词）；"
              "\n            误唤醒 → 升 threshold，或把 num_trailing_blanks 从 1 加到 2。")
        return 1
    print("\n  ✅ 全对 —— 正样本都叫醒了，反样本（含真人录音）一个都没误唤醒。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
