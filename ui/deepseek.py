"""DeepSeek 客户端（OpenAI 兼容），只做一件事：把 messages 发出去、把回复拿回来。

**为什么自己写而不是装 openai 包**：这是 OpenAI 兼容接口，用 httpx 二三十行就够了，
而 `openai` 包要装一个新依赖。本项目对"现场能不能跑起来"很敏感，少一个依赖少一个坑。

**模型名要小心**：`deepseek-chat` / `deepseek-reasoner` 这两个老名字在
2026-07-24 已经停用，现在会直接报错。官方现在列的是 `deepseek-flash` 与
`deepseek-v4-pro`。所以模型名做成配置项，并且提供：

    python ui/deepseek.py --models      # 用你的 key 问一次，看真实可用的模型名单

不要靠猜，也不要靠文档——名单是会变的，这个命令 10 秒就能问出来。

命令行自测（不用开界面）：

    python ui/deepseek.py --models
    python ui/deepseek.py --say "我有点困"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import httpx
except ImportError:            # pragma: no cover
    httpx = None

ROOT = Path(__file__).resolve().parent.parent


def mask(key: str) -> str:
    """打印 key 时只露尾巴。日志、截图、答辩投屏都可能泄露它。"""
    if not key:
        return "(空)"
    return f"{key[:3]}****{key[-4:]}" if len(key) > 12 else "****"


def resolve_key(cfg: dict | None = None) -> tuple[str, str]:
    """返回 (key, 来源)。配置优先，其次环境变量。

    环境变量优先会让"临时试一下"更容易，配置优先会让"双击运行"更可靠
    —— 这个项目的使用方式是双击，所以配置优先。
    """
    cfg = cfg or {}
    k = (cfg.get("api_key") or "").strip()
    if k:
        return k, "config.json"
    k = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if k:
        return k, "环境变量 DEEPSEEK_API_KEY"
    return "", "未提供"


class DeepSeekClient:
    def __init__(self, base_url="https://api.deepseek.com", model="deepseek-flash",
                 api_key="", timeout_s=12.0, temperature=1.0, max_tokens=220):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.temperature = temperature
        self.max_tokens = max_tokens

    @property
    def ready(self) -> bool:
        return bool(self.api_key) and httpx is not None

    def _url(self, path: str) -> str:
        # 官方两种写法都收：https://api.deepseek.com/chat/completions
        # 和 https://api.deepseek.com/v1/chat/completions。这里统一走不带 v1 的。
        return f"{self.base_url}/{path.lstrip('/')}"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"}

    def chat(self, messages: list[dict], **over) -> str:
        """一次对话。失败抛 RuntimeError，消息里带上人话解释。

        不做流式：流式要多写一整套解析，而这个场景回复只有一两句，
        界面那边显示"小瑞在想…"就够了。真需要逐字效果再加。
        """
        if httpx is None:
            raise RuntimeError("没装 httpx（pip install httpx）")
        if not self.api_key:
            raise RuntimeError("没有 API key")
        body = {
            "model": over.get("model", self.model),
            "messages": messages,
            "temperature": over.get("temperature", self.temperature),
            "max_tokens": over.get("max_tokens", self.max_tokens),
            "stream": False,
        }
        try:
            r = httpx.post(self._url("/chat/completions"), json=body,
                           headers=self._headers(), timeout=self.timeout_s)
        except httpx.TimeoutException:
            raise RuntimeError(f"请求超时（{self.timeout_s:.0f} 秒）")
        except Exception as e:
            raise RuntimeError(f"连不上 {self.base_url}：{type(e).__name__} {e}")

        if r.status_code == 401:
            raise RuntimeError("401 —— API key 不对（检查 config.json 或环境变量）")
        if r.status_code == 402:
            raise RuntimeError("402 —— 账户余额不足")
        if r.status_code == 404:
            raise RuntimeError(f"404 —— 模型名 `{body['model']}` 可能已停用。"
                               f"跑 `python ui/deepseek.py --models` 看现在能用的名字")
        if r.status_code == 429:
            raise RuntimeError("429 —— 被限流了，稍后再试")
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code}：{r.text[:200]}")

        try:
            data = r.json()
            ch = (data.get("choices") or [{}])[0]
            msg = ch.get("message") or {}
            content = (msg.get("content") or "").strip()
        except Exception as e:
            raise RuntimeError(f"返回体看不懂：{type(e).__name__} {r.text[:200]}")

        # ★ 2026-09-24 晚：这里原来只有一行 `return content`，正文空了就由上层
        #   报一句「回复是空的」——**把唯一的线索扔了**。
        #   实情是 `deepseek-flash` 是**推理模型**：每次返回都带 `reasoning_content`，
        #   而 `max_tokens` 卡的是**思考 + 正文合起来**的预算。思考一多就把预算
        #   吃光，正文一个字不剩，`finish_reason='length'`。
        #   实测（_scratch/_probe_empty.py，max_tokens=400）：三轮里**两轮**是这样，
        #   400 个 completion token 全是 reasoning —— 产品那边静默退回固定话术，
        #   用户看到的就是"有时候像模型、有时候像提前写好的话"，而界面卡头还写着
        #   「回复来自 DeepSeek 模型」。所以这一支必须带上数字说清楚。
        if not content:
            u = data.get("usage") or {}
            rt = (u.get("completion_tokens_details") or {}).get("reasoning_tokens")
            fin = ch.get("finish_reason")
            if fin == "length":
                raise RuntimeError(
                    "思考把 token 预算吃光了，正文一个字没返回"
                    f"（finish_reason=length，completion_tokens={u.get('completion_tokens')}"
                    f"，其中 reasoning_tokens={rt}，max_tokens={body['max_tokens']}）"
                    "—— 把 config.json 里 agent.deepseek.max_tokens 调大")
            raise RuntimeError(
                f"模型返回了空正文（finish_reason={fin!r}，"
                f"reasoning_tokens={rt}，有 reasoning_content="
                f"{bool(msg.get('reasoning_content'))}）")
        return content

    def list_models(self) -> list[str]:
        if httpx is None or not self.api_key:
            return []
        r = httpx.get(self._url("/models"), headers=self._headers(),
                      timeout=self.timeout_s)
        r.raise_for_status()
        return [m.get("id", "?") for m in r.json().get("data", [])]


def load_config(path: str | Path | None = None) -> dict:
    """读 ui/config.json；没有就退回 config.example.json（只是为了让界面能起来）。"""
    p = Path(path) if path else (ROOT / "ui" / "config.json")
    if not p.exists():
        p = ROOT / "ui" / "config.example.json"
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser(description="DeepSeek 连通性自测")
    ap.add_argument("--models", action="store_true", help="列出这个 key 能用的模型")
    ap.add_argument("--say", metavar="TEXT", help="发一句话，看回复")
    ap.add_argument("--config", default=None)
    a = ap.parse_args()

    cfg = load_config(a.config)
    d = cfg.get("agent", {}).get("deepseek", {})
    key, src = resolve_key(d)
    print(f"base_url = {d.get('base_url')}")
    print(f"model    = {d.get('model')}")
    print(f"api_key  = {mask(key)}   （来源：{src}）")
    if not key:
        print("\n没有 key。两种填法：")
        print("  1) 复制 ui/config.example.json -> ui/config.json，把 api_key 填上")
        print("  2) 或者设环境变量 DEEPSEEK_API_KEY")
        return 1

    cli = DeepSeekClient(d.get("base_url", "https://api.deepseek.com"),
                         d.get("model", "deepseek-flash"), key,
                         d.get("timeout_s", 12.0))
    if a.models or not a.say:
        try:
            names = cli.list_models()
            print(f"\n可用模型（{len(names)} 个）：")
            for n in sorted(names):
                flag = "   ← 配置里用的就是这个" if n == cli.model else ""
                print(f"  - {n}{flag}")
            if cli.model not in names:
                print(f"\n⚠️ 配置里的 `{cli.model}` 不在名单里，换一个。")
        except Exception as e:
            print(f"\n列模型失败：{e}")
            return 1
    if a.say:
        try:
            out = cli.chat([{"role": "system", "content": "你是车载助手小瑞，回复控制在 40 字以内。"},
                            {"role": "user", "content": a.say}])
            print(f"\n小瑞：{out}")
        except Exception as e:
            print(f"\n调用失败：{e}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
