# Capability matrix: 25 research projects → OmniResearch OSS v1.0.0

**Important:** A row maps an *idea* from the named project to an independently implemented capability, not a claim that the project's plugin, code, dataset or service was imported. No external tool is silently installed. `Partial` means the exact breadth, source integrations or behavior is missing.

| # | External reference | Relevant capability | v1.0.0 coverage |
|---:|---|---|---|
| 1 | [open-webSearch](https://github.com/Aas-ee/open-webSearch) | Multi-engine search, fetch | **Partial:** DDG/Bing/Mojeek/Wikipedia + fetch, not full engine list |
| 2 | [MCP-SearXNG](https://github.com/ihor-sokoliuk/mcp-searxng) | Independent meta-search | **Partial:** optional configured SearXNG JSON endpoint (HTTPS or loopback HTTP) |
| 3 | [DuckDuckGo MCP](https://github.com/nickclyde/duckduckgo-mcp-server) | Web search | **Implemented:** DDG HTML, subject to blocking |
| 4 | [G-Search MCP](https://github.com/jae-jae/g-search-mcp) | Browser Google search | **Not included:** no Google browser automation |
| 5 | [Fetcher MCP](https://github.com/jae-jae/fetcher-mcp) | Page fetch, JS | **Partial:** HTTP HTML/text only; no JS rendering |
| 6 | [Deep-Research-skills](https://github.com/Weizhena/deep-research-skills) | Structured research plans | **Partial:** skill protocol; no dedicated outline editor |
| 7 | [agamarora/deep-research](https://github.com/agamarora/deep-research) | Workers, critic, citation audit | **Partial:** skill orchestrates host agents; no bundled parallel agents |
| 8 | [phyr97/deep-research](https://github.com/phyr97/deep-research) | Evidence research | **Partial:** bundling + agent workflow |
| 9 | [JamesPrial/deep-research](https://github.com/JamesPrial/deep-research) | Research archive | **Partial:** local notes, no full HTML archival |
| 10 | [claude-adaptive-research](https://github.com/primeline-ai/claude-adaptive-research) | Adaptive research | **Partial:** skill stop-when-saturated guideline |
| 11 | [GPTaku insane-research](https://github.com/fivetaku/gptaku_plugins) | Cross-source analysis | **Partial:** skills + `research_bundle` |
| 12 | [GPTaku docs-guide](https://github.com/fivetaku/gptaku_plugins) | Documentation research | **Partial:** bounded site mapper, no semantic docs index |
| 13 | [RivalSearchMCP](https://github.com/damionrashford/RivalSearchMCP) | Web/social/academic/news/code | **Partial:** many categories, fewer providers, no independent source-quality score |
| 14 | [free-search-mcp](https://github.com/sweetcornna/free-search-mcp) | Local-free search, cache, documents | **Partial:** SQLite cache + multi-engine; no Playwright/agent delegation |
| 15 | [Last30Days](https://github.com/mvanhorn/last30days-skill) | Community and recent trends | **Partial:** HN/StackOverflow/Reddit/news; no X/YouTube/TikTok/Polymarket |
| 16 | [hn-mcp](https://github.com/LevNyyon/hn-mcp) | Hacker News | **Implemented:** HN Algolia search |
| 17 | [Athenaeum](https://github.com/huuunleashed/athenaeum-mcp) | Academic meta-search | **Partial:** four sources; no citation graph |
| 18 | [arxiv-mcp-server](https://github.com/blazickjp/arxiv-mcp-server) | arXiv works | **Partial:** search metadata; no full local paper library |
| 19 | [BioMCP](https://github.com/genomoncology/biomcp) | Biomedical search | **Partial:** PubMed only, not clinical genetics/trials |
| 20 | [claude-sciencing](https://github.com/dsatory/claude-sciencing) | Science workflows | **Partial:** methods and bibliography skill, no experiments engine |
| 21 | [research-mcp](https://github.com/hampikamayuq/research-mcp) | Literature and meta-analysis | **Partial:** paper search; no automated statistical meta-analysis |
| 22 | [MCP Fetch](https://github.com/modelcontextprotocol/servers/tree/main/src/fetch) | Retrieve text and HTML | **Implemented:** HTTP(S) HTML/text (with security limits) |
| 23 | [MarkItDown](https://github.com/microsoft/markitdown) | Document conversion | **Partial:** standard Office OpenXML/text, optional PDF, not full formats/OCR |
| 24 | [Playwright MCP](https://github.com/microsoft/playwright-mcp) | Browser rendering/interaction | **Not included:** external browser is optional separate integration |
| 25 | [GitHub MCP](https://github.com/github/github-mcp-server) | GitHub search and repo intelligence | **Partial:** repository/issue/user search, no code search without token, no PR/write operations |

## Structural enhancements in OmniResearch

- One local Python stdlib runtime for 14 read-oriented tools and one note-write tool (rather than multiple servers).
- Explicit failures and provider provenance rather than silently manufactured coverage.
- Source triage that **never** labels claims verified based solely on heuristic text overlap.
- Restriction of file access to approved directories and private-network fetch blocking.
- Reproducible, audited research protocol and offline test fixtures.

## Honest limitations

No end-to-end quality, speed, accuracy or comprehensiveness benchmark against all 25 tools is available. Some linked third-party projects may have changed or been deleted after the list was compiled. This is a **capability convergence** plugin, not a drop-in replacement for every unique feature. Public web sources and GitHub impose limits; the Claude/Codex model may entail subscription usage. Only the original code in this archive is relicensed MIT.

## User-supplied Claude Code Deep Research integration (v1.1.0)

The plugin now includes a sixth skill, `deep-research`, based on three user-provided documents: coordinator (`SKILL.md`), researcher (`researcher.md`), and writer (`report-writer.md`). It coordinates multiagent parallel research when an Agent/Task tool is available; without that tool it falls back to a single-agent research-and-writing workflow. Research notes, BLUF reporting, in-line source citations, gaps, and limited additional research are part of the skill instructions. These are **agent instructions**, not a new independent model or a guarantee that a client supports multiagent execution.


Cloud edition: see PUBLIC_DEPLOYMENT.md; the local/private edition retains full file and memory tools.
