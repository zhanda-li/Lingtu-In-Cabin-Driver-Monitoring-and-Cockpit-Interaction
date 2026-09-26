# -*- coding: utf-8 -*-
'''
「冻在 119.9 不动」这个 bug 的验收 —— 不需要串口。

## 症状与根因（2026-09-26，用户原话「现在心率还不是实时的」）

实测：20 秒 159 帧里 `hr` **只有 1 个值**（119.9），同一帧里 pitch/ear/mar/p_fat
全都是 159 个不同的值 —— 所以 tick 是活的，**冻的只有心率这一路**。

读代码 + 离线复现得到两条独立的结构性毛病，都在 `ui/serial_hr.py`：

  ① `bpm()` 是**队列的纯函数，一个时间项都没有**。`ibis` 那 8 个间隔一旦不再进
     新值，它就永远返回同一串间隔的中位数 —— 屏幕上一个化石，而 `finger` 还写着 on，
     更糟的是它非 None 就**把频谱兜底整个挡住了**。
  ② 峰值检波的阈值是 `PEAK_FRAC * env`，**把自己的尺度归一化了**：输入只剩噪声，
     包络缩小、阈值跟着缩小，于是噪声里照样"找到"搏动，报出一串**会动**的错数。
     ①的时效救不了它 —— 噪声确实在不停产生搏动。

所以修法是两道，各治一条：`IBI_FRESH_S`（时效，治①的化石）+ `AC_MIN_RMS`
（带内交流的绝对下限，治②的信噪比）—— 后者在 `snapshot()` 出口，两条路一起卡。

## 这个脚本怎么验

同一段输入跑**两遍**，只差两个常数：

  「改前」= `IBI_FRESH_S → 1e9`、`AC_MIN_RMS → 0`   ← 等价于原来那套逻辑
            （原来压根没有这两个判据，不是"设成很小的值"，是**不存在**）
  「改后」= 线上的真值

输入 = 唯一那段真人录（`runs/_hr_raw.txt`，15 s，真有脉搏，≈64.7 BPM）
接 60 s「直流一样高、**没有脉搏**」（手指还压着但没搏动／环境光饱和，数据上同一种）。

★ 判据看的是 `snapshot()` 给的 `hr`（**界面看到的就是它**），不是 `bpm()` ——
  `bpm()` 是内部量，`snapshot()` 才是出口。两个都打出来，但结论以 snapshot 为准。

⚠️ 这里**不复现 119.9 这个具体数字**：那要真录波。这个脚本验的是**机制**——
"信号没了以后，屏幕上还会不会一直挂着一个数"。数字是多少是噪声说了算。

用法：D:\\Anaconda3\\envs\\dms\\python.exe _scratch/_hr_fossil.py
输出：runs/_hr_fossil.log（UTF-8）
'''
import io
import os
import random
import sys
import time

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


def build_input(noise=5.0, sec_nopulse=60.0):
    real = load_real()
    dc_hi = 123000.0
    rnd = random.Random(31415)
    tail = [(real[-1][0] + 10 * (i + 1),
             int(round(dc_hi + rnd.gauss(0.0, noise))))
            for i in range(int(sec_nopulse * 100))]
    return real + tail, len(real)


def run(tag, samples, n_real, fresh_s, ac_min):
    """跑一遍，每 0.5 秒（50 个样本）取一次 snapshot()。

    ⚠️ 分段按**样本序号**，不按时刻 —— 板子的 `t_ms` 是从上电算起的，
    这段录里它落在 645053~660040（即 645 s 起），拿 `t_ms/1000 <= 15` 去分
    会把**全部**真人样本分进"无脉搏段"（第一版就是这么错的：两臂的真人段
    都是 0 帧，然后打印时对 None 用 %.1f 崩掉）。
    """
    import serial_hr
    old = (serial_hr.IBI_FRESH_S, serial_hr.AC_MIN_RMS)
    serial_hr.IBI_FRESH_S, serial_hr.AC_MIN_RMS = fresh_s, ac_min
    try:
        dev = serial_hr.SerialHr(enabled=True)
        real_vals, no_vals = [], []
        for i, (t_ms, ir) in enumerate(samples):
            dev._feed(t_ms, ir)
            if i % 50:
                continue
            dev.last_rx = time.monotonic()      # 有数据在流，别被"串口停了"拦
            hr = dev.snapshot()["hr"]
            (real_vals if i < n_real else no_vals).append(hr)
        d = dev.diag()
    finally:
        serial_hr.IBI_FRESH_S, serial_hr.AC_MIN_RMS = old

    def stat(vals):
        n = [v for v in vals if v is not None]
        return {"tot": len(vals), "num": len(n),
                "lo": (min(n) if n else None), "hi": (max(n) if n else None),
                "frozen": longest_frozen(vals)}

    def longest_frozen(vals):
        """最长的一串**连续相同**的数 —— 化石的定义就是这个。"""
        best = cur = 0
        prev = object()
        for v in vals:
            if v is not None and v == prev:
                cur += 1
            else:
                cur = 1
            prev = v
            if v is not None:
                best = max(best, cur)
        return best

    say('【%s】  时效窗=%s  交流下限=%s' % (tag, fresh_s, ac_min))
    for label, vals in (('真人段', real_vals), ('无脉搏段', no_vals)):
        s = stat(vals)
        say('  %-6s %3d 帧：有数 %3d 帧（%3.0f%%）  范围 %s ~ %s   最长连续不变 %d 帧'
            % (label, s["tot"], s["num"], 100.0 * s["num"] / max(1, s["tot"]),
               ('%.1f' % s["lo"]) if s["lo"] is not None else '—',
               ('%.1f' % s["hi"]) if s["hi"] is not None else '—', s["frozen"]))
    say('  末帧判据值： ac_rms=%s  ibi_age=%s s  ibi_fresh=%s  spread=%s'
        % (d['ac_rms'], d['ibi_age'], d['ibi_fresh'], d['spread']))
    say('  末帧内部量： main_bpm=%s  spec_bpm=%s'
        % (d['main_bpm'] if d['main_bpm'] is None else '%.1f' % d['main_bpm'],
           d['spec_bpm'] if d['spec_bpm'] is None else '%.1f' % d['spec_bpm']))
    say('')
    return {"real": stat(real_vals), "none": stat(no_vals)}


