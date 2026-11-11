# OmniResearch OSS v1.2.0 Desktop-only candidate

**Local-first, MIT-licensed research plugin.** One install provides 15 MCP tools and six complementary skills for Claude Code and compatible MCP clients. A portable Agent Plugins package also allows its research *skills* to be saved to ChatGPT/Codex. The bundled **local** MCP tools require a local executor and are **not** remotely available in ChatGPT mobile/web just because the plugin is saved.

> This is an original integration of **capability categories** inspired by 25 publicly available projects. It is **not** the binary union of those repositories, and no comparative benchmark has established it as superior to every alternative. See [RESEARCH_MATRIX.md](RESEARCH_MATRIX.md) for implemented, partial and absent capabilities.

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
- Memory: local SQLite + FTS5 for user-requested saved notes; short-lived search cache.

## Requirements

- Python 3.10+ on macOS/Linux/Windows; no `pip install` required for core features.
- Working internet for external research; sources may rate-limit, block automation, change interfaces or require paid services for optional features.
- Optional PDF parsing: `python3 -m pip install pypdf` (separately installed open-source library).

## Claude Code installation (from the downloaded directory)

```bash
unzip omni-research-oss.zip
claude plugin marketplace add "$(pwd)/omni-research-oss"
claude plugin install omni-research-oss@omni-research-marketplace --scope user
```

Restart Claude Code if tools are not immediately discovered. Run `/omni-research-oss:deep-research` for the new multiagent report workflow, or `/omni-research-oss:omni-research` for general research. Run (or ask to use the OmniResearch research skill) then request `health_check` to test server discovery.

**Manual MCP fallback**, from any folder with the extracted directory:

```bash
claude mcp add omni-research -- python3 "/ABSOLUTE/PATH/omni-research-oss/server/main.py"
```

Use a real absolute path; this alternative registers the server without the five plugin skills. The `plugin.json`/`mcp.json` format works with compatible local plugin hosts; `.claude-plugin/` and `.mcp.json` provide Claude Code compatibility.

## Available tools

| MCP tool | Behavior |
|---|---|
| `web_search` | 4 default web engines, optional SearXNG, RRF, dedup |
| `academic_search` | OpenAlex, Crossref, arXiv, PubMed |
| `code_search` | GitHub repositories, issues, users; optional code auth |
| `social_search` | Hacker News, Stack Overflow, public Reddit |
| `news_search` | Google News RSS |
| `dataset_search` | Hugging Face or Zenodo |
| `fetch_source` | Extract public URLs; SSRF guard; optional PDF |
| `map_website` | Bounded same-domain crawl |
| `read_document` | Local text, Office XML, optional PDF |
| `compare_evidence` | Return passages to audit, no auto-verdict |
| `research_bundle` | Multi-provider parallel evidence pack |
| `citation_lookup` | Crossref DOI metadata |
| `memory_save` | Save requested notes locally |
| `memory_search` | Search saved notes |
| `health_check` | Configuration and capability report |

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

## Testing

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q server
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}' '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"health_check","arguments":{}}}' | python3 server/main.py
```

All tests are offline and use mock data. A successful offline test does **not** prove live provider availability. Run live smoke checks with an MCP client after installation. Never depend on web-scraping endpoints as a critical service without fallbacks.

## Contribution and provenance

Source code here is original and MIT-licensed; it **does not vendor** third-party source files. Links to 25 related projects and the precise coverage/gap classification are in `RESEARCH_MATRIX.md`. Verify third-party licenses before incorporating any future code.

## Deep research integration (v1.1.0)

- New skill: `skills/deep-research/SKILL.md`, with valid YAML metadata and cross-references from `omni-research`.
- Public reference instructions: `references/researcher.md` and `references/report-writer.md` under the new skill; the coordinator remains in `SKILL.md`.
- A supported `Agent`/`Task` tool enables foreground parallel independent researchers followed by a single writer. **The plugin does not install a subagent runtime.** Without it, the coordinator performs sequential research and writing directly.
- Notes are stored in the active project under `research_notes/<title>/`; output under `reports/<title>.md` when filesystem write tools are available. These paths are not pre-created by installing the plugin.
- Citation checking is methodological, not an automatic guarantee of accuracy. Academic and web search can fail due to upstream rate limits.

### Source provenance and licensing

For public distribution, researcher and writer reference documents were independently authored for OmniResearch OSS. The three user-provided upstream instructions are not included because public redistribution permission was not established. Their workflow concepts remain supported; the exact supplied text remains only in the private v1.1.0 release.

## Desktop-only directory submission status

This package is a **candidate**, not an approved or published plugin. OpenAI's
Desktop-only local MCP submission route is restricted to approved partners whose
submission organization is allowlisted. Do not submit under Skills only before
OpenAI confirms local-MCP eligibility. Keep all 15 stdio MCP tools packaged; do
not silently remove `mcp.json` if a portal warning excludes local MCP.

Public listing must use the publisher's *verified* identity. This ZIP intentionally
omits unverified HTTPS website, support, privacy and terms URLs, a nonexistent
demo recording URL and unconfirmed geographic/commerce declarations. The current
`developerName` is the project's legacy label, **not proof of verified identity**.
See `SUBMISSION_READINESS.md` outside the ZIP for requirements.

For standalone desktop testing (with `python3` installed), run:

```bash
python3 -m unittest discover -s tests -v
python3 server/main.py
```

The local MCP executes with the user's OS permissions and can access specifically
allowed files as configured by `OMNI_ALLOWED_DIRS`. It does not bundle Python;
Windows may require mapping `python3` to an installed Python executable.


Cloud edition: see PUBLIC_DEPLOYMENT.md; the local/private edition retains full file and memory tools.
