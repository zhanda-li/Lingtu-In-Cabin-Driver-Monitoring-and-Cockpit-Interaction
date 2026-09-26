# -*- coding: utf-8 -*-
'''
心率**实时窗口** —— 独立小窗口，不经过浏览器。

    hr\\live.bat                                    （推荐：双击）
    D:\\Anaconda3\\envs\\dms\\python.exe _scratch\\_hr_live_win.py
    D:\\Anaconda3\\envs\\dms\\python.exe _scratch\\_hr_live_win.py --selftest

为什么要它：出问题时能看见的东西只有 `hr\\probe.bat` 那串秒级文本 ——
它一要独占串口、二看不到波形的**形状**、三看不到直流**在往哪边走**。
2026-09-26 那两次（「屏幕上还是 120」「未接入」）都是因为看不见裸量才绕远的。

⚠️ **串口是独占设备：跑之前必须把座舱界面关掉。** 界面开着时本窗口会顶上一行
   红字「串口被占（界面开着？）」—— 那句话在说"界面占着口"，**不是板子坏了**。

窗口里有什么（左边一列是标签，右边是数，没有解释文字）：
  · 脉搏波（带通后，25 Hz 抽取，最近 SPEC_WIN_S 秒）+ 被登记的搏动标记
  · IR 直流趋势（60 秒）
  · 底行是**五道门的判据值 / 门槛 + 过没过** —— 屏幕上没数的时候，先看这一行
'''
import io
import os
import sys
import time
import warnings
from collections import deque

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'ui'))

from serial_hr import (AC_MIN_RMS, BAUD, BEATS_KEPT, FINGER_DC_MIN,  # noqa: E402
                       HR_NN_NEED_MS, IBI_FRESH_S, MAX_IBI_S, MAX_IBI_SPREAD,
                       MIN_BEATS, MIN_IBI_S, SAMPLE_RATE_HZ, SPEC_DECIM,
                       STALE_S, SerialHr)

POLL_HZ = 5.0        # 取数（diag/snapshot）频率。**不要贴着 100 Hz 的喂数** ——
                     # diag 拿着喂数那把锁，里面那句 spec_bpm 是个几十毫秒的 DFT。
DRAW_HZ = 20.0       # 重绘频率（画的都是上次取到的快照，不再碰锁）
DC_WIN_S = 60.0      # 直流曲线回溯多长（跟踪器里只有 1 秒的 dc_win，趋势得自己攒）

OUT = []


def say(s=''):
    OUT.append(s)


def fmt(v, nd=1):
    """None → '—'。**不给 0** —— "没量到"和"量到 0"是两件事。"""
    if v is None:
        return '—'
    return '%.*f' % (nd, v)


# 中文字形缺失时的退路标签。宁可显示 'HR' 也不要一排方框。
EN = {
    '心率实时': 'HR LIVE', '心率': 'HR', '来源': 'src', '主路': 'main',
    '频谱': 'spec', '手指': 'finger', '按住': 'ON', '离开': 'off',
    '未知': '?', '搏动': 'beats', '状态': 'state', '串口': 'port',
    '行数': 'lines', '坏行': 'bad', '兜底': 'specbpm',
    '直流': 'DC', '交流': 'AC', '离散度': 'spread', '有效拍': 'ibi',
    '时效': 'fresh', '过': 'ok', '否': 'NO',
    '脉搏波（带通后）': 'pulse (bandpassed)', 'IR 直流': 'IR DC',
    '秒前': 's ago', '板子': 'board',
    '串口被占（界面开着？）': 'PORT BUSY - close the UI?',
    '没找到串口（板子没插？）': 'NO SERIAL PORT - board unplugged?',
    '串口停了': 'serial stopped', '串口停了 %.1fs': 'serial stopped %.1fs',
    '陈旧 —— 串口停了': 'STALE - serial stopped',
    '攒心跳中': 'gathering beats', '没搏动': 'no pulse',
    '串口无数据': 'no data yet', '一个样本都没进来': 'no samples at all',
}


class LiveHr(SerialHr):
    """`SerialHr` + 一个每样本的钩子：记下板子钟的最新时刻。

    `_feed(t_ms, ir)` 是**每个样本**（100 Hz）的入口，也是唯一能拿到板子时刻的
    公开位置 —— 窗口的横轴要用板子钟（不能用墙钟，两者原点不同、还会各走各的）。
    """

    t_seen = None                 # 板子钟（秒），最近一个样本的时刻

    # ---- 步长统计（"丢没丢样"的唯一直接判据）-------------------------------
    # 板子**一个 `D` 行对应芯片一个样本**，所以相邻 `t_ms` 的差恒为 10 ms 才是
    # "一个都没丢"。这个只是**整数自增 + 字典计数**，因为 `_feed` 跑在**读线程**
    # 上（100 Hz）：一旦在这儿落盘，一次写阻塞就把读循环拖住 —— **制造出它本来
    # 要测的那个丢样**。真正的落盘在绘制线程（`poll()` → `HrLog.steps`），
    # 两边靠这几个计数器交接。
    #
    # 为什么非要它：`hr/README.md` §3 那个**未决**的头号假设就是"USB 丢了 `D`
    # 样 ⟹ 有效采样率不再是恒 100 Hz ⟹ 而三节双二阶的系数是按 100 Hz 定死的"。
    # 之前 README 写着"这个用 `_hr_live_win.py` 的步长判据就能看" —— 那句话
    # **当时是空头支票**，窗口里根本没有这个判据，只有 `_hr_soak.py` 独占串口
    # 单跑才有。现在补上。
    steps = None                  # {dt_ms: 次数}
    back = 0                      # dt <= 0 的次数（复位 / 回绕 / 乱序）
    n_samp = 0
    gap_max = 0                   # 最大 dt（ms）
    _lg_ms = None

    def _feed(self, t_ms, ir):
        # 赋值放在 super() 之前：_feed 里面要拿喂数那把锁，我们只想记个数、
        # 不想在锁里多待一毫秒。浮点赋值是原子的，读线程/绘制线程都安全。
        self.t_seen = t_ms / 1000.0
        if self.steps is None:
            self.steps = {}
        if self._lg_ms is not None:
            dt = t_ms - self._lg_ms
            if dt <= 0:
                # 板子复位 / 回绕：**不当丢样算**，重新定基准（和 `SerialHr.
                # _feed` 里那个 `t_ms < last_t_ms - 1000` 的重置同理）。
                self.back += 1
            else:
                self.steps[dt] = self.steps.get(dt, 0) + 1
                if dt > self.gap_max:
                    self.gap_max = dt
        self._lg_ms = t_ms
        self.n_samp += 1
        super()._feed(t_ms, ir)

    # 自检时用来代替读线程（真跑起来是 `_read_loop` 在填 last_rx）。
    def pretend_live(self):
        self.last_rx = time.monotonic()


