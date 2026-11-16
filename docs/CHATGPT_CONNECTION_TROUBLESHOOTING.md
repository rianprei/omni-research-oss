# Omni Host Sampling — ChatGPT MCP connection

## Actual failure observed (2026-11-11)

Using @Omni Host Sampling activated the portable skill, but the tool namespace
was missing. The ChatGPT plugin permission status was `not_installed` for its
underlying app, while the plugin package itself was present. This means the
skill is present but the remote MCP connection is not available to the chat.
A model cannot invoke a tool that its host has not supplied.

## Owner-approved OAuth 2.1 — fixed auth negotiation

**Previous blocker:** The remote app required a custom static `Authorization: Bearer`
API key and returned 401 to every ChatGPT MCP discovery request, including
OAuth well-known metadata. ChatGPT's hosted MCP integration cannot supply
custom API keys. Its OAuth discovery attempts therefore all failed.

The Host Sampling server now uses the official MCP Python SDK's
OAuth 2.1 authorization server integration with:
- RFC 9728 protected resource metadata, public OAuth metadata and DCR
- PKCE S256 authorization-code flow
- a small, owner-only HTTPS login page at /owner/approve
- OAuth bearer access tokens on every /mcp request
- strict chatgpt.com callback allowlisting, audience and scope validation
- optional IP allowlist on /mcp (disabled by default in source after 2026-11-16); OAuth remains mandatory

**To connect:**

1. Open ChatGPT Plugins on the web and choose Add custom MCP server.
2. Enter https://omni-host-sampling-mcp.onrender.com/mcp.
3. Select **OAuth**, not API key and not No Authentication.
4. Select **Dynamic Client Registration (DCR)** when offered.
5. When the login page opens at the HTTPS Render domain, enter the
   original OMNI_AGENT_ACCESS_TOKEN in the hosted login form
   (NOT in ChatGPT text). This step approves ChatGPT to use the MCP server.
6. Complete Create as plugin and Install; then select the connected MCP
   plugin in a fresh conversation and inspect tools/list.

The login uses the existing server-side owner key only to verify consent.
The key is not given to ChatGPT; ChatGPT obtains a distinct OAuth token.

This is a **single-owner experimental authorization server**. Signed OAuth client IDs and access/refresh tokens can survive Render restarts when the owner secret remains unchanged. Pending approvals, one-time authorization codes and revocation state remain process-local, so a restart during login may require a fresh authorization. For multi-user production use a durable identity provider and token store.

## Second fix: ingress allowlist (2026-11-16)

Render app logs on 2026-11-13 showed **POST /mcp -> 403**, while OAuth
metadata, DCR and earlier 401 challenges were functioning. The source-IP
allowlist checked a `cf-connecting-ip` header and accepted only configured
Render CIDRs; ChatGPT's changing egress addresses are not guaranteed to match.

Commit `6d7e666` changed the Host Sampling app so the IP filter is **opt-in**:
`OMNI_HOST_SAMPLING_ENFORCE_IP_ALLOWLIST=1`. Default leaves the IP filter
off. **OAuth 2.1 access tokens remain required for /mcp**, with existing
rate and request-size limits. Do not add an unauthenticated MCP bypass.

If the optional IP filter is intentionally enabled, populate
`OMNI_HOST_SAMPLING_ALLOWED_CIDRS` with verified network ranges and optionally
`OMNI_HOST_SAMPLING_INCLUDE_OPENAI_EGRESS=1`. Those ranges can change, and a
missing proxy-provided IP header may still reject valid traffic. Prefer OAuth
as the principal access control. /healthz reports `ip_allowlist_enforced`.

**Important:** source changes take effect only after Render has deployed the
updated commit. A plugin package alone does not update the remote service.

## Third issue: host sampling capability

Even a connected MCP client may not expose the legacy
`sampling/createMessage` protocol capability. On such a client,
`agent` should show `client_sampling_declared=false`, and
`spawn_agent` will return `HOST_SAMPLING_UNSUPPORTED` and zero
model invocations. A model hint `gpt-6` is never a model grant.
MCP sampling was deprecated in the July 2026 protocol revision.

For external independent GPT-6 inference via **ChatGPT plan usage**,
OpenAI documents a separate Sign in with ChatGPT OAuth process for eligible
open-source, locally hosted tools. It is not a ChatGPT MCP sampling
feature and cannot be silently borrowed from the current chat. Hosted
commercial/remote apps require the corresponding OpenAI eligibility path.
See https://developers.openai.com/siwc/token-sharing-open-source

## Successful test criteria

- Plugin connection shown as authorized/available in current account.
- MCP `tools/list` returns `agent`, `spawn_agent`, and `task`.
- `agent` actually runs through the remote MCP server.
- Client sampling capability is explicitly reported.
- Only then attempt `spawn_agent` and verify reported model and output.

**No real GPT-6 subagent run has been validated in ChatGPT.**
