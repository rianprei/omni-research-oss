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
- separate IP allowlist on /mcp, not the public OAuth metadata or consent page

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

This is a **single-owner experimental authorization server** with
in-memory client registrations and tokens. A restart of Render Free may
invalidate an existing connection, requiring a new OAuth authorization.
For production multi-user use a durable identity provider and token store.

## Second fix: ingress allowlist

74.220.49.0/24 and 74.220.57.0/24 are associated with Render hosting, NOT
verified ChatGPT egress. Restricting the MCP exclusively to those networks
can block calls from OpenAI before authentication even begins.

Keep those user-selected CIDRs. Additionally set
`OMNI_HOST_SAMPLING_INCLUDE_OPENAI_EGRESS=1` on the **Host Sampling
service only**. The server fetches and validates the official
`https://openai.com/chatgpt-connectors.json` feed and caches it for one
hour. It will accept connections from those ranges *plus* the two configured
Render CIDRs, while still requiring the existing Bearer credential.
If the feed fails on cold start, OpenAI ranges are not provisioned and
unrecognized IPs fail closed (HTTP 403). The service retries later.

Documented source: https://developers.openai.com/api/docs/guides/ip-addresses

This is an application-layer filter, not a Render-native firewall.
It does not replace authorization. These ranges can change and other
platform infrastructure may use additional IPs.

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