def pick_labels():
    """中文标签能不能用？不能就退回 ASCII。返回 (可用?, 说明)。"""
    import matplotlib
    from matplotlib import font_manager
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.font_manager import FontProperties

    hit = None
    for name in ('Microsoft YaHei', 'SimHei', 'Noto Sans CJK SC', 'SimSun'):
        try:
            font_manager.findfont(FontProperties(family=name),
                                  fallback_to_default=False)
        except Exception:                                          # noqa: BLE001
            continue
        hit = name
        break
    if hit is None:
        return False, 'no CJK font'

    # 找到字体还不够：那颗字体的字形表里未必有我们真用的这几个字 ——
    # **真画一遍**，让 matplotlib 自己喊 "missing from font"。
    # 用 Figure + Agg 而不是 pyplot：这一步只为了问字，绝不能弹出窗口。
    matplotlib.rcParams['font.sans-serif'] = [hit, 'DejaVu Sans']
    matplotlib.rcParams['axes.unicode_minus'] = False
    f = Figure(figsize=(3, 1), dpi=60)
    FigureCanvasAgg(f)
    f.text(0.02, 0.5, '心率直流交流离散度时效搏动串口被占陈旧', fontsize=8)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        f.canvas.draw()
    miss = [w for w in caught if 'missing from font' in str(w.message)]
    if miss:
        return False, '%s missing %d glyphs' % (hit, len(miss))
    return True, hit


