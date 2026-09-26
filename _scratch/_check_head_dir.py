# -*- coding: utf-8 -*-
"""低头规则**带方向**之后的对账器：判据换了，数字必须重标一遍。

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch\\_check_head_dir.py

回答用户 2026-09-26 的第二问：「**我仰头为啥也算重度疲劳 我仰头咋了**」，
第三问（同日晚）：「**我低头回正后还有很长一段时间报重度疲劳 然后我从回正到仰头
过了一段时间才报疲劳**」—— 后者是**参考位被拖住**造成的假触发（①）。
第四问（当晚深夜）：「**不要多报 我已经说了**」「**不要锁存**」—— 锁存去掉之后，
判据**自己撑不住**的那两个洞才露出来（④）：人还低着判据自己松手、低过一分钟之后
再也报不出低头。见【5】。

这份脚本干四件事，缺一不可：
  【1】**方向性**：造两条合成轨迹（低头 14° / 仰头 14°），断言 `head_swing`
       对低头给正、对仰头给**负**（旧判据对两者给同一个数 —— 这就是那个 bug）。
  【1b】**偏一阵子再回正**：仰头 11 秒 / 40 秒、低头 20° 11 秒，回正之后都不许触发
       （真人会话上假报了 14.8 s 的那一段）。仰头那条原来的【1】测不出来 ——
       它只覆盖"仰头本身不触发"，而 bug 在**回正之后**。
  【1c】**拿真人录像原样重放**：`runs/_probe_lag_cam.csv`。对账只在"参考位没被拖住"
       的区间做（记录下来的列是旧口径写的，被拖那段本来就该对不上）。
  【2】**口径一致**：`_scratch/_calib_head_down.py` 的【6】是**另写了一遍**
       参考位的式子（为了能扫参数），生产里那份在 `src/face.py`。那边把表落盘
       （`_calib_head_down_ref.json`，含当时的常量），这边跑**生产函数**算同样的
       两列去比。⚠️ 这条断言**原来是假的**（只印了两遍同一个数），2026-09-26 才改成真的。
  【3】**代价与收益**：四组片段在 10° 上的触发数（正常/扭头/低头/疲劳），
       以及**旧判据**在同样片段上"靠上抬顶过阈值"的那几段（真人会话里约三成）。
  【5】**判据自己会不会松手**（④）：合成轨迹（持续低头 30 s、长低头后再低头 6 s）。
       锁存去掉之后这一条是唯一的防线 —— 第三次那条口径在 A 上低下去 13.0 秒就自己
       松手，在 B 上只给 5.7°。

⚠️ import `face` 会拖进 mediapipe（析构固定 42 s，见 mediapipe 那条记录），
   所以脚本最后一行必须是 `os._exit(0)`。
"""
import json
import os
import sys

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

from face import (HEAD_DEG, HEAD_REF_ITERS, HEAD_REF_Q, HEAD_REF_WIN,  # noqa: E402
                  HEAD_WIN, ROLL_WIN, head_ref, head_swing, norm_by_time)

CACHE = os.path.join(HERE, "_ear_raw.npz")
TABLE = os.path.join(HERE, "_calib_head_down_ref.json")     # 【6】落盘的标定表（【2】对账用）
GROUPS = ("normal", "glance", "phone", "fatigue", "talking")
TRAIL, STEP = HEAD_WIN, 0.2
# ★ **冻结的旧口径分位**（2026-09-26 第三次之前/之中的口径）—— 它唯一的用处是
#   "改动前后比一比"，**绝不许跟着 `src/face.py` 的 `HEAD_REF_Q` 改**（那个现在是 35）。
#   跟着改就等于把基线也换了：比出来的"摘掉多少秒"当场变成 0，而且是**假绿**。
_OLD_Q = 25.0
REDS = []


def ck(name, cond, detail=""):
    print("  %s %-52s %s" % ("✅" if cond else "❌", name, detail))
    if not cond:
        REDS.append(name)


