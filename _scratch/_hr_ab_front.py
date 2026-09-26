# -*- coding: utf-8 -*-
'''
高通拐点扫描：在**合成用例**和**真人录制**上一起跑，定 `BP_LOW_HZ`。

**两列必须一起看**：
  · 只看合成用例 → 会选错：拐点越低在合成上越干净（合成波里没有那个 0.53 Hz 的
    artifact），可是真人那段录里 0.53 Hz 幅度 201 比心跳 1.09 Hz 的 132 还大
    （runs/_hr_look.log），拐点越低漏进来越多。
  · 只看真人那一段 → 15 秒一条，样本太少，容易把运气当通例。

**基线必须是原版本身的（逐字照抄）。** 2026-09-26 我先犯了这个错 —— 把原版
**自己重写成**"高通×1 + 低通×1"当基线比，那不是同一个滤波器（原版是单节带通、
Q=0.56），据此得到的"单级 2 阶不够"这个结论虽然方向上是对的（原版在真人录上
确实攒不到数），但**基线数字是假的**。下面标了"拼"的那几档就是这种重写版，
留着是为了复现当时的错，**别当基线**。

⚠️ 原版现在**只能抄在这儿**，`serial_hr` 里已经没有它了：线上的 `_Biquad`
已经换成通用的高通/低通节（`_make_bp` 拿它拼 4 阶），带通那个构造不再存在。
下面 `OrigBp` 就是从改动前的 `ui/serial_hr.py` 逐字抄的（取证在
`runs/_orig_biquad.txt`），**别改它** —— 它的价值全在"和线上曾经的代码字面一致"。

用法：D:\\Anaconda3\\envs\\dms\\python.exe _scratch/_hr_ab_front.py
输出：runs/_hr_ab_front.log
'''
import io
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'ui'))
sys.path.insert(0, HERE)

import serial_hr                                              # noqa: E402
from _check_hr_algo import synth                              # noqa: E402

OUT = []
Q4 = (0.54119610, 1.30656296)
LP = 3.50
FS = 100.0


def say(s=''):
    OUT.append(s)


class OrigBp:
    """**原版**：单节 RBJ 带通（常数 0 dB 峰值增益），给两个拐点，f0 取几何中点、
    Q = f0/带宽。逐字抄自改动前的 `ui/serial_hr.py`（见文件头）。"""

    def __init__(self, low_hz, high_hz, fs):
        f0 = math.sqrt(low_hz * high_hz)
        bw = math.log2(high_hz / low_hz)          # 带宽，以八度为单位
        w0 = 2.0 * math.pi * f0 / fs
        alpha = math.sin(w0) * math.sinh(math.log(2.0) / 2.0 * bw * w0 / math.sin(w0))

        a0 = 1.0 + alpha
        self.b0 = alpha / a0
        self.b1 = 0.0
        self.b2 = -alpha / a0
        self.a1 = (-2.0 * math.cos(w0)) / a0
        self.a2 = (1.0 - alpha) / a0

        self.x1 = self.x2 = self.y1 = self.y2 = 0.0

    def push(self, x):
        y = (self.b0 * x + self.b1 * self.x1 + self.b2 * self.x2
             - self.a1 * self.y1 - self.a2 * self.y2)
        self.x2, self.x1 = self.x1, x
        self.y2, self.y1 = self.y1, y
        return y

    def reset(self):
        self.x1 = self.x2 = self.y1 = self.y2 = 0.0


