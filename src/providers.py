# -*- coding: utf-8 -*-
"""模型调用接口层（Provider）。

设计要点
--------
1. 把「一次补全」抽象成最小动作，测试套件不关心底层是哪家模型；
2. `MockProvider` 用于 CI：结果完全确定、可离线运行，
   并且让「套件本身是否有效」也能被回归测试（对应 `tests/test_checks.py`）；
3. `OpenAICompatProvider` 兼容所有 OpenAI 协议的服务
   （DeepSeek / 通义千问 / 智谱 / 本地 Ollama / vLLM 均可），只改 base_url 与 model 即可切换。

零第三方依赖：HTTP 走标准库，方便在任何环境跑起来。
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field


@dataclass
class Completion:
    """一次模型补全的结果。"""

    text: str
    latency_ms: float
    model: str
    error: str = ""          # 非空表示调用失败（超时、网络、限流等）
    raw: dict = field(default_factory=dict)


class Provider:
    """模型接口基类。"""

    name = "base"

    def complete(self, prompt: str, system: str = "", case_id: str = "",
                 temperature: float = 0.0) -> Completion:
        raise NotImplementedError

    def close(self) -> None:
        pass


class OpenAICompatProvider(Provider):
    """OpenAI 兼容协议（/v1/chat/completions）。

    典型配置：
        DeepSeek   base_url=https://api.deepseek.com/v1          model=deepseek-chat
        通义千问   base_url=https://dashscope.aliyuncs.com/compatible-mode/v1
        智谱 GLM   base_url=https://open.bigmodel.cn/api/paas/v4
        本地 Ollama base_url=http://localhost:11434/v1           model=qwen2.5:7b
    """

    def __init__(self, base_url: str, api_key: str, model: str,
                 timeout: int = 60, retries: int = 2):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.retries = retries
        self.name = "openai-compat:%s" % model

    def complete(self, prompt: str, system: str = "", case_id: str = "",
                 temperature: float = 0.0) -> Completion:
        body = {
            "model": self.model,
            "temperature": temperature,
            "messages": ([{"role": "system", "content": system}] if system else [])
                        + [{"role": "user", "content": prompt}],
        }
        url = self.base_url + "/chat/completions"
        last_err = ""
        for attempt in range(self.retries + 1):
            t0 = time.perf_counter()
            try:
                req = urllib.request.Request(
                    url, data=json.dumps(body).encode("utf-8"), method="POST")
                req.add_header("Content-Type", "application/json")
                if self.api_key:
                    req.add_header("Authorization", "Bearer " + self.api_key)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                ms = (time.perf_counter() - t0) * 1000
                text = data["choices"][0]["message"]["content"]
                return Completion(text=text, latency_ms=ms,
                                  model=self.model, raw=data)
            except Exception as exc:                      # noqa: BLE001
                last_err = "%s: %s" % (type(exc).__name__, exc)
                if attempt < self.retries:
                    time.sleep(1.5 * (attempt + 1))
        return Completion(text="", latency_ms=0.0, model=self.model,
                          error=last_err)

    @classmethod
    def from_env(cls, model: str = "") -> "OpenAICompatProvider":
        """从环境变量构造：LLM_BASE_URL / LLM_API_KEY / LLM_MODEL。"""
        return cls(
            base_url=os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1"),
            api_key=os.environ.get("LLM_API_KEY", ""),
            model=model or os.environ.get("LLM_MODEL", "deepseek-chat"),
        )


class MockProvider(Provider):
    """离线确定性 Provider，用于 CI 与套件自检。

    scenario='good' → 所有检查应通过（验证检查器不会误报）
    scenario='bad'  → 预设缺陷应答（验证检查器确实能抓到问题）
    """

    def __init__(self, scenario: str = "good"):
        self.scenario = scenario
        self.name = "mock:%s" % scenario
        self._call_index: dict[str, int] = {}

    def complete(self, prompt: str, system: str = "", case_id: str = "",
                 temperature: float = 0.0) -> Completion:
        from mock_data import respond                     # 延迟导入，便于单独使用
        idx = self._call_index.get(case_id, 0)
        self._call_index[case_id] = idx + 1
        text = respond(self.scenario, case_id, idx, prompt)
        return Completion(text=text, latency_ms=1.0,
                          model="mock", raw={"scenario": self.scenario})


def build_provider(spec: str) -> Provider:
    """按字符串规格构造 Provider。

    'mock'        或 'mock:good' / 'mock:bad'
    'env'         从环境变量读 OpenAI 兼容配置
    'openai:<model>'  同上但指定模型名
    """
    spec = (spec or "mock:good").strip()
    if spec.startswith("mock"):
        _, _, sc = spec.partition(":")
        return MockProvider(sc or "good")
    if spec == "env":
        return OpenAICompatProvider.from_env()
    if spec.startswith("openai:"):
        return OpenAICompatProvider.from_env(spec.split(":", 1)[1])
    raise ValueError("无法识别的 provider 规格: %r" % spec)