def synth():
    """【1】合成轨迹：静态站 8 秒，然后往一个方向偏 14°。

    ⚠️ 仰头的值**不是一律为负**，三种时长各量一条，因为它们落在三处不同的地方
       （第一版我在这里断言错了，被这张表当场打回）：
       · 仰头 0.5 s：p95 取的还是窗里偏高的那侧 → 约 **0**
       · 仰头 ≈2.2 s：整窗都在抬头侧 → **负数**
       · 仰头 6 s：偏移占了 14 秒窗的 43%（**多于锚点 q0 = 35%**），修剪的**初值**
         当场被拽到抬头那一侧、内点集也只剩仰头那一段 → 又回到 **0**
       三种**都 ≤ 0**、都远离 HEAD_DEG，这就是修复的全部内容 ——
       旧判据对这三种给的都是同一个 **+14**（同一个 +14 也给了低头）。
    """
    print("【1】方向性（合成轨迹，静态 6° 起，偏 14°）")
    t = np.arange(0.0, 14.0, 1 / 15.0)
    base = 6.0
    # 第 8 秒起偏 14°：低头 = pitch 变大；仰头 = pitch 变小（实测口径：pitch 大 = 低头）
    down = np.where(t < 8.0, base, base + 14.0)             # 低头 6 s
    up_long = np.where(t < 8.0, base, base - 14.0)          # 仰头 6 s
    up_brief = np.where(t < 13.5, base, base - 14.0)        # 仰头 0.5 s
    up_fit = np.where(t < 11.8, base, base - 14.0)          # 仰头 2.2 s
    s_down = head_swing(t, down)
    s_up = head_swing(t, up_long)
    s_brief = head_swing(t, up_brief)
    s_fit = head_swing(t, up_fit)
    print("     低头 6 s → %+.2f°   仰头 6 s → %+.2f°   仰头 2.2 s → %+.2f°   "
          "仰头 0.5 s → %+.2f°" % (s_down, s_up, s_fit, s_brief))
    ck("低头 6 s：≥ HEAD_DEG(%.0f°)，会触发" % HEAD_DEG, s_down >= HEAD_DEG,
       "%+.2f" % s_down)
    ck("仰头 6 s：**不能**触发（旧判据在这里给的是同一个 +14）", s_up < HEAD_DEG,
       "%+.2f" % s_up)
    ck("仰头 2.2 s：**不能**触发，且为负（方向写进了符号里）", s_fit < 0,
       "%+.2f" % s_fit)
    ck("仰头 0.5 s：不能触发（≈0，不是负 —— p95 取的是窗里偏高的那侧）",
       s_brief < HEAD_DEG, "%+.2f" % s_brief)
    ck("仰头三种时长全部 ≤ 0（没有一个能混进触发区）",
       s_up <= 0 and s_fit <= 0 and s_brief <= 0,
       "%.2f / %.2f / %.2f" % (s_up, s_fit, s_brief))
    # 静止不动：dip 必须接近 0（不能因为噪声就报）
    still = np.full_like(t, base) + np.random.RandomState(0).normal(0, 1.0, len(t))
    s_still = head_swing(t, still)
    ck("静止（±1° 噪声）：不触发", s_still < HEAD_DEG, "%+.2f" % s_still)


def _along(t, p, t_from=None, step=STEP):
    """沿轨迹逐帧评 `head_swing`（前缀数组，函数自己从尾部取窗 —— 与在线同构）。

    返回 (时刻, 值)。`t_from` 只决定**从哪一刻开始记**，不裁剪喂进去的历史 ——
    参考位要的正是"在这之前发生过什么"。
    """
    tt, vv = [], []
    t0 = t[0] if t_from is None else t_from
    while t0 <= t[-1]:
        j = int(np.searchsorted(t, t0, side="right"))
        if j >= 5:                                             # noqa: PLR2004
            tt.append(float(t[j - 1]))
            vv.append(head_swing(t[:j], p[:j]))
        t0 += step
    return np.asarray(tt), np.asarray(vv)


