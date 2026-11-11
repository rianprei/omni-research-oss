# Host Sampling source-IP allowlist on Render Free

The experimental omni-host-sampling-mcp is on Render's Free compute plan.
Native inbound-IP rules for web services are only available on Scale and Enterprise workspaces:
https://render.com/docs/inbound-ip-rules

Therefore this project implements an application-layer allowlist, not Render-native edge filtering.

Allowed IPv4 CIDRs (and no others):
- 74.220.49.0/24
- 74.220.57.0/24

The service can set OMNI_HOST_SAMPLING_ALLOWED_CIDRS to the comma-separated
CIDRs above via Render environment configuration. When omitted, these exact
two ranges remain the default. An empty or malformed value fails startup.

server/inbound_ip_filter.py examines the single CF-Connecting-IP header forwarded
by the Cloudflare edge in front of Render. Requests without this header,
with duplicate/malformed IPs or from other networks receive HTTP 403.
X-Forwarded-For is deliberately not trusted.
https://render.com/articles/how-render-handles-ddos-attacks

Limitations:
- Requests reach the app before being rejected; this is not a WAF or native Render IP ACL.
- Security relies on Render's ingress forwarding an authentic CF-Connecting-IP.
- If that header is missing, all MCP requests are denied, including legitimate ones.
- GET/HEAD /healthz remains accessible for Render liveness probes and returns no credentials.
- Bearer authorization remains mandatory for allowed IPs.
- ChatGPT may connect from IP addresses outside the two ranges and be blocked.
- The public OmniResearch MCP service remains untouched.
- Real Render-native edge rules require upgrading the workspace or a managed edge proxy.

Tests validate application behavior using synthetic CF-Connecting-IP headers,
not that a real caller's network IP is trusted or covered by these CIDRs.
