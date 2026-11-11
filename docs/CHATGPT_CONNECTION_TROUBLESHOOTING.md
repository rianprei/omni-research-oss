# Omni Host Sampling — ChatGPT MCP connection

## Actual failure observed (2026-11-11)

Using @Omni Host Sampling activated the portable skill, but the tool namespace
was missing. The ChatGPT plugin permission status was `not_installed` for its
underlying app, while the plugin package itself was present. This means the
skill is present but the remote MCP connection is not available to the chat.
A model cannot invoke a tool that its host has not supplied.

## First fix: install and authorize the MCP connection

1. Open https://chatgpt.com/plugins/plugins_6af4bc3b0ce0819183dc94f669d0ba25
   on ChatGPT **web** in the same account/workspace.
2. Choose Install/Connect when available and complete the API-key/Bearer
   authorization in the **plugin connection UI**, not in chat text.
3. The token is the service's existing OMNI_AGENT_ACCESS_TOKEN from the
   user-owned Render service. Do not paste it into chat, GitHub, skill files,
   screenshots or public logs. The plugin does not store the token in its ZIP.
4. Confirm that the server tools `agent`, `spawn_agent`, `task` were
   discovered; if ChatGPT shows Refresh, refresh the tool list.
5. Start a **new text conversation** with the connected plugin selected.

The user must perform plugin installation/authorization; adding @ or merely
creating a plugin release does not grant a live MCP connection. Plugin
manifests, skills and server deployments cannot override this.

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
