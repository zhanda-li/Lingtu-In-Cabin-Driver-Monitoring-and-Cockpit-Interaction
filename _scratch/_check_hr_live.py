# -*- coding: utf-8 -*-
'''
心率这一路的**端到端**验收：真板子 + 真串口 + 真 WS 帧。

为什么不并成一段测：**串口是独占设备**，读线程和服务进程不能同时开同一个口。
所以顺序两段，各自把口开全用完就放：

  【A】读数器直连板子：确认口能开、**行数在涨**、快照字段自洽
       （这一段回答的是"数据到底有没有从板子过来"，光看 hr=None 分不出
        "没数据"和"手指没按上去"—— 那就等于没验）
  【B】起一个 `--source demo` 的服务（**不碰摄像头**），连 /ws 抓一帧 state，
       断言帧里有 hr 这个键、且值自洽（None 或 20~220 之间的有限数）

⚠️ 全程不打开摄像头。
用法：
    D:\\Anaconda3\\envs\\dms\\python.exe _scratch/_check_hr_live.py
输出：runs/_hr_live_check.log（UTF-8）+ stdout 一行 ASCII 结论
'''
import io
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'ui'))
sys.path.insert(0, os.path.join(ROOT, 'src'))

PORT = 8791                      # 不用 8765：用户可能正开着界面
OUT = []


def say(s=''):
    OUT.append(s)


# ---------------------------------------------------------------- 【A】
def part_a():
    say('【A】读数器直连板子（HPM5300 + MAX30102，FT2232 console 口）')
    from serial_hr import make_hr_reader

    dev = make_hr_reader({})            # 不带配置 = 全默认（enabled=True、自动找口）
    try:
        # 口是读线程开的，make_hr_reader 里已经有 0.5 s 的有界等待
        info = dev.info()
        say('     端口          ：%s' % (info['port'] or '（没找到）'))
        say('     错误          ：%s' % (info['error'] or '（无）'))
        if not info['port']:
            say('     ♥ 结论：**这一路没起来**，下面无从验起')
            return 1

        # 3 秒：板子是 100 Hz，正常应该涨 ~300 行。少一个量级就是问题。
        time.sleep(3.0)
        info = dev.info()
        snap = dev.snapshot()
        say('     3 秒后的行数  ：%d（100 Hz 下正常约 300）' % info['lines'])
        say('     坏行          ：%d' % info['bad'])
        say('     搏动累计      ：%d' % info['beats'])
        say('     快照          ：hr=%s finger=%s note=%s'
            % (snap['hr'], snap['finger'], snap['note'] or '空'))

        # ★ 2026-09-26：把**裸量**也打出来。手指按上去第一件事就是看这两个数 ——
        #   IR 直流落在哪（手指闸判据，也是"要不要调 LED_PA"的依据）、
        #   交流幅度有多大（包络）。只看 finger=off / 攒心跳中 是看不见差多少的。
        d = dev.diag()
        say('     手指/直流      ：finger=%s  IR 直流均值 %.0f'
            % (d['finger'], d['dc']))
        say('     交流幅度      ：包络 %.0f  最近波峰 %.0f  搏动累计 %d'
            % (d['env'], d['peak_y'], d['beats']))
        say('     间隔          ：有效 %d 个  中位 %s s  离散度 %s'
            % (d['n_ibi'],
               ('%.3f' % d['ibi_med_s']) if d['ibi_med_s'] else '—',
               ('%.3f' % d['spread']) if d['spread'] is not None else '—'))
        # 手指没按上去时说清楚"差多少才够"，别让人以为门槛是随便定的
        from serial_hr import FINGER_DC_MIN
        if d['finger'] == 'off' and d['dc'] < FINGER_DC_MIN:
            say('     （手指闸门槛 %.0f：现在 %.0f，差 %.0f 才够 —— 按实一点，'
                '或把板端 max30102.h 的 LED_PA 调大）'
                % (FINGER_DC_MIN, d['dc'], FINGER_DC_MIN - d['dc']))

        if dev.board_errors:
            say('     板子报的错    ：%s' % ' | '.join(dev.board_errors[-3:]))
        else:
            say('     板子报的错    ：无')

        ok = info['lines'] > 100 and info['bad'] == 0
        # 手指在不在是**用户此刻的状态**，不是判据 —— 但两种状态下的自洽性要分别成立：
        #   没按（finger=off）→ hr 必须是 None。这一条是硬的：空载那 8450 的噪声
        #   内部能数出 42 次"搏动"（见 _hr_algo_check 的【3】），闸漏了就会在这儿露出来。
        if snap['finger'] == 'off' and snap['hr'] is not None:
            say('     ♥ 手指不在位却出了数：%.1f —— 手指闸没拦住' % snap['hr'])
            return 1
        say('     ♥ 结论：%s' % ('读数器通了' if ok else '行数不对，没通'))
        return 0 if ok else 1
    finally:
        dev.close()
        time.sleep(0.5)              # 让读线程把口松开，B 段才开得上


