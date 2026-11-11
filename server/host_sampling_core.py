"""Experimental MCP sampling bridge. No API key or native ChatGPT agent access."""
from __future__ import annotations
import asyncio
import time
import uuid
from collections import OrderedDict
from threading import RLock
from typing import Any
from mcp.types import ModelHint, ModelPreferences, SamplingMessage, TextContent

ROLES = {
    "researcher": "Independently analyze the research question. Flag unverified claims, do not invent citations.",
    "critic": "Review assumptions, contradictions, edge cases and weaknesses independently.",
    "planner": "Produce a concrete independent plan with dependencies and measurable acceptance criteria.",
    "coder": "Analyze code tasks. You cannot execute code or access a repository unless explicitly provided.",
    "synthesizer": "Synthesize the supplied problem and flag disputed evidence.",
}
_records: OrderedDict[str, dict] = OrderedDict()
_lock = RLock()

def capability(session: Any) -> bool:
    return getattr(getattr(session, "client_capabilities", None), "sampling", None) is not None

def describe(session: Any) -> dict:
    return {
        "client_sampling_declared": capability(session),
        "roles": list(ROLES),
        "maximum_agents": 3,
        "backend": "MCP client sampling/createMessage",
        "api_key_required": False,
        "native_chatgpt_agent_creation": False,
        "model": "Client-controlled; model hint gpt-6 is not a guarantee",
        "protocol": "Legacy 2025-era server-to-client sampling; deprecated in MCP 2026-07-28",
        "run_mode": "Synchronous inside the originating MCP request",
    }

def lookup(task_id: str) -> dict:
    if not isinstance(task_id, str) or len(task_id) > 80:
        raise ValueError("Invalid task id")
    with _lock:
        record = _records.get(task_id)
        return dict(record) if record else {"error": "TASK_NOT_FOUND_OR_RESTARTED", "task_id": task_id}

async def spawn(session: Any, request_id: Any, prompt: str,
                roles: list[str] | None = None, max_tokens: int = 400,
                model_hint: str = "gpt-6", timeout_seconds: float = 45) -> dict:
    if not isinstance(prompt, str) or not 3 <= len(prompt.strip()) <= 2000:
        raise ValueError("Prompt must be 3-2000 characters")
    chosen = roles if roles is not None else ["researcher", "critic", "planner"]
    if not isinstance(chosen, list) or not 1 <= len(chosen) <= 3 or any(r not in ROLES for r in chosen):
        raise ValueError("roles must contain 1-3 supported roles")
    if type(max_tokens) is not int or not 64 <= max_tokens <= 1024:
        raise ValueError("max_tokens must be an integer from 64 to 1024")
    if not isinstance(model_hint, str) or len(model_hint) > 48:
        raise ValueError("Invalid model hint")
    if not capability(session):
        return {"spawned": False, "error": "HOST_SAMPLING_UNSUPPORTED", "agents_started": 0,
                "message": "Connected MCP client does not advertise sampling; no model invoked."}

    async def one(role: str) -> dict:
        try:
            result = await asyncio.wait_for(session.create_message(
                messages=[SamplingMessage(role="user", content=TextContent(type="text", text=prompt.strip()))],
                system_prompt=ROLES[role],
                model_preferences=ModelPreferences(hints=[ModelHint(name=model_hint)]),
                max_tokens=max_tokens, related_request_id=request_id,
            ), timeout=timeout_seconds)
            content = getattr(result, "content", None)
            if not isinstance(content, TextContent) or not content.text.strip():
                return {"role": role, "status": "failed", "error": "UNSUPPORTED_MODEL_RESULT"}
            return {"role": role, "status": "completed", "result": content.text[:12000],
                    "reported_model": getattr(result, "model", "unknown")}
        except asyncio.TimeoutError:
            return {"role": role, "status": "failed", "error": "HOST_SAMPLING_TIMEOUT"}
        except Exception as exc:
            return {"role": role, "status": "failed", "error": "CLIENT_SAMPLING_REQUEST_REJECTED",
                    "reason_class": type(exc).__name__}

    results = await asyncio.gather(*(one(role) for role in chosen))
    record = {
        "task_id": uuid.uuid4().hex,
        "status": "completed" if all(r["status"] == "completed" for r in results) else "partial_failure",
        "agents_requested": len(chosen),
        "agents_completed": sum(r["status"] == "completed" for r in results),
        "results": results,
        "created_at": time.time(),
        "note": "The MCP client, not the server, selected the models; this did not create native ChatGPT agents.",
    }
    with _lock:
        _records[record["task_id"]] = record
        while len(_records) > 32:
            _records.popitem(last=False)
    return dict(record, spawned=record["agents_completed"] > 0)