class HrLog:
    """把一次实时会话落成一份**能离线复算**的日志。

    存在理由（2026-09-26 用户点名：「你肯定要落日志啊 不然你看什么」）：
    这个窗口原来**只画不记**，出了问题只能在屏幕上读**一个瞬间** —— 链子是
    **在哪一拍**断的、`NN跨度` 是一格格涨的还是反复从零重来、USB 有没有丢样，
    看完那一瞬就没了。而 `hr/README.md` §3 那个**未决**（同一套代码：离线
    `31.0 s / 断 2 次` vs 实时 `12.0 s / 断 13 次`）就卡在这儿：**没有实时的
    拍序列，两边永远对不上**，只能靠各说各话。

    三类行，逗号分隔，`#` 打头是注释/表头/脚注。列名纯 ASCII，值可能是中文。
    量不出来一律 `--`（和串口 `H,` 行同一条规矩，**不用 0 顶替**）：

        S,...  约 1 Hz 的状态快照（`poll()` 是 5 Hz，这里按墙钟节流）
        B,...  **每一拍新登记的**（`beat_times` 里新出现的那些）
        T,...  步长直方图 + 累计计数，1 Hz

    🔴 **`B` 行必须记 `beat_times`（所有登记到的拍），不能记 `nn_ms`。**
    `_HrTracker` 只留下**被收下**的间隔 —— 掉出 `[MIN_IBI_S, MAX_IBI_S]` 的
    那个间隔它**根本不存**。而"链子是在哪一拍断的"恰恰由**被拒的那些**间隔
    决定：记 `nn_ms` 就正好把要查的东西丢了，日志会看着很干净而问题全隐身。

    🔴 **两个时钟都记，别只记一个。** `wall` 是墙钟（会话内秒数，看"我按了
    多久"），`t_seen` 是**板子的样本钟**（看"板子觉得过了多久"）。离线放录时
    这两个会差出数量级，只记一个就分不开"是算法慢"还是"我按得短"。
    """

    def __init__(self, path, port=None):
        self.path = path
        self.f = io.open(path, 'w', encoding='utf-8', newline='\n')
        self._last_beat_s = -1.0
        self._last_s = -1.0
        self._last_t = -1.0
        self.t0 = time.monotonic()
        self.n_beats = 0
        self.n_rows = 0
        self.f.write('# 心率实时窗口会话日志\n')
        self.f.write('# when %s\n' % time.strftime('%Y-%m-%dT%H:%M:%S'))
        self.f.write('# port %s\n' % (port or 'none'))
        # 常数逐字从产品 import，**不在这里重新打一遍数** —— 日志是给将来的
        # 复算用的，写上"我以为的阈值"就是给复算埋雷（同 `_hr_live_win.py` 的
        # 判据行那条纪律）。
        self.f.write('# consts MIN_IBI_S=%g MAX_IBI_S=%g MIN_IBI_MS=%d '
                     'MAX_IBI_MS=%d HR_NN_NEED_MS=%d BEATS_KEPT=%d MIN_BEATS=%d '
                     'AC_MIN_RMS=%g FINGER_DC_MIN=%g IBI_FRESH_S=%g '
                     'SAMPLE_RATE_HZ=%d SPEC_DECIM=%d\n'
                     % (MIN_IBI_S, MAX_IBI_S, int(round(MIN_IBI_S * 1000)),
                        int(round(MAX_IBI_S * 1000)), HR_NN_NEED_MS, BEATS_KEPT,
                        MIN_BEATS, AC_MIN_RMS, FINGER_DC_MIN, IBI_FRESH_S,
                        SAMPLE_RATE_HZ, SPEC_DECIM))
        self.f.write('# S cols wall_s,t_seen_s,dc,ac_rms,spread,beats,ibi_age,'
                     'main_bpm,spec_bpm,hr,finger,nn_n,nn_span_ms,rmssd,pi,'
                     'lines,bad,note\n')
        self.f.write('# B cols wall_s,t_seen_s,beat_ms,ibi_ms,nn_n,nn_span_ms\n')
        self.f.write('# T cols wall_s,n_samples,back,gap_max_ms,steps(dt_ms:count,'
                     'top6)\n')

    # ---- 小工具 ----
    @staticmethod
    def _n(v, nd=1):
        """数 → 字符串。`None` → `--`（**不是 0**）。"""
        return '--' if v is None else ('%.*f' % (nd, v))

    @staticmethod
    def _i(v):
        return '--' if v is None else str(int(v))

    def _w(self, line):
        self.f.write(line + '\n')
        self.n_rows += 1

    def _flush(self):
        # 每行 flush：窗口被强杀（这是常态 —— 直接关窗口）时，盘上至少留下
        # 已经写过的那些。缓冲着不写 = 出了事什么都没有，那就白记了。
        try:
            self.f.flush()
        except Exception:                                          # noqa: BLE001
            pass

    # ---- S：约 1 Hz 的状态快照 ----
    def state(self, d, i, s, t_seen):
        now = time.monotonic() - self.t0
        if now - self._last_s < 1.0:
            return
        self._last_s = now
        note = (s or {}).get('note') or ''
        # 逗号是分隔符，注释里的逗号会让列数变（中文提示不会带逗号，但注解
        # 「没搏动,手压着」这种以后可能加 —— 统一挡掉，别让日志格式有一天崩掉）。
        note = note.replace(',', ';').replace('\n', ' ')
        self._w('S,%.1f,%s,%s,%s,%s,%d,%s,%s,%s,%s,%s,%d,%s,%s,%s,%d,%d,%s' % (
            now, (('%.3f' % t_seen) if t_seen is not None else '--'),
            self._n(d.get('dc'), 0), self._n(d.get('ac_rms'), 1),
            self._n(d.get('spread'), 3), d.get('beats') or 0,
            self._n(d.get('ibi_age'), 2), self._n(d.get('main_bpm'), 1),
            self._n(d.get('spec_bpm'), 1), self._n((s or {}).get('hr'), 1),
            (s or {}).get('finger') or '--', d.get('nn_n') or 0,
            self._n((d.get('nn_span_s') or 0.0) * 1000.0, 0),
            self._n((s or {}).get('rmssd'), 1), self._n((s or {}).get('pi'), 2),
            i.get('lines') or 0, i.get('bad') or 0, note))
        self._flush()

    # ---- B：每一拍新登记的 ----
    def beats(self, bt, t_seen, d):
        if t_seen is not None and t_seen < self._last_beat_s - 1.0:
            # 板子复位：`t_seen` 回到 0，`beat_times` 也跟着回到小值。**不重置
            # 基准的话后面每一拍都"不是新的"** —— 日志会静默空掉，而且看起来
            # 一切正常（这比报错坏得多）。
            self._last_beat_s = -1.0
        prev = self._last_beat_s
        for b in list(bt or []):
            if b <= prev:
                continue
            ms = int(round(b * 1000.0))
            pms = int(round(prev * 1000.0)) if prev >= 0 else None
            ibi = '--' if pms is None else str(ms - pms)
            self._w('B,%.1f,%s,%d,%s,%d,%s' % (
                time.monotonic() - self.t0,
                (('%.3f' % t_seen) if t_seen is not None else '--'),
                ms, ibi, (d or {}).get('nn_n') or 0,
                self._n((((d or {}).get('nn_span_s') or 0.0) * 1000.0), 0)))
            prev = b
            self.n_beats += 1
        if prev != self._last_beat_s:
            self._last_beat_s = prev
            self._flush()

    # ---- T：步长直方图 ----
    def steps(self, dev):
        now = time.monotonic() - self.t0
        if now - self._last_t < 1.0:
            return
        self._last_t = now
        # 读线程在改这个 dict ⟹ `dict()` 可能撞上，包一下（和 `board_errors()`
        # 同一个理由：丢一份快照算了，不值得加锁）。
        try:
            hist = dict(dev.steps or {})
        except Exception:                                          # noqa: BLE001
            hist = {}
        top = sorted(hist.items(), key=lambda kv: (-kv[1], kv[0]))[:6]
        self._w('T,%.1f,%d,%d,%d,%s' % (
            now, dev.n_samp, dev.back, dev.gap_max,
            ' '.join('%d:%d' % kv for kv in top) or '-'))

    def close(self, dev=None):
        try:
            self._w('# END wall_s=%.1f rows=%d beats=%d samples=%s back=%s '
                    'gap_max_ms=%s' % (
                        time.monotonic() - self.t0, self.n_rows, self.n_beats,
                        getattr(dev, 'n_samp', '--') if dev is not None else '--',
                        getattr(dev, 'back', '--') if dev is not None else '--',
                        getattr(dev, 'gap_max', '--') if dev is not None else '--'))
            self.f.close()
        except Exception:                                          # noqa: BLE001
            pass