def return_case():
    """【1b】「抬头/低头一阵 → 回正」：**回正之后不许触发**。

    ★ 这条用例是**补上来的**：原来的【1】只量"仰头本身不触发"，而 2026-09-26 真人会话
      上量出来的假触发**不在仰头那一段，在回正之后那一段**（用户原话：「我从回正到
      仰头 过了一段时间才报疲劳」）：

        w=25.1 仰头 → w=36.05 回正 → 直立着报重度 **14.8 s**（`hsw` 实测 14.6~25.3）

      机制：参考位 `ref = p25(最近 ROLL_WIN 秒)`。仰头把 ref 拽到抬头那一侧，回正瞬间
      `hi = p95(最近 HEAD_WIN 秒)` 已经追上直立、ref 还留在抬头 → 差 20° 上下 ≥ HEAD_DEG。

    ★ 历史长度**故意取短的（30 秒）**：用户就是"打开页面 → 点接入摄像头 → 马上做动作"，
      全场 57 秒。拿几分钟的假历史来测会测成另一个问题（长参考位天然不会被几分钟里
      几秒的偏移拖走），于是"修好了"只发生在测试里、不发生在演示里。

    ★ 同时量**对称的那一侧**（低头 20° 11 秒 → 回正）：低头那一次必须照旧触发 ——
      任何"把参考位整体抬高"的修法都会先把这条弄红。

    ★ 仰头那一侧再量一条 **40 秒**的：参考位抗拖动靠的是"偏移没占满窗的 (1−q0)"，
      11 秒在 300 秒窗里微不足道，40 秒也一样（要 **195 秒**才拽得动，见
      `HEAD_REF_WIN` 的"记忆"）。这条是拿来说清**记忆有多长**的。
    """
    print("\n【1b】抬头/低头 20° 各 11 秒 → 回正（前面只有 30 秒静息，模拟现场）")
    t = np.arange(0.0, 52.0, 1 / 15.0)
    base = 6.0
    for name, tilt in (("仰头", -20.0), ("低头", +20.0)):
        p = np.where(t < 30.0, base, np.where(t < 41.0, base + tilt, base))
        tt, vv = _along(t, p, t_from=28.0)
        v = np.isfinite(vv)
        tt, vv = tt[v], vv[v]
        during = vv[(tt >= 31.0) & (tt < 40.0)]
        after = vv[tt >= 42.0]
        pk_d = float(during.max()) if len(during) else float("nan")
        pk_a = float(after.max()) if len(after) else float("nan")
        print("     %-3s：偏着 11 秒里峰值 %+.2f°   回正之后峰值 %+.2f°"
              % (name, pk_d, pk_a))
        if tilt < 0:
            ck("仰头：偏着的时候不触发", pk_d < HEAD_DEG, "%+.2f" % pk_d)
            ck("仰头：**回正之后也不触发**（真人会话上假报了 14.8 s）",
               pk_a < HEAD_DEG, "%+.2f" % pk_a)
        else:
            ck("低头：偏着的时候触发（修完这条必须还在）", pk_d >= HEAD_DEG, "%+.2f" % pk_d)
            ck("低头：回正之后撤掉", pk_a < HEAD_DEG, "%+.2f" % pk_a)

    print("     仰头 40 秒（量「记忆」够不够长：195 秒才拽得动）→ 回正：")
    t2 = np.arange(0.0, 82.0, 1 / 15.0)
    p2 = np.where(t2 < 30.0, base, np.where(t2 < 70.0, base - 20.0, base))
    tt, vv = _along(t2, p2, t_from=40.0)
    v = np.isfinite(vv)
    tt, vv = tt[v], vv[v]
    pk2 = float(vv[tt >= 71.0].max()) if len(vv[tt >= 71.0]) else float("nan")
    print("       偏着 40 秒里峰值 %+.2f°   回正之后峰值 %+.2f°"
          % (float(vv[(tt >= 41.0) & (tt < 69.0)].max()), pk2))
    ck("仰头 40 秒：回正之后不触发（记忆 195 秒 > 40 秒）", pk2 < HEAD_DEG, "%+.2f" % pk2)


