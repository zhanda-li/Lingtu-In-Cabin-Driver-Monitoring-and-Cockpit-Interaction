# -*- coding: utf-8 -*-
'''
在**真实录制的波形**上试几种前端（去直流 + 带通），比谁能把心跳从慢漂移里救出来。

🔴 **已被 `_scratch/_hr_ab_front.py` 取代，别再拿这个的表格当结论。** 这里有几档
把那一行标成"现状/基线"，但**那条不是文件里真正的滤波器** —— 是我按两个拐点自己
拼的，比出来"单级 2 阶不够"这个方向虽然对，可**基线的数字是假的**（原版是一个
单节 RBJ 带通、Q=0.56，不是"高通×1 + 低通×1"）。`_hr_ab_front.py` 把原版逐字抄了
出来当基线，并且把 `_Biquad`/`BP_LOW_HZ` 一起扫了。留着本文件是为了复现当时那次
误判。**还要注意它的"现状"标签指的是改动前的线上代码，现在线上已经换了。**

当时的病：手指按上去后 IR 直流在 15 秒里飘了 7815 个数（压力变化），脉动只有 ~700。

比法：每种前端都过**同一套**找峰逻辑（抄 serial_hr 的 PEAK_FRAC），看：
  登记波峰数、间隔的中位/中位绝对偏差、以及"带通输出里负值占比"
  （零均值的信号应该在 50% 附近，显著偏离 = 还有漂移漏进来）。
**判据不是"能出个数"，是"间隔稳"** —— 漂移导致的是忽大忽小的假间隔。

用法：D:\\Anaconda3\\envs\\dms\\python.exe _scratch/_hr_front.py
输入：runs/_hr_raw.txt
输出：runs/_hr_front.log
'''
import collections
import io
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'ui'))
OUT = []

FS = 100.0
ENV_DECAY = 0.995
PEAK_FRAC = 0.45
MIN_IBI = 0.33
MAX_IBI = 1.60
MIN_BEATS = 4
MAX_SPREAD = 0.20


def say(s=''):
    OUT.append(s)


class BQ(object):
    """RBJ 双二阶（跟 ui/serial_hr.py 的 _Biquad 同一套公式，独立写一遍）。"""

    def __init__(self, f0, fs, kind, q):
        w0 = 2.0 * math.pi * f0 / fs
        alpha = math.sin(w0) / (2.0 * q)
        cw = math.cos(w0)
        if kind == 'hp':
            b0, b1, b2 = (1 + cw) / 2, -(1 + cw), (1 + cw) / 2
            a0, a1, a2 = 1 + alpha, -2 * cw, 1 - alpha
        else:                                   # lp
            b0, b1, b2 = (1 - cw) / 2, 1 - cw, (1 - cw) / 2
            a0, a1, a2 = 1 + alpha, -2 * cw, 1 - alpha
        self.b0, self.b1, self.b2 = b0 / a0, b1 / a0, b2 / a0
        self.a1, self.a2 = a1 / a0, a2 / a0
        self.x1 = self.x2 = self.y1 = self.y2 = 0.0

    def push(self, x):
        y = (self.b0 * x + self.b1 * self.x1 + self.b2 * self.x2
             - self.a1 * self.y1 - self.a2 * self.y2)
        self.x2, self.x1 = self.x1, x
        self.y2, self.y1 = self.y1, y
        return y


def ma(ir, w):
    """滑动均值（w 个样本）。"""
    out = []
    q = collections.deque()
    s = 0.0
    for v in ir:
        q.append(v)
        s += v
        if len(q) > w:
            s -= q.popleft()
        out.append(s / len(q))
    return out


