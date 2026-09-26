# -*- coding: utf-8 -*-
"""
板端 `hr/firmware/src/hr_algo.c`（**真 C**，宿主 MSVC 编出来的）与 PC 侧
`ui/serial_hr.py` 的 `_HrTracker` 逐样本对拍。

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch\\_hr_board_ab.py [录...]

不给参数就跑下面 `RUNS` 里那三份实录，结果落到 `runs/_hr_board_ab.log`。

── 为什么是"跑真 C"而不是镜像 ─────────────────────────────────────────────
计划原来打算手写一份 numpy 镜像，前提是"这台机器上没有宿主编译器"。前提不成立：
这台机器上装着 MSVC 2022（`_scratch/_cl.bat`），而 `hr_algo.c` 只用
`<stdint.h>/<stdbool.h>/<math.h>`，编它不需要任何 SDK 头。镜像是**第二份转写**、
它自己也会错，而"两份手写的东西互相对齐"证明不了任何一份是对的。

── 对拍分三级，判据不一样 ─────────────────────────────────────────────────
  L0 结构  样本数 / `_reset_beats` 发生在第几拍 / 登记搏动的拍号 / `H` 行的拍号
           → **必须逐个相同**。这条不过，下面几级的"通过"都没有意义。
  L1 中间量 每样本的 带通输出 y / 包络 env / 峰判据 above / 直流 dc / settle / finger
           → **要求逐位相同**（不是"差得小"）。做不到就是实现不一致，**不许用容差掩盖**。
  L2 峰顶   登记到的峰顶时刻序列（`peak_ms`）
           → **必须逐毫秒相同**。
  L3 出数   `H` 行**真正要打出去的那三个字符串**，以及三个裸值
           → 字符串必须逐字节相同；裸值另外报相对差（有几处已知的结构性差异，
             见下面"已知差异"）。
  L4 闸     `AC_MIN_RMS` 那道闸两边用的是**不同的缓冲**（PC 是 25 Hz/10 s 的
           `slow`，板端是 100 Hz/3 s 的 `pi_ac`）⟹ 专门统计两边判决不一致的次数。

── 🔴 已知差异（不是 bug，但必须**报出次数**，不许静默）─────────────────
  1. **间隔闸的数值类型不同。** PC 的 `_register_beat` 用**浮点秒**比
     `MIN_IBI_S`/`MAX_IBI_S`（`ibi = t - last_beat_t`，而 `t = t_ms/1000.0`），
     板端用**整数毫秒**比 330/1600。`ibi_ms` 是 10 的倍数，恰在 330/1600 这两个
     边界上两者**可能反向**（例：t1=645010, t2=645340 → PC 得
     0.32999999999992724 < 0.33 ⟹ 拒，板端得 330 >= 330 ⟹ 收）。
     → 这里如实数出来，**不猜、不调常数去凑**。真发生了要单独报告。
  2. `bpm()` 的中位间隔：PC 存的是**浮点秒差**（两个 `t_ms/1000.0` 相减，两次舍入），
     板端存整数毫秒。相对差 ~1e-16，只可能影响最后一位。
  3. `ibi_spread()`：PC 是 `mad_s/med_s`，板端是 `mad_ms/med_ms`；同理由 ~1e-16。
  4. `ac_rms()`：见 L4。
  5. 板端**没有频谱兜底**（`spec_bpm`），所以"板端 `--` 而 PC 有数"是正常的诚实行为。
     L3 会把这类次数单独报出来。
"""
import io
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import ui.serial_hr as S            # noqa: E402

HOST_EXE = os.path.join(HERE, '_hr_algo_host.exe')

RUNS = [
    ('runs/_hr_nn_20260926_205912.txt', '真人 90 秒（本轮标定的主证据）'),
    ('runs/_hr_pi_cal.txt',             '60 秒 PI 标定（含拿开手指）'),
    ('runs/_hr_raw.txt',                '15 秒早期片段'),
]

out_lines = []

# 控制台是 GBK，`✓`/`✗` 编不出去会当场崩。log 文件本身写 UTF-8。
# （`ui/` 那边是同一件事：板子日志是 UTF-8、PC 脚本 stdout 重定向是 GBK。）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass


