# -*- coding: utf-8 -*-
"""常听唤醒 · **端到端延迟拆解**（真 WebSocket + 真音频，按真实时间喂）。

    python _scratch/_measure_latency.py 8790
    python _scratch/_measure_latency.py 8790 --rounds 5

量的是"说完之后要等多久"，拆成四段，每一段都标清楚**是谁花的时间**：

  ① 收口等待   说完 → 状态机判定"这句说完了"   = 断句静音（就是 10 s，见下）+ 一片
  ② 转文字     收口 → heard                    = whisper，本地 CPU，整段式
  ③ 问模型     heard → reply                   = 一次 DeepSeek 往返，**联网**，
                                                 这一段抖动最大，也是唯一
                                                 不在这台机器上的
  ④ 出声       reply → 喇叭响                  = **这里量不到**，那是页面 TTS 的事
                                                 （页面 `XQ.speak` 的回调）。
                                                 要真数得在页面上量，且浏览器
                                                 那条链路的时序和真机不是一回事。

⚠️ 音频**按真实时间**喂（100 ms 一片、睡 0.1 s）。把时间轴压扁的话，① 和
   ④ 这些按挂钟算的东西全是假的 —— 见 `ui/voice/kws.py` 第 2 条纪律：
   凡是按挂钟计时的机制，压缩时间的回放里都不成立。

🔴 2026-09-26 用户拍板：**「语音结束的标志是我中途 10s 没有发出声音」**。
   于是 ① 从 0.84 s 变成 **10 s** —— 「说完到答复」这个总数也就从 3.85 s 涨到
   ≈13 s。这是**用户自己选的**（宁可等 10 s，也不许切主人的话），不是回归。
   这段静音是**真等**的（`SILENCE_S`），量出来的 ① 自然就是那个数 —— 所以这个
   脚本现在主要是量 ② 和 ③（whisper 和 DeepSeek 各花多久），① 只作对表用。

⚠️ 这几个数**只代表这台机器 + 这个网**：whisper 在 CPU 上跑、DeepSeek 在云上。
   换机器/换网络/换模型（`base`→`small`）都得重新量 —— 脚本在这儿，重跑就有。

⚠️ 它对"识别得准不准"一个字都没说（样本是合成的）。准不准只有真人对着麦克风
   说才算数。
"""

import argparse
import asyncio
import base64
import json
import sys
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).parent.parent / "ui"))
sys.path.insert(0, str(Path(__file__).parent.parent / "ui" / "voice"))

import asr                                              # noqa: E402
from kws import SR                                      # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ONE_SHOT = ROOT / "runs" / "wake_samples" / "pos_hello_xiaorui_slow.wav"
CHUNK = 1600                                            # 100 ms
SILENCE_S = 10.5                                        # 判据 10 s + 一片（见文件头 🔴）


