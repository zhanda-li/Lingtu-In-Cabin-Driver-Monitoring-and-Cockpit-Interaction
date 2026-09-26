"""对拍 `ui/cam.py` 与 `src/fuse.py` —— 证明界面那份融合胶水没有抄歪。

    python src/fuse.py --replay X.mp4 --fast --no-display --no-voice --quiet \
                       --log-probs runs/_ref.csv
    python ui/cam.py   --replay X.mp4 --fast --dump runs/_cam.csv
    python tools/cmp_cam_fuse.py runs/_ref.csv runs/_cam.csv

**为什么非对拍不可**：`ui/cam.py` 里的融合块是从 `src/fuse.py:507~644` **抄**过来的
（fuse.py 是支路一的回归基线，不能改，它也没有可挂回调的缝）。抄写就有抄歪的风险，
而"界面上的 L 级别和 fuse.py 不一致"是个**看不出来**的错 —— 界面上数字照样在动。

只有 `--fast` 那一路能这么比：它不按真实时间配速，帧源时间轴是确定的；
实速回放会因为调度抖动丢帧，两边的丢弃时机不同，本来就不该逐行相等。

`mark` 那一列**不参与比较**：fuse.py 靠空格键手动 toggle，cam.py 恒写 0。
真要带着标记比，先在 fuse.py 那边别按空格。

退出码：0 = 一致，1 = 不一致（能挂进批处理）。
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config as C

# 参与比较的列 = `t` + 类别列 + 下面这段固定列（顺序就是 fuse.py 写表头的顺序）。
# ⚠️ 类别列**从 `config.CLASSES` 推**，不要手写成字面量：这份清单以前写死过
# `"glance"`/`"phone"`，类别删掉之后它们成了**查不到的死列** ——
# 而 `rows()` 用的是 `DictReader` + `.get(c)`，缺列只会让 `x` 是 `None`、两边
# 都 `None` 就"相等"，于是**对拍全绿但根本没比到那一列**（静默失效）。
# 现在由 `check_header()` 在开跑前把这件事变成**红字**。
TAIL_COLS = ["l1", "gate", "ema_normal", "p_fat", "l2", "perclos", "brate", "nod",
             "en_now", "d_pitch", "yawn_sec", "head_swing", "l_fused", "ear", "mar",
             "pitch"]
# ⚠️ `head_swing` 是 2026-09-26 补进来的：治①把 `face.head_swing` 的参考位换了
#    口径，而**这份清单里原来没有它** —— 也就是说列在两边都写着、值也都在动，
#    对拍却从来没比过这一列（正是本文件开头警告的那种"绿得没根据"）。
#    加它之前先确认两边格式化一致：两个 `cell()` 都把非有限值写成 `-`。
COLS = ["t"] + list(C.CLASSES) + TAIL_COLS


def rows(path):
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def check_header(pa, pb, a, b):
    """两边表头必须一致，且比较清单里的每一列都真的存在。返回错误说明或 None。

    这是本脚本唯一能防"静默漏比"的地方 —— 宁可红，也不要绿得没根据。
    """
    if not a or not b:
        return None                       # 空文件的报错在 main 里有更清楚的一句
    ha = [c for c in a[0] if c != "mark"]
    hb = [c for c in b[0] if c != "mark"]
    if ha != hb:
        only_a = [c for c in ha if c not in hb]
        only_b = [c for c in hb if c not in ha]
        return (f"两边表头不一致：{pa.name} 多 {only_a}，{pb.name} 多 {only_b}。\n"
                f"    多半有一边的服务是**旧进程**（源码改了但没重启），"
                f"或者类别数与 config.CLASSES 对不上。")
    missing = [c for c in COLS if c not in ha]
    if missing:
        return (f"要比的列 {missing} 在 CSV 里根本不存在 —— 那就是没比到。\n"
                f"    CSV 实际表头：{ha}\n"
                f"    多半是 config.CLASSES 改了之后这里没跟上。")
    return None


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    pa, pb = Path(sys.argv[1]), Path(sys.argv[2])
    a, b = rows(pa), rows(pb)
    print(f"{pa.name}: {len(a)} 次决策    {pb.name}: {len(b)} 次决策")
    if not a or not b:
        print("有一边是空的 —— 回放是不是没跑完？")
        return 1

    err = check_header(pa, pb, a, b)
    if err:
        print(f"✗ {err}")
        return 1
    print(f"  比 {len(COLS)} 列：{','.join(COLS)}")

    # 差异按列汇总。**最后一格对不上**多半只是段尾截断，单列出来别混进来。
    diff = {}
    n = min(len(a), len(b))
    for i in range(n):
        for c in COLS:
            x, y = a[i].get(c), b[i].get(c)
            if x != y:
                diff.setdefault(c, []).append((i, x, y))
    if not diff:
        print(f"★ 前 {n} 行逐格完全一致")
    else:
        print(f"✗ {len(diff)} 列有差异：")
        for c, v in sorted(diff.items(), key=lambda kv: -len(kv[1])):
            i, x, y = v[0]
            print(f"   {c:<11} {len(v):>4}/{n} 处不同   首次 第{i}行 "
                  f"fuse={x!r} cam={y!r}")

    # 顺手报一下闸门开合比例：全关的片段验不到支路二那段，
    # 那种"一致"是结构性的，别当成验过了。
    for name, r in ((pa.name, a), (pb.name, b)):
        op = sum(1 for x in r if x.get("gate") == "1")
        print(f"   闸门开 {op}/{len(r)}（{op / max(len(r), 1) * 100:.0f}%）  {name}")
    if diff:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
