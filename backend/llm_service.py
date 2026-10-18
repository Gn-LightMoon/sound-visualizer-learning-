# -*- coding: utf-8 -*-
"""
看得见的声音 - 本地大模型服务（Ollama 封装）

职责：
- 封装对 Ollama 本地服务（http://localhost:11434）的调用
- 提供非流式对话 chat() 与流式对话 chat_stream()
- 供 /api/llm/chat、/api/llm/chat/stream、CMS 初筛等复用

说明：
- 使用标准库 urllib，避免引入额外 HTTP 依赖
- 同步调用，由 FastAPI 的同步 def 接口自动放入线程池，不阻塞事件循环
- 模型名可用环境变量 LLM_MODEL 覆盖，默认 qwen2.5:7b
"""
import json
import os
import urllib.request

OLLAMA_BASE = os.environ.get("OLLAMA_BASE", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("LLM_MODEL", "qwen2.5:7b")


def _build_payload(messages: list[dict], temperature: float, stream: bool) -> dict:
    return {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": stream,
        "options": {"temperature": temperature},
    }


def _post(payload: dict, timeout: int = 180):
    req = urllib.request.Request(
        f"{OLLAMA_BASE}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return urllib.request.urlopen(req, timeout=timeout)


def chat(messages: list[dict], temperature: float = 0.7) -> str:
    """非流式对话，返回完整回复文本"""
    payload = _build_payload(messages, temperature, stream=False)
    with _post(payload) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("message", {}).get("content", "")


def chat_stream(messages: list[dict], temperature: float = 0.7):
    """流式对话，逐段 yield 回复文本片段（供前端打字机效果）"""
    payload = _build_payload(messages, temperature, stream=True)
    with _post(payload) as resp:
        for raw in resp:
            line = raw.decode("utf-8").strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            piece = data.get("message", {}).get("content", "")
            if piece:
                yield piece
            if data.get("done"):
                break


def is_available() -> bool:
    """检查 Ollama 服务是否可访问"""
    try:
        with urllib.request.urlopen(f"{OLLAMA_BASE}/api/tags", timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False
