# OmniResearch OSS deployment and client setup

This document describes the repository's deployment profiles. It does not claim that a service is currently live or connected to a client.

## Profiles

| Profile | Entrypoint | Transport | Tools |
|---|---|---|---:|
| Local research | `server/main.py` | stdio | 9 |
| Public research | `server/cloud.py` | Streamable HTTP | 6 read-only |
| API-backed agents | `server/agent_cloud.py` via `render-agents.yaml` | Authenticated Streamable HTTP | 3 |
| Host sampling experiment | `server/host_sampling_cloud.py` | OAuth-protected, stateful Streamable HTTP | 8 |

The root `mcp.json` configures only the public research profile. The agent services are separate and are not included by that file. Local document and memory tools must stay on the local entry point.

## Public research service

The configured URL in `mcp.json` is:

```
https://omni-research-oss-mcp.onrender.com/mcp
```

Before connecting a client or submitting a plugin, deploy from `render.yaml` and verify the actual service hostname:

```sh
HOST=omni-research-oss-mcp.onrender.com
curl -fsS "https://$HOST/healthz"
```

Then issue MCP `initialize` and `tools/list` over Streamable HTTP. The expected public tool names are:

```text
omni_research-deep
fetch_source
map_website
compare_evidence
citation_lookup
health_check
```

The local-only tools `read_document`, `memory_save`, and `memory_search` must not appear on the public endpoint.

## API-backed agent service

`render-agents.yaml` deploys `server.agent_cloud:app` as a separate service. It requires a private bearer token and an external OpenAI-compatible provider configuration. Provider calls are separate from ChatGPT Plus usage and may incur charges. Do not publish the endpoint in a manifest until deployment, authentication, `tools/list`, and provider readiness have been checked.

## Host sampling experiment

`server.host_sampling_cloud:app` is a separate experimental adapter. It requires OAuth configuration and a client that actually supports the legacy sampling capability, unless an external provider is configured. MCP deprecated sampling in revision `2026-07-28`; new deployments should use a provider-backed design instead. This service does not create native ChatGPT agents.

## Client installation

Use [CLIENT_COMPATIBILITY.md](docs/CLIENT_COMPATIBILITY.md) for setup instructions for ChatGPT web, Codex, Claude Code, Claude Cowork, OpenCode, Cursor, and local stdio clients. The same package cannot launch itself inside every host: each client requires its own connection setup.

## Validation and CI

The standard CI runs offline unit and contract tests plus a local stdio handshake. The remote smoke workflow checks the live research endpoint's health and its exact six-tool inventory. A green offline CI run does not prove that a Render service is live or that an app has installed it.
