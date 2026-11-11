"""Bounded, API-backed subagent executor for an authenticated remote MCP service.

These are independent LLM calls with isolated prompts, not native ChatGPT agents.
Render free instances are ephemeral: tasks do NOT survive a restart/sleep.
"""
from __future__ import annotations

import concurrent.futures
import hmac
import json
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from urllib.parse import urlparse

ROLES = {
    "general": "You are an autonomous task-focused assistant. Return concrete, verifiable results. Identify uncertainty.",
    "researcher": "You are a research subagent. Analyze the question, distinguish evidence from assumption, and state what needs external verification. You have no browsing tools.",
    "critic": "You are an independent reviewer. Find unsupported claims, edge cases, contradictions, and specific corrective actions.",
    "coder": "You are a programming subagent. Provide precise implementation or review. You have no filesystem, shell, or repository access.",
    "synthesizer": "You synthesize independent agent outputs. Preserve disagreements and never invent citations.",
}
MAX_CONCURRENT = 3
MAX_TASKS = 32
MAX_REQUESTS_PER_DAY = 30  # Process-local backstop, not a billing or distributed quota.
_pool = concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT, thread_name_prefix="omni-agent")
_lock = threading.RLock()
_jobs = {}
_seen = {}
_daily = {"day": "", "count": 0}


@dataclass
class Job:
    id: str
    role: str
    prompt: str
    status: str = "queued"
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    result: str | None = None
    error: str | None = None
    cancelled: threading.Event = field(default_factory=threading.Event, repr=False)
    future: object = field(default=None, repr=False)

    def public(self) -> dict:
        return {
            "task_id": self.id, "role": self.role, "status": self.status,
            "created_at": self.created, "started_at": self.started,
            "finished_at": self.finished, "result": self.result if self.status == "completed" else None,
            "error": self.error, "cancellation_pending": self.cancelled.is_set() and self.status == "running",
        }


