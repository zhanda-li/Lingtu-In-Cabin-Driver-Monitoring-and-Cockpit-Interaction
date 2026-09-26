# -*- coding: utf-8 -*-
"""把 `hr\\live.bat` 落下的会话日志读回来并算出结论。

用法（在 `dms_project` 目录下）::

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch\\_hr_live_log.py [日志路径]

不给路径就读 `runs/` 下**最新**那份 `_hr_live_*.log`。

为什么要有这个脚本
------------------
窗口原来**只画不记**（用户 2026-09-26 点名：「你肯定要落日志啊 不然你看什么」）。
把日志补上以后，**光有文件还是等于没得看** —— 一份几百上千行的 CSV，人眼扫不出
结论。要的就是这个脚本替你算出那几件只有它能回答的事：

① **步长**：`D` 行到底有没有丢样。`hr/README.md` §3 那个**未决**的头号假设
   就是「USB 丢了 `D` 样 ⟹ 有效采样率不再是恒 100 Hz ⟹ 而三节双二阶的系数是
   按 100 Hz 定死的」。健康的样子是**几乎每一次都是 10 ms**。

② **链子**：`nn_span_ms` 最长到过多少、断了几次、**到底够没够 30 秒**。
   这是「HRV-RMSSD 那格为什么是 `--`」的唯一直接答案 —— 屏幕上的 `--` 有
   「手指不在位 / 链子没连起来 / 就差几秒」三种来路，长在屏幕上**一模一样**。

③ **那串间隔长什么样**：落在 `[MIN_IBI_S, MAX_IBI_S]` 里的比例、有没有**长短
   交替**。离线那份是「一处劈拍」（`…890, 350, 1470, 990…`），实时那份据说是
   「全程长短交替」—— 同一套代码的两种表现，**先把这次是哪种量出来**。

④ **RMSSD 复算**：从**被收下的**那串 NN 上按 PC 的口径重算一遍，和屏幕上那个
   数对一下；再按 `_hr_jitter.py` 的办法把劈拍剔掉看看剩多少。

🔴 **判据全部从产品 import**（`ui/serial_hr.py`），**不在这里写第二份阈值**
——`ui/sources.py` 那条纪律：多一份阈值就是多一个会和产品走散的东西。

⚠️ 这个脚本**不碰串口**，所以界面开着也能跑。
"""

import io
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'ui'))

from serial_hr import (AC_MIN_RMS, FINGER_DC_MIN, HR_NN_NEED_MS,  # noqa: E402
                       MAX_IBI_S, MIN_IBI_S)

# `t_ms` 的分辨率就是 1 ms ⟹ 间隔的整数毫秒就是它的精确表示，再细是编数
# （同 `H,` 行那条"rmssd 打整数毫秒"的规矩）。
MIN_IBI_MS = int(round(MIN_IBI_S * 1000))          # 330
MAX_IBI_MS = int(round(MAX_IBI_S * 1000))          # 1600

OUT = []


def say(s=''):
    print(s)
    OUT.append(s)


# ============================================================================
# 读
# ============================================================================
def newest_log():
    """最新的**会话**日志。

    🔴 只认 `_hr_live_<YYYYMMDD>_<HHMMSS>.log` 这个结构，**不能只按
    `_hr_live_*.log` 前缀去匹配** —— `hr\\check.bat` 会落下
    `runs\\_hr_live_selftest.log`，那是自检的**叙述**报告，根本不是会话日志。
    按前缀匹配的话，刚跑完 `check.bat` 它就一定是最新的那份，**这个脚本会
    安安静静地去读错文件**，然后报"一行都没解析出来"—— 而真会话日志就在
    旁边。这个坑实测撞到过。
    """
    d = os.path.join(ROOT, 'runs')
    hits = []
    try:
        for n in os.listdir(d):
            if not (n.startswith('_hr_live_') and n.endswith('.log')):
                continue
            stamp = n[len('_hr_live_'):-len('.log')]
            try:
                time.strptime(stamp, '%Y%m%d_%H%M%S')
            except ValueError:
                continue                       # 不是会话日志的名字，跳过
            hits.append(os.path.join(d, n))
    except OSError:
        pass
    if not hits:
        return None
    return max(hits, key=os.path.getmtime)