def recorded():
    """【1c】拿**用户那场真人会话的 pitch 原样**重放（`runs/_probe_lag_cam.csv`）。

    合成轨迹是自己画的，容易画成"刚好能过"的样子。这一段的好处是它**不是**为测试
    造的：动作时刻是量出来的（低头 onset w=7.35、回正 13.98、仰头 25.11、回正 36.05，
    见 `runs/_lag_cam.txt`），历史长度就是他当时真实的那几十秒。

    ⚠️ 这段只用 pitch 一列、并且断言**回正之后那段是 0** —— 不去断"低头那段"，
       因为那段的真值（0.7 s 触发）在融合器里、不在这条判据里。

    ⚠️ 2026-09-26 治①之后，**对账只做 `t ≤ 25.0`**（仰头 onset 25.11 之前那段）。
       理由：记录下来的 `head_swing` 列是**旧口径**（参考位只取 10 秒窗）写的，而
       ①要改的正是"参考位被拖住"的那一段 —— 用旧列去核对新式子，在仰头/回正那段
       必然对不上（那正是要改的东西）。所以这条断言改成更强的一句话：
       **在参考位没被拖住的区间里，新式子必须复现记录值** —— 也就是"改动只落在
       被拖住的那一段"，不是"到处都变了"。
    """
    path = os.path.join(ROOT, "runs", "_probe_lag_cam.csv")
    if not os.path.exists(path):
        print("\n【1c】跳过：没有 %s" % path)
        return
    print("\n【1c】真人会话重放：%s" % os.path.relpath(path, ROOT))
    import csv
    with open(path, encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r.get("source") == "cam"]
    ts, ps, hs = [], [], []
    for r in rows:
        try:
            ts.append(float(r["wall"]))
            ps.append(float(r["pitch"]))
            hs.append(float(r["head_swing"]))
        except (TypeError, ValueError):
            continue
    ts, ps, hs = np.asarray(ts), np.asarray(ps), np.asarray(hs)
    ts = ts - ts[0]
    if len(ts) < 20:                                           # noqa: PLR2004
        print("     有效帧太少（%d），跳过" % len(ts))
        return
    tt, vv = _along(ts, ps, t_from=1.0, step=0.5)
    ok = np.isfinite(vv)
    tt, vv = tt[ok], vv[ok]
    # 重放对账：只在**参考位没被拖住**的区间做（t ≤ 25.0 = 仰头 onset 之前）。
    # 记录下来的那一列是旧口径写的，被拖住的那段本来就该对不上 —— 对不上正是①要的。
    on = np.isfinite(hs)
    rec = np.interp(tt, ts[on], hs[on])
    keep = tt <= 25.0
    d = np.abs(vv[keep] - rec[keep])
    print("     重放对账（t ≤ 25 s，参考位没被拖的那段）：%d 点，"
          "与记录值的中位差 %.2f°、最大 %.2f°"
          % (len(d), float(np.median(d)), float(d.max())))
    ck("参考位没被拖的区间里，新式子复现记录值（中位差 < 2°）",
       float(np.median(d)) < 2.0, "%.2f" % float(np.median(d)))
    # 回正之后（w >= 36.05，`_lag_cam.txt` 量出来的那一刻）不许触发
    after = vv[tt >= 36.05]
    pk = float(after.max()) if len(after) else float("nan")
    print("     回正之后（%.0f~%.0f s，%d 点）峰值 %+.2f°"
          % (tt[tt >= 36.05].min() if len(after) else 0.0, ts[-1], len(after), pk))
    ck("仰头回正之后不触发（这一段当时假报了 14.8 s 重度）", pk < HEAD_DEG,
       "%+.2f" % pk)
    # 仰头那一段本身：旧口径把它压到 0 附近，新口径给明确的负值（参考位没被拖走）
    up = vv[(tt >= 26.0) & (tt <= 35.0)]
    if len(up):
        print("     仰头那一段（26~35 s，%d 点）峰值 %+.2f°（旧口径 ≈ 0）"
              % (len(up), float(up.max())))
        ck("仰头那一段给负值（参考位没被仰头拖走）", float(up.max()) < 0.0,
           "%+.2f" % float(up.max()))


def _num(x):
    """CSV 单元 → float，解析不了就给 NaN。"""
    try:
        return float(x)
    except ValueError:
        return np.nan


