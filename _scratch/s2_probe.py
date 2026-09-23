# session2 专项：护栏为什么还是超了 0.70？
# protocol 是「闭眼 5 s、间隔 12 s」，那 10 s 窗里最多只该有 ~0.58。
# 逐段把 mark 的开合与间隔列出来，看是哪一段、哪一个原因。
import csv
import io
import sys

import numpy as np

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PATH = sys.argv[1] if len(sys.argv) > 1 else "runs/session2.csv"
ROLL_WIN = 10.0

rows = list(csv.DictReader(open(PATH, encoding="utf-8")))


def col(name):
    out = []
    for r in rows:
        v = r[name]
        out.append(float("nan") if v in ("-", "") else float(v))
    return np.array(out, dtype=float)


t = col("t")
mark = col("mark")
gate = col("gate")
en = col("en_now")
ear = col("ear")
perc = col("perclos")
pf = col("p_fat")
pitch = col("pitch")

# mark 是不是只有 0/1
u = np.unique(mark)
print("mark 取值：", u)

# ---- 逐段列 mark ----
print("\n======== mark 段（按下标切，标出真实秒数）========")
print("  #  起    止    时长   到下一段的间隔")
segs = []
i = 0
while i < len(mark):
    if mark[i] > 0.5:
        j = i
        while j + 1 < len(mark) and mark[j + 1] > 0.5:
            j += 1
        segs.append((i, j))
        i = j + 1
    else:
        i += 1

for k, (i, j) in enumerate(segs):
    dur = t[j] - t[i]
    gap = t[segs[k + 1][0]] - t[j] if k + 1 < len(segs) else float("nan")
    e_m = np.nanmedian(ear[i:j + 1])
    en_m = np.nanmedian(en[i:j + 1])
    print("{:3d}  {:5.1f} {:5.1f}  {:5.2f}   {:5.2f}      "
          "EAR原始 {:.3f}  en_now {:.3f}".format(
              k + 1, t[i], t[j], dur, gap, e_m, en_m))

# ---- 谁把 c 顶上去的 ----
print("\n======== 滑窗闭眼占比 c(t)，只打 >= 0.60 的拍 ========")
print("   t      c     落在哪个 mark 段")
worst = []
for k in range(len(t)):
    sel = (t >= t[k] - ROLL_WIN) & (t <= t[k])
    if not sel.any():
        continue
    c = float(mark[sel].mean())
    if c >= 0.60:
        worst.append((c, k))
worst.sort(reverse=True)
for c, k in worst[:12]:
    inside = [n + 1 for n, (i, j) in enumerate(segs) if i <= k <= j]
    print("  {:5.1f}  {:5.2f}   段 {}  (t 处 EAR 原始 {:.3f}  en_now {:.3f})".format(
        t[k], c, inside or "-", ear[k], en[k]))
if not worst:
    print("  （没有）")

# ---- 这个"闭眼占比"到底对应多少真实闭眼：用原始 EAR 反推 ----
# 睁眼参考 = 全场 EAR 的 p90（闭眼只占少数，p90 必然在睁眼区间）
ref_open = float(np.nanpercentile(ear, 90))
ref_closed = float(np.nanpercentile(ear, 5))
thr = ref_open - 0.35 * (ref_open - ref_closed)
eye_closed = ear < thr
print("\n======== 用原始 EAR 反推的真实闭眼占比（不靠 mark）========")
print("  睁眼参考 p90 {:.3f}   闭眼参考 p5 {:.3f}   判闭眼阈值 {:.3f}".format(
    ref_open, ref_closed, thr))
c_true_max = 0.0
for k in range(len(t)):
    sel = (t >= t[k] - ROLL_WIN) & (t <= t[k])
    if sel.any():
        c_true_max = max(c_true_max, float(np.nanmean(eye_closed[sel])))
print("  10 s 窗内真实闭眼占比最大 {:.2f}".format(c_true_max))

# ---- 干净窗里支路二还读得懂眼睛吗（逐 mark 段判）----
print("\n======== 逐段：这一段之前的 10 s 基线是干净的吗 ========")
print("  #  闭眼前 10 s 的 c   该段 en_now 中位   未闭眼期 en_now 中位   方向对不对")
base_open = np.nanmedian(en[mark < 0.5])
for k, (i, j) in enumerate(segs):
    before = (t >= t[i] - ROLL_WIN) & (t < t[i])
    c_before = float(mark[before].mean()) if before.any() else float("nan")
    en_m = np.nanmedian(en[i:j + 1])
    ok = "✅ 降" if en_m < base_open else "❌ 没降反升"
    print("{:3d}      {:5.2f}            {:6.3f}            {:6.3f}          {}".format(
        k + 1, c_before, en_m, base_open, ok))

print("\n  未闭眼期 en_now 中位 {:.3f}（作为对照基准）".format(base_open))
print("  标记期   en_now 中位 {:.3f}".format(np.nanmedian(en[mark > 0.5])))
print("\n  原始 EAR：标记期 {:.3f}   未标记期 {:.3f}   降幅 {:.0f}%".format(
    np.nanmedian(ear[mark > 0.5]), np.nanmedian(ear[mark < 0.5]),
    100 * (1 - np.nanmedian(ear[mark > 0.5]) / np.nanmedian(ear[mark < 0.5]))))