def main():
    from serial_hr import IBI_FRESH_S, AC_MIN_RMS

    samples, n_real = build_input()
    say('心率「冻住的化石」验收 —— 喂进 snapshot()（界面看到的那一层）')
    say('=' * 88)
    say('输入：真人录 15.0 s（真脉搏，≈64.7 BPM）＋ 60 s「直流 12.3 万、没有脉搏」')
    say('      共 %d 个样本 = %.1f 秒（分段按样本序号，见 run() 的说明）'
        % (len(samples), len(samples) / 100.0))
    say('')

    before = run('改前', samples, n_real, 1e9, 0.0)
    after = run('改后', samples, n_real, IBI_FRESH_S, AC_MIN_RMS)
    b, a = before["none"], after["none"]
    br, ar = before["real"], after["real"]

    say('=' * 88)
    say('★ 「无脉搏段」—— 用户看到的就是这一段挂着一个数不动：')
    say('   改前  有数 %d/%d 帧（%3.0f%%）  最长连续不变 %d 帧 = %.1f 秒'
        % (b["num"], b["tot"], 100.0 * b["num"] / max(1, b["tot"]),
           b["frozen"], b["frozen"] * 0.5))
    say('   改后  有数 %d/%d 帧（%3.0f%%）  最长连续不变 %d 帧 = %.1f 秒'
        % (a["num"], a["tot"], 100.0 * a["num"] / max(1, a["tot"]),
           a["frozen"], a["frozen"] * 0.5))
    say('')
    say('★ 「真人段」—— 两道门**不许把它一起杀掉**：')
    say('   改前  有数 %d/%d 帧，范围 %.1f~%.1f' % (br["num"], br["tot"],
                                              br["lo"], br["hi"]))
    say('   改后  有数 %d/%d 帧，范围 %.1f~%.1f（真值 ≈64.7）'
        % (ar["num"], ar["tot"], ar["lo"], ar["hi"]))
    say('')
    # ⚠️ 判据**不是**"0 帧有数"—— 那是我第一版写错的（把 5 帧的拖尾判成不通过）。
    #    搏动一停，任何**逐拍更新**的显示都必然把最后一次测量再挂一会儿：
    #    屏幕上不可能在脉搏消失的那一帧就知道"它不会回来了"。
    #    所以"实时"的定义是**拖尾有界**，不是"立刻归零"；
    #    真正该被拦掉的是**无限期冻住**（改前：整段 120/120 帧、最长连续 25 帧 = 12.5 s）。
    #    上界由机制推出来 —— 最紧的那道门是 `IBI_FRESH_S`，超过它主路自己撒手，
    #    所以连续不变的帧数不可能超过它；有数帧数不超过 `IBI_FRESH_S / 0.5` 再取整 +1。
    hold_max = int(IBI_FRESH_S / 0.5) + 1
    ok = (a["frozen"] <= int(IBI_FRESH_S / 0.5) + 1
          and a["num"] <= hold_max
          and b["num"] > a["num"]                       # 必须真的更少
          and ar["num"] == br["num"]                    # 真人段一格都没被误伤
          and ar["lo"] is not None
          and abs((ar["lo"] + ar["hi"]) / 2.0 - 64.7) <= 3.0)
    say('结论：%s' % ('通过' if ok else '不通过'))
    say('  · 无脉搏段**不许无限期冻住**：最长连续不变 ≤ %d 帧（时效窗 %.1f s）'
        % (int(IBI_FRESH_S / 0.5) + 1, IBI_FRESH_S))
    say('    改前 %d 帧 = %.1f 秒 —— 那才是用户说的"不是实时"。'
        % (b["frozen"], b["frozen"] * 0.5))
    say('  · 无脉搏段有数帧数 ≤ %d 帧（同样的上界推出来的）' % hold_max)
    say('  · 真人段**逐帧一致**：改前 %d 帧 / 改后 %d 帧（一格都不许被误伤）'
        % (br["num"], ar["num"]))
    say('  · 真人段的数落在真值附近（%.1f~%.1f，真值 ≈64.7）'
        % (ar["lo"], ar["hi"]))
    say('')
    say('⚠️ 这里**不复现 119.9 这个具体数字** —— 那要真录波。验的是机制：')
    say('   信号没了以后，屏幕上还会不会一直挂着一个数。数字多少是噪声说了算。')

    with io.open(os.path.join(ROOT, 'runs', '_hr_fossil.log'), 'w',
                 encoding='utf-8') as f:
        f.write('\n'.join(OUT) + '\n')
    return 0 if ok else 1


if __name__ == '__main__':
    rc = 0
    try:
        rc = main()
    finally:
        print('hr fossil: %s' % ('OK' if rc == 0 else 'FAIL rc%d' % rc))
    sys.exit(rc)