def run(name, ir, detrend, stages):
    base = detrend(ir)
    filters = []
    for kind, f0, q in stages:
        filters.append(BQ(f0, FS, kind, q))
    ys = []
    for i, v in enumerate(ir):
        y = v - base[i]
        for f in filters:
            y = f.push(y)
        ys.append(y)

    env = 0.0
    above = False
    beats = []
    for i, y in enumerate(ys):
        a = abs(y)
        env = a if a > env else env * ENV_DECAY
        thr = PEAK_FRAC * env
        if thr <= 0.0:
            continue
        if y > thr:
            above = True
        elif above:
            above = False
            beats.append(i)

    ibis = [b / FS for b in
            [(b - a) for a, b in zip(beats, beats[1:])]]
    ibis = [t for t in ibis if MIN_IBI <= t <= MAX_IBI]
    neg = 100.0 * sum(1 for y in ys if y < 0) / len(ys)
    rms = math.sqrt(sum(y * y for y in ys) / len(ys))
    if len(ibis) >= MIN_BEATS:
        s = sorted(ibis)
        med = s[len(s) // 2]
        mad = sorted(abs(x - med) for x in ibis)[len(s) // 2]
        spread = mad / med if med else 9.9
        verdict = 'BPM %.1f' % (60.0 / med) if spread <= MAX_SPREAD else \
                  '有数但离散度 %.3f 超标' % spread
    else:
        med = spread = None
        verdict = '攒不到 4 个间隔'
    say('%-34s 波峰 %3d  有效间隔 %2d  中位 %s  离散度 %s  负值占比 %4.1f%%  rms %6.0f'
        % (name, len(beats), len(ibis),
           ('%.3f' % med) if med else '  —  ',
           ('%.3f' % spread) if spread is not None else ' —  ',
           neg, rms))
    say('%-34s → %s' % ('', verdict))
    return len(ibis), med, spread


def main():
    xs = []
    for ln in io.open(os.path.join(ROOT, 'runs', '_hr_raw.txt'), encoding='utf-8'):
        ln = ln.strip()
        if ln.startswith('D,'):
            f = ln.split(',')
            if len(f) == 4:
                xs.append(int(f[3]))
    if len(xs) < 500:
        say('♥ 波形太少（%d）' % len(xs))
        return 1
    say('样本 %d 个 / %.1f s' % (len(xs), len(xs) / FS))
    say('IR：mean %.0f  峰峰 %d  （峰峰/均值 = %.1f%%）'
        % (sum(xs) / len(xs), max(xs) - min(xs),
           100.0 * (max(xs) - min(xs)) / (sum(xs) / len(xs))))
    say('')
    say('── 各种前端（同样的找峰逻辑）' + '─' * 30)

    # A ⚠️ 这一档**不是**当时的线上代码（线上是单节 RBJ 带通 Q=0.56、一个滤波器；
    #    这里是高通 + 低通两个节）。标"现状"是当时的错，改名保留免得再被读成基线。
    run('A 拼(≠原版) 1s均值 + HP.7+LP3.5',
        xs, lambda a: ma(a, 100),
        [('hp', 0.70, 0.707), ('lp', 3.50, 0.707)])

    # B 去直流窗加长
    run('B       2s均值 + 单级 0.7~3.5',
        xs, lambda a: ma(a, 200),
        [('hp', 0.70, 0.707), ('lp', 3.50, 0.707)])
    run('C       3s均值 + 单级 0.7~3.5',
        xs, lambda a: ma(a, 300),
        [('hp', 0.70, 0.707), ('lp', 3.50, 0.707)])

    # D 高通级联两级（24 dB/oct）
    run('D       1s均值 + 高通×2 + 低通',
        xs, lambda a: ma(a, 100),
        [('hp', 0.70, 0.707), ('hp', 0.70, 0.707), ('lp', 3.50, 0.707)])
    run('E       2s均值 + 高通×2 + 低通',
        xs, lambda a: ma(a, 200),
        [('hp', 0.70, 0.707), ('hp', 0.70, 0.707), ('lp', 3.50, 0.707)])

    # F 只靠滤波去直流（不做均值），高通×2 自己把直流压掉
    run('F       无均值 + 高通×2 + 低通',
        xs, lambda a: [0.0] * len(a),
        [('hp', 0.70, 0.707), ('hp', 0.70, 0.707), ('lp', 3.50, 0.707)])

    # G 高通抬到 0.9 Hz（65 BPM 是 1.09 Hz，还有余量）
    run('G       2s均值 + 高通×2@0.9 + 低通3.5',
        xs, lambda a: ma(a, 200),
        [('hp', 0.90, 0.707), ('hp', 0.90, 0.707), ('lp', 3.50, 0.707)])

    # H/I/J 正规 4 阶巴特沃斯（两个 Q 不同的节，−3 dB 点正好落在 0.7 Hz）。
    # 为什么不沿用 D/E 那种"两个 Q=0.707 串起来"：那等于 −3 dB 点被推到 ~0.85 Hz，
    # 心率慢的人（45 BPM = 0.75 Hz）基波会被削掉一截 —— D/E 在这段波形上够用，
    # 但换个 50 BPM 的人就未必了。巴特沃斯是按"通带最平"设计的，不该在图省事
    # 的地方换成"两个一样的节"。
    Q4 = (0.54119610, 1.30656296)
    run('H       1s均值 + 4阶BW HP@0.7 + 单级LP3.5',
        xs, lambda a: ma(a, 100),
        [('hp', 0.70, Q4[0]), ('hp', 0.70, Q4[1]), ('lp', 3.50, 0.707)])
    run('I       2s均值 + 4阶BW HP@0.7 + 单级LP3.5',
        xs, lambda a: ma(a, 200),
        [('hp', 0.70, Q4[0]), ('hp', 0.70, Q4[1]), ('lp', 3.50, 0.707)])
    run('J       1s均值 + 4阶BW HP@0.7 + 4阶BW LP3.5',
        xs, lambda a: ma(a, 100),
        [('hp', 0.70, Q4[0]), ('hp', 0.70, Q4[1]),
         ('lp', 3.50, Q4[0]), ('lp', 3.50, Q4[1])])

    say('')
    say('判据：**间隔稳**才算好（漂移给的是忽大忽小的假间隔）。')
    say('负值占比 50% 附近 = 没有漂移漏进来。')
    return 0


if __name__ == '__main__':
    try:
        rc = main()
    except Exception as e:
        say('♥ 异常：%r' % (e,))
        rc = 1
    with io.open(os.path.join(ROOT, 'runs', '_hr_front.log'), 'w',
                 encoding='utf-8') as f:
        f.write('\n'.join(OUT) + '\n')
    print('hr front: rc=%d' % rc)
    sys.exit(rc)