# ---------------------------------------------------------------- 【B】
def part_b():
    say('')
    say('【B】服务进程的 WS 帧里有没有 hr（--source demo，**不开摄像头**）')
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    logp = os.path.join(ROOT, 'runs', '_hr_server.log')
    log = io.open(logp, 'w', encoding='utf-8')
    proc = subprocess.Popen(
        [sys.executable, os.path.join('ui', 'server.py'),
         '--source', 'demo', '--port', str(PORT)],
        cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, env=env)

    import asyncio
    import aiohttp

    async def grab():
        url = 'http://127.0.0.1:%d/ws' % PORT
        last = None
        for _ in range(90):                       # 最多等 45 s（whisper 会把启动拉长）
            if proc.poll() is not None:
                return None, '服务进程提前退出了（exit=%s）' % proc.returncode
            try:
                async with aiohttp.ClientSession() as s:
                    async with s.ws_connect(url) as ws:
                        for _ in range(40):
                            msg = await asyncio.wait_for(ws.receive(), timeout=3.0)
                            if msg.type != aiohttp.WSMsgType.TEXT:
                                continue
                            d = json.loads(msg.data)
                            if d.get('type') == 'state':
                                return d['data'], None
            except Exception as e:
                last = e
                await asyncio.sleep(0.5)
        return None, '连不上 /ws：%s' % last

    try:
        data, err = asyncio.run(grab())
    finally:
        try:
            proc.kill()
        except Exception:
            pass
        log.close()

    # 服务端启动横幅（那一行是"界面为什么显示未接入"的第一现场）
    txt = io.open(logp, encoding='utf-8', errors='replace').read().splitlines()
    for ln in txt:
        if '心率' in ln or 'VID:PID' in ln:
            say('     服务端：%s' % ln.strip())

    if data is None:
        say('     ♥ 结论：%s' % err)
        return 1

    has = 'hr' in data
    val = data.get('hr')
    say('     收到一帧 state   ：%d 个字段' % len(data))
    say('     帧里有 hr 这个键 ：%s' % ('有' if has else '**没有**'))
    say('     hr 的值          ：%r' % (val,))
    say('     同时抽查别的字段 ：severity=%r  t=%r'
        % (data.get('severity'), data.get('t')))
    if not has:
        say('     ♥ 结论：**帧里没有 hr** —— State 或 to_json 那一段断了')
        return 1
    if val is not None and not (isinstance(val, (int, float)) and 20.0 <= val <= 220.0):
        say('     ♥ 结论：hr 值不合理（%r）' % (val,))
        return 1
    say('     ♥ 结论：WS 帧里带着 hr，通道没断')
    return 0


def main():
    say('心率端到端验收 —— 板子 → 串口 → ui/serial_hr.py → WS state 帧')
    say('=' * 68)
    bad = part_a()
    bad += part_b()
    say('')
    say('=' * 68)
    say('红项合计：%d' % bad)
    say('结论：%s' % ('全部通过' if bad == 0 else '有 %d 项不通过' % bad))

    with io.open(os.path.join(ROOT, 'runs', '_hr_live_check.log'), 'w',
                 encoding='utf-8') as f:
        f.write('\n'.join(OUT) + '\n')
    print('hr live check: %s  (%d red)' % ('PASS' if bad == 0 else 'FAIL', bad))
    return 0 if bad == 0 else 1


if __name__ == '__main__':
    sys.stdout.flush()
    sys.exit(main())
