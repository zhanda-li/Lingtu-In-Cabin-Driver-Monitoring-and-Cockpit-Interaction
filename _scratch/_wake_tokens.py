# -*- coding: utf-8 -*-
"""唤醒词诊断：让模型自己说，它到底把「你好小瑞」听成了哪串拼音。

    python _scratch/_wake_tokens.py

**为什么要有这个脚本。** 当时 `_check_wake.py` 量出来的形状是：三个正样本只有
第一个叫醒，另外两个不叫；而且 `num_trailing_blanks ∈ {0,1,2} × threshold ∈
{0.25,0.15}` 六种组合**一模一样**。于是当时的推断是：不是"判定太严"，而是那串
拼音 token 从来没被走完过 —— 声学模型在这种语调下吐的韵母/声调和
`keywords.txt` 里写的那一行不是同一串。

⚠️ **那个推断是错的**，真正的漏唤醒原因不在模型里，在我的测试里
（`debounce_s` 按挂钟时间算、回放把时间压扁，见 `_scratch/_wake_reset.py`）。
修好之后重跑，这个脚本给出的答案是干净的：

  · **V01（`n ǐ h ǎo x iǎo r uì`）是唯一命中的一种，三个正样本全中**；
    另外 23 种声调拼法一次都没中（`neg_xiaoxin`/`neg_name_only` 也始终不中）。
  · 结论：声学模型对这个词的 token 输出**稳定且按本调**，`keywords.txt` 里现在
    写的那一行就是对的，**不需要加近似词**。

留着这个脚本的价值是：以后改唤醒词（比如换成"小瑞小瑞"）时，先用它把候选拼法
一次列全，省得一个个试。

**怎么办：不再猜，改成问。** 把每个音节所有说得通的声调拼法**全列进去**，
每条起一个不同的名字（`@V3_ni3hao3…`），一次喂进去，哪条命中就是哪串。
这就是个"多重假设"探测 —— 同时也顺手验证了多关键词共存（`max_active_paths`
必须 ≥ 关键词条数，否则排在后面的词根本搜不到，见 `ui/voice/kws.py`）。

⚠️ 关键词条数 = 假设数，所以这个脚本的 `max_active_paths` 给得很大。
   在 `keywords.txt` 里也这么干**不合适**：词表越长越容易误唤醒，真收尾时只留
   实测命中的那几条。
"""
import itertools
import os
import sys
import time
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ui"))
sys.path.insert(0, str(ROOT / "ui" / "voice"))

import asr                                    # noqa: E402  只借它的 wav 解析
from kws import WakeWord, SR                  # noqa: E402

CHUNK = 1600

# 「你好小瑞」四个音节，每个音节列出所有说得通的 token 拼法。
#   你 nǐ  → ǐ 是本调；í 是三声连读变调（3+3→2+3，实际发音就是 ní hǎo）；
#            i 是不带调（词表里有不带调的韵母，模型可能吐那个）
#   好 hǎo → ǎo 本调；áo 变调
#   小 xiǎo→ iǎo 本调；iáo 变调（小 + 四声，规范上不该变，列上排除掉）
#   瑞 ruì → uì 四声；uí/ui 备选
SYLLABLES = {
    "你": ["n ǐ", "n í", "n i"],
    "好": ["h ǎo", "h áo", "h ao"],
    "小": ["x iǎo", "x iáo", "x iao"],
    "瑞": ["r uì", "r uí", "r ui"],
}
TRIALS = ["pos_hello_xiaorui", "pos_hello_xiaorui2", "pos_hello_xiaorui_slow",
          "neg_xiaoxin", "neg_name_only"]


def variants(known: set[str]):
    """笛卡尔积 → 每条一个名字。token 不在模型词表里的组合直接丢掉（留着建实例会报错）。"""
    out, skipped = [], 0
    for combo in itertools.product(*(SYLLABLES[k] for k in SYLLABLES)):
        toks = [t for part in combo for t in part.split()]
        if any(t not in known for t in toks):
            skipped += 1
            continue
        name = "V%02d_%s" % (len(out) + 1, "_".join(part.replace(" ", "") for part in combo))
        out.append((name, " ".join(part for part in combo), "+".join(combo)))
    return out, skipped


