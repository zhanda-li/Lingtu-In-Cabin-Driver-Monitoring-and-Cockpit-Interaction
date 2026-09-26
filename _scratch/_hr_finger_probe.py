# -*- coding: utf-8 -*-
'''
手指按住时的**裸量轨迹** —— 回答"按了怎么没数字"。

为什么单独一个脚本：`_check_hr_live.py` 的 A 段只在 3 s 后取**一次** `diag()`，
而"不出数"有三条来路，只有看**轨迹**才分得开：

  ⓪ **板子侧就没通** —— 一个 D 样本都没进来（IR 直流恒 0），板子在打 `E,1,init ...`
  ① 手指闸没过 —— IR 直流均值按上去也一直在 8000 上下（< FINGER_DC_MIN）
  ② 闸过了但攒不到心跳 —— 直流跳到几万，可 `有效 IBI` 一直 < 4（MIN_BEATS）
  ③ 攒够了但质量闸在拒 —— 离散度 > MAX_IBI_SPREAD
  ④ 其实出数了 —— hr 是个合理的数

这五条在界面上**长得一模一样**（都是「未接入」），所以必须看数。

⚠️ ⓪ 必须排在前面判：直流恒 0 时若按"< FINGER_DC_MIN"往下走，会得出
   "手指闸没过、按实一点"的结论 —— **方向和真因正好相反**（真因在板子/接线上），
   2026-09-26 第一版就是这么误报的。判序：先看有没有样本，再看手指。

⚠️ 串口是独占设备：跑之前先把界面关掉（`ui/run_ui.bat` 那个窗口 / 8790 之类的
   服务进程），否则报 `PermissionError(13)` —— 那句在说"界面开着"，不是板子坏了。

用法：
    D:\\Anaconda3\\envs\\dms\\python.exe _scratch/_hr_finger_probe.py [预热秒 [采样秒]]
输出：runs/_hr_finger.log（UTF-8）+ stdout 一行 ASCII 结论
'''
import io
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'ui'))

OUT = []


def say(s=''):
    OUT.append(s)


WARM = float(sys.argv[1]) if len(sys.argv) > 1 else 6.0
SAMP = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0


