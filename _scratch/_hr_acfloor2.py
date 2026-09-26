# -*- coding: utf-8 -*-
'''
定 `AC_MIN_RMS` 用的证据表 —— **交流幅度到底落在哪**，把家里的信号全过一遍。

## 为什么不能只拿 `_hr_acfloor.py` 那张表定阈值

那张表里的"有脉搏"侧是我自己写的**正弦**，而验收脚本
（`_scratch/_check_hr_algo.py`）用的是**高斯脉冲串**（陡升缓降 + 舒张期小鼓包）。
同一个人两个波形过 0.65~3.5 Hz 带通之后剩下的能量差得很远 ——
拿正弦量出来的下限去卡脉冲串，会把验收用例一起卡死。
所以这里**直接 import 那个脚本的 `synth()`**，一个字符都不重写：
波形定义只能有一份，否则改了一边忘了另一边，离线结论就作废
（`_hr_ab_front.py` 踩过这个坑，`_make_bp` 的 docstring 里记着）。

## 顺带纠一个我自己踩的坑

`spec_bpm()` 的节流用的是 **`time.monotonic()`**，而离线脚本里"时间"是
逐样本喂进去的板子时刻 —— 一次 75 秒的模拟在墙钟上只花几十毫秒，
于是节流永远命中、**兜底的值从头到尾是第一次算出来的那个**。
`_hr_fossil.py` 第一版就栽在这上面（打出一串纹丝不动的 62.5）。
这里每次调用前把 `_spec_t` 拨回去强制重算，下面打的是**重算过的**兜底值。
线上不存在这个问题（样本是按实时进来的，墙钟≈板钟）。

用法：D:\\Anaconda3\\envs\\dms\\python.exe _scratch/_hr_acfloor2.py
输出：runs/_hr_acfloor2.log（UTF-8）
'''
import importlib.util
import io
import math
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'ui'))

OUT = []
AC = []
ENV = []


def say(s=''):
    OUT.append(s)