def provider_status() -> dict:
    key = os.environ.get("OMNI_AGENT_MODEL_KEY", "")
    model = os.environ.get("OMNI_AGENT_MODEL", "")
    base = os.environ.get("OMNI_AGENT_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    parsed = urlparse(base)
    valid = (parsed.scheme == "https" and bool(parsed.hostname)
             and not parsed.username and not parsed.password and not parsed.fragment
             and not parsed.query and not parsed.path.endswith("/chat/completions"))
    return {
        "configured": bool(key and model and valid),
        "model": model if model else None,
        "provider_host": parsed.hostname if valid else None,
        "max_concurrent": MAX_CONCURRENT,
        "max_active_and_retained": MAX_TASKS,
        "daily_submission_backstop": MAX_REQUESTS_PER_DAY,
        "durable": False,
        "native_chatgpt_agents": False,
        "note": "Independent one-shot model requests, not internal ChatGPT subagents. "
                "Provider/API billing and quotas are separate. Jobs are process-local.",
    }


def agent(action: str = "list") -> dict:
    if action not in ("list", "status"):
        raise ValueError("action must be list or status")
    out = {"roles": ROLES if action == "list" else list(ROLES), "backend": provider_status()}
    with _lock:
        out["task_counts"] = {state: sum(j.status == state for j in _jobs.values())
                              for state in ("queued", "running", "completed", "failed", "cancelled")}
    return out


def _invoke_provider(role: str, prompt: str, max_output_tokens: int) -> str:
    key = os.environ["OMNI_AGENT_MODEL_KEY"]
    model = os.environ["OMNI_AGENT_MODEL"]
    base = os.environ.get("OMNI_AGENT_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    if not provider_status()["configured"]:
        raise RuntimeError("Invalid model provider configuration")
    timeout = min(75, max(5, int(os.environ.get("OMNI_AGENT_TIMEOUT_SECONDS", "45"))))
    token_param = os.environ.get("OMNI_AGENT_TOKEN_PARAMETER", "max_completion_tokens")
    if token_param not in ("max_tokens", "max_completion_tokens"):
        raise RuntimeError("Invalid token parameter configuration")
    data = {
        "model": model, "messages": [
            {"role": "system", "content": ROLES[role]},
            {"role": "user", "content": prompt},
        ], token_param: max_output_tokens,
    }
    request = urllib.request.Request(
        base + "/chat/completions", method="POST",
        data=json.dumps(data).encode("utf-8"),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json",
                 "User-Agent": "OmniAgentsOSS/0.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(1_000_000)
        parsed = json.loads(raw)
    except urllib.error.HTTPError as exc:
        # Do not expose raw provider errors; they may echo sensitive data.
        raise RuntimeError(f"Provider HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"Provider connection failed: {type(exc).__name__}") from None
    try:
        answer = parsed["choices"][0]["message"]["content"]
        if isinstance(answer, list):
            answer = "\n".join(x.get("text", "") for x in answer if isinstance(x, dict))
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("Empty model text")
        return answer[:16000]
    except (KeyError, IndexError, TypeError, ValueError):
        raise RuntimeError("Provider returned an unsupported response schema") from None


def _run(job: Job, max_output_tokens: int) -> None:
    with _lock:
        if job.cancelled.is_set():
            job.status = "cancelled"
            job.finished = time.time()
            return
        job.status = "running"
        job.started = time.time()
    try:
        result = _invoke_provider(job.role, job.prompt, max_output_tokens)
        with _lock:
            if job.cancelled.is_set():
                job.status, job.result = "cancelled", None
            else:
                job.status, job.result = "completed", result
    except Exception as exc:
        with _lock:
            if job.cancelled.is_set():
                job.status = "cancelled"
            else:
                job.status, job.error = "failed", str(exc)[:250]
    finally:
        with _lock:
            job.finished = time.time()


def spawn_agent(
    prompt: str, role: str = "general", count: int = 1,
    max_output_tokens: int = 512, idempotency_key: str = "",
) -> dict:
    if not provider_status()["configured"]:
        return {"started": False, "error": "MODEL_PROVIDER_NOT_CONFIGURED",
                "required_env": ["OMNI_AGENT_MODEL_KEY", "OMNI_AGENT_MODEL"],
                "note": "A ChatGPT subscription is not a model API credential."}
    if not isinstance(prompt, str) or not 3 <= len(prompt.strip()) <= 4000:
        raise ValueError("prompt must be between 3 and 4000 characters")
    if role not in ROLES:
        raise ValueError("Unknown role")
    if type(count) is not int or not 1 <= count <= MAX_CONCURRENT:
        raise ValueError("count must be 1-3")
    if type(max_output_tokens) is not int or not 64 <= max_output_tokens <= 1024:
        raise ValueError("max_output_tokens must be 64-1024")
    if not isinstance(idempotency_key, str) or len(idempotency_key) > 100:
        raise ValueError("idempotency_key is too long")
    prompt = prompt.strip()
    with _lock:
        today = time.strftime("%Y-%m-%d", time.gmtime())
        if _daily["day"] != today:
            _daily.update(day=today, count=0)
        if idempotency_key and idempotency_key in _seen:
            old_prompt, old_role, old_count, ids = _seen[idempotency_key]
            if (old_prompt, old_role, old_count) != (prompt, role, count):
                raise ValueError("Idempotency key reused with different arguments")
            return {"started": True, "replayed": True, "task_ids": ids}
        live = sum(x.status in ("queued", "running") for x in _jobs.values())
        if live + count > MAX_CONCURRENT:
            return {"started": False, "error": "CONCURRENCY_LIMIT"}
        if _daily["count"] + count > MAX_REQUESTS_PER_DAY:
            return {"started": False, "error": "DAILY_LIMIT"}
        if len(_jobs) + count > MAX_TASKS:
            # Evict only terminal history, never running work.
            expired = sorted((j for j in _jobs.values() if j.status in ("completed", "failed", "cancelled")),
                             key=lambda j: j.finished or 0)
            for job in expired[:len(_jobs) + count - MAX_TASKS]:
                _jobs.pop(job.id, None)
            if len(_jobs) + count > MAX_TASKS:
                return {"started": False, "error": "TASK_STORAGE_LIMIT"}
        ids = []
        for _ in range(count):
            job = Job(id=uuid.uuid4().hex, role=role, prompt=prompt)
            _jobs[job.id] = job
            ids.append(job.id)
        _daily["count"] += count
        if idempotency_key:
            _seen[idempotency_key] = (prompt, role, count, ids)
        for id_ in ids:
            job = _jobs[id_]
            job.future = _pool.submit(_run, job, max_output_tokens)
    return {"started": True, "replayed": False, "task_ids": ids,
            "note": "Real separate model API calls; use task(action='get') to poll. In-memory only."}


def task(action: str = "list", task_id: str = "") -> dict:
    if action not in ("list", "get", "cancel"):
        raise ValueError("action must be list, get or cancel")
    with _lock:
        if action == "list":
            return {"tasks": [job.public() for job in
                              sorted(_jobs.values(), key=lambda j: j.created, reverse=True)[:25]]}
        job = _jobs.get(task_id)
        if not job:
            return {"error": "TASK_NOT_FOUND_OR_RESTARTED", "task_id": task_id}
        if action == "cancel" and job.status in ("queued", "running"):
            job.cancelled.set()
            future = job.future
            if future is not None and future.cancel():
                job.status, job.finished = "cancelled", time.time()
        return job.public()
