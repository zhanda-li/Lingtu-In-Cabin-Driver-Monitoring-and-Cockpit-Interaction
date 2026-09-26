# -*- coding: utf-8 -*-
'''
把 `_hr_raw.py` 录下来的原始波形**离线过一遍 serial_hr 的链路**，看波峰为什么没被登记。

2026-09-26 现场：手指真的按上去了（IR 直流 124696、包络 400~600、空载只有 6~10），
可是 18 秒只登记到 1 次搏动 —— 信号明明有，是找峰那一步没跟上。这个脚本回答
"是哪一步、为什么"，不靠猜。

⚠️ 它取的是**当前**的 `serial_hr._make_bp`，所以输出跟着线上走（改前端前后各跑
一次就能看出差别；`runs/_hr_wave.log` 里那份是 2026-09-26 早先单节带通那版的，
当时只登记到 5 拍）。想和"改动前的原版"比请用 `_scratch/_hr_ab_front.py`
—— 它把原版逐字抄了出来当基线，本脚本做不到（`serial_hr` 里已经没有那个构造了）。

用法：
    D:\\Anaconda3\\envs\\dms\\python.exe _scratch/_hr_wave.py
输入：runs/_hr_raw.txt（由 _scratch/_hr_raw.py 录）
输出：runs/_hr_wave.log
'''
import collections
import io
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'ui'))
OUT = []


def say(s=''):
    OUT.append(s)


def main():
    from serial_hr import _make_bp, ENV_DECAY, PEAK_FRAC

    p = os.path.join(ROOT, 'runs', '_hr_raw.txt')
    xs = []
    for ln in io.open(p, encoding='utf-8'):
        ln = ln.strip()
        if ln.startswith('D,'):
            f = ln.split(',')
            if len(f) == 4:
                xs.append((int(f[1]), int(f[2]), int(f[3])))
    if len(xs) < 100:
        say('♥ 原始波形太少（%d 行）—— 先跑 _scratch/_hr_raw.py 录一段' % len(xs))
        return 1

    span = (xs[-1][0] - xs[0][0]) / 1000.0
    ir = [x[2] for x in xs]
    red = [x[1] for x in xs]
    say('样本        ：%d 个 / %.2f s  = %.2f Hz'
        % (len(xs), span, len(xs) / span))
    say('IR          ：min %d  max %d  mean %.0f  峰峰 %d'
        % (min(ir), max(ir), sum(ir) / len(ir), max(ir) - min(ir)))
    say('RED         ：min %d  max %d  mean %.0f  峰峰 %d'
        % (min(red), max(red), sum(red) / len(red), max(red) - min(red)))

    # ---- 照搬 serial_hr 的链路（_make_bp 就是 serial_hr 自己用的那个构造）----
    bp = _make_bp()
    win = collections.deque(maxlen=100)
    s = 0.0
    ys = []
    envs = []
    beats = []
    env = 0.0
    above = False
    for t, _, v in xs:
        if len(win) == 100:
            s -= win[0]
        win.append(v)
        s += v
        y = v - s / len(win)
        for sec in bp:
            y = sec.push(y)
        a = abs(y)
        env = a if a > env else env * ENV_DECAY
        ys.append(y)
        envs.append(env)
        thr = PEAK_FRAC * env
        if thr > 0.0:
            if y > thr:
                above = True
            elif above:
                above = False
                beats.append(t)

    rms = math.sqrt(sum(v * v for v in ys) / len(ys))
    say('带通输出 y  ：min %.0f  max %.0f  rms %.0f（%d 节）'
        % (min(ys), max(ys), rms, len(bp)))
    say('幅值包络 env：min %.0f  max %.0f  末尾 %.0f'
        % (min(envs), max(envs), envs[-1]))

    n_above = sum(1 for y, e in zip(ys, envs) if y > PEAK_FRAC * e)
    say('y > 阈值 的占比 %.1f%%    y < 0 的占比 %.1f%%'
        % (100.0 * n_above / len(ys),
           100.0 * sum(1 for y in ys if y < 0) / len(ys)))

    say('')
    say('照 serial_hr 原样复算 -> 登记波峰 %d 个' % len(beats))
    if len(beats) > 1:
        ib = [(b - a) / 1000.0 for a, b in zip(beats, beats[1:])]
        say('  间隔：%s' % ['%.3f' % v for v in ib])
        say('  中位 %.3f s -> %.1f BPM' % (sorted(ib)[len(ib) // 2],
                                          60.0 / sorted(ib)[len(ib) // 2]))
    else:
        # 一次都没登记上：看"above"到底有没有翻回来过
        say('  ↑ 只登记了 %d 次。看下面的"驻留时长"就知道是卡在哪一步' % len(beats))

    # ---- 驻留时长：y 连续待在同一侧多久 ----
    runs = []
    cur = 0
    for y, e in zip(ys, envs):
        if y > PEAK_FRAC * e:
            cur += 1
        elif cur:
            runs.append(cur)
            cur = 0
    if cur:
        runs.append(cur)
    if runs:
        rr = sorted(runs)
        say('y 单次"高于阈值"的驻留（样本数）：中位 %d  最长 %d  （%d 段）'
            % (rr[len(rr) // 2], rr[-1], len(rr)))
        say('  → 100 Hz 下，一段 50 样本 = 0.5 s。驻留时长 ≈ 半个心动周期时，'
            '每跳只该登记 1 次；')
        say('    若中位驻留 ≈ 100 样本（1 s），说明阈值太低、信号落不回来。')

    # ---- 真实周期：用自相关找主频，跟"登记波峰"对照 ----
    # ⚠️ lag 必须限制在**生理范围**（0.40~1.60 s = 150~37 BPM）。不限制的话它会挑中
    # lag 30（0.30 s = 200 BPM）—— 那是脉搏波自己的形状周期，不是心率，结果是个
    # 看着很确定、其实是假的裁判。2026-09-26 这个脚本就报了 200 BPM（旧的
    # runs/_hr_wave.log 第 14 行还留着），后来才改成限范围。
    # ⚠️ 而且它算的是**带通之后**的 `ys`，所以**不是独立口径** —— 它已经过了一遍
    # 被测前端。要独立裁判请用 `_hr_ab_front.py` 的 `ref_bpm`（只在原始 IR 上做
    # 去趋势 + 窄带 DFT）。这一行只回答"滤完之后波形本身像多少 BPM"。
    n = len(ys)
    m = sum(ys) / n
    z = [v - m for v in ys]
    best = None
    for lag in range(40, min(161, n // 2)):
        c = sum(z[i] * z[i + lag] for i in range(n - lag)) / (n - lag)
        if best is None or c > best[1]:
            best = (lag, c)
    if best:
        say('自相关主周期：%d 样本 = %.3f s -> 约 %.1f BPM'
            '（滤完之后波形本身的周期，不是独立裁判）'
            % (best[0], best[0] / 100.0, 6000.0 / best[0]))
    return 0


if __name__ == '__main__':
    try:
        rc = main()
    except Exception as e:
        say('♥ 异常：%r' % (e,))
        rc = 1
    with io.open(os.path.join(ROOT, 'runs', '_hr_wave.log'), 'w',
                 encoding='utf-8') as f:
        f.write('\n'.join(OUT) + '\n')
    print('hr wave: rc=%d' % rc)
    sys.exit(rc)
