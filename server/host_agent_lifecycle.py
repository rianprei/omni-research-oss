"""Process-local conversations for independent MCP client-sampling completions.

Each model call occurs inside a live MCP tools/call request. This never starts
an autonomous ChatGPT agent, and no data survives a process restart.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from collections import OrderedDict
from threading import RLock
from typing import Any

import host_sampling_core as sampling

_MAX_AGENTS = 32
_MAX_PARALLEL = 3
_lock = RLock()
_agents: OrderedDict[str, dict] = OrderedDict()
_limit = 3
_active = 0


def _public(agent: dict, include_result: bool = True) -> dict:
    out = {k: agent[k] for k in (
        "agent_id", "role", "status", "created_at", "updated_at", "reported_model"
    )}
    out["messages"] = len(agent["history"])
    if include_result:
        out["result"] = agent["result"]
        out["error"] = agent["error"]
    return out


def configuration(limit: int | None = None) -> dict:
    """Return or set the maximum in-flight host sampling requests (1..3)."""
    global _limit
    if limit is not None and (type(limit) is not int or not 1 <= limit <= _MAX_PARALLEL):
        raise ValueError("limit must be an integer from 1 to 3")
    with _lock:
        if limit is not None:
            _limit = limit
        return {
            "max_concurrent_subagents": _limit,
            "active_sampling_requests": _active,
            "maximum_supported": _MAX_PARALLEL,
            "scope": "single server process (reset on restart)",
            "native_chatgpt_agents": False,
        }


def list_agents(include_results: bool = False) -> dict:
    with _lock:
        return {
            "agents": [_public(a, include_results) for a in _agents.values()],
            "count": len(_agents),
            "configuration": configuration(),
        }


def _reserve(count: int) -> bool:
    global _active
    with _lock:
        if _active + count > _limit:
            return False
        _active += count
        return True


def _release(count: int) -> None:
    global _active
    with _lock:
        _active -= count


def _register(role: str, prompt: str, result: dict) -> dict:
    record = {
        "agent_id": uuid.uuid4().hex,
        "role": role,
        "status": result["status"],
        "created_at": time.time(),
        "updated_at": time.time(),
        "reported_model": result.get("reported_model"),
        "result": result.get("result"),
        "error": result.get("error"),
        "history": [{"role": "user", "text": prompt}],
    }
    if record["result"]:
        record["history"].append({"role": "assistant", "text": record["result"]})
    with _lock:
        while len(_agents) >= _MAX_AGENTS:
            candidate = next((k for k, a in _agents.items() if a["status"] != "running"), None)
            if candidate is None:
                return {"error": "AGENT_STORAGE_LIMIT"}
            _agents.pop(candidate)
        _agents[record["agent_id"]] = record
    return _public(record)


async def spawn_agents(session: Any, request_id: Any, prompt: str,
                       roles: list[str] | None = None, max_tokens: int = 400,
                       model_hint: str = "gpt-6") -> dict:
    chosen = ["researcher", "critic", "planner"] if roles is None else roles
    if not isinstance(prompt, str) or not 3 <= len(prompt.strip()) <= 2000:
        raise ValueError("prompt must contain 3-2000 characters")
    if not isinstance(chosen, list) or not 1 <= len(chosen) <= 3 or any(r not in sampling.ROLES for r in chosen):
        raise ValueError("roles must contain 1-3 supported roles")
    if type(max_tokens) is not int or not 64 <= max_tokens <= 1024:
        raise ValueError("max_tokens must be an integer from 64 to 1024")
    if not isinstance(model_hint, str) or len(model_hint) > 48:
        raise ValueError("Invalid model hint")
    if not sampling.capability(session):
        return {"spawned": False, "agents_started": 0,
                "error": "HOST_SAMPLING_UNSUPPORTED", "agent_ids": [],
                "message": "MCP client did not advertise sampling; no model invoked."}
    groups, offset = [], 0
    while offset < len(chosen):
        with _lock:
            capacity = max(0, _limit - _active)
        if capacity == 0:
            return {"spawned": bool(groups), "error": "CONCURRENCY_LIMIT",
                    "agent_ids": [a["agent_id"] for group in groups for a in group["agents"] if "agent_id" in a],
                    "groups": groups}
        batch = chosen[offset:offset + capacity]
        if not _reserve(len(batch)):
            continue
        try:
            raw = await sampling.spawn(session, request_id, prompt, batch, max_tokens, model_hint)
        finally:
            _release(len(batch))
        registrations = [_register(role, prompt.strip(), res)
                         for role, res in zip(batch, raw["results"])]
        groups.append({"task_id": raw["task_id"], "status": raw["status"],
                       "agents": registrations})
        offset += len(batch)
    agent_ids = [a["agent_id"] for group in groups for a in group["agents"] if "agent_id" in a]
    completed = sum(a["status"] == "completed" for group in groups for a in group["agents"])
    return {"spawned": completed > 0, "task_id": groups[0]["task_id"],
            "task_ids": [g["task_id"] for g in groups], "agent_ids": agent_ids,
            "agents_requested": len(chosen), "agents_completed": completed,
            "status": "completed" if completed == len(chosen) else "partial_failure",
            "groups": groups,
            "note": "Independent sampling completions; not native ChatGPT agents. All model calls finish within this request."}


async def send_message(session: Any, request_id: Any, agent_id: str, message: str,
                       max_tokens: int = 400, model_hint: str = "gpt-6") -> dict:
    if not isinstance(agent_id, str) or len(agent_id) != 32:
        raise ValueError("Invalid agent_id")
    if not isinstance(message, str) or not 3 <= len(message.strip()) <= 800:
        raise ValueError("message must contain 3-800 characters")
    if type(max_tokens) is not int or not 64 <= max_tokens <= 1024:
        raise ValueError("max_tokens must be an integer from 64 to 1024")
    if not isinstance(model_hint, str) or len(model_hint) > 48:
        raise ValueError("Invalid model hint")
    if not sampling.capability(session):
        return {"sent": False, "error": "HOST_SAMPLING_UNSUPPORTED",
                "message": "No model invoked."}
    with _lock:
        agent = _agents.get(agent_id)
        if agent is None:
            return {"sent": False, "error": "AGENT_NOT_FOUND_OR_RESTARTED"}
        if agent["status"] == "running":
            return {"sent": False, "error": "AGENT_BUSY"}
        if not _reserve(1):
            return {"sent": False, "error": "CONCURRENCY_LIMIT"}
        agent["status"] = "running"
        history = list(agent["history"][-4:])
        role = agent["role"]
    transcript = "\n".join(f"{turn['role'].upper()}: {turn['text'][:210]}" for turn in history)
    followup = ("Continue this same isolated subagent conversation. Prior exchanges:\n"
                + transcript + "\nUSER: " + message.strip())[:2000]
    try:
        raw = await sampling.spawn(session, request_id, followup, [role], max_tokens, model_hint)
        item = raw["results"][0]
    except Exception:
        with _lock:
            agent["status"] = "failed"
            agent["error"] = "SAMPLING_ERROR"
            agent["updated_at"] = time.time()
        raise
    finally:
        _release(1)
    with _lock:
        agent["status"] = item["status"]
        agent["reported_model"] = item.get("reported_model")
        agent["result"] = item.get("result")
        agent["error"] = item.get("error")
        agent["updated_at"] = time.time()
        agent["history"].append({"role": "user", "text": message.strip()})
        if agent["result"]:
            agent["history"].append({"role": "assistant", "text": agent["result"]})
        agent["history"] = agent["history"][-8:]
        result = _public(agent)
    return {"sent": item["status"] == "completed", **result,
            "note": "This was a new client-sampling completion in the active tool request."}


async def wait_agent(agent_id: str, timeout_seconds: int = 0) -> dict:
    if not isinstance(agent_id, str) or len(agent_id) != 32:
        raise ValueError("Invalid agent_id")
    if type(timeout_seconds) is not int or not 0 <= timeout_seconds <= 20:
        raise ValueError("timeout_seconds must be between 0 and 20")
    deadline = time.monotonic() + timeout_seconds
    while True:
        with _lock:
            agent = _agents.get(agent_id)
            if agent is None:
                return {"error": "AGENT_NOT_FOUND_OR_RESTARTED", "agent_id": agent_id}
            snapshot = _public(agent)
        if snapshot["status"] != "running" or time.monotonic() >= deadline:
            return snapshot
        await asyncio.sleep(0.1)