def load_check_module():
    """把验收脚本当模块装进来，只为拿它那个 `synth()`。`main()` 有 `__main__` 卫兵，
    所以 import 不会跑整套检查。"""
    p = os.path.join(ROOT, '_scratch', '_check_hr_algo.py')
    spec = importlib.util.spec_from_file_location('_hr_chk', p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def load_real():
    p = os.path.join(ROOT, 'runs', '_hr_raw.txt')
    rows = []
    for line in io.open(p, encoding='utf-8', errors='replace'):
        line = line.strip()
        if not line.startswith('D,'):
            continue
        f = line.split(',')
        if len(f) == 4:
            rows.append((int(f[1]), int(f[3])))
    return rows


def measure(name, samples, fs=100.0, group=''):
    """喂进线上那个 tracker，回报交流 RMS 与两条路的输出。"""
    from serial_hr import _HrTracker
    tr = _HrTracker(fs=fs)
    for i, (t_ms, ir) in enumerate(samples):
        tr.push(t_ms / 1000.0, float(ir))
    ac = tr.ac_rms()
    # ★ 强制重算兜底（见文件头：不拨回去的话节流会一直命中缓存）
    tr._spec_t = -1e9
    spec = tr.spec_bpm()
    bpm = tr.bpm()
    say('%-40s %10s %10.0f %9s %9s'
        % (name, ('%.1f' % ac) if ac is not None else '—', tr.env,
           ('%.1f' % bpm) if bpm is not None else '—',
           ('%.1f' % spec) if spec is not None else '—'))
    if ac is not None:
        AC.append((ac, name, group))
    return ac


def main():
    chk = load_check_module()
    synth = chk.synth

    say('交流幅度证据表 —— 「传感器上有没有搏动」能不能只靠幅度判')
    say('=' * 88)
    say('%-40s %10s %10s %9s %9s' % ('场景', '交流RMS', '包络', 'bpm', '兜底'))
    say('-' * 88)

    say('【一】真人录（有脉搏，IR 直流 ≈12.3 万）')
    measure('真人录 15s（真脉搏）', load_real(), group='pulse')

    say('')
    say('【二】验收脚本自己的合成族（高斯脉冲串；就是它们必须继续过）')
    cases = [
        ('默认 ac=1200 噪声σ=20', 75, dict()),
        ('干净 90', 90, dict()),
        ('弱信号 ac=200', 75, dict(ac=200.0)),
        ('强噪声 σ=150', 75, dict(noise=150.0)),
        ('偏弱 ac=500 + 噪声σ=120', 75, dict(ac=500.0, noise=120.0)),
        ('没救档 ac=250 噪声σ=120 漂移', 75,
         dict(ac=250.0, noise=120.0, drift=2000.0)),
        ('48 BPM（已知边界，改前就红）', 48, dict()),
    ]
    for label, truth, kw in cases:
        measure('%s  真值%d' % (label, truth), synth(truth, **kw), group='pulse')

    say('')
    say('【三】空载 / 太短（手指闸本来就该拦掉的）')
    measure('空载 dc=8450 ac=25 σ=20', synth(75, sec=15, dc=8450.0, ac=25.0,
                                          noise=20.0), group='nopulse')
    # ⚠️ 「只有 1 秒」单独一组：它的交流 RMS 很高（235.7），但那是**手指到达的
    #    直流阶跃过高通之后的振铃**，是暂态，不是"有搏动的信号"。混进
    #    "没有脉搏"那组会把空档算成 0.23×（第一版就是这么错的），
    #    混进"有脉搏"那组更荒谬。它本来就该由"样本不够"那一条拦掉。
    measure('只有 1 秒（直流阶跃振铃）', synth(75, sec=1, dc=60000.0),
            group='transient')

    say('')
    say('【四】直流高但**没有脉搏**（压太死／环境光饱和那种"人在但没搏动"）')
    say('     ⚠️ 这组是**我合成的白噪声**，σ 是我挑的 —— 它只能说明')
    say('        "合成噪声推到多高才追上有脉搏那侧"，**不能用来给阈值定位**。')
    say('        这块板子真实的噪声量在 `_scratch/_hr_noise.py`。')
    for noise in (2.0, 5.0, 20.0, 50.0, 100.0, 200.0):
        rnd = random.Random(20260926)
        s = [(i * 10, int(round(123000.0 + rnd.gauss(0.0, noise))))
             for i in range(1500)]
        measure('直流123000 无脉搏 σ=%.0f' % noise, s, group='synth_noise')

    say('')
    say('【五】汇总')
    for g, label in (('pulse', '有脉搏（真人+合成脉冲串）'),
                     ('nopulse', '空载（手指闸拦）'),
                     ('transient', '暂态（样本不够拦）'),
                     ('synth_noise', '合成白噪声（不作数，见上）')):
        vals = [a for a, _n, gg in AC if gg == g]
        if vals:
            say('  %-28s n=%2d   交流RMS  %s ~ %s'
                % (label, len(vals),
                   ('%.1f' % min(vals)), ('%.1f' % max(vals))))
    pl = [a for a, _n, g in AC if g == 'pulse']
    say('')
    if pl:
        from serial_hr import AC_MIN_RMS
        # 表里的真人录是 498.1，而 `_hr_noise.py` 对同一段打出 761.4 —— 不是矛盾：
        # tracker 在带通**之前**先减掉了 1 秒滑动均值，两级高通串起来比单独一级
        # 抠掉更多低频。两条路量的都是"带内交流"，只是前端差一级。
        say('  **作数**的两侧：有脉搏最低 %.1f（合成 ac=200 那档），' % min(pl))
        say('  这块板子实测的带内噪声 5.6（`_hr_noise.py`）—— 真正的另一侧。')
        say('  下限 %.1f 落在两者之间：实测噪声的 %.1f 倍、最弱脉搏的 1/%.1f。'
            % (AC_MIN_RMS, AC_MIN_RMS / 5.6, min(pl) / AC_MIN_RMS))
    say('')
    say('⚠️ 诚实说明：这块板子**真实**的"没有脉搏"只有空载那一种（直流 8450，')
    say('   8.7 个数），而它是被手指闸拦的、走不到这道门。手指拿开、只有环境光、')
    say('   而直流仍然高的那一种**没量过**（要独占串口）。真饱和若把带内噪声顶过')
    say('   下限，这道门拦不住 —— 那时还有时效、离散度闸、兜底量程边三道兜着。')

    with io.open(os.path.join(ROOT, 'runs', '_hr_acfloor2.log'), 'w',
                 encoding='utf-8') as f:
        f.write('\n'.join(OUT) + '\n')
    return 0


if __name__ == '__main__':
    rc = 0
    try:
        rc = main()
    finally:
        print('hr ac floor 2: %s' % ('OK' if rc == 0 else 'rc%d' % rc))
    sys.exit(rc)
