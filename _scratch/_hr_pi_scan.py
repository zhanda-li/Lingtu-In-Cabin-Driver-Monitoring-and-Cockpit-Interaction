# -*- coding: utf-8 -*-
'''
PI 口径体检（滑动窗扫描版）—— 在所有**有手指**的时段上，问同一个问题：
"这个 3 秒窗的 RMS 里，多少是搏动、多少是按压力度漂移"。

`_hr_pi_spec.py` 是拿手工挑的窗口看的；这个扫全段，好处是**能看出 PI 和
搏动占比到底同不同向** —— 同向 ⟹ PI 当信号质量用是站得住的；不同向 ⟹ 它在
某些按压档上量的是别的东西（`_hr_pi_cal` 的重按档就是这样）。

⚠️ 裁判只能用**窄带 DFT**。绝不对原始 IR 做自相关（单调下降必报 lag 下限）。

用法：
    D:\\Anaconda3\\envs\\dms\\python.exe _scratch/_hr_pi_scan.py [文件 …]
不给文件名就扫 _hr_pi_cal.txt 与 _hr_nn_20260926_205912.txt。
输出：runs/_hr_pi_scan.log
'''
import io
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ui.serial_hr import _make_bp, SAMPLE_RATE_HZ, FINGER_DC_MIN  # noqa: E402

FS = float(SAMPLE_RATE_HZ)
STEP_S = 2.0            # 滑窗步长
WIN_S = 8.0             # 分析窗（要装下好几个脉搏周期才谈得上频谱）
OUT = []


def say(s=''):
    OUT.append(s)


def load(name):
    rows = []
    with io.open(os.path.join(ROOT, 'runs', name), 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line.startswith('D,'):
                continue
            p = line.split(',')
            if len(p) == 4:
                rows.append((int(p[1]), int(p[3])))
    return rows


def bandpass(x):
    secs = _make_bp()
    st = [{'x1': 0.0, 'x2': 0.0, 'y1': 0.0, 'y2': 0.0} for _ in secs]
    out = [0.0] * len(x)
    for i, v in enumerate(x):
        y = v
        for k, s in enumerate(secs):
            d = st[k]
            o = ((((s.b0 * y) + (s.b1 * d['x1'])) + (s.b2 * d['x2']))
                 - (s.a1 * d['y1'])) - (s.a2 * d['y2'])
            d['x2'] = d['x1']
            d['x1'] = y
            d['y2'] = d['y1']
            d['y1'] = o
            y = o
        out[i] = y
    return out


def rms(seg):
    if not seg:
        return 0.0
    m = sum(seg) / len(seg)
    return math.sqrt(sum((v - m) ** 2 for v in seg) / len(seg))


def dft_peak(seg, lo=0.6, hi=3.6):
    """窄带 DFT（汉宁窗），返回 (峰频, 峰幅)。seg 是 25 Hz 抽取后的。"""
    n = len(seg)
    if n < 64:
        return None
    m = sum(seg) / n
    w = [0.5 - 0.5 * math.cos(2 * math.pi * i / (n - 1)) for i in range(n)]
    dt = 4.0 / FS
    best = (0.0, 0.0)
    f = lo
    while f <= hi:
        re = im = 0.0
        for i in range(n):
            ang = 2 * math.pi * f * i * dt
            v = (seg[i] - m) * w[i]
            re += v * math.cos(ang)
            im -= v * math.sin(ang)
        amp = 2.0 * math.hypot(re, im) / (n * 0.5)
        if amp > best[1]:
            best = (f, amp)
        f += 0.02
    return best


def scan(name):
    rows = load(name)
    if len(rows) < 400:
        say('%-30s  ♥ 样本太少' % name)
        return
    t0 = rows[0][0]
    ir = [float(r[1]) for r in rows]
    bp = bandpass(ir)
    say('')
    say('=' * 84)
    say('%s   %d 样本  %.1f 秒' % (name, len(rows), len(rows) / FS))
    say('=' * 84)
    say('%8s %9s %8s %8s %8s %9s %8s  %s'
        % ('t_s', 'dc', 'ac3s', 'PI%', 'RMS8s', '峰频', '峰幅', '搏动占比'))
    t = 0.0
    n_win = 0
    while t + WIN_S <= len(rows) / FS:
        a = int(t * FS)
        b = int((t + WIN_S) * FS)
        dcs = ir[max(0, b - 100):b]
        dc = sum(dcs) / len(dcs) if dcs else 0.0
        if dc < FINGER_DC_MIN:
            t += STEP_S
            continue
        # 末 3 秒（= 出货口径那个窗）
        c = max(a, b - int(3 * FS))
        ac3 = rms(bp[c:b])
        seg = [bp[i] for i in range(a, b, 4)]
        r8 = rms(seg)
        pk = dft_peak(seg)
        pi = ac3 / dc * 100.0 if dc > 0 else float('nan')
        if pk and r8 > 0:
            ratio = 100.0 * (pk[1] / math.sqrt(2)) / r8
            say('%8.1f %9.0f %8.1f %8.3f %8.1f %7.3fHz %8.1f %7.1f%%'
                % (t, dc, ac3, pi, r8, pk[0], pk[1], ratio))
        else:
            say('%8.1f %9.0f %8.1f %8.3f %8.1f      --       --      --'
                % (t, dc, ac3, pi, r8))
        n_win += 1
        t += STEP_S
    if n_win == 0:
        say('  （整段没有 dc ≥ %.0f 的窗口 —— 手指从没到位）' % FINGER_DC_MIN)


def main():
    names = sys.argv[1:] or ['_hr_pi_cal.txt', '_hr_nn_20260926_205912.txt']
    say('口径：ac3s = 出货那个 3 秒窗 RMS（PI 的分子）；RMS8s = 8 秒窗 RMS')
    say('      搏动占比 = 窄带 DFT 峰值的等效 RMS ÷ RMS8s')
    for n in names:
        if not n.endswith('.txt'):
            n += '.txt'
        try:
            scan(n)
        except Exception as e:
            say('%s  ♥ 异常 %r' % (n, e))
    return 0


if __name__ == '__main__':
    try:
        rc = main()
    except Exception as e:
        import traceback
        say('♥ 异常：%r' % (e,))
        say(traceback.format_exc())
        rc = 1
    with io.open(os.path.join(ROOT, 'runs', '_hr_pi_scan.log'), 'w',
                 encoding='utf-8') as f:
        f.write('\n'.join(OUT) + '\n')
    print('hr pi scan: rc=%d' % rc)
    sys.exit(rc)