class LiveWin:
    """一个窗口。**只读 `SerialHr` 的公开接口** —— `diag()` / `snapshot()` /
    `info()` / `t_seen`，不碰它的私有属性（`_tracker` 会被板子复位换掉）。"""

    def __init__(self, dev, en=False):
        import matplotlib.pyplot as plt

        self.plt = plt
        self.dev = dev
        self.en = en
        self.T = lambda s: EN.get(s, s) if en else s     # noqa: E731
        self.quit = False

        self.dc_t = deque(maxlen=int(DC_WIN_S * POLL_HZ))
        self.dc_v = deque(maxlen=int(DC_WIN_S * POLL_HZ))
        self.dcs = []                 # 全程直流（自检里看范围用）
        self.last = (None, None, None)
        self.nodata = 0

        self.fig = plt.figure(figsize=(9.6, 6.8))
        try:
            self.fig.canvas.manager.set_window_title(self.T('心率实时'))
        except Exception:                                          # noqa: BLE001
            pass
        # 版面：ax_d 的 xlabel（"秒前"）落在它下方 ~0.045，所以底行文字要再低一点，
        # 不然两者会叠在一起（第一版就是这么叠的）。
        self.ax_w = self.fig.add_axes([0.095, 0.475, 0.875, 0.295])
        self.ax_d = self.fig.add_axes([0.095, 0.180, 0.875, 0.205])

        self.t_banner = self.fig.text(0.015, 0.985, '', fontsize=10.5, va='top',
                                      color='#bb0000', wrap=True)
        # ⚠️ 这三行**不要** `family='monospace'` —— `font.monospace` 默认链是
        #    DejaVu Sans Mono，它一个汉字都没有，标签会当场变成一排方框。
        self.t_num = self.fig.text(0.02, 0.952, '', fontsize=10, va='top',
                                   color='#222222')
        self.t_num2 = self.fig.text(0.02, 0.926, '', fontsize=10, va='top',
                                    color='#444444')
        self.t_gate = self.fig.text(0.02, 0.055, '', fontsize=10, va='bottom',
                                    color='#117a55')
        self.t_stale = self.fig.text(0.5, 0.62, '', fontsize=15, ha='center',
                                     va='center', color='#999999', weight='bold')

        self.ln_w, = self.ax_w.plot([], [], lw=1.1, color='#117a55')
        self.mk, = self.ax_w.plot([], [], 'o', ms=4.0, color='#cc3311')
        self.ax_w.set_ylabel(self.T('脉搏波（带通后）'), fontsize=9)
        self.ax_w.grid(True, lw=0.3, color='#dddddd')
        self.ax_w.axhline(0.0, lw=0.4, color='#bbbbbb')

        # 带个几乎看不见的点：曲线只有一两个点时（刚启动）也得看得见它在哪。
        self.ln_d, = self.ax_d.plot([], [], lw=1.5, color='#2b6cb0', marker='o',
                                    ms=2.0, mfc='#2b6cb0', mec='#2b6cb0')
        self.ln_gate = self.ax_d.axhline(FINGER_DC_MIN, ls=':', lw=1.2,
                                         color='#cc3311')
        self.ax_d.set_ylabel(self.T('IR 直流'), fontsize=9)
        self.ax_d.set_xlabel(self.T('秒前'), fontsize=9)
        self.ax_d.grid(True, lw=0.3, color='#dddddd')

        # 刻度显示绝对值：x 内部是负数（口径见 render），但用户要看的是"几秒前"，
        # 而且最右边那个 0 就是"现在"。不这么弄，刻度会是一串 −10 −8 … 0。
        from matplotlib.ticker import FuncFormatter
        absfmt = FuncFormatter(lambda v, _p: '%.0f' % abs(v))
        self.ax_w.xaxis.set_major_formatter(absfmt)
        self.ax_d.xaxis.set_major_formatter(absfmt)

        self.fig.canvas.mpl_connect('key_press_event', self._on_key)
        self.fig.canvas.mpl_connect('close_event', self._on_close)

        # 会话日志。`main()` 只在**实时**分支里把它建起来（`--selftest` 全程是
        # None）—— 自检往 `runs/` 落会话日志会把真会话那份冲掉。
        self.log = None

    # ---- 事件 ----
    def _on_key(self, ev):
        if ev.key in ('q', 'escape'):
            self.quit = True

    def _on_close(self, _ev):
        self.quit = True

    # ---- 取数（~5 Hz）----
    def poll(self):
        d = self.dev.diag()
        s = self.dev.snapshot()
        i = self.dev.info()
        self.dcs.append(d['dc'])
        t = self.dev.t_seen
        if t is not None:
            if self.dc_t and t < self.dc_t[-1] - 1.0:
                # 板子复位（t_ms 回到 0）—— 曲线要是折回去就没法看了，清掉重来。
                # 清完**紧接着**就落这个新点（所以是两条独立的 if，不是 elif）：
                # 用 elif 的话复位那一次取数一个点都不落，曲线会白一帧。
                self.dc_t.clear()
                self.dc_v.clear()
            if not self.dc_t or t > self.dc_t[-1]:
                # ★ 只在板子钟**真的往前走**时才落一个点。串口一停，t_seen 会冻住，
                #   照落的话会画出一条竖线假装还在收数（就是那个"化石"的图形版）。
                self.dc_t.append(t)
                self.dc_v.append(d['dc'])
        # ---- 落日志 ----
        # ★ 放在 `poll()` 里、不放 `render()`：`poll()` 是**取数**那一步（5 Hz），
        #   `render()` 是画的那一步。日志记的是**测量**，不是屏幕状态；而且
        #   `--selftest` 里 `render()` 会被调很多次，挂在它上面会写出一堆重复行。
        # ⚠️ 自检模式下 `self.log` 是 None（`main()` 只在实时分支里建它）——
        #    自检绝不能往 `runs/` 落会话日志，那会把真的会话日志冲掉。
        if self.log is not None:
            try:
                bt = d.get('beat_times') or []
                self.log.beats(bt, t, d)
                self.log.state(d, i, s, t)
                self.log.steps(self.dev)
            except Exception as e:                                 # noqa: BLE001
                # 日志坏了**不能把窗口带崩** —— 停掉它并说一句，别每帧抛一次。
                self.log = None
                sys.stderr.write('hr live log: disabled (%r)\n' % (e,))
        self.last = (d, s, i)
        return self.last

    # ---- 状态判读 ----
    def banner(self, d, s, i):
        """顶上那一行。返回 (文字, 颜色) —— 五种"没数"的来路要当场分开。"""
        if i['error']:
            txt = i['error']
            if ('打不开' in txt or 'PermissionError' in txt
                    or 'denied' in txt.lower()):
                return '%s  |  %s' % (self.T('串口被占（界面开着？）'), txt), '#bb0000'
            return txt, '#bb0000'
        if not i['port']:
            return self.T('没找到串口（板子没插？）'), '#bb0000'
        age = self.age()
        if age is None or age > STALE_S:
            # ⚠️ 门槛用 STALE_S（从产品那边 import 的），不自己写 1.5。
            return (self.T('串口停了 %.1fs') % age) if age is not None \
                else self.T('串口无数据'), '#bb0000'
        be = self.board_errors()
        if be and d['dc'] <= 0:
            # ⚠️ **只在直流恒 0（一个样本都没进来）时才把它当"当前状态"报。**
            #    `board_errors` 是只留最后 20 条的**历史表**，不复位、也不清空 ——
            #    模块自己好了以后那条 `E,1,init` 还躺在里面。不判这一下，屏幕上
            #    会永远挂着一条已经过期的错，比不报还坏。
            return '%s: %s' % (self.T('板子'), be[-1]), '#cc6600'
        return '', '#222222'

    def age(self):
        return None if self.dev.last_rx is None else time.monotonic() - self.dev.last_rx

    def board_errors(self):
        # append + del 不在锁里 ⟹ 拷贝可能撞上，包一下（丢一行算了，不值得为它加锁）。
        try:
            return list(self.dev.board_errors)
        except Exception:                                          # noqa: BLE001
            return []

    def stale(self):
        a = self.age()
        return a is None or a > STALE_S

    # ---- 画 ----
    def render(self, d=None, s=None, i=None):
        if d is None or s is None or i is None:
            return
        T = self.T
        st = self.stale()
        t = self.dev.t_seen
        wave = d.get('slow') or []
        n = len(wave)
        dt = SPEC_DECIM / float(SAMPLE_RATE_HZ)      # slow 是每 4 个样本抽一个
        origin = t if t is not None else 0.0

        # ---- 脉搏波 ----
        # 横轴口径（两条轴共用）：**x = −(几秒前)，升序，0 是最新、画在最右边**。
        # 取负是为了让它跟数组同向（数组下标越大越新）；刻度再用 FuncFormatter
        # 显示成绝对值，看着就是"10 秒前 …… 现在"。
        mx, my = [], []
        if n:
            xs = [-(n - 1 - k) * dt for k in range(n)]
            self.ln_w.set_data(xs, wave)
            self.ax_w.set_xlim(xs[0], 0.25)
            a = max(1.0, max(abs(v) for v in wave) * 1.15)
            self.ax_w.set_ylim(-a, a)
            if t is not None:
                # 搏动标记：beat_times 是板子秒 ⟹ 换算到同一条"几秒前"轴上，
                # 再把 y 插值到波形上（标记要落在波峰上，不是坐在 0 线上）。
                for b in d['beat_times']:
                    x = b - t                       # = −(几秒前)，跟 xs 同号
                    idx = (x - xs[0]) / dt
                    k = int(idx)
                    if 0 <= k < n - 1:
                        f = idx - k
                        mx.append(x)
                        my.append(wave[k] * (1 - f) + wave[k + 1] * f)
        else:
            self.ln_w.set_data([], [])
        self.mk.set_data(mx, my)

        # ---- 直流曲线 ----
        if self.dc_v:
            # 同一口径：tt 是板子秒，origin 是最新样本的板子秒 ⟹ tt−origin ≤ 0。
            self.ln_d.set_data([tt - origin for tt in self.dc_t], list(self.dc_v))
        self.ax_d.set_xlim(-DC_WIN_S, 0.25)
        if self.dc_v:
            lo = min(self.dc_v)
            hi = max(self.dc_v)
            # 门槛要不要画进纵轴，取决于**现在过没过**：
            #  · 没过（直流还在门槛下面，比如空载 1267）—— 这时要看的就是"差多少"，
            #    门槛必须画进来，否则一条贴底的平线什么也说明不了；
            #  · 过了（手指按着，12 万）—— 硬把 2 万塞进来会把曲线压成一条直线，
            #    那就什么都看不出来了，索性不画。
            if lo < FINGER_DC_MIN:
                hi = max(hi, FINGER_DC_MIN * 1.05)
                self.ln_gate.set_visible(True)
            else:
                self.ln_gate.set_visible(False)
            pad = max(500.0, 0.08 * (hi - lo))
            self.ax_d.set_ylim(lo - pad, hi + pad)

        # ---- 数值 ----
        hr = s['hr']
        src = '—'
        if hr is not None:
            src = T('主路') if d['main_bpm'] is not None else T('频谱')
        fing = {'on': T('按住'), 'off': T('离开')}.get(d['finger'], T('未知'))
        # ★ 串口有行、却一个样本都没进来（直流恒 0）—— 板子卡在初始化失败那条路上
        #   （原话就在上面那行橙字里）。这时候产品给的 note 是「攒心跳中」，
        #   那是在说"再等等就有数了"，**和真因正好相反** —— 2026-09-26 白天就是
        #   这么误判过一次。所以这一格如实写"没进来样本"。
        state = T(s['note']) or '—'
        if d['dc'] <= 0 and i['lines'] > 0:
            state = T('一个样本都没进来')
        self.t_num.set_text('%s %s   %s %s   %s %s   %s %d   %s %s' % (
            T('心率'), fmt(hr), T('来源'), src, T('手指'), fing,
            T('搏动'), d['beats'], T('状态'), state))
        self.t_num2.set_text('%s %s   %s %d / %d   %s %s   %s %s' % (
            T('串口'), i['port'] or '—', T('行数'), i['lines'], i['bad'],
            T('时效'), fmt(d['ibi_age'], 2), T('兜底'), fmt(d['spec_bpm'])))

        # ---- 五道门：判据值 / 门槛 + 过没过 ----
        # 屏幕上没数的时候，先看这一行 —— 哪道门在拦，一眼能看出来。
        ac = d['ac_rms']
        gates = [
            (T('直流'), fmt(d['dc'], 0), fmt(FINGER_DC_MIN, 0),
             d['dc'] >= FINGER_DC_MIN),
            (T('交流'), fmt(ac, 0), fmt(AC_MIN_RMS, 0),
             None if ac is None else ac >= AC_MIN_RMS),
            (T('离散度'), fmt(d['spread'], 3), fmt(MAX_IBI_SPREAD, 2),
             None if d['spread'] is None else d['spread'] <= MAX_IBI_SPREAD),
            (T('有效拍'), '%d' % d['n_ibi'], '%d' % MIN_BEATS,
             d['n_ibi'] >= MIN_BEATS),
            (T('时效'), fmt(d['ibi_age'], 2), fmt(IBI_FRESH_S, 1),
             None if d['ibi_age'] is None else d['ibi_age'] <= IBI_FRESH_S),
        ]
        # ★ RMSSD 那一路的门：**上面五道全是 `hr` 的**，这一行才是决定
        #   「HRV-RMSSD 那格为什么是 `--`」的那个值。不加上它，屏幕上只能看到
        #   `--`、看不到"差多少" —— 而 `--` 的来路有"手指不在位 / 链子没连起来 /
        #   就差几秒"三种，长在屏幕上一模一样。
        # ⚠️ 它**不参与 `whole`**：链子没攒够是**常态**不是故障，让它把整行染红会
        #    盖掉上面那五道门真正的红。
        nn_row = (T('NN跨度'), fmt(d['nn_span_s'], 1),
                  fmt(HR_NN_NEED_MS / 1000.0, 0),
                  d['nn_span_s'] * 1000.0 >= HR_NN_NEED_MS)
        whole = st or any(v is False for _n, _a, _b, v in gates)
        self.t_gate.set_text('   '.join(
            '%s %s/%s %s' % (nm, a, b, T('过') if v else (T('否') if v is False else '—'))
            for nm, a, b, v in gates + [nn_row]))
        self.t_gate.set_color('#bb0000' if whole else '#117a55')

        # ---- 陈旧：整幅图变灰 + 明说 ----
        line_c = '#aaaaaa' if st else None
        for ln, c in ((self.ln_w, '#117a55'), (self.mk, '#cc3311'),
                      (self.ln_d, '#2b6cb0')):
            ln.set_color(line_c or c)
        a = self.age()
        self.t_stale.set_text(
            ('%s %.1fs' % (T('陈旧 —— 串口停了'), a)) if (st and a is not None)
            else (T('串口无数据') if st else ''))
        self.t_stale.set_visible(bool(st))
        txt, col = self.banner(d, s, i)
        self.t_banner.set_text(txt)
        self.t_banner.set_color(col)
        self.fig.canvas.draw_idle()

    # ---- 主循环 ----
    def run(self):
        plt = self.plt
        plt.ion()
        plt.show()
        last = 0.0
        state = (None, None, None)
        while not self.quit and plt.fignum_exists(self.fig.number):
            now = time.monotonic()
            if now - last >= 1.0 / POLL_HZ or state[0] is None:
                last = now
                try:
                    state = self.poll()
                except Exception as e:                             # noqa: BLE001
                    state = (None, None, None)
                    self.t_banner.set_text('内部错误 %r' % (e,))
            self.render(*state)
            try:
                plt.pause(1.0 / DRAW_HZ)
            except Exception:                                      # noqa: BLE001
                break
        try:
            plt.close(self.fig)
        except Exception:                                          # noqa: BLE001
            pass