class Sec:
    """单个高通/低通二阶节（RBJ）。**只给标了"拼"的对照档用** ——
    原版在上面的 `OrigBp` 里，是另一个滤波器（带通、带两个拐点）。"""

    def __init__(self, f0, fs, kind, q):
        w0 = 2.0 * math.pi * f0 / fs
        cw = math.cos(w0)
        alpha = math.sin(w0) / (2.0 * q)
        if kind == 'hp':
            b0, b1, b2 = (1.0 + cw) / 2.0, -(1.0 + cw), (1.0 + cw) / 2.0
        else:
            b0, b1, b2 = (1.0 - cw) / 2.0, 1.0 - cw, (1.0 - cw) / 2.0
        a0 = 1.0 + alpha
        self.b0, self.b1, self.b2 = b0 / a0, b1 / a0, b2 / a0
        self.a1, self.a2 = (-2.0 * cw) / a0, (1.0 - alpha) / a0
        self.x1 = self.x2 = self.y1 = self.y2 = 0.0

    def push(self, x):
        y = (self.b0 * x + self.b1 * self.x1 + self.b2 * self.x2
             - self.a1 * self.y1 - self.a2 * self.y2)
        self.x2, self.x1 = self.x1, x
        self.y2, self.y1 = self.y1, y
        return y


def bw4(fc, fs):
    """4 阶巴特沃斯高通 = 两个 Q 不同的二阶节，−3 dB 点正好在 fc。"""
    return [Sec(fc, fs, 'hp', Q4[0]), Sec(fc, fs, 'hp', Q4[1]), Sec(LP, fs, 'lp', 0.7071)]


CONTROLS = [
    ('原版 单节带通 Q=.56（改动前）', lambda fs: [
        OrigBp(0.70, 3.50, fs)]),
    ('拼  HP0.7x1 + LP3.5（≠原版）', lambda fs: [
        Sec(0.70, fs, 'hp', 0.7071), Sec(LP, fs, 'lp', 0.7071)]),
    ('拼  HP0.7x2 同Q + LP3.5', lambda fs: [
        Sec(0.70, fs, 'hp', 0.7071), Sec(0.70, fs, 'hp', 0.7071),
        Sec(LP, fs, 'lp', 0.7071)]),
]

CANDIDATE_FC = [0.50, 0.55, 0.60, 0.65, 0.70, 0.80]

CASES = [
    ('48 BPM', 48, dict(), 'num'),
    ('60 BPM', 60, dict(), 'num'),
    ('75 BPM', 75, dict(), 'num'),
    ('90 BPM', 90, dict(), 'num'),
    ('120 BPM', 120, dict(), 'num'),
    ('150 BPM', 150, dict(), 'num'),
    ('ac=200', 75, dict(ac=200.0), 'num'),
    ('noise=150', 75, dict(noise=150.0), 'num'),
    ('drift=3000', 75, dict(drift=3000.0), 'num'),
    ('ac=500+noise=120', 75, dict(ac=500.0, noise=120.0), 'num'),
    ('没救了(信噪比2:1)', 75, dict(ac=250.0, noise=120.0, drift=2000.0), 'none'),
]
WAVES = [(n, t, w, synth(t, **kw)) for n, t, kw, w in CASES]  # (名, 真值, 期望, 波形)


def load_real():
    """真人录制（runs/_hr_raw.txt，由 _scratch/_hr_raw.py 录）。"""
    xs = []
    for ln in io.open(os.path.join(ROOT, 'runs', '_hr_raw.txt'), encoding='utf-8'):
        ln = ln.strip()
        if ln.startswith('D,'):
            f = ln.split(',')
            if len(f) == 4:
                xs.append((int(f[1]), int(f[3])))
    return xs


