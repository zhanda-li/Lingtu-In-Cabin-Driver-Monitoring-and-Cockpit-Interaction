# -*- coding: utf-8 -*-
"""搏动检测器到底怎么抖 —— 漏检 / 多检 / 时抖，三选一。**全离线**，不碰串口。

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch/_hr_jitter.py [录...]

## 为什么要先分清这三件事

`rmssd()` 出来的数是垃圾（81~253 ms，见 `hr/README.md`），根因是"相邻两拍一长一短
交替"。但那个现象有**三种完全不同的来路**，修法南辕北辙：

  · **漏检**：该登记的拍没登记 ⟹ 间隔序列里混进"两个心跳那么长"的项。
  · **多检**：一个心跳被登记成两拍 ⟹ 混进"半拍那么长"的项。
  · **时抖**：每一拍都登记了、总数也对，但登记的时刻在真峰附近飘。

**判据是看间隔落在哪。** 生理范围是 `MIN_IBI_S`~`MAX_IBI_S`（330~1600 ms）：

    短于 330 ms  ⟹ 多检（一拍被劈成两下）
    330~1600 ms  ⟹ 正常
    长于 1600 ms ⟹ 漏检

⚠️ **别拿"被采纳的间隔"算统计量。** 那个数列已经把超范围的项**扔掉了** ——
用它算出来的平均/中位/max 全是幸存者偏差，而且样本数可能只剩个位数。
本脚本用 `beat_times` 里**全部**相邻拍（含被拒的），这才是检测器的原始输出。

⚠️ **两处环是有界的，别当成全量**：
  · `beat_times` 是 `deque(maxlen=64)` ⟹ 只拿得到**最后 64 拍**；
  · `beats` 计数器**不被 `_reset_beats()` 清**（`serial_hr.py:490-493` 明写了为什么），
    所以它比环里的拍数多 —— 多出来的多半是**手指上来之前**的噪声拍。
  脚本会把这两个数分开报，别混着看。

## 一条已经排除的假设

`_register_beat` 登记的是**包络的局部极大**，不是"跌回阈值那次采样"
（`serial_hr.py:565-571`：在阈值上方期间一路 `peak_y/peak_t/peak_ms` 取最大，
跌回下方时才登记 `peak_t`）。所以"改成登记峰顶"这个修法**代码里早就有了**，
时抖不该记在它头上。

⚠️ 本脚本**只读**录音文件，不写盘。
"""

import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(ROOT, "ui"))

DEFAULT = "runs/_hr_nn_20260926_205912.txt"
SEC_WIN = 10.0          # 每 10 秒一段去看，免得整段的平均把局部的错盖掉


def _seg(rows, title):
    if not rows:
        print("   （没有一个）")
        return
    print("   %s" % title)
    line = "     "
    for x in rows:
        if len(line) + 6 > 76:
            print(line)
            line = "     "
        line += "%6.0f" % x
    print(line)


