"""Optional server-side LLM inference for MCP hosts without client sampling.

Configure OMNI_INFERENCE_BASE_URL (OpenAI-compatible /v1 base),
OMNI_INFERENCE_MODEL and optionally OMNI_INFERENCE_API_KEY in Render.
Never accept provider URL or credentials from MCP tool parameters.
"""
from __future__ import annotations

import asyncio
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_REPLY_BYTES = 1_000_000


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def configured() -> bool:
    return bool(os.getenv("OMNI_INFERENCE_BASE_URL", "").strip()
                and os.getenv("OMNI_INFERENCE_MODEL", "").strip())


def model_name() -> str | None:
    return os.getenv("OMNI_INFERENCE_MODEL", "").strip() or None


def _endpoint() -> str:
    base = os.environ["OMNI_INFERENCE_BASE_URL"].strip().rstrip("/")
    parsed = urlsplit(base)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Invalid provider URL")
    local = parsed.hostname in ("127.0.0.1", "::1", "localhost")
    if not parsed.netloc or not (parsed.scheme == "https" or (parsed.scheme == "http" and local)):
        raise ValueError("Inference endpoint must use HTTPS (except loopback)")
    if base.endswith("/chat/completions"):
        return base
    return base + "/chat/completions"


def _call_provider(prompt: str, instructions: str, max_tokens: int) -> dict:
    model = model_name()
    if not configured() or not model:
        return {"status": "failed", "error": "MODEL_PROVIDER_UNCONFIGURED"}
    try:
        url = _endpoint()
        payload = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": max_tokens,
        }, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        secret = os.getenv("OMNI_INFERENCE_API_KEY", "").strip()
        if secret:
            headers["Authorization"] = "Bearer " + secret
        request = Request(url, data=payload, headers=headers, method="POST")
        with build_opener(_NoRedirect).open(request, timeout=40) as response:
            raw = response.read(MAX_REPLY_BYTES + 1)
        if len(raw) > MAX_REPLY_BYTES:
            return {"status": "failed", "error": "PROVIDER_RESPONSE_TOO_LARGE"}
        data = json.loads(raw)
        choice = data["choices"][0]["message"]["content"]
        if not isinstance(choice, str) or not choice.strip():
            return {"status": "failed", "error": "PROVIDER_EMPTY_RESPONSE"}
        reported = data.get("model")
        return {"status": "completed", "result": choice[:12000],
                "reported_model": reported if isinstance(reported, str) else model,
                "backend": "server_provider"}
    except HTTPError as exc:
        # Intentionally never return response bodies, URL, API key or user prompt.
        return {"status": "failed", "error": "PROVIDER_HTTP_ERROR", "http_status": exc.code}
    except (URLError, TimeoutError, OSError):
        return {"status": "failed", "error": "PROVIDER_CONNECTION_ERROR"}
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        return {"status": "failed", "error": "PROVIDER_RESPONSE_INVALID"}


async def generate(role: str, prompt: str, instructions: str, max_tokens: int) -> dict:
    result = await asyncio.to_thread(_call_provider, prompt, instructions, max_tokens)
    return {"role": role, **result}
