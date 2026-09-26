# -*- coding: utf-8 -*-
'''
换一个质量判据试试：**同一段间隔，两种独立算法各估一次，看同不同意。**

为什么想到它：`MAX_IBI_SPREAD` 测的是"间隔规不规范"，可对称的多检/漏检会把间隔
搞乱、却把计数抵消掉 —— 所以那个数**跟误差不成比例**（实测：散度 0.254 误差 +9.5，
散度 0.314 误差只有 −2.4，两个方向都反着）。而"两个独立估法给出同一个率"这件事，
直接就是"这个率稳不稳"，不需要它长得规整。

两种独立估法（用**同一段间隔**，只换统计量）：
  · 中位法  60 / median(间隔)        —— 抗少数坏值
  · 计数法  60 × n / (t_last − t_first) —— 抗**对称**的坏值

判据：`不一致度 = |计数 − 中位| / 中位`。

**要看的只有一件事：所有用例上，不一致度能不能把"准的"和"不准的"分开。**
分得开 → 换这个判据；分不开 → 这道闸就该拿掉，别再换个数字继续骗自己。

用法：D:\\Anaconda3\\envs\\dms\\python.exe _scratch/_hr_agree.py
输出：runs/_hr_agree.log
'''
import io
import math
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'ui'))

from serial_hr import _HrTracker  # noqa: E402

FS = 100
OUT = []


def say(s=''):
    OUT.append(s)


# 与 _hr_est_ab.py 同一个合成器（那边的 docstring 写了它的来路和边界）
def synth(bpm, sec=30.0, dc=60000.0, ac=1200.0, noise=20.0,
          drift=0.0, drop_beat=None, seed=1, motion=0.0, mrate=0.3):
    rng = random.Random(seed)
    T = 60.0 / bpm
    out = []
    for k in range(int(sec * FS)):
        t = k / FS
        n = int(t / T)
        if drop_beat is not None and n == drop_beat:
            y = 0.0
        else:
            ph = (t % T) / T
            y = (math.exp(-((ph - 0.0) / 0.18) ** 2)
                 + 0.35 * math.exp(-((ph - 0.45) / 0.10) ** 2)
                 + math.exp(-((ph - 1.0) / 0.18) ** 2))
        g = 1.0 + motion * math.sin(2 * math.pi * mrate * t)
        v = dc + drift * math.sin(2 * math.pi * 0.1 * t) + ac * g * y + rng.gauss(0, noise)
        out.append((k * 10, int(round(v))))
    return out


def beats_of(samples):
    tr = _HrTracker(FS)
    for t_ms, ir in samples:
        tr.push(t_ms / 1000.0, float(ir))
    return list(tr.beat_times)


def pair_estimates(ts, k=8):
    """同一段（最近 k 个间隔）：返回 (中位法, 计数法)。"""
    w = ts[-(k + 1):]
    if len(w) < 3:
        return None, None
    ib = [b - a for a, b in zip(w, w[1:])]
    ib = [x for x in ib if x > 0]
    if not ib:
        return None, None
    med = sorted(ib)[len(ib) // 2]
    rm = 60.0 / med if med > 0 else None
    span = w[-1] - w[0]
    rc = 60.0 * len(ib) / span if span > 0 else None
    return rm, rc


def scan(name, truth, ts, k, rows):
    rm, rc = pair_estimates(ts, k)
    if rm is None or rc is None:
        return
    dis = abs(rc - rm) / rm          # 不一致度
    # 判"这个估计可不可信"用的是**它自己的误差**，真值只有离线才知道
    err = abs(rm - truth)
    rows.append((name, truth, k, rm, rc, dis, err))


CASES = [
    ('干净 60', 60, dict()),
    ('干净 75', 75, dict()),
    ('干净 120', 120, dict()),
    ('弱信号 ac=200', 75, dict(ac=200.0)),
    ('强噪声 σ=150', 75, dict(noise=150.0)),
    ('基线漂移 ±3000', 75, dict(drift=3000.0)),
    ('弱+噪 ac500 σ120', 75, dict(ac=500.0, noise=120.0)),
    ('闸说"没救了" ac250 σ120 漂2000', 75, dict(ac=250.0, noise=120.0, drift=2000.0)),
    ('漏一拍', 75, dict(drop_beat=12)),
    ('运动 1.5×', 75, dict(motion=1.5)),
    ('运动 3×', 75, dict(motion=3.0)),
    ('运动 3× + σ120', 75, dict(motion=3.0, noise=120.0)),
    ('运动 3× @120', 120, dict(motion=3.0, noise=60.0)),
    ('运动 2× @120', 120, dict(motion=2.0)),
]


def main():
    rows = []
    for name, truth, kw in CASES:
        ts = beats_of(synth(truth, **kw))
        for k in (8, 12):
            scan(name, truth, ts, k, rows)

    say('判据：不一致度 = |计数法 − 中位法| / 中位法（同一段间隔，只换统计量）')
    say('要能分开的是"中位法的误差" —— 误差大 = 这个数不该给。')
    say('=' * 100)
    say('  %-32s %5s %4s %8s %8s %9s %8s  %s'
        % ('场景', '真值', 'k', '中位法', '计数法', '不一致度', '中位误差', '判'))
    say('  ' + '-' * 96)
    rows.sort(key=lambda r: r[5])
    for name, truth, k, rm, rc, dis, err in rows:
        say('  %-32s %5d %4d %8.1f %8.1f %8.1f%% %8.1f  %s'
            % (name, truth, k, rm, rc, 100 * dis, err,
               '准' if err <= 5 else ('偏' if err <= 10 else '烂')))
    say('')
    say('  按不一致度排序后，看"偏/烂"是不是都排在后面 ——')
    say('  如果"准"和"烂"交错着出现，这个判据就是**分不开**，别用它。')

    # ---------------- 真人那一段：判据必须**放它过去**，这是用户的诉求
    say('')
    say('=' * 100)
    say('★ 真人那一段（用户要它「一直有数」的那类信号）—— 判据必须放它过去：')
    real = None
    for ln in io.open(os.path.join(ROOT, 'runs', '_hr_finger.log'), encoding='utf-8'):
        if ln.startswith('最近的搏动时刻'):
            real = [float(x) for x in ln.split('：')[1].split()]
    if real:
        anchor = 60.0 * (len(real) - 1) / (real[-1] - real[0])
        say('  整段锚 %.1f BPM。逐拍滚动（每拍一个窗口）：' % anchor)
        for k in (8, 12):
            line = []
            for i in range(k + 1, len(real) + 1):
                rm, rc = pair_estimates(real[:i], k)
                if rm is None:
                    continue
                line.append('%4.0f/%.0f%%' % (rm, 100 * abs(rc - rm) / rm))
            say('    k=%2d  值/不一致度： %s' % (k, ' '.join(line[-24:])))
        say('  （格式：中位法的值 / 不一致度）')
    else:
        say('  （runs/_hr_finger.log 里没有搏动时刻）')
    return 0


if __name__ == '__main__':
    rc = 1
    try:
        rc = main()
    except Exception as e:
        import traceback
        say('!!!! 异常：%r' % (e,))
        say(traceback.format_exc())
    with io.open(os.path.join(ROOT, 'runs', '_hr_agree.log'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(OUT) + '\n')
    print('hr agree: rc=%d' % rc)
    sys.exit(rc)
