# -*- coding: utf-8 -*-
"""一次性探针：小瑞为什么会出现「回复是空的」。

    python _scratch/_probe_empty.py

`_probe_chat.py` 跑出来的现场：三轮里第三轮「那放首歌听听」，
`backend` 掉回固定话术，`last_error = '回复是空的'`。
`deepseek.py:121` 只读 `choices[0].message.content`，空了就 raise，
**`finish_reason` 和 `usage` 直接被丢掉** —— 于是"为什么空"完全没留下证据。

这个脚本把 `httpx.post` 换成一个记录器，把**原始返回体的元信息**打出来：
status / finish_reason / usage / 有没有 reasoning_content / content 长度。

有了 finish_reason 就能分清两种完全不同的情况：
  · `length` —— 是被 max_tokens 截断的（那就得加预算，或让它少想点）
  · `stop`   —— 是模型自己就吐了个空（那得改提示词，加预算没用）

⚠️ 会真的调 API（几毛钱以内）。只打元信息，不打 key。
"""
import sys, time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ui"))

import deepseek as ds                     # noqa: E402
from deepseek import load_config          # noqa: E402
from state import State                   # noqa: E402
from xiaorui import Agent                 # noqa: E402

TURNS = ["我有点困", "还行吧，再撑一会儿", "那放首歌听听"]


def main():
    cfg = load_config()
    agent = Agent(cfg)
    if not agent.client.ready:
        print("没配 key，跑不了。")
        return
    print("model = %s   max_tokens = %s\n" % (agent.client.model,
                                              agent.client.max_tokens))

    real_post = ds.httpx.post
    rec = []

    def spy_post(url, **kw):
        r = real_post(url, **kw)
        try:
            js = r.json()
        except Exception:
            js = None
        rec.append((r.status_code, js))
        return r

    ds.httpx.post = spy_post

    st = State()
    history = []
    try:
        for t in TURNS:
            t0 = time.time()
            r = agent.respond(st, t, history)
            el = time.time() - t0
            history.append({"role": "user", "content": t})
            history.append({"role": "assistant", "content": r.text})
            print("\n我：%s" % t)
            print("  → backend=%-11s %d 字  %.1f 秒：%s"
                  % (r.backend, len(r.text), el, r.text))
            code, js = rec[-1]
            note = ""
            if js:
                ch = (js.get("choices") or [{}])[0]
                msg = ch.get("message") or {}
                u = js.get("usage") or {}
                note = ("  └ HTTP %s  finish_reason=%r  completion_tokens=%s "
                        "reasoning_tokens=%s  content=%d 字  "
                        "有 reasoning_content=%s"
                        % (code, ch.get("finish_reason"),
                           u.get("completion_tokens"),
                           (u.get("completion_tokens_details") or {})
                           .get("reasoning_tokens"),
                           len(msg.get("content") or ""),
                           bool(msg.get("reasoning_content"))))
                if len(js.get("choices") or []) == 0:
                    note += "\n     ⚠️ choices 是空的，整条返回体的键：%s" % list(js)
            else:
                note = "  └ HTTP %s（返回体不是 JSON）" % code
            print(note)
    finally:
        ds.httpx.post = real_post

    print("\n" + "=" * 68)
    print("last_error = %r" % agent.last_error)
    bad = [i for i, (c, j) in enumerate(rec)
           if not j or not (j.get("choices") or [])
           or not (((j["choices"][0].get("message") or {}).get("content") or "")
                   .strip())]
    print("空回复出现在第 %s 次调用" % ([i + 1 for i in bad] or "无"))
    print("\n判读：那边 `finish_reason=length` ⇒ 撞 max_tokens 了（加预算 / 让它少想）；\n"
          "      `stop` 却是空 ⇒ 模型自己吐的空（加预算没用，得改提示词）；\n"
          "      `choices` 空或有 reasoning_content ⇒ 这是个**推理模型**，\n"
          "      思考过程吃掉了 token 预算，而 `deepseek.py:121` 只读 content。\n"
          "      这一支要在 `deepseek.py` 里**显式处理**，不能只回一句「回复是空的」。")


if __name__ == "__main__":
    main()