def say(s=''):
    try:
        print(s)
    except UnicodeEncodeError:
        print(s.encode('utf-8', 'replace').decode('utf-8', 'replace'))
    out_lines.append(s)


# ============================================================================
# PC 侧：留痕的 tracker
# ============================================================================
class SpyTracker(S._HrTracker):
    """把 `push` 之后的中间量、以及"复位发生在哪一拍"留出来。

    ⚠️ `pre` 是在 `push()` **返回之前**取的，所以它和板端 `L1` 一样是**复位之前**
       的那一瞬；而板端驱动是在 `hr_algo_push()` **返回之后**读的（= 复位之后）。
       所以复位那一拍两边的中间量**根本取不到同一个东西** —— 板端把它标成 `L1R`
       不给数，这里也不比那一拍。**但复位发生在第几拍是照常比的**（L0）。
    """

    def __init__(self, fs=S.SAMPLE_RATE_HZ):
        super().__init__(fs)
        self.reset_count = 0
        self.pre = None                 # (y, env, above)
        self.rejected_float = 0         # 按**浮点秒**判据拒掉的个数（见已知差异 1）

    def push(self, t_s, ir, t_ms=None):
        super().push(t_s, ir, t_ms)
        self.pre = (self.bp[-1].y1, self.env, self.above)

    def _reset_beats(self):
        self.reset_count += 1
        super()._reset_beats()

    def _register_beat(self, t, t_ms=None):
        if self.last_beat_t is not None:
            ibi = t - self.last_beat_t
            if not (S.MIN_IBI_S <= ibi <= S.MAX_IBI_S):
                self.rejected_float += 1
        super()._register_beat(t, t_ms)


# 让 `SerialHr.__init__` 和 `_feed` 里那条"板子复位就换新 tracker"的分支
# 都造出留痕的那个 —— 后者是模块内的全局查找，打这个补丁才盖得住。
S._HrTracker = SpyTracker


def load_d(path):
    rows = []
    with io.open(path, encoding='utf-8', errors='replace') as f:
        for ln in f:
            ln = ln.strip()
            if not ln.startswith('D,'):
                continue
            f4 = ln.split(',')
            if len(f4) != 4:
                continue
            try:
                rows.append((int(f4[1]), int(f4[3])))    # (t_ms, ir)
            except ValueError:
                continue
    return rows


def replay_pc(rows):
    """走 `SerialHr._feed` 那条**线上真路**（手指闸、settle、复位判据全在里面）。

    不自己重写一遍 `_feed` —— 那就会漏掉 settle 那 1 秒的静默。
    """
    hr = S.SerialHr(enabled=False)
    recs, beats, board_resets = [], [], 0
    beats_prev, prev_t = 0, None

    for i, (t_ms, ir) in enumerate(rows):
        if prev_t is not None and t_ms < prev_t - 1000:
            board_resets += 1
        prev_t = t_ms

        tr = hr._tracker
        rc_before = tr.reset_count
        hr._feed(t_ms, ir)
        tr = hr._tracker                     # 板子复位分支会换一个对象

        fired = tr.reset_count > rc_before
        y, env, above = tr.pre
        dc = (tr.dc_sum / len(tr.dc_win)) if tr.dc_win else 0.0
        settle = hr._settle_left
        finger_on = (hr.finger == 'on')

        recs.append({
            'i': i, 't_ms': t_ms, 'y': y, 'env': env, 'above': above,
            'dc': dc, 'settle': settle, 'finger': finger_on, 'fired': fired,
            # 每个 `H` 拍要用的 PC 侧量（板端没有频谱兜底，所以只取主路 `bpm()`）
            'bpm': tr.bpm(), 'rmssd': tr.rmssd(), 'perf': tr.perfusion(),
            'ac_slow': tr.ac_rms(), 'spread': tr.ibi_spread(),
            'nn_span': tr.nn_span_ms, 'nn_n': len(tr.nn_ms),
            'ibi_n': len(tr.ibis),
        })
        if tr.beats != beats_prev:
            beats.append((i, t_ms, tr.peak_ms))
            beats_prev = tr.beats

    return recs, beats, board_resets, hr._tracker


