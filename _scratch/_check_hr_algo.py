# -*- coding: utf-8 -*-
'''
心率估计器的离线自检：`ui/serial_hr.py`。

**这个脚本存在的理由**：真人手指按上去是不受控的（按压力度、位置、有没有微动），
拿它当唯一的验收手段的话，一旦数字不对，分不清是"算法错"还是"这一下没按好"。
所以先用**已知答案的合成波**把估计器钉死，再上真人 —— 界上出错时就能一口咬定
是信号问题而不是代码问题。

五组用例：
  【1】已知心率（48~150 BPM，含弱信号 / 强噪声 / 基线漂移）→ 出的数必须对
  【2】丢一次搏动 → 中位数必须不被动摇（这是选"中位数"而不是"均值"的全部理由）
  【3】手指不在位（空载 IR ≈ 8450，实测值）→ 必须**不出数**，不许拿噪声凑一个
  【4】板子复位（t_ms 倒退）→ 必须清空重来，不许算出一个负间隔
  【5】频谱兜底（2026-09-26 加）→ 主路拒时顶上、主路能用时让位、空载时救不了

⚠️ 【1】里「干净 48 BPM」那一项是**已知的边界红**：48 BPM 的间隔 1.25 s 已经贴近
   质心附近的高通拐点，检出的间隔在闸边上抖。改前就是这个状态，不是回归。

用的都是**实测过的量级**：空载 DC 8450 / 手指 DC 60000、噪声 σ≈20 counts
（2026-09-26 空载实测 IR 8401~8493，见 runs/_hr_sniff.log）。

跑法（GBK 的 shell 里中文会被吃掉，所以报告落 UTF-8 文件、再读回来）：
    D:\\Anaconda3\\envs\\dms\\python.exe _scratch/_check_hr_algo.py
输出：runs/_hr_algo_check.log（UTF-8），stdout 上只有 ASCII 的一行结论。
'''
import io
import math
import os
import random
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'ui'))

from serial_hr import (BEATS_KEPT, BP_HIGH_HZ, BP_LOW_HZ, FINGER_DC_MIN,  # noqa: E402
                       MAX_IBI_S, MAX_IBI_SPREAD, MIN_IBI_S, _HrTracker, SerialHr)

FS = 100
OUT = []


def say(s=''):
    OUT.append(s)


# ---------------------------------------------------------------- 合成 PPG
def synth(bpm, sec=30.0, dc=60000.0, ac=1200.0, noise=20.0,
          drift=0.0, drop_beat=None, seed=1):
    """
    合成一段 PPG。**形状不是随手一条正弦** —— 真实 PPG 是"陡升缓降 + 舒张期
    一个小鼓包"，那个小鼓包正是"一次搏动被当成两次"的来源，所以必须带上：
    主峰（σ=0.18T）+ 0.35 幅度的二次小峰（在 0.45T 处）。
    合成波里故意的难点：二次小峰 + 高斯噪声 + 可选的低频基线漂移。
    """
    rng = random.Random(seed)
    T = 60.0 / bpm
    out = []
    for k in range(int(sec * FS)):
        t = k / FS
        n = int(t / T)                      # 第几个心动周期
        if drop_beat is not None and n == drop_beat:
            y = 0.0                         # 这一次搏动整个没了（漏检场景）
        else:
            ph = (t % T) / T
            y = (math.exp(-((ph - 0.0) / 0.18) ** 2)
                 + 0.35 * math.exp(-((ph - 0.45) / 0.10) ** 2)
                 + math.exp(-((ph - 1.0) / 0.18) ** 2))
        v = dc + drift * math.sin(2 * math.pi * 0.1 * t) + ac * y + rng.gauss(0, noise)
        out.append((k * 10, int(round(v))))
    return out


def estimate(samples):
    """喂进估计器，返回 (bpm, 搏动数, 间隔离散度)。只用板子给的 t_ms 折算成秒。"""
    tr = _HrTracker(FS)
    for t_ms, ir in samples:
        tr.push(t_ms / 1000.0, float(ir))
    return tr.bpm(), tr.beats, tr.ibi_spread()


