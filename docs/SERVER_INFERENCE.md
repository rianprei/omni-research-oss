# Omni Host Sampling: independent server-side inference (v0.6)

The ChatGPT Chat host does not expose a general native subagent-spawn API through custom MCPs. An installed skill is **not** proof that remote MCP tools were registered. The OAuth connection must be authorized and `tools/list` must expose the tools in the active conversation.

## Fallback engine

As of commit `67fb2abe`, `spawn_agent` and `send_message` can call a configured **OpenAI-compatible chat-completions provider directly** when MCP client sampling is unavailable. Multiple independent role prompts are executed concurrently (up to three) and their replies are held temporarily in process memory.

In Render's **omni-host-sampling-mcp** service configure the following environment variables (never put secret values in plugin manifests or source control):

| Variable | Purpose |
| --- | --- |
| `OMNI_INFERENCE_BASE_URL` | HTTPS base URL of an OpenAI-compatible API, typically ending in `/v1` |
| `OMNI_INFERENCE_MODEL` | Model ID supported by that provider |
| `OMNI_INFERENCE_API_KEY` | Secret API credential, if required by the provider |

The implementation uses `POST {base}/chat/completions`, Bearer authentication when a key is configured, role-specific system instructions, and the provider's chosen model ID in responses. HTTPS is required except local loopback URLs. Redirects are not followed to avoid leaking credentials. The server does not return provider response bodies on failed HTTP calls.

These environment variables are intentionally *unset by default*: choosing and paying for a provider is an independent user-controlled decision. ChatGPT Plus does not grant a general server-side API entitlement. For inference on a local or private model service, ensure the Render service has network access and use an authenticated HTTPS gateway.

## Expected outcomes

- Connected MCP client advertises sampling: the legacy client sampling backend is used.
- Client has no sampling, provider configured: independent completions use server-side inference.
- Neither available: `HOST_SAMPLING_UNSUPPORTED`; no agents or model calls are invented.
- Provider HTTP errors: `PROVIDER_HTTP_ERROR` plus status code, without revealing credentials.
- Result records are transient and vanish after Render restarts. No autonomous background agents are created.

A server deployment and OAuth authorization are still mandatory. No version of this server or private plugin can grant missing ChatGPT host capabilities.

Tests: `python -m unittest discover -s tests -p 'test_server_inference_provider.py' -v`