# ============================================================================
# 自检：不用人看窗口，也不用插板子
# ============================================================================
def selftest():
    import importlib.util
    import matplotlib

    matplotlib.use('Agg')
    from matplotlib import pyplot as plt

    ok, why = pick_labels()
    say('字体          ：%s（中文标签%s）' % (why, '可用' if ok else '不可用 → 退回 ASCII'))

    # 波形定义只有一处：借 `_check_hr_algo.py` 的合成 PPG（它有自己的 __main__ 守卫）。
    p = os.path.join(ROOT, '_scratch', '_check_hr_algo.py')
    spec = importlib.util.spec_from_file_location('_hr_algo_ref', p)
    ref = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ref)

    dev = LiveHr(port=None, baud=BAUD, enabled=True)   # 不起线程 ⟹ 不碰串口
    win = LiveWin(dev, en=not ok)
    bad = 0
    n = 0

    def check(name, cond, extra=''):
        nonlocal bad, n
        n += 1
        if not cond:
            bad += 1
        say('  [%s] %s%s' % ('OK' if cond else '红', name,
                             ('  ' + extra) if extra else ''))

    # 【1】真人量级的一段：72 BPM、直流 6 万。
    #    **分小段喂、每段之间 poll 一次** —— 直流曲线是"每次取数落一个点"攒出来的，
    #    一口气喂完再 poll 就只有 1 个点，那条曲线的代码路径等于没测到。
    rows = ref.synth(72, sec=20.0)
    for k in range(0, len(rows), 200):        # 2 秒一段
        for t_ms, ir in rows[k:k + 200]:
            dev._feed(t_ms, ir)
        dev.pretend_live()
        win.poll()
    d, s, i = win.poll()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        win.render(d, s, i)
    say('【1】真人量级 72 BPM —— 面板/波形/标记')
    check('diag 里有 slow', isinstance(d.get('slow'), list))
    check('slow 与 spec_n 等长', len(d['slow']) == d['spec_n'],
          '%d 点' % len(d['slow']))
    check('出数了（真值 72）', s['hr'] is not None, '%.1f' % (s['hr'] or -1))
    check('面板上就是 diag 的那个数（不是另算的）',
          s['hr'] is not None and fmt(s['hr']) in win.t_num.get_text())
    check('搏动标记落在波形范围内（有标记）',
          len(win.mk.get_xdata()) > 0, '%d 个' % len(win.mk.get_xdata()))
    check('直流曲线攒到了多个点', len(win.dc_v) >= 8, '%d 点' % len(win.dc_v))
    # ★ "化石"的图形版守卫：串口一停板子钟就不动了，曲线**不许**继续长个。
    #   照长的话会画出一条竖线，看着像还在收数 —— 那正是今天屏幕冻住的那回事。
    frozen = len(win.dc_v)
    for _ in range(3):
        win.poll()               # 没有新样本 ⟹ t_seen 不动
    check('板子钟不往前走时，直流曲线不再长个', len(win.dc_v) == frozen)
    check('渲染无缺字警告',
          not [w for w in caught if 'missing from font' in str(w.message)], why)
    check('标题写着 hr', win.t_num.get_text().strip() != '')
    win.fig.savefig(os.path.join(ROOT, 'runs', '_hr_live_selftest.png'), dpi=110)

    # 【1b】手指拿开（空载直流 1267，COM9 实测过这个量级）—— 门槛线必须画得出来。
    #   门槛落在纵轴外面的话，屏幕上就是一条贴底的平线，看不出"还差多少够门槛"。
    say('【1b】手指不在 —— 门槛线要看得见')
    rows2 = ref.synth(75, sec=6.0, dc=1267.0, ac=25.0)   # 板子钟从 0 重来
    for k in range(0, len(rows2), 200):
        for t_ms, ir in rows2[k:k + 200]:
            dev._feed(t_ms, ir)
        dev.pretend_live()
        d2, s2, i2 = win.poll()
    win.render(d2, s2, i2)
    ylo, yhi = win.ax_d.get_ylim()
    check('空载时门槛线画出来了', win.ln_gate.get_visible(),
          '纵轴 %.0f~%.0f，门槛 %.0f' % (ylo, yhi, FINGER_DC_MIN))
    check('空载时不出数（手指闸在算法之前拦掉）',
          s2['hr'] is None and s2['finger'] == 'off',
          'hr=%s finger=%s' % (s2['hr'], s2['finger']))

    # 【2】三种退化输入：空缓冲 / 单点 / 板子复位（tracker 被换掉，slow 变短）
    say('【2】退化输入 —— 一个都不许抛异常')
    fresh = LiveHr(port=None, baud=BAUD, enabled=True)
    w2 = LiveWin(fresh, en=not ok)
    for name, feed in (
            ('空缓冲（一个样本都没来过）', []),
            ('只有一个样本', [(0, 60000)]),
            ('板子复位（t_ms 回到 0）', ref.synth(72, sec=6.0) + [(5, 60000)]),
    ):
        try:
            for t_ms, ir in feed:
                fresh._feed(t_ms, ir)
            fresh.pretend_live()
            dd, ss, ii = w2.poll()
            w2.render(dd, ss, ii)
            check(name, True)
        except Exception as e:                                     # noqa: BLE001
            check(name, False, repr(e))

    # 【3】失败态必须"说出来"（这个窗口的价值全在这）
    # ⚠️ 每改一次状态都要**重新 poll**：`info()` 一次给一个新 dict，用旧的那份
    #    等于拿改之前的状态去渲染 —— 我第一版就是这么把自己的判据骗红的。
    say('【3】失败态 —— 五种「没数」要当场分开')
    win.dev.error = 'COM9 打不开：PermissionError(13, ...)'
    win.dev.port = None
    win.dev.last_rx = None
    dd, ss, ii = win.poll()
    win.render(dd, ss, ii)
    check('界面开着 → 红字「串口被占」',
          '串口被占' in win.t_banner.get_text(), win.t_banner.get_text()[:44])
    check('横幅是红的', win.t_banner.get_color() == '#bb0000')

    win.dev.error = ''
    win.dev.port = None
    dd, ss, ii = win.poll()
    win.render(dd, ss, ii)
    check('板子没插 → 「没找到串口」', '没找到串口' in win.t_banner.get_text())

    win.dev.port = 'COM9'
    win.dev.last_rx = time.monotonic() - 5.0
    dd, ss, ii = win.poll()
    win.render(dd, ss, ii)
    check('串口停了 5 s → 横幅说出来 + 整幅图标陈旧',
          '串口停了' in win.t_banner.get_text() and win.t_stale.get_visible(),
          win.t_banner.get_text()[:44])
    check('陈旧时波形被画成灰的', win.ln_w.get_color() == '#aaaaaa')
    check('陈旧时门槛行是红的（不允许装作还在动）',
          win.t_gate.get_color() == '#bb0000')

    win.dev.last_rx = time.monotonic()
    win.dev.board_errors.append('E,1,init stat=3 part_id=0x00')
    dd, ss, ii = win.poll()
    win.render(dd, ss, ii)
    check('有样本在流时，旧的板子错不再挂在那儿（历史表不会自己清）',
          'E,1,init' not in win.t_banner.get_text() and not win.t_stale.get_visible(),
          win.t_banner.get_text()[:44] or '(空)')

    # ★ 2026-09-26 实测撞到的那一态：串口有行、**一个 D 样本都没有**
    #   （板子卡在 `E,1,init` 上）。此时产品给的 note 是「攒心跳中」——
    #   那是在说"再等等"，和真因正好相反；而板子的原话必须顶到横幅上。
    blind = LiveHr(port=None, baud=BAUD, enabled=True)
    w3 = LiveWin(blind, en=not ok)
    blind.port, blind.lines = 'COM9', 16
    blind.board_errors.append('E,1,init stat=3 part_id=0x00')
    blind.pretend_live()
    d3, s3, i3 = w3.poll()
    w3.render(d3, s3, i3)
    check('有行没样本 → 面板上出现板子的原话',
          'E,1,init' in w3.t_banner.get_text(), w3.t_banner.get_text()[:44])
    check('同一态下状态不许写「攒心跳中」',
          '一个样本都没进来' in w3.t_num.get_text()
          and '攒心跳中' not in w3.t_num.get_text(), w3.t_num.get_text()[-22:])
    check('同一态下直流判据是 否', '否' in w3.t_gate.get_text())

    # 【4】门槛行必须跟着产品那边的常量走（不是窗口自己写的数）
    check('门槛行印的是 AC_MIN_RMS / MAX_IBI_SPREAD 等（从产品 import）',
          fmt(AC_MIN_RMS, 0) in win.t_gate.get_text()
          and fmt(MAX_IBI_SPREAD, 2) in win.t_gate.get_text()
          and fmt(FINGER_DC_MIN, 0) in win.t_gate.get_text())

    # 【5】会话日志（用户点名：「你肯定要落日志啊 不然你看什么」）。
    #    **不能只测"文件建起来了"** —— 那样一个把行写错的日志也会绿。这里落一份
    #    真的、喂过 72 BPM 合成波的日志，再**读回来**验两类事实：
    #    ① 三类行都在（S/B/T 各管一件事，缺哪类哪件事就查不了）；
    #    ② `B` 行的间隔对得上喂进去的心率 —— 这是"日志能离线复算"的最小证明。
    say('【5】会话日志 —— 落盘 + 能离线复算')
    lgv = LiveHr(port=None, baud=BAUD, enabled=True)
    w5 = LiveWin(lgv, en=not ok)
    lpath = os.path.join(ROOT, 'runs', '_hr_live_selftest.hlog')
    w5.log = HrLog(lpath, 'SELFTEST')
    rows5 = ref.synth(72, sec=12.0)
    for k in range(0, len(rows5), 100):          # 100 样本 = 1 秒喂一段 ⟹ 多条 S/T
        for t_ms, ir in rows5[k:k + 100]:
            lgv._feed(t_ms, ir)
        lgv.pretend_live()
        w5.poll()
    w5.log.close(lgv)
    txt5 = io.open(lpath, encoding='utf-8').read()
    L5 = txt5.splitlines()
    s5 = [l for l in L5 if l.startswith('S,')]
    b5 = [l for l in L5 if l.startswith('B,')]
    t5 = [l for l in L5 if l.startswith('T,')]
    check('日志：三类行都落了（S/B/T 各管一件事）',
          bool(s5) and bool(b5) and bool(t5),
          'S=%d B=%d T=%d' % (len(s5), len(b5), len(t5)))
    check('日志：表头带常量（离线复算不用回头读代码）',
          'MIN_IBI_MS=' in txt5 and 'HR_NN_NEED_MS=' in txt5)
    hdr5 = next((l for l in L5 if l.startswith('# S cols')), '')
    n5 = len(hdr5.split('cols ')[-1].split(',')) + 1       # +1 = 前缀那个 'S'
    check('日志：每行列数与表头一致',
          bool(s5) and n5 == 19 and all(len(l.split(',')) == n5 for l in s5)
          and all(len(l.split(',')) == 7 for l in b5),
          'S=%d 列 B=7 列' % n5)
    ibi5 = [int(f[4]) for f in (l.split(',') for l in b5) if f[4].isdigit()]
    med5 = sorted(ibi5)[len(ibi5) // 2] if ibi5 else 0
    check('日志：B 行的间隔对得上 72 BPM（期望 ~833 ms）',
          800 <= med5 <= 870, '中位 %d ms，共 %d 个间隔' % (med5, len(ibi5)))
    check('日志：步长直方图以 10 ms 为主（= 一个样本都没丢）',
          bool(t5) and '10:' in t5[-1].split(',')[5], t5[-1][:60] if t5 else '')

    plt.close('all')
    say('')
    say('♥ 结论：%s（%d 项）' % ('全过' if not bad else '有 %d 项红' % bad, n))
    return bad


def main():
    if '--selftest' in sys.argv:
        try:
            rc = selftest()
        except Exception as e:                                     # noqa: BLE001
            say('♥ 异常：%r' % (e,))
            rc = 1
        finally:
            import io
            with io.open(os.path.join(ROOT, 'runs', '_hr_live_selftest.log'),
                         'w', encoding='utf-8') as f:
                f.write('\n'.join(OUT) + '\n')
        print('hr live win selftest: %s' % ('OK' if rc == 0 else 'FAIL-rc%d' % rc))
        return rc

    print('hr live win: starting (close the cockpit UI first -- the port is '
          'exclusive)')
    dev = LiveHr(port=None, baud=BAUD, enabled=True)
    dev.start()
    # ⚠️ 必须在 `start()` 之后才有力气等：跟 `make_hr_reader` 同一个理由 ——
    #    开串口是读线程干的，不等一下会把"还没来得及"当成"没找到串口"。
    t0 = time.monotonic()
    while time.monotonic() - t0 < 0.5 and dev.port is None and not dev.error:
        time.sleep(0.02)
    info = dev.info()
    print('hr live win: port=%s err=%s' % (info['port'] or 'none',
                                          info['error'] or 'none'))
    # ⚠️ 实时模式**也必须**调一次 `pick_labels()` —— 不只是为了那个 (ok, why)：
    #    设 CJK 字体的那两行 `matplotlib.rcParams[...]` 就写在它里面（115-116）。
    #    只在 `--selftest` 分支里调（414-417）的后果是：实时窗口里**每一个中文
    #    标签都渲染成豆腐块**（方框），而控制台刷 `Glyph 65E0 missing from
    #    font(s) DejaVu Sans` —— 因为 matplotlib 一直用默认字体。
    #    `ok` 为假时退回 ASCII 标签（`en=True` 会走 `EN` 那张表）。
    ok_labels, why_labels = pick_labels()
    print('hr live win: labels=%s (%s)' % ('CJK' if ok_labels else 'ASCII',
                                           why_labels))
    win = LiveWin(dev, en=not ok_labels)

    # ---- 会话日志（用户点名：不落日志就没得看）----------------------------
    # ★ 每次会话一份，文件名带秒级时间戳。**绝不覆盖上一份** —— 这个项目里
    #   `runs/_hr_raw.txt` 就被覆盖过一次，代价是那次现场的证据整个没了。
    #   `--log <path>` 可以指到别处（要和别人比对时用）。
    log_path = None
    for k, a in enumerate(sys.argv):
        if a == '--log' and k + 1 < len(sys.argv):
            log_path = sys.argv[k + 1]
    if log_path is None:
        log_path = os.path.join(ROOT, 'runs',
                                time.strftime('_hr_live_%Y%m%d_%H%M%S.log'))
    try:
        win.log = HrLog(log_path, info['port'])
        print('hr live win: log=%s' % log_path)
    except Exception as e:                                         # noqa: BLE001
        # 日志建不起来**不该拦住窗口** —— 看图仍然是主要用途。
        print('hr live win: log failed (%r) -- continuing without it' % (e,))

    try:
        win.run()
    finally:
        # ★ 先收日志再放串口：`HrLog.steps()` 要读 `dev.steps`，而 `dev.close()`
        #   之后读线程就停了（那个 dict 不会再变，但顺序反了就成了"读一个已经
        #   停掉的设备"，将来改 `close()` 的人会被这个顺序绊到）。
        if win.log is not None:
            win.log.close(dev)
            print('hr live win: log written -> %s' % win.log.path)
        dev.close()
        # close() 只置停止位、不 join：端口要等读循环下一次 readline 超时
        # （≤0.2 s）才放。等一下，用户才能立刻把界面开回来。
        time.sleep(0.5)
    print('hr live win: stopped, port released')
    return 0


if __name__ == '__main__':
    sys.exit(main())
