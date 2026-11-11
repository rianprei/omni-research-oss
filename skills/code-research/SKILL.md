---
name: code-research
description: Use to compare open-source repositories, research libraries or frameworks, validate implementation claims, check licenses, and evaluate architectural tradeoffs.
---

# Technical and repository research

Use `code_search` in `repositories` or `issues` mode; optionally use `code` mode only if `GITHUB_TOKEN` is configured. Use `web_search` for docs, advisories and external issue threads. Inspect actual repository files and tagged releases with an authorized GitHub connector or `fetch_source` for public raw files; repository descriptions alone are insufficient.

Score implementations by maintainability and security rather than stars: license, contributor activity, releases, tests and CI, reproducible installation, architecture, dependency health, latency/resource benchmarks with fixed hardware and inputs, failure behavior, compatibility and documentation. Do not label a project "best" without comparable data. Verify version/release dates and distinguish benchmark methodology from marketing.

For a user wanting a unified plugin, construct a **capability matrix** (feature → original idea → current integration → implementation status → verified test → limitation) and avoid copying incompatible licensed code. Respect repository LICENSE/NOTICE and third-party attribution. Require regression and end-to-end MCP tests to claim completion.
