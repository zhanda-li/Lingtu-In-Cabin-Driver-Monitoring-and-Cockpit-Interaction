# -*- coding: utf-8 -*-
"""量 `initial_prompt` 那几版候选：**繁简、认不认得准、有没有"多出来的词"**。

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch\\_probe_asr_zh.py

为什么要量而不是挑一版看着顺眼的：2026-09-26 用户报「我的话翻译出来为啥繁体字」
+「为啥它还听不清我说话」。给 whisper 传一段**简体提示**（`initial_prompt`）是
"别吐繁体"的主路（见 `ui/asr.py` 的 `SIMPLIFIED_PROMPT`），可提示词**会被模型
顺着往下写** —— 第一版提示里带「导航到最近的服务区」，于是「给我放个音乐」这句
的识别结果尾巴上**多出来一个「导航」**。那不是识别变好，那是**提示泄漏**，
而且泄漏出来的正好是**动作词**：一句"放音乐"会变成"跳导航页"。

所以这个脚本量三件事，一版一版比：
  1. **繁体**：识别结果里还有没有繁体字形（`ui/zh.py` 的表能看出来的那些）。
  2. **该认的认出来没有**：每个样本按文件名有一个"必须出现的词"（见 `EXPECT`）。
  3. **不该有的有没有**：名字里没有动作的样本，识别结果里**不许出现动作词**
     —— 多一个就是泄漏（见 `LEAK`）。

样本是 `runs/wake_samples/` 那 13 个（本来就是给唤醒率实测用的，见
`_scratch/_check_wake.py`），**真音频、真跑 whisper**。挂钟机制在这儿不成立，
所以只用来看字。
"""
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
sys.path.insert(0, str(ROOT / "ui"))

import asr as A                                                    # noqa: E402
import zh                                                          # noqa: E402

# 样本名 → (必须出现的词, 判断用的额外说明)。**故意宽松**：量的是"这句话认出来了
# 没有"，不是逐字对拍 —— 逐字对拍要求一份标准答案，而标准答案是**当时那个人
# 的发音**，没有第二份能对照的东西（见 `_scratch/_check_wake.py` 里同一段道理）。
EXPECT = {
    "pos_affirm.wav":               ("要", "同意"),
    "pos_goto_media.wav":           ("多媒体", "打开多媒体"),
    "pos_goto_nav.wav":             ("导航", "导航"),
    "pos_hello_xiaorui.wav":        ("小瑞", "叫名字"),
    "pos_hello_xiaorui2.wav":       ("小瑞", "叫名字"),
    "pos_hello_xiaorui_slow.wav":   ("小瑞", "叫名字（慢）"),
    "pos_music.wav":                ("音乐", "放音乐"),
    "pos_other_topic.wav":          (None, "闲聊（没有动作）"),
    "pos_rest_stop.wav":            ("服务区", "去服务区"),
}
# 只有**这几句**不许出现的动作词：它们的外号是"放音乐/闲聊"，识别结果里冒出
# 导航/服务区/多媒体就是提示泄漏。**不是**给所有样本都用 —— `pos_goto_nav` 的
# 正主就是"导航"，拿它当泄漏词会把对的判成错的。
LEAK = {"pos_music.wav": ("导航", "服务区", "多媒体"),
        "pos_other_topic.wav": ("导航", "服务区", "多媒体", "音乐")}

PROMPTS = [
    ("P0 不发提示", None),
    ("P1 车机例句", "请用简体中文转写。你好小瑞，给我放个音乐，导航到最近的服务区，我有点困了。"),
    ("P2 单句 meta", "以下是普通话的简体中文转写。"),
    ("P3 极短", "请用简体中文。"),
    ("P4 主人对我说", "主人对我说的话，用简体中文记下来。"),
]


def say(s: str) -> None:
    print(s)


def main() -> int:
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    m = A.LocalAsr({"preload": True})
    t0 = time.time()
    while not m.ok() and time.time() - t0 < 180:
        time.sleep(1)
    say("识别器: %s" % m.engine())
    files = [f for f in sorted((ROOT / "runs" / "wake_samples").glob("pos_*.wav"))
             if not only or f.name in only]
    if not files:
        say("!! 没有样本（runs/wake_samples/pos_*.wav）")
        return 1

    for tag, prompt in PROMPTS:
        kw = {} if prompt is None else {"initial_prompt": prompt}
        n_trad = n_hit = n_miss = n_leak = 0
        rows = []
        for f in files:
            want, why = EXPECT.get(f.name, (None, "?"))
            x = A.trim_silence(A.wav_bytes_to_float32(f.read_bytes()))
            r = m.model.transcribe(x, language="zh", fp16=False, verbose=None,
                                   condition_on_previous_text=False, **kw)
            t = A._tidy(" ".join(str(r.get("text") or "").split()), "zh")
            trad = zh.zh_t2s(t) != t
            out = zh.zh_t2s(t)
            n_trad += 1 if trad else 0
            hit = (want in out) if want else True
            n_hit += 1 if hit else 0
            n_miss += 0 if hit else 1
            leak = [w for w in LEAK.get(f.name, ()) if w in out]
            n_leak += 1 if leak else 0
            rows.append("      %-26s %-30r%s%s%s"
                        % (f.name, out,
                           "  ←繁体" if trad else "",
                           "" if hit else "  ←漏了「%s」" % want,
                           "  ←多了%s" % leak if leak else ""))
        say("\n%s  （%s）  繁体 %d/%d  认对 %d/%d  泄漏 %d"
            % (tag, prompt or "无", n_trad, len(files), n_hit, len(files), n_leak))
        for r in rows:
            say(r)
    say("\n★ 挑法：泄漏必须是 0（泄漏出来的都是动作词，会让「放音乐」变成「跳导航页」），"
        "在这个前提下要繁体最少、认对最多。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