def pcm(path) -> np.ndarray:
    return asr.wav_bytes_to_float32(path.read_bytes(), want_sr=SR)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port", nargs="?", default="8790")
    ap.add_argument("--rounds", type=int, default=3)
    a = ap.parse_args()
    import aiohttp

    # ⚠️ 静音要**真的拼进数组**再切片。第一版是"按 `len(x) + 1.6 s` 数帧"，
    #    结果越界的那几十片全是**空数组** —— 于是那 1.6 s 静音一个字都没发出去，
    #    而样本自带的尾巴只有 0.8 s（< 断句线），"说完了"永远判不出来，
    #    表现是"叫醒了、然后一直没下文"（而且连超时兜底都不动，因为状态机只在
    #    有音频进来的时候才推进）。**别用下标算补零，拼出来。**
    # 🔴 10.5 s = 生产值（判据 10 s + 一片），**不许为了少等而改小** ——
    #    改小了量的就不是线上那件事。这段是按真实时间喂的，所以脚本会真的多等 10 s。
    x = np.concatenate([pcm(ONE_SHOT), np.zeros(int(SILENCE_S * SR), dtype=np.float32)])
    # "说完"是哪一片：按峰值找最后一片有声的（阈值取得很低，盖过底噪就行）
    peak = float(np.abs(x).max())
    loud = [i for i in range(0, len(x), CHUNK)
            if float(np.abs(x[i:i + CHUNK]).max()) >= peak * 0.05]
    last_loud = loud[-1] + CHUNK if loud else len(x)
    print("样本 %s：%.2f s，其中「说完」在第 %.2f s"
          % (ONE_SHOT.name, len(x) / SR, last_loud / SR))

    evs, t_ev = [], {}
    async with aiohttp.ClientSession() as sess:
        async with sess.ws_connect("ws://127.0.0.1:%s/ws" % a.port,
                                   max_msg_size=0) as ws:
            async def pump():
                try:
                    async for m in ws:
                        if m.type != aiohttp.WSMsgType.TEXT:
                            continue
                        d = json.loads(m.data)
                        if d.get("type") == "voice":
                            e = d["data"].get("ev")
                            evs.append(d["data"])
                            t_ev.setdefault(e, []).append(
                                asyncio.get_event_loop().time())
                except Exception as e:
                    print("  !! 收消息的任务挂了：%s: %s" % (type(e).__name__, e))

            async def status(timeout=5.0):
                n = len(evs)
                await ws.send_json({"type": "voice_status"})
                t0 = asyncio.get_event_loop().time()
                while asyncio.get_event_loop().time() - t0 < timeout:
                    hit = next((e for e in reversed(evs[n:])
                                if e.get("ev") == "status"), None)
                    if hit is not None:
                        return hit
                    await asyncio.sleep(0.05)
                return None

            t = asyncio.create_task(pump())
            await asyncio.sleep(0.5)

            # 建耳朵（第一次要加载 KWS + 复用服务端那份 whisper）
            await ws.send_json({"type": "voice_start"})
            for _ in range(120):                        # 最多 60 s
                await asyncio.sleep(0.5)
                st = await status()
                if st and (st.get("voice") or {}).get("asr_ok"):
                    break
            st = await status() or {}
            ear = st.get("ear") or {}
            print("耳朵：%s" % (st.get("voice") or {}).get("kws", "?"))
            print("识别：%s（%s）" % ((st.get("voice") or {}).get("asr", "?"),
                                     "已就绪" if (st.get("voice") or {}).get("asr_ok")
                                     else "**还没就绪**"))

            rows = []
            for r in range(1, a.rounds + 1):
                evs.clear()
                t_ev.clear()
                t_loud = None
                for i in range(0, len(x), CHUNK):
                    ch = x[i:i + CHUNK]
                    blob = (np.clip(ch, -1, 1) * 32767).astype("<i2").tobytes()
                    await ws.send_json({"type": "pcm", "seq": r,
                                        "b64": base64.b64encode(blob).decode()})
                    await asyncio.sleep(0.1)
                    if i >= last_loud and t_loud is None:
                        t_loud = asyncio.get_event_loop().time()
                # 等这一轮走完：heard → reply（都是秒级，等事件，别定时长）
                for _ in range(900):                    # 最多 90 s
                    await asyncio.sleep(0.1)
                    if t_ev.get("reply"):
                        break
                if not (t_ev.get("reply") and t_ev.get("heard") and t_ev.get("thinking")):
                    print("  第 %d 轮没收全：%s（跳过）"
                          % (r, " | ".join(e.get("ev", "") for e in evs)))
                    break
                t1 = t_ev["thinking"][0] - t_loud            # ① 收口等待
                t2 = t_ev["heard"][0] - t_ev["thinking"][0]  # ② 转文字
                t3 = t_ev["reply"][0] - t_ev["heard"][0]     # ③ 问模型
                tot = t_ev["reply"][0] - t_loud
                rep = next(e for e in reversed(evs) if e.get("ev") == "reply")
                st = await status() or {}
                asr_ms = ((st.get("ear") or {}).get("asr") or {}).get("last_ms")
                rows.append((t1, t2, t3, tot))
                print("  第 %d 轮  ①收口 %.2f s  ②转文字 %.2f s（whisper 自报 %s ms）"
                      "  ③问模型 %.2f s  →  **说完到答复 %.2f s**"
                      % (r, t1, t2, asr_ms, t3, tot))
                print("            答复：%s" % (rep.get("text") or "")[:38])
                # 收尾：这一轮结束，等它**收干净**（+ 余音保护）再进下一轮。
                # ⚠️ 2026-09-26：念完之后进的是**追问窗口**（状态 `follow`，见
                #    `ui/voice/loop.py` 的 FOLLOW），不再是 `idle` —— 只认 `idle`
                #    的话这里会每一轮都白等 8 秒（等窗口超时），量出来的还是对的，
                #    但量一轮要 3 倍时间。两档都算"收干净了"。
                await ws.send_json({"type": "voice_spoken"})
                for _ in range(60):
                    await asyncio.sleep(0.1)
                    if (((await status() or {}).get("ear") or {}).get("state")
                            in ("idle", "follow")):
                        break
                await asyncio.sleep(0.6)                    # GUARD_S 的余音保护
            await ws.send_json({"type": "voice_stop"})
            t.cancel()

    print("\n" + "=" * 74)
    if not rows:
        print("❌ 一轮都没量到")
        return 1
    n = len(rows)
    avg = [sum(r[i] for r in rows) / n for i in range(4)]
    print("平均（%d 轮）：①收口 %.2f s + ②转文字 %.2f s + ③问模型 %.2f s"
          "  =  说完到答复 %.2f s" % (n, avg[0], avg[1], avg[2], avg[3]))
    print("  ① 那 10 s 是**用户定的规矩**（10 s 不说话才算说完），不是谁的开销；")
    print("    真在花时间的是 ②（whisper，本地 CPU）和 ③（DeepSeek，联网）。")
    print("  最慢一轮 %.2f s，最快一轮 %.2f s —— **抖动几乎全在 ③**"
          % (max(r[3] for r in rows), min(r[3] for r in rows)))
    print("  ④出声这一段不在这里：那是页面 TTS（见文件头）。")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