def main():
    from serial_hr import make_hr_reader, FINGER_DC_MIN

    dev = make_hr_reader({})          # 不带配置 = 全默认（enabled、自动找口）
    bad = 0
    try:
        info = dev.info()
        say('端口          ：%s' % (info['port'] or '（没找到）'))
        say('错误          ：%s' % (info['error'] or '（无）'))
        say('  行数/坏行   ：%d / %d' % (info['lines'], info['bad']))
        if not info['port']:
            say('♥ 结论：这一路没起来（口都没开上）')
            return 1

        say('')
        say('★ 现在开始 %.0f 秒预热 —— 手指按住传感器、盖住整颗器件、别动' % WARM)
        time.sleep(WARM)

        say('')
        say('  秒   hr    来自   finger   IR直流   包络   波峰   搏动  有效IBI  中位IBI  离散度  频谱')
        dcs = []
        hrs = []
        nibi = 0
        n_main = n_spec = 0
        b0 = dev.info()['beats']
        t0 = time.time()
        while time.time() - t0 < SAMP:
            d = dev.diag()
            s = dev.snapshot()
            dcs.append(d['dc'])
            # ★ 2026-09-26 加：分清这个数是**主路**给的还是**频谱兜底**给的。
            #   用户要的是「一直有数」，兜底就是干这个的 —— 但"兜底在救命"和
            #   "兜底在瞎报"在屏幕上长得一模一样，只有把来源打出来才分得开。
            src = '—'
            if s['hr'] is not None:
                hrs.append(s['hr'])
                src = '主路' if d['main_bpm'] is not None else '频谱'
                if d['main_bpm'] is not None:
                    n_main += 1
                else:
                    n_spec += 1
            nibi = max(nibi, d['n_ibi'])
            say('%5.1f  %-5s  %-5s  %-6s  %6.0f  %5.0f  %5.0f  %5d  %4d  %8s  %6s  %7s' % (
                time.time() - t0,
                ('%.1f' % s['hr']) if s['hr'] is not None else '—',
                src,
                d['finger'], d['dc'], d['env'], d['peak_y'], d['beats'], d['n_ibi'],
                ('%.3f' % d['ibi_med_s']) if d['ibi_med_s'] else '—',
                ('%.3f' % d['spread']) if d['spread'] is not None else '—',
                ('%.1f' % d['spec_bpm']) if d['spec_bpm'] else '—'))
            time.sleep(1.0)

        info = dev.info()
        say('')
        say('全程          ：行数 %d  坏行 %d  新增搏动 %d'
            % (info['lines'], info['bad'], info['beats'] - b0))
        say('IR 直流       ：最低 %.0f  最高 %.0f  （手指闸门槛 %.0f）'
            % (min(dcs or [0]), max(dcs or [0]), FINGER_DC_MIN))

        # ★ 2026-09-26 加：把**间隔本身**打出来。中位数分不出"本来就慢"和"漏拍" ——
        #   中位 1.2 s 既可能是真 50 BPM，也可能是真 100 BPM 漏了一半。
        #   看列表：漏拍是 T / 2T **交替**，本来就慢是**全都一样长**。
        #   再对照 `beat_times` 的实际数值。
        d = dev.diag()
        say('')
        say('最后 8 个有效间隔（秒）   ：%s'
            % (' '.join('%.3f' % x for x in d['ibis']) or '（无）'))
        say('最近的搏动时刻（秒，板子时间轴）：%s'
            % (' '.join('%.3f' % x for x in d['beat_times']) or '（无）'))
        bt = d['beat_times']
        if len(bt) >= 2:
            say('相邻搏动间隔（秒，含被范围闸拒掉的）：%s'
                % ' '.join('%.3f' % (b - a) for a, b in zip(bt, bt[1:])))
            say('   → 若这里 T 与 2T 交替出现，就是**漏拍**（屏幕上那个数偏低是假的）；')
            say('     若全是同一长度，就是**真就这么慢**（那个数是对的）。')
        if dev.board_errors:
            say('板子报的错    ：%s' % ' | '.join(dev.board_errors[-3:]))

        say('')
        hw = [e for e in dev.board_errors if e.startswith('E,1')]
        if hrs:
            say('♥ 结论：**出数了**，心率 %s BPM（%d 帧里有数：主路 %d / 频谱兜底 %d）'
                % ('%.1f' % hrs[-1], len(hrs), n_main, n_spec))
            if len(hrs) >= n_spec > 0:
                frac = 100.0 * n_spec / len(hrs)
                if frac > 80:
                    say('   → 兜底占了 %.0f%% —— 这个数**基本是兜底撑起来的**，'
                        '说明主路那道质量闸在这段信号上一直在拒。' % frac)
                else:
                    say('   → 兜底只占了 %.0f%%，主路还是主力。' % frac)
        elif hw or max(dcs or [0]) <= 0:
            # ★ 2026-09-26：这一支必须排在手指闸前面。直流恒 0 = 一个 D 样本都没进来，
            #   那不是"测得弱"，是"压根没在测"。
            say('♥ 结论：**一个样本都没进来 —— 板子侧没通，跟手指没关系**')
            say('   板子报的   ：%s' % (hw[-1] if hw else '（没报错，但也没有 D 行）'))
            say('   → `E,1,init stat=3 part_id=0x00`：stat=3 是 status_timeout，'
                'part_id 停在 0 是因为')
            say('     失败在最早的"软复位"那一步，**根本没读到 PART_ID**（不是读到了 0）。')
            say('     也就是板子压根没在采数据，界面上显示「未接入」是对的。查三样：')
            say('     ① 模块 VCC 是不是 3.3 V、GND 通不通（模块上那颗电源灯亮着吗）')
            say('     ② SCL→PB02 / SDA→PB03 有没有松、有没有反')
            say('     ③ 都插好了还没好 → 按一下板子的 RESET 键（开机那次总线恢复会重跑）')
            say('     接回去会**自己**恢复：固件每秒重试一次初始化，不用重烧固件、不用重启界面。')
            bad = 1
        elif max(dcs or [0]) < FINGER_DC_MIN:
            say('♥ 结论：**手指闸没过** —— 直流最高 %.0f，差 %.0f 才够'
                % (max(dcs), FINGER_DC_MIN - max(dcs)))
            say('   → 手指要盖住整颗器件（不只是中间那个亮块）、按住压实别动；')
            say('     按实了还上不去，就把板端 max30102.h 的 LED_PA 调大（0x24→0x3F→0x7F）')
            bad = 1
        elif nibi < 4:
            say('♥ 结论：**闸过了**（直流最高 %.0f）**但攒不到心跳** —— 有效间隔只有 %d 个（要 ≥4）'
                % (max(dcs), nibi))
            say('   → 看包络/波峰：一直是个位数 = 交流分量太小（贴合不实 / LED 太暗 / 一直在动）')
            bad = 1
        else:
            say('♥ 结论：间隔攒够了但**质量闸一直在拒**（离散度超 %.2f）—— 波形不稳，多半在动'
                % 0.20)
            bad = 1
        return bad
    finally:
        dev.close()
        time.sleep(0.5)


if __name__ == '__main__':
    sys.exit_code = 0
    try:
        rc = main()
    except Exception as e:
        say('♥ 异常：%r' % (e,))
        rc = 1
    finally:
        with io.open(os.path.join(ROOT, 'runs', '_hr_finger.log'), 'w',
                     encoding='utf-8') as f:
            f.write('\n'.join(OUT) + '\n')
    print('hr finger probe: %s' % ('OK' if rc == 0 else 'BLOCKED-rc%d' % rc))
    sys.exit(rc)
