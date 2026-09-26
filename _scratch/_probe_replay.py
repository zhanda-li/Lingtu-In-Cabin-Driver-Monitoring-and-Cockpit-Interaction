"""实测：同一个动作**连着播两次**，动画到底有没有从头再来。

    python _scratch/_probe_replay.py 8790

为什么单独探这一下：`live.js` 的 `playOne()` 里有一句
    `void slot.el.offsetWidth;  // 强制回流，让同名动画重新开始`
和它上面那段"不加这句点第二次没反应"的注释 —— 那是**我写的推断，没在浏览器里量过**。
而这条很容易推错：`data-act` 和 `src` 都只是被赋成**同样的值**，样式树上
"动画名"前后都是 `xqHappy`，按 CSS Animations 的规则，**同名动画是"更新"不是"重建"**，
已经播完的（iteration-count:1、fill 默认 none）会停在终态不动 —— 也就是说
**光靠 `void offsetWidth` 很可能不重启**。

这里用 `animationstart` 事件数当判据（不重启就不会有新事件），并且
**先用一个换名的动作做对照**，证明这个计数器确实数得到事件（不然"没重启"和
"计数器没接上"长得一模一样）。

判据：
  · 「换个动作」那一步必须 +1（否则是这个探测器本身坏了，结论全部作废）
  · 「同名重播」那一步 +1 = 真的重启了；不动 = 需要改实现
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _check_pages import Session, ck          # noqa: E402

COUNT = """(function(){
  window.__xq = {};
  const el = document.querySelector('#tipImg');
  el.addEventListener('animationstart', (e) => {
    window.__xq[e.animationName] = (window.__xq[e.animationName] || 0) + 1;
  });
  return 'hooked';
})()"""

N = "JSON.stringify(window.__xq||{})"


async def main():
    worst = 0
    async with Session(9424) as S:
        await S.goto("/chat.html", 2.6)
        print("\n=== 装探测器 ===")
        print(" ", await S.js(COUNT))
        print("  当前:", await S.js(N), "（xqIdle 应当已经数到 1）")

        print("\n=== 对照：换一个动作（moved）必须 +1 ===")
        before = await S.js(N)
        await S.js("XQ.mascot.play('moved', {hold: 4000})")
        await asyncio.sleep(0.3)
        after = await S.js(N)
        worst |= ck("换名播放 -> 新动画被创建",
                    after.get("xqMoved", 0) == before.get("xqMoved", 0) + 1,
                    f"xqMoved {before.get('xqMoved', 0)} -> {after.get('xqMoved', 0)}")

        print("\n=== 等 1.2s 让它播完（xqMoved 是 1.3s，多等一点）===")
        await asyncio.sleep(1.6)
        mid = await S.js(N)
        print("  ", mid)

        print("\n=== ★ 同名重播：再播一次 moved ===")
        await S.js("XQ.mascot.play('moved', {hold: 4000})")
        await asyncio.sleep(0.35)
        end = await S.js(N)
        restarted = end.get("xqMoved", 0) == mid.get("xqMoved", 0) + 1
        worst |= ck("★ 同名重播 -> 动画真的从头开始", restarted,
                    f"xqMoved {mid.get('xqMoved', 0)} -> {end.get('xqMoved', 0)}"
                    + ("" if restarted else "   << 没重启：`void offsetWidth` 那句不够"))
        if not restarted:
            print("\n  再验一种改法：先摘掉 data-act、强制重算、再挂回去")
            await S.js("document.querySelector('#tipImg').removeAttribute('data-act')")
            await S.js("void document.querySelector('#tipImg').offsetWidth")
            await S.js("document.querySelector('#tipImg').dataset.act='moved'")
            await asyncio.sleep(0.35)
            end2 = await S.js(N)
            worst |= ck("★ 摘属性/重算/挂回 -> 真的重启",
                        end2.get("xqMoved", 0) == end.get("xqMoved", 0) + 1,
                        f"xqMoved {end.get('xqMoved', 0)} -> {end2.get('xqMoved', 0)}")
    print()
    return worst


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