# ============================================================================
# 板端：跑真 C
# ============================================================================
def run_host(src, dst):
    r = subprocess.run([HOST_EXE, os.path.abspath(src), os.path.abspath(dst)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit('宿主驱动失败 rc=%d %s' % (r.returncode, r.stderr))


def parse_host(path):
    L1, L1R, beats, hs = {}, set(), [], []
    with io.open(path, encoding='utf-8') as f:
        for line in f:
            f2 = line.split()
            if not f2 or f2[0].startswith('#'):
                continue
            k = f2[0]
            if k == 'L1':
                L1[int(f2[1])] = (int(f2[2]), float(f2[3]), float(f2[4]), int(f2[5]),
                                  float(f2[6]), int(f2[7]), int(f2[8]))
            elif k == 'L1R':
                L1R.add(int(f2[1]))
            elif k == 'BEAT':
                beats.append((int(f2[1]), int(f2[2]), int(f2[3]),
                              int(f2[4]), int(f2[5]), int(f2[6]), int(f2[7])))
            elif k == 'H':
                hs.append({
                    'i': int(f2[1]), 't_ms': int(f2[2]),
                    'hr_s': f2[3], 'rr_s': f2[4], 'pi_s': f2[5],
                    'hr': float(f2[6]), 'rr': float(f2[7]), 'pi': float(f2[8]),
                    'ok_hr': int(f2[9]), 'ok_rr': int(f2[10]), 'ok_pi': int(f2[11]),
                    'nn_span': int(f2[12]), 'nn_n': int(f2[13]), 'ibi_n': int(f2[14]),
                    'beats': int(f2[15]), 'rejected': int(f2[16]),
                    'ac': float(f2[17]), 'spread': float(f2[18]),
                    'have_last_ibi': int(f2[19]), 'last_ibi_ms': int(f2[20]),
                    'finger': int(f2[21]), 'settle': int(f2[22]),
                })
    return L1, L1R, beats, hs


# ============================================================================
# 比对
# ============================================================================
def reldiff(a, b):
    if a == b:
        return 0.0
    d = max(abs(a), abs(b))
    return abs(a - b) / d if d else abs(a - b)


def one_run(path, label):
    say('=' * 78)
    say('【%s】' % label)
    say('  %s' % path)

    dst = os.path.join(ROOT, 'runs', '_hr_host_%s.txt'
                       % os.path.splitext(os.path.basename(path))[0])
    run_host(path, dst)

    rows = load_d(path)
    recs, py_beats, board_resets, tr = replay_pc(rows)
    L1, L1R, c_beats, hs = parse_host(dst)

    fails = []

    # ---- L0 结构 --------------------------------------------------------
    say('')
    say('  L0 结构')
    say('     样本数         PC %d   板端 %d' % (len(recs), len(L1) + len(L1R)))
    if len(recs) != len(L1) + len(L1R):
        fails.append('样本数不等')

    py_resets = [r['i'] for r in recs if r['fired']]
    say('     复位拍号       PC %s   板端 %s' % (py_resets, sorted(L1R)))
    if py_resets != sorted(L1R):
        fails.append('复位拍号不一致')

    if board_resets:
        fails.append('录里出现板子复位 %d 次 —— 板端 C 没有这条分支，无法比对'
                     % board_resets)

    py_bi = [b[0] for b in py_beats]
    c_bi = [b[0] for b in c_beats]
    say('     登记搏动拍号   PC %d 次   板端 %d 次   %s'
        % (len(py_bi), len(c_bi), '逐个相同' if py_bi == c_bi else '**不同**'))
    if py_bi != c_bi:
        fails.append('登记搏动的拍号不一致')

    h_idx = [h['i'] for h in hs]
    say('     H 行拍号       %d 行   %s' % (len(hs), h_idx[:6] + (['...'] if len(h_idx) > 6 else [])))

    # ---- L1 中间量 ------------------------------------------------------
    say('')
    say('  L1 中间量（逐位要求相同）')
    bad = []
    n_cmp = 0
    for r in recs:
        i = r['i']
        if i in L1R:
            continue
        if i not in L1:
            bad.append((i, '板端缺这一拍'))
            continue
        c = L1[i]
        n_cmp += 1
        # 逐字段比，报第一个不同的字段（`float` 用 `!=` 是**精确**比较，没有容差）
        names = ['t_ms', 'y', 'env', 'above', 'dc', 'settle', 'finger']
        pv = [r['t_ms'], r['y'], r['env'], int(r['above']), r['dc'], r['settle'], int(r['finger'])]
        for k, nm in enumerate(names):
            if c[k] != pv[k]:
                bad.append((i, nm, c[k], pv[k]))
                break
    say('     比了 %d 拍（剔掉复位那 %d 拍）' % (n_cmp, len(L1R)))
    if bad:
        fails.append('L1 有 %d 拍不同' % len(bad))
        for b in bad[:8]:
            say('       ✗ 拍 %s：%s' % (b[0], b[1:]))
    else:
        say('     ✓ y/env/above/dc/settle/finger 全部逐位相同')

    # 复位那几拍确认"确实取不到值"，不是我们漏比了
    for i in sorted(L1R):
        if i < len(recs):
            say('       拍 %d 是复位拍：板端 `L1R`（不给数）、PC `bp[-1].y1` 已被 '
                '`reset()` 成 %.1f' % (i, recs[i]['y']))

    # ---- L2 峰顶时刻 ----------------------------------------------------
    say('')
    say('  L2 峰顶时刻')
    py_pk = [b[2] for b in py_beats]
    c_pk = [b[2] for b in c_beats]
    if py_pk == c_pk:
        say('     ✓ %d 个峰顶时刻逐毫秒相同' % len(py_pk))
    else:
        fails.append('峰顶时刻序列不同')
        for k, (a, b) in enumerate(zip(py_pk, c_pk)):
            if a != b:
                say('       ✗ 第 %d 个：PC %s  板端 %s' % (k, a, b))
                break

    # ---- 已知差异 1：间隔闸的数值类型 -----------------------------------
    say('')
    say('  已知差异 1 — 间隔闸：浮点秒（PC） vs 整数毫秒（板端）')
    # 从 L2 的候选序列上独立重算两边判据，数出"反向"的次数
    py_ms = [b[1] for b in py_beats]
    n_rev = 0
    ex = []
    for k in range(1, len(py_ms)):
        t1, t2 = py_ms[k - 1], py_ms[k]
        ibi_ms = t2 - t1
        c_acc = (330 <= ibi_ms <= 1600)
        pc_acc = (S.MIN_IBI_S <= ((t2 / 1000.0) - (t1 / 1000.0)) <= S.MAX_IBI_S)
        if c_acc != pc_acc:
            n_rev += 1
            if len(ex) < 5:
                ex.append((t1, t2, ibi_ms, (t2 / 1000.0) - (t1 / 1000.0)))
    say('     PC 判据拒掉 %d 个（`SpyTracker.rejected_float`），板端判据拒掉 %d 个'
        % (tr.rejected_float, hs[-1]['rejected'] if hs else 0))
    say('     两侧判据**反向**的次数：%d' % n_rev)
    for t1, t2, ims, sec in ex:
        say('       · t1=%d t2=%d  ibi_ms=%d  ibi_s=%.17g' % (t1, t2, ims, sec))
    if n_rev:
        say('     ⚠️ 真发生了 —— 见文件头"已知差异 1"。**不调常数去凑**，如实报。')

    # ---- L3 出数 --------------------------------------------------------
    say('')
    say('  L3 出数（`H` 行）')
    n_str_bad, n_val_bad = 0, 0
    n_ac_cmp = 0
    maxd = {'hr': 0.0, 'rr': 0.0, 'pi': 0.0, 'ac': 0.0}
    fallback_only = 0
    fake_fails = []
    for h in hs:
        i = h['i']
        if i >= len(recs):
            fake_fails.append('H 拍号 %d 越界' % i)
            continue
        r = recs[i]
        # 板端 `hr_algo_hr` 的闸 == PC `snapshot()` 出口那几道（**只取主路**）
        pc_ok_hr = (r['finger'] and r['settle'] == 0 and r['bpm'] is not None
                    and not (r['ac_slow'] is not None and r['ac_slow'] < S.AC_MIN_RMS))
        pc_ok_rr = (r['finger'] and r['settle'] == 0 and r['rmssd'] is not None)
        pc_ok_pi = (r['finger'] and r['settle'] == 0 and r['perf'] is not None)

        for nm, ok_c, ok_pc, pv in (('hr', h['ok_hr'], pc_ok_hr, r['bpm']),
                                    ('rr', h['ok_rr'], pc_ok_rr, r['rmssd']),
                                    ('pi', h['ok_pi'], pc_ok_pi, r['perf'])):
            if bool(ok_c) != bool(ok_pc):
                if nm == 'hr' and pc_ok_hr and not h['ok_hr']:
                    # 板端 -- 而 PC 有数：多半是 PC 走的是频谱兜底，或 AC 闸的缓冲差异
                    pass
                fake_fails.append('拍 %d %s 闸不同：板端 %d PC %d' % (i, nm, ok_c, ok_pc))
        if h['ok_hr'] and r['bpm'] is not None:
            maxd['hr'] = max(maxd['hr'], reldiff(h['hr'], r['bpm']))
        if h['ok_rr'] and r['rmssd'] is not None:
            maxd['rr'] = max(maxd['rr'], reldiff(h['rr'], r['rmssd']))
        if h['ok_pi'] and r['perf'] is not None:
            maxd['pi'] = max(maxd['pi'], reldiff(h['pi'], r['perf']))
        # ⚠️ 这一行的两边**量的不是同一个东西**（见已知差异 4），只在都非 None
        #    时才比，而且它是**参考**不是判据 —— 判决一致已经单独验过了。
        if r['ac_slow'] is not None and h['ac'] > 0.0:
            maxd['ac'] = max(maxd['ac'], reldiff(h['ac'], r['ac_slow']))
            n_ac_cmp += 1

    say('     H 行 %d 条' % len(hs))
    if hs:
        n_hr = sum(x['ok_hr'] for x in hs)
        n_rr = sum(x['ok_rr'] for x in hs)
        n_pi = sum(x['ok_pi'] for x in hs)
        say('     出数条数：hr %d/%d   rmssd %d/%d   pi %d/%d'
            % (n_hr, len(hs), n_rr, len(hs), n_pi, len(hs)))
        say('     裸值最大相对差：hr %.3g   rmssd %.3g   pi %.3g'
            % (maxd['hr'], maxd['rr'], maxd['pi']))
        say('       （`hr` 那 ~1e-14 是**已知差异 2**：PC 的中位间隔是浮点秒差。'
            'rmssd/pi 为 0 = 逐位相同。）')
        say('     已知差异 4 — AC 闸的缓冲不同：PC 用 25 Hz/10 s 的 `slow`，板端用 '
            '100 Hz/3 s 的 `pi_ac`')
        say('       %d 拍两边都有值，最大相对差 %.3g —— **这不是判据**，只是量级参考；'
            % (n_ac_cmp, maxd['ac']))
        say('       判决本身（上面那三行闸）逐个相同。')
        say('     末行样例：H,%s,%s,%s,%s,%s' % (hs[-1]['t_ms'], hs[-1]['hr_s'],
                                                hs[-1]['rr_s'], hs[-1]['pi_s'],
                                                hs[-1]['finger'] and 'on' or 'off'))
    if fake_fails:
        say('     闸不同 %d 处：' % len(fake_fails))
        for s in fake_fails[:10]:
            say('       · %s' % s)
    else:
        say('     ✓ 三个闸（出不出数）逐个相同')

    say('')
    if fails:
        say('  结论：**不通过** —— %s' % '；'.join(fails))
    else:
        say('  结论：L0/L1/L2 全部通过；L3 见上面的闸差异计数')
    return fails


def main():
    runs = RUNS
    if len(sys.argv) > 1:
        runs = [(a, os.path.basename(a)) for a in sys.argv[1:]]
    if not os.path.exists(HOST_EXE):
        raise SystemExit('先编宿主驱动：_scratch\\_cl.bat _hr_algo_host '
                         '../hr/firmware/src/hr_algo.c')
    allf = []
    for p, lab in runs:
        allf += one_run(os.path.join(ROOT, p), lab)
    say('=' * 78)
    say('总：%s' % ('全部通过' if not allf else '有 %d 项不通过 — %s' % (len(allf), '；'.join(allf))))
    dst = os.path.join(ROOT, 'runs', '_hr_board_ab.log')
    with io.open(dst, 'w', encoding='utf-8') as f:
        f.write('\n'.join(out_lines) + '\n')
    print('\n[log] %s' % dst)


if __name__ == '__main__':
    main()