def sessions():
    """【1d】真人长会话：4 场 `_face_live_*.csv` 共约 18 分钟。

    ⚠️ 旧口径**冻在这里**当基线（`ref_old`，分位用 `_OLD_Q`）—— 那是 2026-09-26 治①
       **之前**生产用的式子（参考位 = 最近 ROLL_WIN 秒的 p25）。它**不许跟着
       `src/face.py` 改**：它的用途就是"改动前后比一比"，跟着改就等于没有基线了。

    ★ 三次口径各自的"该出现什么"（这条断言跟着口径改过，别照旧版读）：
      · ①（治仰头假触发）：只许**摘**、不许添 —— 那时新参考位恒 ≥ 旧参考位，子集关系
        是**结构性**的，所以那条断言的作用是"证明实现没写反"。
      · ④（双侧修剪）：**故意会在持续低头时添**（旧口径低下去十几秒就自己松手，
        新的不松）—— 子集关系**不再成立**，照旧断会得到一条永远红的断言。改成
        一个**独立于参考位**的判据：**新添的每一秒，头必须真的低着**
        （`p95(最近 2 秒) − 整场 pitch 中位 ≥ HEAD_DEG`）。
      · 被摘掉的秒数照旧打印 —— 真人正常坐着时被摘掉的那些是①的收益。
    """
    import glob
    files = sorted(glob.glob(os.path.join(HERE, "_face_live_*.csv")))
    if not files:
        print("\n【1d】跳过：没有 _face_live_*.csv")
        return

    def ref_old(ts, p, j, now):
        """【冻结】2026-09-26 之前的参考位：最近 ROLL_WIN 秒的 p25。别改。"""
        m = (ts[:j] >= now - ROLL_WIN) & np.isfinite(p[:j])
        return float(np.percentile(p[:j][m], _OLD_Q)) if m.sum() >= 5 else np.nan  # noqa: PLR2004

    def ref_new(ts, p, j, now):
        """生产那份 —— 只能喂**前缀数组**（`head_ref` 只认 `ts[-1]` 那一刻）。
        `now` 参数不用，留着是为了和 `ref_old` 同形。"""
        return head_ref(ts[:j], p[:j])

    def grid(ts, p, ref_fn, step=0.2):
        """滑 2 秒窗，逐点 (t, hi − ref)，两条口径共用同一个窗、同一个锚点 ——
        所以这是**逐点**可比的 A/B（子集关系应该精确成立，不需要容差）。

        ⚠️ 锚点取 `t0` 之前**最后一个样本**（不管它是不是 NaN），和生产
           `head_swing` 一致（那边锚在缓冲末帧）。生产那份参考位**只认 `ts[-1]`**，
           所以必须喂**前缀数组** —— 写成 `head_ref(ts, p, now)` 是错的
           （第三个位置是 `base_win` 不是时刻；我第一版就这么写废了一整张表，
           现在签名已经是关键词专用，再那么写会当场 TypeError）。
        """
        rows = []
        t0 = ts[0] + HEAD_WIN
        while t0 <= ts[-1]:
            j = int(np.searchsorted(ts, t0, side="right"))
            if j >= 5:                                             # noqa: PLR2004
                now = float(ts[j - 1])
                m = (ts[:j] >= now - HEAD_WIN) & np.isfinite(p[:j])
                if m.sum() >= 5:                                   # noqa: PLR2004
                    rows.append((now, float(np.percentile(p[:j][m], 95))
                                 - ref_fn(ts, p, j, now)))
            t0 += step
        return rows

    def spans(rows):
        out, cur = [], None
        for t, v in rows:
            if v >= HEAD_DEG:
                cur = (t, t) if cur is None else (cur[0], t)
            elif cur is not None:
                out.append(cur)
                cur = None
        if cur is not None:
            out.append(cur)
        return out

    print("\n【1d】真人长会话（共 %d 场）：摘掉 = ①的收益；新添的必须是**真的低头**"
          % len(files))
    print("     %-34s %-8s %-11s %-11s %-8s %-9s %s"
          % ("会话", "跨度(s)", "旧口径触发", "新口径触发", "摘掉", "新添的",
             "最长的一段被摘掉"))
    ok_sub = True
    for path in files:
        ts, ps = [], []
        for line in open(path, encoding="utf-8", errors="replace").read().splitlines()[1:]:
            f = line.split(",")
            if len(f) < 5:
                continue
            # ⚠️ 解析失败要存 NaN、**不能丢这一行**：时间戳得留着，否则时间窗会算错；
            #    而且 NaN 的 pitch 正是生产里"没检到脸"那一档（`HeadMotion.push` 也是塞 NaN）。
            ts.append(_num(f[0]))
            ps.append(_num(f[4]))
        ts, ps = np.asarray(ts, float), np.asarray(ps, float)
        if len(ts) < 20:                                           # noqa: PLR2004
            continue
        old, new = grid(ts, ps, ref_old), grid(ts, ps, ref_new)
        # ⚠️ 逐点比，不按"段包含"：旧口径自己在阈值上下抖，会把一段碎成好几个小段
        #    （652 s 那场就是 401~402s、406~408s、408~410s 这样碎的）。按段包含去比
        #    会把成立的事判成红 —— 我第一版就是这么写错的。
        # ★ ④ 之后**不再断"子集"**：新口径故意在持续低头时多报（那是修复本身）。
        #   改成"新添的每一秒，头必须真的低着"，判据是**独立于参考位**的量：
        #   整场 pitch 的中位（当"平视位"的粗代理）+ 最近 2 秒的 p95。
        med_all = float(np.median(ps[np.isfinite(ps)]))
        added, bad_add = [], []
        for (t, vo), (_, vn) in zip(old, new):
            if vn >= HEAD_DEG and vo < HEAD_DEG:
                m = (ts > t - HEAD_WIN) & (ts <= t) & np.isfinite(ps)
                hi2 = float(np.percentile(ps[m], 95)) if m.sum() >= 5 else np.nan   # noqa: PLR2004
                (added if np.isfinite(hi2) and hi2 - med_all >= HEAD_DEG
                 else bad_add).append((t, vo, vn, hi2 - med_all))
        new_sec = sum(b - a for a, b in spans(new))
        old_sec = sum(b - a for a, b in spans(old))
        # 最长的一段"被摘掉"= 连续网格点上旧过、新不过
        longest = run = 0.0
        step = (old[1][0] - old[0][0]) if len(old) > 1 else 0.0
        for (_, vo), (_, vn) in zip(old, new):
            if vo >= HEAD_DEG > vn:
                run += step
                longest = max(longest, run)
            else:
                run = 0.0
        ok_sub = ok_sub and not bad_add
        print("     %-34s %-8.0f %-11s %-11s %-8s %-9s %s"
              % (os.path.basename(path), ts[-1] - ts[0], "%.1f s" % old_sec,
                 "%.1f s" % new_sec, "%.1f s" % (old_sec - new_sec),
                 "%.1f s" % (len(added) * step) if added else "（无）",
                 "%.1f s" % longest if longest else "（无）"))
        for t, vo, vn, dm in bad_add[:5]:
            print("        ❌ t=%.1f s 旧 %.1f° 没过、新 %.1f° 过了，"
                  "而头只比整场中位低 %.1f°" % (t, vo, vn, dm))
    ck("新添的触发都发生在**头真的低着**的地方（独立判据；④故意会多报）", ok_sub)


