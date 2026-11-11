"""Experimental stateful MCP client-sampling endpoint (no model API key)."""
import hmac
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations
from pydantic import StrictInt
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse
from starlette.routing import Route
import host_sampling_core as runtime
from request_limits import RateLimitedApp
from inbound_ip_filter import IngressAllowlist

mcp = MCPServer("Omni Host Sampling (Experimental)", version="0.1.0",
    instructions="Sampling needs client support and approval; GPT-6 is a model hint, not a promise.")
READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
SPAWN = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)

@mcp.tool(name="agent", annotations=READ)
async def agent(ctx: Context) -> dict:
    """Check whether the connected MCP client advertises sampling."""
    return runtime.describe(ctx.session)

@mcp.tool(name="spawn_agent", annotations=SPAWN)
async def spawn_agent(prompt: str, ctx: Context, roles: list[str] | None = None,
                      max_tokens: StrictInt = 400, model_hint: str = "gpt-6") -> dict:
    """Request up to three role-specific completions using the client's model.

    Does NOT create native ChatGPT agents. Waits synchronously for sampling.
    Returns HOST_SAMPLING_UNSUPPORTED if the client cannot sample.
    """
    return await runtime.spawn(ctx.session, ctx.request_id, prompt, roles, max_tokens, model_hint)

@mcp.tool(name="task", annotations=READ)
async def task(task_id: str) -> dict:
    """Retrieve a completed sampling record from process memory."""
    return runtime.lookup(task_id)

class BearerAccess:
    def __init__(self, app, token):
        if len(token) < 32:
            raise RuntimeError("Set a random OMNI_AGENT_ACCESS_TOKEN with >=32 characters")
        self.app = app
        self.expected = ("Bearer " + token).encode("utf-8")

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or (scope.get("path") == "/healthz" and scope.get("method") == "GET"):
            return await self.app(scope, receive, send)
        supplied = dict(scope.get("headers", [])).get(b"authorization", b"")
        if not hmac.compare_digest(supplied, self.expected):
            payload = b"Unauthorized"
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"text/plain"), (b"content-length", str(len(payload)).encode())]})
            return await send({"type": "http.response.body", "body": payload})
        return await self.app(scope, receive, send)

host = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip().lower()
if not host:
    raise RuntimeError("RENDER_EXTERNAL_HOSTNAME required")
security = TransportSecuritySettings(
    allowed_hosts=[host, host + ":*"],
    allowed_origins=["https://chatgpt.com", "https://chat.openai.com"],
)
# Only a sessionful MCP connection can deliver 2025-era client sampling replies.
app = mcp.streamable_http_app(stateless_http=False, json_response=True, transport_security=security)
app.router.routes.insert(0, Route("/healthz", lambda req: JSONResponse(
    {"status": "ok", "sampling": "client-required"}), methods=["GET"]))
app = RateLimitedApp(app, requests_per_minute=50, concurrency=6, max_bytes=16384)
app = BearerAccess(app, os.getenv("OMNI_AGENT_ACCESS_TOKEN", ""))
# Application-level CIDR restriction; Render Free does not provide native web-service IP ACLs.
app = IngressAllowlist(app)