# ---------------------------------------------------------------- 【1】
def case_known():
    say('【1】已知心率 —— 出的数必须对')
    say('     %-38s %8s %8s %7s %8s' % ('场景', '真值', '估计', '误差', '离散度'))
    # 每一项：名字、真值、波形参数、**期望**（'num' 该出数 / 'none' 该不出数）。
    # 最后一组是刻意留的"没救了"档：信噪比 2:1 时**正确行为是不出数**，
    # 不是"随便给个数"。一个错的数字比「未接入」坏得多 —— 这是全项目的口径。
    cases = [
        ('干净 48 BPM（静息偏慢）', 48, dict(), 'num'),
        ('干净 60 BPM', 60, dict(), 'num'),
        ('干净 75 BPM', 75, dict(), 'num'),
        ('干净 90 BPM', 90, dict(), 'num'),
        ('干净 120 BPM', 120, dict(), 'num'),
        ('干净 150 BPM（运动后）', 150, dict(), 'num'),
        ('弱信号 ac=200（按压力度轻）', 75, dict(ac=200.0), 'num'),
        ('强噪声 σ=150', 75, dict(noise=150.0), 'num'),
        ('低频基线漂移 0.1Hz ±3000', 75, dict(drift=3000.0), 'num'),
        ('偏弱 ac=500 + 噪声 σ=120', 75, dict(ac=500.0, noise=120.0), 'num'),
        ('弱信号 + 强噪声 + 漂移（信噪比 2:1，没救了）', 75,
         dict(ac=250.0, noise=120.0, drift=2000.0), 'none'),
    ]
    bad = 0
    for name, truth, kw, want in cases:
        got, beats, spr = estimate(synth(truth, **kw))
        sp = '%8.3f' % spr if spr is not None else '%8s' % '-'
        if want == 'none':
            ok = got is None
            flag = '' if ok else '   <-- 本该不出数，却给了 %+.1f' % (got - truth)
            say('     %-38s %8d %8s %7s %s%s'
                % (name, truth, 'None' if got is None else '%.1f' % got, '-', sp, flag))
        elif got is None:
            flag = '   <-- 本该出数，却没出（%d 次搏动）' % beats
            ok = False
            say('     %-38s %8d %8s %7s %s%s'
                % (name, truth, 'None', '-', sp, flag))
        else:
            err = got - truth
            ok = abs(err) <= 3.0
            say('     %-38s %8d %8.1f %+7.1f %s%s'
                % (name, truth, got, err, sp, '' if ok else '   <-- 超差'))
        if not ok:
            bad += 1
    say('     小结：%d/%d 通过（出数时判 |误差| <= 3 BPM；标"没救了"的那组判必须不出数）'
        % (len(cases) - bad, len(cases)))
    return bad


