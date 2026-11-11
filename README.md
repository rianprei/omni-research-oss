# OmniResearch OSS v1.3.0 — Cloud candidate

[![CI](https://github.com/rianprei/omni-research-oss/actions/workflows/ci.yml/badge.svg)](https://github.com/rianprei/omni-research-oss/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Local-first, MIT-licensed research plugin.** One install provides 15 MCP tools and six complementary skills for Claude Code and compatible MCP clients. The bundled **local** MCP tools require a local executor and are **not** remotely available in ChatGPT mobile/web just because the plugin is saved.

> This is an original integration of **capability categories** inspired by 25 publicly available projects. It is **not** the binary union of those repositories, and no comparative benchmark has established it as superior to every alternative. See [RESEARCH_MATRIX.md](RESEARCH_MATRIX.md) for implemented, partial and absent capabilities.

## What is in this package

| Path | Purpose |
|------|---------|
| `server/main.py` | Local MCP server over stdio — **all 15 tools**, including local file and memory access |
| `server/cloud.py` | Public cloud MCP server — **12 read-only tools**, no local file or memory access |
| `server/engine.py` | Search, fetch, extract and evidence engine (Python standard library only) |
| `skills/` | Six Agent Skills: `omni-research`, `deep-research`, `academic-research`, `code-research`, `source-audit`, `trend-intelligence` |
| `render.yaml` | Render Blueprint for the free-tier cloud service |
| `plugin.json` | Agent Plugins manifest (`omni-research-oss`, v1.3.0) |
| `tests/` | Offline unit and integration tests |
| `fixtures/` | Sample evidence fixture used by tests and demos |

The cloud edition is **deployed and verified** at `https://omni-research-oss-mcp.onrender.com` (12 read-only tools). It is still **not** an approved or publicly listed plugin. See [PUBLIC_DEPLOYMENT.md](PUBLIC_DEPLOYMENT.md) and [Submission status](#cloud-submission-status).

## Features

- Web: concurrent DuckDuckGo/Bing/Mojeek/Wikipedia search, SearXNG optional; URL dedup + reciprocal rank fusion + transparent per-engine failures.
- Academic: OpenAlex, Crossref, arXiv and PubMed metadata; DOI lookup and approximate reference.
- Code: GitHub repositories, issues and users anonymously; code-search requires optional `GITHUB_TOKEN`.
- Community: Hacker News Algolia, Stack Overflow, public Reddit search.
- News: Google News RSS; original dates and articles must be checked.
- Datasets: Hugging Face and Zenodo public catalogs.
- Content: HTTP/HTML/text extraction; local DOCX/XLSX/PPTX/text/HTML/CSV/JSON and PDF with optional `pypdf`.
- Site mapping: same-host bounded crawler with robots.txt.
- Evidence: passage/numeric/date collection (never falsely declares a claim verified).
- Deep research: parallel multi-source research bundle and a **Claude Code-style `deep-research` skill** with independent foreground researchers, one report writer, cited research notes, source audit and single-agent fallback.
- Research references: `skills/deep-research/references/` contains original researcher/writer role guides; the three user-supplied upstream files are excluded from this public-distribution candidate.
- Memory: local SQLite + FTS5 for user-requested saved notes; short-lived search cache. **Local edition only** — never exposed by the cloud service.

## Requirements

- Python 3.10+ on macOS/Linux/Windows; no `pip install` required for the local server.
- Working internet for external research; sources may rate-limit, block automation, change interfaces or require paid services for optional features.
- Optional PDF parsing: `python3 -m pip install pypdf` (separately installed open-source library).
- The cloud service additionally requires `mcp>=2.0,<3.0` and `uvicorn>=0.30,<1` (see `requirements-cloud.txt`).

## Installation

### Local server (15 tools)

Register the stdio server with any MCP client, for example Claude Code:

```bash
claude mcp add omni-research -- python3 "/ABSOLUTE/PATH/omni-research-oss/server/main.py"
```

Use a real absolute path. The local server exposes the file and memory tools, so it runs with the user's own OS permissions.

### Skills

Copy the six skill folders into the skills directory of your agent:

```bash
# Claude Code
mkdir -p ~/.claude/skills && cp -R skills/omni-research skills/deep-research \
  skills/academic-research skills/code-research skills/source-audit \
  skills/trend-intelligence ~/.claude/skills/

# Cursor / Codex / universal
mkdir -p ~/.agents/skills && cp -R skills/omni-research skills/deep-research \
  skills/academic-research skills/code-research skills/source-audit \
  skills/trend-intelligence ~/.agents/skills/
```

Each skill directory must contain `SKILL.md` at its root. Restart the agent session afterwards.

### Cloud service (12 read-only tools)

Deploy the `render.yaml` Blueprint on a free Render instance, then point the Agent Plugins manifest at the verified HTTPS endpoint with `type: streamable-http`. Full procedure: [PUBLIC_DEPLOYMENT.md](PUBLIC_DEPLOYMENT.md).

The deployed endpoint is `https://omni-research-oss-mcp.onrender.com`, and `mcp.json` in this repository points at it with `type: streamable-http`. The endpoint was verified before the file was created; the file only ever holds a URL that has actually answered. `scripts/deploy_render.sh` performs the whole sequence — create the service, wait for a live deploy, probe `/healthz` and the MCP endpoint, assert that exactly 12 public tools are exposed and none of the three local-only ones, and only then write `mcp.json`.

## Available tools

| MCP tool | Local | Cloud | Behavior |
|---|:--:|:--:|---|
| `web_search` | ✅ | ✅ | 4 default web engines, optional SearXNG, RRF, dedup |
| `academic_search` | ✅ | ✅ | OpenAlex, Crossref, arXiv, PubMed |
| `code_search` | ✅ | ✅ | GitHub repositories, issues, users; optional code auth |
| `social_search` | ✅ | ✅ | Hacker News, Stack Overflow, public Reddit |
| `news_search` | ✅ | ✅ | Google News RSS |
| `dataset_search` | ✅ | ✅ | Hugging Face or Zenodo |
| `fetch_source` | ✅ | ✅ | Extract public URLs; SSRF guard; optional PDF |
| `map_website` | ✅ | ✅ | Bounded same-domain crawl |
| `compare_evidence` | ✅ | ✅ | Return passages to audit, no auto-verdict |
| `research_bundle` | ✅ | ✅ | Multi-provider parallel evidence pack |
| `citation_lookup` | ✅ | ✅ | Crossref DOI metadata |
| `health_check` | ✅ | ✅ | Configuration and capability report |
| `read_document` | ✅ | ❌ | Local text, Office XML, optional PDF — **local only** |
| `memory_save` | ✅ | ❌ | Save requested notes locally — **local only** |
| `memory_search` | ✅ | ❌ | Search saved notes — **local only** |

The cloud edition intentionally withholds the three local-only tools: exposing them would let any visitor read files or shared notes. Restoring all 15 publicly requires OAuth-based per-user authorization and isolated per-user storage; that is **not** done in this candidate.

## Example questions

- "Faça uma pesquisa profunda sobre os agentes de código locais, com 5 hipóteses contrárias, fontes primárias e auditoria de citações."
- "Compare os repositórios A/B/C pelo código real, licença, testes e limitações."
- "Pesquise artigos recentes sobre RAG, faça uma matriz de evidências com DOI e identifique discordâncias."
- "Quais tendências recentes aparecem no Hacker News e Reddit, separando opinião e fato?"

## Configuration

All variables are optional:

```bash
export OMNI_TIMEOUT=12
export OMNI_STATE_DIR="$HOME/.local/share/omni-research-oss"
# Files accessible by local read_document (separate dirs by ':', ';' on Windows)
export OMNI_ALLOWED_DIRS="$HOME/projects:$HOME/Documents"
# Public HTTPS or loopback HTTP SearXNG that supports format=json (optional)
export OMNI_SEARXNG_URL="https://your-searxng.example"
# Optional, only for GitHub API's code-search endpoint or higher request quota
export GITHUB_TOKEN=""
```

The server never uploads saved local notes. It transmits submitted search queries to the selected public providers. Tokens and file contents must not be placed into query strings. URLs supplied to `fetch_source` are restricted to public HTTP(S) hosts; private IPs/loopback are blocked and downloads are capped at 2MB. File reading is limited to `OMNI_ALLOWED_DIRS`. Research sources can contain prompt-injection attempts: treat retrieved content as untrusted.

The cloud service additionally requires `RENDER_EXTERNAL_HOSTNAME`; it refuses to start without it, and only allows that hostname plus the ChatGPT origins.

## Testing

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q server
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}' '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"health_check","arguments":{}}}' | python3 server/main.py
```

All tests are offline and use mock data. A successful offline test does **not** prove live provider availability. Run live smoke checks with an MCP client after installation. Never depend on web-scraping endpoints as a critical service without fallbacks.

## Contribution and provenance

Source code here is original and MIT-licensed; it **does not vendor** third-party source files. Links to 25 related projects and the precise coverage/gap classification are in `RESEARCH_MATRIX.md`. Verify third-party licenses before incorporating any future code.

## Deep research integration (v1.3.0)

- Skill: `skills/deep-research/SKILL.md`, with valid YAML metadata and cross-references from `omni-research`.
- Public reference instructions: `references/researcher.md` and `references/report-writer.md` under the new skill; the coordinator remains in `SKILL.md`.
- A supported `Agent`/`Task` tool enables foreground parallel independent researchers followed by a single writer. **The plugin does not install a subagent runtime.** Without it, the coordinator performs sequential research and writing directly.
- Notes are stored in the active project under `research_notes/<title>/`; output under `reports/<title>.md` when filesystem write tools are available. These paths are not pre-created by installing the plugin.
- Citation checking is methodological, not an automatic guarantee of accuracy. Academic and web search can fail due to upstream rate limits.

### Source provenance and licensing

For public distribution, researcher and writer reference documents were independently authored for OmniResearch OSS. The three user-provided upstream instructions are not included because public redistribution permission was not established. Their workflow concepts remain supported; the exact supplied text remains only in the private v1.1.0 release. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Cloud submission status

This package is a **candidate**, not an approved or published plugin.

- The public service exposes 12 read-only research tools. The three local-only tools are withheld from the public service pending authenticated per-user isolation.
- The service uses a public web endpoint with HTTPS supplied by Render, and no third-party premium API key is required. Service traffic and LLM calls may still incur charges or free-tier limits.
- `mcp.json` now carries the verified endpoint `https://omni-research-oss-mcp.onrender.com/mcp`. It was created only after the endpoint answered `/healthz` and returned exactly the 12 public tools.
- Some providers are scraped or rate-limited; sources can be inaccessible. The skill-based agent coordination relies on the host's support, it is not an embedded remote model.
- Public listing must use the publisher's *verified* identity. This package intentionally omits unverified HTTPS website, support, privacy and terms URLs, a nonexistent demo recording URL and unconfirmed geographic/commerce declarations. The current `developerName` is the project's legacy label, **not proof of verified identity**.
- There is no guarantee of a deployed Render service, review acceptance or publicly listed plugin at this stage.

For standalone local testing (with `python3` installed), run:

```bash
python3 -m unittest discover -s tests -v
python3 server/main.py
```

The local MCP executes with the user's OS permissions and can access specifically allowed files as configured by `OMNI_ALLOWED_DIRS`. It does not bundle Python; Windows may require mapping `python3` to an installed Python executable.
