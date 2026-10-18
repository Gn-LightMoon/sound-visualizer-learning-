# -*- coding: utf-8 -*-
"""最小后端：仅用于测试 /api/llm/chat 与 /api/llm/chat/stream 的 HTTP 层。

不依赖 torch/librosa 等重模块，接口代码与 main.py 中完全一致。
完整后端请用 main.py（需 A/B 环境）。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

import llm_service

app = FastAPI(title="看得见的声音 - LLM 接口最小测试服务")


class ChatMessage(BaseModel):
    role: str = "user"
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    temperature: float = 0.7


@app.post("/api/llm/chat")
def llm_chat(req: ChatRequest):
    if not llm_service.is_available():
        return JSONResponse(
            status_code=503,
            content={"code": 503, "message": "本地大模型服务（Ollama）未运行，请先启动"},
        )
    try:
        reply = llm_service.chat(
            [m.model_dump() for m in req.messages], temperature=req.temperature
        )
        return {"code": 200, "data": {"model": llm_service.OLLAMA_MODEL, "reply": reply}}
    except Exception as e:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content={"code": 500, "message": f"大模型调用失败: {str(e)}"},
        )


@app.post("/api/llm/chat/stream")
def llm_chat_stream(req: ChatRequest):
    def gen():
        try:
            for piece in llm_service.chat_stream(
                [m.model_dump() for m in req.messages], temperature=req.temperature
            ):
                yield f"data: {json.dumps({'content': piece}, ensure_ascii=False)}\n\n"
        except Exception as e:  # noqa: BLE001
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8001)