def clips():
    """读缓存里的片段，**用生产函数**扫一遍，和标定工具那张表对账。"""
    z = np.load(CACHE, allow_pickle=True)
    per = {g: [] for g in GROUPS}
    for k in z.files:
        parts = k.split("|")
        if len(parts) != 3 or parts[2] != "euler":
            continue
        g, clip, _ = parts
        if g not in per:
            continue
        tk = "%s|%s|t" % (g, clip)
        if tk not in z.files:
            continue
        ts = np.asarray(z[tk], float)
        eu = np.asarray(z[k], float)
        if eu.ndim != 2 or len(ts) < 20:                       # noqa: PLR2004
            continue
        p = eu[:, 0]
        if not np.isfinite(p).any():
            continue
        # 用**生产函数**（face.head_swing）在滑动窗上扫：传前缀数组，它自己取尾部
        # 的 HEAD_WIN 秒 —— 这和在线只喂缓冲是一回事。
        dE = d0 = upE = 0.0
        # ⚠️ 这里的 `ref` 是**旧口径**（窗首的 p25(10 s)）—— 它喂的是 d0/upE 那两列
        #    （"旧判据靠上抬顶过阈值"的代价表），所以分位必须用**冻结的** `_OLD_Q`，
        #    不能写 `HEAD_REF_Q`（2026-09-26 第四次起那个是 35，2026-09-26 之前是 25；
        #    用错了这两列量的就变成了另一个东西，而且**不会报错**）。
        ref = norm_by_time(ts, p, ROLL_WIN, q=_OLD_Q)
        i0 = 0
        t0 = ts[0]
        while t0 + TRAIL <= ts[-1]:
            j = int(np.searchsorted(ts, t0 + TRAIL, side="right"))
            if j >= 5:                                         # noqa: PLR2004
                v = head_swing(ts[:j], p[:j])
                if np.isfinite(v):
                    dE = max(dE, v)
                m = (ts >= t0) & (ts <= t0 + TRAIL) & np.isfinite(p)
                if m.sum() > 5 and np.isfinite(ref[m][0]):     # noqa: PLR2004
                    d0 = max(d0, float(np.percentile(p[m], 95)) - float(ref[m][0]))
                    upE = max(upE, float(ref[m][0]) - float(np.percentile(p[m], 5)))
            i0 += 1
            t0 += STEP
        per[g].append((clip, dE, d0, upE))
    return per


