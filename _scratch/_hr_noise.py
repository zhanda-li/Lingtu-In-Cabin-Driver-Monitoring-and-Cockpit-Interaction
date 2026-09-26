# -*- coding: utf-8 -*-
'''
这块板子**真实的噪声有多大** —— 决定 `AC_MIN_RMS` 到底该定多少的那个数。

## 为什么非量它不可

`_hr_acfloor2.py` 那张表里，"没有脉搏"那组是**我自己合成的白噪声**，σ 是我随手
挑的（2/5/20/50/100/200）。σ=200 那档算出来的带通交流 RMS 是 49.8，
而验收脚本最弱的有脉搏那档（ac=200）是 54.2 —— **只差 1.09 倍，绝对阈值分不开**。
σ=5 那档是 1.3，那就差 40 倍，阈值随便定。

所以"绝对阈值行不行"完全取决于**真实噪声落在哪**，而不是取决于我合成到哪。
自己挑噪声去论证自己的阈值 = 循环论证。

## 怎么从已有数据里量出真实噪声（不用串口）

`runs/_hr_raw.txt`（唯一一段真人录，100 Hz、15 s）里，**脉搏在 1 Hz 附近**，
所以 **10 Hz 以上那部分全是噪声**（PPG 的谐波到不了那儿，电源/环境光闪烁
在 50/100 Hz，混叠下来也在高频）。用高通把 >10 Hz 抠出来算 RMS，
就是逐样本噪声 σ 的一个可靠估计。

再把它投回带通（0.65~3.5 Hz，宽 2.85 Hz，Nyquist 50 Hz）：
白噪声过 2.85/50 = 5.7% 的带宽，**带内噪声 RMS ≈ σ × √0.057 ≈ σ × 0.24**。
这个投影值才是和 `AC_MIN_RMS` 同量纲的东西。

★ 这段录的是**手指按着**的时候，所以量出来的是"信号在的时候的噪声"；
手指拿开只有环境光时的噪声可能更大（也可能是直流饱和后噪声反而变小）——
**这一点这份数据答不了**，脚本末尾会说清楚，不许拿它冒充。

用法：D:\\Anaconda3\\envs\\dms\\python.exe _scratch/_hr_noise.py
输出：runs/_hr_noise.log（UTF-8）
'''
import io
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'ui'))

OUT = []


def say(s=''):
    OUT.append(s)


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


def bp_apply(x, fs, sections):
    """把一串样本过一组 _Biquad（和线上同一个类，不重写）。"""
    from serial_hr import _Biquad
    out = []
    secs = [_Biquad(*s) for s in sections]
    for v in x:
        y = v
        for s in secs:
            y = s.push(y)
        out.append(y)
    return out


def rms(v):
    if not v:
        return 0.0
    return math.sqrt(sum(a * a for a in v) / len(v))


def main():
    from serial_hr import SAMPLE_RATE_HZ, BP_LOW_HZ, BP_HIGH_HZ, BW4_Q

    real = load_real()
    fs = float(SAMPLE_RATE_HZ)
    ir = [float(r[1]) for r in real]
    say('这块板子真实噪声有多大 —— 从 runs/_hr_raw.txt 反推')
    say('=' * 84)
    say('样本 %d 个 = %.1f 秒 @ %.0f Hz，IR %.0f~%.0f'
        % (len(ir), len(ir) / fs, fs, min(ir), max(ir)))
    say('')

    # ---- 噪声 σ：一阶差分的稳健估计。逐样本白噪声下 Var(Δ) = 2σ²。
    d = [ir[i + 1] - ir[i] for i in range(len(ir) - 1)]
    d = sorted(d)
    n = len(d)
    mad = sorted(abs(x - d[n // 2]) for x in d)[n // 2]
    sigma_mad = mad * 1.4826 / math.sqrt(2.0)
    mean_d = sum(d) / n
    sd = math.sqrt(sum((x - mean_d) ** 2 for x in d) / n) / math.sqrt(2.0)
    say('逐样本噪声 σ（一阶差分反推）：')
    say('  稳健估计（MAD）  σ ≈ %.2f 个数' % sigma_mad)
    say('  含离群（标准差）  σ ≈ %.2f 个数   ← 两者差得多说明有尖刺' % sd)
    say('')

    # ---- >10 Hz 高通，直接量高频噪声
    hp10 = bp_apply(ir, fs, [(10.0, fs, 'hp', BW4_Q[0]), (10.0, fs, 'hp', BW4_Q[1])])
    # 丢前 200 个（滤波器起来那一段是暂态，不是噪声）
    n_hi = rms(hp10[200:])
    say('10 Hz 以上实测 RMS（前 2 s 丢掉，避开暂态）：%.2f 个数' % n_hi)
    say('  （脉搏在 1 Hz 附近，到不了这儿 —— 这一段就是噪声本体）')
    say('')

    # ---- 噪声投回带通
    bwm = max(0.0, BP_HIGH_HZ - BP_LOW_HZ)
    frac = bwm / (fs / 2.0)
    say('白噪声投回 %.2f~%.2f Hz 带通：带宽占比 %.4f，投影系数 %.4f'
        % (BP_LOW_HZ, BP_HIGH_HZ, frac, math.sqrt(frac)))
    say('  → 带内噪声 RMS ≈ %.2f × %.4f = %.2f 个数'
        % (n_hi, math.sqrt(frac), n_hi * math.sqrt(frac)))
    say('')

    # ---- 同一段录的带内交流（信号 + 噪声），做对照
    bp = bp_apply(ir, fs, [(BP_LOW_HZ, fs, 'hp', BW4_Q[0]),
                           (BP_LOW_HZ, fs, 'hp', BW4_Q[1]),
                           (BP_HIGH_HZ, fs, 'lp', 0.7071)])
    seg = bp[200:]
    n_lo = rms(seg)
    say('同一段的**带内**交流 RMS（脉搏 + 噪声）：%.1f 个数' % n_lo)
    say('  信噪比 ≈ %.1f 倍（功率 %.0f 倍）'
        % (n_lo / max(1e-9, n_hi * math.sqrt(frac)),
           (n_lo / max(1e-9, n_hi * math.sqrt(frac))) ** 2))
    say('')

    say('★ 结论：真实噪声的带内投影比真手指的信号低 %.0f 倍左右。'
        % (n_lo / max(1e-9, n_hi * math.sqrt(frac))))
    say('  所以 `_hr_acfloor2.py` 里 σ=100/200 那两档**不代表这块板子**——')
    say('  它们只是把"合成噪声"推到多高才追上有脉搏那侧，用来证明')
    say('  **绝对阈值不是万能的**，不是用来给阈值找位置的。')
    say('')
    say('⚠️ 这份数据答不了的一件事：**手指拿开、只有环境光**时的噪声。')
    say('   上面量的全是"手指按着"的时候。饱和之后噪声可能变大也可能变小')
    say('   （直流顶到满量程时 ADC 会削顶），这里是**没有证据**的状态，')
    say('   不许拿"手指按着时的噪声"冒充它。真手指离下限的余量够大，')
    say('   所以下限先贴着噪声那侧定；真要坐实得拿串口录一段空载高直流。')

    with io.open(os.path.join(ROOT, 'runs', '_hr_noise.log'), 'w',
                 encoding='utf-8') as f:
        f.write('\n'.join(OUT) + '\n')
    return 0


if __name__ == '__main__':
    rc = 0
    try:
        rc = main()
    finally:
        print('hr noise: %s' % ('OK' if rc == 0 else 'rc%d' % rc))
    sys.exit(rc)
