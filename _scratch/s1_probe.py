# 一次性诊断：session1 里标记期 vs 未标记期，各量到底怎么动。
# 起因是判决的【2】给出 r(p_fat, en_now)=+0.251，符号与预期相反，
# 而【3】只报了 PERCLOS、没报 p_fat。把它补上，再看符号问题出在哪。
import csv
import sys
import io

import numpy as np

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

rows = list(csv.DictReader(open("runs/session1.csv", encoding="utf-8")))


def col(name, cast=float):
    out = []
    for r in rows:
        v = r[name]
        out.append(float("nan") if v in ("-", "") else cast(v))
    return np.array(out, dtype=float)


t = col("t")
mark = col("mark")
gate = col("gate")
en = col("en_now")
perc = col("perclos")
pf = col("p_fat")
dp = col("d_pitch")
pitch = col("pitch")
ear = col("ear")

# p_fat / perclos 只在出数后才有值；en_now 在闸门开且 ready 后有值
finite = np.isfinite(pf)


def med(x):
    x = x[np.isfinite(x)]
    return float(np.median(x)) if len(x) else float("nan")


def show(tag, m):
    print("{}  n={:3d}  t={:.0f}~{:.0f}s".format(tag, m.sum(), t[m][0], t[m][-1]))
    print("   en_now   中位 {:7.3f}   范围 {:.3f}~{:.3f}".format(
        med(en[m]), np.nanmin(en[m]), np.nanmax(en[m])))
    print("   EAR 原始 中位 {:7.3f}".format(med(ear[m])))
    print("   PERCLOS  中位 {:7.3f}".format(med(perc[m])))
    print("   p_fat    中位 {:7.3f}   范围 {:.3f}~{:.3f}".format(
        med(pf[m]), np.nanmin(pf[m]) if np.isfinite(pf[m]).any() else float("nan"),
        np.nanmax(pf[m]) if np.isfinite(pf[m]).any() else float("nan")))
    print("   d_pitch  中位 {:7.2f}   pitch 中位 {:7.2f}".format(
        med(dp[m]), med(pitch[m])))


mo = finite & (mark > 0.5)
mu = finite & (mark < 0.5)
print("======== 只能比 p_fat 有数的拍 ========")
show("标记期(闭眼)", mo)
show("未标记期", mu)

# 关键问题：en_now 与 p_fat 的关系为什么是正的？
print("\n======== en_now 与 p_fat 的实际联合分布 ========")
both = np.isfinite(en) & finite
print("两者都有数的拍：", both.sum())
if both.sum() > 10:
    print("r = {:+.3f}".format(float(np.corrcoef(en[both], pf[both])[0, 1])))
    # 按 en_now 分箱看 p_fat
    qs = np.quantile(en[both], [0, .2, .4, .6, .8, 1.0])
    for i in range(5):
        m = both & (en >= qs[i]) & (en <= qs[i + 1])
        if m.sum():
            print("   en_now {:.3f}~{:.3f}  n={:3d}   p_fat 中位 {:.3f}"
                  "   PERCLOS 中位 {:.3f}   mark率 {:.0f}%".format(
                      qs[i], qs[i + 1], m.sum(), med(pf[m]), med(perc[m]),
                      100 * float(np.mean(mark[m]))))

print("\n======== 时间轴（10 秒一格）========")
print("  t窗      mark%   en_now  PERCLOS  p_fat   d_pitch")
for a in np.arange(0, t[-1], 10):
    m = (t >= a) & (t < a + 10)
    if m.sum() == 0:
        continue
    print("{:4.0f}-{:4.0f}   {:5.0f}%   {:6.3f}  {:6.3f}  {:6.3f}  {:6.2f}".format(
        a, a + 10, 100 * float(np.mean(mark[m])), med(en[m]), med(perc[m]),
        med(pf[m]), med(dp[m])))
