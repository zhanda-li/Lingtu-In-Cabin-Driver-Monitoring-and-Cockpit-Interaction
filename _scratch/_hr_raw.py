# -*- coding: utf-8 -*-
'''
串口**原样**录制 + 速率体检 —— 回答"板子到底在以多快的速率、有没有重复地打数据"。

为什么要自己落盘：第一版是把行打到 stdout 再看工具存下来的文件，那个文件里
**同一段 10 秒的流出现了两遍**（存档层的重复，不是板子重发），差点让我误判成
"每个样本打了两次"。凡是"同一行出现了两次"这种结论，必须**先排除记录层**再下。

它回答三件事：
  ① 真实采样率：不同 t_ms 的个数 ÷ t_ms 跨度
  ② 有没有重复行：同一个 t_ms 出现两次吗、两次是不是**挨着**的
     （挨着 = 板子重发；不挨着 = 记录层的重复）
  ③ 丢样：相邻 dt 的分布（100 Hz 下应该几乎全是 10 ms，偶尔 9/11 是量化噪声）

用法：
    D:\\Anaconda3\\envs\\dms\\python.exe _scratch/_hr_raw.py [秒] [输出名]
输出：runs/<输出名>.txt（原始行）+ runs/_hr_raw.log（体检结论）
      [输出名] 不给就是 _hr_raw.txt。

⚠️ 给 [输出名] 那个参数是 2026-09-26 加的。在那之前每次录都盖同一个
   `_hr_raw.txt`，而那一份是**后续所有离线比对的历史基线**（`_hr_ab_front.py`
   `_hr_nn.py` 都在读它）—— 随手录一段 5 秒就把它冲掉了，而且冲掉之后
   **没有任何东西会报错**，只会让以后的离线结论都建立在新数据上。
   要另存就显式给个名字。
'''
import collections
import io
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEC = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0
NAME = sys.argv[2] if len(sys.argv) > 2 else '_hr_raw.txt'
if not NAME.endswith('.txt'):
    NAME += '.txt'

OUT = []


def say(s=''):
    OUT.append(s)


def main():
    import serial
    from serial.tools import list_ports

    port = None
    for q in list_ports.comports():
        if q.vid == 0x0403 and q.pid == 0x6010:
            port = q.device
    say('端口     ：%s' % port)
    if not port:
        say('♥ 没找到 FT2232')
        return 1

    s = serial.Serial(port, 115200, timeout=0.2)
    raw = []
    t0 = time.time()
    while time.time() - t0 < SEC:
        b = s.readline()
        if b:
            raw.append(b.decode('utf-8', 'replace').rstrip())
    s.close()

    with io.open(os.path.join(ROOT, 'runs', NAME), 'w',
                 encoding='utf-8') as f:
        f.write('\n'.join(raw) + '\n')
    say('存到     ：runs/%s' % NAME)

    lines = len(raw)
    d = [x for x in raw if x.startswith('D,')]
    say('录了     ：%.1f 秒  共 %d 行  其中 D 行 %d  非 D %d'
        % (SEC, lines, len(d), lines - len(d)))

    ts = []
    bad = 0
    for x in d:
        f = x.split(',')
        if len(f) != 4:
            bad += 1
            continue
        try:
            ts.append(int(f[1]))
        except ValueError:
            bad += 1
    say('坏行     ：%d' % bad)
    if len(ts) < 10:
        say('♥ D 行太少，没法判')
        return 1

    uniq = len(set(ts))
    span = max(ts) - min(ts)
    say('t_ms 跨度：%d ms   不同 t_ms 个数：%d' % (span, uniq))
    say('真实采样率：%.2f Hz   （%d 个样本 / %.3f s）'
        % (uniq / (span / 1000.0), uniq, span / 1000.0))

    # 重复：同一个 t_ms 出现几次、两次之间隔了多远
    pos = {}
    for i, t in enumerate(ts):
        pos.setdefault(t, []).append(i)
    dup = {t: p for t, p in pos.items() if len(p) > 1}
    say('重复的 t_ms：%d 个' % len(dup))
    if dup:
        gaps = [p[1] - p[0] for p in dup.values() if len(p) >= 2]
        say('  两次之间的**行距**：最小 %d  最大 %d  —— 1 = 挨着重发，'
            '大于 1 = 记录层重复' % (min(gaps), max(gaps)))
        say('  举例  ：t=%d 出现在第 %s 行' % (sorted(dup)[0], pos[sorted(dup)[0]]))

    hist = collections.Counter(b - a for a, b in zip(ts, ts[1:]))
    say('相邻 dt 分布（前 6 个）：%s' % dict(sorted(hist.items())[:6]))
    say('')
    say('♥ 结论：%.2f Hz%s' % (uniq / (span / 1000.0),
                              '' if not dup else '，**有重复行**'))
    return 0


if __name__ == '__main__':
    try:
        rc = main()
    except Exception as e:
        say('♥ 异常：%r' % (e,))
        rc = 1
    with io.open(os.path.join(ROOT, 'runs', '_hr_raw.log'), 'w',
                 encoding='utf-8') as f:
        f.write('\n'.join(OUT) + '\n')
    print('hr raw: rc=%d' % rc)
    sys.exit(rc)
