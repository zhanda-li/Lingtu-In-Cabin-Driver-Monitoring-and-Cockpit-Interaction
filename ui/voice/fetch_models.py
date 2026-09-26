# -*- coding: utf-8 -*-
"""把小瑞要用的 sherpa-onnx 模型下到**仓库里**（不落 C: —— 这台机器 C: 是满的）。

    python ui/voice/fetch_models.py --list
    python ui/voice/fetch_models.py kws            # 唤醒词模型，32 MB，先下这个
    python ui/voice/fetch_models.py asr            # 流式语音识别
    python ui/voice/fetch_models.py all

为什么不用 `huggingface` 命令行：这台机器上 huggingface.co **连不上**（实测超时），
而 GitHub 的 release 是通的（实测 KWS 包 HTTP 200）。所以默认走 GitHub。
网不行的时候再回头找镜像，别把默认值改成某个镜像站。

⚠️ 下完**要解包**才算好：`models/sherpa/<名字>/` 里得看得见 `tokens.txt`。
   校验方式就是这个 —— 判据是"文件在不在"，不是"下载那一行打印成功没有"。

⚠️ 全程走 `.part` 再改名：中途断了不会留下一个看起来像好文件的半截包。
   重跑这个脚本会跳过已经解好的，所以断了直接再跑一遍。
"""
import argparse
import shutil
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]          # dms_project
DEST = ROOT / "models" / "sherpa"
GH = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
# ⚠️ 必须给超时。这台机器上到 GitHub 的连接**会卡在"连上了但对方不答"**（实测
#   WinError 10060），不给超时的话 urlopen 会一直挂着 —— 后台跑就是永远不结束、
#   前台跑就是看着像死机，而且**连一句失败都打不出来**。超时 + 重试才是对的。
TIMEOUT = 30
RETRY = 3

# 名字 -> (release 标签, 包名, 大约多少 MB, 一句话说明)
MODELS = {
    "kws": ("kws-models", "sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01",
            32, "中文唤醒词（关键词）检测。自定义唤醒词写在 keywords.txt 里，"
                "token 是带声调的拼音 —— 「你好小瑞」= n ǐ h ǎo x iǎo r uì"),
    "asr": ("asr-models", "sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30",
            133, "流式中文识别（int8，CPU 实时）。默认选它不选 paraformer："
                 "paraformer 那个包 1047 MB，是它的 8 倍，而我们是纯中文场景"),
    # 备选，留着换：更小更快、精度低一点
    "asr_small": ("asr-models", "sherpa-onnx-streaming-zipformer-small-ctc-zh-int8-2025-04-01",
                  21, "极小的流式中文 CTC（21 MB，最快，精度最低）"),
    "asr_paraformer": ("asr-models", "sherpa-onnx-streaming-paraformer-bilingual-zh-en",
                       1047, "流式 Paraformer（中英混说最强，但 1 GB）"),
}
# ⚠️ VAD（断句用）不在这个表里：`silero_vad.onnx` 在 release 里是**单文件**不是
#    tar.bz2，塞进来会拼出一个 404 的 URL。要它的话单独下：
#      https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx
#    第一期先按"静音超过 X 毫秒就算说完"来断句，够用；不够再上 VAD。


def url_of(key: str) -> str:
    tag, name, _, _ = MODELS[key]
    return f"{GH}/{tag}/{name}.tar.bz2"


def dir_of(key: str) -> Path:
    return DEST / MODELS[key][1]


def ready(key: str) -> bool:
    """解好了没。判据是**看得见 tokens.txt**（有的包还带别的目录，不管它）。"""
    d = dir_of(key)
    return d.is_dir() and any(d.rglob("tokens.txt"))


def human(n: float) -> str:
    return "%.1f MB" % (n / 1e6) if n < 1e9 else "%.2f GB" % (n / 1e9)


def fetch(key: str, force: bool = False) -> bool:
    tag, name, mb, _ = MODELS[key]
    d = dir_of(key)
    if ready(key) and not force:
        print("  ✓ %-14s 已经在了：%s" % (key, d.relative_to(ROOT)))
        return True
    DEST.mkdir(parents=True, exist_ok=True)
    url = url_of(key)
    part = DEST / (name + ".tar.bz2.part")
    final = DEST / (name + ".tar.bz2")
    print("  ↓ %-14s %s" % (key, url))
    got = 0
    for attempt in range(1, RETRY + 1):
        t0, last, got = time.time(), 0.0, 0
        try:
            with urllib.request.urlopen(
                    urllib.request.Request(url, headers={"User-Agent": "xiaoqi-fetch"}),
                    timeout=TIMEOUT) as r, open(part, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                while True:
                    buf = r.read(1 << 18)
                    if not buf:
                        break
                    f.write(buf)
                    got += len(buf)
                    now = time.time()
                    if now - last > 2.0:
                        last = now
                        sp = got / max(now - t0, 1e-6)
                        left = (total - got) / sp if (total and sp > 0) else 0
                        print("      %s / %s  (%s/s，还剩约 %.0f 秒)"
                              % (human(got), human(total) if total else "?",
                                 human(sp), left), flush=True)
            break                                  # 这一趟跑完了
        except Exception as e:
            print("  ✗ 第 %d/%d 次失败：%s %s"
                  % (attempt, RETRY, type(e).__name__, e), flush=True)
            if attempt < RETRY:
                print("      %.0f 秒后重试（GitHub 在这台机器上时通时不通，"
                      "重试往往就好）…" % 5.0, flush=True)
                time.sleep(5.0)
            else:
                print("    放弃。已经下到的 %s 留在 %s，重跑本脚本会**从头发起**"
                      "（不续传，省得半个包被当成好包）。" % (human(got), part.name))
                return False
    part.replace(final)
    print("  ✓ 下完 %s，解包…" % human(got))
    try:
        with tarfile.open(final, "r:bz2") as tf:
            tf.extractall(DEST)
    except Exception as e:
        print("  ✗ 解包失败：%s %s" % (type(e).__name__, e))
        return False
    final.unlink(missing_ok=True)
    if not ready(key):
        print("  ✗ 解出来了，但找不到 tokens.txt —— 包里结构变了？看一眼 %s" % d)
        return False
    print("  ✓ %s 就绪：%s" % (key, d.relative_to(ROOT)))
    return True


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="下 sherpa-onnx 模型到 models/sherpa/")
    p.add_argument("what", nargs="?", default="kws",
                   choices=list(MODELS) + ["all"])
    p.add_argument("--force", action="store_true", help="已经有的也重下")
    p.add_argument("--list", action="store_true", help="只列清单，不下东西")
    a = p.parse_args(argv)

    if a.list or a.what == "all":
        print("模型清单（默认目录 %s）：" % DEST.relative_to(ROOT))
        for k, (tag, name, mb, why) in MODELS.items():
            print("  %-15s %5d MB  %s  %s"
                  % (k, mb, "✓" if ready(k) else " ", why))
        if a.list:
            return 0

    keys = list(MODELS) if a.what == "all" else [a.what]
    ok = True
    for k in keys:
        ok = fetch(k, force=a.force) and ok
    if not ok:
        print("\n有没下成的，重跑一遍这个脚本即可（已就绪的会跳过）。")
        return 1
    print("\n全部就绪。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