def ref_bpm(ir):
    """裁判：这段录里**心率频段**（0.8~2.5 Hz = 48~150 BPM）最强的那个频点。
    不经过任何前端，只做"去趋势 + 窄带 DFT"。

    ⚠️ **不能用自相关**（本函数 2026-09-26 之前用的就是它，报 150.0，是假的）：
    IR 去完趋势之后，自相关从 lag 下限开始**单调下降**，整段没有局部极大 ——
    所以"全局最大"永远落在 lag 40（0.40 s = 150 BPM），那不是周期，是"曲线在
    往下走"这件事本身。换 1 秒的去趋势窗能让 lag 92（65.2 BPM）冒出来，可那个窗
    里最大的局部极大在 lag 152（39.5 BPM，低频残留的假峰），挑"最大"还是错。
    窄带 DFT 不受这个影响：它按频点分别积分，低频尾巴摊不到 1.09 Hz 上。

    频段下限取 0.8 Hz：这段录里 0.53 Hz（32 BPM）的幅度比心跳还大
    （runs/_hr_look.log：201 vs 132），那是漂移不是心率，必须挡在段外。
    上限 2.5 Hz：1.09 Hz 的二次谐波 2.18 Hz 落在段内，但它比基频弱，赢不了。
    """
    n = len(ir)
    W = 200                                   # 先减 2 s 滑动均值，压掉慢漂移
    acc, q, d = 0.0, [], []
    for v in ir:
        q.append(v)
        acc += v
        if len(q) > W:
            acc -= q.pop(0)
        d.append(v - acc / len(q))
    best = None
    f = 0.80
    while f <= 2.50:
        w = 2.0 * math.pi * f / FS
        re = im = 0.0
        for i, v in enumerate(d):
            re += v * math.cos(w * i)
            im += v * math.sin(w * i)
        mag = math.hypot(re, im) / n
        if best is None or mag > best[1]:
            best = (f, mag)
        f += 0.01
    return best[0] * 60.0


def run(make_bp, samples, peak_frac=None, env_decay=None):
    """换掉模块级的 `_make_bp` / `PEAK_FRAC` / `ENV_DECAY`（线上用的就是它们），跑一遍。"""
    serial_hr._make_bp = make_bp
    serial_hr.PEAK_FRAC = 0.45 if peak_frac is None else peak_frac
    serial_hr.ENV_DECAY = 0.995 if env_decay is None else env_decay
    tr = serial_hr._HrTracker(FS)
    for t_ms, ir in samples:
        tr.push(t_ms / 1000.0, float(ir))
    return tr


