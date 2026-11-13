"""Experimental stateful MCP client-sampling endpoint (no model API key)."""
import os
import sys
from pathlib import Path
from pydantic import AnyHttpUrl
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations
from pydantic import StrictInt
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse
from starlette.routing import Route
import host_sampling_core as runtime
import host_agent_lifecycle as lifecycle
from request_limits import RateLimitedApp
from inbound_ip_filter import IngressAllowlist
from owner_oauth import OwnerOAuthProvider, BASE_URL, MCP_RESOURCE
from oauth_issuer_identification import OAuthIssuerIdentification

# An HTTPS OAuth 2.1 authorization server and protected resource are hosted together.
# ChatGPT cannot send a custom static API key; it must complete authorization code + PKCE.
oauth_provider = OwnerOAuthProvider(os.environ.get("OMNI_AGENT_ACCESS_TOKEN", ""))
auth_settings = AuthSettings(
    issuer_url=AnyHttpUrl(BASE_URL),
    resource_server_url=AnyHttpUrl(MCP_RESOURCE),
    required_scopes=["mcp"],
    client_registration_options=ClientRegistrationOptions(
        enabled=True, valid_scopes=["mcp"], default_scopes=["mcp"]
    ),
    validate_token_resource=True,
)
mcp = MCPServer(
    "Omni Host Sampling (Experimental)", version="0.4.0",
    instructions="OAuth-protected MCP. Five agent-management tools; model inference requires MCP client sampling. These are not native ChatGPT agents.",
    auth=auth_settings, auth_server_provider=oauth_provider,
)
READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
SPAWN = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)

@mcp.tool(name="agent", annotations=READ)
async def agent(ctx: Context) -> dict:
    """Check whether the connected MCP client advertises sampling."""
    return dict(runtime.describe(ctx.session), configuration=lifecycle.configuration())

@mcp.tool(name="spawn_agent", annotations=SPAWN)
async def spawn_agent(prompt: str, ctx: Context, roles: list[str] | None = None,
                      max_tokens: StrictInt = 400, model_hint: str = "gpt-6") -> dict:
    """Request up to three role-specific completions using the client's model.

    Does NOT create native ChatGPT agents. Waits synchronously for sampling.
    Returns HOST_SAMPLING_UNSUPPORTED if the client cannot sample.
    """
    return await lifecycle.spawn_agents(ctx.session, ctx.request_id, prompt, roles, max_tokens, model_hint)


@mcp.tool(name="send_message", annotations=SPAWN)
async def send_message(agent_id: str, message: str, ctx: Context,
                       max_tokens: StrictInt = 400, model_hint: str = "gpt-6") -> dict:
    """Send a follow-up to a subagent's isolated transcript.

    Performs a NEW, synchronous client-sampling request. No native ChatGPT
    agent or background job is created; returns an explicit failure without
    sampling capability.
    """
    return await lifecycle.send_message(ctx.session, ctx.request_id, agent_id,
                                        message, max_tokens, model_hint)


@mcp.tool(name="wait_agent", annotations=READ)
async def wait_agent(agent_id: str, timeout_seconds: StrictInt = 0) -> dict:
    """Read a subagent's latest result; optionally wait up to 20 seconds.

    The model call is synchronous inside spawn_agent/send_message, so this
    typically returns immediately. Records vanish on service restart.
    """
    return await lifecycle.wait_agent(agent_id, timeout_seconds)


@mcp.tool(name="list_agents", annotations=READ)
def list_agents(include_results: bool = False) -> dict:
    """List process-local agent IDs, roles and statuses (max 32 retained)."""
    return lifecycle.list_agents(include_results)


@mcp.tool(name="max_concurrent_subagents", annotations=SPAWN)
def max_concurrent_subagents(limit: StrictInt | None = None) -> dict:
    """Get or set server-side parallel sampling limit (1-3; process-local).

    Does not grant additional model capacity or override ChatGPT limitations.
    """
    return lifecycle.configuration(limit)

@mcp.tool(name="task", annotations=READ)
async def task(task_id: str) -> dict:
    """Retrieve a completed sampling record from process memory."""
    return runtime.lookup(task_id)


host = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip().lower()
if not host:
    raise RuntimeError("RENDER_EXTERNAL_HOSTNAME required")
security = TransportSecuritySettings(
    allowed_hosts=[host, host + ":*"],
    allowed_origins=["https://chatgpt.com", "https://chat.openai.com"],
)
# Only a sessionful MCP connection can deliver 2025-era client sampling replies.
app = mcp.streamable_http_app(stateless_http=False, json_response=True, transport_security=security)
app.router.routes.insert(0, Route(
    "/owner/approve", oauth_provider.approval_page, methods=["GET"]
))
app.router.routes.insert(0, Route(
    "/owner/approve", oauth_provider.approve, methods=["POST"]
))
app.router.routes.insert(0, Route("/healthz", lambda req: JSONResponse(
    {"status": "ok", "sampling": "client-required", "auth": "OAuth2.1",
     "ingress_feed": ingress.feed_status}), methods=["GET"]))
app = RateLimitedApp(app, requests_per_minute=50, concurrency=6, max_bytes=16384)
# OAuth discovery, client registration and the owner login must be PUBLICLY reachable.
# Only /mcp ingress is filtered; MCP's own OAuth middleware verifies access tokens.
ingress = IngressAllowlist(app)
app = ingress
# RFC 9207 caused the live ChatGPT connector to stop before /authorize.
# Compatibility default: use the previously observed callback-ID-specific flow.
# Re-enable only after ChatGPT confirms stable-callback support for this plugin.
if os.getenv("OMNI_OAUTH_RFC9207_ENABLED", "0") == "1":
    app = OAuthIssuerIdentification(app, issuer=BASE_URL)