def load(path):
    """→ (header_lines, consts, S, B, T)"""
    txt = io.open(path, encoding='utf-8', errors='replace').read()
    hdr, consts, S, B, T = [], {}, [], [], []
    for ln in txt.splitlines():
        if not ln:
            continue
        if ln.startswith('#'):
            hdr.append(ln)
            if ln.startswith('# consts '):
                for tok in ln[len('# consts '):].split():
                    if '=' in tok:
                        k, v = tok.split('=', 1)
                        try:
                            consts[k] = float(v)
                        except ValueError:
                            consts[k] = v
            continue
        f = ln.split(',')
        if f[0] == 'S' and len(f) >= 19:
            S.append(f)
        elif f[0] == 'B' and len(f) >= 7:
            B.append(f)
        elif f[0] == 'T' and len(f) >= 6:
            T.append(f)
    return hdr, consts, S, B, T


def num(s):
    """'--' / '' → None，其余 → float。**不把 `--` 当 0**（日志的规矩）。"""
    if s in ('--', ''):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ============================================================================
# ① 步长：丢样的唯一直接判据
# ============================================================================
def report_steps(T, consts):
    say('=' * 74)
    say('① 步长 —— `D` 行有没有丢样（USB 掉样的直接判据）')
    say('=' * 74)
    if not T:
        say('  日志里没有 T 行（会话太短，1 Hz 那一下还没到）。')
        return None

    # 直方图是**累计快照**，最后一行就是全程总和。
    last = T[-1]
    n_samp = int(num(last[2]) or 0)
    back = int(num(last[3]) or 0)
    gap_max = int(num(last[4]) or 0)
    hist = {}
    for tok in last[5].split():
        if ':' in tok:
            k, v = tok.split(':', 1)
            hist[int(k)] = int(v)

    say('  样本总数 %d，往回跳 %d 次，最大间隔 %d ms' % (n_samp, back, gap_max))
    say('  ⚠️ 下面这个直方图只列**前 6 名**（日志里就存了前 6 名）；'
        '要全程完整分布请用 `_hr_soak.py` 独占串口跑。')
    tot = sum(hist.values()) or 1
    for dt in sorted(hist, key=lambda k: -hist[k]):
        say('      %3d ms  × %-6d  %5.1f%%' % (dt, hist[dt], 100.0 * hist[dt] / tot))

    if not hist:
        say('  → 直方图是空的：板子一个样本都没进来。')
        return None
    top = max(hist, key=lambda k: hist[k])
    say('')
    if top == 10 and back == 0 and gap_max <= 10:
        # 10 ms 是 `MAX30102_SPO2_CFG` 选的采样率的倒数，板子一个 `D` 行对应
        # 芯片一个样本 ⟹ 步长恒 10 ms 才是"一个都没丢"。
        say('  ✅ 几乎全是 10 ms、无往回跳、无长间隔 ⟹ **没丢样**。')
        say('     ⟹ 未决里那个「有效采样率漂了、双二阶系数跟着失配」的假设**不成立**。')
        return 'clean'
    ok = hist.get(10, 0) / float(tot)
    say('  🔴 只有 %.1f%% 是 10 ms（健康的样子是接近 100%%），最大间隔 %d ms '
        '（= 丢了约 %d 个样本）⟹ **真丢了样**。' % (100.0 * ok, gap_max,
                                                 int(gap_max // 10) - 1))
    say('     ⟹ 三节双二阶的系数是按 `fs = 100 Hz` 定死的，而实际有效采样率'
        '已经不是 100 Hz ⟹ 0.65/3.5 Hz 两个拐点整体漂掉，**过阈时刻跟着漂**。')
    say('     这条会把未决往"实时那份本身有问题"那一侧推。')
    return 'dirty'


# ============================================================================
# ② 链子：够没够 30 秒
# ============================================================================
def chain_from_ibi(ibis, need_ms):
    """按文档写的规则，**独立地**从 `ibi_ms` 重放一遍链子。

    规则（`ui/serial_hr.py` 的 `HR_NN_NEED_MS` 那段）：这一拍的起点 == 上一段
    的终点才接着攒；掉出 `[MIN_IBI_MS, MAX_IBI_MS]` 就丢掉旧窗口从头攒。

    → (spans, breaks, longest, ever_qualified)
    `spans[i]` 是第 i 个**被收下**的间隔之后那条链的跨度（ms）。
    """
    spans, breaks, span = [], 0, 0
    for v in ibis:
        if v is None or v < MIN_IBI_MS or v > MAX_IBI_MS:
            if span:
                breaks += 1
            span = 0
            continue
        span += v
        spans.append(span)
    longest = max(spans) if spans else 0
    return spans, breaks, longest, longest >= need_ms


def report_chain(B, consts, steps_verdict):
    say('')
    say('=' * 74)
    say('② 链子 —— `NN跨度` 够没够 30 秒（`--` 的第一嫌疑）')
    say('=' * 74)
    need = consts.get('HR_NN_NEED_MS', HR_NN_NEED_MS)
    if not B:
        say('  日志里一个 `B` 行都没有 ⟹ **这一整段里一拍都没登记上**。')
        say('  那就不是"链子没攒够"，是检测器根本没在工作 —— 先看手指在不在位'
            '（`S` 行的 `finger` / `dc`）。')
        return None

    beat_ms = [int(num(f[3]) or 0) for f in B]
    ibi = [num(f[4]) for f in B]
    nn_span_log = [num(f[6]) for f in B]
    t_seen = [num(f[2]) for f in B]

    say('  登记到 %d 拍' % len(B))
    if t_seen[0] is not None and t_seen[-1] is not None:
        say('  覆盖板子钟 %.1f ~ %.1f s（共 %.1f 秒）'
            % (t_seen[0], t_seen[-1], t_seen[-1] - t_seen[0]))

    spans, breaks, longest, ever = chain_from_ibi(ibi, need)
    log_span_max = max([v for v in nn_span_log if v is not None] or [0])
    log_drops = sum(1 for k in range(1, len(nn_span_log))
                    if nn_span_log[k] is not None and nn_span_log[k - 1] is not None
                    and nn_span_log[k] < nn_span_log[k - 1])
    say('')
    say('  独立复算（从 `ibi_ms` 按文档规则重放）：')
    say('      链最长 %d ms = %.1f s，断链 %d 次' % (longest, longest / 1000.0, breaks))
    say('  日志里板端自己算的那个 `nn_span_ms`：')
    say('      链最长 %d ms = %.1f s，下降 %d 次'
        % (log_span_max, log_span_max / 1000.0, log_drops))
    if abs(log_span_max - longest) > 2 * need:
        say('  🔴 两者差得很多。**先别信任何一边** —— 要么"文档写的规则"和'
            '`_HrTracker` 真跑的不是一回事，要么这个脚本的复算写错了。')
    else:
        say('  ✅ 两者一致 ⟹ 复算用的规则就是产品在跑的那条。')

    say('')
    say('  门槛 `HR_NN_NEED_MS` = %d ms = %.0f 秒' % (need, need / 1000.0))
    if ever:
        # 第一次够格的那一拍的板子钟 —— 现场"要按多久"就是这个数。
        first = None
        for k, sp in enumerate(spans):
            if sp >= need:
                first = k
                break
        say('  ✅ **够过格**。第一次够格在第 %d 个被收下的间隔（板子钟 %s s）。'
            % (first + 1, ('%.1f' % t_seen[first + 1])
               if first + 1 < len(t_seen) and t_seen[first + 1] is not None else '?'))
        say('     ⟹ 屏幕上 `--` 是"**还没到那一刻**"，不是"算不出来"。')
        if longest < 2 * need:
            say('     ⚠️ 但最长才 %.1f 秒，只比门槛多 %.1f 秒 —— 现场演示按不到'
                '这个时长就还是 `--`。' % (longest / 1000.0,
                                        (longest - need) / 1000.0))
    else:
        say('  🔴 **一次都没够格**（最长 %.1f 秒，差 %.1f 秒）。'
            % (longest / 1000.0, (need - longest) / 1000.0))
        say('     所以屏幕上 `--` 是"真的没攒够"，不是显示问题。')
    return {'longest': longest, 'breaks': breaks, 'ever': ever,
            'log_max': log_span_max, 'log_drops': log_drops}


# ============================================================================
# ③ 间隔长什么样
# ============================================================================
def report_ibis(B):
    say('')
    say('=' * 74)
    say('③ 那串间隔长什么样 —— 离线"一处劈拍" vs 实时"全程交替"，这次是哪种')
    say('=' * 74)
    ibi = [int(v) for v in (num(f[4]) for f in B) if v is not None]
    if len(ibi) < 3:
        say('  只有 %d 个间隔，不够看。' % len(ibi))
        return None
    lo, hi = MIN_IBI_MS, MAX_IBI_MS
    good = [v for v in ibi if lo <= v <= hi]
    say('  %d 个间隔，落在 [%d, %d] ms 里的 %d 个 = %.1f%%'
        % (len(ibi), lo, hi, len(good), 100.0 * len(good) / len(ibi)))
    srt = sorted(good)
    if srt:
        med = srt[len(srt) // 2]
        mean = sum(good) / float(len(good))
        say('  中位 %d ms、平均 %.1f ms（差 %.1f%%）、最小 %d、最大 %d'
            % (med, mean, 100.0 * abs(mean - med) / med, srt[0], srt[-1]))
        say('  中位对应 %.1f BPM' % (60000.0 / med))

        # 长短交替：用 `_hr_jitter.py` 那把尺子 —— **中位数当尺**，不是门槛线。
        # 门槛线[330,1600]两边的数都能落在里面（`350/1470` 就是），拿它当判据
        # 会一对都找不出来（`_hr_jitter.py` 第一版就是这么写错的）。
        pairs = 0
        for k in range(len(good) - 1):
            a, b = good[k], good[k + 1]
            s_, l_ = (a, b) if a <= b else (b, a)
            if s_ < 0.65 * med and l_ > 1.35 * med and abs(s_ + l_ - 2 * med) < 0.2 * med:
                pairs += 1
        say('')
        say('  长短交替（一对和 ≈ 2×中位）：**%d 对** / %d 个相邻对 = %.1f%%'
            % (pairs, len(good) - 1, 100.0 * pairs / max(1, len(good) - 1)))
        if pairs >= 0.5 * (len(good) - 1):
            say('  🔴 全程交替 ⟹ 和**离线那份**（一处劈拍）是**两回事**。')
            say('     一路长短交替最像"一拍被登记成两下、下一拍又并回去"，'
                '也最像"某根线被慢变量调制"。**这一侧要单独查。**')
        elif pairs:
            say('  ⚠️ 有交替但不占多数 —— 和离线那份（一处劈拍）**像同一种**。')
        else:
            say('  ✅ 没有交替 ⟹ 和离线那份同侧，间隔本身是干净的。')
        # 剔掉劈拍之后剩多少：RMSSD 是平方和，一对就能盖住其余全部。
        bad = set()
        for k in range(len(good) - 1):
            a, b = good[k], good[k + 1]
            s_, l_ = (a, b) if a <= b else (b, a)
            if s_ < 0.65 * med and l_ > 1.35 * med and abs(s_ + l_ - 2 * med) < 0.2 * med:
                bad |= {k - 1, k, k + 1}
        keep = [good[k] for k in range(len(good)) if k not in bad]
        r_all = rmssd_of(good)
        r_keep = rmssd_of(keep)
        say('')
        say('  RMSSD（从这串间隔直接算，与屏幕上的口径可能差在"链子"上）：')
        say('      全部      %s' % ('--' if r_all is None else '%.1f ms' % r_all))
        say('      剔掉劈拍  %s（剔了 %d 个间隔）'
            % (('--' if r_keep is None else '%.1f ms' % r_keep), len(bad)))
        if r_all and r_keep and r_keep < 0.7 * r_all:
            say('  ⚠️ 剔完小了一半以上 ⟹ **这个数和离线那份一样，是被单对劈拍'
                '撑起来的**，不能直接摆到页面上。')
    return len(good)


def rmssd_of(seq):
    """一阶差分的均方根 —— 和 `_HrTracker.rmssd()` 同一个口径（**含 ddof=0**）。

    ⚠️ 这只是**从这里这串间隔**上算的，不含"必须是一条链"那条约束，所以它和
    屏幕上那个数**本来就可能不一样**。要的是量级对照，不是逐位对拍。
    """
    if len(seq) < 2:
        return None
    d = [seq[k + 1] - seq[k] for k in range(len(seq) - 1)]
    return (sum(v * v for v in d) / float(len(d))) ** 0.5


# ============================================================================
# ④ 结论
# ============================================================================
def report_verdict(steps_verdict, chain, ibi_n, S):
    say('')
    say('=' * 74)
    say('结论')
    say('=' * 74)
    if not S:
        say('  没有 S 行 ⟹ 这个会话没进入稳态，下面的都不算数。')
        return
    bad = int(num(S[-1][17]) or 0)
    say('  串口行数 %s、坏行 %d' % (S[-1][16], bad))
    if bad:
        say('  🔴 有坏行 ⟹ 先看串口那一侧，别在算法上找原因。')

    # ---- 屏幕上的 `--` 有三种来路，长在屏幕上一模一样；这里逐个排掉 ----
    # 这一段就是 `hr/README.md` 里那句"`--` 的来路有手指不在位 / 链子没连起来 /
    # 就差几秒三种"的机器版。
    say('')
    say('  `--` 的三条来路，逐条排：')
    dc = num(S[-1][3])
    ac = num(S[-1][4])
    fing = S[-1][11]
    rm = num(S[-1][14])
    pi = num(S[-1][15])
    # ⚠️ 三态，不是两态。`--`（这一格没数）**不等于"在位/有搏动"** —— 写成
    #    两态的话，一个什么都量不到的会话会被报成"一切正常"（`_hr_live_win.py`
    #    的 `whole` 那条注释踩过同一个坑：`None` 和 `False` 是两回事）。
    def verdict(v, thr, bad_txt, ok_txt):
        if v is None:
            return '未知（这一格是 `--`）'
        return bad_txt if v < thr else ok_txt

    say('      ① 手指在不在位：`dc` = %s，门槛 `FINGER_DC_MIN` = %.0f → %s'
        % (('%d' % dc) if dc is not None else '--', FINGER_DC_MIN,
           verdict(dc, FINGER_DC_MIN, '**不在位**（就是这条）', '在位')))
    say('         日志里 `finger` = %s' % fing)
    say('      ② 传感器上有没有搏动：`ac_rms` = %s，门槛 `AC_MIN_RMS` = %.1f → %s'
        % (('%.1f' % ac) if ac is not None else '--', AC_MIN_RMS,
           verdict(ac, AC_MIN_RMS, '**没搏动**（就是这条）', '有搏动')))
    say('      ③ 就差几秒：见上面 ② 链子那一段')
    say('      屏幕那一刻：`rmssd` = %s、`pi` = %s'
        % ('--' if rm is None else '%.1f ms' % rm,
           '--' if pi is None else '%.2f' % pi))

    if chain is None:
        say('  ② 链子：这次没登记到拍，查手指。')
    elif chain['ever']:
        say('  ② 链子：够过格（最长 %.1f s）。屏幕上的 `--` 是"还没到那一刻"。'
            % (chain['longest'] / 1000.0))
    else:
        say('  ② 链子：**一次都没够格**（最长 %.1f s，门槛 30 s）。'
            % (chain['longest'] / 1000.0))

    if steps_verdict == 'clean':
        say('  ① 步长：干净 ⟹ 未决**不能**用"丢样"解释，得往别处找。')
    elif steps_verdict == 'dirty':
        say('  ① 步长：**丢样了** ⟹ 先修这个（它是别的一切的前提）。')

    say('')
    say('  ⚠️ 这个脚本只报它量到的东西，**不替你判"能不能上页面"** ——')
    say('     那一条要看 `hr/README.md` §3 的未决和"出数之后那个值也不能直接用"。')


def main():
    # 退出码**分两种**，别混：这个脚本会出现在验收清单里，清单上 rc≠0 就是红。
    #   2 = **还没得看**（一次会话都没跑过）—— 不是失败，别当红
    #   1 = **真失败**（日志在、却一行都解析不出来 = 格式和脚本走散了）
    path = sys.argv[1] if len(sys.argv) > 1 else newest_log()
    if not path or not os.path.exists(path):
        print('退出码 2 = 还没得看（不是失败）：runs\\ 下一份 _hr_live_*.log 都没有。')
        print('先跑一次 `hr\\live.bat` 按几十秒，或者把日志路径当参数传进来。')
        return 2
    hdr, consts, S, B, T = load(path)
    say('日志 %s' % path)
    for ln in hdr[:4]:
        say(ln)
    say('  解析到：S=%d 行  B=%d 行  T=%d 行' % (len(S), len(B), len(T)))
    if not S and not B and not T:
        say('  🔴 一行都没解析出来 ⟹ 日志格式和这个脚本对不上，先别下结论。')
        return 1

    steps_verdict = report_steps(T, consts)
    chain = report_chain(B, consts, steps_verdict)
    ibi_n = report_ibis(B)
    report_verdict(steps_verdict, chain, ibi_n, S)

    try:
        with io.open(os.path.join(ROOT, 'runs', '_hr_live_log_report.txt'),
                     'w', encoding='utf-8') as f:
            f.write('\n'.join(OUT) + '\n')
        say('')
        say('（以上也写进了 runs\\_hr_live_log_report.txt）')
    except OSError as e:
        say('（报告落盘失败：%r）' % (e,))
    return 0


if __name__ == '__main__':
    sys.exit(main())