def main():
    import serial_hr

    rec = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    path = rec if os.path.isabs(rec) else os.path.join(ROOT, rec)
    if not os.path.exists(path):
        print("找不到录音：%s" % path)
        return 1

    dev = serial_hr.SerialHr(enabled=False)        # 不起读线程，手动喂
    tr = dev._tracker
    min_ms = serial_hr.MIN_IBI_S * 1000.0
    max_ms = serial_hr.MAX_IBI_S * 1000.0

    n_samp = 0
    t_first = None
    t_last = None
    # 每一秒的直流均值 —— 用来看"手指到底在不在位"，不然间隔序列没法解释
    dc_sum = 0.0
    dc_n = 0
    dc_by_sec = []
    cur_sec = None
    spans = []              # 每登记一拍记一次 (t_s, nn_span_ms, len(nn_ms))
    _last_beats = [0]

    for line in io.open(path, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line.startswith("D,"):
            continue
        f = line.split(",")
        if len(f) != 4:
            continue
        t_ms = int(f[1])
        ir = int(f[3])
        dev._feed(t_ms, ir)
        n_samp += 1
        if t_first is None:
            t_first = t_ms
        t_last = t_ms
        sec = (t_ms - t_first) // 1000
        if sec != cur_sec:
            if cur_sec is not None and dc_n:
                dc_by_sec.append((cur_sec, dc_sum / dc_n))
            cur_sec = sec
            dc_sum = 0.0
            dc_n = 0
        dc_sum += tr.dc_mean()
        dc_n += 1
        # RMSSD 的连续性链走到哪了 —— 每一拍记一次，用来判"断链是常态还是偶发"
        if tr.beats != _last_beats[0]:
            _last_beats[0] = tr.beats
            spans.append((tr.last_t - t_first / 1000.0, tr.nn_span_ms,
                          len(tr.nn_ms)))
    if cur_sec is not None and dc_n:
        dc_by_sec.append((cur_sec, dc_sum / dc_n))

    bt_ms = [int(round(t * 1000.0)) for t in tr.beat_times]     # 环里最后 ≤64 拍
    diffs = [bt_ms[i + 1] - bt_ms[i] for i in range(len(bt_ms) - 1)]

    print("=" * 78)
    print("录音：%s" % os.path.basename(path))
    print("样本 %d 个（%.1f 秒）" % (n_samp, ((t_last - t_first) / 1000.0)
                                       if t_first is not None else 0.0))
    print("历次登记搏动 %d 拍（**含手指上来之前的噪声拍**，`beats` 计数器不清）"
          % tr.beats)
    print("`beat_times` 环里剩 %d 拍（maxlen=64）⟹ 相邻间隔 %d 个"
          % (len(bt_ms), len(diffs)))
    if len(bt_ms) >= 2:
        print("环里那几拍覆盖的时刻范围 %.1f ~ %.1f s（跨 %.1f 秒）"
              % ((bt_ms[0] - t_first) / 1000.0, (bt_ms[-1] - t_first) / 1000.0,
                 (bt_ms[-1] - bt_ms[0]) / 1000.0))
    print("=" * 78)
    if len(diffs) < 8:
        print("间隔太少，判不了。")
        return 1

    short = [d for d in diffs if d < min_ms]
    good = [d for d in diffs if min_ms <= d <= max_ms]
    long_ = [d for d in diffs if d > max_ms]
    n = len(diffs)

    print()
    print("【间隔落在哪】判据线 %.0f ~ %.0f ms" % (min_ms, max_ms))
    print("   < %.0f ms  多检（一拍劈成两下）  %3d 个  %5.1f%%"
          % (min_ms, len(short), 100.0 * len(short) / n))
    print("   %.0f~%.0f   正常                  %3d 个  %5.1f%%"
          % (min_ms, max_ms, len(good), 100.0 * len(good) / n))
    print("   > %.0f ms  漏检（两次心跳算一次）%3d 个  %5.1f%%"
          % (max_ms, len(long_), 100.0 * len(long_) / n))

    print()
    print("【全部 %d 个相邻间隔（毫秒，按时间顺序）】" % n)
    _seg(diffs[:66], "前 66 个：")

    s = sorted(diffs)
    med = s[n // 2]
    avg = sum(diffs) / n
    print()
    print("【平均 vs 中位 —— **用全部 %d 个**，不是被采纳的那些】" % n)
    print("     平均 %.1f ms   中位 %.1f ms   差 %.1f%%"
          % (avg, med, 100.0 * abs(avg - med) / med))
    print("     最小 %.0f   最大 %.0f" % (s[0], s[-1]))

    sp = tr.spec_bpm()
    per = (60000.0 / sp) if sp else None
    print()
    print("【频谱那一路的独立说法】（只看整段波形主频，不看单拍）")
    print("     spec_bpm = %s  -> 周期 %s ms"
          % (("%.1f" % sp) if sp is not None else "None",
             ("%.0f" % per) if per else "——"))
    if per:
        span_s = (bt_ms[-1] - bt_ms[0]) / 1000.0
        print("     按它算，这 %.1f 秒里应该有 %.1f 拍；环里是 %d 拍"
              % (span_s, span_s * sp / 60.0, len(bt_ms)))

    # ---- 找"劈拍"：一短一长挨着、且两者之和 ≈ 两个真周期 ----
    # ⚠️ 判据**不能拿闸线（330 ms）去卡**：实测那一对是 350 / 1470，两个都
    #    **落在闸内**、都被当成合法间隔收了进去。要拿**中位数**当尺子。
    sp_pairs = []
    for i in range(n - 1):
        a, b = diffs[i], diffs[i + 1]
        if a <= b:
            s_, l_ = a, b
        else:
            s_, l_ = b, a
        if s_ < 0.65 * med and l_ > 1.35 * med and abs(s_ + l_ - 2 * med) < 0.2 * med:
            sp_pairs.append((i, a, b))

    print()
    print("【找「劈拍」：一短一长挨着、两者之和 ≈ 两个真周期】")
    print("     （左右两边都以 **中位数 %.0f ms** 当尺子，不是拿闸线卡 —— " % med)
    print("      实测那对 350/1470 **两个都在闸内**，用闸线一个都筛不出来）")
    if not sp_pairs:
        print("     没找到。")
    for (i, a, b) in sp_pairs:
        print("     第 %d、%d 个之间：%d + %d = %d  (2×中位 = %.0f)"
              % (i + 1, i + 2, a, b, a + b, 2 * med))
    print("     共 %d 处" % len(sp_pairs))

    # 把劈拍那一带剔除之后 RMSSD 会变成多少 —— 这才是"没有它时本来是多少"
    # ⚠️ 剔的是**三个**差分不是一个：`diffs[i-1]→diffs[i]`、`diffs[i]→diffs[i+1]`、
    #    `diffs[i+1]→diffs[i+2]` 都跨过了这一对。少剔一个，剩下的那个照样是
    #    几百毫秒的假差分，算出来的"干净值"会偏高。
    ds_all = [diffs[i + 1] - diffs[i] for i in range(n - 1)]
    r_all = (sum(d * d for d in ds_all) / len(ds_all)) ** 0.5
    bad = set()
    for (i, _, _) in sp_pairs:
        bad |= {i - 1, i, i + 1}
    keep = [ds_all[k] for k in range(len(ds_all)) if k not in bad]
    r_clean = ((sum(d * d for d in keep) / len(keep)) ** 0.5) if keep else None
    if sp_pairs and r_clean is not None:
        print("     ⟹ 把劈拍那**三个**跨过它的差分都剔掉后，RMSSD 会是 "
              "**%.1f ms**（现在 %.1f ms）" % (r_clean, r_all))

    print()
    print("【★ 决定性的一问：这段录音上 `rmssd()` 出不出数】")
    span_s = tr.nn_span_s()
    print("     结束时 nn_span_s = %.3f 秒（门槛 %.0f 秒）"
          % (span_s, serial_hr.HR_NN_NEED_MS / 1000.0))
    print("     结束时链上 %d 个 NN，环上限 %d" % (len(tr.nn_ms), serial_hr.HR_NN_MAX))
    if spans:
        mx = max(s for (_, s, _) in spans)
        mx_at = [t for (t, s, _) in spans if s == mx][0]
        brk = sum(1 for i in range(1, len(spans))
                  if spans[i - 1][1] > 0 and spans[i][1] == 0)
        print("     整段里链最长到过 %.3f 秒（在 t=%.1f s）；中途断链 %d 次"
              % (mx / 1000.0, mx_at, brk))
        reach = [t for (t, s, _) in spans
                 if s >= serial_hr.HR_NN_NEED_MS]
        if reach:
            print("     链够 %.0f 秒的时刻：第一次在 t=%.1f s，之后一连 %d 拍都够"
                  % (serial_hr.HR_NN_NEED_MS / 1000.0, reach[0], len(reach)))
        else:
            print("     **一次都没够过 %.0f 秒**" % (serial_hr.HR_NN_NEED_MS / 1000.0))

    rr = tr.rmssd()
    print()
    print("     最后那一段链的 rmssd() = %s"
          % (("%.1f ms" % rr) if rr is not None else "None（不出数）"))
    if len(tr.nn_ms) >= 2:
        nn = list(tr.nn_ms)
        print("     链上那 %d 个 NN（毫秒）：%s" % (len(nn), nn))
        ds = [nn[i + 1] - nn[i] for i in range(len(nn) - 1)]
        print("     它们的一阶差分：%s" % ds)
        ss = sorted(d * d for d in ds)
        contrib = sum(ss[-3:]) / sum(ss) * 100.0
        print("     ⟹ 最大的 3 个差分占了 Σd² 的 %.0f%%（%s）"
              % (contrib, ["%d" % d for d in sorted(ds, key=abs)[-3:]]))

    # 整段（不分链）手算一个 RMSSD，当参照
    if len(diffs) >= 3:
        print()
        print("     【参照】拿**全部 %d 个相邻间隔**手算（不分链、不问跨度）："
              % len(diffs))
        print("            rmssd = %.1f ms" % r_all)
        top = sorted(ds_all, key=abs)[-5:]
        print("            最大的 5 个差分 %s 占了 Σd² 的 %.0f%%"
              % ([int(x) for x in top],
                 100.0 * sum(x * x for x in top) / sum(x * x for x in ds_all)))


    print("   窗口      拍数  平均IBI  中位IBI  最短   最长   直流均值")
    print("   " + "-" * 66)
    for x in range(int((t_last - t_first) / 1000.0 / SEC_WIN) + 1):
        t0 = t_first + x * SEC_WIN * 1000.0
        seg = [bt_ms[k] for k in range(len(bt_ms)) if t0 <= bt_ms[k] < t0 + SEC_WIN * 1000.0]
        seg_d = [bt_ms[k + 1] - bt_ms[k] for k in range(len(bt_ms) - 1)
                 if t0 <= bt_ms[k] < t0 + SEC_WIN * 1000.0]
        dcs = [v for (k, v) in dc_by_sec if x * SEC_WIN <= k < (x + 1) * SEC_WIN]
        dc_avg = (sum(dcs) / len(dcs)) if dcs else 0.0
        if len(seg_d) < 3:
            continue
        ss = sorted(seg_d)
        print("   %4.0f~%4.0fs  %4d  %7.1f  %7.1f  %5.0f  %6.0f  %9.0f"
              % (x * SEC_WIN, (x + 1) * SEC_WIN, len(seg_d),
                 sum(seg_d) / len(seg_d), ss[len(ss) // 2], ss[0], ss[-1], dc_avg))

    print()
    print("=" * 78)
    print("判读")
    print("=" * 78)
    print("  手指在位判据：直流 > %.0f（下面每段的「直流均值」对照着看）"
          % serial_hr.FINGER_DC_MIN)
    print()
    fs, fl = 100.0 * len(short) / n, 100.0 * len(long_) / n
    print("  ① 检测器本身健不健")
    print("     %.0f%% 的间隔落在 %.0f~%.0f ms 里；平均与中位差 %.1f%%"
          % (100.0 * len(good) / n, min_ms, max_ms,
             100.0 * abs(avg - med) / med))
    if per:
        print("     频谱说这 %.1f 秒该有 %.1f 拍，环里 %d 拍 —— %s"
              % ((bt_ms[-1] - bt_ms[0]) / 1000.0, (bt_ms[-1] - bt_ms[0]) / 1000.0 * sp / 60.0,
                 len(bt_ms),
                 "对得上，**总数没大错**"
                 if abs(len(bt_ms) - (bt_ms[-1] - bt_ms[0]) / 1000.0 * sp / 60.0) < 4
                 else "**对不上，总数是错的**"))
    if fs < 5 and fl < 5:
        print("     ⟹ 检测器是好的。别再往「峰值检测坏了」那条路上去查。")
    else:
        print("     ⟹ 短 %.0f%% / 长 %.0f%% —— 检测器有实质性问题。" % (fs, fl))

    print()
    print("  ② 为什么页面上**一直**看不到 RMSSD（这条最容易被答错）")
    if spans:
        reach = [t for (t, sp_, _) in spans if sp_ >= serial_hr.HR_NN_NEED_MS]
        mx = max(s for (_, s, _) in spans)
        if reach:
            print("     链要**连着不断**攒够 %.0f 秒才出数。这段 %.0f 秒录音里，"
                  % (serial_hr.HR_NN_NEED_MS / 1000.0,
                     (t_last - t_first) / 1000.0))
            print("     链最长只到过 %.1f 秒，**第一次够格是 t=%.0f 秒**。"
                  % (mx / 1000.0, reach[0]))
            print("     ⟹ 演示时手指按不到那么久 / 中途动一下就重来，屏幕上就永远")
            print("        是 `--`。**这不是算法不出数，是还没攒够。**")
        else:
            print("     链最长只到过 %.1f 秒，够不着 %.0f 秒 ⟹ 这段数据里根本出不了数。"
                  % (mx / 1000.0, serial_hr.HR_NN_NEED_MS / 1000.0))

    print()
    print("  ③ 出数了的话，那个数可信吗")
    if rr is not None and len(tr.nn_ms) >= 2:
        nn = list(tr.nn_ms)
        ds = [nn[i + 1] - nn[i] for i in range(len(nn) - 1)]
        ss = sorted(d * d for d in ds)
        top3 = sum(ss[-3:]) / sum(ss) * 100.0
        print("     rmssd() = %.1f ms。但链上 %d 个一阶差分里，**最大的 3 个"
              % (rr, len(ds)))
        print("     就占了 Σd² 的 %.0f%%** —— RMSSD 是平方和，一次异常拍就能"
              % top3)
        print("     盖过其余 %d 个。" % (len(ds) - 3))
        if sp_pairs:
            print("     那 3 个差分全部来自第 %d/%d 个间隔那一对 %d+%d"
                  % (sp_pairs[0][0] + 1, sp_pairs[0][0] + 2,
                     sp_pairs[0][1], sp_pairs[0][2]))
            print("     ⟹ 这个 %.1f ms **不代表这个人的 HRV**，它代表「一次劈拍」。" % rr)
            if r_clean is not None:
                print("        把跨过那一对的三个差分剔掉后：RMSSD = **%.1f ms**"
                      % r_clean)
                print("        （注意：剔完还剩 %.1f —— 说明**其余那些拍本身就不算"
                      "干净**，" % r_clean)
                print("          不是「剔掉那一下就好了」，别指望一个过滤器救回全部。）")
        print()
        print("     ⚠️ 那对 %d+%d 之和 = %d ≈ 2×中位(%.0f) —— 这正是**代偿间歇**"
              % (sp_pairs[0][1], sp_pairs[0][2], sp_pairs[0][1] + sp_pairs[0][2], 2 * med)
              if sp_pairs else "")
        if sp_pairs:
            print("        的形状。它有两种来路：一次真早搏，或一次劈拍（一拍登记")
            print("        成两下）。**在间隔序列上这两者不可分**（和 `MAX_IBI_SPREAD`")
            print("        被推翻是同一条道理）—— 但**处置相同**：HRV 的标准做法")
            print("        本来就是剔除异位搏动/伪间隔，两条来路都该剔。")
    else:
        print("     链上数不够，这一步没得判。")

    print()
    print("  ⚠️ 以上是判读，不是结论 —— 要看波形坐实的话：")
    print("     `hr\\live.bat`（实时窗口，会画带通后的波 + 五道门判据行）")
    return 0


if __name__ == "__main__":
    try:
        rc = main()
    except Exception:                                               # noqa: BLE001
        import traceback
        traceback.print_exc()
        rc = 1
    sys.exit(rc)
