# MCP host sampling adapter (experimental, no API key in the server)

The experimental agent tool implementation is in:
- `server/host_sampling_core.py` (sampling and result validation)
- `server/host_sampling_cloud.py` (authenticated stateful MCP endpoint)
- `tests/test_host_sampling_core.py` (mocked MCP sampling tests)

The MCP server advertises three tools: `agent`, `spawn_agent`, `task`.

## How it works

A client that **explicitly declares the MCP sampling capability** can respond
to `sampling/createMessage` requests. The server asks for one to three
independent role-specific completions while the original `spawn_agent` call
remains in flight. The client chooses its actual model. A `gpt-6` hint is
not guaranteed and is not a way to take over internal ChatGPT sessions.

If the client does not support sampling, `spawn_agent` returns the explicit
`HOST_SAMPLING_UNSUPPORTED` result and performs zero LLM calls.

This architecture uses no model API key in the MCP server, but any hosting
client may still impose approvals, usage limits, or its own inference costs.

## Critical limitations

1. **There is no verified ChatGPT sampling support.** This adapter is not an
   API for ChatGPT to launch native GPT-6 subagents. It cannot alter its host.
2. **The MCP sampling feature was deprecated in MCP protocol 2026-07-28.**
   The server uses the 2025-era server-to-client request mechanism and
   sessionful Streamable HTTP. New hosts need their own explicit support.
3. A running `spawn_agent` tool waits for model responses. There are no
   persistent independent ChatGPT conversations or durable background agents.
4. Role prompts may be answered by the same model serially if the client
   chooses to serialize sampling. True concurrency depends on the host.
5. The cache is process-local and single-owner. This is not multi-tenant or
   production-scale task orchestration.
6. No public Render deployment or ChatGPT plugin connection has been
   validated. Existing OmniResearch and API-backed OmniAgents remain intact.

## Opt-in isolated deployment

Use the existing repository's Python dependencies and launch:

```sh
uvicorn server.host_sampling_cloud:app --host 0.0.0.0 --port 8000
```

Set `RENDER_EXTERNAL_HOSTNAME` and a random, private
`OMNI_AGENT_ACCESS_TOKEN` (minimum 32 characters) on the server.
The new endpoint must be deployed **separately** from the existing public
research MCP. Do not put bearer tokens in GitHub or chat. A client must
support sampling and complete any required approval.

The test suite checks SDK capability handling and mocked client responses,
not GPT-6 inference. Official reference:
https://modelcontextprotocol.io/specification/2025-11-25/client/sampling
