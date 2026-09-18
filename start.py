#!/usr/bin/env python3

import importlib
import json
import time
from collections.abc import Iterator
from contextlib import asynccontextmanager
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

print("sandboxed-llm v1.0 - An LLM Server to test a sandboxed LLM architecture, created by Simone Curzi.")

from logging_config import logger
from src.data_classes import RequestParams
from src.model_manager import ModelManager
from src.session import Session
from src.session_manager import SessionManager
from src.session_model import ModelSession


class ChatCompletionMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str

class DataNode(BaseModel):
    id: str
    content: str

class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[ChatCompletionMessage]
    data: list[DataNode] | None = None  # This is the new proposed addition for handling structured data nodes.
    stream: bool = False
    temperature: float | None = None
    top_k: int | None = None
    top_p: float | None = None
    typical_p: float | None = None
    min_p: float | None = None
    tfs_z: float | None = None
    repeat_penalty: float | None = None
    max_tokens: int | None = None
    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    logit_bias: dict[str, float] | None = None

    def to_request_params(self) -> RequestParams:
        return RequestParams(
            messages=[message.model_dump() for message in self.messages],
            data=[data_node.model_dump() for data_node in self.data] if self.data is not None else None,
            temperature=self.temperature,
            top_k=self.top_k,
            top_p=self.top_p,
            typical_p=self.typical_p,
            min_p=self.min_p,
            tfs_z=self.tfs_z,
            repeat_penalty=self.repeat_penalty,
            max_tokens=self.max_tokens,
            presence_penalty=self.presence_penalty,
            frequency_penalty=self.frequency_penalty,
            logit_bias=self.logit_bias,
        )

def run_server(host: str = "127.0.0.1", port: int = 10421):
    try:
        uvicorn = importlib.import_module("uvicorn")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "uvicorn is required to run the server. Install it with: pip install uvicorn"
        ) from exc

    import sys
    import termios
    _original_term_attrs: list[Any] | None = None
    fd: int | None = None
    if sys.stdin.isatty():
        try:
            stdin_fd = sys.stdin.fileno()
            fd = stdin_fd
            _original_term_attrs = termios.tcgetattr(stdin_fd)
            new_attrs = termios.tcgetattr(stdin_fd)
            new_attrs[3] &= ~termios.ECHOCTL
            termios.tcsetattr(stdin_fd, termios.TCSANOW, new_attrs)
        except termios.error:
            _original_term_attrs = None

    try:
        logger.info(f"Starting sandboxed-llm on http://{host}:{port}")
        uvicorn.run(app, host=host, port=port)
    finally:
        if _original_term_attrs is not None and fd is not None:
            try:
                termios.tcsetattr(fd, termios.TCSANOW, _original_term_attrs)
            except termios.error:
                pass

@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        yield
    finally:
        session_manager.close_all_sessions()

        import gc
        gc.collect()

        print("All resources have been released.")

app = FastAPI(title="sandboxed-llm", lifespan=lifespan)
model_manager: ModelManager
session_manager: SessionManager

#region API Endpoints: OpenAPI-compatible APIs.
@app.get("/v1/models")
def list_openai_models():
    return {
        "object": "list",
        "data": [
            {
                "id": model_info.name,
                "object": "model",
                "owned_by": "sandboxed-llm",
            }
            for model_info in model_manager.get_model_infos()
        ],
    }

def _sse_data(payload: object) -> str:
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"

def _stream_chat_completion(
    session_id: UUID,
    stream: Iterator[str],
    completion_id: str,
    created: int,
    model_name: str,
) -> Iterator[str]:
    def chunk(delta: dict[str, str], finish_reason: str | None = None) -> dict:
        return {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "delta": delta,
                    "finish_reason": finish_reason,
                }
            ],
        }

    try:
        yield _sse_data(chunk({"role": "assistant", "content": ""}))
        for text in stream:
            yield _sse_data(chunk({"content": text}))
        yield _sse_data(chunk({}, "stop"))
        yield "data: [DONE]\n\n"
    finally:
        session_manager.close_session(session_id)

@app.post("/v1/chat/completions")
def create_chat_completion(request: ChatCompletionRequest):
    if not model_manager.is_model_defined(request.model):
        logger.warning(f"Model '{request.model}' is not defined.")
        raise HTTPException(status_code=404, detail=f"Model '{request.model}' is not defined.")

    session: Session | None = session_manager.get_global_session(request.model)
    if session is None:
        logger.info(f"No global session found for model '{request.model}'. Creating a new session.")
        session_id = session_manager.create_session(request.model, global_session=True)
        session = session_manager.get_session(session_id)
    else:
        logger.info(f"Using existing global session '{session.session_id}' for model '{request.model}'.")
        session_id = session.session_id
  
    if not isinstance(session, ModelSession):
        session_manager.close_session(session_id)
        raise HTTPException(status_code=500, detail="Model session could not be initialized.")

    completion_id = f"chatcmpl-{uuid4().hex}"
    created = int(time.time())
    params = request.to_request_params()

    if request.stream:
        stream = session.stream(params)
        if stream is None:
            raise HTTPException(status_code=500, detail="Model stream is not available.")
        return StreamingResponse(
            _stream_chat_completion(session_id, stream, completion_id, created, request.model),
            media_type="text/event-stream",
        )

    content = session.chat(params)
    if content is None:
        raise HTTPException(status_code=500, detail="Model response is not available.")
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": request.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }
#endregion

if __name__ == "__main__":
    model_manager = ModelManager()
    session_manager = SessionManager(model_manager)
    print("Starting sandboxed model...")
    session_manager.register_sandboxed_model()

    run_server()
