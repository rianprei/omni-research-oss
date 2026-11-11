# OmniAgents OSS — remote ChatGPT MCP

This service implements exactly three MCP tools: agent, spawn_agent and task.
It does NOT create native GPT-6 ChatGPT subagents. It uses external, potentially
billable, OpenAI-compatible model APIs.

## Architecture

- OmniResearch's public MCP remains unchanged at its original endpoint.
- A separate authenticated Render service runs server.agent_cloud:app.
- Bearer authentication on ALL MCP routes; HTTPS at the public edge.
- Secrets are never embedded in source or the plugin archive.
- Each subagent is a separate one-shot model request, without browser, shell,
  private files, or host ChatGPT tool access.
- At most three concurrent jobs, and a process-local backstop of 30 per day.
- Returns task IDs, status, result, and cooperative cancellation.
- Jobs are in memory and are lost when Render restarts or sleeps.
- Per-process quotas are NOT substitutes for provider spending limits.

## Deploy on Render

Repository: https://github.com/rianprei/omni-research-oss
Branch: main
Runtime: Python
Build command: pip install -r requirements-cloud.txt
Start command: uvicorn server.agent_cloud:app --host 0.0.0.0 --port $PORT
Health endpoint: /healthz
MCP endpoint: /mcp

Required environment:
- OMNI_AGENT_ACCESS_TOKEN: random owner-only Bearer token, 32+ characters.
- OMNI_AGENT_MODEL_KEY: provider API credential.
- OMNI_AGENT_MODEL: permitted, cost-controlled model ID.

Optional:
- OMNI_AGENT_BASE_URL: defaults to https://api.openai.com/v1.
- OMNI_AGENT_TOKEN_PARAMETER: max_completion_tokens (default) or max_tokens.
- OMNI_AGENT_TIMEOUT_SECONDS: 5-75, default 45.

Without the provider key and model, agent and task work, but spawn_agent
returns MODEL_PROVIDER_NOT_CONFIGURED and DOES NOT start model requests.

## ChatGPT plugin connection

Configure MCP Streamable HTTP API-key auth using headerScheme bearer. Enter
the same OMNI_AGENT_ACCESS_TOKEN via ChatGPT's secure Connect flow. Do not
include the token in plugin files or prompts. A ChatGPT subscription is NOT
an OpenAI Platform API key and does not cover independent model usage.

## Tools

- agent(action=list|status): roles, readiness, quotas.
- spawn_agent(prompt, role=general, count=1, max_output_tokens=512,
  idempotency_key=""): starts 1-3 independent model jobs; roles general,
  researcher, critic, coder, synthesizer.
- task(action=list|get|cancel, task_id=""): result/status and cooperative
  cancellation. An active HTTP call might finish after cancel is requested.

These are one-shot specialized model tasks. They do not implement recursive
tool-use, persistent conversations, or native ChatGPT Task/Agent controls.
Provider billing, credentials, networking and instance restarts are independent.
