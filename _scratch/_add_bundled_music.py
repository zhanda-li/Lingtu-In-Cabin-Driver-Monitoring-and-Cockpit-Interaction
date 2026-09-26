# -*- coding: utf-8 -*-
"""一次性：从用户的曲库里挑 30 首拷进项目，当**内置曲库**。

为什么是「最小的 30 首」：内置的那批是**演示机不依赖用户目录**时唯一能放的东西
（答辩机器上多半没有 D:\\CloudMusic），所以要挑**加载快**的 —— 按体积从小到大选，
30 首 91 MB、单首最大 5.3 MB。顺便验过歌手是散的（27 个歌手 / 30 首），
不是同一张专辑扎堆。

⚠️ 挑出来的里面确实有几首是「片段」「0.8x 变速」这种，**照原样拷，不筛**：
   那是用户曲库里真实存在的东西，替用户"觉得这些不够正式"才是越界。

⚠️ 服务端**只认文件名**：内置那份和用户目录里的同名文件是**同一首**（就是同一首，
   这里是拷贝），`music_list` 按文件名去重、内置优先，所以 155 首还是 155 首，
   不会变成 185。改文件名会让去重失效 —— 别改。

    PYTHONIOENCODING=utf-8 python _scratch/_add_bundled_music.py [--dry]
"""

import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = r"D:\CloudMusic"
DST = os.path.join(ROOT, "ui", "media")
EXTS = {".mp3", ".m4a", ".wav", ".ogg", ".opus", ".flac"}
WANT = 30


def main():
    dry = "--dry" in sys.argv
    files = [p for p in os.listdir(SRC)
             if os.path.splitext(p)[1].lower() in EXTS
             and os.path.isfile(os.path.join(SRC, p))]
    files.sort(key=lambda n: (os.path.getsize(os.path.join(SRC, n)), n.lower()))
    pick = files[:WANT]

    if not dry:
        os.makedirs(DST, exist_ok=True)
    total = 0
    for n in pick:
        s = os.path.join(SRC, n)
        d = os.path.join(DST, n)
        total += os.path.getsize(s)
        if dry:
            continue
        if os.path.exists(d) and os.path.getsize(d) == os.path.getsize(s):
            continue                      # 已经拷过了（脚本可以反复跑）
        shutil.copy2(s, d)
    print("%s %d 首 -> %s（%.1f MB）" % ("会拷" if dry else "已拷", len(pick), DST,
                                        total / 1048576))
    if not dry:
        got = [p for p in os.listdir(DST) if os.path.splitext(p)[1].lower() in EXTS]
        print("目录里现在 %d 个音频文件" % len(got))
        assert len(got) == WANT, "拷出来 %d 个，不是 %d 个 —— 先看一眼再说" % (len(got), WANT)


if __name__ == "__main__":
    main()
