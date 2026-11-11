# OmniResearch OSS public cloud candidate

This is a candidate, **not a published or connected ChatGPT plugin**.

## Live endpoint

The service is deployed and verified:

| Item | Value |
|------|-------|
| Host | `omni-research-oss-mcp.onrender.com` |
| Health | `https://omni-research-oss-mcp.onrender.com/healthz` → `{"status":"ok"}` |
| MCP | `https://omni-research-oss-mcp.onrender.com/mcp` (`streamable-http`) |
| Server | `OmniResearch OSS` v1.3.0, protocol `2025-06-18` |
| Tools | exactly the 12 public ones; `read_document`, `memory_save` and `memory_search` are **not** exposed |

The remote smoke test in `.github/workflows/remote-smoke.yml` re-checks the health route, the MCP handshake and the full tool inventory against the live endpoint on every change to that workflow. Free-tier instances sleep after inactivity, so the first request after a quiet period is slow; that is a plan limitation, not a service fault.

The source is published at **<https://github.com/rianprei/omni-research-oss>** (branch `main`).
The `render.yaml` Blueprint in this repository is the deployment definition.

## Deploy

1. **Connect the repository.** In the Render dashboard, choose *New → Blueprint*, connect the GitHub account that owns `rianprei/omni-research-oss`, and select the repository. Render reads `render.yaml` from the root of the default branch.
2. **Apply the Blueprint.** Keep the generated service name, the `free` plan, and the region closest to the users. Render builds with `pip install -r requirements-cloud.txt` and starts with `uvicorn server.cloud:app --host 0.0.0.0 --port $PORT`.
3. **Confirm the hostname.** Render sets `RENDER_EXTERNAL_HOSTNAME` automatically. The service refuses to start without it, and the transport security layer only accepts that hostname plus the ChatGPT origins. Note the public hostname, for example `omni-research-oss-mcp.onrender.com`.
4. **Verify the endpoint.** Both checks must pass before anything is published:

   ```bash
   HOST=omni-research-oss-mcp.onrender.com

   # health check route
   curl -fsS "https://$HOST/healthz"

   # MCP initialize over streamable HTTP
   curl -fsS "https://$HOST/mcp" \
     -H 'Content-Type: application/json' \
     -H 'Accept: application/json, text/event-stream' \
     -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"probe","version":"1"}}}'
   ```

   `tools/list` must return exactly the **12** public tools. `read_document`, `memory_save` and `memory_search` must be absent.
5. **Add the verified endpoint to the submission copy of `mcp.json`** using `type: streamable-http` and the real hostname. `mcp.json` must only ever hold a URL that has actually answered — `scripts/deploy_render.sh` writes it as its last step, after the probes pass.
6. **Submit.** Confirm the OAuth/authentication policy with the OpenAI Developer Portal, complete the required listing URLs, identity verification, evidence, demo and review cases, then submit for approval. Public listing is never automatic.

### Render API alternative

If the Render account has an API key (`https://api.render.com`), the same Blueprint can be applied without the dashboard:

```bash
export RENDER_API_KEY=...        # never commit this
curl -sS -X POST https://api.render.com/v1/services \
  -H "Authorization: Bearer $RENDER_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"service": {"name":"omni-research-oss-mcp","repo":"https://github.com/rianprei/omni-research-oss","branch":"main","runtime":"python","plan":"free","buildCommand":"pip install -r requirements-cloud.txt","startCommand":"uvicorn server.cloud:app --host 0.0.0.0 --port $PORT","healthCheckPath":"/healthz","autoDeploy":true}}'
```

Free instances sleep after inactivity and the first request after a sleep is slow. This is a free-tier limitation, not a service fault.

## Security and functionality

- The public server offers 12 research-related read-only tools. Original local-only `read_document`, `memory_save`, and `memory_search` are **not** exposed across public sessions.
- This prevents untrusted users reading local files or shared notes; to restore all 15 tools publicly, add OAuth-based per-user authorization and isolated persistent storage. This is not done in this candidate.
- The cloud service uses a public web endpoint, HTTPS supplied by Render, no third-party premium API key required. Service traffic and LLM calls may still incur charges or free-tier limits.
- `mcp.json` carries the verified endpoint. It was written only after the endpoint answered; do not replace it with an invented URL.
- Some providers are scraped or rate-limited; sources can be inaccessible. The skill-based agent coordination relies on the host's support, it is not an embedded remote model.
- No guarantee of a deployed Render service, review acceptance or publicly listed plugin at this stage.

## Pre-deploy verification already performed

The repository CI (`.github/workflows/ci.yml`) runs on every push and pull request and must be green before deploying:

- byte-compile of `server/`;
- the offline unit and integration suite (`python3 -m unittest discover -s tests`);
- an MCP stdio smoke test over `initialize`, `tools/list` and `health_check`;
- an import check of `server.cloud` against the real `requirements-cloud.txt`, with `RENDER_EXTERNAL_HOSTNAME` set.

The import check is the one that matters for the deployment: it proves the pinned `mcp` SDK exposes `MCPServer`, `TransportSecuritySettings` and `streamable_http_app` with the signatures the entrypoint uses.
