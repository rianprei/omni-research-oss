# OmniResearch OSS public cloud candidate

This is a candidate, **not a published or connected ChatGPT plugin**.

## Deploy

1. Place this project in a Git repository the Render account can access.
2. Deploy the `render.yaml` Blueprint on a **free** instance or create a Python web service with its build and start commands.
3. Confirm `RENDER_EXTERNAL_HOSTNAME` and verify `/mcp` using a compatible MCP client.
4. Add the **verified** HTTPS endpoint to a separate submission copy of `mcp.json` using `type: streamable-http`.
5. Confirm OAuth/authentication policy with the OpenAI Developer Portal, complete required listing URLs, verification, evidence, demo and review cases, then submit for approval. Public listing is never automatic.

## Security and functionality

- The public server offers 12 research-related read-only tools. Original local-only `read_document`, `memory_save`, and `memory_search` are **not** exposed across public sessions.
- This prevents untrusted users reading local files or shared notes; to restore all 15 tools publicly, add OAuth-based per-user authorization and isolated persistent storage. This is not done in this candidate.
- The cloud service uses a public web endpoint, HTTPS supplied by Render, no third-party premium API key required. Service traffic and LLM calls may still incur charges or free-tier limits.
- `mcp.json` is deliberately absent because no endpoint has been deployed and verified. Do not publish with an invented URL.
- Some providers are scraped or rate-limited; sources can be inaccessible. The skill-based agent coordination relies on the host's support, it is not an embedded remote model.
- No guarantee of a deployed Render service, review acceptance or publicly listed plugin at this stage.
