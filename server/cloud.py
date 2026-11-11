#!/usr/bin/env python3
"""Cloud MCP entrypoint. Public, read-only and stateless.

Never expose local file APIs or the shared SQLite notes database over this endpoint.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import engine as e
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from mcp.server.transport_security import TransportSecuritySettings

mcp=MCPServer('OmniResearch OSS', version='1.3.0', instructions='Research public sources and supply verifiable citations. Search output is not proof of accuracy.')

def _bounds(v, low, high):
    if isinstance(v,bool) or not isinstance(v,int):raise ValueError('Expected integer limit')
    return min(high,max(low,v))

@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True, destructive_hint=False))
def web_search(query: str, engines: list[str] | None = None, limit: int = 12) -> dict:
    """Search public web engines with provenance, ranked results and provider errors."""
    return e.web_search(query,engines,_bounds(limit,1,30))

@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True, destructive_hint=False))
def academic_search(query: str, sources: list[str] | None = None, limit: int = 8) -> dict:
    """Find scientific works via OpenAlex, Crossref, arXiv and PubMed."""
    return e.academic_search(query,sources,_bounds(limit,1,25))

@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True, destructive_hint=False))
def code_search(query: str, mode: str = 'repositories', limit: int = 10) -> dict:
    """Search public GitHub repositories, issues, users, or indexed code when authorized."""
    return e.code_search(query,mode,_bounds(limit,1,30))

@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True, destructive_hint=False))
def social_search(query: str, sources: list[str] | None = None, limit: int = 8) -> dict:
    """Search public Hacker News, Stack Overflow and Reddit discussions."""
    return e.social_search(query,sources,_bounds(limit,1,30))

@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True, destructive_hint=False))
def news_search(query: str, limit: int = 12, locale: str = 'en-US') -> dict:
    """Search public news feeds; publisher timestamps require independent verification."""
    return e.news_search(query,_bounds(limit,1,30),locale)

@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True, destructive_hint=False))
def dataset_search(query: str, source: str = 'huggingface', limit: int = 10) -> dict:
    """Discover public datasets on Hugging Face or Zenodo."""
    return e.dataset_search(query,source,_bounds(limit,1,25))

@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True, destructive_hint=False))
def fetch_source(url: str, max_chars: int = 16000) -> dict:
    """Fetch public HTTP(S) documents with URL restrictions and response size limits."""
    return e.extract_url(url,_bounds(max_chars,100,60000))

@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True, destructive_hint=False))
def map_website(url: str, max_pages: int = 6) -> dict:
    """Crawl a bounded number of pages on the same public host."""
    return e.crawl_site(url,_bounds(max_pages,1,15))

@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True, destructive_hint=False))
def compare_evidence(claim: str, urls: list[str]) -> dict:
    """Collect source passages relevant to a claim; no automatic truth verdict."""
    return e.evidence_compare(claim,urls)

@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True, destructive_hint=False))
def research_bundle(topic: str, mode: str = 'general', max_results: int = 16) -> dict:
    """Collect parallel evidence from multiple public providers with traceable citations."""
    return e.deep_research(topic,mode,_bounds(max_results,1,30))

@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True, destructive_hint=False))
def citation_lookup(doi: str) -> dict:
    """Resolve a DOI through Crossref and return bibliographic metadata."""
    return e.citation_lookup(doi)

@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False, destructive_hint=False))
def health_check() -> dict:
    """Report provider configuration and public API availability, not internal secrets."""
    data=e.health()
    # Prevent inadvertently displaying credentials, filesystem paths, user identifiers.
    return {'status':'ok','mode':'cloud-public','public_tools':12,'providers':data.get('providers',{}) if isinstance(data,dict) else {}}

# DNS rebinding protection: allow only the deployed hostname, no wildcard domains.
hostname=os.environ.get('RENDER_EXTERNAL_HOSTNAME','').strip().lower()
if not hostname:
    raise RuntimeError('Set RENDER_EXTERNAL_HOSTNAME to deployed Render hostname before startup')
security=TransportSecuritySettings(
    allowed_hosts=[hostname,hostname+':*'],
    allowed_origins=['https://chatgpt.com','https://chat.openai.com'],
)
app=mcp.streamable_http_app(stateless_http=True,json_response=True,transport_security=security)
from starlette.routing import Route
from starlette.responses import JSONResponse
app.router.routes.insert(0,Route('/healthz',lambda request: JSONResponse({'status':'ok'}),methods=['GET']))

