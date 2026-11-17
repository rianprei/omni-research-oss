#!/usr/bin/env python3
"""Minimal MCP stdio JSON-RPC server; no pip dependencies.

Protocol: newline-delimited UTF-8 JSON-RPC, stdout reserved for protocol.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine as e
import unified


def arg(name, description, typ="string", default=None, enum=None):
    prop = {"type": typ, "description": description}
    if enum:
        prop["enum"] = enum
    if default is not None:
        prop["default"] = default
    if typ == "array":
        prop["items"] = {"type": "string"}
    return prop


def tool(name, description, props, required=()):
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": props,
            "required": list(required),
            "additionalProperties": False,
        },
        "annotations": {
            "readOnlyHint": name != "memory_save",
            "destructiveHint": False,
            "openWorldHint": name in {
                "omni_research-deep", "fetch_source", "map_website",
                "compare_evidence", "citation_lookup", "research_bundle",
            },
        },
    }


TOOLS = [
    tool(
        "omni_research-deep",
        "Search all six source categories via one MCP tool; modes deep, web, academic, code, social, news, datasets, technical and trends.",
        {
            "query": arg("query", "Research question"),
            "mode": arg("mode", "Research scope", "string", "deep",
                        ["deep", "web", "academic", "code", "social", "news",
                         "datasets", "technical", "trends"]),
            "providers": arg("providers", "Subset: web, academic, code, social, news, datasets", "array"),
            "limit": arg("limit", "Maximum merged results", "integer", 16),
            "locale": arg("locale", "Locale for news", "string", "en-US"),
            "code_mode": arg("code_mode", "GitHub search type", "string", "repositories",
                             ["repositories", "issues", "users", "code"]),
            "dataset_source": arg("dataset_source", "Dataset catalog", "string", "both",
                                  ["both", "huggingface", "zenodo"]),
            "web_engines": arg("web_engines", "Specific web engines", "array"),
            "academic_sources": arg("academic_sources", "Specific scholarly providers", "array"),
            "social_sources": arg("social_sources", "Specific communities", "array"),
        },
        ["query"],
    ),
    tool("fetch_source", "Extract public HTTP(S) documents and PDFs.",
         {"url": arg("url", "Public URL"),
          "max_chars": arg("max_chars", "Returned text characters", "integer", 16000)}, ["url"]),
    tool("map_website", "Crawl a bounded number of public pages on one host.",
         {"url": arg("url", "Public URL"),
          "max_pages": arg("max_pages", "Pages", "integer", 6)}, ["url"]),
    tool("read_document", "Read local research documents within OMNI_ALLOWED_DIRS.",
         {"path": arg("path", "Local path"),
          "max_chars": arg("max_chars", "Returned characters", "integer", 16000)}, ["path"]),
    tool("compare_evidence", "Collect relevant passages from public URLs.",
         {"claim": arg("claim", "Atomic claim"),
          "urls": arg("urls", "Source URLs", "array")}, ["claim", "urls"]),
    tool("citation_lookup", "Resolve DOI metadata with Crossref.",
         {"doi": arg("doi", "DOI")}, ["doi"]),
    tool("memory_save", "Store local research note.",
         {"topic": arg("topic", "Topic"), "body": arg("body", "Body")}, ["topic", "body"]),
    tool("memory_search", "Search local notes.",
         {"query": arg("query", "Terms"),
          "limit": arg("limit", "Results", "integer", 10)}, ["query"]),
    tool("health_check", "Local provider configuration and status.", {}),
]


class JsonRpcError(Exception):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def bounds(value, lower, upper):
    if type(value) is not int:
        raise ValueError("Expected integer")
    return min(upper, max(lower, value))


def dispatch(name, args):
    if name == "omni_research-deep":
        return unified.research(
            query=args["query"], mode=args.get("mode", "deep"),
            providers=args.get("providers"), limit=bounds(args.get("limit", 16), 1, 30),
            locale=args.get("locale", "en-US"), code_mode=args.get("code_mode", "repositories"),
            dataset_source=args.get("dataset_source", "both"),
            web_engines=args.get("web_engines"), academic_sources=args.get("academic_sources"),
            social_sources=args.get("social_sources"),
        )
    if name == "fetch_source":
        return e.extract_url(args["url"], bounds(args.get("max_chars", 16000), 100, 60000))
    if name == "map_website":
        return e.crawl_site(args["url"], bounds(args.get("max_pages", 6), 1, 15))
    if name == "read_document":
        return e.document_read(args["path"], bounds(args.get("max_chars", 16000), 100, 60000))
    if name == "compare_evidence":
        return e.evidence_compare(args["claim"], args["urls"])
    if name == "citation_lookup":
        return e.citation_lookup(args["doi"])
    if name == "memory_save":
        return e.save_note(args["topic"], args["body"])
    if name == "memory_search":
        return e.search_notes(args["query"], bounds(args.get("limit", 10), 1, 50))
    if name == "health_check":
        return e.health()
    raise ValueError("Tool not found")


def _validate_arguments(tool_definition, arguments):
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be an object")
    schema = tool_definition["inputSchema"]
    properties = schema["properties"]
    extra = set(arguments) - set(properties)
    if extra:
        raise ValueError("Unexpected argument(s): " + ", ".join(sorted(extra)))
    missing = set(schema["required"]) - set(arguments)
    if missing:
        raise ValueError("Missing argument(s): " + ", ".join(sorted(missing)))
    for name, value in arguments.items():
        prop = properties[name]
        expected = prop["type"]
        valid = (
            isinstance(value, str) if expected == "string" else
            type(value) is int if expected == "integer" else
            isinstance(value, list) and all(isinstance(item, str) for item in value)
            if expected == "array" else False
        )
        if not valid:
            raise ValueError(f"{name} must be {expected}")
        if "enum" in prop and value not in prop["enum"]:
            raise ValueError(f"{name} must be one of: {', '.join(prop['enum'])}")


def _tool_error(message):
    return {
        "content": [{"type": "text", "text": message[:500]}],
        "isError": True,
    }


def handle(request):
    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
        raise JsonRpcError(-32600, "Invalid Request")
    method = request.get("method")
    if not isinstance(method, str):
        raise JsonRpcError(-32600, "Invalid Request")

    params = request.get("params", {})
    if method.startswith("notifications/"):
        return None
    if method in {"initialize", "tools/list", "tools/call"} and not isinstance(params, dict):
        raise JsonRpcError(-32602, "Invalid params")

    if method == "initialize":
        offered = params.get("protocolVersion", "2025-06-18")
        supported = ("2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25")
        if not isinstance(offered, str):
            raise JsonRpcError(-32602, "protocolVersion must be a string")
        protocol = offered if offered in supported else "2025-06-18"
        return {
            "protocolVersion": protocol,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "omni-research-oss", "version": "1.4.0"},
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        name = params.get("name")
        if not isinstance(name, str):
            raise JsonRpcError(-32602, "Tool name must be a string")
        arguments = params.get("arguments", {})
        if arguments is None:
            arguments = {}
        definition = next((item for item in TOOLS if item["name"] == name), None)
        if definition is None:
            return _tool_error("Tool not found")
        try:
            _validate_arguments(definition, arguments)
            result = dispatch(name, arguments)
            return {
                "content": [{
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False, default=str),
                }],
                "structuredContent": result,
            }
        except Exception as exc:
            return _tool_error(f"{type(exc).__name__}: {str(exc)}")
    raise JsonRpcError(-32601, "Method not found")


def _response(identifier, result=None, error=None):
    response = {"jsonrpc": "2.0", "id": identifier}
    if error is not None:
        response["error"] = error
    else:
        response["result"] = result
    sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin.buffer:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            _response(None, error={"code": -32700, "message": "Parse error"})
            continue

        if not isinstance(request, dict):
            _response(None, error={"code": -32600, "message": "Invalid Request"})
            continue
        identifier = request.get("id")
        has_id = "id" in request
        if has_id and not (isinstance(identifier, (str, int)) and type(identifier) is not bool):
            _response(None, error={"code": -32600, "message": "Invalid Request"})
            continue

        try:
            result = handle(request)
            if not has_id:
                continue
            _response(identifier, result=result)
        except JsonRpcError as exc:
            if has_id:
                _response(identifier, error={"code": exc.code, "message": str(exc)})
        except Exception:
            if has_id:
                _response(identifier, error={"code": -32603, "message": "Internal error"})


if __name__ == "__main__":
    main()