def doubles(tr):
    """数"一次搏动被数成两次"：相邻搏动时刻里短于 0.6×中位间隔的那几个。

    为什么要单独数它：`beats` 和 BPM 都盖得住它 —— 真人那段录里 18 拍看着比
    期望的 16 拍还"多"，而多出来的正是舒张期小峰（0.27 s 那种），
    不看时刻表就发现不了。
    """
    t = list(tr.beat_times)
    if len(t) < 3:
        return 0, 0
    d = [b - a for a, b in zip(t, t[1:])]
    s = sorted(d)
    med = s[len(s) // 2]
    return sum(1 for x in d if x < 0.6 * med), len(d)


def sect_gain(sections, f, fs=FS):
    """一串二阶节在频率 f 上的**幅频增益**（直接代 H(e^jω)，不放信号进去跑）。"""
    w = 2.0 * math.pi * f / fs
    z = complex(math.cos(-w), math.sin(-w))
    out = 1.0
    for sec in sections:
        out *= abs((sec.b0 + sec.b1 * z + sec.b2 * z * z)
                   / (1.0 + sec.a1 * z + sec.a2 * z * z))
    return out


def verdict(got, truth, want):
    if want == 'none':
        return got is None
    return got is not None and abs(got - truth) <= 3.0


def row(name, make, peak_frac=None, env_decay=None):
    red = []
    for cname, truth, want, w in WAVES:
        tr = run(make, w, peak_frac, env_decay)
        if not verdict(tr.bpm(), truth, want):
            red.append('%s=%s' % (cname, 'None' if tr.bpm() is None else '%.1f' % tr.bpm()))
    tr = run(make, REAL, peak_frac, env_decay)
    return red, tr


REAL = None


def main():
    global REAL
    REAL = load_real()
    ac = ref_bpm([v for _, v in REAL])
    say('真人录制：%d 样本 / %.1f s   裁判（0.8~2.5 Hz 最强的频点）= %.1f BPM'
        % (len(REAL), len(REAL) / FS, ac or -1))
    say('          独立口径：runs/_hr_look.log 上同一段录的频谱峰也是 1.09 Hz = 65.4 BPM')
    say('          期望拍数 ≈ %.0f（15 s × %.0f BPM）' % (15.0 * ac / 60.0, ac))
    say('')
    say('  %-28s %-30s %s' % ('前端', '合成用例红项', '真人录：拍/双计/离散度/BPM（时）'))
    say('  ' + '-' * 96)

    for name, make in CONTROLS:
        red, tr = row(name, make)
        say('  %-28s %-30s %s' % (name, (','.join(red) or '无')[:30], real_cell(tr)))
    say('  ' + '-' * 96)
    for fc in CANDIDATE_FC:
        name = '4阶BW@%.2f + LP3.5%s' % (fc, '  ← 线上' if fc == 0.65 else '')
        red, tr = row(name, lambda fs, fc=fc: bw4(fc, fs))
        say('  %-28s %-30s %s' % (name, (','.join(red) or '无')[:30], real_cell(tr)))

    say('')
    say('为什么拐点 0.65 —— 直接算传递函数，看滤完之后 artifact 和心跳谁更大：')
    say('  artifact 幅度 201（0.53 Hz） vs 心跳 132（1.09 Hz）—— runs/_hr_look.log 的频谱。')
    say('  所以要让心跳赢，两者增益之比必须大过 201/132 = %.2f。' % (201.0 / 132.0))
    say('  %-8s %14s %14s %8s %s' % ('拐点', '0.53Hz 增益', '1.09Hz 增益', '比值', '谁赢'))
    for fc in CANDIDATE_FC:
        g_art = sect_gain(bw4(fc, FS), 0.53)
        g_hrt = sect_gain(bw4(fc, FS), 1.09)
        r = g_hrt / g_art
        who = '心跳' if r > 201.0 / 132.0 else 'artifact'
        say('  %-8.2f %14.3f %14.3f %8.2f %s%s'
            % (fc, g_art, g_hrt, r, who, '   ← 线上' if fc == 0.65 else ''))

    say('')
    say('再扫包络衰减 τ（ENV_DECAY，100 Hz；0.995=τ2s, 0.998=τ5s, 0.999=τ10s）：')
    say('  道理：包络在两次搏动之间往下掉，阈值也跟着掉 —— 舒张期那个小鼓包')
    say('        （约主峰的 0.35）本来不该过 0.45 的线，是"env 掉下去了"才过的。')
    for fc in (0.60, 0.65, 0.70):
        for ed in (0.995, 0.998, 0.999):
            red, tr = row('x', lambda fs, fc=fc: bw4(fc, fs), 0.45, ed)
            say('  fc=%.2f ENV_DECAY=%.3f  红 %-24s %s'
                % (fc, ed, (','.join(red) or '无')[:24], real_cell(tr)))

    say('')
    say('真人录制上的搏动时刻（秒）—— 一眼看出漏拍（整段缺一块）和双计（两个挨在一起）：')
    for fc in (0.65, 0.70):
        for ed in (0.995, 0.999):
            tr = run(lambda fs, fc=fc: bw4(fc, fs), REAL, 0.45, ed)
            say('  fc=%.2f ENV_DECAY=%.3f  %s' % (fc, ed,
                ' '.join('%.2f' % t for t in tr.beat_times)))
    return 0


def real_cell(tr):
    bpm = tr.bpm()
    spr = tr.ibi_spread()
    nd, _ = doubles(tr)
    return '%2d 拍  %d 双计  %s  %s' % (tr.beats, nd,
                                       '—' if spr is None else '离散度 %.3f' % spr,
                                       'None' if bpm is None else '%.1f BPM' % bpm)


if __name__ == '__main__':
    try:
        rc = main()
    except Exception as e:
        import traceback
        say('!!!! 异常：%r' % (e,))
        say(traceback.format_exc())
        rc = 1
    with io.open(os.path.join(ROOT, 'runs', '_hr_ab_front.log'), 'w',
                 encoding='utf-8') as f:
        f.write('\n'.join(OUT) + '\n')
    print('hr ab front: rc=%d' % rc)
    sys.exit(rc)
