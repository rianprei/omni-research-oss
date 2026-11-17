# MCP client and platform compatibility

The project has one research codebase but several MCP entry points. Each host must be configured for a transport it supports. A manifest in this repository does not install tools into every app automatically.

## Entry points and tools

| Entry point | Transport | Tools | Model requirements |
|---|---|---:|---|
| `server/main.py` | Local stdio | 9 research tools, including local document and note tools | No model API key; research calls use public providers |
| `server/cloud.py` | Remote Streamable HTTP | 6 read-only research tools | No model inference |
| `server/agent_cloud.py` | Remote Streamable HTTP | 3 agent tools | Requires a configured external OpenAI-compatible provider and bearer token |
| `server/host_sampling_cloud.py` | Remote, stateful Streamable HTTP | 8 experimental agent tools | Legacy client sampling or an explicitly configured provider |

The repository's root `mcp.json` points only to the remote research server. It does not register the local stdio process or either agent service. Keep local file and memory tools on the local entry point; do not expose them from the public research server.

## Host matrix

| Host/surface | Supported connection | Status and limit |
|---|---|---|
| ChatGPT web custom MCP | Public HTTPS MCP endpoint using Streamable HTTP or SSE | Supported after the user connects, installs, and selects the app. A local stdio process is not launched by the web app. |
| ChatGPT Work/Codex session | Tools already connected to that session; Codex can also register MCP servers | A repository `mcp.json` does not make a tool appear in every ChatGPT Work session. |
| Responses API / Agents API | Remote Streamable HTTP or SSE; Secure MCP Tunnel can bridge a private/local server | This is API usage, not a ChatGPT Plus subscription entitlement. |
| Codex CLI / IDE | Local stdio or remote MCP, configured per Codex profile | Use `codex mcp add` or `~/.codex/config.toml`; the CLI and IDE share this configuration. |
| Claude Code | Local stdio or remote HTTP MCP | Configure with `claude mcp add`; use `/mcp` to inspect connection status. |
| Claude Cowork | Remote custom MCP connectors; local MCP for desktop-local execution | Cloud sessions connect to remote services. Local servers require the desktop/local execution path and cannot be assumed available to cloud sessions. |
| OpenCode | Local stdio or remote Streamable HTTP | Configure each server in OpenCode; use `opencode mcp list` to inspect it. |
| Cursor and other MCP clients | Local stdio and/or remote HTTP, depending on the host | Use that client's own configuration format and supported transport. |

## Local installation examples

Use the repository's absolute path. These commands start the research server locally; they do not configure remote agent inference.

```sh
# Codex CLI
codex mcp add omni-research -- python3 "/ABSOLUTE/PATH/omni-research-oss/server/main.py"

# Claude Code
claude mcp add omni-research -- python3 "/ABSOLUTE/PATH/omni-research-oss/server/main.py"

# OpenCode
opencode mcp add omni-research -- python3 "/ABSOLUTE/PATH/omni-research-oss/server/main.py"
```

For Cursor-style JSON configuration:

```json
{
  "mcpServers": {
    "omni-research": {
      "command": "python3",
      "args": ["/ABSOLUTE/PATH/omni-research-oss/server/main.py"]
    }
  }
}
```

On Windows, replace `python3` with the installed Python executable path if needed. On Termux, install Python and configure a client that can launch local stdio processes. Mobile ChatGPT does not launch that process.

## Remote installation

For a host that supports remote MCP, use the deployed HTTPS URL only after checking `/healthz` and confirming `tools/list` returns the expected set. The repository's current `mcp.json` is the research-server profile. Add an agent service separately only after its URL, authentication, provider configuration, and spending controls are ready.

For ChatGPT custom MCP, connect and install the server from ChatGPT on the web, then select it in a conversation. For Claude Cowork cloud sessions, add a remote connector; a localhost URL or local stdio command is not reachable from Anthropic's cloud.

## Agent backend behavior

The research tools do not spawn AI agents. The API-backed `agent_cloud.py` makes separate model-provider requests and can incur provider charges. The `host_sampling_cloud.py` adapter depends on client sampling, which MCP deprecated in protocol revision `2026-07-28`; retain it only as a legacy compatibility path. Neither backend can create native ChatGPT subagents or use a Plus subscription as an API credential. A `model_hint` is a preference, not a model grant.

## Verification

After connecting a server, verify these separately:

1. The host reports the connection as active.
2. `tools/list` matches the intended entry point's inventory.
3. `health_check` succeeds for research, or `agent` reports configured inference for agent tools.
4. Run one low-cost call and inspect the actual returned tool/model status.

A successful local stdio handshake does not prove the remote service is deployed, and a deployed endpoint does not prove that every host has installed or enabled it.
