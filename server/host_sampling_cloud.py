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
    "Omni Host Sampling (Experimental)", version="0.3.0",
    instructions="OAuth-protected MCP. ChatGPT must connect via OAuth. Sampling requires client support.",
    auth=auth_settings, auth_server_provider=oauth_provider,
)
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
# RFC 9207 issuer identification enables ChatGPT's stable OAuth callback.
app = OAuthIssuerIdentification(app, issuer=BASE_URL)