def self_release():
    """【5】判据**自己会不会松手**（2026-09-26 第四次，用户「不要锁存」）。

    红线里的锁存（`src/fuse.HEAD_HOLD`）去掉之后，**判据自己撑不撑得住就成了唯一的
    防线**。第三次那条"分段取 p25、再取 max"撑不住：它抗仰头、**不抗低头**（低头把
    最近那一段拖高，而 `max` 只采纳高的那一侧）。两条合成轨迹：

      A 持续低头 30 s（前面 60 s 直立）—— 低头期间**一次都不许**掉到阈值以下。
        旧口径实测：低下去 **13.0 秒**就掉了。
      B 长低头 60 s + 回正 60 s + **再低头 6 s** —— 那 6 秒**必须报得出来**。
        旧口径实测：只有 **5.7°**（"低了一分钟的人从此不报低头"）。

    ⚠️ 为什么必须合成：`_ear_raw.npz` 里**没有**超过几秒的持续低头（片段都 ≤27 s），
       真人录像里也没有"低一分钟再低六秒"这种动作。这个洞正是从【7】那张表的列缺口
       里漏过去的（它量"一次短偏移"，不量"一直偏着"）。
    ⚠️ 8 Hz + 固定种子，跑几次都一样；噪声 σ=2° 是为了别让"恒等于常数"掩盖抖动。
    ⚠️ 两条都用前缀数组喂 `head_swing`（与在线同构）。
    """
    print("\n【5】判据自己会不会松手（合成轨迹 8 Hz，噪声 σ=2°，固定种子 20260926）")
    hz, seed = 8.0, 20260926

    def traj(segs):
        rng = np.random.default_rng(seed)
        p = np.concatenate([mu + rng.normal(0.0, 2.0, int(d * hz)) for d, mu in segs])
        return np.arange(len(p)) / hz, p

    ta, pa = traj(((60.0, 0.0), (30.0, 25.0), (20.0, 0.0)))
    tt, vv = _along(ta, pa, t_from=62.0)
    ok = np.isfinite(vv)
    tt, vv = tt[ok], vv[ok]
    seg = vv[tt <= 88.0]
    lo = float(seg.min()) if len(seg) else float("nan")
    print("     A 持续低头 30 s：低头期间最小 %+.2f°（要 ≥ %.0f°）" % (lo, HEAD_DEG))
    ck("A 人还低着的时候判据不松手（旧口径 13.0 s 就掉）", lo >= HEAD_DEG, "%+.2f" % lo)

    tb, pb = traj(((240.0, 0.0), (60.0, 25.0), (60.0, 0.0), (6.0, 25.0), (20.0, 0.0)))
    tt, vv = _along(tb, pb, t_from=360.0)
    ok = np.isfinite(vv)
    tt, vv = tt[ok], vv[ok]
    seg = vv[(tt >= 360.0) & (tt <= 366.0)]
    pk = float(seg.max()) if len(seg) else float("nan")
    print("     B 长低头 60 s + 回正 60 s 后再低头 6 s：峰值 %+.2f°（要 ≥ %.0f°）"
          % (pk, HEAD_DEG))
    ck("B 低过一分钟之后**仍然**报得出低头（旧口径只有 5.7°）", pk >= HEAD_DEG,
       "%+.2f" % pk)


