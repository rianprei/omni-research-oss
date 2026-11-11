#!/usr/bin/env python3
"""Authenticated remote MCP for *external* LLM subagents, never host ChatGPT clones.

Run separately from the free public research server. Never expose model
credentials or cost-incurring tools through the anonymous research endpoint.
"""
from __future__ import annotations

import hmac
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pydantic import StrictInt
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse
from starlette.routing import Route

import agent_runtime as runtime
from request_limits import RateLimitedApp

service = MCPServer(
    "OmniAgents OSS",
    version="0.1.0",
    instructions=(
        "Three external subagent tools: agent, spawn_agent, task. "
        "This server does NOT have access to the hosting ChatGPT model, "
        "subscription, internal tools or conversation history. "
        "Spawned tasks use separate OpenAI-compatible model API calls "
        "only when the provider is configured, with independent billing. "
        "Tasks are ephemeral and can be lost when Render sleeps or restarts."
    ),
)
READ = ToolAnnotations(read_only_hint=True, open_world_hint=False, destructive_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, open_world_hint=True, destructive_hint=False)


@service.tool(name="agent", annotations=READ)
def agent(action: str = "list") -> dict:
    """List subagent roles, model-provider readiness, and runtime limits.

    This does not create a native ChatGPT agent or start inference.
    """
    return runtime.agent(action)


@service.tool(name="spawn_agent", annotations=WRITE)
def spawn_agent(
    prompt: str,
    role: str = "general",
    count: StrictInt = 1,
    max_output_tokens: StrictInt = 512,
    idempotency_key: str = "",
) -> dict:
    """Start 1-3 independent, isolated one-shot model tasks concurrently.

    Roles: general, researcher, critic, coder, synthesizer. Each task
    performs one external model inference; agents cannot call ChatGPT
    internal tools or use filesystem/shell. Requires a provider API key
    configured on the service. Returns task IDs for polling with task.
    """
    return runtime.spawn_agent(
        prompt=prompt, role=role, count=count,
        max_output_tokens=max_output_tokens,
        idempotency_key=idempotency_key,
    )


@service.tool(name="task", annotations=WRITE)
def task(action: str = "list", task_id: str = "") -> dict:
    """List, read, or cooperatively cancel spawned subagent tasks.

    action: list, get, cancel. Running HTTP requests cannot be interrupted
    immediately. Results are lost if the server restarts.
    """
    return runtime.task(action=action, task_id=task_id)


class BearerAccess:
    def __init__(self, app, secret: str):
        if len(secret) < 32:
            raise RuntimeError("OMNI_AGENT_ACCESS_TOKEN must have >=32 characters")
        self.app = app
        self.secret = ("Bearer " + secret).encode("utf-8")

    async def _reject(self, send):
        body = b"Unauthorized; configure the OmniAgents plugin connection"
        await send({"type": "http.response.start", "status": 401,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8"),
                                (b"content-length", str(len(body)).encode()),
                                (b"www-authenticate", b'Bearer realm="OmniAgents"')]})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        if scope.get("path") == "/healthz" and scope.get("method") in ("GET", "HEAD"):
            return await self.app(scope, receive, send)
        token = dict(scope.get("headers", [])).get(b"authorization", b"")
        if not hmac.compare_digest(token, self.secret):
            return await self._reject(send)
        return await self.app(scope, receive, send)


hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip().lower()
if not hostname:
    raise RuntimeError("RENDER_EXTERNAL_HOSTNAME must be configured")
secret = os.environ.get("OMNI_AGENT_ACCESS_TOKEN", "")
security = TransportSecuritySettings(
    allowed_hosts=[hostname, hostname + ":*"],
    allowed_origins=["https://chatgpt.com", "https://chat.openai.com"],
)
app = service.streamable_http_app(stateless_http=True, json_response=True, transport_security=security)
app.router.routes.insert(0, Route(
    "/healthz", lambda request: JSONResponse(
        {"status": "ok", "service": "omni-agents", "version": "0.1.0",
         "provider_configured": runtime.provider_status()["configured"]}
    ), methods=["GET"],
))
app = RateLimitedApp(app, requests_per_minute=60, concurrency=8, max_bytes=16384)
app = BearerAccess(app, secret)