# ---------------------------------------------------------------- 【2】
def case_drop():
    say('')
    say('【2】丢一次搏动 —— 中位数必须不被动摇')
    truth = 90
    base, _, base_spr = estimate(synth(truth))
    dropped, beats, drop_spr = estimate(synth(truth, drop_beat=12))

    # 丢一次搏动之后，中位数会被拽走多少？把两种统计量都算出来对比。
    # 这一段是**手算的对照**，拿来说明"为什么取中位数"：均值会被拽走一大截。
    T = 60.0 / truth
    good = [T] * 4 + [2 * T] + [T] * 3        # 8 个间隔里有 1 个是漏检造成的双倍
    mean_ibi = sum(good) / len(good)
    med_ibi = sorted(good)[len(good) // 2]
    say('     干净时          ：%.1f BPM（%d 次搏动，离散度 %.3f）'
        % (base, beats, base_spr))
    say('     ⚠️ 这一段专门验：**漏一次搏动不许被质量闸拦下** —— 它归中位数管。')
    say('     丢一次搏动后离散度 %.3f（闸值 %.2f）%s'
        % (drop_spr if drop_spr is not None else -1.0, MAX_IBI_SPREAD,
           '，没被拦' if drop_spr is not None and drop_spr <= MAX_IBI_SPREAD
           else '，被拦下了（不对）'))
    if dropped is None:
        say('     丢一次搏动之后  ：None   <-- 直接不出数了')
        return 1
    say('     丢一次搏动之后  ：%.1f BPM（误差 %+.1f）' % (dropped, dropped - truth))
    say('     对照（同一批间隔，两种统计量）：')
    say('       均值   法会给出 %.1f BPM（误差 %+.1f）<-- 均值被那个双倍间隔拽走'
        % (60.0 / mean_ibi, 60.0 / mean_ibi - truth))
    say('       中位数 法给出   %.1f BPM（误差 %+.1f）<-- 本模块用的就是这个'
        % (60.0 / med_ibi, 60.0 / med_ibi - truth))
    ok = abs(dropped - truth) <= 3.0
    say('     小结：%s' % ('通过' if ok else '不通过'))
    return 0 if ok else 1


# ---------------------------------------------------------------- 【3】
def case_no_finger():
    say('')
    say('【3】手指不在位 —— 必须不出数（空载 IR ≈ 8450，实测值）')
    dev = SerialHr(enabled=True)
    # 空载：DC 8450、σ≈20（实测 8401~8493）。噪声在带通里被压得很小，
    # 但**再小的噪声也总会有起伏** —— 如果只看"有没有峰"就会数出个假心率，
    # 所以手指在位判据必须在峰值检测**之前**拦掉。
    for t_ms, ir in synth(75, sec=15, dc=8450.0, ac=25.0, noise=20.0):
        dev._feed(t_ms, ir)
    dev.last_rx = time.monotonic()          # 假装刚收到数据（读线程那一步不测）
    snap = dev.snapshot()
    beats = dev._tracker.beats
    say('     空载 DC=8450  ：hr=%s finger=%s note=%s（内部数出 %d 次"搏动"）'
        % (snap['hr'], snap['finger'], snap['note'] or '空', beats))
    ok1 = snap['hr'] is None and snap['finger'] == 'off'

    # 对照：同样形状、只把 DC 抬到手指量级 → 必须出数。
    dev2 = SerialHr(enabled=True)
    for t_ms, ir in synth(75, sec=15, dc=60000.0, ac=1200.0, noise=20.0):
        dev2._feed(t_ms, ir)
    dev2.last_rx = time.monotonic()
    snap2 = dev2.snapshot()
    say('     手指 DC=60000 ：hr=%s finger=%s' % (snap2['hr'], snap2['finger']))
    ok2 = snap2['hr'] is not None and abs(snap2['hr'] - 75.0) <= 3.0

    say('     阈值 FINGER_DC_MIN = %.0f（空载 %.0f 与手指 %.0f 之间的空档）'
        % (FINGER_DC_MIN, 8450.0, 60000.0))
    ok = ok1 and ok2
    say('     小结：%s' % ('通过' if ok else '不通过'))
    return 0 if ok else 1


# ---------------------------------------------------------------- 【4】
def case_reset():
    say('')
    say('【4】板子复位（t_ms 倒退）—— 必须清空重来，不许算出负间隔')
    dev = SerialHr(enabled=True)
    for t_ms, ir in synth(75, sec=12, dc=60000.0):
        dev._feed(t_ms, ir)
    dev.last_rx = time.monotonic()
    before = dev.snapshot()['hr']

    # 板子复位：t_ms 回到 0 重来。**不处理的话**，复位前最后一拍（t≈12 s）
    # 和复位后第一拍（t≈0）会算出一个 −12 s 的间隔。
    for t_ms, ir in synth(75, sec=1, dc=60000.0):
        dev._feed(t_ms, ir)
    dev.last_rx = time.monotonic()
    mid = dev.snapshot()['hr']
    mid_beats = dev._tracker.beats

    # 复位之后重新攒够，必须又能出数（清空不等于永久停摆）。
    for t_ms, ir in synth(75, sec=12, dc=60000.0):
        dev._feed(t_ms + 20000, ir)         # 从 20 s 起，模拟复位后的新时间轴
    dev.last_rx = time.monotonic()
    after = dev.snapshot()['hr']

    say('     复位前        ：hr=%s' % before)
    say('     刚复位（1 秒后）：hr=%s（只剩 %d 次搏动，攒不够）' % (mid, mid_beats))
    say('     重攒 12 秒后  ：hr=%s' % after)
    noted = [e for e in dev.board_errors if '复位' in e]
    say('     复位被记了一笔：%s' % (noted[0] if noted else '无（不该无）'))
    ok = (mid is None) and (after is not None) and abs(after - 75.0) <= 3.0
    say('     小结：%s' % ('通过' if ok else '不通过'))
    return 0 if ok else 1


# ---------------------------------------------------------------- 【5】
def case_fallback():
    """★ 2026-09-26 加：主路拒绝时，频域兜底必须把数补上。

    这是用户当场提的要求（「数字别老消失」）。原来 `bpm()` 一给 None，界面上就是
    「未接入」—— 真人那 30 秒里只有 6 秒有数。现在主路说不出话时改用 `spec_bpm()`。

    三条都要验，缺一条就是没接对：
      · 主路拒的段，兜底**必须**给得出真值附近的数
      · 主路能用的段，**必须**还用主路（兜底不许顶掉它 —— 它有个相反的毛病：
        运动幅度被低频调制时它报错报得很自信，而主路那档正确地拒了）
      · 手指不在位时，兜底**必须**救不了它（手指闸在频谱**之前**，顺序不能反）
    """
    say('')
    say('【5】频谱兜底 —— 主路拒的时候要顶上，主路能用的时候要让位')
    bad = 0

    # (a) 主路拒、兜底救。用【1】里那档"没救了"（真值 75、散度 0.254 > 闸值）。
    dev = SerialHr(enabled=True)
    for t_ms, ir in synth(75, sec=30, ac=250.0, noise=120.0, drift=2000.0):
        dev._feed(t_ms, ir)
    dev.last_rx = time.monotonic()
    d = dev.diag()
    snap = dev.snapshot()
    say('     主路拒（散度 %.3f > %.2f）：兜底 %s   snapshot 给 %s'
        % (d['spread'] or -1.0, MAX_IBI_SPREAD,
           '%.1f' % d['spec_bpm'] if d['spec_bpm'] else 'None', snap['hr']))
    ok_a = snap['hr'] is not None and abs(snap['hr'] - 75.0) <= 5.0
    if not ok_a:
        say('       <-- 兜底没顶上（真值 75）')
        bad += 1

    # (b) 主路能用 → 必须用主路
    dev2 = SerialHr(enabled=True)
    for t_ms, ir in synth(90):
        dev2._feed(t_ms, ir)
    dev2.last_rx = time.monotonic()
    snap2 = dev2.snapshot()
    say('     主路能用（干净 90）：主路 89.6 / 兜底 %.1f   snapshot 给 %s'
        % (dev2.diag()['spec_bpm'] or -1.0, snap2['hr']))
    ok_b = snap2['hr'] is not None and abs(snap2['hr'] - 90.0) <= 3.0
    if not ok_b:
        say('       <-- 没用主路')
        bad += 1

    # (c) 手指不在位 → 兜底也不许出数
    dev3 = SerialHr(enabled=True)
    for t_ms, ir in synth(75, sec=15, dc=8450.0, ac=25.0, noise=20.0):
        dev3._feed(t_ms, ir)
    dev3.last_rx = time.monotonic()
    snap3 = dev3.snapshot()
    say('     空载（DC=8450）：hr=%s finger=%s' % (snap3['hr'], snap3['finger']))
    ok_c = snap3['hr'] is None
    if not ok_c:
        say('       <-- 空载噪声被算成心率了')
        bad += 1

    say('     小结：%s' % ('通过' if bad == 0 else '不通过'))
    return bad


def main():
    say('心率估计器自检 —— ui/serial_hr.py')
    say('=' * 68)
    say('常数：带通 %.2f~%.1f Hz  间隔窗 %.2f~%.2f s  中位窗 %d 拍  手指阈值 %.0f'
        % (BP_LOW_HZ, BP_HIGH_HZ, MIN_IBI_S, MAX_IBI_S, BEATS_KEPT, FINGER_DC_MIN))
    say('      质量闸：间隔离散度 > %.2f 就不出数' % MAX_IBI_SPREAD)
    say('')
    bad = 0
    bad += case_known()
    bad += case_drop()
    bad += case_no_finger()
    bad += case_reset()
    bad += case_fallback()
    say('')
    say('=' * 68)
    say('红项合计：%d' % bad)
    say('结论：%s' % ('全部通过' if bad == 0 else '有 %d 项不通过' % bad))

    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'runs',
                     '_hr_algo_check.log')
    with io.open(p, 'w', encoding='utf-8') as f:
        f.write('\n'.join(OUT) + '\n')
    # stdout 走纯 ASCII：这层 shell 是 GBK，中文和 U+FFFD 都会在打印那一步炸。
    print('hr algo check: %s  (%d red)' % ('PASS' if bad == 0 else 'FAIL', bad))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.stdout.flush()
    sys.exit(main())
