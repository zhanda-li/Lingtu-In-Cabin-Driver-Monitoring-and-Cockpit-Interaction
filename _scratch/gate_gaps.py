# 一次性分析：量 fuse.csv 里闸门的开合节奏。
# 目的只有一个 —— 把「司机一扭头、支路二 27 秒热身清零」这句话变成数字。
# 不改任何代码、不出判决，只看结构。
import csv
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PATH = sys.argv[1] if len(sys.argv) > 1 else "fuse.csv"
HIST = 27.0          # src/face.py: HIST_SEC = ROLL_WIN + WIN_SEC = 10 + 17

with open(PATH, encoding="utf-8") as fp:
    rd = csv.DictReader(fp)
    cols = rd.fieldnames
    rows = list(rd)

print("列：", cols)
t = [float(d["t"]) for d in rows]
g = [int(float(d["gate"])) for d in rows]
dur = t[-1] - t[0]
print("总 {} 拍，时长 {:.1f} s，决策频率 {:.1f} Hz".format(
    len(rows), dur, len(rows) / dur))
print("闸门开启 {}/{} = {:.1f}%".format(sum(g), len(g), 100 * sum(g) / len(g)))

# 连续开/关段（按真实秒数切）
segs = []
cur, t0 = g[0], t[0]
for i in range(1, len(g)):
    if g[i] != cur:
        segs.append((cur, t0, t[i - 1]))
        cur, t0 = g[i], t[i]
segs.append((cur, t0, t[-1]))

op = sorted(b - a for v, a, b in segs if v == 1)
cl = sorted(b - a for v, a, b in segs if v == 0)


def q(xs, p):
    return xs[min(len(xs) - 1, int(p / 100 * (len(xs) - 1)))]


print("\n开启段 {} 段 / 关闭段 {} 段".format(len(op), len(cl)))
print("开启段时长   p10 {:.1f}  中位 {:.1f}  p90 {:.1f}  最长 {:.1f} s".format(
    q(op, 10), q(op, 50), q(op, 90), op[-1]))
print("关闭段时长   p10 {:.1f}  中位 {:.1f}  p90 {:.1f}  最长 {:.1f} s".format(
    q(cl, 10), q(cl, 50), q(cl, 90), cl[-1]))

print("\n开启段时长分布（秒）：")
for p in (0, 10, 25, 50, 75, 90, 100):
    print("  p{:<3} {:7.1f}".format(p, q(op, p)))

n_short = sum(1 for d in op if d < HIST)
print("\n★ 开启段里短于 HIST_SEC={:.0f} s 的：{}/{} = {:.0f}%".format(
    HIST, n_short, len(op), 100 * n_short / len(op)))
print("  这些段里，支路二从热到能出数就开始计时，仍是永远热不满 ——")
print("  不改设计的话，它们就是支路二完全不工作的那部分时间。")
t_dead = sum(d for d in op if d < HIST)
print("  落在这些段里的总时长：{:.1f} s / {:.1f} s = {:.0f}%".format(
    t_dead, dur, 100 * t_dead / dur))