def main() -> int:
    kw_file = ROOT / "ui" / "voice" / "keywords.txt"
    mdir = WakeWord().model_dir
    if mdir is None:
        print("找不到 KWS 模型，先跑 python ui/voice/fetch_models.py kws")
        return 1
    known = {l.split()[0] for l in (mdir / "tokens.txt").read_text(
        encoding="utf-8").splitlines() if l.strip()}
    base = [l.strip() for l in kw_file.read_text(encoding="utf-8").splitlines() if l.strip()]

    vs, skipped = variants(known)
    print("=" * 78)
    print("假设表：每个音节的声调拼法做笛卡尔积")
    print("=" * 78)
    for name, toks, combo in vs:
        star = "  ← 现在 keywords.txt 里写的就是它" if toks in base else ""
        print("  %-34s %-24s %s%s" % (name, toks, combo, star))
    print("  （另有 %d 种组合的 token 不在模型词表里，已跳过）" % skipped)

    tmp = ROOT / "runs" / "_wake_tokens.txt"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text("\n".join("%s @%s" % (toks, name) for name, toks, _ in vs) + "\n",
                   encoding="utf-8")

    w = WakeWord({"keywords_file": str(tmp), "max_active_paths": len(vs) + 4})
    print("\n  建实例：关键词 %d 条，max_active_paths=%d  →  %s"
          % (len(vs), w.cfg["max_active_paths"], "就绪" if w.ready else w.why))
    if not w.ready:
        return 1

    sdir = ROOT / "runs" / "wake_samples"
    print("\n" + "=" * 78)
    print("逐样本喂进去，看哪些假设命中")
    print("=" * 78)
    for stem in TRIALS:
        p = sdir / (stem + ".wav")
        if not p.exists():
            print("  ? %s（样本不在，跳过）" % stem)
            continue
        x = asr.wav_bytes_to_float32(p.read_bytes(), want_sr=SR)
        w.clear_debounce()          # ← 不清的话后面样本全被上一个命中吃掉
        t0, hits = time.perf_counter(), []
        for i in range(0, len(x), CHUNK):
            for d in w.feed(x[i:i + CHUNK]):
                hits.append((d, (i + CHUNK) / SR * 1000.0))
        ms = (time.perf_counter() - t0) * 1000.0
        look = {name: combo for name, _, combo in vs}
        want = stem.startswith("pos_")            # pos_* 才该命中，neg_* 命中反倒是坏事
        print("\n  %s %-24s %.2fs  %d 帧 %.0f ms"
              % ("✅" if bool(hits) == want else "❌", stem,
                 len(x) / SR, len(x) / CHUNK + 1, ms))
        if not hits:
            print("      " + ("该命中却一条假设都没中 —— 拼法全试过了，那就是真没听出来"
                              if want else "反样本，一条都没中 = 正常"))
        for name, at in hits:
            print("      %s %-33s @%.0f ms   听成了：%s"
                  % ("✅" if want else "⚠️ 误唤醒", name, at, look.get(name, "?")))

    print("\n" + "=" * 78)
    print("怎么读这张表")
    print("=" * 78)
    print("  · **V01 是唯一命中的一种，且三个正样本全中** → 拼法是对的，")
    print("    不用加近似词（这也是实测结果，不是推断）")
    print("  · 某条别的变体也全中 → 把它一起写回 ui/voice/keywords.txt（多写不亏，")
    print("    只是每条都会略微抬高误唤醒——所以要有反样本看着）")
    print("  · 正样本命中的变体各不相同 → 声学模型在连读/不同语调下吐的 token 不稳定，")
    print("    那就把命中的几条都写进词表，并接受「说得含糊时叫不醒、重说一遍即可」")
    return 0


if __name__ == "__main__":
    sys.exit(main())