def main():
    print("HEAD_DEG=%.1f  HEAD_WIN=%.1f  ROLL_WIN=%.1f  HEAD_REF_Q=%.0f"
          % (HEAD_DEG, HEAD_WIN, ROLL_WIN, HEAD_REF_Q))
    synth()
    return_case()
    recorded()
    sessions()

    per = clips()
    print("\n【2】口径一致：生产函数 `face.head_swing` vs 标定工具落盘的那张表")
    if not os.path.exists(TABLE):
        ck("标定表在（%s）" % os.path.basename(TABLE), False,
           "先跑 _scratch/_calib_head_down.py")
    else:
        with open(TABLE, encoding="utf-8") as fh:
            tab = json.load(fh)
        # 常量一起对：face.py 里的常量改了而这张表没重跑 = 拿着旧表当证据
        same = (abs(tab["ref_win"] - HEAD_REF_WIN) < 1e-9
                and abs(tab["q"] - HEAD_REF_Q) < 1e-9
                and abs(tab["tol"] - HEAD_DEG) < 1e-9
                and int(tab["iters"]) == int(HEAD_REF_ITERS))
        ck("标定表是**当前常量**下量的（修剪 win %.0fs、q%.0f、tol %.0f°、%d 轮）"
           % (tab["ref_win"], tab["q"], tab["tol"], tab["iters"]), same,
           "" if same else "表里是 win %.0fs q%.0f tol %.0f° %d 轮"
           "（生产是 %.0fs q%.0f tol %.0f° %d 轮）—— 重跑 _calib_head_down.py"
           % (tab["ref_win"], tab["q"], tab["tol"], tab["iters"],
              HEAD_REF_WIN, HEAD_REF_Q, HEAD_DEG, HEAD_REF_ITERS))
        print("     %-9s %-6s %-16s %-16s %s"
              % ("组", "段数", "生产(中位/最大)", "工具(中位/最大)", "差"))
        for g in GROUPS:
            if not per[g]:
                continue
            e = sorted(v for _, v, _, _ in per[g])
            med, mx = e[len(e) // 2], e[-1]
            t = tab["groups"].get(g)
            if not t:
                ck("工具表里有 %s 这一组" % g, False, "表是旧的")
                continue
            dm, dx = abs(med - t["med"]), abs(mx - t["max"])
            ck("口径一致 · %s（中位/最大差都 < 0.5°）" % g, dm < 0.5 and dx < 0.5,
               "%.1f/%.1f vs %.1f/%.1f（Δ %.2f/%.2f）"
               % (med, mx, t["med"], t["max"], dm, dx))

    print("\n【3】阈值 %.0f° 上的触发数（正常要 0，疲劳要尽量多）" % HEAD_DEG)
    for g in GROUPS:
        if not per[g]:
            continue
        n = sum(v >= HEAD_DEG for _, v, _, _ in per[g])
        print("     %-9s %2d/%d" % (g, n, len(per[g])))
    nrm = per["normal"]
    ck("正常 0 误报", sum(v >= HEAD_DEG for _, v, _, _ in nrm) == 0,
       "%d/%d" % (sum(v >= HEAD_DEG for _, v, _, _ in nrm), len(nrm)))
    fat = per["fatigue"]
    hit = sum(v >= HEAD_DEG for _, v, _, _ in fat)
    ck("疲劳命中 ≥ 22/26（③ 是 24/26；④ 用 1 段换掉「自己松手」，23/26）",
       hit >= 22, "%d/%d" % (hit, len(fat)))

    print("\n【4】旧判据靠**上抬**顶过阈值的那几段（= 用户报的「仰头也算低头」）")
    for g in ("normal", "glance"):
        for clip, dE, _, upE in sorted(per[g], key=lambda x: -x[3]):
            if upE >= HEAD_DEG and dE < HEAD_DEG:
                print("     %-9s %-12s 上抬 %.1f° ≥ %.0f°，而 dipE 只有 %.1f° → "
                      "旧判据会误报，新的不会" % (g, clip, upE, HEAD_DEG, dE))
    bad = sum(1 for g in ("normal", "glance") for _, v, _, u in per[g]
              if u >= HEAD_DEG and v < HEAD_DEG)
    print("     合计 %d 段（缓存里只有这么点 —— 真人是**约三成**，见 "
          "_probe_live_rules.py 的【3】）" % bad)

    self_release()

    print("\n" + "=" * 66)
    if REDS:
        print("❌ 有问题：")
        for r in REDS:
            print("   · " + r)
    else:
        print("✅ 方向、口径、代价、自松手四项全过")
    sys.stdout.flush()
    # ⚠️ 退码**跟着 REDS 走**。原来恒 `os._exit(0)`，于是"先看它变红"只能靠人眼读那几
    #    行输出 —— 而人眼漏读正是这类守卫失效的常态（项目里已经有两条恒假断言的前科）。
    os._exit(1 if REDS else 0)


if __name__ == "__main__":
    main()
