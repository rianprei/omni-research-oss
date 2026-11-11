#!/usr/bin/env python3
"""Cloud MCP server: one unified search tool plus five read-only support tools."""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine as e
import unified
from request_limits import RateLimitedApp
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from mcp.server.transport_security import TransportSecuritySettings

mcp = MCPServer(
    "OmniResearch OSS",
    version="1.4.0",
    instructions=(
        "Use omni_research-deep for all public research discovery. "
        "Choose mode=deep for six source categories or select a specific mode. "
        "Fetch and independently verify sources before claiming facts. "
        "A search bundle is not an autonomous subagent and does not synthesize evidence."
    ),
)

def _bounds(v, low, high):
    if isinstance(v, bool) or not isinstance(v, int):
        raise ValueError("Expected integer limit")
    return min(high, max(low, v))

READ = ToolAnnotations(read_only_hint=True, open_world_hint=True, destructive_hint=False)

@mcp.tool(name="omni_research-deep", annotations=READ)
def omni_research_deep(
    query: str,
    mode: str = "deep",
    providers: list[str] | None = None,
    limit: int = 16,
    locale: str = "en-US",
    code_mode: str = "repositories",
    dataset_source: str = "both",
    web_engines: list[str] | None = None,
    academic_sources: list[str] | None = None,
    social_sources: list[str] | None = None,
) -> dict:
    """Search across web, academia, code, communities, news and datasets with one call.

    Modes: deep (all categories), web, academic, code, social, news, datasets,
    technical or trends. Optional providers filters the six categories.
    Advanced filters preserve original per-provider search functionality.
    Returns citations, provenance, source errors and bounded results.
    This is concurrent source retrieval, not independent LLM agents.
    """
    return unified.research(
        query=query,
        mode=mode,
        providers=providers,
        limit=_bounds(limit, 1, 30),
        locale=locale,
        code_mode=code_mode,
        dataset_source=dataset_source,
        web_engines=web_engines,
        academic_sources=academic_sources,
        social_sources=social_sources,
    )

@mcp.tool(annotations=READ)
def fetch_source(url: str, max_chars: int = 16000) -> dict:
    """Fetch public HTTP(S) documents and PDFs with URL and size guards."""
    return e.extract_url(url, _bounds(max_chars, 100, 60000))

@mcp.tool(annotations=READ)
def map_website(url: str, max_pages: int = 6) -> dict:
    """Crawl a bounded number of same-host public pages."""
    return e.crawl_site(url, _bounds(max_pages, 1, 15))

@mcp.tool(annotations=READ)
def compare_evidence(claim: str, urls: list[str]) -> dict:
    """Extract relevant passages from sources without certifying the claim."""
    return e.evidence_compare(claim, urls)

@mcp.tool(annotations=READ)
def citation_lookup(doi: str) -> dict:
    """Resolve a DOI via Crossref and return bibliographic metadata."""
    return e.citation_lookup(doi)

@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False, destructive_hint=False))
def health_check() -> dict:
    """Return public capabilities and sanitized upstream availability metadata."""
    return {
        "status": "ok",
        "mode": "cloud-public",
        "version": "1.4.0",
        "public_tools": 6,
        "search_tool": "omni_research-deep",
        "search_categories": list(unified.SEARCH_PROVIDERS),
        "providers": {
            "web_default": ["wikipedia", "google-news"],
            "web_optional": ["duckduckgo", "bing", "mojeek", "searxng"],
            "social_default": ["hackernews", "stackoverflow"],
            "social_optional": ["reddit"],
            "academic": ["openalex", "crossref", "arxiv", "pubmed"],
            "code_search_token_configured": bool(os.getenv("GITHUB_TOKEN")),
        },
        "notes": (
            "One search tool combines six source categories, not six autonomous agents. "
            "Remote tools are unauthenticated and globally rate limited. "
            "Public provider blocking and incomplete web coverage remain possible."
        ),
    }

hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip().lower()
if not hostname:
    raise RuntimeError("Set RENDER_EXTERNAL_HOSTNAME to deployed Render hostname before startup")
security = TransportSecuritySettings(
    allowed_hosts=[hostname, hostname + ":*"],
    allowed_origins=["https://chatgpt.com", "https://chat.openai.com"],
)
app = mcp.streamable_http_app(stateless_http=True, json_response=True, transport_security=security)
from starlette.routing import Route
from starlette.responses import JSONResponse
app.router.routes.insert(0, Route("/healthz", lambda request: JSONResponse({"status": "ok"}), methods=["GET"]))
app = RateLimitedApp(app, requests_per_minute=120, concurrency=6, max_bytes=32768)
