"""界面环境快照 —— 装语音输入**之前/之后**各打一次，用来证明那四个包还在、没被动过。

只有 `ui/install_asr.bat` 用它，别的地方不用。

**为什么为了这件事单开一个文件**（而不是写在 bat 里）：
  · bat 必须保持纯 ASCII，而这里最要紧的那句话（"numpy 被换了，摄像头那条要先验
    一遍"）得是中文 —— 只有 python 侧能用 utf-8 打出来。
  · `)` 不能出现在 bat 的 `( )` 块里的 echo 文本中（cmd 的块解析器会把 echo 里的
    `)` 当成块结束，见 `ui/run_ui.bat` 里那段注释）。
  · 这件事本身要**比较两次结果**，bat 里存/读临时文件又要绕一圈。

**为什么是这四个**：`ui/run_ui.bat` 那条路活命全靠它们 —— `cam` 模式要
cv2 + mediapipe + torch，模型和音频处理要 numpy。而 `install_asr.bat` 要装的
`numba`（whisper 的依赖）**有能力把 numpy 挪走**：numba → llvmlite 对 numpy 有上界
约束，而本机的 mediapipe 对 numpy 版本很挑。真被挪走的后果不是"语音输入不能用"，
是"**cam 模式直接打不开**"——一个可选功能装出一个致命故障。所以两头各打一次，
一旦对不上就当场说出来，别等到答辩现场才发现摄像头黑屏。

用法：
    python ui/env_snapshot.py --save _before.json      # 记下现在这四个的版本
    python ui/env_snapshot.py --compare _before.json   # 再打一次，并和它比
    python ui/env_snapshot.py                          # 只打一次，当状态查询
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

# 顺序就是重要性：numpy 排第一，因为它是最可能被挪动的那个。
MODULES = ("numpy", "torch", "cv2", "mediapipe")


def snapshot() -> dict[str, str]:
    """逐个 import 并取版本。**import 失败不抛异常**，把原因记成字符串。

    ⚠️ 失败时记的是 `!! ImportError: ...` 而不是一个 `MISSING` 记号：装完东西之后
    看到"MISSING"的人需要知道它是**本来就没装**还是**刚被弄坏的**，这两种情况
    要采取的行动完全相反。
    """
    out: dict[str, str] = {}
    for m in MODULES:
        try:
            mod = importlib.import_module(m)
            out[m] = str(getattr(mod, "__version__", "（这个包没有 __version__）"))
        except Exception as e:
            out[m] = f"!! {type(e).__name__}: {e}"
    return out


def show(snap: dict[str, str]) -> None:
    for m in MODULES:
        print(f"  {m:<10} {snap[m]}")


def _dump(path: str) -> int:
    snap = snapshot()
    Path(path).write_text(json.dumps(snap, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    print("装之前这四个包的版本（已记到下面这个文件，装完用它对比）：")
    print(f"  {path}")
    show(snap)
    return 0


def _compare(path: str) -> int:
    try:
        before = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as e:
        # 不硬失败：比不了就退化成"只打一次"，安装流程不该因为记账文件丢了就停。
        print(f"读不到装之前的记录（{type(e).__name__}: {e}），只打一遍现在的：")
        show(snapshot())
        return 0

    after = snapshot()
    print("装完之后的版本：")
    show(after)

    bad = [m for m in MODULES if before.get(m) != after[m]]
    if not bad:
        print()
        print("四个包一个都没动，和装之前逐字一样 —— 摄像头那条路没被这件事碰到。")
        return 0

    print()
    print("有包被改动了：")
    for m in bad:
        print(f"  {m:<10} {before.get(m)}  →  {after[m]}")
    if "numpy" in bad:
        print()
        print("⚠️ numpy 变了。这不是语音输入的事，是 **cam 模式可能打不开** 的事 ——")
        print("   本机的 mediapipe 对 numpy 版本很挑。装完语音输入之后，别直接去")
        print("   走答辩流程，先双击 ui\\run_ui_cam.bat 把摄像头验一遍。")
        print()
        print("想退回装之前：把上面那个旧版本号填进下面这行再跑一遍 ——")
        print(f"   \"%PY%\" -m pip install numpy=={before.get('numpy')}")
    print()
    print("⚠️ 不管是哪个包变了，这里都算**没通过**（退出码 1）：安装脚本会停下来，")
    print("   不会装作一切正常接着往下走。")
    return 1


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--save":
        if len(argv) < 2:
            print("用法：python ui/env_snapshot.py --save <文件>")
            return 2
        return _dump(argv[1])
    if argv and argv[0] == "--compare":
        if len(argv) < 2:
            print("用法：python ui/env_snapshot.py --compare <文件>")
            return 2
        return _compare(argv[1])
    show(snapshot())
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main(sys.argv[1:]))
