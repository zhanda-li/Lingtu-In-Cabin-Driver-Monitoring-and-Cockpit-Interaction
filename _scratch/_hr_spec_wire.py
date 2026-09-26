# -*- coding: utf-8 -*-
'''
验「频谱兜底」真的接上了：主路拒的时候，`snapshot()` 会不会给出频域那个数。

以及量它的**耗时** —— 它在 `snapshot()` 里跑，而 `snapshot()` 和读线程共用一把锁，
太慢会拖住串口读取。这是接上它之前必须知道的数。

用法：D:\\Anaconda3\\envs\\dms\\python.exe _scratch/_hr_spec_wire.py
输出：runs/_hr_spec_wire.log
'''
import io
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'ui'))

from serial_hr import SPEC_EVERY_S, SerialHr, _HrTracker  # noqa: E402

sys.path.insert(0, HERE)
from _hr_spec import bandpass, synth  # noqa: E402

OUT = []


def say(s=''):
    OUT.append(s)


def feed(dev, samples):
    """`_hr_spec.synth` 返回的是纯 float 列表（它自己按 100 Hz 算时间轴）。"""
    for i, v in enumerate(samples):
        dev._feed(i * 10, int(round(v)))
    dev.last_rx = time.monotonic()


def main():
    say('频谱兜底接线检查')
    say('=' * 74)

    # ---- 1) 主路拒、兜底救：就用合成里"没救了"那一档（真值 75）
    say('【1】合成「没救了」档（真值 75）—— 主路拒，兜底必须给得出 75 附近')
    dev = SerialHr(enabled=True)
    feed(dev, synth(75, sec=30, ac=250.0, noise=120.0, drift=2000.0))
    d = dev.diag()
    snap = dev.snapshot()
    say('      主路 bpm      ：None（离散度 %.3f > 0.20）' % (d['spread'] or -1))
    say('      兜底 spec_bpm ：%s   （缓冲 %d 点 = %.1f 秒）'
        % (d['spec_bpm'], d['spec_n'], d['spec_n'] / 25.0))
    say('      snapshot 给的 ：hr=%s finger=%s' % (snap['hr'], snap['finger']))
    ok1 = snap['hr'] is not None and abs(snap['hr'] - 75.0) <= 5.0

    # ---- 2) 主路能用时，必须以主路为准（不许被兜底顶掉）
    say('')
    say('【2】干净 90 BPM —— 主路能用，必须用主路（兜底不许顶掉它）')
    dev2 = SerialHr(enabled=True)
    feed(dev2, synth(90))
    d2 = dev2.diag()
    snap2 = dev2.snapshot()
    say('      主路 bpm      ：90 附近（离散度 %.3f）' % (d2['spread'] or -1))
    say('      兜底 spec_bpm ：%s' % d2['spec_bpm'])
    say('      snapshot 给的 ：hr=%s' % snap2['hr'])
    ok2 = snap2['hr'] is not None and abs(snap2['hr'] - 90.0) <= 3.0

    # ---- 3) 手指不在位 —— 兜底**不许**把空载噪声算成心率
    say('')
    say('【3】手指不在位（空载 DC=8450，实测值）—— 兜底必须救不了它')
    dev3 = SerialHr(enabled=True)
    feed(dev3, synth(75, sec=15, dc=8450.0, ac=25.0, noise=20.0))
    snap3 = dev3.snapshot()
    say('      snapshot 给的 ：hr=%s finger=%s（手指闸在频谱之前拦掉）'
        % (snap3['hr'], snap3['finger']))
    ok3 = snap3['hr'] is None

    # ---- 4) 耗时：DFT 一次多少毫秒，以及节流有没有生效
    say('')
    say('【4】耗时 —— 它跑在 snapshot 里，和读线程共用锁')
    tr = _HrTracker()
    y = bandpass(synth(75, sec=12))
    for i, v in enumerate(y):
        tr.push(i / 100.0, float(v))
    tr._spec_v, tr._spec_t = None, -1e9
    t0 = time.perf_counter()
    v = tr.spec_bpm()
    dt = (time.perf_counter() - t0) * 1000.0
    say('      缓冲 %d 点（%.1f 秒，抽过 %d 倍）  一次算下来 %.1f ms  → %.1f BPM'
        % (len(tr.slow), len(tr.slow) / 25.0, 4, dt, v))
    t0 = time.perf_counter()
    for _ in range(50):
        tr.spec_bpm()
    dt2 = (time.perf_counter() - t0) * 1000.0 / 50.0
    say('      连问 50 次平均 %.3f ms（节流生效 → 应该远小于上一次）' % dt2)
    say('      节流窗口 SPEC_EVERY_S = %.1f s：%.1f ms 占它 %.1f%%'
        % (SPEC_EVERY_S, dt, dt / (SPEC_EVERY_S * 1000.0) * 100.0))
    ok4 = dt < 200.0 and dt2 < 5.0

    say('')
    say('=' * 74)
    say('结论：%s' % ('全过' if (ok1 and ok2 and ok3 and ok4) else '有不通过的'))
    return 0 if (ok1 and ok2 and ok3 and ok4) else 1


if __name__ == '__main__':
    rc = 1
    try:
        rc = main()
    except Exception as e:
        import traceback
        say('!!!! 异常：%r' % (e,))
        say(traceback.format_exc())
    with io.open(os.path.join(ROOT, 'runs', '_hr_spec_wire.log'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(OUT) + '\n')
    print('hr spec wire: rc=%d' % rc)
    sys.exit(rc)
